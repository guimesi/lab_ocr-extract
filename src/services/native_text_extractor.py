"""Native (embedded) text extraction with structure classification.

Works on PyMuPDF's ``page.get_text("dict")`` layout blocks: text blocks
become headings / paragraphs / lists / captions based on font size
relative to the document's body size, boldness and list markers; image
blocks become image placeholders (described later by the visual
analyzer). Every element keeps its bounding box.
"""
from __future__ import annotations

import logging
import re
from collections import Counter

from src.models import BoundingBox, DocumentElement, ElementType, SourceReference
from src.models.document_element import new_element_id
from src.services import layout_analyzer

logger = logging.getLogger(__name__)

_BOLD_FLAG = 16  # PyMuPDF span flag bit for bold

_LIST_MARKER_RE = re.compile(
    r"^\s*(?:[-•▪◦‣·*–—]|\d{1,3}[.)]|[a-zA-Z][.)]|\((?:\d{1,3}|[a-z])\))\s+"
)
_NUMBERED_RE = re.compile(r"^\s*(\d{1,3})[.)]\s+(.*)$")
_CAPTION_RE = re.compile(
    r"^\s*(figure|fig\.|table|chart|graph|diagram|source:|exhibit)\b",
    re.IGNORECASE,
)

# Pages with fewer native characters than this are treated as scanned
# and routed to OCR.
SCANNED_PAGE_CHAR_THRESHOLD = 30


def page_char_count(page) -> int:
    """How much real native text the page carries."""
    return len("".join(page.get_text("text").split()))


def compute_body_font_size(doc) -> float:
    """The document's dominant (body) font size, weighted by text length."""
    counts: Counter = Counter()
    for page in doc:
        for block in page.get_text("dict").get("blocks", []):
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    text = span.get("text", "").strip()
                    if text:
                        counts[round(span.get("size", 0), 1)] += len(text)
    if not counts:
        return 11.0
    return counts.most_common(1)[0][0]


def _rect_center_in(bbox: tuple, rects: list) -> bool:
    cx = (bbox[0] + bbox[2]) / 2
    cy = (bbox[1] + bbox[3]) / 2
    return any(x0 <= cx <= x1 and y0 <= cy <= y1 for x0, y0, x1, y1 in rects)


def _block_lines(block: dict) -> list:
    """Per-line ``(text, max_size, bold_ratio)`` for a text block."""
    lines = []
    for line in block.get("lines", []):
        text = "".join(s.get("text", "") for s in line.get("spans", [])).strip()
        if not text:
            continue
        sizes = [s.get("size", 0) for s in line.get("spans", []) if s.get("text", "").strip()]
        bold_chars = sum(
            len(s.get("text", ""))
            for s in line.get("spans", [])
            if s.get("flags", 0) & _BOLD_FLAG
        )
        total_chars = sum(len(s.get("text", "")) for s in line.get("spans", []))
        lines.append(
            (
                text,
                max(sizes) if sizes else 0.0,
                (bold_chars / total_chars) if total_chars else 0.0,
            )
        )
    return lines


def _join_paragraph(texts: list) -> str:
    """Join wrapped lines into one paragraph, undoing hyphenation."""
    out = ""
    for text in texts:
        if not out:
            out = text
        elif out.endswith("-") and out[-2:-1].isalpha():
            out = out[:-1] + text
        else:
            out += " " + text
    return out


def _list_content(texts: list) -> str:
    """Normalize list lines to Markdown bullets, keeping numbering."""
    items = []
    for text in texts:
        numbered = _NUMBERED_RE.match(text)
        if numbered:
            items.append(f"{numbered.group(1)}. {numbered.group(2).strip()}")
        elif _LIST_MARKER_RE.match(text):
            items.append("- " + _LIST_MARKER_RE.sub("", text).strip())
        else:
            # Continuation of the previous item's wrapped text.
            if items:
                items[-1] += " " + text.strip()
            else:
                items.append("- " + text.strip())
    return "\n".join(items)


