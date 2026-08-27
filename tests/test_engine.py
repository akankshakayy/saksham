from unittest.mock import patch

import pytest
import pytest_asyncio

from app.audit.logger import AuditLogger
from app.memory.database import Database
from app.memory.store import WorkflowMemory
from app.models.domain import (
    AIRecommendation,
    ApplicationDocument,
    ExtractedDocumentData,
    OnboardingApplication,
    WorkflowContext,
)
from app.models.states import EventType, FinalDecision, RiskLevel, WorkflowState
from app.worker.engine import WorkerEngine


@pytest_asyncio.fixture
async def db(tmp_path):
    """Create a temporary SQLite database for each test."""
    db_path = str(tmp_path / "test.db")
    database = Database(f"sqlite+aiosqlite:///{db_path}")
    await database.connect()
    yield database
    await database.close()


@pytest_asyncio.fixture
async def engine(db):
    """Create a WorkerEngine with SQLite-backed memory and audit."""
    memory = WorkflowMemory(db=db)
    audit = AuditLogger(db=db)
    return WorkerEngine(memory=memory, audit=audit)


@pytest.mark.asyncio
async def test_complete_valid_application(engine: WorkerEngine):
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


@pytest.mark.asyncio
async def test_missing_fields_triggers_more_info(engine: WorkerEngine):
    app = OnboardingApplication(
        applicant_name=None,
        business_name=None,
        pan_number=None,
        phone=None,
    )

    context = await engine.process_application(app)

    assert context.current_state == WorkflowState.MORE_INFORMATION_REQUIRED
    assert len(context.missing_fields) > 0
    assert context.final_decision == FinalDecision.REQUEST_MORE_INFORMATION


@pytest.mark.asyncio
async def test_invalid_pan_triggers_failure(engine: WorkerEngine):
    app = OnboardingApplication(
        applicant_name="John Doe",
        business_name="Doe Enterprises",
        pan_number="INVALID",
        phone="9876543210",
    )

    context = await engine.process_application(app)

    assert context.current_state in (
        WorkflowState.FAILED,
        WorkflowState.MORE_INFORMATION_REQUIRED,
    )


@pytest.mark.asyncio
async def test_application_with_documents(engine: WorkerEngine):
    app = OnboardingApplication(
        applicant_name="John Doe",
        business_name="Doe Enterprises",
        pan_number="ABCDE1234F",
        phone="9876543210",
        documents=[
            ApplicationDocument(
                document_type="pan_card",
                raw_text="Name: John Doe\nPAN: ABCDE1234F\nDOB: 15/01/1990",
            )
        ],
    )

    context = await engine.process_application(app)

    assert context.current_state in (
        WorkflowState.APPROVED,
        WorkflowState.ESCALATED,
        WorkflowState.ESCALATED_TO_HUMAN,
        WorkflowState.MORE_INFORMATION_REQUIRED,
    )


@pytest.mark.asyncio
async def test_audit_trail_created(engine: WorkerEngine):
    app = OnboardingApplication(
        applicant_name="John Doe",
        business_name="Doe Enterprises",
        pan_number="ABCDE1234F",
        phone="9876543210",
    )

    await engine.process_application(app)

    events = await engine.get_application_history(app.application_id)
    assert len(events) > 0
    assert any(
        e.event_type.value == "INPUT_RECEIVED" for e in events
    )


@pytest.mark.asyncio
async def test_list_applications(engine: WorkerEngine):
    app1 = OnboardingApplication(
        applicant_name="John Doe",
        business_name="Doe Enterprises",
        pan_number="ABCDE1234F",
        phone="9876543210",
    )
    app2 = OnboardingApplication(
        applicant_name="Jane Smith",
        business_name="Smith Corp",
        pan_number="FFFFF1111F",
        phone="1234567890",
    )

    await engine.process_application(app1)
    await engine.process_application(app2)

    apps = await engine.list_applications()
    assert len(apps) == 2


