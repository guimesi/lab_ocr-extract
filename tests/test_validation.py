"""Upload validation: malformed, protected, oversized, non-PDF files."""
import pytest

from src.utils.validation import ValidationError, validate_pdf_upload


def test_valid_pdf_returns_page_count(text_pdf_bytes):
    assert validate_pdf_upload(text_pdf_bytes, "doc.pdf", max_mb=100) == 3


def test_empty_file_rejected():
    with pytest.raises(ValidationError, match="empty"):
        validate_pdf_upload(b"", "empty.pdf", max_mb=100)


def test_non_pdf_rejected():
    with pytest.raises(ValidationError, match="does not look like a PDF"):
        validate_pdf_upload(b"hello world" * 100, "notes.pdf", max_mb=100)


def test_corrupted_pdf_rejected():
    with pytest.raises(ValidationError, match="corrupted|could not be opened"):
        validate_pdf_upload(b"%PDF-1.7\ngarbage garbage", "bad.pdf", max_mb=100)


def test_oversized_pdf_rejected(text_pdf_bytes):
    with pytest.raises(ValidationError, match="limit"):
        validate_pdf_upload(text_pdf_bytes, "big.pdf", max_mb=0.000001)


def test_password_protected_rejected(protected_pdf_bytes):
    with pytest.raises(ValidationError, match="password"):
        validate_pdf_upload(protected_pdf_bytes, "locked.pdf", max_mb=100)
