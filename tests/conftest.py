"""Shared fixtures: representative PDFs built in-memory with PyMuPDF."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

PAGE_W, PAGE_H = 595, 842  # A4 in points

_LOREM = (
    "This is a plain body paragraph with enough words that the font "
    "size of the body text clearly dominates the document statistics."
)


@pytest.fixture()
def text_pdf_bytes() -> bytes:
    """3-page native-text PDF with a title, headings and paragraphs."""
    import fitz

    doc = fitz.open()
    for page_no in range(3):
        page = doc.new_page(width=PAGE_W, height=PAGE_H)
        y = 110
        if page_no == 0:
            page.insert_text((72, y), "Annual Report 2025", fontsize=24)
            y += 50
        page.insert_text((72, y), _LOREM, fontsize=11)
        y += 40
        page.insert_text(
            (72, y), f"Section body on page {page_no + 1}.", fontsize=11
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
