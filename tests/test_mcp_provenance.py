"""Tests for MCP caller provenance in the audit trail.

Verifies that MCP-originated operations produce audit events with
interface/caller provenance metadata, while normal operations remain
unchanged.
"""

import json

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.audit.logger import AuditLogger
from app.audit.provenance import Interface, clear_call_context, get_call_context, set_call_context
from app.main import app
from app.mcp import create_mcp_server
from app.memory.database import Database
from app.memory.store import WorkflowMemory
from app.models.domain import OnboardingApplication
from app.models.states import EventType, WorkflowState
from app.worker.engine import WorkerEngine

AUTH_HEADERS = {"X-API-Key": "test-secret-key-12345"}


@pytest.fixture(scope="module")
def mcp_server():
    return create_mcp_server()


@pytest_asyncio.fixture
async def db(tmp_path):
    """Create a temporary SQLite database for each test."""
    db_path = str(tmp_path / "test_provenance.db")
    database = Database(f"sqlite+aiosqlite:///{db_path}")
    await database.connect()
    yield database
    await database.close()


async def _create_application(client: AsyncClient) -> str:
    """Helper: submit a test application and return its ID."""
    resp = await client.post(
        "/api/v1/applications",
        json={
            "applicant_name": "Provenance Test User",
            "business_name": "Provenance Test Business",
            "pan_number": "ABCDE1234F",
            "phone": "9876543210",
            "email": "prov@example.com",
        },
    )
    assert resp.status_code == 202
    return resp.json()["application_id"]


# ── 1. MCP tool invocation produces MCP provenance ──


@pytest.mark.asyncio
async def test_mcp_tool_records_mcp_provenance(mcp_server):
    """MCP tool call should produce an audit event with interface=MCP."""
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://test", headers=AUTH_HEADERS
    ) as client:
        app_id = await _create_application(client)

    # Invoke an MCP tool
    result = await mcp_server.call_tool("get_application_status", {"application_id": app_id})
    assert len(result.content) == 1
    data = json.loads(result.content[0].text)
    assert data["application_id"] == app_id

    # Check the audit trail for MCP-provenance events
    audit = AuditLogger()
    events = await audit.get_events_for_application(app_id)

    # Filter for MCP access events
    mcp_events = [e for e in events if e.event_type == EventType.MCP_ACCESS]
    assert len(mcp_events) >= 1, (
        f"Expected at least 1 MCP_ACCESS event, got {len(mcp_events)}. "
        f"All event types: {[e.event_type.value for e in events]}"
    )

    mcp_event = mcp_events[0]
    assert mcp_event.metadata["tool"] == "get_application_status"
    assert mcp_event.actor == "MCP_CLIENT"


# ── 2. Tool name is recorded correctly ──


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "tool_name",
    [
        "get_application_status",
        "list_applications",
        "get_application_documents",
        "get_document",
        "get_document_raw_text",
        "get_audit_history",
        "get_verification_summary",
        "get_risk_assessment",
        "validate_application",
    ],
)
async def test_each_mcp_tool_records_its_name(mcp_server, tool_name):
    """Each MCP tool should record its own name in audit metadata."""
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://test", headers=AUTH_HEADERS
    ) as client:
        app_id = await _create_application(client)

    # Build args for the tool
    if tool_name in ("get_document", "get_document_raw_text"):
        args = {"application_id": app_id, "document_id": "nonexistent"}
    else:
        args = {"application_id": app_id}

    await mcp_server.call_tool(tool_name, args)

    audit = AuditLogger()

    # list_applications uses a sentinel application_id since it's a global query
    if tool_name == "list_applications":
        all_events = await audit.get_all_events()
        tool_events = [
            e
            for e in all_events
            if e.event_type == EventType.MCP_ACCESS and e.metadata.get("tool") == tool_name
        ]
    else:
        events = await audit.get_events_for_application(app_id)
        tool_events = [
            e
            for e in events
            if e.event_type == EventType.MCP_ACCESS and e.metadata.get("tool") == tool_name
        ]
    assert len(tool_events) >= 1, f"Tool '{tool_name}' should have produced an MCP_ACCESS event"


# ── 3. Application ID appears in the audit event ──


@pytest.mark.asyncio
async def test_mcp_provenance_event_includes_application_id(mcp_server):
    """MCP access events should include the application_id."""
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://test", headers=AUTH_HEADERS
    ) as client:
        app_id = await _create_application(client)

    await mcp_server.call_tool("get_application_status", {"application_id": app_id})

    audit = AuditLogger()
    events = await audit.get_events_for_application(app_id)
    mcp_events = [e for e in events if e.event_type == EventType.MCP_ACCESS]
    assert len(mcp_events) >= 1

    # The event's application_id field should match
    assert mcp_events[0].application_id == app_id


# ── 4. Normal non-MCP operations remain unchanged ──


