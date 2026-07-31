"""Table detection and conversion to structured rows + Markdown."""
from __future__ import annotations

import logging

from src.models import BoundingBox, DocumentElement, ElementType, SourceReference
from src.models.document_element import new_element_id

logger = logging.getLogger(__name__)


def rows_to_markdown(rows: list) -> str:
    """Render ``list[list[str]]`` as a GitHub Markdown table.

    The first row is treated as the header. Pipe characters inside cells
    are escaped; newlines collapse to spaces so rows stay on one line.
    """
    if not rows:
        return ""
    width = max(len(r) for r in rows)

    def cell(value) -> str:
        text = "" if value is None else str(value)
        return text.replace("\n", " ").replace("|", "\\|").strip()

    def line(row: list) -> str:
        padded = list(row) + [""] * (width - len(row))
        return "| " + " | ".join(cell(c) for c in padded) + " |"

    out = [line(rows[0]), "| " + " | ".join("---" for _ in range(width)) + " |"]
    out.extend(line(r) for r in rows[1:])
    return "\n".join(out)


def clean_rows(raw_rows: list) -> list:
    """Normalize PyMuPDF's ``Table.extract()`` output (None -> "")."""
    rows = []
    for raw in raw_rows:
        row = ["" if c is None else str(c).strip() for c in raw]
        if any(row):
            rows.append(row)
    return rows


def extract_tables(page, page_number: int) -> tuple[list, list]:
    """Detect tables on a page.

    Returns ``(elements, bboxes)`` where ``bboxes`` are the table
    rectangles (``fitz.Rect``-like 4-tuples) so the text extractor can
    skip blocks already captured by a table.
    """
    elements: list[DocumentElement] = []
    bboxes: list = []
    try:
        finder = page.find_tables()
        tables = list(finder.tables)
    except Exception as exc:
        logger.warning("Table detection failed on page %s: %s", page_number, exc)
        raise
    for tab in tables:
        try:
            rows = clean_rows(tab.extract())
        except Exception as exc:
            logger.warning(
                "Table extraction failed on page %s: %s", page_number, exc
            )
            continue
        if not rows:
            continue
        x0, y0, x1, y1 = tab.bbox
        elements.append(
            DocumentElement(
                id=new_element_id(),
                type=ElementType.TABLE,
                content=rows_to_markdown(rows),
                table_data=rows,
                source=SourceReference(
                    page=page_number,
                    bounding_box=BoundingBox.from_rect(x0, y0, x1, y1),
                    extraction_method="table_detection",
                ),
            )
        )
        bboxes.append((x0, y0, x1, y1))
    return elements, bboxes
