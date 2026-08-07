"""
PDF Text Extractor - Streamlit app.

Upload a PDF -> its text is extracted locally -> edit it as Markdown in
one text box -> download as Markdown, JSON or HTML. No LLM, no external
services.

Run: streamlit run app.py
"""
from __future__ import annotations

import streamlit as st

from config.settings import SETTINGS
from src import exporters, extractor
from src.file_utils import content_hash, safe_stem
from src.validation import ValidationError, validate_pdf_upload

st.set_page_config(
    page_title="PDF Text Extractor",
    page_icon=":material/edit_document:",
    layout="centered",
)

st.title(":material/edit_document: PDF Text Extractor")
st.caption("Upload a PDF, edit the extracted text, export it.")

# ---------------------------------------------------------------- upload

upload = st.file_uploader("Upload a PDF document", type=["pdf"])

if upload is None:
    st.session_state.pop("doc_hash", None)
    st.session_state.pop("text", None)
    st.info("Upload a PDF to get started.", icon=":material/upload_file:")
    st.stop()

file_bytes = upload.getvalue()
doc_hash = content_hash(file_bytes)

try:
    validate_pdf_upload(file_bytes, upload.name, SETTINGS.max_upload_mb)
except ValidationError as exc:
    st.error(str(exc), icon=":material/error:")
    st.stop()

# ------------------------------------------------------------ extraction
# Runs once per file content; edits live in st.session_state["text"].

if st.session_state.get("doc_hash") != doc_hash:
    try:
        with st.spinner("Extracting text..."):
            text, warnings = extractor.extract_text(file_bytes)
    except extractor.ExtractionError as exc:
        st.error(f"Extraction failed: {exc}", icon=":material/error:")
        st.stop()
    st.session_state.doc_hash = doc_hash
    st.session_state.text = text
    st.session_state.warnings = warnings

for warning in st.session_state.get("warnings", []):
    st.warning(warning, icon=":material/warning:")

# --------------------------------------------------------------- editing

text = st.text_area(
    "Extracted text (Markdown)",
    key="text",
    height=520,
)

with st.expander(":material/preview: Preview"):
    st.markdown(text)

# ---------------------------------------------------------------- export

stem = safe_stem(upload.name)
md_col, json_col, html_col = st.columns(3)
md_col.download_button(
    "Markdown (.md)",
    exporters.to_markdown(text),
    f"{stem}.md",
    "text/markdown",
    icon=":material/markdown:",
    width="stretch",
)
json_col.download_button(
    "JSON (.json)",
    exporters.to_json(upload.name, text),
    f"{stem}.json",
    "application/json",
    icon=":material/data_object:",
    width="stretch",
)
html_col.download_button(
    "HTML (.html)",
    exporters.to_html(upload.name, text),
    f"{stem}.html",
    "text/html",
    icon=":material/html:",
    width="stretch",
)
