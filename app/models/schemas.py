from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.models.states import FinalDecision, RiskLevel, WorkflowState


class SubmitApplicationRequest(BaseModel):
    """Request to submit a new onboarding application."""

    applicant_name: str | None = None
    business_name: str | None = None
    business_type: str | None = None
    pan_number: str | None = None
    gst_number: str | None = None
    address: str | None = None
    phone: str | None = None
    email: str | None = None
    documents: list[DocumentInput] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class DocumentInput(BaseModel):
    """Input document for an application."""

    document_type: str
    file_path: str | None = None
    raw_text: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


SubmitApplicationRequest.model_rebuild()


class SubmitApplicationResponse(BaseModel):
    """Response after submitting an application."""

    application_id: str
    state: WorkflowState
    message: str


class ApplicationStatusResponse(BaseModel):
    """Current status of an application."""

    application_id: str
    current_state: WorkflowState
    missing_fields: list[str] = Field(default_factory=list)
    retry_count: int = 0
    final_decision: FinalDecision | None = None
    risk_level: RiskLevel | None = None
    created_at: datetime
    updated_at: datetime


class AuditEventResponse(BaseModel):
    """An audit event in API response."""

    event_id: str
    application_id: str
    timestamp: datetime
    state: WorkflowState
    event_type: str
    actor: str
    action: str
    result: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class WorkflowHistoryResponse(BaseModel):
    """Full workflow history for an application."""

    application_id: str
    events: list[AuditEventResponse] = Field(default_factory=list)


class HealthResponse(BaseModel):
    """Health check response."""

    status: str = "ok"
    version: str = "0.1.0"
