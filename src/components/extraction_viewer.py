"""The extracted document, element by element, with inline manual editing."""
from __future__ import annotations

import streamlit as st

from src.models import DocumentElement, ElementType
from src.services.document_editor import DocumentEditor, EditOperation, EditError

_TYPE_ICONS = {
    ElementType.TITLE: ":material/title:",
    ElementType.HEADING: ":material/format_h2:",
    ElementType.PARAGRAPH: ":material/notes:",
    ElementType.LIST: ":material/format_list_bulleted:",
    ElementType.TABLE: ":material/table:",
    ElementType.IMAGE: ":material/image:",
    ElementType.CAPTION: ":material/closed_caption:",
    ElementType.HEADER: ":material/vertical_align_top:",
    ElementType.FOOTER: ":material/vertical_align_bottom:",
    ElementType.PAGE_NUMBER: ":material/tag:",
}


def _caption(el: DocumentElement) -> str:
    parts = [el.type]
    if el.source:
        parts.append(f"p.{el.source.page}")
    if el.edited:
        parts.append("edited")
    return " · ".join(parts)


def _render_content(el: DocumentElement) -> None:
    if el.type == ElementType.TITLE:
        st.markdown(f"### {el.content}")
    elif el.type == ElementType.HEADING:
        level = min(6, max(1, (el.level or 2)))
        st.markdown(f"{'#' * min(6, level + 3)} {el.content}")
    elif el.type in (ElementType.IMAGE, ElementType.CHART, ElementType.DIAGRAM):
        st.markdown(f"> {el.content}")
    elif el.type == ElementType.CAPTION:
        st.markdown(f"*{el.content}*")
    else:
        st.markdown(el.content)


def _manual_editor(el: DocumentElement, editor: DocumentEditor) -> None:
    with st.expander(":material/edit: Edit"):
        new_content = st.text_area(
            "Content (Markdown)",
            value=el.content,
            key=f"edit_area_{el.id}",
            height=160,
        )
        if st.button(
            "Save",
            key=f"save_edit_{el.id}",
            icon=":material/save:",
            disabled=new_content == el.content,
        ):
            try:
                editor.apply_operations(
                    [EditOperation(op="update", element_id=el.id, content=new_content)],
                    source="manual",
                    instruction="Manual edit",
                    summary=f"Manual edit of {el.type} [{el.id}]",
                )
            except EditError as exc:
                st.error(str(exc))
            else:
                st.rerun()


def render_extraction_viewer(editor: DocumentEditor) -> None:
    """Render the extracted document; each element is editable in place."""
    document = editor.document

    shown = 0
    for el in document.elements:
        if el.is_furniture:
            continue
        shown += 1
        with st.container(border=True):
            st.caption(
                f"{_TYPE_ICONS.get(el.type, ':material/notes:')} {_caption(el)}"
            )
            _render_content(el)
            _manual_editor(el, editor)
    if shown == 0:
        st.info("No content was extracted from this document.")
