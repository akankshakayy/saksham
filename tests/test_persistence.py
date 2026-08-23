"""Tests proving that persistence is real and survives new instances."""
import pytest
import pytest_asyncio

from app.audit.logger import AuditLogger
from app.memory.database import Database
from app.memory.store import WorkflowMemory
from app.models.domain import ApplicationDocument, OnboardingApplication
from app.models.states import WorkflowState
from app.worker.engine import WorkerEngine


@pytest_asyncio.fixture
async def db(tmp_path):
    """Create a temporary SQLite database for each test."""
    db_path = str(tmp_path / "test_persistence.db")
    database = Database(f"sqlite+aiosqlite:///{db_path}")
    await database.connect()
    yield database
    await database.close()


# ── Test 1: Workflow context survives a new store instance ──


@pytest.mark.asyncio
async def test_context_survives_new_store_instance(db):
    """Store context with one WorkflowMemory, retrieve with a completely new one."""
    app = OnboardingApplication(
        applicant_name="Persist Test",
        business_name="Persist Corp",
        pan_number="ABCDE1234F",
        phone="9876543210",
    )

    # Process and store using first memory instance
    memory1 = WorkflowMemory(db=db)
    audit1 = AuditLogger(db=db)
    engine1 = WorkerEngine(memory=memory1, audit=audit1)
    await engine1.process_application(app)
    app_id = app.application_id

    # Verify first instance can read it
    ctx1 = await memory1.get(app_id)
    assert ctx1 is not None
    assert ctx1.application.application_id == app_id

    # Create a completely new memory instance (simulates restart)
    memory2 = WorkflowMemory(db=db)

    # New instance reads from same database
    ctx2 = await memory2.get(app_id)
    assert ctx2 is not None
    assert ctx2.application.application_id == app_id
    assert ctx2.application.applicant_name == "Persist Test"
    assert ctx2.application.pan_number == "ABCDE1234F"
    assert ctx2.current_state == ctx1.current_state


# ── Test 2: Audit history survives a new logger instance ──


@pytest.mark.asyncio
async def test_audit_history_survives_new_logger_instance(db):
    """Record events with one AuditLogger, retrieve with a new one."""
    app = OnboardingApplication(
        applicant_name="Audit Test",
        business_name="Audit Corp",
        pan_number="ABCDE1234F",
        phone="9876543210",
    )

    # Process application to generate audit events
    memory = WorkflowMemory(db=db)
    audit1 = AuditLogger(db=db)
    engine = WorkerEngine(memory=memory, audit=audit1)
    await engine.process_application(app)
    app_id = app.application_id

    # Get events from first logger
    events1 = await audit1.get_events_for_application(app_id)
    assert len(events1) > 0

    # Create a completely new logger instance (simulates restart)
    audit2 = AuditLogger(db=db)

    # New logger reads same events
    events2 = await audit2.get_events_for_application(app_id)
    assert len(events2) == len(events1)

    # Verify event IDs match
    ids1 = {e.event_id for e in events1}
    ids2 = {e.event_id for e in events2}
    assert ids1 == ids2


# ── Test 3: History ordering ──


@pytest.mark.asyncio
async def test_history_ordering(db):
    """Events are returned in chronological order."""
    app = OnboardingApplication(
        applicant_name="Order Test",
        business_name="Order Corp",
        pan_number="ABCDE1234F",
        phone="9876543210",
    )

    memory = WorkflowMemory(db=db)
    audit = AuditLogger(db=db)
    engine = WorkerEngine(memory=memory, audit=audit)
    await engine.process_application(app)

    events = await audit.get_events_for_application(app.application_id)

    # Verify chronological ordering
    for i in range(1, len(events)):
        prev = events[i - 1]
        curr = events[i]
        assert prev.timestamp <= curr.timestamp, (
            f"Event {i-1} ({prev.timestamp}) should be <= Event {i} ({curr.timestamp})"
        )

    # Verify we see the expected sequence
    event_types = [e.event_type.value for e in events]
    assert "INPUT_RECEIVED" in event_types
    assert "STATE_TRANSITION" in event_types
    # INPUT_RECEIVED should be first
    assert event_types[0] == "INPUT_RECEIVED"


# ── Test 4: State updates persist ──


