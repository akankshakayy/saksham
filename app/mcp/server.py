"""MCP server exposing Saksham's verification data as read-only tools.

Tools are strictly inspection-only: they return data from the SQLite store
without modifying workflow state, audit history, or any persisted records.

Mount in FastAPI via:
    from app.mcp import create_mcp_server
    mcp = create_mcp_server()
    app.mount("/mcp", mcp.streamable_http_app())
"""

from __future__ import annotations

import logging
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager

from app.audit.logger import AuditLogger
from app.audit.provenance import Interface, set_call_context
from app.memory.store import DocumentStore, WorkflowMemory
from app.models.states import EventType, WorkflowState
from app.services.onboarding import OnboardingService

logger = logging.getLogger(__name__)

# Sentinel for applications not found — still audit the access attempt
_NOT_FOUND = "__NOT_FOUND__"


def create_mcp_server() -> MCPServer:
    """Create and configure the Saksham MCP server with all read-only tools."""
    server = MCPServer(
        name="saksham",
        title="Saksham Verification Worker",
        description="Read-only access to Saksham onboarding verification data",
        version="0.1.0",
    )

    # Store the session manager for lifespan management
    server._saksham_session_manager: StreamableHTTPSessionManager | None = None

    _service: OnboardingService | None = None
    _memory: WorkflowMemory | None = None
    _doc_store: DocumentStore | None = None
    _audit: AuditLogger | None = None

    def _get_service() -> OnboardingService:
        nonlocal _service
        if _service is None:
            _service = OnboardingService()
        return _service

    def _get_memory() -> WorkflowMemory:
        nonlocal _memory
        if _memory is None:
            _memory = WorkflowMemory()
        return _memory

    def _get_doc_store() -> DocumentStore:
        nonlocal _doc_store
        if _doc_store is None:
            _doc_store = DocumentStore()
        return _doc_store

    def _get_audit() -> AuditLogger:
        nonlocal _audit
        if _audit is None:
            _audit = AuditLogger()
        return _audit

    async def _record_mcp_access(
        tool_name: str,
        application_id: str,
        result: str = "SUCCESS",
    ) -> None:
        """Record an MCP_ACCESS audit event for observability."""
        audit = _get_audit()
        try:
            await audit.record(
                application_id=application_id,
                state=WorkflowState.RECEIVED,
                event_type=EventType.MCP_ACCESS,
                action=tool_name,
                result=result,
                metadata={"tool": tool_name},
                actor="MCP_CLIENT",
            )
        except Exception:
            logger.debug("Failed to record MCP access event for %s", tool_name)

    @server.tool(
        name="get_application_status",
        description=(
            "Get the full status of a single onboarding application including "
            "applicant details, current workflow state, risk assessment, "
            "recommendation, and timestamps."
        ),
    )
    async def get_application_status(application_id: str) -> dict[str, Any]:
        """Return full application status or error if not found."""
        set_call_context(Interface.MCP, "get_application_status")
        service = _get_service()
        status = await service.get_status(application_id)
        if status is None:
            await _record_mcp_access("get_application_status", application_id, "NOT_FOUND")
            return {"error": f"Application '{application_id}' not found"}
        await _record_mcp_access("get_application_status", application_id)
        return status.model_dump(mode="json")

    @server.tool(
        name="list_applications",
        description=(
            "List onboarding applications with optional filtering by state, "
            "risk level, or final decision. Returns a paginated list with "
            "summary fields: applicant name, business name, current state, "
            "risk score, and timestamps."
        ),
    )
    async def list_applications(
        state: str | None = None,
        risk_level: str | None = None,
        final_decision: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> dict[str, Any]:
        """Return paginated application list with optional filters."""
        set_call_context(Interface.MCP, "list_applications")
        service = _get_service()
        result = await service.list_applications(
            state=state,
            risk_level=risk_level,
            final_decision=final_decision,
            limit=limit,
            offset=offset,
        )
        await _record_mcp_access("list_applications", _NOT_FOUND)
        return result.model_dump(mode="json")

    @server.tool(
        name="get_application_documents",
        description=(
            "List all documents uploaded for a given application. Returns "
            "document type, processing status, confidence scores, and "
            "processing method for each document."
        ),
    )
    async def get_application_documents(application_id: str) -> dict[str, Any]:
        """Return document list for an application or error if not found."""
        set_call_context(Interface.MCP, "get_application_documents")
        service = _get_service()
        if not await service.application_exists(application_id):
            await _record_mcp_access("get_application_documents", application_id, "NOT_FOUND")
            return {"error": f"Application '{application_id}' not found"}
        docs = await service.get_documents(application_id)
        await _record_mcp_access("get_application_documents", application_id)
        return {
            "application_id": application_id,
            "documents": [d.model_dump(mode="json") for d in docs],
        }

    @server.tool(
        name="get_document",
        description=(
            "Get full detail for a single document including extracted fields, "
            "confidence breakdown, processing method, and error information."
        ),
    )
    async def get_document(application_id: str, document_id: str) -> dict[str, Any]:
        """Return document detail or error if not found."""
        set_call_context(Interface.MCP, "get_document")
        service = _get_service()
        if not await service.application_exists(application_id):
            await _record_mcp_access("get_document", application_id, "NOT_FOUND")
            return {"error": f"Application '{application_id}' not found"}
        doc = await service.get_document(application_id, document_id)
        if doc is None:
            await _record_mcp_access("get_document", application_id, "NOT_FOUND")
            return {"error": f"Document '{document_id}' not found"}
        await _record_mcp_access("get_document", application_id)
        return doc.model_dump(mode="json")

    @server.tool(
        name="get_document_raw_text",
        description=(
            "Get the raw OCR text extracted from a document. Returns the "
            "full text content along with character count."
        ),
    )
    async def get_document_raw_text(application_id: str, document_id: str) -> dict[str, Any]:
        """Return raw OCR text or error if not found."""
        set_call_context(Interface.MCP, "get_document_raw_text")
        service = _get_service()
        if not await service.application_exists(application_id):
            await _record_mcp_access("get_document_raw_text", application_id, "NOT_FOUND")
            return {"error": f"Application '{application_id}' not found"}
        raw = await service.get_raw_text(application_id, document_id)
        if raw is None:
            await _record_mcp_access("get_document_raw_text", application_id, "NOT_FOUND")
            return {"error": f"Document '{document_id}' not found"}
        await _record_mcp_access("get_document_raw_text", application_id)
        return raw.model_dump(mode="json")

    @server.tool(
        name="get_audit_history",
        description=(
            "Get the full audit trail for an application. Returns all "
            "recorded events in chronological order including state "
            "transitions, tool executions, AI recommendations, and "
            "policy decisions."
        ),
    )
    async def get_audit_history(application_id: str) -> dict[str, Any]:
        """Return audit history or error if application not found."""
        set_call_context(Interface.MCP, "get_audit_history")
        service = _get_service()
        history = await service.get_history(application_id)
        if history is None:
            await _record_mcp_access("get_audit_history", application_id, "NOT_FOUND")
            return {"error": f"Application '{application_id}' not found"}
        await _record_mcp_access("get_audit_history", application_id)
        return history.model_dump(mode="json")

    @server.tool(
        name="get_verification_summary",
        description=(
            "Get a compact verification summary for an application: "
            "current state, final decision, risk level, risk score, "
            "missing fields, retry count, and key timestamps."
        ),
    )
    async def get_verification_summary(application_id: str) -> dict[str, Any]:
        """Return verification summary or error if not found."""
        set_call_context(Interface.MCP, "get_verification_summary")
        service = _get_service()
        status = await service.get_status(application_id)
        if status is None:
            await _record_mcp_access("get_verification_summary", application_id, "NOT_FOUND")
            return {"error": f"Application '{application_id}' not found"}
        await _record_mcp_access("get_verification_summary", application_id)
        return {
            "application_id": status.application_id,
            "current_state": status.current_state.value,
            "final_decision": status.final_decision.value if status.final_decision else None,
            "risk_level": status.risk_level.value if status.risk_level else None,
            "risk_score": status.risk_score,
            "missing_fields": status.missing_fields,
            "retry_count": status.retry_count,
            "created_at": status.created_at.isoformat(),
            "updated_at": status.updated_at.isoformat(),
        }

    @server.tool(
        name="get_risk_assessment",
        description=(
            "Get the risk assessment details for an application: risk level, "
            "risk score, risk factors, and the AI recommendation if available."
        ),
    )
    async def get_risk_assessment(application_id: str) -> dict[str, Any]:
        """Return risk assessment or error if not found."""
        set_call_context(Interface.MCP, "get_risk_assessment")
        service = _get_service()
        status = await service.get_status(application_id)
        if status is None:
            await _record_mcp_access("get_risk_assessment", application_id, "NOT_FOUND")
            return {"error": f"Application '{application_id}' not found"}
        await _record_mcp_access("get_risk_assessment", application_id)
        return {
            "application_id": status.application_id,
            "risk_level": status.risk_level.value if status.risk_level else None,
            "risk_score": status.risk_score,
            "risk_factors": status.risk_factors,
            "recommendation": status.recommendation.model_dump(mode="json")
            if status.recommendation
            else None,
        }

    @server.tool(
        name="validate_application",
        description=(
            "Dry-run validation of an application without modifying state. "
            "Returns the validation result, missing fields, and the "
            "application's current state. This is a read-only operation."
        ),
    )
    async def validate_application(application_id: str) -> dict[str, Any]:
        """Return validation status without changing application state."""
        set_call_context(Interface.MCP, "validate_application")
        service = _get_service()
        status = await service.get_status(application_id)
        if status is None:
            await _record_mcp_access("validate_application", application_id, "NOT_FOUND")
            return {"error": f"Application '{application_id}' not found"}
        await _record_mcp_access("validate_application", application_id)
        return {
            "application_id": status.application_id,
            "current_state": status.current_state.value,
            "missing_fields": status.missing_fields,
            "retry_count": status.retry_count,
            "is_valid": len(status.missing_fields) == 0,
        }

    return server
