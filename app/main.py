from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.responses import Response

from app.api.routes import router
from app.config.settings import get_settings
from app.mcp import create_mcp_server
from app.memory.database import close_database, init_database
from app.middleware import SecurityHeadersMiddleware, UploadSizeLimitMiddleware

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize database, recover stuck jobs, and manage MCP session."""
    settings = get_settings()
    await init_database(settings.database_url)

    await _recover_stuck_work()

    mcp_server = app.state.mcp_server
    session_manager = mcp_server._lowlevel_server._session_manager
    async with session_manager.run():
        yield

    # Shut down background worker before closing database
    from app.worker.background import get_worker

    worker = get_worker()
    await worker.shutdown(timeout=10.0)

    await close_database()


async def _recover_stuck_work() -> None:
    """Recover work that was accepted but not completed before a shutdown.

    Scans for:
    - Applications in non-terminal processing states (RECEIVED, VERIFYING, etc.)
    - Documents in 'pending' or 'processing' status

    Re-queues recoverable items for background processing.
    """
    from app.memory.database import get_database
    from app.models.states import WorkflowState

    recoverable_states = {
        WorkflowState.RECEIVED.value,
        WorkflowState.VALIDATING.value,
        WorkflowState.VERIFYING.value,
        WorkflowState.TOOL_RETRYING.value,
    }

    terminal_states = {
        WorkflowState.APPROVED.value,
        WorkflowState.REJECTED.value,
        WorkflowState.ESCALATED.value,
        WorkflowState.ESCALATED_TO_HUMAN.value,
        WorkflowState.FAILED.value,
        WorkflowState.MORE_INFORMATION_REQUIRED.value,
        WorkflowState.MISSING_INFORMATION.value,
    }

    try:
        db = get_database()
        cursor = await db.conn.execute(
            "SELECT application_id, current_state FROM workflow_contexts "
            "WHERE current_state NOT IN ({})".format(
                ",".join("?" for _ in terminal_states)
            ),
            list(terminal_states),
        )
        stuck_apps = await cursor.fetchall()

        if stuck_apps:
            logger.info("Recovering %d stuck application(s)", len(stuck_apps))

            from app.worker.background import get_worker

            worker = get_worker()
            for row in stuck_apps:
                app_id = row["application_id"]
                state = row["current_state"]

                if state in recoverable_states:
                    logger.info("Re-queuing application %s (state=%s)", app_id, state)
                    await worker.submit_workflow_task(
                        key=app_id,
                        coro=_recover_application(app_id),
                    )

        doc_cursor = await db.conn.execute(
            "SELECT document_id, application_id, document_type, original_filename, stored_path "
            "FROM documents WHERE processing_status IN ('pending', 'processing')"
        )
        stuck_docs = await doc_cursor.fetchall()

        if stuck_docs:
            logger.info("Recovering %d stuck document(s)", len(stuck_docs))

            from app.config.settings import get_settings as _get_settings
            from app.worker.background import get_worker

            worker = get_worker()
            settings = _get_settings()
            for row in stuck_docs:
                doc_id = row["document_id"]
                logger.info("Re-queuing document %s", doc_id)
                await worker.submit_ocr_task(
                    key=doc_id,
                    coro=_recover_document(
                        document_id=doc_id,
                        application_id=row["application_id"],
                        document_type=row["document_type"],
                        original_filename=row["original_filename"],
                        stored_path=row["stored_path"],
                        max_pdf_pages=settings.max_pdf_pages,
                    ),
                )

    except Exception:
        logger.exception("Startup recovery failed")


async def _recover_application(application_id: str) -> None:
    """Recover a stuck application by re-running its workflow."""
    from app.memory.store import WorkflowMemory
    from app.models.states import WorkflowState
    from app.worker.engine import WorkerEngine

    memory = WorkflowMemory()
    engine = WorkerEngine(memory=memory)

    try:
        context = await memory.get(application_id)
        if context is None:
            logger.error("Recovery: no context for application %s", application_id)
            return

        terminal = {
            WorkflowState.APPROVED,
            WorkflowState.REJECTED,
            WorkflowState.ESCALATED,
            WorkflowState.ESCALATED_TO_HUMAN,
            WorkflowState.FAILED,
            WorkflowState.MORE_INFORMATION_REQUIRED,
            WorkflowState.MISSING_INFORMATION,
        }
        if context.current_state in terminal:
            logger.info(
                "Recovery: application %s already in terminal state %s",
                application_id,
                context.current_state.value,
            )
            return

        logger.info(
            "Recovery: resuming application %s from state %s",
            application_id,
            context.current_state.value,
        )
        await engine.resume_application(context)

    except Exception:
        logger.exception("Recovery failed for application %s", application_id)


async def _recover_document(
    *,
    document_id: str,
    application_id: str,
    document_type: str,
    original_filename: str,
    stored_path: str,
    max_pdf_pages: int,
) -> None:
    """Recover a stuck document by re-running OCR processing."""
    import asyncio

    from app.audit.logger import AuditLogger
    from app.memory.store import DocumentStore
    from app.models.states import EventType, WorkflowState

    store = DocumentStore()
    audit = AuditLogger()

    try:
        doc = await store.get_document(document_id)
        if doc and doc["processing_status"] == "completed":
            logger.info("Recovery: document %s already completed, skipping", document_id)
            return

        logger.info("Recovery: re-processing document %s", document_id)
        await store.update_document_status(document_id, "processing")

        from app.tools.document_processing import process_document_file

        result = await asyncio.to_thread(
            process_document_file,
            file_path=stored_path,
            document_type=document_type,
            application_id=application_id,
            document_id=document_id,
            original_filename=original_filename,
            max_pdf_pages=max_pdf_pages,
        )

        await store.update_document_status(
            document_id,
            result.processing_status,
            raw_text=result.raw_text,
            raw_text_available=result.raw_text_available,
            ocr_confidence=result.ocr_confidence,
            field_extraction_confidence=result.field_extraction_confidence,
            overall_confidence=result.overall_confidence,
            extracted_fields=result.extracted_fields,
            processing_method=result.processing_method,
            error_code=result.error_code,
            error_message=result.error_message,
        )

        event_type = (
            EventType.DOCUMENT_PROCESSING_COMPLETED
            if result.processing_status == "completed"
            else EventType.DOCUMENT_LOW_CONFIDENCE
            if result.processing_status == "low_confidence"
            else EventType.DOCUMENT_PROCESSING_FAILED
        )
        await audit.record(
            application_id=application_id,
            state=WorkflowState.RECEIVED,
            event_type=event_type,
            action="recover_document",
            result=result.processing_status.upper(),
            metadata={
                "document_id": document_id,
                "processing_status": result.processing_status,
                "overall_confidence": result.overall_confidence,
            },
        )

    except Exception:
        logger.exception("Recovery failed for document %s", document_id)
        try:
            await store.update_document_status(
                document_id,
                "failed",
                error_code="RECOVERY_FAILED",
                error_message="Startup recovery failed",
            )
        except Exception:
            logger.exception("Failed to persist recovery error for document %s", document_id)


class MCPAuthMiddleware:
    """ASGI middleware that gates access to the MCP endpoint behind API key auth."""

    def __init__(self, app, mount_path: str = "/mcp") -> None:
        self.app = app
        self.mount_path = mount_path

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope["path"].startswith(self.mount_path):
            from app.auth import _get_api_keys, _hash_key

            api_keys = _get_api_keys()
            if not api_keys:
                error_msg = (
                    '{"error_code":"AUTH_NOT_CONFIGURED","message":"No API keys configured"}'
                )
                response = Response(
                    content=error_msg,
                    status_code=503,
                    media_type="application/json",
                )
                await response(scope, receive, send)
                return

            headers = dict(scope.get("headers", []))
            auth_header = None
            for key, value in headers:
                if key == b"x-api-key":
                    auth_header = value.decode()
                    break

            if auth_header is None:
                error_msg = '{"error_code":"MISSING_API_KEY","message":"X-API-Key header required"}'
                response = Response(
                    content=error_msg,
                    status_code=401,
                    media_type="application/json",
                )
                await response(scope, receive, send)
                return

            import hmac as _hmac

            provided_hash = _hash_key(auth_header)
            authorized = any(_hmac.compare_digest(provided_hash, kh) for kh in api_keys)
            if not authorized:
                response = Response(
                    content='{"error_code":"INVALID_API_KEY","message":"Invalid API key"}',
                    status_code=401,
                    media_type="application/json",
                )
                await response(scope, receive, send)
                return

        return await self.app(scope, receive, send)


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title=settings.app_name,
        description="Autonomous Partner Onboarding and Verification AI Worker",
        version="0.1.0",
        lifespan=lifespan,
        debug=settings.debug,
    )

    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        logger.error("Unhandled exception: %s", exc, exc_info=True)
        return JSONResponse(
            status_code=500,
            content={
                "error_code": "INTERNAL_ERROR",
                "message": "An unexpected error occurred",
            },
        )

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        detail = (
            exc.detail
            if isinstance(exc.detail, dict)
            else {
                "error_code": "HTTP_ERROR",
                "message": str(exc.detail),
            }
        )
        return JSONResponse(
            status_code=exc.status_code,
            content=detail,
        )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=settings.cors_methods,
        allow_headers=settings.cors_headers,
    )

    app.add_middleware(SecurityHeadersMiddleware)

    if settings.max_file_size:
        app.add_middleware(UploadSizeLimitMiddleware, max_size=settings.max_file_size)

    app.include_router(router, prefix="/api/v1")

    mcp_server = create_mcp_server()
    app.state.mcp_server = mcp_server
    mcp_app = MCPAuthMiddleware(mcp_server.streamable_http_app(), mount_path="/mcp")
    app.mount("/mcp", mcp_app)

    return app


app = create_app()
