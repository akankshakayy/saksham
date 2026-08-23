"""Structured field extraction from raw document text.

Uses deterministic pattern matching and label-aware heuristics
to extract structured fields from OCR/raw text output.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


FIELD_NOT_PRESENT = "FIELD_NOT_PRESENT"
FIELD_EXTRACTION_FAILED = "FIELD_EXTRACTION_FAILED"


@dataclass
class ExtractedField:
    """A single extracted field with its status."""
    field_name: str
    value: str | None
    status: str  # "extracted", "not_present", "extraction_failed"
    confidence: float  # 0.0 to 1.0
    source_label: str | None = None  # The label text that was matched


@dataclass
class FieldExtractionResult:
    """Result of structured field extraction."""
    fields: dict[str, ExtractedField] = field(default_factory=dict)
    overall_confidence: float = 0.0
    fields_found: int = 0
    fields_attempted: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for storage."""
        result = {}
        for name, ef in self.fields.items():
            result[name] = {
                "value": ef.value,
                "status": ef.status,
                "confidence": ef.confidence,
                "source_label": ef.source_label,
            }
        return result


def extract_fields(text: str) -> FieldExtractionResult:
    """Extract structured fields from raw text using deterministic heuristics.

    Args:
        text: Raw text from OCR or PDF extraction.

    Returns:
        FieldExtractionResult with all extracted fields.
    """
    if not text or not text.strip():
        return FieldExtractionResult()

    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.strip() for line in normalized.split("\n") if line.strip()]

    extractors = [
        ("pan_number", _extract_pan),
        ("gst_number", _extract_gst),
        ("phone", _extract_phone),
        ("email", _extract_email),
        ("date_of_birth", _extract_dob),
        ("name", _extract_name),
        ("address", _extract_address),
        ("registration_number", _extract_registration),
    ]

    fields = {}
    found_count = 0

    for field_name, extractor in extractors:
        result = extractor(text, lines)
        fields[field_name] = result
        if result.status == "extracted":
            found_count += 1

    attempted = len(extractors)
    confidences = [ef.confidence for ef in fields.values() if ef.status == "extracted"]
    overall = sum(confidences) / len(confidences) if confidences else 0.0

    return FieldExtractionResult(
        fields=fields,
        overall_confidence=overall,
        fields_found=found_count,
        fields_attempted=attempted,
    )


def _extract_pan(text: str, lines: list[str]) -> ExtractedField:
    """Extract PAN number using deterministic pattern matching."""
    pan_pattern = re.compile(r"[A-Z]{5}[0-9]{4}[A-Z]")
    match = pan_pattern.search(text.upper())
    if match:
        return ExtractedField(
            field_name="pan_number",
            value=match.group(),
            status="extracted",
            confidence=0.95,
            source_label="pattern_match",
        )

    label_match = re.search(
        r"(?:PAN|Permanent\s+Account\s+Number)[:\s]*([A-Z0-9]{10})",
        text, re.IGNORECASE,
    )
    if label_match:
        return ExtractedField(
            field_name="pan_number",
            value=label_match.group(1).upper(),
            status="extracted",
            confidence=0.85,
            source_label="label_match",
        )

    return ExtractedField(
        field_name="pan_number",
        value=None,
        status="not_present",
        confidence=0.0,
    )


def _extract_gst(text: str, lines: list[str]) -> ExtractedField:
    """Extract GST number using deterministic pattern matching."""
    gst_pattern = re.compile(
        r"[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]"
    )
    match = gst_pattern.search(text.upper())
    if match:
        return ExtractedField(
            field_name="gst_number",
            value=match.group(),
            status="extracted",
            confidence=0.95,
            source_label="pattern_match",
        )

    label_match = re.search(
        r"(?:GST(?:IN)?|Goods\s+and\s+Services\s+Tax)[:\s]*([A-Z0-9]{15})",
        text, re.IGNORECASE,
    )
    if label_match:
        return ExtractedField(
            field_name="gst_number",
            value=label_match.group(1).upper(),
            status="extracted",
            confidence=0.85,
            source_label="label_match",
        )

    return ExtractedField(
        field_name="gst_number",
        value=None,
        status="not_present",
        confidence=0.0,
    )


def _extract_phone(text: str, lines: list[str]) -> ExtractedField:
    """Extract phone number with normalization."""
    phone_pattern = re.compile(r"(?<!\d)[6-9]\d{9}(?!\d)")
    match = phone_pattern.search(text)
    if match:
        return ExtractedField(
            field_name="phone",
            value=match.group(),
            status="extracted",
            confidence=0.90,
            source_label="pattern_match",
        )

    label_match = re.search(
        r"(?:Phone|Mobile|Contact|Tel)[:\s]*(\d{10})",
        text, re.IGNORECASE,
    )
    if label_match:
        return ExtractedField(
            field_name="phone",
            value=label_match.group(1),
            status="extracted",
            confidence=0.80,
            source_label="label_match",
        )

    return ExtractedField(
        field_name="phone",
        value=None,
        status="not_present",
        confidence=0.0,
    )


