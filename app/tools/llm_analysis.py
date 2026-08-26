from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from app.config.settings import get_settings
from app.models.domain import AIRecommendation, WorkflowContext
from app.models.states import FinalDecision, RiskLevel

logger = logging.getLogger(__name__)

RECOMMENDATION_PROMPT = """You are an AI verification assistant for partner/merchant onboarding.

Analyze the following verification context and recommend the appropriate action.

Application ID: {application_id}
Current State: {current_state}
Missing Fields: {missing_fields}
Retry Count: {retry_count}

Verification Results:
{verification_summary}

Risk Assessment:
{risk_summary}

You MUST respond with ONLY a valid JSON object in this exact format:
{{
  "recommended_action": "APPROVE" | "REQUEST_MORE_INFORMATION" |
                        "ESCALATE_TO_HUMAN" | "REJECT_OR_BLOCK",
  "confidence": 0.0 to 1.0,
  "risk_level": "LOW" | "MEDIUM" | "HIGH" | "CRITICAL",
  "reason": "Brief explanation of the recommendation",
  "evidence": ["list", "of", "evidence", "items"]
}}

Rules:
- Use REJECT_OR_BLOCK ONLY for clearly invalid data (bad PAN format, known fraud patterns)
- Use ESCALATE_TO_HUMAN when confidence is below 0.7 or risk is HIGH/CRITICAL
- Use REQUEST_MORE_INFORMATION when required fields are missing or documents are unclear
- Use APPROVE only when all checks pass with high confidence
"""


async def get_ai_recommendation(context: WorkflowContext) -> AIRecommendation:
    """Get an AI recommendation for the workflow decision.

    Falls back to rule-based recommendation if LLM is unavailable.
    """
    settings = get_settings()

    if not settings.llm_api_key:
        logger.warning("No LLM API key configured, using rule-based recommendation")
        rec = _rule_based_recommendation(context)
        rec.source = "rule_based_fallback"
        return rec

    try:
        return await _llm_recommendation(settings, context)
    except Exception as e:
        logger.warning("LLM recommendation failed, falling back to rule-based: %s", e)
        rec = _rule_based_recommendation(context)
        rec.source = "rule_based_fallback"
        return rec


async def _llm_recommendation(
    settings: Any, context: WorkflowContext
) -> AIRecommendation:
    """Use LLM to generate a recommendation."""
    verification_summary = _build_verification_summary(context)
    risk_summary = _build_risk_summary(context)

    prompt = RECOMMENDATION_PROMPT.format(
        application_id=context.application.application_id,
        current_state=context.current_state.value,
        missing_fields=context.missing_fields,
        retry_count=context.retry_count,
        verification_summary=verification_summary,
        risk_summary=risk_summary,
    )

    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{settings.llm_base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {settings.llm_api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": settings.llm_model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.2,
                "max_tokens": 800,
            },
            timeout=30.0,
        )
        response.raise_for_status()

    data = response.json()
    raw_text = data["choices"][0]["message"]["content"]

    rec = _parse_recommendation(raw_text)
    rec.source = "openrouter"
    rec.model = settings.llm_model
    return rec


def _parse_recommendation(raw_text: str) -> AIRecommendation:
    """Parse LLM response into structured recommendation."""
    text = raw_text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        lines = [line for line in lines if not line.strip().startswith("```")]
        text = "\n".join(lines)

    try:
        data = json.loads(text)
        return AIRecommendation(
            recommended_action=FinalDecision(data["recommended_action"]),
            confidence=float(data["confidence"]),
            risk_level=RiskLevel(data["risk_level"]),
            reason=data["reason"],
            evidence=data.get("evidence", []),
        )
    except (json.JSONDecodeError, KeyError, ValueError) as e:
        logger.warning("Failed to parse LLM recommendation: %s", e)
        return AIRecommendation(
            recommended_action=FinalDecision.ESCALATE_TO_HUMAN,
            confidence=0.3,
            risk_level=RiskLevel.HIGH,
            reason=f"Failed to parse AI recommendation: {e}",
            evidence=["LLM output parsing failed"],
        )


