"""Tests for the frontend API contract: CORS, pagination, document endpoints,
enriched status, error standardization, and all new response models."""

from __future__ import annotations

import json
import os
import shutil
import tempfile

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")


@pytest.fixture
def tmp_upload_dir():
    d = tempfile.mkdtemp()
    yield d
    shutil.rmtree(d, ignore_errors=True)


async def _submit_app(client: AsyncClient, **overrides) -> str:
    """Submit an application and return the application_id."""
    payload = {
        "applicant_name": "Test User",
        "business_name": "Test Business",
        "pan_number": "ABCDE1234F",
        "phone": "9876543210",
        "email": "test@example.com",
    }
    payload.update(overrides)
    resp = await client.post("/api/v1/applications", json=payload)
    assert resp.status_code == 200
    return resp.json()["application_id"]


# ============================================================
# CORS Tests
# ============================================================


class TestCORS:
    @pytest.mark.asyncio
    async def test_cors_preflight_allowed_origin(self):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.options(
                "/api/v1/health",
                headers={
                    "Origin": "http://localhost:3000",
                    "Access-Control-Request-Method": "GET",
                },
            )
        assert response.status_code == 200
        assert "access-control-allow-origin" in response.headers
        assert response.headers["access-control-allow-origin"] == "http://localhost:3000"

    @pytest.mark.asyncio
    async def test_cors_preflight_vite_origin(self):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.options(
                "/api/v1/health",
                headers={
                    "Origin": "http://localhost:5173",
                    "Access-Control-Request-Method": "GET",
                },
            )
        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == "http://localhost:5173"

    @pytest.mark.asyncio
    async def test_cors_get_includes_origin_header(self):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get(
                "/api/v1/health",
                headers={"Origin": "http://localhost:3000"},
            )
        assert response.status_code == 200
        assert response.headers.get("access-control-allow-origin") == "http://localhost:3000"


# ============================================================
# Application List — Pagination & Filtering
# ============================================================


class TestListApplications:
    @pytest.mark.asyncio
    async def test_empty_list(self):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/v1/applications")
        assert response.status_code == 200
        data = response.json()
        assert data["applications"] == []
        assert data["total"] == 0
        assert data["limit"] == 20
        assert data["offset"] == 0

    @pytest.mark.asyncio
    async def test_response_shape(self):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await _submit_app(client)
            response = await client.get("/api/v1/applications")
        data = response.json()
        assert "applications" in data
        assert "total" in data
        assert "limit" in data
        assert "offset" in data
        assert isinstance(data["applications"], list)
        assert data["total"] >= 1
        first = data["applications"][0]
        assert "application_id" in first
        assert "current_state" in first
        assert "final_decision" in first
        assert "risk_level" in first
        assert "created_at" in first
        assert "updated_at" in first

    @pytest.mark.asyncio
    async def test_pagination(self):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            for _ in range(5):
                await _submit_app(client)
            resp_all = await client.get("/api/v1/applications")
            total = resp_all.json()["total"]
            assert total >= 5

            resp_page = await client.get("/api/v1/applications?limit=2&offset=0")
            data = resp_page.json()
            assert len(data["applications"]) == 2
            assert data["total"] == total
            assert data["limit"] == 2
            assert data["offset"] == 0

            resp_page2 = await client.get("/api/v1/applications?limit=2&offset=2")
            data2 = resp_page2.json()
            assert len(data2["applications"]) == 2
            assert data2["offset"] == 2

    @pytest.mark.asyncio
    async def test_state_filter(self):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await _submit_app(client)
            resp = await client.get("/api/v1/applications?state=APPROVED")
            data = resp.json()
            for app_summary in data["applications"]:
                assert app_summary["current_state"] == "APPROVED"

    @pytest.mark.asyncio
    async def test_final_decision_filter(self):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await _submit_app(client)
            resp = await client.get("/api/v1/applications?final_decision=APPROVE")
            data = resp.json()
            for app_summary in data["applications"]:
                assert app_summary["final_decision"] == "APPROVE"

    @pytest.mark.asyncio
    async def test_invalid_state_returns_422(self):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/v1/applications?state=BOGUS")
        assert response.status_code == 422
        assert "INVALID_STATE" in response.json()["detail"]["error_code"]

    @pytest.mark.asyncio
    async def test_invalid_risk_level_returns_422(self):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/v1/applications?risk_level=NONSENSE")
        assert response.status_code == 422
        assert "INVALID_RISK_LEVEL" in response.json()["detail"]["error_code"]

    @pytest.mark.asyncio
    async def test_invalid_final_decision_returns_422(self):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/v1/applications?final_decision=INVALID")
        assert response.status_code == 422
        assert "INVALID_FINAL_DECISION" in response.json()["detail"]["error_code"]

    @pytest.mark.asyncio
    async def test_negative_offset_rejected(self):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await _submit_app(client)
            resp = await client.get("/api/v1/applications?offset=-5")
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_limit_over_100_rejected(self):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/v1/applications?limit=500")
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_deterministic_ordering_newest_first(self):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            id1 = await _submit_app(client, applicant_name="First")
            id2 = await _submit_app(client, applicant_name="Second")
            resp = await client.get("/api/v1/applications")
            data = resp.json()
            ids = [a["application_id"] for a in data["applications"]]
            assert ids.index(id2) < ids.index(id1)

    @pytest.mark.asyncio
    async def test_total_count_matches_filter(self):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await _submit_app(client)
            await _submit_app(client)
            resp_all = await client.get("/api/v1/applications")
            total_all = resp_all.json()["total"]
            resp_filtered = await client.get("/api/v1/applications?state=APPROVED")
            total_filtered = resp_filtered.json()["total"]
            assert total_filtered <= total_all


