"""Chat protocol: context assembly and answer/edit parsing."""
import json

from src.services import chat_service


def test_plain_answer_passthrough(sample_document):
    result = chat_service.parse_chat_response(
        "The table lists two columns, A and B.", sample_document
    )
    assert result.kind == "answer"
    assert "two columns" in result.text
    assert result.operations == []


def test_edit_payload_parsed(sample_document):
    reply = json.dumps(
        {
            "action": "edit",
            "summary": "Fix the intro paragraph",
            "edits": [
                {"op": "update", "element_id": "p1", "content": "Better text."},
                {
                    "op": "insert_after",
                    "element_id": "h1",
                    "type": "paragraph",
                    "content": "New paragraph.",
                },
            ],
        }
    )
    result = chat_service.parse_chat_response(reply, sample_document)
    assert result.kind == "edit"
    assert result.text == "Fix the intro paragraph"
    assert len(result.operations) == 2
    assert result.operations[0].op == "update"
    assert result.operations[1].element_type == "paragraph"


def test_edit_payload_in_fenced_block(sample_document):
    reply = (
        "```json\n"
        + json.dumps(
            {
                "action": "edit",
                "summary": "s",
                "edits": [{"op": "delete", "element_id": "l1"}],
            }
        )
        + "\n```"
    )
    result = chat_service.parse_chat_response(reply, sample_document)
    assert result.kind == "edit"
    assert result.operations[0].op == "delete"


def test_invalid_ids_reported_not_applied(sample_document):
    reply = json.dumps(
        {
            "action": "edit",
            "summary": "s",
            "edits": [
                {"op": "update", "element_id": "ghost", "content": "x"},
                {"op": "update", "element_id": "p1", "content": "ok"},
            ],
        }
    )
    result = chat_service.parse_chat_response(reply, sample_document)
    assert result.kind == "edit"
    assert len(result.operations) == 1
    assert result.errors and "ghost" in result.errors[0]


def test_all_invalid_edits_become_answer(sample_document):
    reply = json.dumps(
        {
            "action": "edit",
            "summary": "s",
            "edits": [{"op": "update", "element_id": "ghost", "content": "x"}],
        }
    )
    result = chat_service.parse_chat_response(reply, sample_document)
    assert result.kind == "answer"
    assert "ghost" in result.text


def test_needs_confirmation_rules(sample_document):
    from src.services.document_editor import EditOperation

    update = EditOperation(op="update", element_id="p1", content="x")
    delete = EditOperation(op="delete", element_id="p1")
    assert not chat_service.needs_confirmation([update])
    assert chat_service.needs_confirmation([delete])
    assert chat_service.needs_confirmation([update] * 4)


def test_context_includes_ids_and_selection(sample_document):
    context = chat_service.build_document_context(sample_document, "p1", 100000)
    assert "[p1]" in context and "[tb1]" in context
    assert "currently has element [p1] selected" in context


def test_context_degrades_to_outline_when_over_budget(sample_document):
    sample_document.get("p1").content = "x" * 5000
    context = chat_service.build_document_context(sample_document, "tb1", 2000)
    assert "outline" in context.lower()
    assert "[h1]" in context  # headings survive in the outline
    assert "x" * 5000 not in context


def test_api_messages_shape(sample_document):
    history = [{"role": "user", "content": "hello"}]
    messages = chat_service.build_api_messages(sample_document, None, history, 100000)
    assert messages[0]["role"] == "user"
    assert "sample.pdf" in messages[0]["content"]
    assert messages[1]["role"] == "assistant"
    assert messages[-1] == {"role": "user", "content": "hello"}