def _extract_email(text: str, lines: list[str]) -> ExtractedField:
    """Extract email address."""
    email_pattern = re.compile(
        r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}"
    )
    match = email_pattern.search(text)
    if match:
        return ExtractedField(
            field_name="email",
            value=match.group().lower(),
            status="extracted",
            confidence=0.95,
            source_label="pattern_match",
        )

    return ExtractedField(
        field_name="email",
        value=None,
        status="not_present",
        confidence=0.0,
    )


def _extract_dob(text: str, lines: list[str]) -> ExtractedField:
    """Extract date of birth in common formats."""
    dob_patterns = [
        (r"DOB[:\s]*(\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{4})", "label_dmy"),
        (r"Date\s+of\s+Birth[:\s]*(\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{4})", "label_dmy"),
        (r"Born[:\s]*(\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{4})", "label_dmy"),
        (r"(\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{4})", "bare_date"),
    ]

    for pattern, source in dob_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return ExtractedField(
                field_name="date_of_birth",
                value=match.group(1) if "label" in source else match.group(),
                status="extracted",
                confidence=0.85 if "label" in source else 0.60,
                source_label=source,
            )

    return ExtractedField(
        field_name="date_of_birth",
        value=None,
        status="not_present",
        confidence=0.0,
    )


def _extract_name(text: str, lines: list[str]) -> ExtractedField:
    """Extract name using label-aware, line-bounded heuristics.

    Uses line-aware extraction to prevent cross-line greedy capture.
    Stops at line boundaries and rejects known subsequent field labels.
    """
    name_patterns = [
        r"^Applicant\s+Name[:\s]+(.+)",
        r"^Name\s+of\s+(?:Holder|Applicant|Assessee)[:\s]+(.+)",
        r"^Beneficiary[:\s]+(.+)",
        r"^Holder(?:'?s)?\s+Name[:\s]+(.+)",
        r"^Legal\s+Name\s+of\s+Business[:\s]+(.+)",
        r"^Trade\s+Name[:\s]+(.+)",
        r"^Name\s*:\s*(.+)",
    ]

    for line in lines:
        for pattern in name_patterns:
            match = re.match(pattern, line.strip(), re.IGNORECASE)
            if match:
                value = match.group(1).strip()
                value = re.sub(r"\s+", " ", value)
                if _is_known_label(value):
                    continue
                if len(value) >= 2:
                    return ExtractedField(
                        field_name="name",
                        value=value.title(),
                        status="extracted",
                        confidence=0.85,
                        source_label="label_match",
                    )

    return ExtractedField(
        field_name="name",
        value=None,
        status="not_present",
        confidence=0.0,
    )


def _is_known_label(text: str) -> bool:
    """Check if extracted text is actually a subsequent field label, not a name."""
    text_lower = text.lower().strip()
    known_labels = [
        "date of birth", "dob", "gstin", "gst", "pan", "address",
        "phone", "mobile", "email", "registration", "certificate no",
        "certificate no.", "father", "trade name", "principal place",
    ]
    for label in known_labels:
        if text_lower.startswith(label):
            return True
    return False


def _extract_address(text: str, lines: list[str]) -> ExtractedField:
    """Extract address using multiline label-aware extraction."""
    address_labels = [
        r"(?:Address|Residential\s+Address|Business\s+Address|Present\s+Address)[:\s]*\n?((?:.+\n?){1,5})",
        r"(?:Address|Residential\s+Address|Business\s+Address)[:\s]*(.{10,200})",
    ]

    for pattern in address_labels:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            addr = match.group(1).strip()
            addr = re.sub(r"\n+", ", ", addr)
            addr = re.sub(r"\s+", " ", addr).strip()
            if len(addr) >= 5:
                return ExtractedField(
                    field_name="address",
                    value=addr,
                    status="extracted",
                    confidence=0.70,
                    source_label="label_match",
                )

    return ExtractedField(
        field_name="address",
        value=None,
        status="not_present",
        confidence=0.0,
    )


def _extract_registration(text: str, lines: list[str]) -> ExtractedField:
    """Extract registration number."""
    reg_patterns = [
        r"(?:Registration|Reg(?:istration)?\s*(?:No|Number))[:\s]*([A-Z0-9/\-]{3,30})",
        r"(?:Certificate\s+No|Cert\.?\s*No)[:\s]*([A-Z0-9/\-]{3,30})",
    ]

    for pattern in reg_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return ExtractedField(
                field_name="registration_number",
                value=match.group(1).strip(),
                status="extracted",
                confidence=0.80,
                source_label="label_match",
            )

    return ExtractedField(
        field_name="registration_number",
        value=None,
        status="not_present",
        confidence=0.0,
    )
