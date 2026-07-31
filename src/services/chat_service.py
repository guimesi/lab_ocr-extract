"""AI chat over the extracted document, including document edits.

The model sees the current (edited) document with element ids and must
choose between two response modes:

* **answer** - plain Markdown prose for questions/explanations;
* **edit** - a single JSON object describing element-level operations,
  which the app converts to :class:`EditOperation` and applies through
  the :class:`DocumentEditor` (after user confirmation for broad or
  destructive changes).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

from src.models import ExtractedDocument
from src.services import llm_support
from src.services.document_editor import EditOperation

logger = logging.getLogger(__name__)

CHAT_SYSTEM_PROMPT = (
    "You are a document-editing assistant for a PDF extraction review "
    "tool. The user has extracted a PDF into a structured document; you "
    "receive that document with a unique id per element (in brackets, "
    'like "[a1b2c3d4]"), plus the conversation. Elements keep a '
    "reference to their page in the original PDF.\n\n"
    "You have TWO response modes and must pick exactly one per reply:\n\n"
    "1. ANSWER mode - the user asks a question, wants an explanation, a "
    "summary to read (not to insert), or a comparison. Reply in plain "
    "Markdown prose. Do NOT output JSON.\n\n"
    "2. EDIT mode - the user asks to change the document (correct, "
    "rewrite, reformat, translate, reorganize, add or remove content). "
    "Reply with ONLY a JSON object, no prose around it:\n"
    '{"action": "edit",\n'
    ' "summary": "<one sentence describing the change>",\n'
    ' "edits": [\n'
    '   {"op": "update", "element_id": "<id>", "content": "<full new '
    'Markdown content for that element>"},\n'
    '   {"op": "insert_after", "element_id": "<anchor id>", "type": '
    '"<paragraph|heading|list|table|caption>", "level": <1-6, headings '
    'only>, "content": "<Markdown content>"},\n'
    '   {"op": "insert_before", "element_id": "<anchor id>", "type": '
    '"...", "content": "..."},\n'
    '   {"op": "delete", "element_id": "<id>"}\n'
    " ]}\n\n"
    "EDIT mode rules:\n"
    "- Use only element ids that exist in the document context; never "
    "invent ids.\n"
    '- "update" content REPLACES the whole element content - include '
    "the complete new text, not a diff.\n"
    "- Tables are GitHub Markdown tables; keep them as one element.\n"
    '- When the user says "this ..." they mean the currently selected '
    "element noted in the context.\n"
    "- Scope edits to exactly what was asked: selected element, a "
    "section, or the whole document.\n"
    "- Stay faithful to the source: when correcting extraction errors, "
    "prefer what the original PDF plausibly says; never invent facts.\n"
    "- If the request is ambiguous about scope or content, use ANSWER "
    "mode to ask for clarification instead of guessing.\n\n"
    "Respond in English unless the user writes in another language - "
    "then answer in that language."
)


@dataclass
class ChatResult:
    """Parsed model reply: either an answer or a set of edit operations."""

    kind: str  # "answer" | "edit"
    text: str  # answer prose, or the edit summary
    operations: list = field(default_factory=list)  # list[EditOperation]
    errors: list = field(default_factory=list)  # invalid ops, for display


# ----------------------------------------------------------------------
# Context assembly
# ----------------------------------------------------------------------

def _element_line(el) -> str:
    flags = []
    if el.is_furniture:
        flags.append(el.type)
    if el.edited_by:
        flags.append(f"edited:{el.edited_by}")
    suffix = f" ({', '.join(flags)})" if flags else ""
    page = el.source.page if el.source else "?"
    level = f" h{el.level}" if el.level else ""
    return f"[{el.id}] {el.type}{level}, p.{page}{suffix}:\n{el.content}"


def _outline_line(el) -> str:
    indent = "  " * max(0, (el.level or 1) - 1)
    page = el.source.page if el.source else "?"
    return f"{indent}- [{el.id}] {el.content} (p.{page})"


def build_document_context(
    document: ExtractedDocument,
    selected_id: Optional[str],
    budget_chars: int,
) -> str:
    """The document context block for the first (synthetic) user turn.

    Small documents are included in full. When the full listing exceeds
    ``budget_chars``, the context degrades to the outline plus the full
    content of the section containing the selected element, so requests
    stay bounded for very large documents.
    """
    header = (
        f'Extracted document "{document.file_name}" - '
        f"{document.page_count} page(s)"
        + (f", language: {document.language}" if document.language else "")
        + ". Elements follow, each with its id in brackets.\n"
    )
    lines = [_element_line(el) for el in document.elements]
    full = header + "\n\n".join(lines)
    if len(full) <= budget_chars:
        context = full
    else:
        context = _sectioned_context(document, selected_id, budget_chars, header)
    if selected_id and document.get(selected_id):
        context += (
            f"\n\nThe user currently has element [{selected_id}] selected."
        )
    else:
        context += "\n\nThe user has no element selected."
    return context


def _sectioned_context(
    document: ExtractedDocument,
    selected_id: Optional[str],
    budget_chars: int,
    header: str,
) -> str:
    from src.models.document_element import ElementType

    outline = [
        _outline_line(el)
        for el in document.elements
        if el.type in (ElementType.TITLE, ElementType.HEADING)
    ]
    parts = [
        header,
        "The document is too large to include in full; here is the "
        "outline (headings with their ids):",
        "\n".join(outline) or "(no headings detected)",
    ]
    selected = document.get(selected_id) if selected_id else None
    if selected is not None:
        section_id = (
            selected.id
            if selected.type in (ElementType.TITLE, ElementType.HEADING)
            else selected.parent_id
        )
        section_elements = [
            el
            for el in document.elements
            if el.id == section_id or el.parent_id == section_id
            or el.id == selected.id
        ]
        listing = "\n\n".join(_element_line(el) for el in section_elements)
        parts.append(
            "Full content of the section containing the selected element:"
        )
        parts.append(listing[: max(1000, budget_chars // 2)])
    parts.append(
        "To edit elements not listed here, ask the user to select an "
        "element in that section first."
    )
    return "\n\n".join(parts)


def build_api_messages(
    document: ExtractedDocument,
    selected_id: Optional[str],
    visible_history: list,
    budget_chars: int,
) -> list:
    """Assemble the message list for one chat completion call.

    The document context travels as a synthetic first user turn (plus a
    canned acknowledgment), then the visible conversation. The context
    is rebuilt every turn so it always reflects the *current* edited
    document.
    """
    context = build_document_context(document, selected_id, budget_chars)
    return [
        {"role": "user", "content": context},
        {
            "role": "assistant",
            "content": (
                "Understood. I have the extracted document and will "
                "answer questions or produce edit JSON as appropriate."
            ),
        },
        *[
            {"role": m["role"], "content": str(m["content"])}
            for m in visible_history
        ],
    ]


# ----------------------------------------------------------------------
# Calling the model + parsing the reply
# ----------------------------------------------------------------------

def send_chat(
    document: ExtractedDocument,
    selected_id: Optional[str],
    visible_history: list,
    budget_chars: int,
) -> ChatResult:
    """One chat turn: call the model and parse its reply."""
    messages = build_api_messages(
        document, selected_id, visible_history, budget_chars
    )
    text, truncated = llm_support.complete_with_retry(
        messages, system=CHAT_SYSTEM_PROMPT
    )
    result = parse_chat_response(text, document)
    if truncated and result.kind == "answer":
        result.text += (
            "\n\n*[The reply hit the output-token limit and may be "
            "incomplete.]*"
        )
    return result


def parse_chat_response(text: str, document: ExtractedDocument) -> ChatResult:
    """Classify the reply as answer vs edit and validate edit payloads."""
    stripped = text.strip()
    if '"action"' not in stripped or '"edits"' not in stripped:
        return ChatResult(kind="answer", text=stripped)
    try:
        payload = llm_support.parse_json_payload(stripped)
    except ValueError:
        logger.warning("Reply looked like an edit but did not parse as JSON.")
        return ChatResult(kind="answer", text=stripped)
    if not isinstance(payload, dict) or payload.get("action") != "edit":
        return ChatResult(kind="answer", text=stripped)

    operations, errors = operations_from_payload(payload, document)
    summary = str(payload.get("summary", "")).strip() or "Apply requested changes"
    if not operations:
        return ChatResult(
            kind="answer",
            text=(
                "The model proposed changes but none were valid:\n- "
                + "\n- ".join(errors or ["empty edit list"])
            ),
        )
    return ChatResult(
        kind="edit", text=summary, operations=operations, errors=errors
    )


def operations_from_payload(
    payload: dict, document: ExtractedDocument
) -> tuple[list, list]:
    """Convert the model's edit JSON to validated EditOperations."""
    operations: list[EditOperation] = []
    errors: list[str] = []
    edits = payload.get("edits")
    if not isinstance(edits, list):
        return [], ["'edits' is not a list"]
    for i, edit in enumerate(edits):
        if not isinstance(edit, dict):
            errors.append(f"edit #{i + 1} is not an object")
            continue
        op = str(edit.get("op", "")).strip()
        element_id = str(edit.get("element_id", "")).strip()
        if op not in EditOperation.VALID_OPS:
            errors.append(f'edit #{i + 1}: unknown op "{op}"')
            continue
        if document.get(element_id) is None:
            errors.append(f'edit #{i + 1}: unknown element id "{element_id}"')
            continue
        content = edit.get("content")
        if op != "delete" and not isinstance(content, str):
            errors.append(f"edit #{i + 1}: missing content")
            continue
        level = edit.get("level")
        operations.append(
            EditOperation(
                op=op,
                element_id=element_id,
                content=content if isinstance(content, str) else None,
                element_type=str(edit.get("type", "paragraph")).strip()
                or "paragraph",
                level=int(level) if isinstance(level, (int, float)) else None,
            )
        )
    return operations, errors


def needs_confirmation(operations: list) -> bool:
    """Broad or destructive changes require an explicit user confirmation."""
    return any(op.op == "delete" for op in operations) or len(operations) > 3
