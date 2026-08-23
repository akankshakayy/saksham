from __future__ import annotations

import logging
from datetime import datetime, timezone

from app.audit.logger import AuditLogger
from app.config.settings import get_settings
from app.memory.errors import AuditPersistenceError, PersistenceError
from app.memory.store import DocumentStore, WorkflowMemory
from app.models.domain import OnboardingApplication, WorkflowContext
from app.models.states import EventType, FinalDecision, RiskLevel, WorkflowState, can_transition
from app.tools import (
    assess_risk,
    compare_information,
    create_escalation,
    extract_document_data,
    get_ai_recommendation,
    validate_application,
)

logger = logging.getLogger(__name__)


class WorkerEngine:
    """Orchestrates the full onboarding verification workflow.

    Follows the pipeline:
    Input Validation -> Document Verification -> AI Analysis -> Risk Assessment
    -> Policy Enforcement -> Final Decision -> Action/Escalation
    """

    def __init__(
        self,
        memory: WorkflowMemory | None = None,
        audit: AuditLogger | None = None,
        document_store: DocumentStore | None = None,
    ) -> None:
        self.memory = memory or WorkflowMemory()
        self.audit = audit or AuditLogger()
        self.document_store = document_store or DocumentStore()
        self.settings = get_settings()

    async def process_application(
        self, application: OnboardingApplication
    ) -> WorkflowContext:
        """Process an onboarding application through the full workflow.

        Raises PersistenceError if the initial context cannot be persisted.
        """
        context = WorkflowContext(application=application)
        await self.memory.save(context)

        await self._record_event(
            context, EventType.INPUT_RECEIVED, "submit_application", "SUCCESS"
        )

        context = await self._validate(context)
        if context.current_state in (
            WorkflowState.MISSING_INFORMATION,
            WorkflowState.MORE_INFORMATION_REQUIRED,
            WorkflowState.FAILED,
        ):
            return context

        context = await self._verify_documents(context)
        if context.current_state in (
            WorkflowState.TOOL_FAILED,
            WorkflowState.LOW_CONFIDENCE,
            WorkflowState.FAILED,
            WorkflowState.ESCALATED_TO_HUMAN,
        ):
            return context

        context = await self._analyze_and_decide(context)

        return context

    async def _validate(self, context: WorkflowContext) -> WorkflowContext:
        """Validate application input."""
        await self._transition(context, WorkflowState.VALIDATING)

        result = validate_application(context.application)

        if not result.is_valid:
            context.missing_fields = result.missing_fields

            await self._record_event(
                context,
                EventType.TOOL_EXECUTION,
                "validate_application",
                "MISSING_DATA",
                {
                    "missing_fields": result.missing_fields,
                    "invalid_fields": result.invalid_fields,
                    "errors": result.errors,
                },
            )

            if result.missing_fields:
                await self._transition(context, WorkflowState.MISSING_INFORMATION)
                await self._transition(context, WorkflowState.MORE_INFORMATION_REQUIRED)
                context.final_decision = FinalDecision.REQUEST_MORE_INFORMATION
                return context
            else:
                await self._transition(context, WorkflowState.FAILED)
                context.final_decision = FinalDecision.REJECT_OR_BLOCK
                return context

        await self._record_event(
            context, EventType.TOOL_EXECUTION, "validate_application", "SUCCESS"
        )
        await self._transition(context, WorkflowState.VERIFYING)
        return context

    async def _verify_documents(self, context: WorkflowContext) -> WorkflowContext:
        """Extract data from documents and compare with application.

        Checks for persisted document processing results first.
        Only runs extraction pipeline when no persisted result exists.
        """
        max_retries = self.settings.max_tool_retries

        persisted_docs = await self.document_store.get_documents_for_application(
            context.application.application_id
        )
        persisted_map = {d["document_id"]: d for d in persisted_docs}

        for doc in context.application.documents:
            persisted = persisted_map.get(doc.document_id)

            if persisted and persisted["processing_status"] == "completed":
                await self._record_event(
                    context,
                    EventType.DOCUMENT_PROCESSING_REUSED,
                    "extract_document_data",
                    "REUSED",
                    {
                        "document_id": doc.document_id,
                        "document_type": doc.document_type,
                        "processing_method": persisted["processing_method"],
                        "overall_confidence": persisted["overall_confidence"],
                    },
                )
                ext_data = self._build_extracted_data_from_persisted(doc, persisted)
                if ext_data.confidence >= self.settings.low_confidence_threshold:
                    context.extracted_data.append(ext_data)
                    continue

            ext_data = await self._extract_with_retry(context, doc, max_retries)
            if ext_data is not None:
                context.extracted_data.append(ext_data)

        if not context.extracted_data and context.application.documents:
            await self._transition(context, WorkflowState.TOOL_FAILED)
            context.final_decision = FinalDecision.ESCALATE_TO_HUMAN
            await self._record_event(
                context,
                EventType.FAILURE,
                "extract_document_data",
                "ALL_FAILED",
                {"retry_count": context.retry_count},
            )
            await create_escalation(context, "All document extraction attempts failed")
            await self._transition(context, WorkflowState.ESCALATED_TO_HUMAN)
            return context

        context.comparison_result = compare_information(
            context.application, context.extracted_data
        )

        await self._record_event(
            context,
            EventType.COMPARISON,
            "compare_information",
            "SUCCESS" if context.comparison_result.overall_match else "MISMATCH",
            {
                "inconsistencies": context.comparison_result.inconsistencies,
                "overall_match": context.comparison_result.overall_match,
            },
        )

        low_confidence = [
            ext for ext in context.extracted_data
            if ext.confidence < self.settings.low_confidence_threshold
        ]
        if low_confidence and context.retry_count >= max_retries:
            context.final_decision = FinalDecision.ESCALATE_TO_HUMAN
            await self._transition(context, WorkflowState.LOW_CONFIDENCE)
            return context

        await self._transition(context, WorkflowState.ANALYZING_RISK)
        return context

    def _build_extracted_data_from_persisted(self, doc, persisted):
        """Build ExtractedDocumentData from a persisted document record."""
        import json
        from app.models.domain import ExtractedDocumentData

        fields_json = persisted.get("extracted_fields_json", "{}")
        extracted_fields = json.loads(fields_json) if isinstance(fields_json, str) else fields_json

        field_values = {}
        for field_name, field_data in extracted_fields.items():
            if isinstance(field_data, dict):
                field_values[field_name] = field_data.get("value")
            else:
                field_values[field_name] = field_data

        return ExtractedDocumentData(
            document_id=persisted["document_id"],
            document_type=persisted["document_type"],
            extracted_fields=field_values,
            confidence=persisted["overall_confidence"],
            extraction_method=persisted["processing_method"],
            raw_response=persisted.get("raw_text", ""),
        )

    async def _extract_with_retry(self, context, doc, max_retries):
        """Extract document data with bounded retries.

        Passes file_path and application_id to enable real document processing.
        """
        for attempt in range(max_retries):
            try:
                await self._record_event(
                    context,
                    EventType.DOCUMENT_PROCESSING_STARTED,
                    "extract_document_data",
                    "STARTED",
                    {
                        "document_id": doc.document_id,
                        "document_type": doc.document_type,
                        "attempt": attempt + 1,
                        "has_file_path": doc.file_path is not None,
                    },
                )

                ext_data = await extract_document_data(
                    doc,
                    file_path=doc.file_path,
                    application_id=context.application.application_id,
                )

                if ext_data.confidence >= self.settings.low_confidence_threshold:
                    await self._record_event(
                        context,
                        EventType.DOCUMENT_PROCESSING_COMPLETED,
                        "extract_document_data",
                        "SUCCESS",
                        {
                            "document_type": doc.document_type,
                            "confidence": ext_data.confidence,
                            "extraction_method": ext_data.extraction_method,
                            "attempt": attempt + 1,
                        },
                    )
                    await self._record_event(
                        context,
                        EventType.EXTRACTION,
                        "extract_document_data",
                        "SUCCESS",
                        {
                            "document_type": doc.document_type,
                            "confidence": ext_data.confidence,
                            "attempt": attempt + 1,
                        },
                    )
                    return ext_data

                await self._record_event(
                    context,
                    EventType.DOCUMENT_LOW_CONFIDENCE,
                    "extract_document_data",
                    "LOW_CONFIDENCE",
                    {
                        "confidence": ext_data.confidence,
                        "attempt": attempt + 1,
                    },
                )
                context.retry_count += 1
                await self._record_event(
                    context,
                    EventType.RETRY,
                    "extract_document_data",
                    "LOW_CONFIDENCE",
                    {
                        "confidence": ext_data.confidence,
                        "attempt": attempt + 1,
                    },
                )
                await self._transition(context, WorkflowState.TOOL_RETRYING)
                await self._transition(context, WorkflowState.VERIFYING)

            except Exception as e:
                context.retry_count += 1
                await self._record_event(
                    context,
                    EventType.DOCUMENT_PROCESSING_FAILED,
                    "extract_document_data",
                    "ERROR",
                    {"error": str(e), "attempt": attempt + 1},
                )
                await self._record_event(
                    context,
                    EventType.FAILURE,
                    "extract_document_data",
                    "ERROR",
                    {"error": str(e), "attempt": attempt + 1},
                )
                if attempt < max_retries - 1:
                    await self._transition(context, WorkflowState.TOOL_RETRYING)
                    await self._transition(context, WorkflowState.VERIFYING)

        return None

    async def _analyze_and_decide(self, context: WorkflowContext) -> WorkflowContext:
        """Perform risk assessment and make final decision."""
        context.risk_assessment = assess_risk(
            context.comparison_result,
            context.extracted_data,
            context.application.metadata,
        )

        await self._record_event(
            context,
            EventType.TOOL_EXECUTION,
            "assess_risk",
            "SUCCESS",
            {
                "risk_level": context.risk_assessment.risk_level.value,
                "risk_score": context.risk_assessment.risk_score,
                "risk_factors": context.risk_assessment.risk_factors,
            },
        )

        context.recommendation = await get_ai_recommendation(context)

        await self._record_event(
            context,
            EventType.AI_RECOMMENDATION,
            "get_ai_recommendation",
            "SUCCESS",
            {
                "recommended_action": context.recommendation.recommended_action.value,
                "confidence": context.recommendation.confidence,
                "reason": context.recommendation.reason,
            },
        )

        await self._transition(context, WorkflowState.DECIDING)

        final_decision = self._enforce_policy(context)
        context.final_decision = final_decision

        await self._record_event(
            context,
            EventType.POLICY_DECISION,
            "enforce_policy",
            final_decision.value,
            {"decision": final_decision.value},
        )

        await self._apply_decision(context, final_decision)
        return context

    def _enforce_policy(self, context: WorkflowContext) -> FinalDecision:
        """Apply deterministic policy rules to the AI recommendation.

        The LLM recommends, the policy engine decides.
        """
        rec = context.recommendation
        risk = context.risk_assessment

        if risk and risk.risk_level == RiskLevel.CRITICAL:
            if rec.recommended_action == FinalDecision.APPROVE:
                logger.warning(
                    "Policy override: LLM recommended APPROVE for CRITICAL risk, escalating"
                )
                return FinalDecision.ESCALATE_TO_HUMAN

        if rec.confidence < self.settings.low_confidence_threshold:
            if rec.recommended_action == FinalDecision.APPROVE:
                logger.warning(
                    "Policy override: confidence %.2f below threshold, escalating",
                    rec.confidence,
                )
                return FinalDecision.ESCALATE_TO_HUMAN

        if context.missing_fields:
            return FinalDecision.REQUEST_MORE_INFORMATION

        if context.retry_count >= self.settings.max_tool_retries:
            if rec.recommended_action != FinalDecision.ESCALATE_TO_HUMAN:
                return FinalDecision.ESCALATE_TO_HUMAN

        if rec.recommended_action == FinalDecision.REJECT_OR_BLOCK:
            if risk and risk.risk_level in (RiskLevel.LOW, RiskLevel.MEDIUM):
                logger.warning(
                    "Policy override: Reject blocked for non-critical risk, escalating"
                )
                return FinalDecision.ESCALATE_TO_HUMAN

        return rec.recommended_action

    async def _apply_decision(self, context: WorkflowContext, decision: FinalDecision) -> None:
        """Apply the final decision to the workflow context."""
        if decision == FinalDecision.APPROVE:
            await self._transition(context, WorkflowState.APPROVED)
        elif decision == FinalDecision.REQUEST_MORE_INFORMATION:
            await self._transition(context, WorkflowState.MORE_INFORMATION_REQUIRED)
        elif decision == FinalDecision.ESCALATE_TO_HUMAN:
            await self._transition(context, WorkflowState.ESCALATED)
        elif decision == FinalDecision.REJECT_OR_BLOCK:
            await self._transition(context, WorkflowState.REJECTED)

    async def _transition(self, context: WorkflowContext, new_state: WorkflowState) -> None:
        """Transition to a new state with validation and persistence."""
        if not can_transition(context.current_state, new_state):
            logger.error(
                "Invalid transition: %s -> %s for application %s",
                context.current_state.value,
                new_state.value,
                context.application.application_id,
            )
            raise ValueError(
                f"Invalid state transition: {context.current_state.value} -> {new_state.value}"
            )

        old_state = context.current_state
        context.current_state = new_state
        context.updated_at = datetime.now(timezone.utc)

        try:
            await self.memory.save(context)
        except PersistenceError:
            logger.error(
                "State persistence failed for app=%s at transition %s -> %s",
                context.application.application_id,
                old_state.value,
                new_state.value,
            )
            raise

        await self._record_event(
            context,
            EventType.STATE_TRANSITION,
            "state_transition",
            "SUCCESS",
            {"from_state": old_state.value, "to_state": new_state.value},
        )

    async def _record_event(
        self,
        context: WorkflowContext,
        event_type: EventType,
        action: str,
        result: str,
        metadata: dict | None = None,
    ) -> None:
        """Record an audit event.

        Audit persistence failure is logged but does NOT crash the workflow.
        The business decision was still made; only the trail is incomplete.
        """
        try:
            await self.audit.record(
                application_id=context.application.application_id,
                state=context.current_state,
                event_type=event_type,
                action=action,
                result=result,
                metadata=metadata,
            )
        except AuditPersistenceError as exc:
            logger.warning(
                "Audit persistence failed for app=%s event=%s: %s",
                context.application.application_id,
                event_type.value,
                exc,
            )

    async def get_application_status(self, application_id: str) -> WorkflowContext | None:
        """Get the current status of an application."""
        return await self.memory.get(application_id)

    async def get_application_history(self, application_id: str) -> list:
        """Get audit history for an application."""
        return await self.audit.get_events_for_application(application_id)

    async def list_applications(self) -> list:
        """List all applications."""
        return await self.memory.list_applications()
