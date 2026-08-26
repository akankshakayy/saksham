"""Tests for persistence failure handling.

Verifies behavior when database writes fail:
- State persistence failure surfaces controlled error
- Audit persistence failure does not crash workflow
- In-memory state is rolled back on persistence failure
- Recovery works after database becomes available again
- Existing successful workflows still pass
- Existing escalation workflows still pass
- Persistence across restart still works
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from app.audit.logger import AuditLogger
from app.memory.database import Database
from app.memory.errors import AuditPersistenceError, PersistenceError
from app.memory.store import DocumentStore, WorkflowMemory
from app.models.domain import ApplicationDocument, OnboardingApplication, WorkflowContext
from app.models.states import EventType, FinalDecision, WorkflowState
from app.worker.engine import WorkerEngine
from app.tools.document_processing import process_document_file

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")


@pytest_asyncio.fixture
async def db(tmp_path):
    db_path = str(tmp_path / "test_reliability.db")
    database = Database(f"sqlite+aiosqlite:///{db_path}")
    await database.connect()
    yield database
    await database.close()


@pytest_asyncio.fixture
async def engine(db):
    memory = WorkflowMemory(db=db)
    audit = AuditLogger(db=db)
    doc_store = DocumentStore(db=db)
    return WorkerEngine(memory=memory, audit=audit, document_store=doc_store)


# ── Test 1: State persistence failure surfaces PersistenceError ──


@pytest.mark.asyncio
async def test_state_persistence_failure_raises_persistence_error(db):
    """When memory.save() fails, PersistenceError is raised."""
    memory = WorkflowMemory(db=db)
    audit = AuditLogger(db=db)
    engine = WorkerEngine(memory=memory, audit=audit)

    app = OnboardingApplication(
        applicant_name="Test User",
        business_name="Test Corp",
        pan_number="ABCDE1234F",
        phone="9876543210",
    )

    original_execute = db.conn.execute

    call_count = 0

    async def failing_execute(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise Exception("SQLite write failed")
        return await original_execute(*args, **kwargs)

    with patch.object(db.conn, "execute", side_effect=failing_execute):
        with pytest.raises(PersistenceError) as exc_info:
            await engine.process_application(app)

    assert "Failed to persist workflow context" in str(exc_info.value)
    assert exc_info.value.application_id == app.application_id


# ── Test 2: Audit persistence failure does not crash workflow ──


@pytest.mark.asyncio
async def test_audit_persistence_failure_does_not_crash_workflow(db):
    """When audit.record() fails, the workflow continues and completes."""
    memory = WorkflowMemory(db=db)
    audit = AuditLogger(db=db)
    engine = WorkerEngine(memory=memory, audit=audit)

    app = OnboardingApplication(
        applicant_name="Test User",
        business_name="Test Corp",
        pan_number="ABCDE1234F",
        phone="9876543210",
    )

    original_audit_execute = db.conn.execute
    audit_call_count = 0

    async def failing_audit_execute(*args, **kwargs):
        nonlocal audit_call_count
        sql = args[0] if args else kwargs.get("sql", "")
        if isinstance(sql, str) and "audit_events" in sql:
            audit_call_count += 1
            raise Exception("Audit write failed")
        return await original_audit_execute(*args, **kwargs)

    with patch.object(db.conn, "execute", side_effect=failing_audit_execute):
        context = await engine.process_application(app)

    assert context.current_state in (
        WorkflowState.APPROVED,
        WorkflowState.ESCALATED,
        WorkflowState.ESCALATED_TO_HUMAN,
        WorkflowState.MORE_INFORMATION_REQUIRED,
        WorkflowState.REJECTED,
    )
    assert context.final_decision is not None


# ── Test 3: In-memory state is rolled back on persistence failure ──


@pytest.mark.asyncio
async def test_in_memory_state_rollback_on_persistence_failure(db):
    """When save() fails, context.updated_at is rolled back to previous value."""
    memory = WorkflowMemory(db=db)
    app = OnboardingApplication(
        applicant_name="Rollback Test",
        business_name="Rollback Corp",
        pan_number="ABCDE1234F",
        phone="9876543210",
    )
    context = WorkflowContext(application=app)

    original_updated_at = context.updated_at

    original_execute = db.conn.execute

    async def failing_execute(*args, **kwargs):
        raise Exception("SQLite write failed")

    with patch.object(db.conn, "execute", side_effect=failing_execute):
        with pytest.raises(PersistenceError):
            await memory.save(context)

    assert context.updated_at == original_updated_at


# ── Test 4: Recovery after database becomes available again ──


@pytest.mark.asyncio
async def test_recovery_after_database_becomes_available(db):
    """After a transient failure, new operations succeed."""
    memory = WorkflowMemory(db=db)
    audit = AuditLogger(db=db)
    engine = WorkerEngine(memory=memory, audit=audit)

    app1 = OnboardingApplication(
        applicant_name="Recovery Test",
        business_name="Recovery Corp",
        pan_number="ABCDE1234F",
        phone="9876543210",
    )

    original_execute = db.conn.execute
    fail_once = True

    async def failing_once_execute(*args, **kwargs):
        nonlocal fail_once
        if fail_once:
            fail_once = False
            raise Exception("Transient failure")
        return await original_execute(*args, **kwargs)

    with patch.object(db.conn, "execute", side_effect=failing_once_execute):
        with pytest.raises(PersistenceError):
            await engine.process_application(app1)

    app2 = OnboardingApplication(
        applicant_name="Recovery Test 2",
        business_name="Recovery Corp 2",
        pan_number="FFFFF1111F",
        phone="1234567890",
    )

    context = await engine.process_application(app2)

    assert context.current_state in (
        WorkflowState.APPROVED,
        WorkflowState.ESCALATED,
        WorkflowState.ESCALATED_TO_HUMAN,
        WorkflowState.MORE_INFORMATION_REQUIRED,
        WorkflowState.REJECTED,
    )
    assert context.final_decision is not None


# ── Test 5: Existing successful workflow still works ──


@pytest.mark.asyncio
async def test_existing_successful_workflow_still_works(engine):
    """The normal APPROVED workflow still passes with persistence changes."""
    app = OnboardingApplication(
        applicant_name="John Doe",
        business_name="Doe Enterprises",
        pan_number="ABCDE1234F",
        phone="9876543210",
        email="john@example.com",
    )

    context = await engine.process_application(app)

    assert context.current_state in (
        WorkflowState.APPROVED,
        WorkflowState.ESCALATED,
        WorkflowState.ESCALATED_TO_HUMAN,
        WorkflowState.MORE_INFORMATION_REQUIRED,
    )
    assert context.final_decision is not None


# ── Test 6: Existing escalation workflow still works ──


@pytest.mark.asyncio
async def test_existing_escalation_workflow_still_works(engine, tmp_path):
    """Corrupted document → retries → escalation still works."""
    unreadable_path = os.path.join(str(tmp_path), "corrupted.png")
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


# ── Test 7: Persistence across restart still works ──


@pytest.mark.asyncio
async def test_persistence_across_restart_still_works(db):
    """State and audit history persist across new instances."""
    app = OnboardingApplication(
        applicant_name="Restart Test",
        business_name="Restart Corp",
        pan_number="ABCDE1234F",
        phone="9876543210",
        documents=[
            ApplicationDocument(
                document_type="pan_card",
                raw_text="Name: Restart Test\nPAN: ABCDE1234F\nDOB: 01/01/1990",
            )
        ],
    )

    memory1 = WorkflowMemory(db=db)
    audit1 = AuditLogger(db=db)
    engine1 = WorkerEngine(memory=memory1, audit=audit1)
    await engine1.process_application(app)
    app_id = app.application_id

    ctx1 = await memory1.get(app_id)
    events1 = await audit1.get_events_for_application(app_id)

    memory2 = WorkflowMemory(db=db)
    audit2 = AuditLogger(db=db)
    engine2 = WorkerEngine(memory=memory2, audit=audit2)

    ctx2 = await engine2.get_application_status(app_id)
    events2 = await engine2.get_application_history(app_id)

    assert ctx2 is not None
    assert ctx2.application.application_id == app_id
    assert ctx2.current_state == ctx1.current_state
    assert len(events2) == len(events1)


# ── Test 8: AuditPersistenceError has correct fields ──


@pytest.mark.asyncio
async def test_audit_persistence_error_has_correct_fields(db):
    """AuditPersistenceError contains application_id and event_type."""
    memory = WorkflowMemory(db=db)
    audit = AuditLogger(db=db)

    with patch.object(db.conn, "execute", side_effect=Exception("DB error")):
        with pytest.raises(AuditPersistenceError) as exc_info:
            await audit.record(
                application_id="test-app-001",
                state=WorkflowState.VALIDATING,
                event_type=EventType.STATE_TRANSITION,
                action="state_transition",
                result="SUCCESS",
            )

    assert exc_info.value.application_id == "test-app-001"
    assert exc_info.value.event_type == "STATE_TRANSITION"


# ── Test 9: PersistenceError has correct application_id ──


@pytest.mark.asyncio
async def test_persistence_error_has_correct_application_id(db):
    """PersistenceError contains the application_id."""
    memory = WorkflowMemory(db=db)
    app = OnboardingApplication(
        applicant_name="Error Test",
        business_name="Error Corp",
        pan_number="ABCDE1234F",
        phone="9876543210",
    )
    context = WorkflowContext(application=app)

    with patch.object(db.conn, "execute", side_effect=Exception("DB error")):
        with pytest.raises(PersistenceError) as exc_info:
            await memory.save(context)

    assert exc_info.value.application_id == app.application_id


# ── Test 10: State transition failure raises PersistenceError ──


@pytest.mark.asyncio
async def test_state_transition_failure_raises_persistence_error(db):
    """_transition() raises PersistenceError when save fails."""
    memory = WorkflowMemory(db=db)
    audit = AuditLogger(db=db)
    engine = WorkerEngine(memory=memory, audit=audit)

    app = OnboardingApplication(
        applicant_name="Transition Test",
        business_name="Transition Corp",
        pan_number="ABCDE1234F",
        phone="9876543210",
    )

    original_execute = db.conn.execute
    call_count = 0

    async def failing_on_first_workflow_write(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        sql = args[0] if args else kwargs.get("sql", "")
        if isinstance(sql, str) and "workflow_contexts" in sql and call_count <= 1:
            raise Exception("SQLite write failed during transition")
        return await original_execute(*args, **kwargs)

    with patch.object(db.conn, "execute", side_effect=failing_on_first_workflow_write):
        with pytest.raises(PersistenceError):
            await engine.process_application(app)


# ── Test 11: Audit failure is logged but workflow completes ──


@pytest.mark.asyncio
async def test_audit_failure_is_logged_but_workflow_completes(db, caplog):
    """When audit fails, a warning is logged and the workflow completes."""
    import logging

    memory = WorkflowMemory(db=db)
    audit = AuditLogger(db=db)
    engine = WorkerEngine(memory=memory, audit=audit)

    app = OnboardingApplication(
        applicant_name="Log Test",
        business_name="Log Corp",
        pan_number="ABCDE1234F",
        phone="9876543210",
    )

    original_execute = db.conn.execute
    audit_call_count = 0

    async def failing_audit_execute(*args, **kwargs):
        nonlocal audit_call_count
        sql = args[0] if args else kwargs.get("sql", "")
        if isinstance(sql, str) and "audit_events" in sql:
            audit_call_count += 1
            raise Exception("Audit write failed")
        return await original_execute(*args, **kwargs)

    with caplog.at_level(logging.WARNING):
        with patch.object(db.conn, "execute", side_effect=failing_audit_execute):
            context = await engine.process_application(app)

    assert context.current_state in (
        WorkflowState.APPROVED,
        WorkflowState.ESCALATED,
        WorkflowState.ESCALATED_TO_HUMAN,
        WorkflowState.MORE_INFORMATION_REQUIRED,
        WorkflowState.REJECTED,
    )
    assert any("Audit persistence failed" in record.message for record in caplog.records)


# ── Test 12: API returns 503 on persistence failure ──


@pytest.mark.asyncio
async def test_api_returns_503_on_persistence_failure(db):
    """The API returns 503 with structured error on persistence failure."""
    from fastapi.testclient import TestClient
    from app.main import app
    from app.memory.database import get_database

    client = TestClient(app)
    global_db = get_database()

    original_execute = global_db.conn.execute

    async def failing_execute(*args, **kwargs):
        raise Exception("SQLite write failed")

    with patch.object(global_db.conn, "execute", side_effect=failing_execute):
        response = client.post(
            "/api/v1/applications",
            json={
                "applicant_name": "Test User",
                "business_name": "Test Corp",
                "pan_number": "ABCDE1234F",
                "phone": "9876543210",
            },
        )

    assert response.status_code == 503
    body = response.json()
    assert body["error_code"] == "PERSISTENCE_FAILURE"
    assert "Application could not be saved" in body["message"]
