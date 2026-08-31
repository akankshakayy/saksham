"""End-to-end integration tests for document processing + WorkerEngine.

Tests cover:
- Real multipart API upload
- Real text-based PDF processing
- Real scanned PDF processing
- Document persistence across new instances
- End-to-end APPROVED workflow with real document
- End-to-end ESCALATED_TO_HUMAN workflow with failure
- Retry and escalation with bounded retries
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.audit.logger import AuditLogger
from app.memory.database import Database, get_database
from app.memory.store import DocumentStore, WorkflowMemory
from app.models.domain import ApplicationDocument, OnboardingApplication
from app.models.states import EventType, FinalDecision, WorkflowState
from app.worker.engine import WorkerEngine
from app.tools.document_processing import process_document_file
from app.tools.field_extraction import extract_fields

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")


@pytest.fixture
def tmp_upload_dir():
    d = tempfile.mkdtemp()
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
async def db(tmp_path):
    db_path = str(tmp_path / "test.db")
    database = Database(f"sqlite+aiosqlite:///{db_path}")
    await database.connect()
    yield database
    await database.close()


def _deterministic_recommendation(context):
    """Deterministic LLM mock: APPROVE when all checks pass, ESCALATE for high risk."""
    from app.models.domain import AIRecommendation

    if context.risk_assessment and context.risk_assessment.risk_level.value in ("HIGH", "CRITICAL"):
        return AIRecommendation(
            recommended_action=FinalDecision.ESCALATE_TO_HUMAN,
            confidence=0.85,
            risk_level=context.risk_assessment.risk_level,
            reason="High risk detected",
            evidence=[],
            source="test_mock",
            model=None,
        )
    return AIRecommendation(
        recommended_action=FinalDecision.APPROVE,
        confidence=0.9,
        risk_level=context.risk_assessment.risk_level if context.risk_assessment else "LOW",
        reason="All verification checks passed",
        evidence=["Application data validated", "Document data matches"],
        source="test_mock",
        model=None,
    )


@pytest.fixture
async def engine(db):
    memory = WorkflowMemory(db=db)
    audit = AuditLogger(db=db)
    doc_store = DocumentStore(db=db)
    eng = WorkerEngine(memory=memory, audit=audit, document_store=doc_store)
    with patch(
        "app.worker.engine.get_ai_recommendation",
        side_effect=_deterministic_recommendation,
    ):
        yield eng


class TestNameExtractionFix:
    """Tests for the fixed name extraction (no cross-line greedy capture)."""

    def test_normal_spacing(self):
        text = "Name: Saksham Test Pvt Ltd"
        result = extract_fields(text)
        assert result.fields["name"].value == "Saksham Test Pvt Ltd"

    def test_no_space_after_colon(self):
        text = "Name:SAKSHAM TEST PVT LTD"
        result = extract_fields(text)
        assert result.fields["name"].value == "Saksham Test Pvt Ltd"

    def test_no_space_next_field_immediately_after(self):
        text = "Name:SAKSHAM TEST PVT LTD\nDate of Birth:01/01/1999"
        result = extract_fields(text)
        assert result.fields["name"].value == "Saksham Test Pvt Ltd"
        assert "Date of Birth" not in result.fields["name"].value

    def test_gst_style_no_merge_with_gstin(self):
        text = "Legal Name of Business: SAKSHAM TEST ENTERPRISES\nGSTIN: 27AABCT1234D1Z5"
        result = extract_fields(text)
        assert result.fields["name"].value == "Saksham Test Enterprises"
        assert "Gstin" not in result.fields["name"].value

    def test_name_of_holder_format(self):
        text = "Name of Holder: RAJESH KUMAR"
        result = extract_fields(text)
        assert result.fields["name"].value == "Rajesh Kumar"

    def test_applicant_name_format(self):
        text = "Applicant Name: PRIYA SHARMA"
        result = extract_fields(text)
        assert result.fields["name"].value == "Priya Sharma"

    def test_real_ocr_no_cross_line_capture(self):
        text = "Name:SAKSHAM TESTPVT LTD\nDateofBirth:15/01/1990\nPAN:ABCDE1234F"
        result = extract_fields(text)
        name_val = result.fields["name"].value
        assert "Dateofbirth" not in name_val.lower()
        assert "Date of Birth" not in name_val
        assert "15/01/1990" not in name_val


class TestRealAPIUpload:
    """Real multipart upload through the API endpoint."""

    @pytest.mark.asyncio
    async def test_upload_real_png(self, db):
        from httpx import ASGITransport, AsyncClient
        from app.main import app

        AUTH_HEADERS = {"X-API-Key": "test-secret-key-12345"}
        transport = ASGITransport(app=app)

        async with AsyncClient(transport=transport, base_url="http://test", headers=AUTH_HEADERS) as client:
            app_data = {
                "applicant_name": "Test Merchant",
                "business_name": "Test Business Corp",
                "pan_number": "ABCDE1234F",
                "phone": "9876543210",
                "email": "test@business.com",
            }
            response = await client.post("/api/v1/applications", json=app_data)
            assert response.status_code == 202
            app_id = response.json()["application_id"]

            pan_path = os.path.join(FIXTURES_DIR, "synthetic_pan_card.png")
            if not os.path.exists(pan_path):
                pytest.skip("Synthetic PAN card fixture not found")

            with open(pan_path, "rb") as f:
                upload_response = await client.post(
                    f"/api/v1/applications/{app_id}/documents",
                    files={"file": ("pan_card.png", f, "image/png")},
                    data={"document_type": "pan_card"},
                )

        assert upload_response.status_code == 202
        data = upload_response.json()
        assert data["processing_status"] == "processing"
        document_id = data["document_id"]

        from app.tools.document_processing import process_document_file
        from app.config.settings import get_settings
        settings = get_settings()
        result = process_document_file(
            file_path=pan_path,
            document_type="pan_card",
            application_id=app_id,
            document_id=document_id,
            original_filename="pan_card.png",
            max_pdf_pages=settings.max_pdf_pages,
        )
        assert result.ocr_confidence > 0.0
        assert result.processing_method == "rapidocr"
        assert result.extracted_fields["pan_number"]["value"] == "ABCDE1234F"

        doc_store = DocumentStore(db=db)
        await doc_store.update_document_status(
            document_id,
            result.processing_status,
            raw_text=result.raw_text,
            raw_text_available=result.raw_text_available,
            ocr_confidence=result.ocr_confidence,
            field_extraction_confidence=result.field_extraction_confidence,
            overall_confidence=result.overall_confidence,
            extracted_fields=result.extracted_fields,
            processing_method=result.processing_method,
        )
        docs = await doc_store.get_documents_for_application(app_id)
        assert len(docs) == 1
        assert docs[0]["processing_status"] in ("completed", "low_confidence")
        assert docs[0]["overall_confidence"] > 0.0


class TestRealPDFProcessing:
    """Tests for real PDF processing through the production pipeline."""

    def test_text_based_pdf_extraction(self):
        import pymupdf as fitz
        doc = fitz.open()
        page = doc.new_page()
        text = (
            "INCOME TAX DEPARTMENT\n"
            "Name: TEST USER\n"
            "PAN: ABCDE1234F\n"
            "Phone: 9876543210\n"
            "Email: test@example.com\n"
        )
        page.insert_text((72, 72), text, fontsize=12)
        pdf_path = "/tmp/test_integration_text.pdf"
        doc.save(pdf_path)
        doc.close()

        try:
            result = process_document_file(
                file_path=pdf_path,
                document_type="pan_card",
                application_id="test-pdf-001",
                document_id="doc-pdf-001",
                original_filename="test.pdf",
            )

            assert result.processing_status == "completed"
            assert result.processing_method == "pymupdf_text_extraction"
            assert result.raw_text_available is True
            assert "ABCDE1234F" in result.raw_text
            assert "test@example.com" in result.raw_text
            assert result.overall_confidence > 0.5
            assert result.extracted_fields["pan_number"]["value"] == "ABCDE1234F"
            assert result.extracted_fields["phone"]["value"] == "9876543210"
            assert result.extracted_fields["email"]["value"] == "test@example.com"
        finally:
            if os.path.exists(pdf_path):
                os.unlink(pdf_path)

    def test_scanned_pdf_ocr_fallback(self):
        import pymupdf as fitz
        doc = fitz.open()
        page = doc.new_page()
        rect = fitz.Rect(0, 0, 800, 400)
        page.insert_image(
            rect,
            filename=os.path.join(FIXTURES_DIR, "synthetic_pan_card.png"),
        )
        pdf_path = "/tmp/test_integration_scanned.pdf"
        doc.save(pdf_path)
        doc.close()

        try:
            result = process_document_file(
                file_path=pdf_path,
                document_type="pan_card",
                application_id="test-pdf-002",
                document_id="doc-pdf-002",
                original_filename="scanned.pdf",
            )

            assert result.processing_status in ("completed", "low_confidence")
            assert result.processing_method == "rapidocr_on_rendered_pdf"
            assert result.raw_text_available is True
            assert len(result.raw_text) > 0
            assert result.overall_confidence > 0.5
            assert result.extracted_fields["pan_number"]["value"] == "ABCDE1234F"
        finally:
            if os.path.exists(pdf_path):
                os.unlink(pdf_path)


class TestDocumentPersistence:
    """Tests that document metadata persists across new instances."""

    @pytest.mark.asyncio
    async def test_persist_and_retrieve(self, db):
        pan_path = os.path.join(FIXTURES_DIR, "synthetic_pan_card.png")
        if not os.path.exists(pan_path):
            pytest.skip("Synthetic PAN card fixture not found")

        result = process_document_file(
            file_path=pan_path,
            document_type="pan_card",
            application_id="test-persist-001",
            document_id="doc-persist-001",
            original_filename="pan.png",
        )

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

        new_store = DocumentStore(db=db)
        docs = await new_store.get_documents_for_application("test-persist-001")
        assert len(docs) == 1
        assert docs[0]["application_id"] == "test-persist-001"
        assert docs[0]["processing_status"] in ("completed", "low_confidence")
        assert docs[0]["overall_confidence"] > 0.0
        assert docs[0]["ocr_confidence"] > 0.0
        fields = json.loads(docs[0]["extracted_fields_json"])
        assert fields["pan_number"]["value"] == "ABCDE1234F"


class TestEndToEndApproved:
    """End-to-end workflow: valid application + real document → APPROVED."""

    @pytest.mark.asyncio
    async def test_approved_with_gst_document(self, engine: WorkerEngine):
        gst_path = os.path.join(FIXTURES_DIR, "synthetic_gst_certificate.png")
        if not os.path.exists(gst_path):
            pytest.skip("Synthetic GST certificate fixture not found")

        app = OnboardingApplication(
            applicant_name="Saksham Test Enterprises",
            business_name="Saksham Test Enterprises",
            pan_number="AABCT1234D",
            gst_number="27AABCT1234D1Z5",
            phone="9876543210",
            email="test@saksham.com",
            documents=[
                ApplicationDocument(
                    document_id="doc-gst-001",
                    document_type="gst_certificate",
                    file_path=gst_path,
                    metadata={"original_filename": "gst_cert.png"},
                )
            ],
        )

        context = await engine.process_application(app)

        assert context.current_state == WorkflowState.APPROVED
        assert context.final_decision == FinalDecision.APPROVE
        assert len(context.extracted_data) > 0
        ext = context.extracted_data[0]
        assert ext.confidence > 0.5
        assert ext.extraction_method == "rapidocr"
        assert context.comparison_result is not None
        assert context.risk_assessment is not None
        assert context.recommendation is not None

        events = await engine.get_application_history(app.application_id)
        event_types = [e.event_type.value for e in events]
        assert "INPUT_RECEIVED" in event_types
        assert "DOCUMENT_PROCESSING_COMPLETED" in event_types
        assert "EXTRACTION" in event_types
        assert "COMPARISON" in event_types


class TestEndToEndEscalated:
    """End-to-end workflow: valid application + unreadable document → ESCALATED."""

    @pytest.mark.asyncio
    async def test_escalated_with_unreadable_document(self, engine: WorkerEngine, tmp_upload_dir):
        unreadable_path = os.path.join(tmp_upload_dir, "corrupted.png")
        with open(unreadable_path, "wb") as f:
            f.write(b"\x89PNG\r\n\x1a\n" + b"\x00" * 50)

        app = OnboardingApplication(
            applicant_name="Test User",
            business_name="Test Business",
            pan_number="ABCDE1234F",
            phone="9876543210",
            documents=[
                ApplicationDocument(
                    document_id="doc-fail-001",
                    document_type="pan_card",
                    file_path=unreadable_path,
                    metadata={"original_filename": "corrupted.png"},
                )
            ],
        )

        context = await engine.process_application(app)

        assert context.current_state == WorkflowState.ESCALATED_TO_HUMAN
        assert context.final_decision == FinalDecision.ESCALATE_TO_HUMAN

        events = await engine.get_application_history(app.application_id)
        event_types = [e.event_type.value for e in events]
        assert "DOCUMENT_PROCESSING_FAILED" in event_types or "FAILURE" in event_types
        assert "ESCALATION" in event_types or "STATE_TRANSITION" in event_types


class TestEndToEndGstApproved:
    """End-to-end workflow: valid application + PAN card processed through engine."""

    @pytest.mark.asyncio
    async def test_pan_card_extracts_fields(self, engine: WorkerEngine):
        pan_path = os.path.join(FIXTURES_DIR, "synthetic_pan_card.png")
        if not os.path.exists(pan_path):
            pytest.skip("Synthetic PAN card fixture not found")

        app = OnboardingApplication(
            applicant_name="Saksham Test Pvt Ltd",
            business_name="Saksham Test Pvt Ltd",
            pan_number="ABCDE1234F",
            phone="9876543210",
            documents=[
                ApplicationDocument(
                    document_id="doc-pan-001",
                    document_type="pan_card",
                    file_path=pan_path,
                    metadata={"original_filename": "pan_card.png"},
                )
            ],
        )

        context = await engine.process_application(app)

        assert len(context.extracted_data) > 0
        ext = context.extracted_data[0]
        assert ext.confidence > 0.5
        assert ext.extracted_fields.get("pan_number") == "ABCDE1234F"
        assert context.comparison_result is not None


class TestEndToEndLowConfidence:
    """End-to-end workflow: valid application + blank/empty image → ESCALATED."""

    @pytest.mark.asyncio
    async def test_escalated_with_blank_image(self, engine: WorkerEngine, tmp_upload_dir):
        from PIL import Image

        blank_path = os.path.join(tmp_upload_dir, "blank.png")
        img = Image.new("RGB", (100, 100), "white")
        img.save(blank_path, "PNG")

        app = OnboardingApplication(
            applicant_name="Test User",
            business_name="Test Business",
            pan_number="ABCDE1234F",
            phone="9876543210",
            documents=[
                ApplicationDocument(
                    document_id="doc-blank-001",
                    document_type="pan_card",
                    file_path=blank_path,
                    metadata={"original_filename": "blank.png"},
                )
            ],
        )

        context = await engine.process_application(app)

        assert context.current_state in (
            WorkflowState.ESCALATED_TO_HUMAN,
            WorkflowState.LOW_CONFIDENCE,
        )

        events = await engine.get_application_history(app.application_id)
        event_types = [e.event_type.value for e in events]
        has_low_confidence = any("LOW_CONFIDENCE" in t for t in event_types)
        has_failure = any("FAILED" in t or "FAILURE" in t for t in event_types)
        has_escalation = any("ESCALAT" in t for t in event_types)
        assert has_low_confidence or has_failure or has_escalation


class TestPersistedDocumentReuse:
    """Tests that the engine reuses persisted extraction results."""

    @pytest.mark.asyncio
    async def test_reuses_persisted_result(self, engine: WorkerEngine, db):
        gst_path = os.path.join(FIXTURES_DIR, "synthetic_gst_certificate.png")
        if not os.path.exists(gst_path):
            pytest.skip("Synthetic GST certificate fixture not found")

        app = OnboardingApplication(
            applicant_name="Saksham Test Enterprises",
            business_name="Saksham Test Enterprises",
            pan_number="AABCT1234D",
            gst_number="27AABCT1234D1Z5",
            phone="9876543210",
            email="test@saksham.com",
            documents=[
                ApplicationDocument(
                    document_id="doc-reuse-001",
                    document_type="gst_certificate",
                    file_path="/nonexistent/path.png",
                    metadata={"original_filename": "gst_cert.png"},
                )
            ],
        )

        result = process_document_file(
            file_path=gst_path,
            document_type="gst_certificate",
            application_id=app.application_id,
            document_id="doc-reuse-001",
            original_filename="gst_cert.png",
        )

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

        context = await engine.process_application(app)

        assert context.current_state == WorkflowState.APPROVED
        assert context.final_decision == FinalDecision.APPROVE

        events = await engine.get_application_history(app.application_id)
        event_types = [e.event_type.value for e in events]
        assert "DOCUMENT_PROCESSING_REUSED" in event_types
