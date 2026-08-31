"""Phase 2G: Async-specific test hardening for background processing.

Tests that verify the real async behavior introduced by Phase 2:
- Background task completion after API 202
- Durability-before-scheduling ordering
- Duplicate task prevention
- Restart recovery via startup mechanism
- Retry bound enforcement
- Concurrency semaphore limits
- Worker failure propagation
- Graceful shutdown / cancellation
- MCP non-blocking access to processing state
- Frontend 202 contract safety
- Security and policy regression under async flow
"""

from __future__ import annotations

import asyncio
import json
import os
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app

AUTH_HEADERS = {"X-API-Key": "test-secret-key-12345"}

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")


async def _submit_app(client: AsyncClient, **overrides) -> str:
    payload = {
        "applicant_name": "AsyncTest User",
        "business_name": "AsyncTest Corp",
        "pan_number": "ABCDE1234F",
        "phone": "9876543210",
        "email": "async@test.com",
    }
    payload.update(overrides)
    resp = await client.post("/api/v1/applications", json=payload)
    assert resp.status_code == 202
    return resp.json()["application_id"]


async def _submit_and_wait_for_terminal(
    client: AsyncClient,
    *,
    timeout: float = 10.0,
    poll_interval: float = 0.05,
    **overrides,
) -> dict:
    app_id = await _submit_app(client, **overrides)
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        resp = await client.get(f"/api/v1/applications/{app_id}")
        assert resp.status_code == 200
        data = resp.json()
        terminal_states = {
            "APPROVED", "REJECTED", "ESCALATED", "ESCALATED_TO_HUMAN",
            "FAILED", "MORE_INFORMATION_REQUIRED", "MISSING_INFORMATION",
        }
        if data["current_state"] in terminal_states:
            return data
        await asyncio.sleep(poll_interval)
    pytest.fail(f"Application {app_id} did not reach terminal state within {timeout}s")


# ── Step 3: Application Submission Integration ────────────────


class TestApplicationSubmissionIntegration:

    @pytest.mark.asyncio
    async def test_submit_returns_202_with_received_state(self):
        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport, base_url="http://test", headers=AUTH_HEADERS
        ) as client:
            resp = await client.post(
                "/api/v1/applications",
                json={
                    "applicant_name": "Submit Test",
                    "business_name": "Submit Corp",
                    "pan_number": "ABCDE1234F",
                    "phone": "9876543210",
                },
            )
        assert resp.status_code == 202
        data = resp.json()
        assert "application_id" in data
        assert data["state"] == "RECEIVED"

    @pytest.mark.asyncio
    async def test_application_persisted_before_background_scheduling(self):
        from app.memory.store import WorkflowMemory

        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport, base_url="http://test", headers=AUTH_HEADERS
        ) as client:
            resp = await client.post(
                "/api/v1/applications",
                json={
                    "applicant_name": "Durability Test",
                    "business_name": "Durability Corp",
                    "pan_number": "ABCDE1234F",
                    "phone": "9876543210",
                },
            )
        assert resp.status_code == 202
        app_id = resp.json()["application_id"]

        memory = WorkflowMemory()
        context = await memory.get(app_id)
        assert context is not None
        assert context.current_state.value == "RECEIVED"

    @pytest.mark.asyncio
    async def test_background_completes_to_terminal_state(self):
        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport, base_url="http://test", headers=AUTH_HEADERS
        ) as client:
            data = await _submit_and_wait_for_terminal(client, timeout=15.0)
        terminal_states = {
            "APPROVED", "REJECTED", "ESCALATED", "ESCALATED_TO_HUMAN",
            "FAILED", "MORE_INFORMATION_REQUIRED", "MISSING_INFORMATION",
        }
        assert data["current_state"] in terminal_states


# ── Step 4: Document Upload Integration ───────────────────────


