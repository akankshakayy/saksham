from __future__ import annotations

import json

from app.audit.logger import AuditLogger
from app.memory.store import DocumentStore, WorkflowMemory
from app.models.domain import ApplicationDocument, OnboardingApplication
from app.models.schemas import (
    ApplicationStatusResponse,
    ApplicationSummaryResponse,
    AuditEventResponse,
    DocumentDetailResponse,
    DocumentSummaryResponse,
    ListApplicationsResponse,
    RawTextResponse,
    RecommendationResponse,
    SubmitApplicationRequest,
    SubmitApplicationResponse,
    WorkflowHistoryResponse,
)
from app.worker.engine import WorkerEngine


class OnboardingService:
    """Service layer for onboarding operations."""

    def __init__(self) -> None:
        self.memory = WorkflowMemory()
        self.audit = AuditLogger()
        self.document_store = DocumentStore()
        self.engine = WorkerEngine(
            memory=self.memory,
            audit=self.audit,
            document_store=self.document_store,
        )

    async def submit_application(
        self, request: SubmitApplicationRequest
    ) -> SubmitApplicationResponse:
        """Submit a new onboarding application for background processing.

        Persists the application in RECEIVED state and returns immediately.
        The full workflow runs in the background.
        """
        documents = [
            ApplicationDocument(
                document_type=doc.document_type,
                file_path=doc.file_path,
                raw_text=doc.raw_text,
                metadata=doc.metadata,
            )
            for doc in request.documents
        ]

        application = OnboardingApplication(
            applicant_name=request.applicant_name,
            business_name=request.business_name,
            business_type=request.business_type,
            pan_number=request.pan_number,
            gst_number=request.gst_number,
            address=request.address,
            phone=request.phone,
            email=request.email,
            documents=documents,
            metadata=request.metadata,
        )

        from app.models.domain import WorkflowContext
        from app.models.states import EventType, WorkflowState

        context = WorkflowContext(application=application)
        await self.memory.save(context)

        await self.audit.record(
            application_id=application.application_id,
            state=WorkflowState.RECEIVED,
            event_type=EventType.INPUT_RECEIVED,
            action="submit_application",
            result="ACCEPTED",
        )

        return SubmitApplicationResponse(
            application_id=application.application_id,
            state=context.current_state,
            message=f"Application accepted. Current state: {context.current_state.value}",
        )

    async def get_status(self, application_id: str) -> ApplicationStatusResponse | None:
        """Get current status of an application."""
        context = await self.engine.get_application_status(application_id)
        if not context:
            return None

        recommendation = None
        if context.recommendation:
            recommendation = RecommendationResponse(
                recommended_action=context.recommendation.recommended_action,
                confidence=context.recommendation.confidence,
                risk_level=context.recommendation.risk_level,
                reason=context.recommendation.reason,
                evidence=context.recommendation.evidence,
                source=context.recommendation.source,
                model=context.recommendation.model,
            )

        return ApplicationStatusResponse(
            application_id=context.application.application_id,
            current_state=context.current_state,
            applicant_name=context.application.applicant_name,
            business_name=context.application.business_name,
            business_type=context.application.business_type,
            pan_number=context.application.pan_number,
            gst_number=context.application.gst_number,
            address=context.application.address,
            phone=context.application.phone,
            email=context.application.email,
            missing_fields=context.missing_fields,
            retry_count=context.retry_count,
            final_decision=context.final_decision,
            risk_level=context.risk_assessment.risk_level if context.risk_assessment else None,
            risk_score=context.risk_assessment.risk_score if context.risk_assessment else None,
            risk_factors=context.risk_assessment.risk_factors if context.risk_assessment else [],
            recommendation=recommendation,
            created_at=context.created_at,
            updated_at=context.updated_at,
        )

    async def get_history(self, application_id: str) -> WorkflowHistoryResponse | None:
        """Get full audit history for an application."""
        context = await self.engine.get_application_status(application_id)
        if not context:
            return None

        events = await self.engine.get_application_history(application_id)
        return WorkflowHistoryResponse(
            application_id=application_id,
            events=[
                AuditEventResponse(
                    event_id=e.event_id,
                    application_id=e.application_id,
                    timestamp=e.timestamp,
                    state=e.state,
                    event_type=e.event_type.value,
                    actor=e.actor,
                    action=e.action,
                    result=e.result,
                    metadata=e.metadata,
                )
                for e in events
            ],
        )

    async def list_applications(
        self,
        *,
        state: str | None = None,
        risk_level: str | None = None,
        final_decision: str | None = None,
        q: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> ListApplicationsResponse:
        """List applications with pagination and filtering."""
        if offset < 0:
            offset = 0
        if limit < 1:
            limit = 1
        if limit > 100:
            limit = 100

        applications, total = await self.memory.list_applications_paginated(
            state=state,
            risk_level=risk_level,
            final_decision=final_decision,
            q=q,
            limit=limit,
            offset=offset,
        )

        return ListApplicationsResponse(
            applications=[
                ApplicationSummaryResponse(
                    application_id=a["application_id"],
                    applicant_name=a["applicant_name"],
                    business_name=a["business_name"],
                    current_state=a["current_state"],
                    final_decision=a["final_decision"],
                    risk_level=a["risk_level"],
                    risk_score=a["risk_score"],
                    created_at=a["created_at"],
                    updated_at=a["updated_at"],
                )
                for a in applications
            ],
            total=total,
            limit=limit,
            offset=offset,
        )

    async def application_exists(self, application_id: str) -> bool:
        """Check if an application exists."""
        return await self.memory.exists(application_id)

    async def get_documents(self, application_id: str) -> list[DocumentSummaryResponse]:
        """Get all documents for an application."""
        docs = await self.document_store.get_documents_for_application(application_id)
        return [
            DocumentSummaryResponse(
                document_id=d["document_id"],
                application_id=d["application_id"],
                document_type=d["document_type"],
                original_filename=d["original_filename"],
                processing_status=d["processing_status"],
                overall_confidence=d["overall_confidence"],
                ocr_confidence=d["ocr_confidence"],
                field_extraction_confidence=d["field_extraction_confidence"],
                processing_method=d["processing_method"],
                created_at=d["created_at"],
                processed_at=d["processed_at"],
            )
            for d in docs
        ]

    async def get_document(
        self, application_id: str, document_id: str
    ) -> DocumentDetailResponse | None:
        """Get a single document scoped to an application."""
        doc = await self.document_store.get_document_for_application(application_id, document_id)
        if not doc:
            return None
        return DocumentDetailResponse(
            document_id=doc["document_id"],
            application_id=doc["application_id"],
            document_type=doc["document_type"],
            original_filename=doc["original_filename"],
            processing_status=doc["processing_status"],
            overall_confidence=doc["overall_confidence"],
            ocr_confidence=doc["ocr_confidence"],
            field_extraction_confidence=doc["field_extraction_confidence"],
            extracted_fields=json.loads(doc["extracted_fields_json"])
            if doc["extracted_fields_json"]
            else {},
            processing_method=doc["processing_method"],
            error_code=doc["error_code"],
            error_message=doc["error_message"],
            attempt_count=doc["attempt_count"],
            created_at=doc["created_at"],
            processed_at=doc["processed_at"],
        )

    async def get_raw_text(self, application_id: str, document_id: str) -> RawTextResponse | None:
        """Get raw OCR text for a document scoped to an application."""
        doc = await self.document_store.get_document_for_application(application_id, document_id)
        if not doc:
            return None
        raw_text = doc["raw_text"] or ""
        return RawTextResponse(
            document_id=doc["document_id"],
            application_id=doc["application_id"],
            raw_text=raw_text,
            character_count=len(raw_text),
        )