@pytest.mark.asyncio
async def test_normal_operations_no_mcp_provenance(db):
    """Direct WorkerEngine operations should NOT have MCP provenance."""
    memory = WorkflowMemory(db=db)
    audit = AuditLogger(db=db)
    engine = WorkerEngine(memory=memory, audit=audit)

    app_obj = OnboardingApplication(
        applicant_name="Normal User",
        business_name="Normal Corp",
        pan_number="ABCDE1234F",
        phone="9876543210",
    )
    await engine.process_application(app_obj)

    events = await audit.get_events_for_application(app_obj.application_id)

    # No event should be MCP_ACCESS
    mcp_events = [e for e in events if e.event_type == EventType.MCP_ACCESS]
    assert len(mcp_events) == 0

    # All events should have actor=SAKSHAM (default)
    for e in events:
        assert e.actor == "SAKSHAM"


# ── 5. Unknown MCP caller does not get falsely labeled OPENCLAW ──


@pytest.mark.asyncio
async def test_mcp_client_not_labeled_openclaw(mcp_server):
    """Generic MCP client must not be mislabeled as OPENCLAW."""
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://test", headers=AUTH_HEADERS
    ) as client:
        app_id = await _create_application(client)

    await mcp_server.call_tool("get_application_status", {"application_id": app_id})

    audit = AuditLogger()
    events = await audit.get_events_for_application(app_id)

    for e in events:
        assert e.actor != "OPENCLAW", (
            f"Actor must not be OPENCLAW when caller identity is unknown: {e.actor}"
        )


# ── 6. No secrets appear in audit metadata ──


@pytest.mark.asyncio
async def test_no_secrets_in_audit_metadata(mcp_server):
    """Audit metadata must not contain API keys, tokens, or secrets."""
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://test", headers=AUTH_HEADERS
    ) as client:
        app_id = await _create_application(client)

    await mcp_server.call_tool("get_application_status", {"application_id": app_id})

    audit = AuditLogger()
    events = await audit.get_events_for_application(app_id)

    blocked_keys = {"api_key", "authorization", "token", "secret", "password", "env"}
    for e in events:
        for key in e.metadata:
            assert key.lower() not in blocked_keys, f"Secret key '{key}' found in audit metadata"


# ── 7. Audit event ordering remains correct ──


@pytest.mark.asyncio
async def test_mcp_events_maintain_chronological_order(mcp_server):
    """MCP-provenance events should maintain chronological ordering."""
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://test", headers=AUTH_HEADERS
    ) as client:
        app_id = await _create_application(client)

    # Call multiple MCP tools
    await mcp_server.call_tool("get_application_status", {"application_id": app_id})
    await mcp_server.call_tool("get_verification_summary", {"application_id": app_id})
    await mcp_server.call_tool("get_audit_history", {"application_id": app_id})

    audit = AuditLogger()
    events = await audit.get_events_for_application(app_id)

    # All events should be in chronological order
    for i in range(1, len(events)):
        assert events[i - 1].timestamp <= events[i].timestamp


# ── 8. All 9 MCP tools remain functional ──


@pytest.mark.asyncio
async def test_all_mcp_tools_still_work(mcp_server):
    """Smoke test: all 9 MCP tools should return valid responses."""
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://test", headers=AUTH_HEADERS
    ) as client:
        app_id = await _create_application(client)

    tools_and_args = [
        ("get_application_status", {"application_id": app_id}),
        ("list_applications", {}),
        ("get_application_documents", {"application_id": app_id}),
        ("get_document", {"application_id": app_id, "document_id": "nonexistent"}),
        ("get_document_raw_text", {"application_id": app_id, "document_id": "nonexistent"}),
        ("get_audit_history", {"application_id": app_id}),
        ("get_verification_summary", {"application_id": app_id}),
        ("get_risk_assessment", {"application_id": app_id}),
        ("validate_application", {"application_id": app_id}),
    ]

    for tool_name, args in tools_and_args:
        result = await mcp_server.call_tool(tool_name, args)
        assert len(result.content) == 1, f"Tool {tool_name} returned no content"
        data = json.loads(result.content[0].text)
        # Should not raise; all tools return valid JSON
        assert isinstance(data, dict)


# ── 9. Policy authority remains unchanged ──


@pytest.mark.asyncio
async def test_policy_authority_unchanged(db):
    """CRITICAL risk + AI APPROVE must still produce ESCALATE_TO_HUMAN."""
    from unittest.mock import patch

    from app.models.domain import (
        AIRecommendation,
        ApplicationDocument,
        ExtractedDocumentData,
    )
    from app.models.states import FinalDecision, RiskLevel

    memory = WorkflowMemory(db=db)
    audit = AuditLogger(db=db)
    engine = WorkerEngine(memory=memory, audit=audit)

    app_obj = OnboardingApplication(
        applicant_name="Policy Test",
        business_name="Policy Corp",
        pan_number="AABCT1234D",
        phone="6111111111",
        email="wrong@example.com",
        documents=[
            ApplicationDocument(
                document_type="pan_card",
                raw_text="Name: Policy Test Corp\nPAN: ABCDE1234F",
            )
        ],
    )

    extracted_data = ExtractedDocumentData(
        document_id=app_obj.documents[0].document_id,
        document_type="pan_card",
        extracted_fields={
            "pan_number": "ABCDE1234F",
            "phone": "9876543210",
            "email": "test@example.com",
        },
        confidence=0.95,
        extraction_method="ocr",
    )

    mock_recommendation = AIRecommendation(
        recommended_action=FinalDecision.APPROVE,
        confidence=0.9,
        risk_level=RiskLevel.LOW,
        reason="All checks pass",
        evidence=[],
    )

    with (
        patch(
            "app.worker.engine.extract_document_data",
            return_value=extracted_data,
        ),
        patch(
            "app.worker.engine.get_ai_recommendation",
            return_value=mock_recommendation,
        ),
    ):
        context = await engine.process_application(app_obj)

    assert context.risk_assessment is not None
    assert context.risk_assessment.risk_level == RiskLevel.CRITICAL
    assert context.final_decision == FinalDecision.ESCALATE_TO_HUMAN


