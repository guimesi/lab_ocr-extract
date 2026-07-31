"""OCR for scanned pages via the vision model (Claude via Databricks).

A scanned page (no usable native text) is rendered to PNG and sent to
the model, which returns the page's elements as JSON with normalized
bounding boxes (percentages of the page size). Those are converted back
to PDF points so highlighting works exactly like native elements.
"""
from __future__ import annotations

import logging

from src import llm_client
from src.models import BoundingBox, DocumentElement, ElementType, SourceReference
from src.models.document_element import new_element_id
from src.services import llm_support

logger = logging.getLogger(__name__)


class OcrError(Exception):
    """OCR failed for a page; message is safe to display."""


OCR_SYSTEM_PROMPT = (
    "You are an OCR engine for scanned document pages. You receive one "
    "page as an image and must transcribe its content faithfully and "
    "completely, preserving the logical reading order (for multi-column "
    "pages: left column first, then right). Never invent content: mark "
    "unreadable fragments as [illegible] and lower the confidence score. "
    "Transcribe text in its original language."
)

_OCR_INSTRUCTIONS = (
    "Transcribe this scanned page (page {page}) into structured elements.\n\n"
    "Answer ONLY with a JSON array. Each item is one element in reading "
    "order:\n"
    '{{"type": "<one of: title, heading, paragraph, list, table, image, '
    'chart, diagram, caption, header, footer, page_number>",\n'
    ' "content": "<the transcribed text as Markdown - tables as GitHub '
    'Markdown tables, lists as - bullets; for image/chart/diagram, a '
    'concise factual description>",\n'
    ' "level": <heading level 1-6, only for heading/title>,\n'
    ' "bbox": [x0, y0, x1, y1],\n'
    ' "confidence": <0.0-1.0, your transcription confidence>}}\n\n'
    "bbox values are PERCENTAGES (0-100) of the page width/height, with "
    "the origin at the top-left corner. Include every piece of visible "
    "content exactly once (headers, footers and page numbers as their "
    "own elements with the matching type). Use [illegible] for fragments "
    "you cannot read; never guess. Do not include any text outside the "
    "JSON array."
)

_VALID_TYPES = set(ElementType.ALL)


def ocr_page(
    png_bytes: bytes, page_number: int, page_width: float, page_height: float
) -> list:
    """OCR one rendered page; return its DocumentElements.

    Raises :class:`OcrError` when the model fails or returns
    unparseable output (after the shared retry policy).
    """
    message = {
        "role": "user",
        "content": [
            {"type": "text", "text": _OCR_INSTRUCTIONS.format(page=page_number)},
            llm_client.image_content(png_bytes, "image/png"),
        ],
    }
    try:
        text, truncated = llm_support.complete_with_retry(
            [message], system=OCR_SYSTEM_PROMPT
        )
    except Exception as exc:
        raise OcrError(f"OCR call failed for page {page_number}: {exc}") from exc
    try:
        payload = llm_support.parse_json_payload(text)
    except ValueError as exc:
        raise OcrError(
            f"OCR output for page {page_number} was not valid JSON: {exc}"
        ) from exc
    if not isinstance(payload, list):
        raise OcrError(f"OCR output for page {page_number} is not a JSON array.")

    elements: list = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        content = str(item.get("content", "")).strip()
        if not content:
            continue
        el_type = str(item.get("type", "paragraph")).strip().lower()
        if el_type not in _VALID_TYPES:
            el_type = ElementType.PARAGRAPH
        bbox = _bbox_from_percentages(item.get("bbox"), page_width, page_height)
        confidence = item.get("confidence")
        try:
            confidence = None if confidence is None else min(1.0, max(0.0, float(confidence)))
        except (TypeError, ValueError):
            confidence = None
        level = item.get("level")
        elements.append(
            DocumentElement(
                id=new_element_id(),
                type=el_type,
                content=content,
                level=int(level) if isinstance(level, (int, float)) else None,
                source=SourceReference(
                    page=page_number,
                    bounding_box=bbox,
                    extraction_method="llm_ocr",
                    confidence=confidence,
                ),
            )
        )
    if truncated and elements:
        elements[-1].metadata["truncated"] = True
    return elements


def _bbox_from_percentages(
    raw, page_width: float, page_height: float
) -> BoundingBox | None:
    if not isinstance(raw, (list, tuple)) or len(raw) != 4:
        return None
    try:
        x0, y0, x1, y1 = (float(v) for v in raw)
    except (TypeError, ValueError):
        return None
    # Clamp to the page; ignore degenerate boxes.
    x0, x1 = sorted((max(0.0, min(100.0, x0)), max(0.0, min(100.0, x1))))
    y0, y1 = sorted((max(0.0, min(100.0, y0)), max(0.0, min(100.0, y1))))
    if x1 - x0 < 0.1 or y1 - y0 < 0.1:
        return None
    return BoundingBox.from_rect(
        x0 / 100.0 * page_width,
        y0 / 100.0 * page_height,
        x1 / 100.0 * page_width,
        y1 / 100.0 * page_height,
    )
