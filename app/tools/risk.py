from __future__ import annotations

import logging
from typing import Any

from app.models.domain import (
    ComparisonResult,
    ExtractedDocumentData,
    RiskAssessment,
)
from app.models.states import RiskLevel

logger = logging.getLogger(__name__)


def assess_risk(
    comparison_result: ComparisonResult | None,
    extracted_data: list[ExtractedDocumentData],
    application_metadata: dict[str, Any] | None = None,
) -> RiskAssessment:
    """Assess risk based on verification results.

    This is a deterministic risk scoring tool.
    """
    risk_score = 0.0
    risk_factors: list[str] = []
    mitigation: list[str] = []

    if comparison_result:
        inconsistency_count = len(comparison_result.inconsistencies)
        if inconsistency_count > 0:
            risk_score += 0.3 * min(inconsistency_count, 3)
            risk_factors.append(
                f"{inconsistency_count} data inconsistencies found "
                "between application and documents"
            )
            mitigation.append("Request clarification for mismatched fields")

    for ext in extracted_data:
        if ext.confidence < 0.5:
            risk_score += 0.25
            risk_factors.append(
                f"Low extraction confidence ({ext.confidence:.2f}) for {ext.document_type}"
            )
            mitigation.append("Request higher quality document or manual review")

    if not extracted_data:
        risk_score += 0.3
        risk_factors.append("No document data available for verification")
        mitigation.append("Request document submission")

    has_pan = any(
        ext.extracted_fields.get("pan_number") for ext in extracted_data
    )
    has_gst = any(
        ext.extracted_fields.get("gst_number") for ext in extracted_data
    )

    if not has_pan and not has_gst:
        risk_score += 0.15
        risk_factors.append("No PAN or GST verification available")
        mitigation.append("Request PAN or GST document")

    risk_score = min(risk_score, 1.0)

    if risk_score >= 0.8:
        risk_level = RiskLevel.CRITICAL
    elif risk_score >= 0.6:
        risk_level = RiskLevel.HIGH
    elif risk_score >= 0.3:
        risk_level = RiskLevel.MEDIUM
    else:
        risk_level = RiskLevel.LOW

    return RiskAssessment(
        risk_level=risk_level,
        risk_score=risk_score,
        risk_factors=risk_factors,
        mitigation_suggestions=mitigation,
    )
