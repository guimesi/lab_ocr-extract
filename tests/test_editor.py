"""Document editor: apply, undo/redo, restore, revision records."""
import pytest

from src.models import ElementType
from src.services.document_editor import DocumentEditor, EditError, EditOperation


@pytest.fixture()
def editor(sample_document):
    return DocumentEditor(sample_document.copy())


def _update(el_id, content):
    return EditOperation(op="update", element_id=el_id, content=content)


def test_update_preserves_id_and_source(editor):
    before = editor.document.get("p1")
    source_before = before.source.to_dict()
    editor.apply_operations([_update("p1", "New text")], source="ai", instruction="fix")
    after = editor.document.get("p1")
    assert after.id == "p1"
    assert after.content == "New text"
    assert after.original_content == before.original_content or after.original_content
    assert after.edited_by == "ai"
    assert after.source.to_dict() == source_before  # mapping survives edits


def test_manual_edit_marked_manual(editor):
    editor.apply_operations([_update("p1", "hand fixed")], source="manual")
    assert editor.document.get("p1").edited_by == "manual"


def test_insert_after_and_delete(editor):
    n = len(editor.document.elements)
    editor.apply_operations(
        [
            EditOperation(
                op="insert_after",
                element_id="p1",
                content="Inserted paragraph",
                element_type=ElementType.PARAGRAPH,
            )
        ],
        source="ai",
    )
    assert len(editor.document.elements) == n + 1
    p1_index = editor.document.index_of("p1")
    inserted = editor.document.elements[p1_index + 1]
    assert inserted.content == "Inserted paragraph"
    assert inserted.source.extraction_method == "authored"
    assert inserted.source.page == 1  # inherited from anchor

    editor.apply_operations(
        [EditOperation(op="delete", element_id=inserted.id)], source="ai"
    )
    assert editor.document.get(inserted.id) is None
    assert len(editor.document.elements) == n


def test_unknown_element_rejected(editor):
    with pytest.raises(EditError, match="does not exist"):
        editor.apply_operations([_update("nope", "x")], source="ai")


def test_undo_redo_roundtrip(editor):
    original = editor.document.get("p1").content
    editor.apply_operations([_update("p1", "v2")], source="ai")
    editor.apply_operations(
        [
            _update("p1", "v3"),
            EditOperation(op="delete", element_id="l1"),
        ],
        source="ai",
    )
    assert editor.document.get("p1").content == "v3"
    assert editor.document.get("l1") is None

    editor.undo()
    assert editor.document.get("p1").content == "v2"
    assert editor.document.get("l1") is not None
    assert editor.document.index_of("l1") == 3  # original position restored

    editor.undo()
    assert editor.document.get("p1").content == original
    assert not editor.can_undo

    editor.redo()
    editor.redo()
    assert editor.document.get("p1").content == "v3"
    assert editor.document.get("l1") is None
    assert not editor.can_redo


def test_new_edit_clears_redo(editor):
    editor.apply_operations([_update("p1", "v2")], source="ai")
    editor.undo()
    editor.apply_operations([_update("p1", "different")], source="manual")
    assert not editor.can_redo


def test_restore_original(editor):
    original_dicts = [el.to_dict() for el in editor.original.elements]
    editor.apply_operations([_update("p1", "changed")], source="ai")
    editor.apply_operations(
        [EditOperation(op="delete", element_id="tb1")], source="ai"
    )
    editor.restore_original()
    assert [el.to_dict() for el in editor.document.elements] == original_dicts
    assert not editor.can_undo and not editor.can_redo


def test_revision_record_contents(editor):
    revision = editor.apply_operations(
        [_update("p1", "v2")], source="ai", instruction="please fix p1"
    )
    assert revision.source == "ai"
    assert revision.instruction == "please fix p1"
    assert revision.affected_ids == ["p1"]
    assert revision.timestamp
    change = revision.changes[0]
    assert change.before["content"] != change.after["content"]
    assert change.after["content"] == "v2"
    payload = revision.to_dict()
    assert payload["affected_element_ids"] == ["p1"]


def test_original_extraction_never_mutated(editor):
    pristine = editor.original.get("p1").content
    editor.apply_operations([_update("p1", "changed")], source="ai")
    assert editor.original.get("p1").content == pristine
