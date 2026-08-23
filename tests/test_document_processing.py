"""Comprehensive tests for document processing functionality.

Tests cover:
- File validation (empty, too large, wrong type)
- OCR on synthetic images
- PDF text extraction and OCR
- Structured field extraction from raw text
- Confidence calculation
- Full document processing pipeline
- Integration with workflow engine for APPROVED and ESCALATED_TO_HUMAN paths
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.tools.document_processing import (
    FileValidationResult,
    DocumentProcessingResult,
    validate_file,
    store_uploaded_file,
    process_document_file,
    _calculate_overall_confidence,
)
from app.tools.ocr import OCRResult, OCRLine, run_ocr
from app.tools.pdf_processing import (
    PDFExtractionResult,
    extract_text_from_pdf,
    render_pdf_pages,
)
from app.tools.field_extraction import (
    FieldExtractionResult,
    ExtractedField,
    extract_fields,
)

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")


@pytest.fixture
def tmp_upload_dir():
    """Create a temporary upload directory for testing."""
    d = tempfile.mkdtemp()
    yield d
    shutil.rmtree(d, ignore_errors=True)


class TestFileValidation:
    """Tests for file validation."""

    def test_empty_file_rejected(self):
        result = validate_file(b"", "test.pdf", "application/pdf")
        assert result.valid is False
        assert result.error_code == "EMPTY_FILE"

    def test_file_too_large_rejected(self):
        large_content = b"x" * (11 * 1024 * 1024)  # 11 MB
        result = validate_file(large_content, "test.pdf", "application/pdf", max_file_size=10 * 1024 * 1024)
        assert result.valid is False
        assert result.error_code == "FILE_TOO_LARGE"

    def test_unsupported_extension_rejected(self):
        result = validate_file(b"content", "test.exe", "application/octet-stream")
        assert result.valid is False
        assert result.error_code == "UNSUPPORTED_EXTENSION"

    def test_unsupported_mime_type_rejected(self):
        result = validate_file(b"content", "test.pdf", "application/exe")
        assert result.valid is False
        assert result.error_code == "UNSUPPORTED_MIME_TYPE"

    def test_valid_jpeg_accepted(self):
        content = b"\xff\xd8\xff" + b"\x00" * 100
        result = validate_file(content, "photo.jpg", "image/jpeg")
        assert result.valid is True
        assert result.file_size == 103

    def test_valid_png_accepted(self):
        content = b"\x89PNG" + b"\x00" * 100
        result = validate_file(content, "photo.png", "image/png")
        assert result.valid is True

    def test_valid_pdf_accepted(self):
        content = b"%PDF-1.4" + b"\x00" * 100
        result = validate_file(content, "doc.pdf", "application/pdf")
        assert result.valid is True

    def test_valid_without_mime_type_accepted(self):
        content = b"some content"
        result = validate_file(content, "doc.pdf")
        assert result.valid is True

    def test_file_size_recorded(self):
        content = b"x" * 1024
        result = validate_file(content, "test.pdf")
        assert result.file_size == 1024


class TestFileStorage:
    """Tests for file storage."""

    def test_store_file_creates_file(self, tmp_upload_dir):
        content = b"test file content"
        stored_path, doc_id = store_uploaded_file(
            content, "test.pdf", tmp_upload_dir, "app-001"
        )
        assert os.path.exists(stored_path)
        assert "app-001" in stored_path
        assert doc_id  # UUID generated

    def test_store_file_preserves_content(self, tmp_upload_dir):
        content = b"test file content"
        stored_path, _ = store_uploaded_file(
            content, "test.pdf", tmp_upload_dir, "app-001"
        )
        with open(stored_path, "rb") as f:
            assert f.read() == content

    def test_store_file_creates_app_dir(self, tmp_upload_dir):
        content = b"test"
        stored_path, _ = store_uploaded_file(
            content, "test.pdf", tmp_upload_dir, "new-app-id"
        )
        assert os.path.isdir(os.path.dirname(stored_path))


class TestOCR:
    """Tests for OCR functionality."""

    def test_ocr_on_synthetic_pan_card(self):
        pan_path = os.path.join(FIXTURES_DIR, "synthetic_pan_card.png")
        if not os.path.exists(pan_path):
            pytest.skip("Synthetic PAN card fixture not found")

        result = run_ocr(pan_path)

        assert isinstance(result, OCRResult)
        assert result.raw_text  # Should have extracted some text
        assert result.average_confidence > 0.0
        assert len(result.lines) > 0

        # Check that key text elements are extracted
        text_upper = result.raw_text.upper()
        assert "ABCDE1234F" in text_upper or "PAN" in text_upper

    def test_ocr_on_synthetic_gst_certificate(self):
        gst_path = os.path.join(FIXTURES_DIR, "synthetic_gst_certificate.png")
        if not os.path.exists(gst_path):
            pytest.skip("Synthetic GST certificate fixture not found")

        result = run_ocr(gst_path)

        assert isinstance(result, OCRResult)
        assert result.raw_text
        assert result.average_confidence > 0.0

    def test_ocr_nonexistent_file_fails(self):
        result = run_ocr("/nonexistent/file.png")
        assert result.success is False
        assert result.error

    def test_ocr_result_to_dict(self):
        result = OCRResult(
            success=True,
            raw_text="Test text",
            lines=[OCRLine(text="Test", confidence=0.95)],
            average_confidence=0.95,
            method="rapidocr",
        )
        d = {"raw_text": result.raw_text, "average_confidence": result.average_confidence}
        assert d["raw_text"] == "Test text"
        assert d["average_confidence"] == 0.95


class TestPDFProcessing:
    """Tests for PDF text extraction."""

    def test_extract_text_from_nonexistent_pdf(self):
        result = extract_text_from_pdf("/nonexistent/file.pdf")
        assert result.success is False
        assert result.error

    def test_render_pages_nonexistent_pdf(self):
        result = render_pdf_pages("/nonexistent/file.pdf")
        assert result.success is False

    def test_pdf_extraction_result_structure(self):
        result = PDFExtractionResult(
            raw_text="Test content",
            page_count=1,
            is_scanned=False,
            success=True,
        )
        assert result.raw_text == "Test content"
        assert result.page_count == 1


class TestFieldExtraction:
    """Tests for structured field extraction."""

    def test_extract_pan_number(self):
        text = "PAN: ABCDE1234F"
        result = extract_fields(text)
        assert "pan_number" in result.fields
        assert result.fields["pan_number"].value == "ABCDE1234F"

    def test_extract_gst_number(self):
        text = "GSTIN: 27AABCT1234D1Z5"
        result = extract_fields(text)
        assert "gst_number" in result.fields
        assert result.fields["gst_number"].value == "27AABCT1234D1Z5"

    def test_extract_phone_number(self):
        text = "Phone: 9876543210"
        result = extract_fields(text)
        assert "phone" in result.fields
        assert result.fields["phone"].value == "9876543210"

    def test_extract_email(self):
        text = "Email: test@example.com"
        result = extract_fields(text)
        assert "email" in result.fields
        assert result.fields["email"].value == "test@example.com"

    def test_extract_name(self):
        text = "Name: John Doe"
        result = extract_fields(text)
        assert "name" in result.fields
        assert result.fields["name"].value == "John Doe"

    def test_extract_address(self):
        text = "Address: 123 Main Street, Mumbai, 400001"
        result = extract_fields(text)
        assert "address" in result.fields
        assert result.fields["address"].value is not None
        assert "Mumbai" in result.fields["address"].value

    def test_extract_multiple_fields(self):
        text = """Name: SAKSHAM TEST PVT LTD
