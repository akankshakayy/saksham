
from app.models.domain import (
    ComparisonResult,
    ExtractedDocumentData,
)
from app.models.states import RiskLevel
from app.tools.risk import assess_risk


def test_low_risk_perfect_data():
    comparison = ComparisonResult(
        field_comparisons={},
        overall_match=True,
        inconsistencies=[],
    )
    extracted = [
        ExtractedDocumentData(
            document_id="doc1",
            document_type="pan_card",
            extracted_fields={"pan_number": "ABCDE1234F"},
            confidence=0.95,
        )
    ]

    result = assess_risk(comparison, extracted)
    assert result.risk_level == RiskLevel.LOW
    assert result.risk_score < 0.3


def test_medium_risk_inconsistencies():
    comparison = ComparisonResult(
        field_comparisons={},
        overall_match=False,
        inconsistencies=["pan_number: mismatch", "phone: mismatch"],
    )
    extracted = [
        ExtractedDocumentData(
            document_id="doc1",
            document_type="pan_card",
            extracted_fields={"pan_number": "ABCDE1234F"},
            confidence=0.9,
        )
    ]

    result = assess_risk(comparison, extracted)
    assert result.risk_level in (RiskLevel.MEDIUM, RiskLevel.HIGH)
    assert len(result.risk_factors) > 0


def test_high_risk_low_confidence():
    comparison = ComparisonResult(
        field_comparisons={},
        overall_match=False,
        inconsistencies=["pan_number: mismatch"] * 4,
    )
    extracted = [
        ExtractedDocumentData(
            document_id="doc1",
            document_type="pan_card",
            extracted_fields={},
            confidence=0.3,
        )
    ]

    result = assess_risk(comparison, extracted)
    assert result.risk_level in (RiskLevel.HIGH, RiskLevel.CRITICAL)
    assert result.risk_score >= 0.6


def test_no_documents():
    result = assess_risk(None, [])
    assert result.risk_level in (RiskLevel.MEDIUM, RiskLevel.HIGH)
    assert any("No document" in f for f in result.risk_factors)


def test_mitigation_suggestions():
    comparison = ComparisonResult(
        field_comparisons={},
        overall_match=False,
        inconsistencies=["pan_number: mismatch"],
    )
    extracted = [
        ExtractedDocumentData(
            document_id="doc1",
            document_type="pan_card",
            extracted_fields={},
            confidence=0.4,
        )
    ]

    result = assess_risk(comparison, extracted)
    assert len(result.mitigation_suggestions) > 0
