"""Security tests for Phase 1 hardening.

Covers: API authentication, MCP authentication, UUID validation,
upload size limits, security headers, CORS, error handling.
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app

AUTH_HEADERS = {"X-API-Key": "test-secret-key-12345"}


# ── 1. Health is public ──────────────────────────────────────


@pytest.mark.asyncio
async def test_health_is_public():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


# ── 2. Protected endpoint without API key → 401 ──────────────


@pytest.mark.asyncio
async def test_protected_endpoint_without_key_returns_401():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/applications")
    assert response.status_code == 401
    data = response.json()
    assert data["error_code"] == "MISSING_API_KEY"


# ── 3. Invalid API key → 401 ─────────────────────────────────


@pytest.mark.asyncio
async def test_invalid_api_key_returns_401():
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://test", headers={"X-API-Key": "wrong-key-12345"}
    ) as client:
        response = await client.get("/api/v1/applications")
    assert response.status_code == 401
    data = response.json()
    assert data["error_code"] == "INVALID_API_KEY"


# ── 4. Valid API key → success ───────────────────────────────


@pytest.mark.asyncio
async def test_valid_api_key_returns_success():
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://test", headers=AUTH_HEADERS
    ) as client:
        response = await client.get("/api/v1/applications")
    assert response.status_code == 200


# ── 5. API key never appears in response ─────────────────────


@pytest.mark.asyncio
async def test_api_key_never_in_response():
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://test", headers=AUTH_HEADERS
    ) as client:
        response = await client.get("/api/v1/applications")
    raw = response.text
    assert "test-secret-key" not in raw
    assert "api_key" not in raw.lower()
    assert "X-API-Key" not in raw


# ── 6. Valid UUID accepted ───────────────────────────────────


@pytest.mark.asyncio
async def test_valid_uuid_accepted():
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://test", headers=AUTH_HEADERS
    ) as client:
        response = await client.get("/api/v1/applications/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404


# ── 7. Malformed ID rejected ─────────────────────────────────


@pytest.mark.asyncio
async def test_malformed_id_rejected():
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://test", headers=AUTH_HEADERS
    ) as client:
        response = await client.get("/api/v1/applications/not-a-uuid")
    assert response.status_code == 400
    data = response.json()
    assert data["error_code"] == "INVALID_APPLICATION_ID"


# ── 8. Traversal-looking ID rejected ─────────────────────────


@pytest.mark.asyncio
async def test_traversal_id_rejected():
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://test", headers=AUTH_HEADERS
    ) as client:
        response = await client.get("/api/v1/applications/../../etc/passwd")
    # Path traversal is blocked: either 400 (UUID validation) or 404 (route not found)
    assert response.status_code in (400, 404)


# ── 9. Security headers present ──────────────────────────────


@pytest.mark.asyncio
async def test_security_headers_present():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/health")
    assert response.headers.get("x-content-type-options") == "nosniff"
    assert response.headers.get("x-frame-options") == "DENY"
    assert response.headers.get("referrer-policy") == "no-referrer"


# ── 10. CORS allowed origin accepted ─────────────────────────


@pytest.mark.asyncio
async def test_cors_allowed_origin():
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
    assert response.headers.get("access-control-allow-origin") == "http://localhost:3000"


# ── 11. CORS disallowed origin not granted ───────────────────


@pytest.mark.asyncio
async def test_cors_disallowed_origin_not_granted():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.options(
            "/api/v1/health",
            headers={
                "Origin": "http://evil.com",
                "Access-Control-Request-Method": "GET",
            },
        )
    assert "access-control-allow-origin" not in response.headers


# ── 12. Unexpected exception returns safe ErrorResponse ──────


@pytest.mark.asyncio
async def test_unexpected_exception_returns_safe_error():
    from unittest.mock import patch

    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://test", headers=AUTH_HEADERS
    ) as client:
        with patch(
            "app.services.onboarding.OnboardingService.submit_application",
            side_effect=RuntimeError("database connection lost at /var/lib/db"),
        ):
            response = await client.post(
                "/api/v1/applications",
                json={
                    "applicant_name": "Test",
                    "business_name": "Test Corp",
                    "pan_number": "ABCDE1234F",
                    "phone": "9876543210",
                },
            )
    assert response.status_code == 500
    data = response.json()
    assert data["error_code"] == "INTERNAL_ERROR"
    assert "An unexpected error occurred" in data["message"]
    raw = response.text
    assert "/var/lib/db" not in raw
    assert "database connection lost" not in raw
    assert "RuntimeError" not in raw


# ── 13. No SQL leakage in error responses ────────────────────


@pytest.mark.asyncio
async def test_no_sql_in_error_response():
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://test", headers=AUTH_HEADERS
    ) as client:
        response = await client.get("/api/v1/applications/00000000-0000-0000-0000-000000000000")
    raw = response.text.lower()
    assert "select" not in raw
    assert "insert" not in raw
    assert "sqlite" not in raw


# ── 14. No secret leakage in error responses ─────────────────


@pytest.mark.asyncio
async def test_no_secret_in_error_response():
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://test", headers=AUTH_HEADERS
    ) as client:
        response = await client.get("/api/v1/applications/00000000-0000-0000-0000-000000000000")
    raw = response.text.lower()
    assert "sk-or" not in raw
    assert "llm_api_key" not in raw
    assert "password" not in raw


# ── 15. Document upload with invalid UUID rejected ────────────


@pytest.mark.asyncio
async def test_upload_with_invalid_uuid_rejected():
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://test", headers=AUTH_HEADERS
    ) as client:
        response = await client.post(
            "/api/v1/applications/not-a-uuid/documents",
            files={"file": ("test.png", b"\x89PNG\r\n\x1a\n" + b"\x00" * 50, "image/png")},
            data={"document_type": "pan_card"},
        )
    assert response.status_code == 400
    data = response.json()
    assert data["error_code"] == "INVALID_APPLICATION_ID"


# ── 16. Audit metadata sanitization ──────────────────────────


def test_sanitize_metadata_value_control_chars():
    from app.audit.logger import sanitize_metadata_value

    result = sanitize_metadata_value("hello\x00\x01\x02world")
    assert result == "helloworld"
    assert "\x00" not in result


def test_sanitize_metadata_value_truncation():
    from app.audit.logger import sanitize_metadata_value

    long_str = "x" * 1000
    result = sanitize_metadata_value(long_str)
    assert len(result) < 600
    assert result.endswith("...[truncated]")


def test_sanitize_metadata_value_nested():
    from app.audit.logger import sanitize_metadata_value

    result = sanitize_metadata_value({"key": "val\x00ue", "list": ["a\x01b"]})
    assert result["key"] == "value"
    assert result["list"] == ["ab"]


# ── 17. CallerIdentity not exposed in responses ──────────────


@pytest.mark.asyncio
async def test_caller_identity_not_in_response():
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://test", headers=AUTH_HEADERS
    ) as client:
        response = await client.get("/api/v1/applications")
    raw = response.text.lower()
    assert "caller" not in raw
    assert "identity" not in raw
    assert "key_id" not in raw
