from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

from app.models.states import FinalDecision, RiskLevel, WorkflowState


class ApplicationDocument(BaseModel):
    """A document submitted as part of an onboarding application."""

    document_id: str = Field(default_factory=lambda: str(uuid4()))
    document_type: str
    file_path: str | None = None
    raw_text: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class OnboardingApplication(BaseModel):
    """An incoming merchant or partner onboarding application."""

    application_id: str = Field(default_factory=lambda: str(uuid4()))
    applicant_name: str | None = None
    business_name: str | None = None
    business_type: str | None = None
    pan_number: str | None = None
    gst_number: str | None = None
    address: str | None = None
    phone: str | None = None
    email: str | None = None
    documents: list[ApplicationDocument] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    submitted_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ExtractedDocumentData(BaseModel):
    """Structured data extracted from a document."""

    document_id: str
    document_type: str
    extracted_fields: dict[str, Any] = Field(default_factory=dict)
    confidence: float = Field(ge=0.0, le=1.0)
    extraction_method: str = "llm"
    raw_response: str | None = None


class ComparisonResult(BaseModel):
    """Result of comparing application data with extracted document data."""

    field_comparisons: dict[str, FieldComparison] = Field(default_factory=dict)
    overall_match: bool = True
    inconsistencies: list[str] = Field(default_factory=list)


class FieldComparison(BaseModel):
    """Comparison of a single field between application and document."""

    field_name: str
    application_value: Any = None
    document_value: Any = None
    match: bool = True
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    discrepancy_reason: str | None = None


# Fix forward reference
ComparisonResult.model_rebuild()


class RiskAssessment(BaseModel):
    """Risk assessment of an onboarding application."""

    risk_level: RiskLevel
    risk_score: float = Field(ge=0.0, le=1.0)
    risk_factors: list[str] = Field(default_factory=list)
    mitigation_suggestions: list[str] = Field(default_factory=list)


class AIRecommendation(BaseModel):
    """Structured recommendation from the LLM."""

    recommended_action: FinalDecision
    confidence: float = Field(ge=0.0, le=1.0)
    risk_level: RiskLevel
    reason: str
    evidence: list[str] = Field(default_factory=list)


class WorkflowContext(BaseModel):
    """Full context maintained during workflow execution."""

    application: OnboardingApplication
    current_state: WorkflowState = WorkflowState.RECEIVED
    extracted_data: list[ExtractedDocumentData] = Field(default_factory=list)
    comparison_result: ComparisonResult | None = None
    risk_assessment: RiskAssessment | None = None
    recommendation: AIRecommendation | None = None
    final_decision: FinalDecision | None = None
    retry_count: int = 0
    missing_fields: list[str] = Field(default_factory=list)
    history: list[dict[str, Any]] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class AuditEvent(BaseModel):
    """An audit trail event."""

    event_id: str = Field(default_factory=lambda: str(uuid4()))
    application_id: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    state: WorkflowState
    event_type: EventType
    actor: str = "SAKSHAM"
    action: str
    result: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class DocumentProcessingRecord(BaseModel):
    """Persistent record of a processed document."""

    document_id: str
    application_id: str
    document_type: str
    original_filename: str
    stored_path: str
    processing_status: str
    raw_text: str = ""
    raw_text_available: bool = False
    ocr_confidence: float = 0.0
    field_extraction_confidence: float = 0.0
    overall_confidence: float = 0.0
    extracted_fields: dict[str, Any] = Field(default_factory=dict)
    processing_method: str = ""
    error_code: str | None = None
    error_message: str | None = None
    attempt_count: int = 1
    created_at: str = ""
    processed_at: str = ""


# Re-import EventType to make it available in this module
from app.models.states import EventType  # noqa: E402
