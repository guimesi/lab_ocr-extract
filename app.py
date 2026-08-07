"""
PDF Extraction Editor - Streamlit app.

Upload a PDF -> the content is extracted locally (native text, layout,
tables) into structured elements -> edit any element in place -> export
as Markdown, JSON or HTML. No LLM, no external services.

Run: streamlit run app.py
"""
from __future__ import annotations

import logging

import streamlit as st

from config.settings import SETTINGS
from src.components import export_panel, extraction_viewer
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
    layout="centered",
)

state_utils.init_state()

st.title(":material/edit_document: PDF Extraction Editor")
st.caption("Upload a PDF, review and edit the extracted content, export it.")


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
    st.info("Upload a PDF to get started.", icon=":material/upload_file:")
    st.stop()

file_bytes = upload.getvalue()
doc_hash = content_hash(file_bytes)

try:
    validate_pdf_upload(file_bytes, upload.name, SETTINGS.max_upload_mb)
except ValidationError as exc:
    state_utils.reset_document_state()
    st.error(str(exc), icon=":material/error:")
    st.stop()

# A different file replaces the previous document and its edits.
if st.session_state.doc_hash not in (None, doc_hash):
    state_utils.reset_document_state()


# =============================================================================
# 2. Extraction (once per file content - reruns reuse the session copy)
# =============================================================================

if st.session_state.doc_hash != doc_hash:
    bar = st.progress(0.0, text="Reading PDF...")
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
    st.session_state.editor = DocumentEditor(document)
    st.session_state.processing_warnings = list(document.warnings)

editor: DocumentEditor = st.session_state.editor
document = editor.document

for warning in st.session_state.processing_warnings:
    st.warning(warning, icon=":material/warning:")


# =============================================================================
# 3. Extracted content with inline editing
# =============================================================================

st.subheader(":material/article: Extracted content", divider="gray")
st.caption(
    f'"{document.file_name}" - {document.page_count} page(s), '
    f"{len(document.elements)} element(s) extracted."
)
extraction_viewer.render_extraction_viewer(editor)


# =============================================================================
# 4. Export
# =============================================================================

st.subheader(":material/download: Export", divider="gray")
export_panel.render_export_panel(editor)