class TestDocumentUploadIntegration:

    @pytest.mark.asyncio
    async def test_upload_returns_202_with_processing_status(self):
        pan_path = os.path.join(FIXTURES_DIR, "synthetic_pan_card.png")
        if not os.path.exists(pan_path):
            pytest.skip("Synthetic PAN fixture not available")

        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport, base_url="http://test", headers=AUTH_HEADERS
        ) as client:
            app_id = await _submit_app(client)
            with open(pan_path, "rb") as f:
                resp = await client.post(
                    f"/api/v1/applications/{app_id}/documents",
                    files={"file": ("pan.png", f, "image/png")},
                    data={"document_type": "pan_card"},
                )
        assert resp.status_code == 202
        data = resp.json()
        assert data["processing_status"] == "processing"
        assert "document_id" in data

    @pytest.mark.asyncio
    async def test_document_pending_record_exists_before_background(self):
        from app.memory.store import DocumentStore

        pan_path = os.path.join(FIXTURES_DIR, "synthetic_pan_card.png")
        if not os.path.exists(pan_path):
            pytest.skip("Synthetic PAN fixture not available")

        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport, base_url="http://test", headers=AUTH_HEADERS
        ) as client:
            app_id = await _submit_app(client)
            with open(pan_path, "rb") as f:
                resp = await client.post(
                    f"/api/v1/applications/{app_id}/documents",
                    files={"file": ("pan.png", f, "image/png")},
                    data={"document_type": "pan_card"},
                )
        assert resp.status_code == 202
        doc_id = resp.json()["document_id"]

        store = DocumentStore()
        doc = await store.get_document(doc_id)
        assert doc is not None
        assert doc["processing_status"] in ("pending", "processing", "completed")

    @pytest.mark.asyncio
    async def test_document_background_completes(self):
        from app.memory.store import DocumentStore

        pan_path = os.path.join(FIXTURES_DIR, "synthetic_pan_card.png")
        if not os.path.exists(pan_path):
            pytest.skip("Synthetic PAN fixture not available")

        store = DocumentStore()
        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport, base_url="http://test", headers=AUTH_HEADERS
        ) as client:
            app_id = await _submit_app(client)
            with open(pan_path, "rb") as f:
                resp = await client.post(
                    f"/api/v1/applications/{app_id}/documents",
                    files={"file": ("pan.png", f, "image/png")},
                    data={"document_type": "pan_card"},
                )
        assert resp.status_code == 202
        doc_id = resp.json()["document_id"]

        deadline = asyncio.get_event_loop().time() + 15.0
        while asyncio.get_event_loop().time() < deadline:
            doc = await store.get_document(doc_id)
            if doc and doc["processing_status"] in ("completed", "low_confidence", "failed"):
                break
            await asyncio.sleep(0.1)

        doc = await store.get_document(doc_id)
        assert doc is not None
        assert doc["processing_status"] in ("completed", "low_confidence", "failed")


# ── Step 5: Durability Before Scheduling ──────────────────────


class TestDurabilityBeforeScheduling:

    @pytest.mark.asyncio
    async def test_receiving_state_persisted_before_task_scheduled(self):
        from app.memory.store import WorkflowMemory

        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport, base_url="http://test", headers=AUTH_HEADERS
        ) as client:
            resp = await client.post(
                "/api/v1/applications",
                json={
                    "applicant_name": "Durability Order",
                    "business_name": "Durability Corp",
                    "pan_number": "ABCDE1234F",
                    "phone": "9876543210",
                },
            )
        assert resp.status_code == 202
        app_id = resp.json()["application_id"]

        memory = WorkflowMemory()
        ctx = await memory.get(app_id)
        assert ctx is not None
        assert ctx.current_state.value == "RECEIVED"

    @pytest.mark.asyncio
    async def test_persistence_failure_returns_500(self):
        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport, base_url="http://test", headers=AUTH_HEADERS
        ) as client:
            with patch(
                "app.services.onboarding.OnboardingService.submit_application",
                side_effect=Exception("simulated persistence failure"),
            ):
                resp = await client.post(
                    "/api/v1/applications",
                    json={
                        "applicant_name": "Fail Test",
                        "business_name": "Fail Corp",
                        "pan_number": "ABCDE1234F",
                        "phone": "9876543210",
                    },
                )
        assert resp.status_code == 500


# ── Step 6: Duplicate Prevention ──────────────────────────────