@pytest.mark.asyncio
async def test_llm_cannot_approve_critical_risk(engine: WorkerEngine):
    """Prove the LLM is not the final decision authority.

    Submit an application with PAN, phone, and email that all mismatch the
    extracted document data.  This produces 3 inconsistencies → risk_score
    0.9 → CRITICAL.  Mock the LLM to recommend APPROVE.  The policy engine
    MUST override that recommendation and escalate to human review.
    """
    app = OnboardingApplication(
        applicant_name="Saksham Test",
        business_name="Saksham Test Pvt Ltd",
        pan_number="AABCT1234D",
        phone="6111111111",
        email="wrong@example.com",
        documents=[
            ApplicationDocument(
                document_type="pan_card",
                raw_text="Name: Saksham Test Pvt Ltd\nPAN: ABCDE1234F",
            )
        ],
    )

    extracted_data = ExtractedDocumentData(
        document_id=app.documents[0].document_id,
        document_type="pan_card",
        extracted_fields={
            "pan_number": "ABCDE1234F",
            "phone": "9876543210",
            "email": "test@example.com",
        },
        confidence=0.95,
        extraction_method="ocr",
    )

    mock_recommendation = AIRecommendation(
        recommended_action=FinalDecision.APPROVE,
        confidence=0.9,
        risk_level=RiskLevel.LOW,
        reason="All checks pass",
        evidence=[],
    )

    with (
        patch(
            "app.worker.engine.extract_document_data",
            return_value=extracted_data,
        ),
        patch(
            "app.worker.engine.get_ai_recommendation",
            return_value=mock_recommendation,
        ),
    ):
        context = await engine.process_application(app)

    assert context.risk_assessment is not None
    assert context.risk_assessment.risk_level == RiskLevel.CRITICAL
    assert context.recommendation is not None
    assert context.recommendation.recommended_action == FinalDecision.APPROVE
    assert context.final_decision == FinalDecision.ESCALATE_TO_HUMAN
    assert context.current_state == WorkflowState.ESCALATED

    events = await engine.get_application_history(app.application_id)
    policy_events = [e for e in events if e.event_type == EventType.POLICY_DECISION]
    assert len(policy_events) == 1
    assert policy_events[0].metadata["decision"] == FinalDecision.ESCALATE_TO_HUMAN.value

    rec_events = [e for e in events if e.event_type == EventType.AI_RECOMMENDATION]
    assert len(rec_events) == 1
    assert rec_events[0].metadata["recommended_action"] == FinalDecision.APPROVE.value


@pytest.mark.asyncio
async def test_llm_approve_allowed_for_low_risk(engine: WorkerEngine):
    """Verify the policy engine does not override when risk is LOW.

    Application and document data match → no inconsistencies → LOW risk.
    LLM recommends APPROVE → final decision should be APPROVE (not overridden).
    """
    app = OnboardingApplication(
        applicant_name="John Doe",
        business_name="Doe Enterprises",
        pan_number="ABCDE1234F",
        phone="9876543210",
        email="john@example.com",
        documents=[
            ApplicationDocument(
                document_type="pan_card",
                raw_text="Name: John Doe\nPAN: ABCDE1234F",
            )
        ],
    )

    extracted_data = ExtractedDocumentData(
        document_id=app.documents[0].document_id,
        document_type="pan_card",
        extracted_fields={
            "pan_number": "ABCDE1234F",
            "phone": "9876543210",
            "email": "john@example.com",
        },
        confidence=0.95,
        extraction_method="ocr",
    )

    mock_recommendation = AIRecommendation(
        recommended_action=FinalDecision.APPROVE,
        confidence=0.9,
        risk_level=RiskLevel.LOW,
        reason="All checks pass",
        evidence=[],
    )

    with (
        patch(
            "app.worker.engine.extract_document_data",
            return_value=extracted_data,
        ),
        patch(
            "app.worker.engine.get_ai_recommendation",
            return_value=mock_recommendation,
        ),
    ):
        context = await engine.process_application(app)

    assert context.risk_assessment is not None
    assert context.risk_assessment.risk_level == RiskLevel.LOW
    assert context.recommendation is not None
    assert context.recommendation.recommended_action == FinalDecision.APPROVE
    assert context.final_decision == FinalDecision.APPROVE
    assert context.current_state == WorkflowState.APPROVED


@pytest.mark.asyncio
async def test_rule_based_no_documents_requests_information(engine: WorkerEngine):
    """Rule-based recommendation must not APPROVE when no documents exist.

    Given: extracted_data=[], missing_fields=[], risk_level=MEDIUM
    Expected: REQUEST_MORE_INFORMATION (not APPROVE)
    """
    from app.tools.llm_analysis import _rule_based_recommendation
    from app.models.domain import RiskAssessment

    app = OnboardingApplication(
        applicant_name="John Doe",
        business_name="Doe Enterprises",
        pan_number="ABCDE1234F",
        phone="9876543210",
    )
    context = WorkflowContext(application=app)
    context.risk_assessment = RiskAssessment(
        risk_level=RiskLevel.MEDIUM,
        risk_score=0.45,
        risk_factors=[
            "No document data available for verification",
            "No PAN or GST verification available",
        ],
    )

    rec = _rule_based_recommendation(context)

    assert rec.recommended_action == FinalDecision.REQUEST_MORE_INFORMATION
    assert rec.recommended_action != FinalDecision.APPROVE
    assert rec.risk_level == RiskLevel.MEDIUM


@pytest.mark.asyncio
async def test_no_documents_llm_approve_overridden_by_policy(engine: WorkerEngine):
    """Defense-in-depth: even if LLM recommends APPROVE with no documents,
    the policy engine MUST override to REQUEST_MORE_INFORMATION.

    This is the most critical regression test.
    """
    app = OnboardingApplication(
        applicant_name="John Doe",
        business_name="Doe Enterprises",
        pan_number="ABCDE1234F",
        phone="9876543210",
    )

    mock_recommendation = AIRecommendation(
        recommended_action=FinalDecision.APPROVE,
        confidence=0.95,
        risk_level=RiskLevel.LOW,
        reason="All checks pass",
        evidence=[],
    )

    with patch(
        "app.worker.engine.get_ai_recommendation",
        return_value=mock_recommendation,
    ):
        context = await engine.process_application(app)

    assert context.recommendation is not None
    assert context.recommendation.recommended_action == FinalDecision.APPROVE
    assert context.final_decision == FinalDecision.REQUEST_MORE_INFORMATION
    assert context.current_state == WorkflowState.MORE_INFORMATION_REQUIRED

    events = await engine.get_application_history(app.application_id)
    policy_events = [e for e in events if e.event_type == EventType.POLICY_DECISION]
    assert len(policy_events) == 1
    assert policy_events[0].metadata["decision"] == FinalDecision.REQUEST_MORE_INFORMATION.value


