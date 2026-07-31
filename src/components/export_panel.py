"""Export panel: download the current document as Markdown, JSON or HTML."""
from __future__ import annotations

import logging

import streamlit as st

from src.services import export_service
from src.services.document_editor import DocumentEditor
from src.utils.file_utils import safe_stem

logger = logging.getLogger(__name__)


def render_export_panel(editor: DocumentEditor) -> None:
    document = editor.document
    stem = safe_stem(document.file_name)

    include_furniture = st.toggle(
        "Include headers, footers and page numbers",
        value=False,
        key="export_furniture",
    )

    edited = sum(1 for el in document.elements if el.edited)
    st.caption(
        f"Exports reflect the current edited document "
        f"({len(document.elements)} element(s), {edited} edited). "
        "The JSON export also carries source references and the full "
        "revision history."
    )

    try:
        markdown_data = export_service.to_markdown(
            document, include_furniture=include_furniture
        ).encode("utf-8")
        json_data = export_service.to_json(
            document, editor.revision_history_dicts()
        ).encode("utf-8")
        html_data = export_service.to_html(
            document, include_furniture=include_furniture
        ).encode("utf-8")
    except Exception as exc:
        logger.exception("Export generation failed")
        st.error(f"Could not generate the exports: {exc}")
        return

    md_col, json_col, html_col = st.columns(3)
    with md_col:
        st.download_button(
            "Markdown (.md)",
            markdown_data,
            f"{stem}.md",
            "text/markdown",
            icon=":material/markdown:",
            width="stretch",
        )
    with json_col:
        st.download_button(
            "JSON (.json)",
            json_data,
            f"{stem}.json",
            "application/json",
            icon=":material/data_object:",
            width="stretch",
        )
    with html_col:
        st.download_button(
            "HTML (.html)",
            html_data,
            f"{stem}.html",
            "text/html",
            icon=":material/html:",
            width="stretch",
        )

    with st.expander("Preview (Markdown)"):
        st.markdown(markdown_data.decode("utf-8"))
