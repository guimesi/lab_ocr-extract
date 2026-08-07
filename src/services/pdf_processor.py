"""Extraction pipeline orchestrator.

Combines native text extraction, table detection and layout analysis
into one :class:`ExtractedDocument`. Everything runs on the calling
thread with plain PyMuPDF — no model calls are involved. Pages without
native text (scans) are marked with an honest placeholder element.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Callable, Optional

from config.settings import SETTINGS
from src.models import BoundingBox, DocumentElement, ElementType, ExtractedDocument, SourceReference
from src.models.document_element import new_element_id
from src.services import (
    layout_analyzer,
    native_text_extractor,
    source_mapper,
    table_extractor,
)

logger = logging.getLogger(__name__)

ProgressFn = Callable[[str, float], None]


@dataclass
class ProcessingOptions:
    """Tunable knobs for one processing run."""

    max_pages: int = field(default_factory=lambda: SETTINGS.pdf_max_pages)


class ProcessingError(Exception):
    """The pipeline failed fatally; message is safe to display."""


def process_pdf(
    file_bytes: bytes,
    file_name: str,
    options: Optional[ProcessingOptions] = None,
    progress: Optional[ProgressFn] = None,
) -> ExtractedDocument:
    """Run the full extraction pipeline on one PDF."""
    import fitz  # PyMuPDF

    opts = options or ProcessingOptions()
    warnings: list[str] = []

    def report(label: str, fraction: float) -> None:
        if progress:
            progress(label, max(0.0, min(1.0, fraction)))

    report("Reading PDF...", 0.02)
    try:
        doc = fitz.open(stream=file_bytes, filetype="pdf")
    except Exception as exc:
        raise ProcessingError(f"Could not open the PDF: {exc}") from exc

    try:
        total_pages = doc.page_count
        limit = (
            total_pages
            if opts.max_pages <= 0
            else min(total_pages, opts.max_pages)
        )
        if limit < total_pages:
            warnings.append(
                f"The PDF has {total_pages} pages; only the first {limit} "
                "were processed (PDF_MAX_PAGES)."
            )

        report("Extracting native text...", 0.05)
        body_size = native_text_extractor.compute_body_font_size(doc)

        pages_elements: dict[int, list] = {}
        scanned_pages: list[int] = []
        page_heights: list[float] = []

        for i in range(limit):
            page = doc.load_page(i)
            page_number = i + 1
            page_heights.append(page.rect.height)
            fraction = 0.05 + 0.75 * (i + 1) / limit

            table_bboxes: list = []
            elements: list = []
            if native_text_extractor.page_char_count(page) >= (
                native_text_extractor.SCANNED_PAGE_CHAR_THRESHOLD
            ):
                report(f"Processing tables (page {page_number})...", fraction)
                try:
                    table_elements, table_bboxes = table_extractor.extract_tables(
                        page, page_number
                    )
                    elements.extend(table_elements)
                except Exception as exc:
                    warnings.append(
                        f"Table detection failed on page {page_number} ({exc}); "
                        "tables on this page may appear as plain text."
                    )
                report(
                    f"Extracting native text (page {page_number}/{limit})...",
                    fraction,
                )
                elements.extend(
                    native_text_extractor.extract_page(
                        page, page_number, body_size, table_bboxes
                    )
                )
            else:
                # Scanned page: no native text to extract and no OCR in
                # this app - mark it honestly instead of dropping it.
                scanned_pages.append(page_number)
                elements.append(
                    _scanned_placeholder(
                        page_number, page.rect.width, page.rect.height
                    )
                )
            pages_elements[page_number] = elements

        if scanned_pages:
            warnings.append(
                f"{len(scanned_pages)} page(s) contain no extractable text "
                "(likely scanned images) and were marked as not extracted: "
                f"page(s) {', '.join(str(p) for p in scanned_pages)}."
            )

        report("Detecting layout...", 0.85)
        if page_heights:
            layout_analyzer.detect_furniture(
                pages_elements, max(page_heights), limit
            )

        _fill_image_placeholders(pages_elements)

        report("Building source references...", 0.96)
        metadata = {
            "pdf_title": (doc.metadata or {}).get("title", "") or "",
            "pdf_author": (doc.metadata or {}).get("author", "") or "",
            "native_pages": limit - len(scanned_pages),
            "scanned_pages": len(scanned_pages),
        }
        document = source_mapper.finalize(
            file_name=file_name,
            page_count=total_pages,
            pages_elements=pages_elements,
            warnings=warnings,
            metadata=metadata,
        )
        report("Generating the final structured document...", 1.0)
        return document
    finally:
        doc.close()


def _scanned_placeholder(
    page_number: int, width: float, height: float
) -> DocumentElement:
    element = DocumentElement(
        id=new_element_id(),
        type=ElementType.PARAGRAPH,
        content=(
            f"*[Page {page_number} appears to be scanned and contains no "
            "extractable text.]*"
        ),
        source=SourceReference(
            page=page_number,
            bounding_box=BoundingBox.from_rect(0, 0, width, height),
            extraction_method="scanned_page",
            confidence=0.0,
        ),
    )
    element.metadata["scanned_page"] = True
    return element


def _fill_image_placeholders(pages_elements: dict) -> None:
    """Give images without content a visible, honest placeholder."""
    for elements in pages_elements.values():
        for el in elements:
            if el.type == ElementType.IMAGE and not el.content:
                el.content = "*[Image - content not extracted.]*"
