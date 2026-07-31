"""Final assembly: ordering, title promotion, hierarchy, language."""
from src.models import ElementType
from src.services import source_mapper

from tests.conftest import make_element


def test_finalize_orders_and_links():
    pages = {
        1: [
            make_element("h_top", ElementType.HEADING, "Big Title", level=1),
            make_element("h_sec", ElementType.HEADING, "Section One", level=2),
            make_element("p_a", ElementType.PARAGRAPH, "the and of to in is for with that on"),
        ],
        2: [
            make_element("p_b", ElementType.PARAGRAPH, "the and of to in is more body text", page=2),
        ],
    }
    document = source_mapper.finalize("f.pdf", 2, pages, warnings=["w1"])
    ids = [el.id for el in document.elements]
    assert ids == ["h_top", "h_sec", "p_a", "p_b"]
    assert [el.order for el in document.elements] == [0, 1, 2, 3]

    # the level-1 heading on page 1 became the document title
    assert document.get("h_top").type == ElementType.TITLE
    # hierarchy: section under title, paragraph under section
    assert document.get("h_sec").parent_id == "h_top"
    assert document.get("p_a").parent_id == "h_sec"
    assert document.language == "en"
    assert document.warnings == ["w1"]
    assert document.processed_at


def test_no_title_promotion_without_page1_heading():
    pages = {1: [make_element("p", ElementType.PARAGRAPH, "just text")]}
    document = source_mapper.finalize("f.pdf", 1, pages, warnings=[])
    assert document.get("p").type == ElementType.PARAGRAPH