class TestDuplicatePrevention:

    @pytest.mark.asyncio
    async def test_duplicate_workflow_task_skipped(self):
        from app.worker.background import get_worker

        worker = get_worker()
        execution_count = 0

        async def _counting_coro():
            nonlocal execution_count
            execution_count += 1
            await asyncio.sleep(0.1)

        await worker.submit_workflow_task(key="dup-test-1", coro=_counting_coro())
        await worker.submit_workflow_task(key="dup-test-1", coro=_counting_coro())

        await asyncio.sleep(0.5)
        assert execution_count == 1
        await worker.shutdown(timeout=2.0)

    @pytest.mark.asyncio
    async def test_duplicate_ocr_task_skipped(self):
        from app.worker.background import get_worker

        worker = get_worker()
        execution_count = 0

        async def _counting_coro():
            nonlocal execution_count
            execution_count += 1
            await asyncio.sleep(0.1)

        await worker.submit_ocr_task(key="dup-ocr-1", coro=_counting_coro())
        await worker.submit_ocr_task(key="dup-ocr-1", coro=_counting_coro())

        await asyncio.sleep(0.5)
        assert execution_count == 1
        await worker.shutdown(timeout=2.0)

    @pytest.mark.asyncio
    async def test_duplicate_api_creates_separate_applications(self):
        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport, base_url="http://test", headers=AUTH_HEADERS
        ) as client:
            resp1 = await client.post(
                "/api/v1/applications",
                json={
                    "applicant_name": "Dup Test",
                    "business_name": "Dup Corp",
                    "pan_number": "ABCDE1234F",
                    "phone": "9876543210",
                },
            )
            resp2 = await client.post(
                "/api/v1/applications",
                json={
                    "applicant_name": "Dup Test",
                    "business_name": "Dup Corp",
                    "pan_number": "ABCDE1234F",
                    "phone": "9876543210",
                },
            )
        assert resp1.status_code == 202
        assert resp2.status_code == 202
        assert resp1.json()["application_id"] != resp2.json()["application_id"]


# ── Step 7: Restart Recovery ──────────────────────────────────


class TestRestartRecovery:

    @pytest.mark.asyncio
    async def test_recovery_requeues_received_application(self):
        from app.memory.store import WorkflowMemory
        from app.models.domain import OnboardingApplication, WorkflowContext
        from app.models.states import WorkflowState

        memory = WorkflowMemory()
        app_id = "00000000-0000-0000-0000-000000000001"
        application = OnboardingApplication(
            applicant_name="Recovery Test",
            business_name="Recovery Corp",
            pan_number="ABCDE1234F",
            phone="9876543210",
        )
        application.application_id = app_id
        context = WorkflowContext(application=application)
        assert context.current_state == WorkflowState.RECEIVED
        await memory.save(context)

        from app.main import _recover_stuck_work
        await _recover_stuck_work()

        from app.worker.background import get_worker, reset_worker
        worker = get_worker()
        assert worker.is_task_running(app_id)
        await worker.shutdown(timeout=3.0)
        reset_worker()

    @pytest.mark.asyncio
    async def test_recovery_ignores_terminal_application(self):
        from app.memory.store import WorkflowMemory
        from app.models.domain import OnboardingApplication, WorkflowContext
        from app.models.states import WorkflowState

        memory = WorkflowMemory()
        app_id = "00000000-0000-0000-0000-000000000002"
        application = OnboardingApplication(
            applicant_name="Terminal Test",
            business_name="Terminal Corp",
            pan_number="ABCDE1234F",
            phone="9876543210",
        )
        application.application_id = app_id
        context = WorkflowContext(application=application)
        context.current_state = WorkflowState.APPROVED
        await memory.save(context)

        from app.main import _recover_stuck_work
        await _recover_stuck_work()

        from app.worker.background import get_worker, reset_worker
        worker = get_worker()
        assert not worker.is_task_running(app_id)
        await worker.shutdown(timeout=2.0)
        reset_worker()

    @pytest.mark.asyncio
    async def test_recovery_skips_terminal_document(self):
        from app.memory.store import DocumentStore

        store = DocumentStore()
        doc_id = "doc-recovery-completed"
        app_id = "00000000-0000-0000-0000-000000000003"
        await store.save_pending_document(
            document_id=doc_id,
            application_id=app_id,
            document_type="pan_card",
            original_filename="pan.png",
            stored_path="/tmp/nonexistent.png",
        )
        await store.update_document_status(doc_id, "completed")

        from app.main import _recover_stuck_work
        await _recover_stuck_work()

        from app.worker.background import get_worker, reset_worker
        worker = get_worker()
        doc = await store.get_document(doc_id)
        assert doc["processing_status"] == "completed"
        await worker.shutdown(timeout=3.0)
        reset_worker()


# ── Step 8: Retry Bound ───────────────────────────────────────