def _heading_level(max_size: float, body_size: float) -> int:
    ratio = max_size / body_size if body_size else 1.0
    if ratio >= 1.6:
        return 1
    if ratio >= 1.35:
        return 2
    if ratio >= 1.15:
        return 3
    return 4


def _classify_text_block(
    block: dict, page_number: int, body_size: float
) -> DocumentElement | None:
    lines = _block_lines(block)
    if not lines:
        return None
    texts = [t for t, _, _ in lines]
    full_text = " ".join(texts)
    max_size = max(size for _, size, _ in lines)
    bold_ratio = sum(b for _, _, b in lines) / len(lines)
    bbox = BoundingBox.from_rect(*block["bbox"])
    source = SourceReference(
        page=page_number, bounding_box=bbox, extraction_method="native_text"
    )

    list_lines = sum(1 for t in texts if _LIST_MARKER_RE.match(t))
    if list_lines >= 2 and list_lines >= len(texts) * 0.6:
        return DocumentElement(
            id=new_element_id(),
            type=ElementType.LIST,
            content=_list_content(texts),
            source=source,
        )
    if len(texts) == 1 and _LIST_MARKER_RE.match(texts[0]) and len(full_text) < 300:
        return DocumentElement(
            id=new_element_id(),
            type=ElementType.LIST,
            content=_list_content(texts),
            source=source,
        )
    if _CAPTION_RE.match(full_text) and len(full_text) <= 200:
        return DocumentElement(
            id=new_element_id(),
            type=ElementType.CAPTION,
            content=full_text,
            source=source,
        )
    is_short = len(texts) <= 2 and len(full_text) <= 120
    looks_heading = max_size >= body_size * 1.15 or (
        bold_ratio >= 0.9 and len(full_text) <= 80
    )
    if is_short and looks_heading and not full_text.endswith((".", ";", ",")):
        return DocumentElement(
            id=new_element_id(),
            type=ElementType.HEADING,
            content=full_text,
            level=_heading_level(max_size, body_size),
            source=source,
        )
    return DocumentElement(
        id=new_element_id(),
        type=ElementType.PARAGRAPH,
        content=_join_paragraph(texts),
        source=source,
    )


def _merge_adjacent_lists(elements: list) -> list:
    """Consecutive single-item list blocks become one list element."""
    merged: list = []
    for el in elements:
        prev = merged[-1] if merged else None
        if (
            prev is not None
            and el.type == ElementType.LIST
            and prev.type == ElementType.LIST
            and prev.source
            and el.source
            and prev.source.page == el.source.page
        ):
            prev.content += "\n" + el.content
            if prev.source.bounding_box and el.source.bounding_box:
                a, b = prev.source.bounding_box, el.source.bounding_box
                prev.source.bounding_box = BoundingBox.from_rect(
                    min(a.x, b.x),
                    min(a.y, b.y),
                    max(a.x1, b.x1),
                    max(a.y1, b.y1),
                )
            continue
        merged.append(el)
    return merged


def extract_page(
    page, page_number: int, body_size: float, table_bboxes: list
) -> list:
    """Extract structured elements from one page's native text layer.

    ``table_bboxes`` are rectangles already captured as tables; text
    blocks whose center falls inside one are skipped to avoid
    duplicating table content as paragraphs.
    """
    raw = page.get_text("dict")
    page_width = raw.get("width") or page.rect.width
    blocks = [
        b
        for b in raw.get("blocks", [])
        if not (b.get("type") == 0 and _rect_center_in(b["bbox"], table_bboxes))
    ]
    blocks = layout_analyzer.split_column_blocks(blocks, page_width)
    ordered = layout_analyzer.order_blocks(blocks, page_width)

    elements: list = []
    for block in ordered:
        if block.get("type") == 1:  # image block
            elements.append(
                DocumentElement(
                    id=new_element_id(),
                    type=ElementType.IMAGE,
                    content="",
                    source=SourceReference(
                        page=page_number,
                        bounding_box=BoundingBox.from_rect(*block["bbox"]),
                        extraction_method="native_text",
                    ),
                )
            )
            continue
        element = _classify_text_block(block, page_number, body_size)
        if element is not None:
            elements.append(element)
    return _merge_adjacent_lists(elements)
