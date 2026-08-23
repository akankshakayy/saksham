import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.mark.asyncio
async def test_health_check():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["version"] == "0.1.0"


@pytest.mark.asyncio
async def test_submit_application():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/applications",
            json={
                "applicant_name": "John Doe",
                "business_name": "Doe Enterprises",
                "pan_number": "ABCDE1234F",
                "phone": "9876543210",
                "email": "john@example.com",
            },
        )
    assert response.status_code == 200
    data = response.json()
    assert "application_id" in data
    assert "state" in data
    assert data["state"] in [
        "APPROVED",
        "ESCALATED",
        "ESCALATED_TO_HUMAN",
        "MORE_INFORMATION_REQUIRED",
        "REJECTED",
    ]


@pytest.mark.asyncio
async def test_submit_missing_fields():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/applications",
            json={
                "applicant_name": None,
                "business_name": None,
                "pan_number": None,
                "phone": None,
            },
        )
    assert response.status_code == 200
    data = response.json()
    assert data["state"] == "MORE_INFORMATION_REQUIRED"


@pytest.mark.asyncio
async def test_get_status_not_found():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/applications/nonexistent")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_list_applications():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/applications")
    assert response.status_code == 200
    assert isinstance(response.json(), list)


@pytest.mark.asyncio
async def test_full_workflow():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        submit_response = await client.post(
            "/api/v1/applications",
            json={
                "applicant_name": "Test User",
                "business_name": "Test Business",
                "pan_number": "ABCDE1234F",
                "phone": "9876543210",
                "email": "test@example.com",
            },
        )
        assert submit_response.status_code == 200
        app_id = submit_response.json()["application_id"]

        status_response = await client.get(f"/api/v1/applications/{app_id}")
        assert status_response.status_code == 200
        assert status_response.json()["application_id"] == app_id

        history_response = await client.get(f"/api/v1/applications/{app_id}/history")
        assert history_response.status_code == 200
        assert len(history_response.json()["events"]) > 0
