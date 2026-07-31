"""AI chat panel: questions, edit requests, and edit confirmation.

Answer-type replies go straight into the visible history. Edit-type
replies are converted to operations; small, non-destructive edits apply
immediately, while broad or destructive ones park in
``st.session_state.pending_edit`` until the user confirms - the pending
panel shows exactly what will change before anything is touched.
"""
from __future__ import annotations

import logging

import streamlit as st

from config.settings import SETTINGS
from src.services import chat_service
from src.services.document_editor import DocumentEditor, EditError

logger = logging.getLogger(__name__)

_PREVIEW_CHARS = 400


def _shorten(text: str) -> str:
    text = text.strip()
    return text if len(text) <= _PREVIEW_CHARS else text[:_PREVIEW_CHARS] + " …"


def _render_edit_preview(operations: list, editor: DocumentEditor) -> None:
    for op in operations:
        element = editor.document.get(op.element_id)
        current = element.content if element else "(missing)"
        if op.op == "update":
            st.markdown(f"**Update** `{op.element_id}`")
            before_col, after_col = st.columns(2)
            with before_col:
                st.caption("Current")
                st.markdown(_shorten(current))
            with after_col:
                st.caption("Proposed")
                st.markdown(_shorten(op.content or ""))
        elif op.op in ("insert_after", "insert_before"):
            where = "after" if op.op == "insert_after" else "before"
            st.markdown(
                f"**Insert** new {op.element_type} {where} `{op.element_id}`"
            )
            st.markdown(_shorten(op.content or ""))
        elif op.op == "delete":
            st.markdown(f"**Delete** `{op.element_id}`")
            st.caption("Content being removed")
            st.markdown(_shorten(current))
        st.divider()


def _apply(operations: list, editor: DocumentEditor, instruction: str, summary: str) -> None:
    try:
        revision = editor.apply_operations(
            operations, source="ai", instruction=instruction, summary=summary
        )
    except EditError as exc:
        st.session_state.chat_messages.append(
            {
                "role": "assistant",
                "content": f"I could not apply the changes: {exc}",
            }
        )
    else:
        st.session_state.chat_messages.append(
            {
                "role": "assistant",
                "content": (
                    f":material/edit_document: **Applied:** {summary} "
                    f"(revision `{revision.id}`, "
                    f"{len(revision.changes)} change(s) - undo available in "
                    "the History tab)."
                ),
            }
        )


def _render_pending_edit(editor: DocumentEditor) -> None:
    pending = st.session_state.pending_edit
    if not pending:
        return
    with st.container(border=True):
        st.markdown(
            ":material/warning: **This change needs your confirmation** - "
            f"{pending['summary']}"
        )
        st.caption(
            f"{len(pending['operations'])} operation(s); deletions and "
            "broad edits always ask before touching the document."
        )
        _render_edit_preview(pending["operations"], editor)
        if pending.get("errors"):
            st.warning(
                "Some proposed operations were invalid and will be "
                "skipped:\n- " + "\n- ".join(pending["errors"])
            )
        apply_col, discard_col = st.columns(2)
        with apply_col:
            if st.button(
                "Apply changes", type="primary", icon=":material/check:"
            ):
                _apply(
                    pending["operations"],
                    editor,
                    pending["instruction"],
                    pending["summary"],
                )
                st.session_state.pending_edit = None
                st.rerun()
        with discard_col:
            if st.button("Discard", icon=":material/close:"):
                st.session_state.pending_edit = None
                st.session_state.chat_messages.append(
                    {
                        "role": "assistant",
                        "content": "Changes discarded - nothing was modified.",
                    }
                )
                st.rerun()


def render_chat_panel(editor: DocumentEditor) -> None:
    if not SETTINGS.databricks_enabled:
        st.error(
            "The chat needs the model connection. Set DATABRICKS_HOST and "
            "DATABRICKS_TOKEN in `.env` (see `.env.example`).",
            icon=":material/cloud_off:",
        )
        return

    selected_id = st.session_state.selected_element_id
    element = editor.document.get(selected_id) if selected_id else None
    if element is not None:
        st.caption(
            f"Selected: {element.type} `[{element.id}]` on page "
            f"{element.source.page if element.source else '?'} - "
            '"this paragraph/table/section" in your messages refers to it.'
        )
    else:
        st.caption(
            "No element selected - select one in the Document tab to "
            "target it with instructions like \"rewrite this paragraph\"."
        )

    for message in st.session_state.chat_messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    _render_pending_edit(editor)

    prompt = st.chat_input(
        "Ask about the document, or request a change "
        "(e.g. 'fix the typos in this paragraph')...",
        disabled=st.session_state.pending_edit is not None,
    )
    if not prompt:
        return

    st.session_state.chat_messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        with st.spinner("Thinking..."):
            try:
                result = chat_service.send_chat(
                    editor.document,
                    selected_id,
                    st.session_state.chat_messages,
                    SETTINGS.chat_context_chars,
                )
            except Exception as exc:
                logger.exception("Chat call failed")
                st.session_state.chat_messages.pop()
                st.error(f"The model call failed: {exc}")
                st.stop()

    if result.kind == "answer":
        st.session_state.chat_messages.append(
            {"role": "assistant", "content": result.text}
        )
        st.rerun()

    # Edit-type reply.
    if chat_service.needs_confirmation(result.operations):
        st.session_state.pending_edit = {
            "summary": result.text,
            "operations": result.operations,
            "errors": result.errors,
            "instruction": prompt,
        }
    else:
        if result.errors:
            st.session_state.chat_messages.append(
                {
                    "role": "assistant",
                    "content": (
                        "Some proposed operations were invalid and were "
                        "skipped:\n- " + "\n- ".join(result.errors)
                    ),
                }
            )
        _apply(result.operations, editor, prompt, result.text)
    st.rerun()
