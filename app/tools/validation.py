from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.config.settings import get_settings
from app.models.domain import OnboardingApplication


@dataclass
class ValidationResult:
    """Result of input validation."""

    is_valid: bool
    missing_fields: list[str] = field(default_factory=list)
    invalid_fields: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def validate_application(application: OnboardingApplication) -> ValidationResult:
    """Validate that an application has all required fields with valid formats.

    This is a deterministic tool - no LLM involved.
    """
    settings = get_settings()
    missing = []
    invalid = []
    errors = []

    for field_name in settings.required_application_fields:
        value = getattr(application, field_name, None)
        if value is None or (isinstance(value, str) and not value.strip()):
            missing.append(field_name)

    if application.pan_number:
        if not re.match(settings.pan_pattern, application.pan_number.upper()):
            invalid.append("pan_number")
            errors.append(f"Invalid PAN format: {application.pan_number}")

    if application.gst_number:
        if not re.match(settings.gst_pattern, application.gst_number.upper()):
            invalid.append("gst_number")
            errors.append(f"Invalid GST format: {application.gst_number}")

    if application.email:
        if "@" not in application.email or "." not in application.email:
            invalid.append("email")
            errors.append(f"Invalid email format: {application.email}")

    is_valid = not missing and not invalid
    return ValidationResult(
        is_valid=is_valid,
        missing_fields=missing,
        invalid_fields=invalid,
        errors=errors,
    )
