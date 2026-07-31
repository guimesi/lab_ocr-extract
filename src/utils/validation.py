"""Upload validation: fail early with a clear, user-facing message."""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


class ValidationError(Exception):
    """Raised when an upload cannot be processed; the message is safe to
    show to the user."""


def validate_pdf_upload(
    file_bytes: bytes, file_name: str, max_mb: int
) -> int:
    """Validate an uploaded PDF; return its page count.

    Raises :class:`ValidationError` for empty files, oversized files,
    non-PDF content, corrupted PDFs, password-protected PDFs and PDFs
    with zero pages.
    """
    if not file_bytes:
        raise ValidationError(f'"{file_name}" is empty.')
    size_mb = len(file_bytes) / (1024 * 1024)
    if max_mb > 0 and size_mb > max_mb:
        raise ValidationError(
            f'"{file_name}" is {size_mb:.1f} MB; the limit is {max_mb} MB '
            "(MAX_UPLOAD_MB)."
        )
    if not file_bytes.lstrip()[:5].startswith(b"%PDF-"):
        raise ValidationError(
            f'"{file_name}" does not look like a PDF file (missing %PDF '
            "header). Please upload a valid PDF."
        )

    import fitz  # PyMuPDF

    try:
        doc = fitz.open(stream=file_bytes, filetype="pdf")
    except Exception as exc:
        logger.warning("Failed to open PDF %s: %s", file_name, exc)
        raise ValidationError(
            f'"{file_name}" could not be opened - the file appears to be '
            "corrupted or is not a valid PDF."
        ) from exc
    try:
        if doc.needs_pass:
            raise ValidationError(
                f'"{file_name}" is password-protected. Remove the password '
                "and upload it again."
            )
        page_count = doc.page_count
        if page_count == 0:
            raise ValidationError(f'"{file_name}" contains no pages.')
        return page_count
    finally:
        doc.close()
