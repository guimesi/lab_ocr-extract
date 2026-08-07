"""Left panel: PDF page viewer with navigation, zoom and highlighting.

Pages are rendered server-side with PyMuPDF; the highlight rectangle of
the selected element is drawn onto the page image before rasterizing, so
no browser-side PDF machinery is needed. Rendered pages are cached per
(document, page, zoom, highlight) so reruns are cheap.
"""
from __future__ import annotations

from typing import Optional

import streamlit as st

from src.models import ExtractedDocument

_HIGHLIGHT_STROKE = (0.85, 0.1, 0.1)
_HIGHLIGHT_FILL = (1.0, 0.85, 0.2)


@st.cache_data(max_entries=64, show_spinner=False)
def _render_page(
    pdf_bytes: bytes,
    page_number: int,
    zoom: float,
    highlight: Optional[tuple],
) -> bytes:
    """Rasterize one page as PNG, with an optional highlight rectangle."""
    import fitz

    with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
        page = doc.load_page(page_number - 1)
        if highlight:
            rect = fitz.Rect(*highlight) & page.rect
            if not rect.is_empty:
                page.draw_rect(
                    rect,
                    color=_HIGHLIGHT_STROKE,
                    fill=_HIGHLIGHT_FILL,
                    fill_opacity=0.25,
                    width=1.5,
                    overlay=True,
                )
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
        return pix.tobytes("png")


def _sync_to_selection(document: ExtractedDocument, page_count: int) -> None:
    """Navigate to the selected element's page when the selection changes."""
    selected_id = st.session_state.selected_element_id
    if not selected_id or selected_id == st.session_state.viewer_synced_id:
        return
    element = document.get(selected_id)
    if element and element.source:
        st.session_state.viewer_page = min(page_count, max(1, element.source.page))
    st.session_state.viewer_synced_id = selected_id


def render_pdf_viewer(
    pdf_bytes: bytes, document: ExtractedDocument, page_count: int
) -> None:
    """Render the viewer: toolbar, page image with highlight, status line."""
    _sync_to_selection(document, page_count)
    st.session_state.viewer_page = min(
        page_count, max(1, int(st.session_state.viewer_page))
    )

    nav_prev, nav_page, nav_next, nav_zoom = st.columns([1, 2, 1, 3])

    def _go(delta: int) -> None:
        st.session_state.viewer_page = min(
            page_count, max(1, int(st.session_state.viewer_page) + delta)
        )

    with nav_prev:
        st.button(
            ":material/chevron_left:",
            on_click=_go,
            args=(-1,),
            disabled=st.session_state.viewer_page <= 1,
            width="stretch",
        )
    with nav_page:
        st.number_input(
            "Page",
            min_value=1,
            max_value=page_count,
            key="viewer_page",
            label_visibility="collapsed",
        )
    with nav_next:
        st.button(
            ":material/chevron_right:",
            on_click=_go,
            args=(1,),
            disabled=st.session_state.viewer_page >= page_count,
            width="stretch",
        )
    with nav_zoom:
        st.slider(
            "Zoom",
            min_value=0.75,
            max_value=3.0,
            step=0.25,
            key="viewer_zoom",
            label_visibility="collapsed",
        )

    page_number = int(st.session_state.viewer_page)
    highlight = None
    selected_id = st.session_state.selected_element_id
    element = document.get(selected_id) if selected_id else None
    if element and element.source and element.source.page == page_number:
        box = element.source.bounding_box
        if box:
            highlight = (box.x, box.y, box.x1, box.y1)

    try:
        png = _render_page(
            pdf_bytes,
            page_number,
            float(st.session_state.viewer_zoom),
            highlight,
        )
    except Exception as exc:
        st.error(f"Could not render page {page_number}: {exc}")
        return
    st.image(png, width="stretch")

    caption = f"Page {page_number} of {page_count}"
    if element and element.source:
        if element.source.page != page_number:
            caption += (
                f" - selected element is on page {element.source.page}"
            )
        elif highlight:
            caption += f" - highlighting the selected {element.type}"
        else:
            caption += (
                f" - the selected {element.type} has no stored location"
            )
    st.caption(caption)
