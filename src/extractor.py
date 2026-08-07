"""Extract the text of a PDF as one Markdown-friendly string (PyMuPDF)."""
from __future__ import annotations

from config.settings import SETTINGS

# Pages with fewer native characters than this are treated as scanned.
SCANNED_PAGE_CHAR_THRESHOLD = 30


class ExtractionError(Exception):
    """The PDF could not be processed; the message is safe to display."""


def extract_text(file_bytes: bytes) -> tuple[str, list[str]]:
    """Return the PDF's text as Markdown-friendly plain text plus warnings.

    Text blocks are joined with blank lines; pages are separated by a
    blank line. Pages without a native text layer (scanned images) are
    marked with a visible placeholder and reported as a warning.
    """
    import fitz  # PyMuPDF

    try:
        doc = fitz.open(stream=file_bytes, filetype="pdf")
    except Exception as exc:
        raise ExtractionError(f"Could not open the PDF: {exc}") from exc

    warnings: list[str] = []
    parts: list[str] = []
    try:
        limit = doc.page_count
        if SETTINGS.pdf_max_pages > 0:
            limit = min(limit, SETTINGS.pdf_max_pages)
            if limit < doc.page_count:
                warnings.append(
                    f"The PDF has {doc.page_count} pages; only the first "
                    f"{limit} were extracted (PDF_MAX_PAGES)."
                )

        scanned: list[int] = []
        for i in range(limit):
            page_number = i + 1
            blocks = doc.load_page(i).get_text("blocks", sort=True)
            texts = [
                " ".join(block[4].split())
                for block in blocks
                if block[6] == 0 and block[4].strip()
            ]
            if sum(len(t) for t in texts) < SCANNED_PAGE_CHAR_THRESHOLD:
                scanned.append(page_number)
                parts.append(
                    f"*[Page {page_number} appears to be scanned and "
                    "contains no extractable text.]*"
                )
            else:
                parts.extend(texts)

        if scanned:
            warnings.append(
                f"{len(scanned)} page(s) contain no extractable text "
                "(likely scanned images): "
                f"page(s) {', '.join(str(p) for p in scanned)}."
            )
        return "\n\n".join(parts), warnings
    finally:
        doc.close()
