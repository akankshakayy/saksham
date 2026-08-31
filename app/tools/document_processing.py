"""Main document processing pipeline.

Orchestrates file validation, OCR/text extraction, and field extraction
into a single coherent pipeline.
"""
from __future__ import annotations

import logging
import os
import shutil
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from app.tools.field_extraction import FieldExtractionResult, extract_fields
from app.tools.ocr import OCRResult, run_ocr
from app.tools.pdf_processing import (
    PDFExtractionResult,
    extract_text_from_pdf,
    render_pdf_pages,
)

logger = logging.getLogger(__name__)

ALLOWED_MIME_TYPES = {
    "image/jpeg",
    "image/png",
    "application/pdf",
}

ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".pdf"}

DEFAULT_MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB
DEFAULT_MAX_PDF_PAGES = 5


@dataclass
class FileValidationResult:
    """Result of file validation."""
    valid: bool
    error_code: str | None = None
    error_message: str | None = None
    detected_mime: str | None = None
    file_size: int = 0


@dataclass
class DocumentProcessingResult:
    """Complete result of processing a document file."""
    document_id: str
    application_id: str
    document_type: str
    original_filename: str
    stored_path: str
    processing_status: str  # "completed", "failed", "low_confidence"
    raw_text: str
    raw_text_available: bool
    ocr_confidence: float
    field_extraction_confidence: float
    overall_confidence: float
    extracted_fields: dict[str, Any]
    processing_method: str
    error_code: str | None = None
    error_message: str | None = None
    attempt_count: int = 1
    created_at: str = ""
    processed_at: str = ""

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()
        if not self.processed_at:
            self.processed_at = datetime.now(timezone.utc).isoformat()


def validate_file(
    file_content: bytes,
    filename: str,
    content_type: str | None = None,
    max_file_size: int = DEFAULT_MAX_FILE_SIZE,
) -> FileValidationResult:
    """Validate an uploaded file before processing.

    Checks:
    - File is not empty
    - File size is within limits
    - Extension is allowed
    - MIME type is allowed (if provided)
    """
    if not file_content:
        return FileValidationResult(
            valid=False,
            error_code="EMPTY_FILE",
            error_message="File is empty",
        )

    file_size = len(file_content)
    if file_size > max_file_size:
        return FileValidationResult(
            valid=False,
            error_code="FILE_TOO_LARGE",
            error_message=f"File size {file_size} exceeds maximum {max_file_size}",
            file_size=file_size,
        )

    ext = os.path.splitext(filename)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        return FileValidationResult(
            valid=False,
            error_code="UNSUPPORTED_EXTENSION",
            error_message=f"File extension '{ext}' is not supported. Allowed: {ALLOWED_EXTENSIONS}",
            file_size=file_size,
        )

    if content_type and content_type not in ALLOWED_MIME_TYPES:
        return FileValidationResult(
            valid=False,
            error_code="UNSUPPORTED_MIME_TYPE",
            error_message=(
                f"MIME type '{content_type}' is not supported. Allowed: {ALLOWED_MIME_TYPES}"
            ),
            detected_mime=content_type,
            file_size=file_size,
        )

    return FileValidationResult(
        valid=True,
        detected_mime=content_type,
        file_size=file_size,
    )


def store_uploaded_file(
    file_content: bytes,
    original_filename: str,
    upload_dir: str,
    application_id: str,
) -> tuple[str, str]:
    """Store an uploaded file with a unique generated name.

    Returns:
        Tuple of (stored_path, document_id)
    """
    document_id = str(uuid.uuid4())
    ext = os.path.splitext(original_filename)[1].lower()
    stored_filename = f"{application_id}_{document_id}{ext}"

    app_dir = os.path.join(upload_dir, application_id)
    os.makedirs(app_dir, exist_ok=True)

    stored_path = os.path.join(app_dir, stored_filename)
    with open(stored_path, "wb") as f:
        f.write(file_content)

    return stored_path, document_id