# ============================================================
# Enriched Application Status
# ============================================================


class TestEnrichedStatus:
    @pytest.mark.asyncio
    async def test_status_includes_application_fields(self):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            app_id = await _submit_app(
                client,
                applicant_name="Jane Smith",
                business_name="Smith Corp",
                gst_number="27AABCT1234D1Z5",
                address="123 Main St",
            )
            resp = await client.get(f"/api/v1/applications/{app_id}")
        data = resp.json()
        assert data["application_id"] == app_id
        assert data["applicant_name"] == "Jane Smith"
        assert data["business_name"] == "Smith Corp"
        assert data["pan_number"] == "ABCDE1234F"
        assert data["phone"] == "9876543210"
        assert data["email"] == "test@example.com"
        assert data["gst_number"] == "27AABCT1234D1Z5"
        assert data["address"] == "123 Main St"

    @pytest.mark.asyncio
    async def test_status_includes_risk_fields(self):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            app_id = await _submit_app(client)
            resp = await client.get(f"/api/v1/applications/{app_id}")
        data = resp.json()
        assert "risk_level" in data
        assert "risk_score" in data
        assert "risk_factors" in data
        assert isinstance(data["risk_factors"], list)

    @pytest.mark.asyncio
    async def test_status_includes_recommendation(self):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            app_id = await _submit_app(client)
            resp = await client.get(f"/api/v1/applications/{app_id}")
        data = resp.json()
        assert "recommendation" in data
        if data["recommendation"] is not None:
            rec = data["recommendation"]
            assert "recommended_action" in rec
            assert "confidence" in rec
            assert "risk_level" in rec
            assert "reason" in rec
            assert "evidence" in rec
            assert "source" in rec
            assert "model" in rec

    @pytest.mark.asyncio
    async def test_status_missing_information_has_missing_fields(self):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            app_id = await _submit_app(
                client,
                applicant_name=None,
                business_name=None,
                pan_number=None,
                phone=None,
            )
            resp = await client.get(f"/api/v1/applications/{app_id}")
        data = resp.json()
        assert data["current_state"] in (
            "MORE_INFORMATION_REQUIRED",
            "MISSING_INFORMATION",
        )
        assert len(data["missing_fields"]) > 0
        assert data["final_decision"] in (
            "REQUEST_MORE_INFORMATION",
            None,
        )

    @pytest.mark.asyncio
    async def test_status_escalated_application(self):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            app_id = await _submit_app(
                client,
                applicant_name="Escalate Test",
                business_name="Escalate Biz",
                pan_number="AABCT1234D",
                phone="6111111111",
                email="wrong@example.com",
            )
            resp = await client.get(f"/api/v1/applications/{app_id}")
        data = resp.json()
        assert data["current_state"] in (
            "ESCALATED",
            "ESCALATED_TO_HUMAN",
            "APPROVED",
            "MORE_INFORMATION_REQUIRED",
        )
        assert "retry_count" in data

    @pytest.mark.asyncio
    async def test_status_not_found(self):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/v1/applications/nonexistent")
        assert resp.status_code == 404


# ============================================================
# Document Endpoints
# ============================================================


