"""Session-state bookkeeping for the Streamlit app.

All mutable app state lives in ``st.session_state`` under these keys so
Streamlit reruns never recompute the extraction or lose edits.
"""
from __future__ import annotations

import streamlit as st

STATE_DEFAULTS = {
    "doc_hash": None,          # content hash of the processed upload
    "editor": None,            # DocumentEditor for the current document
    "pdf_bytes": None,         # raw bytes of the processed PDF
    "selected_element_id": None,
    "viewer_page": 1,
    "viewer_zoom": 1.5,
    "viewer_synced_id": None,  # last element the viewer auto-navigated to
    "processing_warnings": [],
}


def init_state() -> None:
    for key, default in STATE_DEFAULTS.items():
        st.session_state.setdefault(key, default)


def reset_document_state() -> None:
    """Drop everything tied to the current document (new upload)."""
    st.session_state.doc_hash = None
    st.session_state.editor = None
    st.session_state.pdf_bytes = None
    st.session_state.selected_element_id = None
    st.session_state.viewer_page = 1
    st.session_state.viewer_synced_id = None
    st.session_state.processing_warnings = []


def select_element(element_id: str) -> None:
    st.session_state.selected_element_id = element_id