@pytest.mark.asyncio
async def test_state_updates_persist(db):
    """Store, update, then verify the newest state is returned."""
    app = OnboardingApplication(
        applicant_name="Update Test",
        business_name="Update Corp",
        pan_number="ABCDE1234F",
        phone="9876543210",
    )

    memory = WorkflowMemory(db=db)
    audit = AuditLogger(db=db)
    engine = WorkerEngine(memory=memory, audit=audit)
    await engine.process_application(app)
    app_id = app.application_id

    # Get the final state
    ctx = await memory.get(app_id)
    final_state = ctx.current_state
    final_decision = ctx.final_decision

    # Create a new memory and verify the final state is persisted
    memory2 = WorkflowMemory(db=db)
    ctx2 = await memory2.get(app_id)
    assert ctx2.current_state == final_state
    assert ctx2.final_decision == final_decision


# ── Test 5: Application isolation ──


@pytest.mark.asyncio
async def test_application_isolation(db):
    """Two applications are stored independently and never mixed."""
    app1 = OnboardingApplication(
        applicant_name="App One",
        business_name="Corp One",
        pan_number="ABCDE1234F",
        phone="1111111111",
    )
    app2 = OnboardingApplication(
        applicant_name="App Two",
        business_name="Corp Two",
        pan_number="FFFFF1111F",
        phone="2222222222",
    )

    memory = WorkflowMemory(db=db)
    audit = AuditLogger(db=db)
    engine = WorkerEngine(memory=memory, audit=audit)

    await engine.process_application(app1)
    await engine.process_application(app2)

    # Retrieve each independently
    ctx1 = await memory.get(app1.application_id)
    ctx2 = await memory.get(app2.application_id)

    assert ctx1 is not None
    assert ctx2 is not None
    assert ctx1.application.applicant_name == "App One"
    assert ctx2.application.applicant_name == "App Two"
    assert ctx1.application.pan_number == "ABCDE1234F"
    assert ctx2.application.pan_number == "FFFFF1111F"

    # Audit events are also isolated
    events1 = await audit.get_events_for_application(app1.application_id)
    events2 = await audit.get_events_for_application(app2.application_id)

    assert all(e.application_id == app1.application_id for e in events1)
    assert all(e.application_id == app2.application_id for e in events2)


# ── Test 6: Full workflow persistence ──


@pytest.mark.asyncio
async def test_full_workflow_persistence(db):
    """Run a complete workflow, then verify everything persists."""
    app = OnboardingApplication(
        applicant_name="Full Workflow",
        business_name="Full Corp",
        pan_number="ABCDE1234F",
        phone="9876543210",
        documents=[
            ApplicationDocument(
                document_type="pan_card",
                raw_text="Name: Full Workflow\nPAN: ABCDE1234F\nDOB: 01/01/1990",
            )
        ],
    )

    # Process the application
    memory1 = WorkflowMemory(db=db)
    audit1 = AuditLogger(db=db)
    engine1 = WorkerEngine(memory=memory1, audit=audit1)
    await engine1.process_application(app)
    app_id = app.application_id

    # Simulate restart: create entirely new instances
    memory2 = WorkflowMemory(db=db)
    audit2 = AuditLogger(db=db)
    engine2 = WorkerEngine(memory=memory2, audit=audit2)

    # Verify state persisted
    ctx = await engine2.get_application_status(app_id)
    assert ctx is not None
    assert ctx.current_state in (
        WorkflowState.APPROVED,
        WorkflowState.ESCALATED,
        WorkflowState.ESCALATED_TO_HUMAN,
        WorkflowState.MORE_INFORMATION_REQUIRED,
        WorkflowState.REJECTED,
    )
    # Note: final_decision may be None when escalated due to tool failure

    # Verify audit history persisted
    events = await engine2.get_application_history(app_id)
    assert len(events) > 0

    # Verify the history tells a meaningful story
    event_actions = [e.action for e in events]
    event_types = [e.event_type.value for e in events]

    assert "submit_application" in event_actions
    assert "INPUT_RECEIVED" in event_types
    assert "STATE_TRANSITION" in event_types

    # Verify we can reconstruct the decision story
    transition_events = [e for e in events if e.event_type.value == "STATE_TRANSITION"]
    assert len(transition_events) >= 2  # At least RECEIVED -> VALIDATING -> ...

    # The final state in the audit trail matches the stored context
    last_transition = transition_events[-1]
    assert ctx.current_state.value == last_transition.metadata["to_state"]
