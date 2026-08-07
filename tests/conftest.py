"""Shared fixtures: representative PDFs built in-memory with PyMuPDF."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.models import (  # noqa: E402
    BoundingBox,
    DocumentElement,
    ElementType,
    ExtractedDocument,
    SourceReference,
)

PAGE_W, PAGE_H = 595, 842  # A4 in points

_LOREM = (
    "This is a plain body paragraph with enough words that the font "
    "size of the body text clearly dominates the document statistics."
)


@pytest.fixture()
def text_pdf_bytes() -> bytes:
    """3-page native-text PDF: title, headings, paragraphs, a list,
    repeated header/footer and page numbers."""
    import fitz

    doc = fitz.open()
    for page_no in range(3):
        page = doc.new_page(width=PAGE_W, height=PAGE_H)
        page.insert_text((72, 40), "ACME Corp Annual Report", fontsize=9)
        y = 110
        if page_no == 0:
            page.insert_text((72, y), "Annual Report 2025", fontsize=24)
            y += 50
            page.insert_text((72, y), "Introduction", fontsize=16)
            y += 30
        page.insert_text((72, y), _LOREM, fontsize=11)
        y += 40
        page.insert_text((72, y), f"Section body on page {page_no + 1}. " + _LOREM, fontsize=11)
        y += 40
        if page_no == 0:
            page.insert_text((72, y), "- first bullet item", fontsize=11)
            page.insert_text((72, y + 16), "- second bullet item", fontsize=11)
        page.insert_text((290, 820), f"Page {page_no + 1} of 3", fontsize=9)
    return doc.tobytes()


@pytest.fixture()
def table_pdf_bytes() -> bytes:
    """One page with a ruled 3x3 table plus a paragraph outside it."""
    import fitz

    doc = fitz.open()
    page = doc.new_page(width=PAGE_W, height=PAGE_H)
    page.insert_text((72, 60), "Inventory overview. " + _LOREM, fontsize=11)
    x0, y0, cw, rh, cols, rows = 72, 120, 150, 24, 3, 3
    for r in range(rows + 1):
        page.draw_line((x0, y0 + r * rh), (x0 + cols * cw, y0 + r * rh))
    for c in range(cols + 1):
        page.draw_line((x0 + c * cw, y0), (x0 + c * cw, y0 + rows * rh))
    data = [["Name", "Qty", "Price"], ["Widget", "2", "9.99"], ["Gadget", "5", "19.90"]]
    for r, row in enumerate(data):
        for c, cell in enumerate(row):
            page.insert_text((x0 + c * cw + 4, y0 + r * rh + 16), cell, fontsize=10)
    return doc.tobytes()


@pytest.fixture()
def two_column_pdf_bytes() -> bytes:
    """A spanning heading over two columns of body text."""
    import fitz

    doc = fitz.open()
    page = doc.new_page(width=PAGE_W, height=PAGE_H)
    page.insert_text((72, 60), "A Wide Spanning Headline Across Columns", fontsize=18)
    for i in range(3):
        page.insert_text(
            (40, 120 + i * 60),
            f"Left column paragraph {i + 1} with some plain body text here.",
            fontsize=10,
        )
        page.insert_text(
            (320, 120 + i * 60),
            f"Right column paragraph {i + 1} with some plain body text here.",
            fontsize=10,
        )
    return doc.tobytes()


@pytest.fixture()
def scanned_pdf_bytes() -> bytes:
    """A PDF whose single page is a rendered image (no text layer)."""
    import fitz

    source = fitz.open()
    page = source.new_page(width=PAGE_W, height=PAGE_H)
    page.insert_text((72, 100), "Scanned page heading", fontsize=20)
    page.insert_text((72, 160), _LOREM, fontsize=11)
    pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
    png = pix.tobytes("png")
    source.close()

    doc = fitz.open()
    page = doc.new_page(width=PAGE_W, height=PAGE_H)
    page.insert_image(page.rect, stream=png)
    return doc.tobytes()


@pytest.fixture()
def protected_pdf_bytes() -> bytes:
    import fitz

    doc = fitz.open()
    page = doc.new_page(width=PAGE_W, height=PAGE_H)
    page.insert_text((72, 100), "secret", fontsize=12)
    return doc.tobytes(
        encryption=fitz.PDF_ENCRYPT_AES_256, user_pw="pw", owner_pw="pw"
    )


def make_element(
    el_id: str,
    el_type: str = ElementType.PARAGRAPH,
    content: str = "text",
    page: int = 1,
    level=None,
    table_data=None,
) -> DocumentElement:
    return DocumentElement(
        id=el_id,
        type=el_type,
        content=content,
        level=level,
        table_data=table_data,
        source=SourceReference(
            page=page,
            bounding_box=BoundingBox(x=72, y=100, width=200, height=20),
            extraction_method="native_text",
        ),
    )


@pytest.fixture()
def sample_document() -> ExtractedDocument:
    elements = [
        make_element("t1", ElementType.TITLE, "Report Title"),
        make_element("h1", ElementType.HEADING, "Introduction", level=2),
        make_element("p1", ElementType.PARAGRAPH, "Hello <script>alert(1)</script> world & more"),
        make_element("l1", ElementType.LIST, "- alpha\n- beta"),
        make_element(
            "tb1",
            ElementType.TABLE,
            "| A | B |\n| --- | --- |\n| 1 | 2 |",
            page=2,
            table_data=[["A", "B"], ["1", "2"]],
        ),
        make_element("img1", ElementType.IMAGE, "*[Image - content not extracted.]*", page=2),
        make_element("f1", ElementType.FOOTER, "Confidential"),
        make_element("pn1", ElementType.PAGE_NUMBER, "1"),
    ]
    for order, el in enumerate(elements):
        el.order = order
    return ExtractedDocument(
        file_name="sample.pdf", page_count=2, elements=elements
    )
