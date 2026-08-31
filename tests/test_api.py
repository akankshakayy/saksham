import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app

AUTH_HEADERS = {"X-API-Key": "test-secret-key-12345"}


@pytest.mark.asyncio
async def test_health_check():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", headers=AUTH_HEADERS) as client:
        response = await client.get("/api/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["version"] == "0.1.0"


@pytest.mark.asyncio
async def test_submit_application():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", headers=AUTH_HEADERS) as client:
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
    async with AsyncClient(transport=transport, base_url="http://test", headers=AUTH_HEADERS) as client:
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
    async with AsyncClient(transport=transport, base_url="http://test", headers=AUTH_HEADERS) as client:
        response = await client.get("/api/v1/applications/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_list_applications():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", headers=AUTH_HEADERS) as client:
        response = await client.get("/api/v1/applications")
    assert response.status_code == 200
    data = response.json()
    assert "applications" in data
    assert "total" in data
    assert "limit" in data
    assert "offset" in data
    assert isinstance(data["applications"], list)


@pytest.mark.asyncio
async def test_full_workflow():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", headers=AUTH_HEADERS) as client:
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


# ── Summary fields ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_summary_includes_applicant_fields():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", headers=AUTH_HEADERS) as client:
        await client.post(
            "/api/v1/applications",
            json={
                "applicant_name": "Alice Summary",
                "business_name": "Alice Corp",
                "pan_number": "ABCDE1234F",
                "phone": "9876543210",
            },
        )
        response = await client.get("/api/v1/applications")
    assert response.status_code == 200
    apps = response.json()["applications"]
    assert len(apps) >= 1
    latest = apps[-1]
    assert latest["applicant_name"] == "Alice Summary"
    assert latest["business_name"] == "Alice Corp"
    assert "risk_score" in latest


@pytest.mark.asyncio
async def test_list_summary_has_all_expected_fields():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", headers=AUTH_HEADERS) as client:
        await client.post(
            "/api/v1/applications",
            json={
                "applicant_name": "Field Check",
                "business_name": "Field Corp",
                "pan_number": "ABCDE1234F",
                "phone": "9876543210",
            },
        )
        response = await client.get("/api/v1/applications")
    data = response.json()["applications"][-1]
    expected = {
        "application_id",
        "applicant_name",
        "business_name",
        "current_state",
        "final_decision",
        "risk_level",
        "risk_score",
        "created_at",
        "updated_at",
    }
    assert expected.issubset(set(data.keys()))


# ── Search ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_search_by_applicant_name():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", headers=AUTH_HEADERS) as client:
        await client.post(
            "/api/v1/applications",
            json={
                "applicant_name": "UniqueSearchZara",
                "business_name": "Zara Corp",
                "pan_number": "ABCDE1234F",
                "phone": "9876543210",
            },
        )
        response = await client.get("/api/v1/applications", params={"q": "UniqueSearchZara"})
    assert response.status_code == 200
    data = response.json()
    assert data["total"] >= 1
    assert any(a["applicant_name"] == "UniqueSearchZara" for a in data["applications"])


@pytest.mark.asyncio
async def test_search_by_business_name():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", headers=AUTH_HEADERS) as client:
        await client.post(
            "/api/v1/applications",
            json={
                "applicant_name": "Bob",
                "business_name": "UniqueBizAlpha99",
                "pan_number": "ABCDE1234F",
                "phone": "9876543210",
            },
        )
        response = await client.get("/api/v1/applications", params={"q": "UniqueBizAlpha99"})
    assert response.status_code == 200
    data = response.json()
    assert data["total"] >= 1
    assert any(a["business_name"] == "UniqueBizAlpha99" for a in data["applications"])


@pytest.mark.asyncio
async def test_search_by_application_id():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", headers=AUTH_HEADERS) as client:
        resp = await client.post(
            "/api/v1/applications",
            json={
                "applicant_name": "ID Test",
                "business_name": "ID Corp",
                "pan_number": "ABCDE1234F",
                "phone": "9876543210",
            },
        )
        app_id = resp.json()["application_id"]
        response = await client.get("/api/v1/applications", params={"q": app_id[:8]})
    assert response.status_code == 200
    data = response.json()
    assert data["total"] >= 1
    assert any(a["application_id"] == app_id for a in data["applications"])


@pytest.mark.asyncio
async def test_search_case_insensitive():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", headers=AUTH_HEADERS) as client:
        await client.post(
            "/api/v1/applications",
            json={
                "applicant_name": "CaseSensitiveTest",
                "business_name": "CaseCorp",
                "pan_number": "ABCDE1234F",
                "phone": "9876543210",
            },
        )
        response = await client.get("/api/v1/applications", params={"q": "casesensitivetest"})
    assert response.status_code == 200
    assert response.json()["total"] >= 1


@pytest.mark.asyncio
async def test_search_partial_match():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", headers=AUTH_HEADERS) as client:
        await client.post(
            "/api/v1/applications",
            json={
                "applicant_name": "PartialMatchZZZ",
                "business_name": "PartialCorp",
                "pan_number": "ABCDE1234F",
                "phone": "9876543210",
            },
        )
        response = await client.get("/api/v1/applications", params={"q": "PartialMatch"})
    assert response.status_code == 200
    assert response.json()["total"] >= 1


@pytest.mark.asyncio
async def test_search_empty_q_returns_all():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", headers=AUTH_HEADERS) as client:
        resp1 = await client.get("/api/v1/applications")
        resp2 = await client.get("/api/v1/applications", params={"q": ""})
    assert resp1.json()["total"] == resp2.json()["total"]


@pytest.mark.asyncio
async def test_search_no_results():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", headers=AUTH_HEADERS) as client:
        response = await client.get(
            "/api/v1/applications",
            params={"q": "ZZZNonExistent99999"},
        )
    assert response.status_code == 200
    assert response.json()["total"] == 0
    assert len(response.json()["applications"]) == 0


@pytest.mark.asyncio
async def test_search_with_state_filter():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", headers=AUTH_HEADERS) as client:
        await client.post(
            "/api/v1/applications",
            json={
                "applicant_name": "FilterSearchTest",
                "business_name": "FilterCorp",
                "pan_number": "ABCDE1234F",
                "phone": "9876543210",
            },
        )
        response = await client.get(
            "/api/v1/applications",
            params={"q": "FilterSearchTest", "state": "APPROVED"},
        )
    assert response.status_code == 200
    for row in response.json()["applications"]:
        assert row["current_state"] == "APPROVED"


@pytest.mark.asyncio
async def test_search_with_risk_filter():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", headers=AUTH_HEADERS) as client:
        await client.post(
            "/api/v1/applications",
            json={
                "applicant_name": "RiskSearchTest",
                "business_name": "RiskCorp",
                "pan_number": "ABCDE1234F",
                "phone": "9876543210",
            },
        )
        response = await client.get(
            "/api/v1/applications",
            params={"q": "RiskSearchTest", "risk_level": "LOW"},
        )
    assert response.status_code == 200
    for row in response.json()["applications"]:
        assert row["risk_level"] == "LOW"


@pytest.mark.asyncio
async def test_search_with_decision_filter():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", headers=AUTH_HEADERS) as client:
        await client.post(
            "/api/v1/applications",
            json={
                "applicant_name": "DecisionSearchTest",
                "business_name": "DecCorp",
                "pan_number": "ABCDE1234F",
                "phone": "9876543210",
            },
        )
        response = await client.get(
            "/api/v1/applications",
            params={"q": "DecisionSearchTest", "final_decision": "APPROVE"},
        )
    assert response.status_code == 200
    for row in response.json()["applications"]:
        assert row["final_decision"] == "APPROVE"


@pytest.mark.asyncio
async def test_search_with_pagination():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", headers=AUTH_HEADERS) as client:
        for i in range(5):
            await client.post(
                "/api/v1/applications",
                json={
                    "applicant_name": f"PageSearch{i}",
                    "business_name": f"PageCorp{i}",
                    "pan_number": "ABCDE1234F",
                    "phone": "9876543210",
                },
            )
        resp_p1 = await client.get(
            "/api/v1/applications",
            params={"q": "PageSearch", "limit": 2, "offset": 0},
        )
        resp_p2 = await client.get(
            "/api/v1/applications",
            params={"q": "PageSearch", "limit": 2, "offset": 2},
        )
    assert resp_p1.json()["total"] >= 5
    assert len(resp_p1.json()["applications"]) == 2
    assert len(resp_p2.json()["applications"]) == 2
    ids_p1 = {a["application_id"] for a in resp_p1.json()["applications"]}
    ids_p2 = {a["application_id"] for a in resp_p2.json()["applications"]}
    assert ids_p1.isdisjoint(ids_p2)


# ── Stable ordering ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_ordering_newest_first():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", headers=AUTH_HEADERS) as client:
        r1 = await client.post(
            "/api/v1/applications",
            json={
                "applicant_name": "OrderFirst",
                "business_name": "O1",
                "pan_number": "ABCDE1234F",
                "phone": "9876543210",
            },
        )
        r2 = await client.post(
            "/api/v1/applications",
            json={
                "applicant_name": "OrderSecond",
                "business_name": "O2",
                "pan_number": "ABCDE1234F",
                "phone": "9876543210",
            },
        )
        response = await client.get("/api/v1/applications")
    apps = response.json()["applications"]
    ids = [a["application_id"] for a in apps]
    assert ids.index(r2.json()["application_id"]) < ids.index(r1.json()["application_id"])