class TestRetryBound:

    @pytest.mark.asyncio
    async def test_retry_count_bounded_by_max_tool_retries(self):
        from app.audit.logger import AuditLogger
        from app.memory.database import get_database
        from app.memory.store import WorkflowMemory
        from app.models.domain import (
            ApplicationDocument,
            OnboardingApplication,
            WorkflowContext,
        )
        from app.models.states import EventType, WorkflowState
        from app.worker.engine import WorkerEngine

        db = get_database()
        memory = WorkflowMemory(db=db)
        audit = AuditLogger(db=db)
        engine = WorkerEngine(memory=memory, audit=audit)

        application = OnboardingApplication(
            applicant_name="Retry Test",
            business_name="Retry Corp",
            pan_number="ABCDE1234F",
            phone="9876543210",
            documents=[
                ApplicationDocument(document_type="pan_card", raw_text="some text"),
            ],
        )
        context = WorkflowContext(application=application)
        await memory.save(context)

        with patch(
            "app.tools.extract_document_data",
            side_effect=RuntimeError("extraction failure"),
        ):
            result = await engine.resume_application(context)

        events = await audit.get_events_for_application(application.application_id)
        started_events = [
            e for e in events
            if e.event_type == EventType.DOCUMENT_PROCESSING_STARTED
        ]
        assert len(started_events) == 3

        assert result.current_state in {
            WorkflowState.TOOL_FAILED,
            WorkflowState.ESCALATED_TO_HUMAN,
            WorkflowState.FAILED,
        }

    @pytest.mark.asyncio
    async def test_max_tool_retries_configuration(self):
        from app.config.settings import get_settings
        settings = get_settings()
        assert settings.max_tool_retries == 3


# ── Step 9: Concurrency Limit ─────────────────────────────────


class TestConcurrencyLimit:

    @pytest.mark.asyncio
    async def test_workflow_concurrency_bounded_by_semaphore(self):
        from app.worker.background import BackgroundWorker

        worker = BackgroundWorker(max_workflow_concurrency=2)
        active = 0
        max_observed = 0
        hold = asyncio.Event()

        async def _tracking_task():
            nonlocal active, max_observed
            active += 1
            if active > max_observed:
                max_observed = active
            await hold.wait()
            active -= 1

        for i in range(4):
            await worker.submit_workflow_task(key=f"conc-{i}", coro=_tracking_task())

        await asyncio.sleep(0.2)
        assert max_observed <= 2

        hold.set()
        await asyncio.sleep(0.2)
        assert active == 0
        await worker.shutdown(timeout=2.0)

    @pytest.mark.asyncio
    async def test_ocr_concurrency_bounded_by_semaphore(self):
        from app.worker.background import BackgroundWorker

        worker = BackgroundWorker(max_ocr_concurrency=2)
        active = 0
        max_observed = 0
        hold = asyncio.Event()

        async def _tracking_task():
            nonlocal active, max_observed
            active += 1
            if active > max_observed:
                max_observed = active
            await hold.wait()
            active -= 1

        for i in range(4):
            await worker.submit_ocr_task(key=f"ocr-conc-{i}", coro=_tracking_task())

        await asyncio.sleep(0.2)
        assert max_observed <= 2

        hold.set()
        await asyncio.sleep(0.2)
        assert active == 0
        await worker.shutdown(timeout=2.0)


# ── Step 10: Failure Propagation ──────────────────────────────


