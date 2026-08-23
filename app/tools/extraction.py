from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from app.config.settings import get_settings
from app.models.domain import ApplicationDocument, ExtractedDocumentData

logger = logging.getLogger(__name__)

EXTRACTION_PROMPT = """You are a document data extraction system.
Extract structured information from the following document.

Document type: {document_type}
Document content:
{document_content}

Extract the following fields if present:
- name (person or business name)
- pan_number (PAN card number)
- gst_number (GST registration number)
- address
- phone
- email
- date_of_birth
- registration_number

Return ONLY a valid JSON object with these fields. Use null for fields not found.
Example:
{{
  "name": "John Doe",
  "pan_number": "ABCDE1234F",
  "gst_number": null,
  "address": "123 Main St",
  "phone": "9876543210",
  "email": "john@example.com",
  "date_of_birth": "1990-01-15",
  "registration_number": null
}}
"""


async def extract_document_data(
    document: ApplicationDocument,
    file_path: str | None = None,
    application_id: str | None = None,
) -> ExtractedDocumentData:
    """Extract structured data from a document.

    If file_path is provided, uses the document processing pipeline (OCR + field extraction).
    Otherwise falls back to LLM extraction or basic regex extraction.
    """
    settings = get_settings()

    # If file_path provided, use the document processing pipeline
    if file_path and application_id:
        try:
            from app.tools.document_processing import (
                process_document_file,
            )
            from app.tools.field_extraction import FieldExtractionResult

            doc_result = process_document_file(
                file_path=file_path,
                document_type=document.document_type,
                application_id=application_id,
                document_id=document.document_id,
                original_filename=document.metadata.get("original_filename", "unknown"),
                max_pdf_pages=settings.max_pdf_pages,
            )

            if doc_result.processing_status == "failed":
                return ExtractedDocumentData(
                    document_id=document.document_id,
                    document_type=document.document_type,
                    confidence=0.0,
                    extracted_fields={},
                    raw_response=f"Document processing failed: {doc_result.error_message}",
                )

            # Map extracted fields to ExtractedDocumentData format
            extracted_fields = {}
            for field_name, field_data in doc_result.extracted_fields.items():
                if hasattr(field_data, "value"):
                    extracted_fields[field_name] = field_data.value
                elif isinstance(field_data, dict) and "value" in field_data:
                    extracted_fields[field_name] = field_data["value"]
                else:
                    extracted_fields[field_name] = field_data

            return ExtractedDocumentData(
                document_id=document.document_id,
                document_type=document.document_type,
                extracted_fields=extracted_fields,
                confidence=doc_result.overall_confidence,
                extraction_method=doc_result.processing_method,
                raw_response=doc_result.raw_text,
            )
        except Exception as e:
            logger.warning("Document processing pipeline failed, falling back: %s", e)

    # Existing LLM/regex extraction paths
    content = document.raw_text or ""
    if not content:
        return ExtractedDocumentData(
            document_id=document.document_id,
            document_type=document.document_type,
            confidence=0.0,
            extracted_fields={},
            raw_response="No content available for extraction",
        )

    try:
        result = await _llm_extract(settings, document.document_type, content)
        return result
    except Exception as e:
        logger.warning("LLM extraction failed, falling back to basic: %s", e)
        return _basic_extract(document)


async def _llm_extract(
    settings: Any, document_type: str, content: str
) -> ExtractedDocumentData:
    """Use LLM to extract structured data from document content."""
    prompt = EXTRACTION_PROMPT.format(
        document_type=document_type, document_content=content[:3000]
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
                "temperature": 0.1,
                "max_tokens": 1000,
            },
            timeout=30.0,
        )
        response.raise_for_status()

    data = response.json()
    raw_text = data["choices"][0]["message"]["content"]

    extracted = _parse_llm_response(raw_text)
    confidence = _calculate_extraction_confidence(extracted)

    return ExtractedDocumentData(
        document_id="",
        document_type=document_type,
        extracted_fields=extracted,
        confidence=confidence,
        extraction_method="llm",
        raw_response=raw_text,
    )


def _parse_llm_response(raw_text: str) -> dict[str, Any]:
    """Parse LLM response, handling markdown code blocks."""
    text = raw_text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        lines = [line for line in lines if not line.strip().startswith("```")]
        text = "\n".join(lines)

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        logger.warning("Failed to parse LLM response as JSON")
        return {}


def _calculate_extraction_confidence(extracted: dict[str, Any]) -> float:
    """Calculate confidence based on how many fields were extracted."""
    if not extracted:
        return 0.0

    important_fields = ["name", "pan_number", "address", "phone"]
    filled = sum(
        1 for f in important_fields if extracted.get(f) is not None
    )
    return filled / len(important_fields)


def _basic_extract(document: ApplicationDocument) -> ExtractedDocumentData:
    """Basic regex-based extraction as fallback."""
    content = document.raw_text or ""
    extracted: dict[str, Any] = {}

    import re

    pan_match = re.search(r"[A-Z]{5}[0-9]{4}[A-Z]", content.upper())
    if pan_match:
        extracted["pan_number"] = pan_match.group()

    gst_match = re.search(
        r"[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}",
        content.upper(),
    )
    if gst_match:
        extracted["gst_number"] = gst_match.group()

    phone_match = re.search(r"(?<!\d)[6-9]\d{9}(?!\d)", content)
    if phone_match:
        extracted["phone"] = phone_match.group()

    email_match = re.search(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", content)
    if email_match:
        extracted["email"] = email_match.group()

    confidence = len(extracted) / 4 if extracted else 0.0

    return ExtractedDocumentData(
        document_id=document.document_id,
        document_type=document.document_type,
        extracted_fields=extracted,
        confidence=confidence,
        extraction_method="basic_regex",
    )
