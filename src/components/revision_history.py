"""Revision history panel: undo / redo / restore and per-revision diffs."""
from __future__ import annotations

import difflib

import streamlit as st

from src.services.document_editor import DocumentEditor

_SOURCE_LABELS = {
    "manual": ":material/person: Manual edit",
    "restore": ":material/history: Restore",
}


def _change_diff(before: dict | None, after: dict | None) -> str:
    before_text = (before or {}).get("content", "") or ""
    after_text = (after or {}).get("content", "") or ""
    diff = difflib.unified_diff(
        before_text.splitlines(),
        after_text.splitlines(),
        fromfile="before",
        tofile="after",
        lineterm="",
    )
    return "\n".join(diff)


def render_revision_history(editor: DocumentEditor) -> None:
    undo_col, redo_col, restore_col = st.columns(3)
    with undo_col:
        if st.button(
            "Undo",
            icon=":material/undo:",
            disabled=not editor.can_undo,
            width="stretch",
        ):
            editor.undo()
            st.rerun()
    with redo_col:
        if st.button(
            "Redo",
            icon=":material/redo:",
            disabled=not editor.can_redo,
            width="stretch",
        ):
            editor.redo()
            st.rerun()
    with restore_col:
        if st.button(
            "Restore original",
            icon=":material/restore_page:",
            disabled=not (editor.can_undo or editor.can_redo),
            width="stretch",
            help=(
                "Reset the document to the pristine extraction. "
                "Clears the revision history."
            ),
        ):
            editor.restore_original()
            st.session_state.selected_element_id = None
            st.rerun()

    history = editor.history
    if not history:
        st.info(
            "No changes yet - edits from the Document tab will appear "
            "here.",
            icon=":material/history:",
        )
        return

    st.caption(
        f"{len(history)} applied revision(s), newest first. The original "
        "extraction is never overwritten."
    )
    for revision in reversed(history):
        label = _SOURCE_LABELS.get(revision.source, revision.source)
        title = f"{label} - {revision.summary or 'change'}"
        with st.expander(f"{title}  ·  {revision.timestamp}"):
            st.caption(f"Revision `{revision.id}`")
            if revision.instruction:
                st.markdown(f"**Instruction:** {revision.instruction}")
            for change in revision.changes:
                st.markdown(f"`{change.element_id}` - {change.op}")
                diff = _change_diff(change.before, change.after)
                if diff:
                    st.code(diff, language="diff")
