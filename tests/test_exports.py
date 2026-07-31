"""Markdown / JSON / HTML export correctness and safety."""
import json

from src.services import export_service
from src.services.document_editor import DocumentEditor, EditOperation


def test_markdown_structure(sample_document):
    md = export_service.to_markdown(sample_document)
    assert "# Report Title" in md
    assert "## Introduction" in md
    assert "- alpha" in md
    assert "| A | B |" in md
    assert "**Image (page 2):**" in md
    # furniture excluded by default
    assert "Confidential" not in md


def test_markdown_can_include_furniture(sample_document):
    md = export_service.to_markdown(sample_document, include_furniture=True)
    assert "Confidential" in md


def test_json_schema(sample_document):
    editor = DocumentEditor(sample_document.copy())
    editor.apply_operations(
        [EditOperation(op="update", element_id="p1", content="edited text")],
        source="ai",
        instruction="fix it",
    )
    payload = json.loads(
        export_service.to_json(editor.document, editor.revision_history_dicts())
    )
    assert payload["document"]["file_name"] == "sample.pdf"
    assert payload["document"]["page_count"] == 2

    by_id = {item["id"]: item for item in payload["content"]}
    p1 = by_id["p1"]
    assert p1["revision"]["edited"] is True
    assert p1["revision"]["edited_by"] == "ai"
    assert p1["revision"]["original_content"].startswith("Hello")
    assert p1["source"]["page"] == 1
    assert set(p1["source"]["bounding_box"]) == {"x", "y", "width", "height"}
    assert by_id["tb1"]["table_data"] == [["A", "B"], ["1", "2"]]

    history = payload["revision_history"]
    assert len(history) == 1
    assert history[0]["source"] == "ai"
    assert history[0]["instruction"] == "fix it"
    assert history[0]["affected_element_ids"] == ["p1"]


def test_html_is_escaped_and_structured(sample_document):
    html_out = export_service.to_html(sample_document)
    assert html_out.startswith("<!DOCTYPE html>")
    assert "<script>" not in html_out  # injected content is escaped
    assert "&lt;script&gt;" in html_out
    assert "<h1>Report Title</h1>" in html_out
    assert "<h2>Introduction</h2>" in html_out
    assert "<th>A</th>" in html_out and "<td>1</td>" in html_out
    assert "<li>alpha</li>" in html_out
    assert "<style>" in html_out


def test_html_table_from_markdown_content(sample_document):
    table = sample_document.get("tb1")
    table.table_data = None  # e.g. an OCR table only has Markdown
    html_out = export_service.to_html(sample_document)
    assert "<th>A</th>" in html_out and "<td>2</td>" in html_out


def test_exports_reflect_edits(sample_document):
    editor = DocumentEditor(sample_document.copy())
    editor.apply_operations(
        [EditOperation(op="update", element_id="p1", content="Rewritten.")],
        source="manual",
    )
    assert "Rewritten." in export_service.to_markdown(editor.document)
    assert "Rewritten." in export_service.to_html(editor.document)