class TestFailurePropagation:

    @pytest.mark.asyncio
    async def test_worker_exception_recorded_in_audit(self):
        from app.audit.logger import AuditLogger
        from app.memory.database import get_database
        from app.memory.store import WorkflowMemory
        from app.models.domain import OnboardingApplication, WorkflowContext
        from app.models.states import EventType

        db = get_database()
        memory = WorkflowMemory(db=db)
        audit = AuditLogger(db=db)

        application = OnboardingApplication(
            applicant_name="Fail Test",
            business_name="Fail Corp",
            pan_number="ABCDE1234F",
            phone="9876543210",
        )
        context = WorkflowContext(application=application)
        await memory.save(context)

        from app.api.routes import _process_application_background
        from app.services.onboarding import SubmitApplicationRequest

        request_data = SubmitApplicationRequest(
            applicant_name="Fail Test",
            business_name="Fail Corp",
            pan_number="ABCDE1234F",
            phone="9876543210",
        )

        with patch(
            "app.worker.engine.WorkerEngine.resume_application",
            side_effect=RuntimeError("simulated engine failure"),
        ):
            from app.worker.background import get_worker, reset_worker
            worker = get_worker()
            await worker.submit_workflow_task(
                key=application.application_id,
                coro=_process_application_background(
                    application_id=application.application_id,
                    request_data=request_data,
                ),
            )
            await asyncio.sleep(0.5)

        events = await audit.get_events_for_application(application.application_id)
        failure_events = [e for e in events if e.event_type == EventType.FAILURE]
        assert len(failure_events) >= 1

        await worker.shutdown(timeout=2.0)
        reset_worker()

    @pytest.mark.asyncio
    async def test_task_registry_cleaned_after_completion(self):
        from app.worker.background import BackgroundWorker

        worker = BackgroundWorker()

        async def _quick_task():
            await asyncio.sleep(0.05)

        await worker.submit_workflow_task(key="cleanup-test", coro=_quick_task())
        assert worker.is_task_running("cleanup-test")

        await asyncio.sleep(0.3)
        assert not worker.is_task_running("cleanup-test")
        assert "cleanup-test" not in worker._tasks
        await worker.shutdown(timeout=2.0)

    @pytest.mark.asyncio
    async def test_no_unhandled_task_exception(self):
        from app.worker.background import BackgroundWorker

        worker = BackgroundWorker()
        task_done = asyncio.Event()

        async def _failing_task():
            raise ValueError("intentional failure")

        task = asyncio.create_task(worker._run_with_semaphore(
            asyncio.Semaphore(1), "fail-test", _failing_task()
        ))
        task.add_done_callback(lambda t: task_done.set())

        await asyncio.wait_for(task_done.wait(), timeout=2.0)
        assert task.done()
        assert task.exception() is None
        assert task.cancelled() is False
        await worker.shutdown(timeout=2.0)


# ── Step 11: Cancellation / Shutdown ──────────────────────────


class TestCancellationShutdown:

    @pytest.mark.asyncio
    async def test_shutdown_cancels_pending_tasks(self):
        from app.worker.background import BackgroundWorker

        worker = BackgroundWorker()
        tasks_started = asyncio.Event()

        async def _slow_task():
            tasks_started.set()
            try:
                await asyncio.sleep(100)
            except asyncio.CancelledError:
                raise

        await worker.submit_workflow_task(key="cancel-1", coro=_slow_task())
        await worker.submit_workflow_task(key="cancel-2", coro=_slow_task())
        await asyncio.sleep(0.1)
        assert tasks_started.is_set()
        assert worker.active_task_count == 2

        await worker.shutdown(timeout=2.0)
        assert worker.active_task_count == 0
        assert len(worker._tasks) == 0

    @pytest.mark.asyncio
    async def test_shutdown_awaits_task_cancellation(self):
        from app.worker.background import BackgroundWorker

        worker = BackgroundWorker()
        cancellation_received = asyncio.Event()

        async def _finishing_task():
            try:
                await asyncio.sleep(100)
            except asyncio.CancelledError:
                cancellation_received.set()
                raise

        await worker.submit_workflow_task(key="wait-test", coro=_finishing_task())
        await asyncio.sleep(0.1)
        await worker.shutdown(timeout=5.0)
        assert cancellation_received.is_set()

    @pytest.mark.asyncio
    async def test_shutdown_timeout_does_not_hang(self):
        from app.worker.background import BackgroundWorker

        worker = BackgroundWorker()

        async def _stuck_task():
            await asyncio.sleep(1000)

        await worker.submit_workflow_task(key="stuck-1", coro=_stuck_task())
        await worker.submit_workflow_task(key="stuck-2", coro=_stuck_task())
        start = asyncio.get_event_loop().time()
        await worker.shutdown(timeout=2.0)
        elapsed = asyncio.get_event_loop().time() - start
        assert elapsed < 4.0

    @pytest.mark.asyncio
    async def test_inner_coroutine_closed_on_cancellation(self):
        from app.worker.background import BackgroundWorker

        worker = BackgroundWorker()

        async def _inner():
            await asyncio.sleep(100)

        coro = _inner()
        await worker.submit_workflow_task(key="close-test", coro=coro)
        await asyncio.sleep(0.1)
        await worker.shutdown(timeout=2.0)
        assert coro.cr_await is None or coro.cr_frame is None


