"""Layout analysis: multi-column reading order and page furniture.

Two responsibilities:

* :func:`order_blocks` - restore the logical reading order of text
  blocks on a page, including simple two-column layouts (left column
  top-to-bottom, then right column, with full-width blocks acting as
  band separators).
* :func:`detect_furniture` - find repeated headers/footers and page
  numbers across pages so they can be excluded from the content flow.
"""
from __future__ import annotations

import re
from collections import Counter

from src.models import DocumentElement, ElementType

_COLUMN_TOLERANCE = 10.0  # points around the page midline

_PAGE_NUMBER_RE = re.compile(
    r"^\s*(page|p[aá]gina|p\.?)?\s*\d{1,4}\s*((of|de|/)\s*\d{1,4})?\s*$",
    re.IGNORECASE,
)


def split_column_blocks(blocks: list, page_width: float) -> list:
    """Split text blocks that straddle two columns into per-column blocks.

    PyMuPDF sometimes merges side-by-side lines of a two-column page
    into one wide block; that would defeat column ordering, so blocks
    whose *lines* cluster left and right of the midline are split into
    one pseudo-block per cluster (bbox recomputed from the lines).
    """
    mid = page_width / 2.0
    out: list = []
    for block in blocks:
        lines = block.get("lines")
        if block.get("type") != 0 or not lines:
            out.append(block)
            continue
        left_lines, right_lines, span_lines = [], [], []
        for line in lines:
            x0, _, x1, _ = line["bbox"]
            if x0 < mid - _COLUMN_TOLERANCE and x1 > mid + _COLUMN_TOLERANCE:
                span_lines.append(line)
            elif x1 <= mid + _COLUMN_TOLERANCE:
                left_lines.append(line)
            else:
                right_lines.append(line)
        if left_lines and right_lines:
            for group in (span_lines, left_lines, right_lines):
                if group:
                    out.append(_block_from_lines(block, group))
        else:
            out.append(block)
    return out


def _block_from_lines(block: dict, lines: list) -> dict:
    bbox = (
        min(l["bbox"][0] for l in lines),
        min(l["bbox"][1] for l in lines),
        max(l["bbox"][2] for l in lines),
        max(l["bbox"][3] for l in lines),
    )
    return {**block, "lines": lines, "bbox": bbox}


def order_blocks(blocks: list, page_width: float) -> list:
    """Sort layout blocks (dicts with a ``bbox`` key) into reading order.

    Single-column pages sort by (top, left). When the page has distinct
    left and right column blocks, the page is split into vertical bands
    at each full-width ("spanning") block; within a band the left column
    is read first, then the right column.
    """
    if not blocks:
        return []
    mid = page_width / 2.0
    left, right, spanning = [], [], []
    for block in blocks:
        x0, _, x1, _ = block["bbox"]
        if x0 < mid - _COLUMN_TOLERANCE and x1 > mid + _COLUMN_TOLERANCE:
            spanning.append(block)
        elif x1 <= mid + _COLUMN_TOLERANCE:
            left.append(block)
        else:
            right.append(block)
    if not left or not right:
        return sorted(blocks, key=lambda b: (round(b["bbox"][1], 1), b["bbox"][0]))

    spanning.sort(key=lambda b: b["bbox"][1])
    bands: list[tuple[float, float, dict | None]] = []
    prev_bottom = float("-inf")
    for span_block in spanning:
        bands.append((prev_bottom, span_block["bbox"][1], span_block))
        prev_bottom = span_block["bbox"][3]
    bands.append((prev_bottom, float("inf"), None))

    def center_y(block: dict) -> float:
        return (block["bbox"][1] + block["bbox"][3]) / 2.0

    ordered: list = []
    for top, bottom, closer in bands:
        for column in (left, right):
            in_band = [b for b in column if top <= center_y(b) < bottom]
            ordered.extend(sorted(in_band, key=lambda b: b["bbox"][1]))
        if closer is not None:
            ordered.append(closer)
    return ordered


def _normalized(text: str) -> str:
    """Normalize furniture text so 'Page 3' and 'Page 4' match."""
    return re.sub(r"\d+", "#", " ".join(text.lower().split()))


def detect_furniture(
    pages_elements: dict, page_height: float, page_count: int
) -> None:
    """Reclassify repeated header/footer text and page numbers in place.

    ``pages_elements`` maps page number -> list of DocumentElement. Only
    text-like elements inside the top/bottom 8% bands of the page are
    candidates. A candidate becomes a header/footer when its normalized
    text repeats on at least half the pages (min 2); standalone page
    numbers are reclassified regardless of repetition.
    """
    top_limit = page_height * 0.08
    bottom_limit = page_height * 0.92
    text_types = (ElementType.PARAGRAPH, ElementType.HEADING, ElementType.CAPTION)

    def zone(el: DocumentElement) -> str | None:
        if el.type not in text_types or not el.source or not el.source.bounding_box:
            return None
        box = el.source.bounding_box
        if box.y1 <= top_limit:
            return "top"
        if box.y >= bottom_limit:
            return "bottom"
        return None

    counts: Counter = Counter()
    for elements in pages_elements.values():
        seen_on_page = set()
        for el in elements:
            z = zone(el)
            if z:
                key = (z, _normalized(el.content))
                if key not in seen_on_page:
                    counts[key] += 1
                    seen_on_page.add(key)

    threshold = max(2, page_count // 2)
    for elements in pages_elements.values():
        for el in elements:
            z = zone(el)
            if not z:
                continue
            if _PAGE_NUMBER_RE.match(el.content):
                el.type = ElementType.PAGE_NUMBER
            elif counts[(z, _normalized(el.content))] >= threshold:
                el.type = ElementType.HEADER if z == "top" else ElementType.FOOTER
            if el.type in ElementType.FURNITURE:
                el.level = None
