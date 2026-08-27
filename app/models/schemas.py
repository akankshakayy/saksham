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


class RecommendationResponse(BaseModel):
    """AI recommendation in API response."""

    recommended_action: FinalDecision
    confidence: float = Field(ge=0.0, le=1.0)
    risk_level: RiskLevel
    reason: str
    evidence: list[str] = Field(default_factory=list)
    source: str = "unknown"
    model: str | None = None


class ApplicationStatusResponse(BaseModel):
    """Current status of an application."""

    application_id: str
    current_state: WorkflowState
    applicant_name: str | None = None
    business_name: str | None = None
    business_type: str | None = None
    pan_number: str | None = None
    gst_number: str | None = None
    address: str | None = None
    phone: str | None = None
    email: str | None = None
    missing_fields: list[str] = Field(default_factory=list)
    retry_count: int = 0
    final_decision: FinalDecision | None = None
    risk_level: RiskLevel | None = None
    risk_score: float | None = None
    risk_factors: list[str] = Field(default_factory=list)
    recommendation: RecommendationResponse | None = None
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


class ApplicationSummaryResponse(BaseModel):
    """Summary of an application for list views."""

    application_id: str
    applicant_name: str | None = None
    business_name: str | None = None
    current_state: WorkflowState
    final_decision: FinalDecision | None = None
    risk_level: RiskLevel | None = None
    risk_score: float | None = None
    created_at: str
    updated_at: str


class ListApplicationsResponse(BaseModel):
    """Paginated list of applications."""

    applications: list[ApplicationSummaryResponse] = Field(default_factory=list)
    total: int = 0
    limit: int = 20
    offset: int = 0


class DocumentUploadResponse(BaseModel):
    """Response after uploading and processing a document."""

    document_id: str
    application_id: str
    document_type: str
    original_filename: str
    processing_status: str
    overall_confidence: float = 0.0
    ocr_confidence: float = 0.0
    field_extraction_confidence: float = 0.0
    extracted_fields: dict[str, Any] = Field(default_factory=dict)
    processing_method: str = ""
    error_code: str | None = None
    error_message: str | None = None


class DocumentSummaryResponse(BaseModel):
    """Summary of a document for list views."""

    document_id: str
    application_id: str
    document_type: str
    original_filename: str
    processing_status: str
    overall_confidence: float = 0.0
    ocr_confidence: float = 0.0
    field_extraction_confidence: float = 0.0
    processing_method: str = ""
    created_at: str = ""
    processed_at: str = ""


class DocumentDetailResponse(BaseModel):
    """Full document detail including extracted fields."""

    document_id: str
    application_id: str
    document_type: str
    original_filename: str
    processing_status: str
    overall_confidence: float = 0.0
    ocr_confidence: float = 0.0
    field_extraction_confidence: float = 0.0
    extracted_fields: dict[str, Any] = Field(default_factory=dict)
    processing_method: str = ""
    error_code: str | None = None
    error_message: str | None = None
    attempt_count: int = 1
    created_at: str = ""
    processed_at: str = ""


class RawTextResponse(BaseModel):
    """Raw OCR text from a document."""

    document_id: str
    application_id: str
    raw_text: str = ""
    character_count: int = 0


class ErrorResponse(BaseModel):
    """Standard error response."""

    error_code: str
    message: str