def process_document_file(
    file_path: str,
    document_type: str,
    application_id: str,
    document_id: str,
    original_filename: str,
    max_pdf_pages: int = DEFAULT_MAX_PDF_PAGES,
) -> DocumentProcessingResult:
    """Process a document file through the full pipeline.

    1. Detect file type
    2. Extract text (OCR for images, text extraction or OCR for PDFs)
    3. Extract structured fields
    4. Calculate confidence
    """
    ext = os.path.splitext(file_path)[1].lower()

    if ext == ".pdf":
        return _process_pdf(
            file_path, document_type, application_id,
            document_id, original_filename, max_pdf_pages,
        )
    elif ext in (".jpg", ".jpeg", ".png"):
        return _process_image(
            file_path, document_type, application_id,
            document_id, original_filename,
        )
    else:
        return DocumentProcessingResult(
            document_id=document_id,
            application_id=application_id,
            document_type=document_type,
            original_filename=original_filename,
            stored_path=file_path,
            processing_status="failed",
            raw_text="",
            raw_text_available=False,
            ocr_confidence=0.0,
            field_extraction_confidence=0.0,
            overall_confidence=0.0,
            extracted_fields={},
            processing_method="none",
            error_code="UNSUPPORTED_FILE_TYPE",
            error_message=f"File type '{ext}' is not supported",
        )


def _process_image(
    file_path: str,
    document_type: str,
    application_id: str,
    document_id: str,
    original_filename: str,
) -> DocumentProcessingResult:
    """Process an image file through OCR and field extraction."""
    ocr_result = run_ocr(file_path)

    if not ocr_result.success:
        return DocumentProcessingResult(
            document_id=document_id,
            application_id=application_id,
            document_type=document_type,
            original_filename=original_filename,
            stored_path=file_path,
            processing_status="failed",
            raw_text="",
            raw_text_available=False,
            ocr_confidence=0.0,
            field_extraction_confidence=0.0,
            overall_confidence=0.0,
            extracted_fields={},
            processing_method="rapidocr",
            error_code="OCR_FAILED",
            error_message=ocr_result.error,
        )

    field_result = extract_fields(ocr_result.raw_text)

    overall = _calculate_overall_confidence(
        ocr_result.average_confidence,
        field_result.overall_confidence,
        field_result.fields_found,
    )

    status = "completed" if overall >= 0.5 else "low_confidence"

    return DocumentProcessingResult(
        document_id=document_id,
        application_id=application_id,
        document_type=document_type,
        original_filename=original_filename,
        stored_path=file_path,
        processing_status=status,
        raw_text=ocr_result.raw_text,
        raw_text_available=True,
        ocr_confidence=ocr_result.average_confidence,
        field_extraction_confidence=field_result.overall_confidence,
        overall_confidence=overall,
        extracted_fields=field_result.to_dict(),
        processing_method="rapidocr",
    )


