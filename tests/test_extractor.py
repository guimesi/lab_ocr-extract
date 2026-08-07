"""Text extraction (pure PyMuPDF, no model calls)."""
import pytest

from src import extractor


def test_extracts_native_text(text_pdf_bytes):
    text, warnings = extractor.extract_text(text_pdf_bytes)
    assert "Annual Report 2025" in text
    assert "Section body on page 3." in text
    assert warnings == []


def test_marks_scanned_pages(scanned_pdf_bytes):
    text, warnings = extractor.extract_text(scanned_pdf_bytes)
    assert "appears to be scanned" in text
    assert any("scanned" in w for w in warnings)


def test_respects_max_pages(text_pdf_bytes, monkeypatch):
    from config.settings import SETTINGS

    monkeypatch.setattr(
        type(SETTINGS), "pdf_max_pages", property(lambda self: 1)
    )
    text, warnings = extractor.extract_text(text_pdf_bytes)
    assert "Section body on page 1." in text
    assert "Section body on page 2." not in text
    assert any("PDF_MAX_PAGES" in w for w in warnings)


def test_rejects_garbage():
    with pytest.raises(extractor.ExtractionError):
        extractor.extract_text(b"not a pdf at all")
