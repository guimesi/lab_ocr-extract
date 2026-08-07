"""
PDF Extraction Editor - Streamlit app.

Upload a PDF -> the pipeline extracts its full content (native text,
layout, tables) into structured elements with source references ->
review the original PDF and the extraction side by side (click an
element to highlight its source region) -> edit the content by hand ->
download the result as Markdown, JSON or HTML.

Run: streamlit run app.py
"""
from __future__ import annotations

import logging

import streamlit as st

from config.settings import SETTINGS
from src.components import (
    export_panel,
    extraction_viewer,
    pdf_viewer,
    revision_history,
)
from src.services import pdf_processor
from src.services.document_editor import DocumentEditor
from src.utils import state_utils
from src.utils.file_utils import content_hash
from src.utils.validation import ValidationError, validate_pdf_upload

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s - %(message)s",
)

st.set_page_config(
    page_title="PDF Extraction Editor",
    page_icon=":material/edit_document:",
    layout="wide",
)

state_utils.init_state()


# =============================================================================
# Sidebar
# =============================================================================

with st.sidebar:
    st.title(":material/edit_document: PDF Extraction Editor")
    st.caption(
        "Extract a PDF into structured, source-mapped content; review it "
        "next to the original, edit it by hand, and export "
        "Markdown / JSON / HTML."
    )
    st.caption(
        "Everything runs locally: uploads are processed in memory only and "
        "nothing is sent to external services or stored on disk. Pages "
        "without native text (scanned images) are marked as not extracted."
    )


# =============================================================================
# 1. Upload & validation
# =============================================================================

upload = st.file_uploader(
    "Upload a PDF document",
    type=["pdf"],
    accept_multiple_files=False,
)

if upload is None:
    state_utils.reset_document_state()
    st.info(
        "Upload a PDF to get started. The full content is extracted with "
        "source references, so every passage can be traced back to its "
        "exact location in the original file.",
        icon=":material/upload_file:",
    )
    st.stop()

file_bytes = upload.getvalue()
doc_hash = content_hash(file_bytes)

try:
    real_page_count = validate_pdf_upload(
        file_bytes, upload.name, SETTINGS.max_upload_mb
    )
except ValidationError as exc:
    state_utils.reset_document_state()
    st.error(str(exc), icon=":material/error:")
    st.stop()

# A different file replaces the previous document and history.
if st.session_state.doc_hash not in (None, doc_hash):
    state_utils.reset_document_state()


# =============================================================================
# 2. Processing (once per file content - reruns reuse the session copy)
# =============================================================================

if st.session_state.doc_hash != doc_hash:
    st.caption(
        f'"{upload.name}" - {real_page_count} page(s), '
        f"{len(file_bytes) / (1024 * 1024):.1f} MB. Not processed yet."
    )
    if not st.button(
        "Process document", type="primary", icon=":material/manage_search:"
    ):
        st.stop()
    bar = st.progress(0.0, text="Queueing...")
    try:
        document = pdf_processor.process_pdf(
            file_bytes,
            upload.name,
            progress=lambda label, fraction: bar.progress(fraction, text=label),
        )
    except pdf_processor.ProcessingError as exc:
        bar.empty()
        st.error(f"Extraction failed: {exc}", icon=":material/error:")
        st.stop()
    except Exception as exc:  # never crash the app on unexpected errors
        bar.empty()
        logging.getLogger(__name__).exception("Unexpected processing failure")
        st.error(f"Unexpected error during extraction: {exc}", icon=":material/error:")
        st.stop()
    bar.empty()
    st.session_state.doc_hash = doc_hash
    st.session_state.pdf_bytes = file_bytes
    st.session_state.editor = DocumentEditor(document)
    st.session_state.processing_warnings = list(document.warnings)
    st.rerun()

editor: DocumentEditor = st.session_state.editor
document = editor.document


# =============================================================================
# 3. Status line + warnings
# =============================================================================

if st.session_state.processing_warnings:
    with st.expander(
        f":material/warning: Extraction completed with "
        f"{len(st.session_state.processing_warnings)} warning(s)",
        expanded=False,
    ):
        for warning in st.session_state.processing_warnings:
            st.warning(warning, icon=":material/error:")

meta = document.metadata
st.caption(
    f'"{document.file_name}" - {document.page_count} page(s) '
    f"({meta.get('native_pages', '?')} native, "
    f"{meta.get('scanned_pages', '?')} scanned), "
    f"{len(document.elements)} element(s) extracted"
    + (f", language: {document.language}" if document.language else "")
    + f". Processed at {document.processed_at}."
)


# =============================================================================
# 4. Side-by-side: original PDF | extraction / history / export
# =============================================================================

left, right = st.columns([1, 1], gap="medium")

with left:
    st.subheader(":material/picture_as_pdf: Original PDF", divider="gray")
    pdf_viewer.render_pdf_viewer(
        st.session_state.pdf_bytes, document, real_page_count
    )

with right:
    doc_tab, history_tab, export_tab = st.tabs(
        [
            ":material/article: Document",
            ":material/history: History",
            ":material/download: Export",
        ]
    )
    with doc_tab:
        extraction_viewer.render_extraction_viewer(editor)
    with history_tab:
        revision_history.render_revision_history(editor)
    with export_tab:
        export_panel.render_export_panel(editor)
