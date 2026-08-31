from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import JSONResponse

from app.auth import CallerIdentity, require_api_key, validate_uuid
from app.memory.errors import PersistenceError
from app.models.schemas import (
    ApplicationStatusResponse,
    DocumentDetailResponse,
    DocumentSummaryResponse,
    DocumentUploadResponse,
    ErrorResponse,
    HealthResponse,
    ListApplicationsResponse,
    RawTextResponse,
    SubmitApplicationRequest,
    SubmitApplicationResponse,
    WorkflowHistoryResponse,
)
from app.models.states import FinalDecision as FinalDecisionEnum
from app.models.states import RiskLevel as RiskLevelEnum
from app.models.states import WorkflowState as WorkflowStateEnum
from app.services.onboarding import OnboardingService

logger = logging.getLogger(__name__)

router = APIRouter()

_service: OnboardingService | None = None


def get_service() -> OnboardingService:
    global _service
    if _service is None:
        _service = OnboardingService()
    return _service


def _error_response(status_code: int, error_code: str, message: str) -> JSONResponse:
    """Return a standardized error response."""
    return JSONResponse(
        status_code=status_code,
        content=ErrorResponse(error_code=error_code, message=message).model_dump(),
    )


@router.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    return HealthResponse()


@router.post("/applications", response_model=SubmitApplicationResponse, status_code=202)
async def submit_application(
    request: SubmitApplicationRequest,
    _caller: CallerIdentity = Depends(require_api_key),
) -> SubmitApplicationResponse:
    """Submit a new onboarding application for background processing.

    Persists the application in RECEIVED state, schedules background workflow,
    and returns 202 Accepted.
    """
    service = get_service()
    try:
        result = await service.submit_application(request)

        from app.worker.background import get_worker

        worker = get_worker()
        await worker.submit_workflow_task(
            key=result.application_id,
            coro=_process_application_background(
                application_id=result.application_id,
                request_data=request,
            ),
        )

        return result
    except PersistenceError as exc:
        logger.error("Application submission failed (persistence): %s", exc)
        return _error_response(
            503,
            "PERSISTENCE_FAILURE",
            "Application could not be saved. Please try again.",
        )
    except Exception as exc:
        logger.error("Application submission failed: %s", exc)
        return _error_response(500, "INTERNAL_ERROR", "An unexpected error occurred")


@router.get(
    "/applications/{application_id}",
    response_model=ApplicationStatusResponse,
)
async def get_application_status(
    application_id: str,
    _caller: CallerIdentity = Depends(require_api_key),
) -> ApplicationStatusResponse:
    """Get current status of an application."""
    application_id = validate_uuid(application_id)
    service = get_service()
    status = await service.get_status(application_id)
    if not status:
        return _error_response(
            404,
            "APPLICATION_NOT_FOUND",
            "Application not found",
        )
    return status


@router.get(
    "/applications/{application_id}/history",
    response_model=WorkflowHistoryResponse,
)
async def get_application_history(
    application_id: str,
    _caller: CallerIdentity = Depends(require_api_key),
) -> WorkflowHistoryResponse:
    """Get full audit history for an application."""
    application_id = validate_uuid(application_id)
    service = get_service()
    history = await service.get_history(application_id)
    if not history:
        return _error_response(
            404,
            "APPLICATION_NOT_FOUND",
            "Application not found",
        )
    return history


