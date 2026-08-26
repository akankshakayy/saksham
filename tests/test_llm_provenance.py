"""Focused tests for LLM recommendation provenance tracking.

Verifies that audit metadata correctly identifies the recommendation source:
- Live LLM success: source="openrouter", model=<configured model>
- LLM failure fallback: source="rule_based_fallback"
- No API key: source="rule_based_fallback"
- Policy authority is not affected by provenance changes
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from app.audit.logger import AuditLogger
from app.memory.database import Database
from app.memory.store import WorkflowMemory
from app.models.domain import (
    AIRecommendation,
    ApplicationDocument,
    ExtractedDocumentData,
    OnboardingApplication,
    WorkflowContext,
)
from app.models.states import EventType, FinalDecision, RiskLevel, WorkflowState
from app.tools.llm_analysis import get_ai_recommendation
from app.worker.engine import WorkerEngine


@pytest_asyncio.fixture
async def db(tmp_path):
    db_path = str(tmp_path / "test.db")
    database = Database(f"sqlite+aiosqlite:///{db_path}")
    await database.connect()
    yield database
    await database.close()


@pytest_asyncio.fixture
async def engine(db):
    memory = WorkflowMemory(db=db)
    audit = AuditLogger(db=db)
    return WorkerEngine(memory=memory, audit=audit)


def _make_context(**overrides) -> WorkflowContext:
    app = OnboardingApplication(
        applicant_name="Test User",
        business_name="Test Business",
        pan_number="ABCDE1234F",
        phone="9876543210",
        email="test@example.com",
    )
    defaults = dict(
        application=app,
        current_state=WorkflowState.ANALYZING_RISK,
        extracted_data=[
            ExtractedDocumentData(
                document_id="doc-1",
                document_type="pan_card",
                extracted_fields={"pan_number": "ABCDE1234F"},
                confidence=0.95,
                extraction_method="ocr",
            )
        ],
    )
    defaults.update(overrides)
    return WorkflowContext(**defaults)


LLM_SUCCESS_RESPONSE = MagicMock(
    status_code=200,
    raise_for_status=lambda: None,
    json=lambda: {
        "choices": [
            {"message": {"content": json.dumps({
                "recommended_action": "APPROVE",
                "confidence": 0.87,
                "risk_level": "LOW",
                "reason": "All checks passed",
                "evidence": ["PAN verified"],
            })}}
        ]
    },
)


@pytest.mark.asyncio
async def test_live_llm_success_source():
    """Live LLM success records source=openrouter and model."""
    context = _make_context()

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=LLM_SUCCESS_RESPONSE)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("app.tools.llm_analysis.httpx.AsyncClient", return_value=mock_client):
        rec = await get_ai_recommendation(context)

    assert rec.source == "openrouter"
    assert rec.model is not None
    assert rec.recommended_action == FinalDecision.APPROVE


@pytest.mark.asyncio
async def test_live_llm_success_model_matches_config():
    """The model field matches the configured llm_model setting."""
    context = _make_context()

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=LLM_SUCCESS_RESPONSE)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("app.tools.llm_analysis.httpx.AsyncClient", return_value=mock_client):
        rec = await get_ai_recommendation(context)

    from app.config.settings import get_settings
    settings = get_settings()
    assert rec.model == settings.llm_model


@pytest.mark.asyncio
async def test_llm_failure_fallback_source():
    """LLM request failure falls back with source=rule_based_fallback."""
    context = _make_context()

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(side_effect=Exception("connection timeout"))
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("app.tools.llm_analysis.httpx.AsyncClient", return_value=mock_client):
        rec = await get_ai_recommendation(context)

    assert rec.source == "rule_based_fallback"
    assert rec.model is None


@pytest.mark.asyncio
async def test_no_api_key_fallback_source():
    """No API key configured uses fallback with source=rule_based_fallback."""
    context = _make_context()

    with patch("app.tools.llm_analysis.get_settings") as mock_settings:
        mock_settings.return_value = MagicMock(llm_api_key=None)
        rec = await get_ai_recommendation(context)

    assert rec.source == "rule_based_fallback"
    assert rec.model is None


@pytest.mark.asyncio
async def test_policy_authority_not_weakened(engine: WorkerEngine):
    """Provenance observability does not weaken deterministic policy.

    LLM recommends APPROVE for CRITICAL risk → policy must override to ESCALATE.
    """
    app = OnboardingApplication(
        applicant_name="Saksham Test",
        business_name="Saksham Test Pvt Ltd",
        pan_number="AABCT1234D",
        phone="6111111111",
        email="wrong@example.com",
        documents=[
            ApplicationDocument(
                document_type="pan_card",
                raw_text="Name: Saksham Test Pvt Ltd\nPAN: ABCDE1234F",
            )
        ],
    )

    extracted_data = ExtractedDocumentData(
        document_id=app.documents[0].document_id,
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
        source="openrouter",
        model="test-model",
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
        context = await engine.process_application(app)

    assert context.risk_assessment.risk_level == RiskLevel.CRITICAL
    assert context.recommendation.recommended_action == FinalDecision.APPROVE
    assert context.final_decision == FinalDecision.ESCALATE_TO_HUMAN
    assert context.current_state == WorkflowState.ESCALATED


@pytest.mark.asyncio
async def test_audit_includes_provenance(engine: WorkerEngine):
    """AI_RECOMMENDATION audit events include source and model metadata."""
    app = OnboardingApplication(
        applicant_name="John Doe",
        business_name="Doe Enterprises",
        pan_number="ABCDE1234F",
        phone="9876543210",
        email="john@example.com",
    )

    mock_recommendation = AIRecommendation(
        recommended_action=FinalDecision.APPROVE,
        confidence=0.9,
        risk_level=RiskLevel.LOW,
        reason="All checks pass",
        evidence=[],
        source="rule_based_fallback",
        model=None,
    )

    with patch(
        "app.worker.engine.get_ai_recommendation",
        return_value=mock_recommendation,
    ):
        await engine.process_application(app)

    events = await engine.get_application_history(app.application_id)
    rec_events = [e for e in events if e.event_type == EventType.AI_RECOMMENDATION]
    assert len(rec_events) == 1

    meta = rec_events[0].metadata
    assert meta["source"] == "rule_based_fallback"
    assert meta["model"] is None
    assert meta["recommended_action"] == FinalDecision.APPROVE.value


@pytest.mark.asyncio
async def test_audit_live_llm_includes_model(db):
    """Live LLM audit event includes model name in metadata."""
    memory = WorkflowMemory(db=db)
    audit = AuditLogger(db=db)
    eng = WorkerEngine(memory=memory, audit=audit)

    app = OnboardingApplication(
        applicant_name="John Doe",
        business_name="Doe Enterprises",
        pan_number="ABCDE1234F",
        phone="9876543210",
        email="john@example.com",
    )

    mock_recommendation = AIRecommendation(
        recommended_action=FinalDecision.APPROVE,
        confidence=0.87,
        risk_level=RiskLevel.LOW,
        reason="All checks pass",
        evidence=[],
        source="openrouter",
        model="meta-llama/llama-3.1-8b-instruct",
    )

    with patch(
        "app.worker.engine.get_ai_recommendation",
        return_value=mock_recommendation,
    ):
        await eng.process_application(app)

    events = await eng.get_application_history(app.application_id)
    rec_events = [e for e in events if e.event_type == EventType.AI_RECOMMENDATION]
    assert len(rec_events) == 1

    meta = rec_events[0].metadata
    assert meta["source"] == "openrouter"
    assert meta["model"] == "meta-llama/llama-3.1-8b-instruct"


@pytest.mark.asyncio
async def test_no_api_key_in_audit_metadata():
    """No API key path never exposes secrets in audit metadata."""
    context = _make_context()

    with patch("app.tools.llm_analysis.get_settings") as mock_settings:
        mock_settings.return_value = MagicMock(llm_api_key=None)
        rec = await get_ai_recommendation(context)

    meta = {
        "recommended_action": rec.recommended_action.value,
        "confidence": rec.confidence,
        "source": rec.source,
        "model": rec.model,
    }
    serialized = json.dumps(meta)
    assert "api_key" not in serialized.lower()
    assert "Bearer" not in serialized
    assert "secret" not in serialized.lower()


@pytest.mark.asyncio
async def test_llm_failure_no_secrets_in_metadata():
    """LLM failure fallback never exposes secrets in audit metadata."""
    context = _make_context()

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(side_effect=Exception("401 Unauthorized"))
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("app.tools.llm_analysis.httpx.AsyncClient", return_value=mock_client):
        rec = await get_ai_recommendation(context)

    meta = {
        "recommended_action": rec.recommended_action.value,
        "confidence": rec.confidence,
        "source": rec.source,
        "model": rec.model,
    }
    serialized = json.dumps(meta)
    assert "api_key" not in serialized.lower()
    assert "Bearer" not in serialized
