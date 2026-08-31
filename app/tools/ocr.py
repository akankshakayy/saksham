"""OCR service using RapidOCR (open-source, ONNX-based).

RapidOCR is a lightweight OCR engine that works without GPU
and without requiring system-level tesseract installation.

Thread safety: Uses thread-local storage so each thread gets its own
RapidOCR instance. This is necessary because RapidOCR mutates internal
state during __call__ and is not thread-safe as a shared singleton.
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

_thread_local = threading.local()


def _get_engine():
    """Get a thread-local RapidOCR instance for thread safety."""
    if not hasattr(_thread_local, "engine"):
        from rapidocr_onnxruntime import RapidOCR
        _thread_local.engine = RapidOCR()
    return _thread_local.engine


@dataclass
class OCRLine:
    """A single OCR-detected text line with its bounding box and confidence."""
    text: str
    confidence: float
    box: list[list[float]] = field(default_factory=list)


@dataclass
class OCRResult:
    """Result from OCR processing of an image."""
    success: bool
    raw_text: str = ""
    lines: list[OCRLine] = field(default_factory=list)
    average_confidence: float = 0.0
    method: str = "rapidocr"
    error: str | None = None


def run_ocr(image_path: str) -> OCRResult:
    """Run OCR on an image file.

    Args:
        image_path: Path to the image file (JPEG, PNG, etc.)

    Returns:
        OCRResult with extracted text, line details, and confidence.
    """
    try:
        engine = _get_engine()
        result, _ = engine(image_path)

        if result is None or len(result) == 0:
            return OCRResult(
                success=False,
                method="rapidocr",
                error="No text detected in image",
            )

        lines = []
        all_text_parts = []
        confidences = []

        for item in result:
            box, text, confidence = item
            lines.append(OCRLine(
                text=text,
                confidence=confidence,
                box=box if box else [],
            ))
            all_text_parts.append(text)
            confidences.append(confidence)

        raw_text = "\n".join(all_text_parts)
        avg_confidence = sum(confidences) / len(confidences) if confidences else 0.0

        return OCRResult(
            success=True,
            raw_text=raw_text,
            lines=lines,
            average_confidence=avg_confidence,
            method="rapidocr",
        )

    except Exception as e:
        logger.error("OCR failed for %s: %s", image_path, e)
        return OCRResult(
            success=False,
            method="rapidocr",
            error=str(e),
        )