def _rule_based_recommendation(context: WorkflowContext) -> AIRecommendation:
    """Deterministic rule-based recommendation as fallback."""
    if context.missing_fields:
        return AIRecommendation(
            recommended_action=FinalDecision.REQUEST_MORE_INFORMATION,
            confidence=0.9,
            risk_level=RiskLevel.LOW,
            reason=f"Missing required fields: {', '.join(context.missing_fields)}",
            evidence=[f"Missing: {f}" for f in context.missing_fields],
        )

    if context.risk_assessment:
        if context.risk_assessment.risk_level in (RiskLevel.CRITICAL, RiskLevel.HIGH):
            return AIRecommendation(
                recommended_action=FinalDecision.ESCALATE_TO_HUMAN,
                confidence=0.85,
                risk_level=context.risk_assessment.risk_level,
                reason=f"High risk detected: {'; '.join(context.risk_assessment.risk_factors[:2])}",
                evidence=context.risk_assessment.risk_factors,
            )

    if context.comparison_result and not context.comparison_result.overall_match:
        inconsistency_count = len(context.comparison_result.inconsistencies)
        if inconsistency_count >= 3:
            return AIRecommendation(
                recommended_action=FinalDecision.ESCALATE_TO_HUMAN,
                confidence=0.7,
                risk_level=RiskLevel.MEDIUM,
                reason=f"Multiple data inconsistencies: {inconsistency_count} mismatches",
                evidence=context.comparison_result.inconsistencies,
            )
        return AIRecommendation(
            recommended_action=FinalDecision.REQUEST_MORE_INFORMATION,
            confidence=0.75,
            risk_level=RiskLevel.MEDIUM,
            reason=f"Data inconsistencies found: {inconsistency_count} mismatches",
            evidence=context.comparison_result.inconsistencies,
        )

    low_confidence_extractions = [
        ext for ext in context.extracted_data if ext.confidence < 0.6
    ]
    if low_confidence_extractions:
        return AIRecommendation(
            recommended_action=FinalDecision.ESCALATE_TO_HUMAN,
            confidence=0.65,
            risk_level=RiskLevel.MEDIUM,
            reason="Document extraction confidence below threshold",
            evidence=[
                f"{ext.document_type}: confidence {ext.confidence:.2f}"
                for ext in low_confidence_extractions
            ],
        )

    return AIRecommendation(
        recommended_action=FinalDecision.APPROVE,
        confidence=0.8,
        risk_level=RiskLevel.LOW,
        reason="All verification checks passed",
        evidence=["Application data validated", "Document data matches", "Risk level acceptable"],
    )


def _build_verification_summary(context: WorkflowContext) -> str:
    lines = []
    if context.comparison_result:
        lines.append(
            f"Overall match: {context.comparison_result.overall_match}"
        )
        lines.append(
            f"Inconsistencies: {len(context.comparison_result.inconsistencies)}"
        )
        for inc in context.comparison_result.inconsistencies[:5]:
            lines.append(f"  - {inc}")
    else:
        lines.append("No comparison results available")

    for ext in context.extracted_data:
        lines.append(
            f"Document {ext.document_type}: confidence={ext.confidence:.2f}, "
            f"method={ext.extraction_method}"
        )

    return "\n".join(lines) if lines else "No verification data"


def _build_risk_summary(context: WorkflowContext) -> str:
    if not context.risk_assessment:
        return "No risk assessment available"

    ra = context.risk_assessment
    lines = [
        f"Risk Level: {ra.risk_level.value}",
        f"Risk Score: {ra.risk_score:.2f}",
    ]
    for factor in ra.risk_factors:
        lines.append(f"  - {factor}")
    return "\n".join(lines)
