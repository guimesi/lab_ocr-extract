"""
Document loading: normalizes an upload (image or PDF) into pages.

The vision API only accepts images, so PDFs are rendered page by page
into PNG via PyMuPDF. Images pass through untouched. Every page becomes
a ``(bytes, mime_type)`` tuple ready for
:func:`src.llm_client.image_content`.
"""
from __future__ import annotations

from config.settings import SETTINGS

# 2.0 => ~144 dpi: legible for OCR without gigantic payloads.
_PDF_RENDER_ZOOM = 2.0


def load_pages(file_bytes: bytes, mime_type: str) -> tuple[list[tuple[bytes, str]], int]:
    """Return ``(pages, total_pages)`` for an uploaded document.

    ``pages`` holds at most ``SETTINGS.pdf_max_pages`` entries (0 means
    no limit); ``total_pages`` is the real page count so callers can
    warn about truncation.
    """
    if mime_type == "application/pdf":
        return _pdf_pages(file_bytes)
    return [(file_bytes, mime_type)], 1


def _pdf_pages(pdf_bytes: bytes) -> tuple[list[tuple[bytes, str]], int]:
    # Lazy import keeps image-only usage working even without pymupdf.
    import fitz  # PyMuPDF

    pages: list[tuple[bytes, str]] = []
    with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
        total = doc.page_count
        limit = total if SETTINGS.pdf_max_pages <= 0 else min(total, SETTINGS.pdf_max_pages)
        matrix = fitz.Matrix(_PDF_RENDER_ZOOM, _PDF_RENDER_ZOOM)
        for i in range(limit):
            pix = doc.load_page(i).get_pixmap(matrix=matrix)
            pages.append((pix.tobytes("png"), "image/png"))
    return pages, total