def _process_pdf(
    file_path: str,
    document_type: str,
    application_id: str,
    document_id: str,
    original_filename: str,
    max_pdf_pages: int,
) -> DocumentProcessingResult:
    """Process a PDF file: try text extraction first, fall back to OCR."""
    text_result = extract_text_from_pdf(file_path)

    if not text_result.success:
        return DocumentProcessingResult(
            document_id=document_id,
            application_id=application_id,
            document_type=document_type,
            original_filename=original_filename,
            stored_path=file_path,
            processing_status="failed",
            raw_text="",
            raw_text_available=False,
            ocr_confidence=0.0,
            field_extraction_confidence=0.0,
            overall_confidence=0.0,
            extracted_fields={},
            processing_method="pymupdf_text_extraction",
            error_code="PDF_EXTRACTION_FAILED",
            error_message=text_result.error,
        )

    if text_result.raw_text and not text_result.is_scanned:
        field_result = extract_fields(text_result.raw_text)
        overall = _calculate_overall_confidence(
            0.95,  # High confidence for direct text extraction
            field_result.overall_confidence,
            field_result.fields_found,
        )
        return DocumentProcessingResult(
            document_id=document_id,
            application_id=application_id,
            document_type=document_type,
            original_filename=original_filename,
            stored_path=file_path,
            processing_status="completed",
            raw_text=text_result.raw_text,
            raw_text_available=True,
            ocr_confidence=0.95,
            field_extraction_confidence=field_result.overall_confidence,
            overall_confidence=overall,
            extracted_fields=field_result.to_dict(),
            processing_method="pymupdf_text_extraction",
        )

    # Scanned PDF: render pages and OCR
    render_result = render_pdf_pages(file_path, max_pages=max_pdf_pages)
    if not render_result.success:
        return DocumentProcessingResult(
            document_id=document_id,
            application_id=application_id,
            document_type=document_type,
            original_filename=original_filename,
            stored_path=file_path,
            processing_status="failed",
            raw_text="",
            raw_text_available=False,
            ocr_confidence=0.0,
            field_extraction_confidence=0.0,
            overall_confidence=0.0,
            extracted_fields={},
            processing_method="pymupdf_render",
            error_code="PDF_RENDER_FAILED",
            error_message=render_result.error,
        )

    # Determine temp directory for cleanup
    temp_dir = None
    if render_result.rendered_images:
        temp_dir = os.path.dirname(render_result.rendered_images[0])

    try:
        all_text = []
        all_confidences = []
        for img_path in render_result.rendered_images:
            ocr_result = run_ocr(img_path)
            if ocr_result.success and ocr_result.raw_text:
                all_text.append(ocr_result.raw_text)
                all_confidences.append(ocr_result.average_confidence)

        if not all_text:
            return DocumentProcessingResult(
                document_id=document_id,
                application_id=application_id,
                document_type=document_type,
                original_filename=original_filename,
                stored_path=file_path,
                processing_status="failed",
                raw_text="",
                raw_text_available=False,
                ocr_confidence=0.0,
                field_extraction_confidence=0.0,
                overall_confidence=0.0,
                extracted_fields={},
                processing_method="rapidocr_on_rendered_pdf",
                error_code="OCR_FAILED",
                error_message="No text extracted from rendered PDF pages",
            )

        combined_text = "\n\n".join(all_text)
        avg_ocr_conf = sum(all_confidences) / len(all_confidences)
        field_result = extract_fields(combined_text)
        overall = _calculate_overall_confidence(
            avg_ocr_conf,
            field_result.overall_confidence,
            field_result.fields_found,
        )
        status = "completed" if overall >= 0.5 else "low_confidence"

        return DocumentProcessingResult(
            document_id=document_id,
            application_id=application_id,
            document_type=document_type,
            original_filename=original_filename,
            stored_path=file_path,
            processing_status=status,
            raw_text=combined_text,
            raw_text_available=True,
            ocr_confidence=avg_ocr_conf,
            field_extraction_confidence=field_result.overall_confidence,
            overall_confidence=overall,
            extracted_fields=field_result.to_dict(),
            processing_method="rapidocr_on_rendered_pdf",
        )
    finally:
        if temp_dir and os.path.isdir(temp_dir):
            shutil.rmtree(temp_dir, ignore_errors=True)


def _calculate_overall_confidence(
    ocr_confidence: float,
    field_confidence: float,
    fields_found: int,
) -> float:
    """Calculate overall document confidence.

    Heuristic: weighted average of OCR confidence and field extraction confidence,
    penalized if few fields were found.

    OCR confidence: 40% weight
    Field extraction confidence: 40% weight
    Field discovery bonus: 20% weight (scaled by fields found)
    """
    ocr_weight = 0.4
    field_weight = 0.4
    discovery_weight = 0.2

    discovery_score = min(fields_found / 4.0, 1.0)

    overall = (
        ocr_confidence * ocr_weight
        + field_confidence * field_weight
        + discovery_score * discovery_weight
    )

    return min(max(overall, 0.0), 1.0)