@router.get("/applications", response_model=ListApplicationsResponse)
async def list_applications(
    state: str | None = Query(None, description="Filter by workflow state"),
    risk_level: str | None = Query(None, description="Filter by risk level"),
    final_decision: str | None = Query(None, description="Filter by final decision"),
    q: str | None = Query(None, description="Search by name or application ID"),
    limit: int = Query(20, ge=1, le=100, description="Page size"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
    _caller: CallerIdentity = Depends(require_api_key),
) -> ListApplicationsResponse:
    """List applications with pagination and filtering."""
    valid_states = {s.value for s in WorkflowStateEnum}
    if state and state not in valid_states:
        raise HTTPException(
            status_code=422,
            detail={
                "error_code": "INVALID_STATE",
                "message": f"Invalid state '{state}'. Valid states: {sorted(valid_states)}",
            },
        )

    valid_risk_levels = {r.value for r in RiskLevelEnum}
    if risk_level and risk_level not in valid_risk_levels:
        raise HTTPException(
            status_code=422,
            detail={
                "error_code": "INVALID_RISK_LEVEL",
                "message": (
                    f"Invalid risk_level '{risk_level}'. Valid levels: {sorted(valid_risk_levels)}"
                ),
            },
        )

    valid_decisions = {d.value for d in FinalDecisionEnum}
    if final_decision and final_decision not in valid_decisions:
        raise HTTPException(
            status_code=422,
            detail={
                "error_code": "INVALID_FINAL_DECISION",
                "message": (
                    f"Invalid final_decision '{final_decision}'. "
                    f"Valid decisions: {sorted(valid_decisions)}"
                ),
            },
        )

    service = get_service()
    return await service.list_applications(
        state=state,
        risk_level=risk_level,
        final_decision=final_decision,
        q=q,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/applications/{application_id}/documents",
    response_model=list[DocumentSummaryResponse],
)
async def list_documents(
    application_id: str,
    _caller: CallerIdentity = Depends(require_api_key),
) -> list[DocumentSummaryResponse]:
    """List all documents for an application."""
    application_id = validate_uuid(application_id)
    service = get_service()
    if not await service.application_exists(application_id):
        return _error_response(
            404,
            "APPLICATION_NOT_FOUND",
            "Application not found",
        )
    return await service.get_documents(application_id)


@router.get(
    "/applications/{application_id}/documents/{document_id}",
    response_model=DocumentDetailResponse,
)
async def get_document(
    application_id: str,
    document_id: str,
    _caller: CallerIdentity = Depends(require_api_key),
) -> DocumentDetailResponse:
    """Get detailed information for a single document."""
    application_id = validate_uuid(application_id)
    service = get_service()
    if not await service.application_exists(application_id):
        return _error_response(
            404,
            "APPLICATION_NOT_FOUND",
            "Application not found",
        )
    doc = await service.get_document(application_id, document_id)
    if not doc:
        return _error_response(
            404,
            "DOCUMENT_NOT_FOUND",
            "Document not found",
        )
    return doc


@router.get(
    "/applications/{application_id}/documents/{document_id}/raw-text",
    response_model=RawTextResponse,
)
async def get_document_raw_text(
    application_id: str,
    document_id: str,
    _caller: CallerIdentity = Depends(require_api_key),
) -> RawTextResponse:
    """Get raw OCR text for a document."""
    application_id = validate_uuid(application_id)
    service = get_service()
    if not await service.application_exists(application_id):
        return _error_response(
            404,
            "APPLICATION_NOT_FOUND",
            "Application not found",
        )
    raw = await service.get_raw_text(application_id, document_id)
    if not raw:
        return _error_response(
            404,
            "DOCUMENT_NOT_FOUND",
            "Document not found",
        )
    return raw


@router.post(
    "/applications/{application_id}/documents",
    response_model=DocumentUploadResponse,
    status_code=202,
)
async def upload_document(
    application_id: str,
    file: UploadFile = File(...),
    document_type: str = Form(...),
    _caller: CallerIdentity = Depends(require_api_key),
) -> DocumentUploadResponse:
    """Upload a document for background processing.

    Validates, stores the file, persists a durable 'pending' record,
    then returns 202 Accepted. OCR/processing runs in the background.
    """
    application_id = validate_uuid(application_id)
    service = get_service()
    if not await service.application_exists(application_id):
        return _error_response(
            404,
            "APPLICATION_NOT_FOUND",
            "Application not found",
        )

    from app.config.settings import get_settings
    from app.tools.document_processing import (
        store_uploaded_file,
        validate_file,
    )

    settings = get_settings()

    content = await file.read()

    validation = validate_file(
        file_content=content,
        filename=file.filename or "unknown",
        content_type=file.content_type,
        max_file_size=settings.max_file_size,
    )

    if not validation.valid:
        raise HTTPException(
            status_code=400,
            detail={"error_code": validation.error_code, "message": validation.error_message},
        )

    stored_path, document_id = store_uploaded_file(
        file_content=content,
        original_filename=file.filename or "unknown",
        upload_dir=settings.upload_dir,
        application_id=application_id,
    )

    await service.document_store.save_pending_document(
        document_id=document_id,
        application_id=application_id,
        document_type=document_type,
        original_filename=file.filename or "unknown",
        stored_path=stored_path,
    )

    from app.worker.background import get_worker

    worker = get_worker()
    await worker.submit_ocr_task(
        key=document_id,
        coro=_process_document_background(
            document_id=document_id,
            application_id=application_id,
            document_type=document_type,
            original_filename=file.filename or "unknown",
            stored_path=stored_path,
            max_pdf_pages=settings.max_pdf_pages,
        ),
    )

    return DocumentUploadResponse(
        document_id=document_id,
        application_id=application_id,
        document_type=document_type,
        original_filename=file.filename or "unknown",
        processing_status="processing",
    )


async def _process_document_background(
    *,
    document_id: str,
    application_id: str,
    document_type: str,
    original_filename: str,
    stored_path: str,
    max_pdf_pages: int,
) -> None:
    """Background task: process a document through OCR and field extraction.

    Runs synchronous CPU-bound work (OCR, PDF rendering) in a thread
    via asyncio.to_thread(), then updates the durable document record.
    """
    import asyncio

    from app.audit.logger import AuditLogger
    from app.memory.store import DocumentStore
    from app.models.states import EventType, WorkflowState

    store = DocumentStore()
    audit = AuditLogger()

    try:
        await store.update_document_status(document_id, "processing")

        await audit.record(
            application_id=application_id,
            state=WorkflowState.RECEIVED,
            event_type=EventType.DOCUMENT_PROCESSING_STARTED,
            action="process_document",
            result="STARTED",
            metadata={"document_id": document_id, "document_type": document_type},
        )

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
            action="process_document",
            result=result.processing_status.upper(),
            metadata={
                "document_id": document_id,
                "processing_status": result.processing_status,
                "overall_confidence": result.overall_confidence,
            },
        )

    except Exception as e:
        logger.exception("Background document processing failed for %s", document_id)
        try:
            await store.update_document_status(
                document_id,
                "failed",
                error_code="BACKGROUND_PROCESSING_FAILED",
                error_message=str(e)[:200],
            )
            await audit.record(
                application_id=application_id,
                state=WorkflowState.RECEIVED,
                event_type=EventType.DOCUMENT_PROCESSING_FAILED,
                action="process_document",
                result="ERROR",
                metadata={"document_id": document_id, "error": str(e)[:200]},
            )
        except Exception:
            logger.exception("Failed to persist error state for document %s", document_id)


