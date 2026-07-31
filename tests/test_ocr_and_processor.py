"""OCR parsing and the full pipeline (model calls mocked)."""
import json

import pytest

from config.settings import SETTINGS
from src.models import ElementType
from src.services import llm_support, ocr_service, pdf_processor

PAGE_W, PAGE_H = 595, 842

_OCR_PAYLOAD = [
    {
        "type": "heading",
        "content": "Scanned page heading",
        "level": 1,
        "bbox": [10, 8, 80, 14],
        "confidence": 0.93,
    },
    {
        "type": "paragraph",
        "content": "Transcribed body text.",
        "bbox": [10, 20, 90, 30],
        "confidence": 0.88,
    },
    {"type": "nonsense-type", "content": "coerced", "bbox": [0, 50, 50, 60]},
    {"type": "paragraph", "content": ""},  # empty content dropped
]


def _databricks(monkeypatch, enabled: bool) -> None:
    monkeypatch.setattr(
        type(SETTINGS), "databricks_enabled", property(lambda self: enabled)
    )


def test_ocr_page_parses_elements(monkeypatch):
    monkeypatch.setattr(
        llm_support,
        "complete_with_retry",
        lambda messages, system=None: (json.dumps(_OCR_PAYLOAD), False),
    )
    elements = ocr_service.ocr_page(b"png", 4, PAGE_W, PAGE_H)
    assert len(elements) == 3
    heading = elements[0]
    assert heading.type == ElementType.HEADING and heading.level == 1
    assert heading.source.page == 4
    assert heading.source.extraction_method == "llm_ocr"
    assert heading.source.confidence == pytest.approx(0.93)
    # bbox percentages converted to page points
    box = heading.source.bounding_box
    assert box.x == pytest.approx(0.10 * PAGE_W)
    assert box.y1 == pytest.approx(0.14 * PAGE_H)
    # unknown type coerced to paragraph
    assert elements[2].type == ElementType.PARAGRAPH


def test_ocr_page_rejects_non_json(monkeypatch):
    monkeypatch.setattr(
        llm_support,
        "complete_with_retry",
        lambda messages, system=None: ("Sorry, I cannot do that.", False),
    )
    with pytest.raises(ocr_service.OcrError):
        ocr_service.ocr_page(b"png", 1, PAGE_W, PAGE_H)


def test_processor_native_document(text_pdf_bytes, monkeypatch):
    _databricks(monkeypatch, False)
    labels = []
    document = pdf_processor.process_pdf(
        text_pdf_bytes,
        "report.pdf",
        options=pdf_processor.ProcessingOptions(
            use_llm_ocr=False, describe_visuals=False
        ),
        progress=lambda label, fraction: labels.append((label, fraction)),
    )
    assert document.page_count == 3
    assert document.metadata["native_pages"] == 3
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


def test_processor_ocr_fallback_with_mock(scanned_pdf_bytes, monkeypatch):
    _databricks(monkeypatch, True)
    calls = {}

    def fake_ocr(png, page_number, width, height):
        calls["page"] = page_number
        return [
            ocr_service.DocumentElement(
                id="ocr1",
                type=ElementType.PARAGRAPH,
                content="Recovered scanned text",
                source=ocr_service.SourceReference(
                    page=page_number, extraction_method="llm_ocr", confidence=0.9
                ),
            )
        ]

    monkeypatch.setattr(ocr_service, "ocr_page", fake_ocr)
    document = pdf_processor.process_pdf(
        scanned_pdf_bytes,
        "scan.pdf",
        options=pdf_processor.ProcessingOptions(describe_visuals=False),
    )
    assert calls["page"] == 1
    assert document.metadata["ocr_pages"] == 1
    assert any("Recovered scanned text" in el.content for el in document.elements)


def test_processor_ocr_failure_becomes_placeholder(scanned_pdf_bytes, monkeypatch):
    _databricks(monkeypatch, True)

    def boom(png, page_number, width, height):
        raise ocr_service.OcrError("model unavailable")

    monkeypatch.setattr(ocr_service, "ocr_page", boom)
    document = pdf_processor.process_pdf(
        scanned_pdf_bytes,
        "scan.pdf",
        options=pdf_processor.ProcessingOptions(describe_visuals=False),
    )
    assert document.warnings, "expected an OCR warning"
    placeholder = document.elements[0]
    assert placeholder.metadata.get("ocr_failed") is True
    assert placeholder.source.bounding_box is not None


def test_processor_without_model_marks_scanned_pages(scanned_pdf_bytes, monkeypatch):
    _databricks(monkeypatch, False)
    document = pdf_processor.process_pdf(
        scanned_pdf_bytes,
        "scan.pdf",
        options=pdf_processor.ProcessingOptions(describe_visuals=False),
    )
    assert any("scanned" in w for w in document.warnings)
    assert any(
        el.metadata.get("ocr_failed") for el in document.elements
    )


def test_parse_json_payload_tolerates_fences_and_prose():
    payload = llm_support.parse_json_payload(
        'Sure! Here you go:\n```json\n{"action": "edit", "edits": []}\n```'
    )
    assert payload == {"action": "edit", "edits": []}
    array = llm_support.parse_json_payload("prefix [1, 2, 3] suffix")
    assert array == [1, 2, 3]
    with pytest.raises(ValueError):
        llm_support.parse_json_payload("no json here")
