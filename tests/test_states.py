
from app.models.states import VALID_TRANSITIONS, WorkflowState, can_transition


def test_valid_transitions():
    assert can_transition(WorkflowState.RECEIVED, WorkflowState.VALIDATING)
    assert can_transition(WorkflowState.VALIDATING, WorkflowState.VERIFYING)
    assert can_transition(WorkflowState.VALIDATING, WorkflowState.MISSING_INFORMATION)
    assert can_transition(WorkflowState.VERIFYING, WorkflowState.ANALYZING_RISK)
    assert can_transition(WorkflowState.ANALYZING_RISK, WorkflowState.DECIDING)
    assert can_transition(WorkflowState.DECIDING, WorkflowState.APPROVED)
    assert can_transition(WorkflowState.DECIDING, WorkflowState.ESCALATED)
    assert can_transition(WorkflowState.DECIDING, WorkflowState.REJECTED)


def test_invalid_transitions():
    assert not can_transition(WorkflowState.RECEIVED, WorkflowState.APPROVED)
    assert not can_transition(WorkflowState.APPROVED, WorkflowState.VALIDATING)
    assert not can_transition(WorkflowState.RECEIVED, WorkflowState.DECIDING)
    assert not can_transition(WorkflowState.VALIDATING, WorkflowState.APPROVED)


def test_terminal_states_have_no_transitions():
    for state in [
        WorkflowState.APPROVED,
        WorkflowState.ESCALATED,
        WorkflowState.ESCALATED_TO_HUMAN,
        WorkflowState.REJECTED,
        WorkflowState.FAILED,
    ]:
        assert len(VALID_TRANSITIONS[state]) == 0, f"{state} should have no transitions"


def test_retry_loop():
    assert can_transition(WorkflowState.VERIFYING, WorkflowState.TOOL_RETRYING)
    assert can_transition(WorkflowState.TOOL_RETRYING, WorkflowState.VERIFYING)
    assert can_transition(WorkflowState.TOOL_RETRYING, WorkflowState.TOOL_FAILED)
    assert can_transition(WorkflowState.TOOL_FAILED, WorkflowState.ESCALATED_TO_HUMAN)
