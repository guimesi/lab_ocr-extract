"""Full extraction pipeline (pure PyMuPDF, no model calls)."""
from src.models import ElementType
from src.services import pdf_processor


def test_processor_native_document(text_pdf_bytes):
    labels = []
    document = pdf_processor.process_pdf(
        text_pdf_bytes,
        "report.pdf",
        progress=lambda label, fraction: labels.append((label, fraction)),
    )
    assert document.page_count == 3
    assert document.metadata["native_pages"] == 3
    assert document.metadata["scanned_pages"] == 0
    types = {el.type for el in document.elements}
    assert ElementType.TITLE in types or ElementType.HEADING in types
    # repeated header/page numbers classified as furniture
    assert any(el.is_furniture for el in document.elements)
    # ids unique, order strictly increasing
    ids = [el.id for el in document.elements]
    assert len(ids) == len(set(ids))
    assert [el.order for el in document.elements] == list(range(len(ids)))
    assert labels and labels[-1][1] == 1.0
    assert document.language == "en"


def test_processor_marks_scanned_pages(scanned_pdf_bytes):
    document = pdf_processor.process_pdf(scanned_pdf_bytes, "scan.pdf")
    assert document.metadata["scanned_pages"] == 1
    assert any("scanned" in w for w in document.warnings)
    placeholder = next(
        el for el in document.elements if el.metadata.get("scanned_page")
    )
    assert placeholder.source.extraction_method == "scanned_page"
    assert placeholder.source.bounding_box is not None


def test_processor_respects_max_pages(text_pdf_bytes):
    document = pdf_processor.process_pdf(
        text_pdf_bytes,
        "report.pdf",
        options=pdf_processor.ProcessingOptions(max_pages=1),
    )
    assert document.page_count == 3
    assert all(el.source.page == 1 for el in document.elements)
    assert any("PDF_MAX_PAGES" in w for w in document.warnings)