@pytest.mark.asyncio
async def test_no_documents_recommendation_no_fabricated_evidence(engine: WorkerEngine):
    """The rule-based recommendation for no-documents must NOT claim
    'Document data matches' or any equivalent unsupported claim.
    """
    from app.tools.llm_analysis import _rule_based_recommendation
    from app.models.domain import RiskAssessment

    app = OnboardingApplication(
        applicant_name="John Doe",
        business_name="Doe Enterprises",
        pan_number="ABCDE1234F",
        phone="9876543210",
    )
    context = WorkflowContext(application=app)
    context.risk_assessment = RiskAssessment(
        risk_level=RiskLevel.MEDIUM,
        risk_score=0.45,
        risk_factors=[
            "No document data available for verification",
            "No PAN or GST verification available",
        ],
    )

    rec = _rule_based_recommendation(context)

    evidence_text = " ".join(rec.evidence).lower()
    assert "document data matches" not in evidence_text
    assert "all verification checks passed" not in rec.reason.lower()
    assert "document verification" in rec.reason.lower() or "required" in rec.reason.lower()
    assert len(rec.evidence) > 0


@pytest.mark.asyncio
async def test_verified_application_can_still_be_approved(engine: WorkerEngine):
    """Ensure the new rule does not overcorrect: a properly verified
    application with extracted documents should still be APPROVABLE."""
    app = OnboardingApplication(
        applicant_name="John Doe",
        business_name="Doe Enterprises",
        pan_number="ABCDE1234F",
        phone="9876543210",
        email="john@example.com",
        documents=[
            ApplicationDocument(
                document_type="pan_card",
                raw_text="Name: John Doe\nPAN: ABCDE1234F",
            )
        ],
    )

    extracted_data = ExtractedDocumentData(
        document_id=app.documents[0].document_id,
        document_type="pan_card",
        extracted_fields={
            "pan_number": "ABCDE1234F",
            "phone": "9876543210",
            "email": "john@example.com",
        },
        confidence=0.95,
        extraction_method="ocr",
    )

    mock_recommendation = AIRecommendation(
        recommended_action=FinalDecision.APPROVE,
        confidence=0.9,
        risk_level=RiskLevel.LOW,
        reason="All checks pass",
        evidence=[],
    )

    with (
        patch(
            "app.worker.engine.extract_document_data",
            return_value=extracted_data,
        ),
        patch(
            "app.worker.engine.get_ai_recommendation",
            return_value=mock_recommendation,
        ),
    ):
        context = await engine.process_application(app)

    assert len(context.extracted_data) > 0
    assert context.risk_assessment is not None
    assert context.risk_assessment.risk_level == RiskLevel.LOW
    assert context.final_decision == FinalDecision.APPROVE
    assert context.current_state == WorkflowState.APPROVED


@pytest.mark.asyncio
async def test_critical_risk_protection_still_intact(engine: WorkerEngine):
    """Verify that CRITICAL risk + AI APPROVE still produces ESCALATE_TO_HUMAN.

    This is the existing protection — ensure it was not weakened.
    """
    app = OnboardingApplication(
        applicant_name="Saksham Test",
        business_name="Saksham Test Pvt Ltd",
        pan_number="AABCT1234D",
        phone="6111111111",
        email="wrong@example.com",
        documents=[
            ApplicationDocument(
                document_type="pan_card",
                raw_text="Name: Saksham Test Pvt Ltd\nPAN: ABCDE1234F",
            )
        ],
    )

    extracted_data = ExtractedDocumentData(
        document_id=app.documents[0].document_id,
        document_type="pan_card",
        extracted_fields={
            "pan_number": "ABCDE1234F",
            "phone": "9876543210",
            "email": "test@example.com",
        },
        confidence=0.95,
        extraction_method="ocr",
    )

    mock_recommendation = AIRecommendation(
        recommended_action=FinalDecision.APPROVE,
        confidence=0.9,
        risk_level=RiskLevel.LOW,
        reason="All checks pass",
        evidence=[],
    )

    with (
        patch(
            "app.worker.engine.extract_document_data",
            return_value=extracted_data,
        ),
        patch(
            "app.worker.engine.get_ai_recommendation",
            return_value=mock_recommendation,
        ),
    ):
        context = await engine.process_application(app)

    assert context.risk_assessment is not None
    assert context.risk_assessment.risk_level == RiskLevel.CRITICAL
    assert context.recommendation is not None
    assert context.recommendation.recommended_action == FinalDecision.APPROVE
    assert context.final_decision == FinalDecision.ESCALATE_TO_HUMAN
    assert context.current_state == WorkflowState.ESCALATED
