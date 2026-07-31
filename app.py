"""
PDF Extraction Editor - Streamlit app.

Upload a PDF -> the pipeline extracts its full content (native text,
layout, tables, OCR for scanned pages, AI descriptions for visuals) into
structured elements with source references -> review the original PDF
and the extraction side by side (click an element to highlight its
source region) -> chat with the AI to answer questions or apply edits ->
download the result as Markdown, JSON or HTML.

Run: streamlit run app.py
"""
from __future__ import annotations

import logging

import streamlit as st

from config.settings import SETTINGS
from src.components import (
    chat_panel,
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
# Sidebar: status + processing options
# =============================================================================

with st.sidebar:
    st.title(":material/edit_document: PDF Extraction Editor")
    st.caption(
        "Extract a PDF into structured, source-mapped content; review it "
        "next to the original, edit it via AI chat or by hand, and export "
        "Markdown / JSON / HTML."
    )

    if SETTINGS.databricks_enabled:
        st.success(
            f"Model: `{SETTINGS.databricks_model}`",
            icon=":material/cloud_done:",
        )
    else:
        st.error(
            "Databricks is not configured - OCR, visual descriptions and "
            "chat are unavailable. Set DATABRICKS_HOST and DATABRICKS_TOKEN "
            "in `.env` (see `.env.example`).",
            icon=":material/cloud_off:",
        )

    st.divider()
    st.subheader("Processing options")
    opt_ocr = st.toggle(
        "OCR scanned pages (AI)",
        value=True,
        disabled=not SETTINGS.databricks_enabled,
        help="Pages without native text are transcribed by the vision model.",
    )
    opt_visuals = st.toggle(
        "Describe images & charts (AI)",
        value=True,
        disabled=not SETTINGS.databricks_enabled,
        help=(
            "Embedded pictures, charts and diagrams get an AI-generated "
            f"description (up to {SETTINGS.max_image_descriptions} per "
            "document, MAX_IMAGE_DESCRIPTIONS)."
        ),
    )
    st.caption(
        "Uploads are processed in memory only; pages sent for OCR, visual "
        "descriptions and chat context go to the configured Databricks "
        "model endpoint. Nothing is stored on disk."
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

# A different file replaces the previous document, chat and history.
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
    options = pdf_processor.ProcessingOptions(
        use_llm_ocr=opt_ocr, describe_visuals=opt_visuals
    )
    try:
        document = pdf_processor.process_pdf(
            file_bytes,
            upload.name,
            options=options,
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
    f"{meta.get('ocr_pages', '?')} scanned), "
    f"{len(document.elements)} element(s) extracted"
    + (f", language: {document.language}" if document.language else "")
    + f". Processed at {document.processed_at}."
)


# =============================================================================
# 4. Side-by-side: original PDF | extraction / chat / history / export
# =============================================================================

left, right = st.columns([1, 1], gap="medium")

with left:
    st.subheader(":material/picture_as_pdf: Original PDF", divider="gray")
    pdf_viewer.render_pdf_viewer(
        st.session_state.pdf_bytes, document, real_page_count
    )

with right:
    doc_tab, chat_tab, history_tab, export_tab = st.tabs(
        [
            ":material/article: Document",
            ":material/chat: Chat",
            ":material/history: History",
            ":material/download: Export",
        ]
    )
    with doc_tab:
        extraction_viewer.render_extraction_viewer(editor)
    with chat_tab:
        chat_panel.render_chat_panel(editor)
    with history_tab:
        revision_history.render_revision_history(editor)
    with export_tab:
        export_panel.render_export_panel(editor)
