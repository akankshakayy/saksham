from __future__ import annotations

import logging
from typing import Any

from app.models.domain import (
    ComparisonResult,
    ExtractedDocumentData,
    FieldComparison,
    OnboardingApplication,
)

logger = logging.getLogger(__name__)

# Fields to compare between application and extracted document data
COMPARABLE_FIELDS = {
    "pan_number": "pan_number",
    "gst_number": "gst_number",
    "phone": "phone",
    "email": "email",
    "address": "address",
}


def compare_information(
    application: OnboardingApplication,
    extracted_data: list[ExtractedDocumentData],
) -> ComparisonResult:
    """Compare application information with extracted document data.

    This is a deterministic comparison tool.
    """
    if not extracted_data:
        return ComparisonResult(
            field_comparisons={},
            overall_match=True,
            inconsistencies=[],
        )

    comparisons: dict[str, FieldComparison] = {}
    inconsistencies: list[str] = []

    app_fields: dict[str, Any] = {}
    for field_name in COMPARABLE_FIELDS:
        value = getattr(application, field_name, None)
        if value is not None:
            app_fields[field_name] = str(value).strip().upper()

    doc_fields: dict[str, Any] = {}
    for ext in extracted_data:
        for ext_key, app_key in COMPARABLE_FIELDS.items():
            ext_value = ext.extracted_fields.get(ext_key)
            if ext_value is not None:
                normalized = str(ext_value).strip().upper()
                if app_key not in doc_fields:
                    doc_fields[app_key] = normalized

    for field_name, app_key in COMPARABLE_FIELDS.items():
        app_val = app_fields.get(field_name)
        doc_val = doc_fields.get(app_key)

        if app_val is None and doc_val is None:
            continue

        if app_val is None:
            comparison = FieldComparison(
                field_name=field_name,
                application_value=None,
                document_value=doc_val,
                match=False,
                confidence=0.8,
                discrepancy_reason="Field missing from application",
            )
            comparisons[field_name] = comparison
            inconsistencies.append(f"{field_name}: missing from application")
            continue

        if doc_val is None:
            comparison = FieldComparison(
                field_name=field_name,
                application_value=app_val,
                document_value=None,
                match=False,
                confidence=0.7,
                discrepancy_reason="Field not found in document",
            )
            comparisons[field_name] = comparison
            inconsistencies.append(f"{field_name}: not found in document")
            continue

        match = app_val == doc_val
        confidence = 1.0 if match else 0.5

        comparison = FieldComparison(
            field_name=field_name,
            application_value=app_val,
            document_value=doc_val,
            match=match,
            confidence=confidence,
            discrepancy_reason=None if match else f"Mismatch: '{app_val}' vs '{doc_val}'",
        )
        comparisons[field_name] = comparison

        if not match:
            inconsistencies.append(f"{field_name}: mismatch '{app_val}' vs '{doc_val}'")

    overall_match = len(inconsistencies) == 0

    return ComparisonResult(
        field_comparisons=comparisons,
        overall_match=overall_match,
        inconsistencies=inconsistencies,
    )
