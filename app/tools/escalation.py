from __future__ import annotations

import logging
from typing import Any

import httpx

from app.config.settings import get_settings
from app.models.domain import WorkflowContext

logger = logging.getLogger(__name__)


async def create_escalation(
    context: WorkflowContext,
    reason: str,
    additional_info: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create an escalation record and optionally notify via webhook.

    Returns the escalation record.
    """
    settings = get_settings()

    escalation_record = {
        "application_id": context.application.application_id,
        "reason": reason,
        "current_state": context.current_state.value,
        "risk_level": context.risk_assessment.risk_level.value
        if context.risk_assessment
        else None,
        "risk_score": context.risk_assessment.risk_score
        if context.risk_assessment
        else None,
        "risk_factors": context.risk_assessment.risk_factors
        if context.risk_assessment
        else [],
        "recommendation": context.recommendation.model_dump()
        if context.recommendation
        else None,
        "retry_count": context.retry_count,
        "additional_info": additional_info or {},
    }

    if settings.escalation_webhook_url:
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    settings.escalation_webhook_url,
                    json=escalation_record,
                    timeout=10.0,
                )
                response.raise_for_status()
                logger.info(
                    "Escalation webhook sent for application %s",
                    context.application.application_id,
                )
        except Exception as e:
            logger.error("Failed to send escalation webhook: %s", e)

    logger.info(
        "ESCALATION: Application %s - %s",
        context.application.application_id,
        reason,
    )

    return escalation_record