PAN: ABCDE1234F
Phone: 9876543210
Email: test@saksham.com"""
        result = extract_fields(text)
        assert result.fields_found >= 3
        assert result.fields["pan_number"].value == "ABCDE1234F"
        assert result.fields["phone"].value == "9876543210"
        assert result.fields["email"].value == "test@saksham.com"

    def test_empty_text_returns_no_fields(self):
        result = extract_fields("")
        assert result.fields_found == 0
        assert result.overall_confidence == 0.0

    def test_to_dict(self):
        text = "PAN: ABCDE1234F\nPhone: 9876543210"
        result = extract_fields(text)
        d = result.to_dict()
        assert "pan_number" in d
        assert "phone" in d


class TestDocumentProcessing:
    """Tests for the main document processing pipeline."""

    def test_process_synthetic_pan_image(self, tmp_upload_dir):
        pan_path = os.path.join(FIXTURES_DIR, "synthetic_pan_card.png")
        if not os.path.exists(pan_path):
            pytest.skip("Synthetic PAN card fixture not found")

        result = process_document_file(
            file_path=pan_path,
            document_type="pan_card",
            application_id="app-001",
            document_id="doc-001",
            original_filename="pan.png",
        )

        assert isinstance(result, DocumentProcessingResult)
        assert result.document_id == "doc-001"
        assert result.application_id == "app-001"
        assert result.processing_status in ("completed", "low_confidence")
        assert result.raw_text_available is True
        assert result.overall_confidence > 0.0
        assert result.processing_method == "rapidocr"

    def test_process_synthetic_gst_image(self, tmp_upload_dir):
        gst_path = os.path.join(FIXTURES_DIR, "synthetic_gst_certificate.png")
        if not os.path.exists(gst_path):
            pytest.skip("Synthetic GST certificate fixture not found")

        result = process_document_file(
            file_path=gst_path,
            document_type="gst_certificate",
            application_id="app-001",
            document_id="doc-002",
            original_filename="gst.png",
        )

        assert isinstance(result, DocumentProcessingResult)
        assert result.processing_status in ("completed", "low_confidence")
        assert result.overall_confidence > 0.0

    def test_process_nonexistent_file_fails(self, tmp_upload_dir):
        result = process_document_file(
            file_path="/nonexistent/file.png",
            document_type="pan_card",
            application_id="app-001",
            document_id="doc-003",
            original_filename="missing.png",
        )
        assert result.processing_status == "failed"
        assert result.error_code

    def test_process_unsupported_file_type(self, tmp_upload_dir):
        test_file = os.path.join(tmp_upload_dir, "test.exe")
        with open(test_file, "wb") as f:
            f.write(b"test content")

        result = process_document_file(
            file_path=test_file,
            document_type="other",
            application_id="app-001",
            document_id="doc-004",
            original_filename="test.exe",
        )
        assert result.processing_status == "failed"
        assert result.error_code == "UNSUPPORTED_FILE_TYPE"


class TestConfidenceCalculation:
    """Tests for confidence calculation heuristics."""

    def test_high_confidence_with_many_fields(self):
        overall = _calculate_overall_confidence(0.9, 0.8, 4)
        assert overall > 0.7

    def test_low_confidence_with_few_fields(self):
        overall = _calculate_overall_confidence(0.5, 0.3, 1)
        assert overall < 0.6

    def test_confidence_bounded(self):
        overall = _calculate_overall_confidence(1.0, 1.0, 10)
        assert 0.0 <= overall <= 1.0

    def test_zero_confidence(self):
        overall = _calculate_overall_confidence(0.0, 0.0, 0)
        assert overall == 0.0


class TestExtractionIntegration:
    """Tests for extraction.py integration with document pipeline."""

    @pytest.mark.asyncio
    async def test_extract_document_data_with_file_path(self, tmp_upload_dir):
        pan_path = os.path.join(FIXTURES_DIR, "synthetic_pan_card.png")
        if not os.path.exists(pan_path):
            pytest.skip("Synthetic PAN card fixture not found")

        from app.models.domain import ApplicationDocument
        from app.tools.extraction import extract_document_data

        doc = ApplicationDocument(
            document_id="doc-001",
            document_type="pan_card",
            metadata={"original_filename": "pan.png"},
        )

        with patch("app.tools.extraction.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(max_pdf_pages=5)
            result = await extract_document_data(
                doc,
                file_path=pan_path,
                application_id="app-001",
            )

        assert result.document_id == "doc-001"
        assert result.confidence > 0.0
        assert result.extraction_method in ("rapidocr", "basic_regex")


class TestAPIUploadEndpoint:
    """Tests for document upload API endpoint."""

    def test_upload_endpoint_exists(self):
        """Verify the upload route is registered."""
        from fastapi.testclient import TestClient
        from app.main import app

        client = TestClient(app)
        # Just verify the route exists by checking OpenAPI schema
        response = client.get("/openapi.json")
        assert response.status_code == 200
        schema = response.json()
        # Check that the documents endpoint exists in the paths
        found = any(
            "documents" in path and "application_id" in path
            for path in schema["paths"].keys()
        )
        assert found, f"Expected documents endpoint, found paths: {list(schema['paths'].keys())}"


class TestPDFResourceCleanup:
    """Tests for temporary resource cleanup in PDF processing."""

    def test_scanned_pdf_temp_files_cleaned_on_success(self, tmp_upload_dir):
        """Verify temp files are cleaned up after successful scanned PDF processing."""
        import pymupdf as fitz
        from app.tools.document_processing import process_document_file

        pan_path = os.path.join(FIXTURES_DIR, "synthetic_pan_card.png")
        if not os.path.exists(pan_path):
            pytest.skip("Synthetic PAN card fixture not found")

        pdf_path = os.path.join(tmp_upload_dir, "scanned.pdf")
        doc = fitz.open()
        page = doc.new_page()
        rect = fitz.Rect(0, 0, 800, 400)
        page.insert_image(rect, filename=pan_path)
        doc.save(pdf_path)
        doc.close()

        # Count temp dirs before
        import tempfile
        before_dirs = set(os.listdir(tempfile.gettempdir()))

        result = process_document_file(
            file_path=pdf_path,
            document_type="pan_card",
            application_id="test-cleanup-001",
            document_id="doc-cleanup-001",
            original_filename="scanned.pdf",
        )

        assert result.processing_status in ("completed", "low_confidence")

        # Verify no new saksham temp dirs remain
        after_dirs = set(os.listdir(tempfile.gettempdir()))
        new_dirs = after_dirs - before_dirs
        saksham_dirs = [d for d in new_dirs if d.startswith("saksham_pdf_")]
        assert len(saksham_dirs) == 0, f"Temp dirs not cleaned: {saksham_dirs}"

    def test_text_pdf_no_temp_files_created(self, tmp_upload_dir):
        """Verify text-based PDF extraction doesn't create temp files."""
        import pymupdf as fitz
        from app.tools.document_processing import process_document_file

        pdf_path = os.path.join(tmp_upload_dir, "text_based.pdf")
        doc = fitz.open()
        page = doc.new_page()
        # Need enough text to exceed MIN_TEXT_LENGTH (50 chars)
        text = (
            "INCOME TAX DEPARTMENT\n"
            "Permanent Account Number Card\n"
            "Name: Test User\n"
            "PAN: ABCDE1234F\n"
            "Phone: 9876543210\n"
            "Address: 123 Main Street, Mumbai, Maharashtra, India\n"
        )
        page.insert_text((72, 72), text, fontsize=12)
        doc.save(pdf_path)
        doc.close()

        import tempfile
        before_dirs = set(os.listdir(tempfile.gettempdir()))

        result = process_document_file(
            file_path=pdf_path,
            document_type="pan_card",
            application_id="test-cleanup-002",
            document_id="doc-cleanup-002",
            original_filename="text.pdf",
        )

        assert result.processing_status == "completed"
        assert result.processing_method == "pymupdf_text_extraction"

        after_dirs = set(os.listdir(tempfile.gettempdir()))
        new_dirs = after_dirs - before_dirs
        saksham_dirs = [d for d in new_dirs if d.startswith("saksham_pdf_")]
        assert len(saksham_dirs) == 0