# ── 10. No-document protection still intact ──


@pytest.mark.asyncio
async def test_no_document_protection_unchanged(db):
    """No documents + LLM APPROVE must produce REQUEST_MORE_INFORMATION."""
    from unittest.mock import patch

    from app.models.domain import AIRecommendation
    from app.models.states import FinalDecision, RiskLevel

    memory = WorkflowMemory(db=db)
    audit = AuditLogger(db=db)
    engine = WorkerEngine(memory=memory, audit=audit)

    app_obj = OnboardingApplication(
        applicant_name="No Doc Test",
        business_name="No Doc Corp",
        pan_number="ABCDE1234F",
        phone="9876543210",
    )

    mock_recommendation = AIRecommendation(
        recommended_action=FinalDecision.APPROVE,
        confidence=0.95,
        risk_level=RiskLevel.LOW,
        reason="All checks pass",
        evidence=[],
    )

    with patch(
        "app.worker.engine.get_ai_recommendation",
        return_value=mock_recommendation,
    ):
        context = await engine.process_application(app_obj)

    assert context.final_decision == FinalDecision.REQUEST_MORE_INFORMATION
    assert context.current_state == WorkflowState.MORE_INFORMATION_REQUIRED


# ── 11. Provenance context variable isolation ──


@pytest.mark.asyncio
async def test_call_context_isolation():
    """Context variable should not leak between calls."""
    set_call_context(Interface.MCP, "test_tool")
    interface, tool = get_call_context()
    assert interface == Interface.MCP
    assert tool == "test_tool"

    clear_call_context()
    interface, tool = get_call_context()
    assert interface is None
    assert tool is None


# ── 12. MCP access event metadata structure ──


@pytest.mark.asyncio
async def test_mcp_access_event_metadata_structure(mcp_server):
    """MCP access events should have correct metadata structure."""
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://test", headers=AUTH_HEADERS
    ) as client:
        app_id = await _create_application(client)

    await mcp_server.call_tool("get_application_status", {"application_id": app_id})

    audit = AuditLogger()
    events = await audit.get_events_for_application(app_id)

    mcp_events = [e for e in events if e.event_type == EventType.MCP_ACCESS]
    assert len(mcp_events) >= 1

    event = mcp_events[0]
    assert "tool" in event.metadata
    assert event.metadata["tool"] == "get_application_status"
    assert event.actor == "MCP_CLIENT"
    assert event.event_type == EventType.MCP_ACCESS


# ── 13. WorkerEngine audit events remain SAKSHAM actor ──


@pytest.mark.asyncio
async def test_worker_engine_events_have_saksham_actor(db):
    """WorkerEngine-generated events should still have actor=SAKSHAM."""
    memory = WorkflowMemory(db=db)
    audit = AuditLogger(db=db)
    engine = WorkerEngine(memory=memory, audit=audit)

    app_obj = OnboardingApplication(
        applicant_name="Actor Test",
        business_name="Actor Corp",
        pan_number="ABCDE1234F",
        phone="9876543210",
    )
    await engine.process_application(app_obj)

    events = await audit.get_events_for_application(app_obj.application_id)
    for e in events:
        assert e.actor == "SAKSHAM", f"WorkerEngine event actor should be SAKSHAM, got {e.actor}"


# ── 14. MCP provenance does not appear in WorkerEngine events ──


@pytest.mark.asyncio
async def test_no_mcp_provenance_in_worker_events(db):
    """WorkerEngine events should not contain MCP_ACCESS events."""
    memory = WorkflowMemory(db=db)
    audit = AuditLogger(db=db)
    engine = WorkerEngine(memory=memory, audit=audit)

    app_obj = OnboardingApplication(
        applicant_name="Metadata Test",
        business_name="Metadata Corp",
        pan_number="ABCDE1234F",
        phone="9876543210",
    )
    await engine.process_application(app_obj)

    events = await audit.get_events_for_application(app_obj.application_id)
    mcp_events = [e for e in events if e.event_type == EventType.MCP_ACCESS]
    assert len(mcp_events) == 0, (
        f"WorkerEngine should not generate MCP_ACCESS events, got {len(mcp_events)}"
    )
