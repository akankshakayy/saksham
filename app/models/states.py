from __future__ import annotations

from enum import Enum


class WorkflowState(str, Enum):
    """Lifecycle states for an onboarding application."""

    RECEIVED = "RECEIVED"
    VALIDATING = "VALIDATING"
    MISSING_INFORMATION = "MISSING_INFORMATION"
    MORE_INFORMATION_REQUIRED = "MORE_INFORMATION_REQUIRED"
    VERIFYING = "VERIFYING"
    ANALYZING_RISK = "ANALYZING_RISK"
    DECIDING = "DECIDING"
    APPROVED = "APPROVED"
    ESCALATED = "ESCALATED"
    REJECTED = "REJECTED"
    FAILED = "FAILED"
    TOOL_RETRYING = "TOOL_RETRYING"
    LOW_CONFIDENCE = "LOW_CONFIDENCE"
    TOOL_FAILED = "TOOL_FAILED"
    ESCALATED_TO_HUMAN = "ESCALATED_TO_HUMAN"


class FinalDecision(str, Enum):
    """High-level decisions the worker can make."""

    APPROVE = "APPROVE"
    REQUEST_MORE_INFORMATION = "REQUEST_MORE_INFORMATION"
    ESCALATE_TO_HUMAN = "ESCALATE_TO_HUMAN"
    REJECT_OR_BLOCK = "REJECT_OR_BLOCK"


class RiskLevel(str, Enum):
    """Risk classification levels."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class EventType(str, Enum):
    """Types of audit events."""

    STATE_TRANSITION = "STATE_TRANSITION"
    TOOL_EXECUTION = "TOOL_EXECUTION"
    AI_RECOMMENDATION = "AI_RECOMMENDATION"
    POLICY_DECISION = "POLICY_DECISION"
    RETRY = "RETRY"
    FAILURE = "FAILURE"
    ESCALATION = "ESCALATION"
    INPUT_RECEIVED = "INPUT_RECEIVED"
    EXTRACTION = "EXTRACTION"
    COMPARISON = "COMPARISON"
    DOCUMENT_UPLOAD_RECEIVED = "DOCUMENT_UPLOAD_RECEIVED"
    DOCUMENT_VALIDATION_COMPLETED = "DOCUMENT_VALIDATION_COMPLETED"
    DOCUMENT_PROCESSING_STARTED = "DOCUMENT_PROCESSING_STARTED"
    DOCUMENT_PROCESSING_COMPLETED = "DOCUMENT_PROCESSING_COMPLETED"
    DOCUMENT_PROCESSING_FAILED = "DOCUMENT_PROCESSING_FAILED"
    DOCUMENT_PROCESSING_REUSED = "DOCUMENT_PROCESSING_REUSED"
    DOCUMENT_LOW_CONFIDENCE = "DOCUMENT_LOW_CONFIDENCE"


# Valid state transitions
VALID_TRANSITIONS: dict[WorkflowState, set[WorkflowState]] = {
    WorkflowState.RECEIVED: {WorkflowState.VALIDATING},
    WorkflowState.VALIDATING: {
        WorkflowState.MISSING_INFORMATION,
        WorkflowState.VERIFYING,
        WorkflowState.FAILED,
    },
    WorkflowState.MISSING_INFORMATION: {WorkflowState.MORE_INFORMATION_REQUIRED},
    WorkflowState.MORE_INFORMATION_REQUIRED: {WorkflowState.VALIDATING},
    WorkflowState.VERIFYING: {
        WorkflowState.ANALYZING_RISK,
        WorkflowState.TOOL_RETRYING,
        WorkflowState.TOOL_FAILED,
        WorkflowState.LOW_CONFIDENCE,
        WorkflowState.FAILED,
    },
    WorkflowState.TOOL_RETRYING: {WorkflowState.VERIFYING, WorkflowState.TOOL_FAILED},
    WorkflowState.TOOL_FAILED: {WorkflowState.ESCALATED_TO_HUMAN, WorkflowState.FAILED},
    WorkflowState.LOW_CONFIDENCE: {WorkflowState.ESCALATED_TO_HUMAN, WorkflowState.VERIFYING},
    WorkflowState.ANALYZING_RISK: {
        WorkflowState.DECIDING,
        WorkflowState.FAILED,
    },
    WorkflowState.DECIDING: {
        WorkflowState.APPROVED,
        WorkflowState.ESCALATED,
        WorkflowState.MORE_INFORMATION_REQUIRED,
        WorkflowState.REJECTED,
        WorkflowState.FAILED,
    },
    WorkflowState.APPROVED: set(),
    WorkflowState.ESCALATED: set(),
    WorkflowState.ESCALATED_TO_HUMAN: set(),
    WorkflowState.REJECTED: set(),
    WorkflowState.FAILED: set(),
}


def can_transition(from_state: WorkflowState, to_state: WorkflowState) -> bool:
    """Check if a state transition is valid."""
    return to_state in VALID_TRANSITIONS.get(from_state, set())
