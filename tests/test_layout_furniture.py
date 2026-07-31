"""Header/footer/page-number reclassification."""
from src.models import BoundingBox, DocumentElement, ElementType, SourceReference
from src.services import layout_analyzer

PAGE_H = 842


def _el(el_id, content, y, height=12, el_type=ElementType.PARAGRAPH, page=1):
    return DocumentElement(
        id=el_id,
        type=el_type,
        content=content,
        source=SourceReference(
            page=page,
            bounding_box=BoundingBox(x=72, y=y, width=200, height=height),
        ),
    )


def test_repeated_header_footer_and_page_numbers():
    pages = {}
    for page in (1, 2, 3):
        pages[page] = [
            _el(f"h{page}", "ACME Corp Report", y=30, page=page),
            _el(f"b{page}", "Body paragraph content here.", y=400, page=page),
            _el(f"n{page}", f"Page {page} of 3", y=810, page=page),
        ]
    layout_analyzer.detect_furniture(pages, PAGE_H, 3)
    for page in (1, 2, 3):
        assert pages[page][0].type == ElementType.HEADER
        assert pages[page][1].type == ElementType.PARAGRAPH
        assert pages[page][2].type == ElementType.PAGE_NUMBER


def test_unique_top_text_is_not_a_header():
    pages = {
        1: [_el("a", "Unique document title", y=30)],
        2: [_el("b", "Completely different text", y=30, page=2)],
        3: [_el("c", "Another different line", y=30, page=3)],
    }
    layout_analyzer.detect_furniture(pages, PAGE_H, 3)
    assert all(els[0].type == ElementType.PARAGRAPH for els in pages.values())


def test_mid_page_text_never_reclassified():
    pages = {
        1: [_el("a", "Repeated body line", y=400)],
        2: [_el("b", "Repeated body line", y=400, page=2)],
        3: [_el("c", "Repeated body line", y=400, page=3)],
    }
    layout_analyzer.detect_furniture(pages, PAGE_H, 3)
    assert all(els[0].type == ElementType.PARAGRAPH for els in pages.values())