# ── Step 12: MCP Non-Blocking ─────────────────────────────────


class TestMCPNonBlocking:

    @pytest.mark.asyncio
    async def test_mcp_status_returns_during_processing(self):
        from app.memory.store import WorkflowMemory
        from app.models.domain import OnboardingApplication, WorkflowContext

        memory = WorkflowMemory()
        app_id = "00000000-0000-0000-0000-000000000010"
        application = OnboardingApplication(
            applicant_name="MCP Non-Block",
            business_name="MCP Corp",
            pan_number="ABCDE1234F",
            phone="9876543210",
        )
        application.application_id = app_id
        context = WorkflowContext(application=application)
        await memory.save(context)

        from app.mcp import create_mcp_server
        mcp_server = create_mcp_server()

        start = asyncio.get_event_loop().time()
        result = await mcp_server.call_tool(
            "get_application_status", {"application_id": app_id}
        )
        elapsed = asyncio.get_event_loop().time() - start

        assert len(result.content) == 1
        data = json.loads(result.content[0].text)
        assert data["application_id"] == app_id
        assert elapsed < 2.0

    @pytest.mark.asyncio
    async def test_api_status_returns_during_processing(self):
        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport, base_url="http://test", headers=AUTH_HEADERS
        ) as client:
            app_id = await _submit_app(client)
            start = asyncio.get_event_loop().time()
            resp = await client.get(f"/api/v1/applications/{app_id}")
            elapsed = asyncio.get_event_loop().time() - start

        assert resp.status_code == 200
        assert resp.json()["current_state"] == "RECEIVED"
        assert elapsed < 2.0


# ── Step 13: Frontend API 202 Contract ────────────────────────


class TestFrontendAPIContract:

    @pytest.mark.asyncio
    async def test_202_response_no_filesystem_paths(self):
        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport, base_url="http://test", headers=AUTH_HEADERS
        ) as client:
            resp = await client.post(
                "/api/v1/applications",
                json={
                    "applicant_name": "Contract Test",
                    "business_name": "Contract Corp",
                    "pan_number": "ABCDE1234F",
                    "phone": "9876543210",
                },
            )
        assert resp.status_code == 202
        raw = resp.text
        assert "/tmp" not in raw
        assert "/data/" not in raw
        assert "/var/" not in raw
        assert "uploads" not in raw

    @pytest.mark.asyncio
    async def test_202_response_no_secrets(self):
        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport, base_url="http://test", headers=AUTH_HEADERS
        ) as client:
            resp = await client.post(
                "/api/v1/applications",
                json={
                    "applicant_name": "Secret Test",
                    "business_name": "Secret Corp",
                    "pan_number": "ABCDE1234F",
                    "phone": "9876543210",
                },
            )
        assert resp.status_code == 202
        raw = resp.text.lower()
        assert "api_key" not in raw
        assert "password" not in raw
        assert "secret" not in raw
        assert "bearer" not in raw

    @pytest.mark.asyncio
    async def test_202_response_no_coroutine_or_task_objects(self):
        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport, base_url="http://test", headers=AUTH_HEADERS
        ) as client:
            resp = await client.post(
                "/api/v1/applications",
                json={
                    "applicant_name": "Coro Test",
                    "business_name": "Coro Corp",
                    "pan_number": "ABCDE1234F",
                    "phone": "9876543210",
                },
            )
        assert resp.status_code == 202
        raw = resp.text.lower()
        assert "coroutine" not in raw
        assert "0x" not in raw

    @pytest.mark.asyncio
    async def test_202_document_upload_no_filesystem_paths(self):
        pan_path = os.path.join(FIXTURES_DIR, "synthetic_pan_card.png")
        if not os.path.exists(pan_path):
            pytest.skip("Synthetic PAN fixture not available")

        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport, base_url="http://test", headers=AUTH_HEADERS
        ) as client:
            app_id = await _submit_app(client)
            with open(pan_path, "rb") as f:
                resp = await client.post(
                    f"/api/v1/applications/{app_id}/documents",
                    files={"file": ("pan.png", f, "image/png")},
                    data={"document_type": "pan_card"},
                )
        assert resp.status_code == 202
        raw = resp.text
        assert "stored_path" not in raw
        assert "/data/" not in raw


# ── Step 14: Security Regression ──────────────────────────────