class TestDocumentEndpoints:
    @pytest.mark.asyncio
    async def test_upload_returns_typed_response(self):
        pan_path = os.path.join(FIXTURES_DIR, "synthetic_pan_card.png")
        if not os.path.exists(pan_path):
            pytest.skip("Synthetic PAN card fixture not found")
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            app_id = await _submit_app(client)
            with open(pan_path, "rb") as f:
                resp = await client.post(
                    f"/api/v1/applications/{app_id}/documents",
                    files={"file": ("pan_card.png", f, "image/png")},
                    data={"document_type": "pan_card"},
                )
            assert resp.status_code == 200
            data = resp.json()
            assert "document_id" in data
            assert data["application_id"] == app_id
            assert data["document_type"] == "pan_card"
            assert data["original_filename"] == "pan_card.png"
            assert "processing_status" in data
            assert "overall_confidence" in data
            assert "ocr_confidence" in data
            assert "field_extraction_confidence" in data
            assert "extracted_fields" in data
            assert "processing_method" in data
            assert "error_code" in data
            assert "error_message" in data
            assert "stored_path" not in data
            assert "raw_text" not in data

    @pytest.mark.asyncio
    async def test_upload_nonexistent_application_returns_404(self):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/applications/nonexistent/documents",
                files={"file": ("test.png", b"\x89PNG\r\n\x1a\n" + b"\x00" * 50, "image/png")},
                data={"document_type": "pan_card"},
            )
        assert resp.status_code == 404
        data = resp.json()
        assert data["error_code"] == "APPLICATION_NOT_FOUND"

    @pytest.mark.asyncio
    async def test_list_documents_empty(self):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            app_id = await _submit_app(client)
            resp = await client.get(f"/api/v1/applications/{app_id}/documents")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) == 0

    @pytest.mark.asyncio
    async def test_list_documents_with_upload(self):
        pan_path = os.path.join(FIXTURES_DIR, "synthetic_pan_card.png")
        if not os.path.exists(pan_path):
            pytest.skip("Synthetic PAN card fixture not found")
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            app_id = await _submit_app(client)
            with open(pan_path, "rb") as f:
                await client.post(
                    f"/api/v1/applications/{app_id}/documents",
                    files={"file": ("pan_card.png", f, "image/png")},
                    data={"document_type": "pan_card"},
                )
            resp = await client.get(f"/api/v1/applications/{app_id}/documents")
        data = resp.json()
        assert len(data) >= 1
        doc = data[0]
        assert "document_id" in doc
        assert "application_id" in doc
        assert doc["application_id"] == app_id
        assert "document_type" in doc
        assert "original_filename" in doc
        assert "processing_status" in doc
        assert "overall_confidence" in doc
        assert "created_at" in doc
        assert "processed_at" in doc
        assert "stored_path" not in doc
        assert "raw_text" not in doc

    @pytest.mark.asyncio
    async def test_list_documents_nonexistent_application(self):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/v1/applications/nonexistent/documents")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_get_single_document(self):
        pan_path = os.path.join(FIXTURES_DIR, "synthetic_pan_card.png")
        if not os.path.exists(pan_path):
            pytest.skip("Synthetic PAN card fixture not found")
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            app_id = await _submit_app(client)
            with open(pan_path, "rb") as f:
                upload_resp = await client.post(
                    f"/api/v1/applications/{app_id}/documents",
                    files={"file": ("pan_card.png", f, "image/png")},
                    data={"document_type": "pan_card"},
                )
            doc_id = upload_resp.json()["document_id"]
            resp = await client.get(f"/api/v1/applications/{app_id}/documents/{doc_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["document_id"] == doc_id
        assert data["application_id"] == app_id
        assert "extracted_fields" in data
        assert "error_code" in data
        assert "attempt_count" in data
        assert "stored_path" not in data

    @pytest.mark.asyncio
    async def test_get_single_document_wrong_application(self):
        pan_path = os.path.join(FIXTURES_DIR, "synthetic_pan_card.png")
        if not os.path.exists(pan_path):
            pytest.skip("Synthetic PAN card fixture not found")
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            app_id1 = await _submit_app(client, applicant_name="App1")
            app_id2 = await _submit_app(client, applicant_name="App2")
            with open(pan_path, "rb") as f:
                upload_resp = await client.post(
                    f"/api/v1/applications/{app_id1}/documents",
                    files={"file": ("pan_card.png", f, "image/png")},
                    data={"document_type": "pan_card"},
                )
            doc_id = upload_resp.json()["document_id"]
            resp = await client.get(f"/api/v1/applications/{app_id2}/documents/{doc_id}")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_get_single_document_nonexistent(self):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            app_id = await _submit_app(client)
            resp = await client.get(f"/api/v1/applications/{app_id}/documents/nonexistent")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_raw_text_endpoint(self):
        pan_path = os.path.join(FIXTURES_DIR, "synthetic_pan_card.png")
        if not os.path.exists(pan_path):
            pytest.skip("Synthetic PAN card fixture not found")
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            app_id = await _submit_app(client)
            with open(pan_path, "rb") as f:
                upload_resp = await client.post(
                    f"/api/v1/applications/{app_id}/documents",
                    files={"file": ("pan_card.png", f, "image/png")},
                    data={"document_type": "pan_card"},
                )
            doc_id = upload_resp.json()["document_id"]
            resp = await client.get(f"/api/v1/applications/{app_id}/documents/{doc_id}/raw-text")
        assert resp.status_code == 200
        data = resp.json()
        assert data["document_id"] == doc_id
        assert data["application_id"] == app_id
        assert "raw_text" in data
        assert "character_count" in data
        assert data["character_count"] == len(data["raw_text"])
        assert "stored_path" not in data

    @pytest.mark.asyncio
    async def test_raw_text_nonexistent_document(self):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            app_id = await _submit_app(client)
            resp = await client.get(f"/api/v1/applications/{app_id}/documents/nonexistent/raw-text")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_raw_text_wrong_application(self):
        pan_path = os.path.join(FIXTURES_DIR, "synthetic_pan_card.png")
        if not os.path.exists(pan_path):
            pytest.skip("Synthetic PAN card fixture not found")
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            app_id1 = await _submit_app(client, applicant_name="App1")
            app_id2 = await _submit_app(client, applicant_name="App2")
            with open(pan_path, "rb") as f:
                upload_resp = await client.post(
                    f"/api/v1/applications/{app_id1}/documents",
                    files={"file": ("pan_card.png", f, "image/png")},
                    data={"document_type": "pan_card"},
                )
            doc_id = upload_resp.json()["document_id"]
            resp = await client.get(f"/api/v1/applications/{app_id2}/documents/{doc_id}/raw-text")
        assert resp.status_code == 404


# ============================================================
# Error Response Standardization
# ============================================================


class TestErrorResponses:
    @pytest.mark.asyncio
    async def test_404_has_standardized_shape(self):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/v1/applications/nonexistent")
        assert resp.status_code == 404
        data = resp.json()
        assert "error_code" in data
        assert "message" in data
        assert data["error_code"] == "APPLICATION_NOT_FOUND"
        assert "nonexistent" in data["message"]

    @pytest.mark.asyncio
    async def test_document_404_has_same_shape(self):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            app_id = await _submit_app(client)
            resp = await client.get(f"/api/v1/applications/{app_id}/documents/nonexistent")
        assert resp.status_code == 404
        data = resp.json()
        assert "error_code" in data
        assert "message" in data
        assert data["error_code"] == "DOCUMENT_NOT_FOUND"

    @pytest.mark.asyncio
    async def test_raw_text_404_has_same_shape(self):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            app_id = await _submit_app(client)
            resp = await client.get(
                f"/api/v1/applications/{app_id}/documents/nonexistent/raw-text"
            )
        assert resp.status_code == 404
        data = resp.json()
        assert "error_code" in data
        assert "message" in data
        assert data["error_code"] == "DOCUMENT_NOT_FOUND"

    @pytest.mark.asyncio
    async def test_upload_invalid_file_returns_400(self):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            app_id = await _submit_app(client)
            resp = await client.post(
                f"/api/v1/applications/{app_id}/documents",
                files={"file": ("empty.txt", b"", "text/plain")},
                data={"document_type": "pan_card"},
            )
        assert resp.status_code == 400
        data = resp.json()
        assert "detail" in data

    @pytest.mark.asyncio
    async def test_no_secrets_in_error_response(self):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/v1/applications/nonexistent")
        raw = resp.text
        assert "api_key" not in raw.lower()
        assert "Bearer" not in raw
        assert "secret" not in raw.lower()


# ============================================================
# No Filesystem Path Exposure
# ============================================================


class TestNoPathExposure:
    @pytest.mark.asyncio
    async def test_upload_response_no_stored_path(self):
        pan_path = os.path.join(FIXTURES_DIR, "synthetic_pan_card.png")
        if not os.path.exists(pan_path):
            pytest.skip("Synthetic PAN card fixture not found")
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            app_id = await _submit_app(client)
            with open(pan_path, "rb") as f:
                resp = await client.post(
                    f"/api/v1/applications/{app_id}/documents",
                    files={"file": ("pan_card.png", f, "image/png")},
                    data={"document_type": "pan_card"},
                )
        data = resp.json()
        assert "stored_path" not in data
        raw = json.dumps(data)
        assert "data/uploads" not in raw

    @pytest.mark.asyncio
    async def test_document_detail_no_stored_path(self):
        pan_path = os.path.join(FIXTURES_DIR, "synthetic_pan_card.png")
        if not os.path.exists(pan_path):
            pytest.skip("Synthetic PAN card fixture not found")
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            app_id = await _submit_app(client)
            with open(pan_path, "rb") as f:
                upload_resp = await client.post(
                    f"/api/v1/applications/{app_id}/documents",
                    files={"file": ("pan_card.png", f, "image/png")},
                    data={"document_type": "pan_card"},
                )
            doc_id = upload_resp.json()["document_id"]
            resp = await client.get(f"/api/v1/applications/{app_id}/documents/{doc_id}")
        data = resp.json()
        assert "stored_path" not in data
        raw = json.dumps(data)
        assert "data/uploads" not in raw
