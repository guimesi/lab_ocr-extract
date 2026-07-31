"""Native extraction: structure classification, reading order, tables."""
import fitz

from src.models import ElementType
from src.services import layout_analyzer, native_text_extractor, table_extractor


def _open(pdf_bytes):
    return fitz.open(stream=pdf_bytes, filetype="pdf")


def test_headings_and_paragraphs_detected(text_pdf_bytes):
    with _open(text_pdf_bytes) as doc:
        body = native_text_extractor.compute_body_font_size(doc)
        elements = native_text_extractor.extract_page(doc.load_page(0), 1, body, [])
    contents = {el.content for el in elements}
    headings = [el for el in elements if el.type == ElementType.HEADING]
    assert any("Annual Report 2025" in el.content for el in headings)
    assert any("Introduction" in el.content for el in headings)
    # The largest heading outranks the section heading.
    top = next(el for el in headings if "Annual Report" in el.content)
    intro = next(el for el in headings if el.content == "Introduction")
    assert top.level < intro.level
    assert any(el.type == ElementType.PARAGRAPH for el in elements)
    assert any("body paragraph" in c for c in contents)


def test_list_detected_and_merged(text_pdf_bytes):
    with _open(text_pdf_bytes) as doc:
        body = native_text_extractor.compute_body_font_size(doc)
        elements = native_text_extractor.extract_page(doc.load_page(0), 1, body, [])
    lists = [el for el in elements if el.type == ElementType.LIST]
    assert lists, "expected a list element"
    merged = "\n".join(el.content for el in lists)
    assert "first bullet item" in merged and "second bullet item" in merged


def test_every_element_has_source_reference(text_pdf_bytes):
    with _open(text_pdf_bytes) as doc:
        body = native_text_extractor.compute_body_font_size(doc)
        for i in range(doc.page_count):
            for el in native_text_extractor.extract_page(
                doc.load_page(i), i + 1, body, []
            ):
                assert el.source is not None
                assert el.source.page == i + 1
                box = el.source.bounding_box
                assert box is not None and box.width > 0 and box.height > 0


def test_two_column_reading_order(two_column_pdf_bytes):
    with _open(two_column_pdf_bytes) as doc:
        body = native_text_extractor.compute_body_font_size(doc)
        elements = native_text_extractor.extract_page(doc.load_page(0), 1, body, [])
    texts = [el.content for el in elements]
    left_positions = [i for i, t in enumerate(texts) if t.startswith("Left column")]
    right_positions = [i for i, t in enumerate(texts) if t.startswith("Right column")]
    assert left_positions and right_positions
    assert max(left_positions) < min(right_positions)


def test_order_blocks_single_column_sorts_by_position():
    blocks = [
        {"bbox": (10, 200, 500, 220), "tag": "second"},
        {"bbox": (10, 100, 500, 120), "tag": "first"},
    ]
    ordered = layout_analyzer.order_blocks(blocks, 595)
    assert [b["tag"] for b in ordered] == ["first", "second"]


def test_table_extracted_as_structured_rows(table_pdf_bytes):
    with _open(table_pdf_bytes) as doc:
        elements, bboxes = table_extractor.extract_tables(doc.load_page(0), 1)
    assert len(elements) == 1 and len(bboxes) == 1
    table = elements[0]
    assert table.type == ElementType.TABLE
    assert table.table_data[0] == ["Name", "Qty", "Price"]
    assert ["Widget", "2", "9.99"] in table.table_data
    assert table.content.startswith("| Name | Qty | Price |")
    assert table.source.extraction_method == "table_detection"


def test_table_text_not_duplicated_as_paragraphs(table_pdf_bytes):
    with _open(table_pdf_bytes) as doc:
        page = doc.load_page(0)
        _, bboxes = table_extractor.extract_tables(page, 1)
        body = native_text_extractor.compute_body_font_size(doc)
        elements = native_text_extractor.extract_page(page, 1, body, bboxes)
    joined = " ".join(el.content for el in elements)
    assert "Widget" not in joined
    assert "Inventory overview" in joined


def test_rows_to_markdown_escapes_pipes():
    md = table_extractor.rows_to_markdown([["a|b", "c"], ["d", "e\nf"]])
    assert "a\\|b" in md
    assert "e f" in md  # newline collapsed


def test_scanned_page_detected(scanned_pdf_bytes, text_pdf_bytes):
    with _open(scanned_pdf_bytes) as doc:
        assert native_text_extractor.page_char_count(doc.load_page(0)) < (
            native_text_extractor.SCANNED_PAGE_CHAR_THRESHOLD
        )
    with _open(text_pdf_bytes) as doc:
        assert native_text_extractor.page_char_count(doc.load_page(0)) >= (
            native_text_extractor.SCANNED_PAGE_CHAR_THRESHOLD
        )
