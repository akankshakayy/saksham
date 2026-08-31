"""Tests for the Saksham MCP server tools.

Tests exercise each of the 9 read-only tools via direct invocation
of the MCPServer.call_tool() method, using the same test database
fixtures as the REST API tests.
"""

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.mcp import create_mcp_server

AUTH_HEADERS = {"X-API-Key": "test-secret-key-12345"}


@pytest.fixture(scope="module")
def mcp_server():
    return create_mcp_server()


async def _create_application(client: AsyncClient) -> str:
    """Helper: submit a test application and return its ID."""
    resp = await client.post(
        "/api/v1/applications",
        json={
            "applicant_name": "MCP Test User",
            "business_name": "MCP Test Business",
            "pan_number": "ABCDE1234F",
            "phone": "9876543210",
            "email": "mcp@example.com",
        },
    )
    assert resp.status_code == 200
    return resp.json()["application_id"]


@pytest.mark.asyncio
async def test_get_application_status(mcp_server):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", headers=AUTH_HEADERS) as client:
        app_id = await _create_application(client)

    result = await mcp_server.call_tool("get_application_status", {"application_id": app_id})
    assert len(result.content) == 1
    import json
    data = json.loads(result.content[0].text)
    assert data["application_id"] == app_id
    assert data["applicant_name"] == "MCP Test User"
    assert data["business_name"] == "MCP Test Business"
    assert "current_state" in data
    assert "created_at" in data


@pytest.mark.asyncio
async def test_get_application_status_not_found(mcp_server):
    result = await mcp_server.call_tool(
        "get_application_status", {"application_id": "nonexistent"}
    )
    assert len(result.content) == 1
    import json
    data = json.loads(result.content[0].text)
    assert "error" in data
    assert "not found" in data["error"]


@pytest.mark.asyncio
async def test_list_applications(mcp_server):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", headers=AUTH_HEADERS) as client:
        await _create_application(client)

    result = await mcp_server.call_tool("list_applications", {})
    assert len(result.content) == 1
    import json
    data = json.loads(result.content[0].text)
    assert "applications" in data
    assert "total" in data
    assert data["total"] >= 1
    assert isinstance(data["applications"], list)


@pytest.mark.asyncio
async def test_list_applications_with_state_filter(mcp_server):
    result = await mcp_server.call_tool(
        "list_applications", {"state": "APPROVED"}
    )
    assert len(result.content) == 1
    import json
    data = json.loads(result.content[0].text)
    assert "applications" in data
    for app_summary in data["applications"]:
        assert app_summary["current_state"] == "APPROVED"


@pytest.mark.asyncio
async def test_get_application_documents(mcp_server):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", headers=AUTH_HEADERS) as client:
        app_id = await _create_application(client)

    result = await mcp_server.call_tool(
        "get_application_documents", {"application_id": app_id}
    )
    assert len(result.content) == 1
    import json
    data = json.loads(result.content[0].text)
    assert data["application_id"] == app_id
    assert "documents" in data
    assert isinstance(data["documents"], list)


@pytest.mark.asyncio
async def test_get_application_documents_not_found(mcp_server):
    result = await mcp_server.call_tool(
        "get_application_documents", {"application_id": "nonexistent"}
    )
    assert len(result.content) == 1
    import json
    data = json.loads(result.content[0].text)
    assert "error" in data


@pytest.mark.asyncio
async def test_get_document_not_found(mcp_server):
    result = await mcp_server.call_tool(
        "get_document", {"application_id": "nonexistent", "document_id": "nonexistent"}
    )
    assert len(result.content) == 1
    import json
    data = json.loads(result.content[0].text)
    assert "error" in data


@pytest.mark.asyncio
async def test_get_document_raw_text_not_found(mcp_server):
    result = await mcp_server.call_tool(
        "get_document_raw_text",
        {"application_id": "nonexistent", "document_id": "nonexistent"},
    )
    assert len(result.content) == 1
    import json
    data = json.loads(result.content[0].text)
    assert "error" in data


