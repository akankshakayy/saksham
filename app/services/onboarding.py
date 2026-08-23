from __future__ import annotations

from typing import Any

from app.audit.logger import AuditLogger
from app.memory.store import DocumentStore, WorkflowMemory
from app.models.domain import ApplicationDocument, OnboardingApplication
from app.models.schemas import (
    ApplicationStatusResponse,
    AuditEventResponse,
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
        """Submit a new onboarding application for processing."""
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

        context = await self.engine.process_application(application)

        return SubmitApplicationResponse(
            application_id=application.application_id,
            state=context.current_state,
            message=f"Application processed. Current state: {context.current_state.value}",
        )

    async def get_status(self, application_id: str) -> ApplicationStatusResponse | None:
        """Get current status of an application."""
        context = await self.engine.get_application_status(application_id)
        if not context:
            return None

        return ApplicationStatusResponse(
            application_id=context.application.application_id,
            current_state=context.current_state,
            missing_fields=context.missing_fields,
            retry_count=context.retry_count,
            final_decision=context.final_decision,
            risk_level=context.risk_assessment.risk_level
            if context.risk_assessment
            else None,
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

    async def list_applications(self) -> list[dict[str, Any]]:
        """List all applications."""
        return await self.engine.list_applications()
