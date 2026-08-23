from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, UploadFile, File, Form

from app.memory.errors import PersistenceError
from app.models.schemas import (
    ApplicationStatusResponse,
    HealthResponse,
    SubmitApplicationRequest,
    SubmitApplicationResponse,
    WorkflowHistoryResponse,
)
from app.services.onboarding import OnboardingService

logger = logging.getLogger(__name__)

router = APIRouter()

_service: OnboardingService | None = None


def get_service() -> OnboardingService:
    global _service
    if _service is None:
        _service = OnboardingService()
    return _service


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
        raise HTTPException(
            status_code=503,
            detail={
                "error_code": "PERSISTENCE_FAILURE",
                "message": "Application could not be saved. Please try again.",
            },
        )
    except Exception as exc:
        logger.error("Application submission failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


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
        raise HTTPException(status_code=404, detail="Application not found")
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
        raise HTTPException(status_code=404, detail="Application not found")
    return history


@router.get("/applications")
async def list_applications() -> list[dict]:
    """List all applications."""
    service = get_service()
    return await service.list_applications()


@router.post("/applications/{application_id}/documents")
async def upload_document(
    application_id: str,
    file: UploadFile = File(...),
    document_type: str = Form(...),
) -> dict:
    """Upload and process a document for an application.

    Stores the file, runs OCR/field extraction pipeline, and returns results.
    """
    from app.config.settings import get_settings
    from app.tools.document_processing import (
        validate_file,
        store_uploaded_file,
        process_document_file,
    )
    from app.memory.database import get_database

    settings = get_settings()

    # Read file content
    content = await file.read()

    # Validate file
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

    # Store file
    stored_path, document_id = store_uploaded_file(
        file_content=content,
        original_filename=file.filename or "unknown",
        upload_dir=settings.upload_dir,
        application_id=application_id,
    )

    # Process document
    result = process_document_file(
        file_path=stored_path,
        document_type=document_type,
        application_id=application_id,
        document_id=document_id,
        original_filename=file.filename or "unknown",
        max_pdf_pages=settings.max_pdf_pages,
    )

    # Store result in database
    db = get_database()
    import json
    await db.conn.execute(
        """INSERT INTO documents
        (document_id, application_id, document_type, original_filename,
         stored_path, processing_status, raw_text, raw_text_available,
         ocr_confidence, field_extraction_confidence, overall_confidence,
         extracted_fields_json, processing_method, error_code, error_message,
         attempt_count, created_at, processed_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            result.document_id,
            result.application_id,
            result.document_type,
            result.original_filename,
            result.stored_path,
            result.processing_status,
            result.raw_text,
            1 if result.raw_text_available else 0,
            result.ocr_confidence,
            result.field_extraction_confidence,
            result.overall_confidence,
            json.dumps(result.extracted_fields),
            result.processing_method,
            result.error_code,
            result.error_message,
            result.attempt_count,
            result.created_at,
            result.processed_at,
        ),
    )
    await db.conn.commit()

    return {
        "document_id": result.document_id,
        "application_id": result.application_id,
        "document_type": result.document_type,
        "processing_status": result.processing_status,
        "overall_confidence": result.overall_confidence,
        "ocr_confidence": result.ocr_confidence,
        "field_extraction_confidence": result.field_extraction_confidence,
        "extracted_fields": result.extracted_fields,
        "processing_method": result.processing_method,
        "error_code": result.error_code,
        "error_message": result.error_message,
    }