@pytest.mark.asyncio
async def test_get_audit_history(mcp_server):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", headers=AUTH_HEADERS) as client:
        app_id = await _create_application(client)

    result = await mcp_server.call_tool(
        "get_audit_history", {"application_id": app_id}
    )
    assert len(result.content) == 1
    import json
    data = json.loads(result.content[0].text)
    assert data["application_id"] == app_id
    assert "events" in data
    assert isinstance(data["events"], list)
    assert len(data["events"]) >= 1


@pytest.mark.asyncio
async def test_get_audit_history_not_found(mcp_server):
    result = await mcp_server.call_tool(
        "get_audit_history", {"application_id": "nonexistent"}
    )
    assert len(result.content) == 1
    import json
    data = json.loads(result.content[0].text)
    assert "error" in data


@pytest.mark.asyncio
async def test_get_verification_summary(mcp_server):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", headers=AUTH_HEADERS) as client:
        app_id = await _create_application(client)

    result = await mcp_server.call_tool(
        "get_verification_summary", {"application_id": app_id}
    )
    assert len(result.content) == 1
    import json
    data = json.loads(result.content[0].text)
    assert data["application_id"] == app_id
    assert "current_state" in data
    assert "missing_fields" in data
    assert "retry_count" in data
    assert "created_at" in data
    assert "updated_at" in data


@pytest.mark.asyncio
async def test_get_verification_summary_not_found(mcp_server):
    result = await mcp_server.call_tool(
        "get_verification_summary", {"application_id": "nonexistent"}
    )
    assert len(result.content) == 1
    import json
    data = json.loads(result.content[0].text)
    assert "error" in data


@pytest.mark.asyncio
async def test_get_risk_assessment(mcp_server):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", headers=AUTH_HEADERS) as client:
        app_id = await _create_application(client)

    result = await mcp_server.call_tool(
        "get_risk_assessment", {"application_id": app_id}
    )
    assert len(result.content) == 1
    import json
    data = json.loads(result.content[0].text)
    assert data["application_id"] == app_id
    assert "risk_level" in data
    assert "risk_score" in data
    assert "risk_factors" in data


@pytest.mark.asyncio
async def test_get_risk_assessment_not_found(mcp_server):
    result = await mcp_server.call_tool(
        "get_risk_assessment", {"application_id": "nonexistent"}
    )
    assert len(result.content) == 1
    import json
    data = json.loads(result.content[0].text)
    assert "error" in data


@pytest.mark.asyncio
async def test_validate_application(mcp_server):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", headers=AUTH_HEADERS) as client:
        app_id = await _create_application(client)

    result = await mcp_server.call_tool(
        "validate_application", {"application_id": app_id}
    )
    assert len(result.content) == 1
    import json
    data = json.loads(result.content[0].text)
    assert data["application_id"] == app_id
    assert "current_state" in data
    assert "missing_fields" in data
    assert "is_valid" in data
    assert isinstance(data["is_valid"], bool)


@pytest.mark.asyncio
async def test_validate_application_not_found(mcp_server):
    result = await mcp_server.call_tool(
        "validate_application", {"application_id": "nonexistent"}
    )
    assert len(result.content) == 1
    import json
    data = json.loads(result.content[0].text)
    assert "error" in data


@pytest.mark.asyncio
async def test_mcp_server_tool_count(mcp_server):
    """Verify exactly 9 tools are registered."""
    tools = await mcp_server.list_tools()
    assert len(tools) == 9
    tool_names = {t.name for t in tools}
    expected = {
        "get_application_status",
        "list_applications",
        "get_application_documents",
        "get_document",
        "get_document_raw_text",
        "get_audit_history",
        "get_verification_summary",
        "get_risk_assessment",
        "validate_application",
    }
    assert tool_names == expected


@pytest.mark.asyncio
async def test_mcp_tools_are_read_only(mcp_server):
    """Verify all tools have no mutating annotations."""
    tools = await mcp_server.list_tools()
    for tool in tools:
        assert tool.annotations is None or not getattr(
            tool.annotations, "readOnlyHint", False
        ) or tool.annotations.readOnlyHint is True
