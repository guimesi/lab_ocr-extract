"""Right panel: the extracted document, element by element.

Every element renders with a type badge, its provenance (page, method,
confidence, edit status) and a target button that selects it - selection
drives the PDF viewer's navigation + highlight. The selected element can
be edited manually in place.
"""
from __future__ import annotations

import streamlit as st

from src.models import DocumentElement, ElementType
from src.services.document_editor import DocumentEditor, EditOperation, EditError
from src.utils import state_utils

_TYPE_ICONS = {
    ElementType.TITLE: ":material/title:",
    ElementType.HEADING: ":material/format_h2:",
    ElementType.PARAGRAPH: ":material/notes:",
    ElementType.LIST: ":material/format_list_bulleted:",
    ElementType.TABLE: ":material/table:",
    ElementType.IMAGE: ":material/image:",
    ElementType.CHART: ":material/bar_chart:",
    ElementType.DIAGRAM: ":material/schema:",
    ElementType.CAPTION: ":material/closed_caption:",
    ElementType.HEADER: ":material/vertical_align_top:",
    ElementType.FOOTER: ":material/vertical_align_bottom:",
    ElementType.PAGE_NUMBER: ":material/tag:",
}


def _provenance(el: DocumentElement) -> str:
    parts = [el.type]
    if el.source:
        parts.append(f"p.{el.source.page}")
        parts.append(el.source.extraction_method)
        if el.source.confidence is not None:
            parts.append(f"conf {el.source.confidence:.0%}")
    if el.edited_by == "ai":
        parts.append("AI-edited")
    elif el.edited_by == "manual":
        parts.append("manually edited")
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
    """Inline manual editing for the selected element."""
    with st.expander("Edit this element manually"):
        new_content = st.text_area(
            "Content (Markdown)",
            value=el.content,
            key=f"edit_area_{el.id}",
            height=160,
        )
        if st.button(
            "Save manual edit",
            key=f"save_edit_{el.id}",
            icon=":material/save:",
            disabled=new_content == el.content,
        ):
            try:
                editor.apply_operations(
                    [EditOperation(op="update", element_id=el.id, content=new_content)],
                    source="manual",
                    instruction="Manual edit in the extraction panel",
                    summary=f"Manual edit of {el.type} [{el.id}]",
                )
            except EditError as exc:
                st.error(str(exc))
            else:
                st.rerun()


def render_extraction_viewer(editor: DocumentEditor) -> None:
    """Render the full extracted document with selection controls."""
    document = editor.document
    selected_id = st.session_state.selected_element_id

    filter_col, furniture_col = st.columns([2, 2])
    with filter_col:
        pages = sorted(
            {el.source.page for el in document.elements if el.source}
        )
        page_filter = st.selectbox(
            "Filter by page",
            options=["All pages", *pages],
            key="extraction_page_filter",
        )
    with furniture_col:
        show_furniture = st.toggle(
            "Show headers/footers/page numbers",
            value=False,
            key="show_furniture",
        )

    shown = 0
    for el in document.elements:
        if el.is_furniture and not show_furniture:
            continue
        if page_filter != "All pages" and (
            not el.source or el.source.page != page_filter
        ):
            continue
        shown += 1
        is_selected = el.id == selected_id
        with st.container(border=is_selected):
            badge_col, button_col = st.columns([6, 1])
            with badge_col:
                st.caption(
                    f"{_TYPE_ICONS.get(el.type, ':material/notes:')} "
                    + _provenance(el)
                )
            with button_col:
                st.button(
                    ":material/my_location:",
                    key=f"select_{el.id}",
                    help="Select this element and highlight it in the PDF",
                    type="primary" if is_selected else "secondary",
                    on_click=state_utils.select_element,
                    args=(el.id,),
                )
            _render_content(el)
            if is_selected:
                if el.original_content is not None:
                    with st.expander("Original extracted content"):
                        st.markdown(el.original_content)
                _manual_editor(el, editor)
    if shown == 0:
        st.info("No elements to show with the current filters.")
