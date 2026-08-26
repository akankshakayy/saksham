from __future__ import annotations

import logging

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import JSONResponse

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


@router.post("/applications", response_model=SubmitApplicationResponse)
async def submit_application(
    request: SubmitApplicationRequest,
) -> SubmitApplicationResponse:
    """Submit a new onboarding application for processing."""
    service = get_service()
    try:
        result = await service.submit_application(request)
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
) -> ApplicationStatusResponse:
    """Get current status of an application."""
    service = get_service()
    status = await service.get_status(application_id)
    if not status:
        return _error_response(
            404,
            "APPLICATION_NOT_FOUND",
            f"Application with id '{application_id}' not found",
        )
    return status


@router.get(
    "/applications/{application_id}/history",
    response_model=WorkflowHistoryResponse,
)
async def get_application_history(
    application_id: str,
) -> WorkflowHistoryResponse:
    """Get full audit history for an application."""
    service = get_service()
    history = await service.get_history(application_id)
    if not history:
        return _error_response(
            404,
            "APPLICATION_NOT_FOUND",
            f"Application with id '{application_id}' not found",
        )
    return history


@router.get("/applications", response_model=ListApplicationsResponse)
async def list_applications(
    state: str | None = Query(None, description="Filter by workflow state"),
    risk_level: str | None = Query(None, description="Filter by risk level"),
    final_decision: str | None = Query(None, description="Filter by final decision"),
    limit: int = Query(20, ge=1, le=100, description="Page size"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
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
        limit=limit,
        offset=offset,
    )


@router.get(
    "/applications/{application_id}/documents",
    response_model=list[DocumentSummaryResponse],
)
async def list_documents(
    application_id: str,
) -> list[DocumentSummaryResponse]:
    """List all documents for an application."""
    service = get_service()
    if not await service.application_exists(application_id):
        return _error_response(
            404,
            "APPLICATION_NOT_FOUND",
            f"Application with id '{application_id}' not found",
        )
    return await service.get_documents(application_id)


@router.get(
    "/applications/{application_id}/documents/{document_id}",
    response_model=DocumentDetailResponse,
)
async def get_document(
    application_id: str,
    document_id: str,
) -> DocumentDetailResponse:
    """Get detailed information for a single document."""
    service = get_service()
    if not await service.application_exists(application_id):
        return _error_response(
            404,
            "APPLICATION_NOT_FOUND",
            f"Application with id '{application_id}' not found",
        )
    doc = await service.get_document(application_id, document_id)
    if not doc:
        return _error_response(
            404,
            "DOCUMENT_NOT_FOUND",
            f"Document with id '{document_id}' not found",
        )
    return doc


@router.get(
    "/applications/{application_id}/documents/{document_id}/raw-text",
    response_model=RawTextResponse,
)
async def get_document_raw_text(
    application_id: str,
    document_id: str,
) -> RawTextResponse:
    """Get raw OCR text for a document."""
    service = get_service()
    if not await service.application_exists(application_id):
        return _error_response(
            404,
            "APPLICATION_NOT_FOUND",
            f"Application with id '{application_id}' not found",
        )
    raw = await service.get_raw_text(application_id, document_id)
    if not raw:
        return _error_response(
            404,
            "DOCUMENT_NOT_FOUND",
            f"Document with id '{document_id}' not found",
        )
    return raw


@router.post(
    "/applications/{application_id}/documents",
    response_model=DocumentUploadResponse,
)
async def upload_document(
    application_id: str,
    file: UploadFile = File(...),
    document_type: str = Form(...),
) -> DocumentUploadResponse:
    """Upload and process a document for an application."""
    service = get_service()
    if not await service.application_exists(application_id):
        return _error_response(
            404,
            "APPLICATION_NOT_FOUND",
            f"Application with id '{application_id}' not found",
        )

    from app.config.settings import get_settings
    from app.tools.document_processing import (
        process_document_file,
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

    result = process_document_file(
        file_path=stored_path,
        document_type=document_type,
        application_id=application_id,
        document_id=document_id,
        original_filename=file.filename or "unknown",
        max_pdf_pages=settings.max_pdf_pages,
    )

    await service.document_store.save_document(result)

    return DocumentUploadResponse(
        document_id=result.document_id,
        application_id=result.application_id,
        document_type=result.document_type,
        original_filename=result.original_filename,
        processing_status=result.processing_status,
        overall_confidence=result.overall_confidence,
        ocr_confidence=result.ocr_confidence,
        field_extraction_confidence=result.field_extraction_confidence,
        extracted_fields=result.extracted_fields,
        processing_method=result.processing_method,
        error_code=result.error_code,
        error_message=result.error_message,
    )