class TestSecurityRegression:

    @pytest.mark.asyncio
    async def test_api_authentication_still_required(self):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/applications",
                json={
                    "applicant_name": "Auth Test",
                    "business_name": "Auth Corp",
                    "pan_number": "ABCDE1234F",
                    "phone": "9876543210",
                },
            )
        assert resp.status_code == 401
        assert resp.json()["error_code"] == "MISSING_API_KEY"

    @pytest.mark.asyncio
    async def test_invalid_api_key_rejected(self):
        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport, base_url="http://test",
            headers={"X-API-Key": "wrong-key-12345"},
        ) as client:
            resp = await client.post(
                "/api/v1/applications",
                json={
                    "applicant_name": "Auth Test",
                    "business_name": "Auth Corp",
                    "pan_number": "ABCDE1234F",
                    "phone": "9876543210",
                },
            )
        assert resp.status_code == 401
        assert resp.json()["error_code"] == "INVALID_API_KEY"

    @pytest.mark.asyncio
    async def test_uuid_validation_still_enforced(self):
        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport, base_url="http://test", headers=AUTH_HEADERS
        ) as client:
            resp = await client.get("/api/v1/applications/not-a-uuid")
        assert resp.status_code == 400
        assert resp.json()["error_code"] == "INVALID_APPLICATION_ID"

    @pytest.mark.asyncio
    async def test_upload_size_limit_still_enforced(self):
        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport, base_url="http://test", headers=AUTH_HEADERS
        ) as client:
            app_resp = await client.post(
                "/api/v1/applications",
                json={
                    "applicant_name": "Size Test",
                    "business_name": "Size Corp",
                    "pan_number": "ABCDE1234F",
                    "phone": "9876543210",
                },
            )
            assert app_resp.status_code == 202
            app_id = app_resp.json()["application_id"]

            large_content = b"\x89PNG\r\n\x1a\n" + b"\x00" * (11 * 1024 * 1024)
            resp = await client.post(
                f"/api/v1/applications/{app_id}/documents",
                files={"file": ("large.png", large_content, "image/png")},
                data={"document_type": "pan_card"},
            )
        assert resp.status_code == 413

    @pytest.mark.asyncio
    async def test_security_headers_present(self):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/v1/health")
        assert resp.headers.get("x-content-type-options") == "nosniff"
        assert resp.headers.get("x-frame-options") == "DENY"
        assert resp.headers.get("referrer-policy") == "no-referrer"

    @pytest.mark.asyncio
    async def test_cors_still_enforced(self):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.options(
                "/api/v1/health",
                headers={
                    "Origin": "http://evil.com",
                    "Access-Control-Request-Method": "GET",
                },
            )
        assert "access-control-allow-origin" not in resp.headers

    @pytest.mark.asyncio
    async def test_safe_error_responses(self):
        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport, base_url="http://test", headers=AUTH_HEADERS
        ) as client:
            resp = await client.get(
                "/api/v1/applications/00000000-0000-0000-0000-000000000000"
            )
        raw = resp.text.lower()
        assert "select" not in raw
        assert "insert" not in raw
        assert "sk-or" not in raw
        assert "/var/" not in raw


# ── Step 15: Policy Regression ────────────────────────────────


