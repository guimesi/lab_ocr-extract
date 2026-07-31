"""Serialization round-trips and element edit bookkeeping."""
from src.models import (
    BoundingBox,
    DocumentElement,
    ElementType,
    ExtractedDocument,
    SourceReference,
)


def test_bounding_box_roundtrip():
    box = BoundingBox.from_rect(10.0, 20.0, 110.0, 60.0)
    assert (box.width, box.height) == (100.0, 40.0)
    assert (box.x1, box.y1) == (110.0, 60.0)
    restored = BoundingBox.from_dict(box.to_dict())
    assert restored == box


def test_source_reference_roundtrip():
    ref = SourceReference(
        page=3,
        bounding_box=BoundingBox(1, 2, 3, 4),
        extraction_method="llm_ocr",
        confidence=0.87,
    )
    restored = SourceReference.from_dict(ref.to_dict())
    assert restored == ref


def test_source_reference_without_bbox():
    ref = SourceReference(page=1, bounding_box=None, extraction_method="authored")
    assert SourceReference.from_dict(ref.to_dict()).bounding_box is None


def test_element_roundtrip_preserves_everything(sample_document):
    for el in sample_document.elements:
        restored = DocumentElement.from_dict(el.to_dict())
        assert restored.to_dict() == el.to_dict()


def test_record_edit_keeps_first_original():
    el = DocumentElement(id="x", type=ElementType.PARAGRAPH, content="v1")
    el.record_edit("v2", "ai")
    el.record_edit("v3", "manual")
    assert el.content == "v3"
    assert el.original_content == "v1"
    assert el.edited_by == "manual"
    assert el.edited


def test_document_roundtrip(sample_document):
    restored = ExtractedDocument.from_dict(sample_document.to_dict())
    assert restored.to_dict() == sample_document.to_dict()
    assert restored.get("p1").content == sample_document.get("p1").content


def test_body_elements_excludes_furniture(sample_document):
    ids = [el.id for el in sample_document.body_elements()]
    assert "f1" not in ids and "pn1" not in ids
    assert "p1" in ids
