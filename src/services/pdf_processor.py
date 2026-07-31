"""Extraction pipeline orchestrator.

Combines native text extraction, table detection, layout analysis, OCR
fallback for scanned pages and AI visual descriptions into one
:class:`ExtractedDocument`. Model calls (OCR, image descriptions) run in
a thread pool; PyMuPDF work and the ``progress`` callback stay on the
calling thread (fitz objects and Streamlit widgets are not thread-safe).
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Callable, Optional

from config.settings import SETTINGS
from src.models import BoundingBox, DocumentElement, ElementType, ExtractedDocument, SourceReference
from src.models.document_element import new_element_id
from src.services import (
    layout_analyzer,
    native_text_extractor,
    ocr_service,
    source_mapper,
    table_extractor,
    visual_content_analyzer,
)

logger = logging.getLogger(__name__)

_RENDER_ZOOM = 2.0  # ~144 dpi, legible for OCR without huge payloads
_MIN_DESCRIBE_SIZE = 40.0  # points; skip tiny decorative images

ProgressFn = Callable[[str, float], None]


@dataclass
class ProcessingOptions:
    """Tunable knobs for one processing run."""

    use_llm_ocr: bool = True
    describe_visuals: bool = True
    max_image_descriptions: int = field(
        default_factory=lambda: SETTINGS.max_image_descriptions
    )
    max_pages: int = field(default_factory=lambda: SETTINGS.pdf_max_pages)
    concurrency: int = field(default_factory=lambda: SETTINGS.llm_concurrency)


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
        scanned_renders: dict[int, tuple[bytes, float, float]] = {}
        page_heights: list[float] = []

        for i in range(limit):
            page = doc.load_page(i)
            page_number = i + 1
            page_heights.append(page.rect.height)
            fraction = 0.05 + 0.40 * (i + 1) / limit

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
                # Scanned page: render now (fitz is main-thread only),
                # OCR later in parallel.
                matrix = fitz.Matrix(_RENDER_ZOOM, _RENDER_ZOOM)
                pix = page.get_pixmap(matrix=matrix)
                scanned_renders[page_number] = (
                    pix.tobytes("png"),
                    page.rect.width,
                    page.rect.height,
                )
            pages_elements[page_number] = elements

        _run_ocr(
            scanned_renders, pages_elements, opts, warnings, report
        )

        report("Detecting layout...", 0.78)
        if page_heights:
            layout_analyzer.detect_furniture(
                pages_elements, max(page_heights), limit
            )

        if opts.describe_visuals:
            _describe_visuals(doc, pages_elements, opts, warnings, report)
        _fill_image_placeholders(pages_elements)

        report("Building source references...", 0.96)
        metadata = {
            "pdf_title": (doc.metadata or {}).get("title", "") or "",
            "pdf_author": (doc.metadata or {}).get("author", "") or "",
            "native_pages": limit - len(scanned_renders),
            "ocr_pages": len(scanned_renders),
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


def _run_ocr(
    scanned_renders: dict,
    pages_elements: dict,
    opts: ProcessingOptions,
    warnings: list,
    report: ProgressFn,
) -> None:
    """OCR scanned pages in parallel; failures become placeholders."""
    if not scanned_renders:
        return
    ocr_available = opts.use_llm_ocr and SETTINGS.databricks_enabled
    if not ocr_available:
        for page_number, (_, width, height) in scanned_renders.items():
            pages_elements[page_number] = [
                _ocr_placeholder(page_number, width, height, "OCR is disabled or the model is not configured")
            ]
        warnings.append(
            f"{len(scanned_renders)} scanned page(s) were not OCRed - "
            "enable OCR and configure Databricks to transcribe them."
        )
        return

    done = 0
    total = len(scanned_renders)
    report(f"Performing OCR (0/{total} pages)...", 0.48)
    with ThreadPoolExecutor(max_workers=max(1, opts.concurrency)) as pool:
        futures = {
            pool.submit(ocr_service.ocr_page, png, page_number, width, height): (
                page_number,
                width,
                height,
            )
            for page_number, (png, width, height) in scanned_renders.items()
        }
        for future in as_completed(futures):
            page_number, width, height = futures[future]
            done += 1
            try:
                pages_elements[page_number] = future.result()
            except Exception as exc:
                logger.warning("OCR failed on page %s: %s", page_number, exc)
                pages_elements[page_number] = [
                    _ocr_placeholder(page_number, width, height, str(exc))
                ]
                warnings.append(
                    f"OCR failed on page {page_number}; the page is marked "
                    "as not extracted."
                )
            report(
                f"Performing OCR ({done}/{total} pages)...",
                0.48 + 0.28 * done / total,
            )


def _ocr_placeholder(
    page_number: int, width: float, height: float, reason: str
) -> DocumentElement:
    element = DocumentElement(
        id=new_element_id(),
        type=ElementType.PARAGRAPH,
        content=(
            f"*[Page {page_number} appears to be scanned and could not be "
            f"transcribed: {reason}.]*"
        ),
        source=SourceReference(
            page=page_number,
            bounding_box=BoundingBox.from_rect(0, 0, width, height),
            extraction_method="llm_ocr",
            confidence=0.0,
        ),
    )
    element.metadata["ocr_failed"] = True
    return element


def _describe_visuals(
    doc,
    pages_elements: dict,
    opts: ProcessingOptions,
    warnings: list,
    report: ProgressFn,
) -> None:
    """Crop image regions and describe them with the vision model."""
    if not SETTINGS.databricks_enabled:
        return
    import fitz

    candidates = []
    for page_number, elements in pages_elements.items():
        for el in elements:
            if el.type != ElementType.IMAGE or el.content:
                continue
            box = el.source.bounding_box if el.source else None
            if not box or box.width < _MIN_DESCRIBE_SIZE or box.height < _MIN_DESCRIBE_SIZE:
                continue
            candidates.append((page_number, el))
    if not candidates:
        return
    skipped = len(candidates) - opts.max_image_descriptions
    if skipped > 0:
        candidates = candidates[: opts.max_image_descriptions]
        warnings.append(
            f"{skipped} image(s) were not described "
            "(MAX_IMAGE_DESCRIPTIONS); they remain as placeholders."
        )

    # Render crops on the calling thread; only model calls go to workers.
    crops: dict[str, bytes] = {}
    matrix = fitz.Matrix(_RENDER_ZOOM, _RENDER_ZOOM)
    for page_number, el in candidates:
        box = el.source.bounding_box
        clip = fitz.Rect(box.x, box.y, box.x1, box.y1)
        try:
            pix = doc.load_page(page_number - 1).get_pixmap(matrix=matrix, clip=clip)
            crops[el.id] = pix.tobytes("png")
        except Exception as exc:
            logger.warning("Could not render image crop on page %s: %s", page_number, exc)

    done = 0
    total = len(crops)
    if not total:
        return
    report(f"Analyzing images and charts (0/{total})...", 0.82)
    elements_by_id = {el.id: el for _, el in candidates}
    with ThreadPoolExecutor(max_workers=max(1, opts.concurrency)) as pool:
        futures = {
            pool.submit(visual_content_analyzer.describe_region, png): el_id
            for el_id, png in crops.items()
        }
        for future in as_completed(futures):
            el_id = futures[future]
            element = elements_by_id[el_id]
            done += 1
            try:
                kind, description = future.result()
                element.type = {
                    "chart": ElementType.CHART,
                    "diagram": ElementType.DIAGRAM,
                }.get(kind, ElementType.IMAGE)
                element.content = description
                if element.source:
                    element.source.extraction_method = "visual_analysis"
            except Exception as exc:
                logger.warning("Visual analysis failed for %s: %s", el_id, exc)
                warnings.append(
                    "An image on page "
                    f"{element.source.page if element.source else '?'} could "
                    "not be described."
                )
            report(
                f"Analyzing images and charts ({done}/{total})...",
                0.82 + 0.13 * done / total,
            )


def _fill_image_placeholders(pages_elements: dict) -> None:
    """Give undescribed images a visible, honest placeholder."""
    for elements in pages_elements.values():
        for el in elements:
            if el.type == ElementType.IMAGE and not el.content:
                el.content = "*[Image - no description generated.]*"