class TestPolicyRegression:

    @pytest.mark.asyncio
    async def test_no_documents_approve_overridden_to_more_info(self):
        from unittest.mock import patch

        from app.audit.logger import AuditLogger
        from app.memory.database import get_database
        from app.memory.store import WorkflowMemory
        from app.models.domain import AIRecommendation, OnboardingApplication, WorkflowContext
        from app.models.states import FinalDecision, RiskLevel
        from app.worker.engine import WorkerEngine

        db = get_database()
        memory = WorkflowMemory(db=db)
        audit = AuditLogger(db=db)
        engine = WorkerEngine(memory=memory, audit=audit)

        application = OnboardingApplication(
            applicant_name="Policy Test",
            business_name="Policy Corp",
            pan_number="ABCDE1234F",
            phone="9876543210",
        )
        context = WorkflowContext(application=application)
        await memory.save(context)

        with patch(
            "app.worker.engine.get_ai_recommendation",
            return_value=AIRecommendation(
                recommended_action=FinalDecision.APPROVE,
                confidence=0.9,
                risk_level=RiskLevel.LOW,
                reason="No reason",
                evidence=[],
                source="test",
                model="test",
            ),
        ):
            result = await engine.resume_application(context)
        assert result.final_decision == FinalDecision.REQUEST_MORE_INFORMATION

    @pytest.mark.asyncio
    async def test_critical_risk_approve_overridden_to_escalate(self):
        from app.audit.logger import AuditLogger
        from app.memory.database import get_database
        from app.memory.store import WorkflowMemory
        from app.models.domain import (
            ApplicationDocument,
            ExtractedDocumentData,
            OnboardingApplication,
            WorkflowContext,
        )
        from app.models.states import FinalDecision, RiskLevel
        from app.worker.engine import WorkerEngine

        db = get_database()
        memory = WorkflowMemory(db=db)
        audit = AuditLogger(db=db)
        engine = WorkerEngine(memory=memory, audit=audit)

        application = OnboardingApplication(
            applicant_name="Critical Test",
            business_name="Critical Corp",
            pan_number="ABCDE1234F",
            phone="9876543210",
            documents=[
                ApplicationDocument(document_type="pan_card", raw_text="PAN: ABCDE1234F"),
            ],
        )
        context = WorkflowContext(application=application)

        from app.models.domain import AIRecommendation
        from app.models.domain import RiskAssessment as RiskAssessmentDomain

        extracted = ExtractedDocumentData(
            document_id=application.documents[0].document_id,
            document_type="pan_card",
            extracted_fields={"pan_number": "ABCDE1234F"},
            confidence=0.95,
            extraction_method="regex",
        )

        with patch(
            "app.worker.engine.extract_document_data",
            return_value=extracted,
        ), patch(
            "app.worker.engine.assess_risk",
            return_value=RiskAssessmentDomain(
                risk_level=RiskLevel.CRITICAL,
                risk_score=0.95,
                risk_factors=["high_value_transaction"],
            ),
        ), patch(
            "app.worker.engine.get_ai_recommendation",
            return_value=AIRecommendation(
                recommended_action=FinalDecision.APPROVE,
                confidence=0.9,
                risk_level=RiskLevel.CRITICAL,
                reason="All checks passed",
                evidence=["documents verified"],
                source="test",
                model="test-model",
            ),
        ):
            result = await engine.resume_application(context)

        assert result.final_decision == FinalDecision.ESCALATE_TO_HUMAN

    @pytest.mark.asyncio
    async def test_verified_documents_low_risk_can_approve(self):
        from app.audit.logger import AuditLogger
        from app.memory.database import get_database
        from app.memory.store import WorkflowMemory
        from app.models.domain import (
            ApplicationDocument,
            ExtractedDocumentData,
            OnboardingApplication,
            WorkflowContext,
        )
        from app.models.states import FinalDecision, RiskLevel
        from app.worker.engine import WorkerEngine

        db = get_database()
        memory = WorkflowMemory(db=db)
        audit = AuditLogger(db=db)
        engine = WorkerEngine(memory=memory, audit=audit)

        application = OnboardingApplication(
            applicant_name="Approved Test",
            business_name="Approved Corp",
            pan_number="ABCDE1234F",
            phone="9876543210",
            documents=[
                ApplicationDocument(document_type="pan_card", raw_text="PAN: ABCDE1234F"),
            ],
        )
        context = WorkflowContext(application=application)

        from app.models.domain import AIRecommendation
        from app.models.domain import RiskAssessment as RiskAssessmentDomain

        extracted = ExtractedDocumentData(
            document_id=application.documents[0].document_id,
            document_type="pan_card",
            extracted_fields={"pan_number": "ABCDE1234F"},
            confidence=0.95,
            extraction_method="regex",
        )

        with patch(
            "app.worker.engine.extract_document_data",
            return_value=extracted,
        ), patch(
            "app.worker.engine.assess_risk",
            return_value=RiskAssessmentDomain(
                risk_level=RiskLevel.LOW,
                risk_score=0.1,
                risk_factors=[],
            ),
        ), patch(
            "app.worker.engine.get_ai_recommendation",
            return_value=AIRecommendation(
                recommended_action=FinalDecision.APPROVE,
                confidence=0.95,
                risk_level=RiskLevel.LOW,
                reason="All checks passed",
                evidence=["documents verified"],
                source="test",
                model="test-model",
            ),
        ):
            result = await engine.resume_application(context)

        assert result.final_decision == FinalDecision.APPROVE
