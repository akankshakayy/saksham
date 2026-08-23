"""PDF processing: text extraction and scanned-PDF-to-image rendering.

Supports two paths:
1. Text-based PDFs: extract text directly via PyMuPDF
2. Scanned PDFs: render pages to images, then OCR
"""
from __future__ import annotations

import logging
import os
import tempfile
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

MIN_TEXT_LENGTH = 50


@dataclass
class PDFExtractionResult:
    """Result from PDF processing."""
    success: bool
    raw_text: str = ""
    method: str = ""
    page_count: int = 0
    rendered_images: list[str] = field(default_factory=list)
    error: str | None = None
    is_scanned: bool = False


def extract_text_from_pdf(pdf_path: str) -> PDFExtractionResult:
    """Attempt direct text extraction from a PDF.

    Returns extracted text if the PDF is text-based.
    Returns empty text if the PDF appears to be scanned.
    """
    try:
        import pymupdf as fitz
        doc = fitz.open(pdf_path)
        page_count = len(doc)

        all_text = []
        for page in doc:
            text = page.get_text()
            all_text.append(text)

        doc.close()

        combined_text = "\n".join(all_text).strip()

        if len(combined_text) >= MIN_TEXT_LENGTH:
            return PDFExtractionResult(
                success=True,
                raw_text=combined_text,
                method="pymupdf_text_extraction",
                page_count=page_count,
                is_scanned=False,
            )

        return PDFExtractionResult(
            success=True,
            raw_text="",
            method="pymupdf_text_extraction",
            page_count=page_count,
            is_scanned=True,
        )

    except Exception as e:
        logger.error("PDF text extraction failed for %s: %s", pdf_path, e)
        return PDFExtractionResult(
            success=False,
            method="pymupdf_text_extraction",
            error=str(e),
        )


def render_pdf_pages(
    pdf_path: str,
    max_pages: int = 5,
    dpi: int = 300,
) -> PDFExtractionResult:
    """Render PDF pages to images for OCR processing.

    Args:
        pdf_path: Path to the PDF file.
        max_pages: Maximum number of pages to render.
        dpi: Resolution for rendering.

    Returns:
        PDFExtractionResult with rendered image paths.
    """
    try:
        import pymupdf as fitz
        doc = fitz.open(pdf_path)
        page_count = min(len(doc), max_pages)
        rendered_images = []

        temp_dir = tempfile.mkdtemp(prefix="saksham_pdf_")

        for i in range(page_count):
            page = doc[i]
            mat = fitz.Matrix(dpi / 72, dpi / 72)
            pix = page.get_pixmap(matrix=mat)

            image_path = os.path.join(temp_dir, f"page_{i + 1}.png")
            pix.save(image_path)
            rendered_images.append(image_path)

        doc.close()

        return PDFExtractionResult(
            success=True,
            method="pymupdf_render",
            page_count=page_count,
            rendered_images=rendered_images,
            is_scanned=True,
        )

    except Exception as e:
        logger.error("PDF rendering failed for %s: %s", pdf_path, e)
        return PDFExtractionResult(
            success=False,
            method="pymupdf_render",
            error=str(e),
        )