async def _process_application_background(
    *,
    application_id: str,
    request_data: SubmitApplicationRequest,
) -> None:
    """Background task: run the full onboarding workflow for an application.

    Loads the persisted context, runs the complete verification pipeline
    (validate → extract → compare → risk → LLM → policy → decision),
    and updates the durable state throughout.
    """
    from app.memory.store import WorkflowMemory
    from app.models.states import EventType, WorkflowState
    from app.worker.engine import WorkerEngine

    memory = WorkflowMemory()
    engine = WorkerEngine(memory=memory)

    try:
        context = await memory.get(application_id)
        if context is None:
            logger.error("No persisted context found for application %s", application_id)
            return

        if context.current_state not in (
            WorkflowState.RECEIVED,
            WorkflowState.VERIFYING,
            WorkflowState.TOOL_RETRYING,
        ):
            logger.info(
                "Application %s already in terminal state %s, skipping",
                application_id,
                context.current_state.value,
            )
            return

        await engine.resume_application(context)

    except Exception as e:
        logger.exception("Background workflow failed for application %s", application_id)
        try:
            from app.audit.logger import AuditLogger

            audit = AuditLogger()
            await audit.record(
                application_id=application_id,
                state=WorkflowState.RECEIVED,
                event_type=EventType.FAILURE,
                action="process_application",
                result="ERROR",
                metadata={"error": str(e)[:200]},
            )
        except Exception:
            logger.exception("Failed to persist workflow error for %s", application_id)
