"""
OCR Extract - Streamlit app.

Upload an image or PDF -> OCR with Claude (via Databricks serving
endpoint, OpenAI SDK) -> chat about the document -> structured
extraction following a Snowflake table schema -> CSV / Excel export.

Run: streamlit run app.py
"""
from __future__ import annotations

import io

import pandas as pd
import streamlit as st

from config.settings import SETTINGS
from src import documents, llm_client
from src.snowflake_client import get_shared_client, qualify

st.set_page_config(
    page_title="OCR Extract",
    page_icon=":material/document_scanner:",
    layout="wide",
)


# =============================================================================
# Cached data access
# =============================================================================

@st.cache_data(ttl=600, show_spinner="Reading schema from Snowflake...")
def load_table_schema(table_ref: str) -> pd.DataFrame:
    return get_shared_client().describe_table(table_ref)


@st.cache_data(ttl=600, show_spinner="Fetching sample rows...")
def load_table_sample(table_ref: str, limit: int) -> pd.DataFrame:
    return get_shared_client().fetch_sample(table_ref, limit=limit)


@st.cache_data(ttl=600, show_spinner="Preparing the document...")
def load_document_pages(
    file_bytes: bytes, mime_type: str
) -> tuple[list[tuple[bytes, str]], int]:
    return documents.load_pages(file_bytes, mime_type)


def page_batches(parts: list[dict]) -> list[tuple[int, int, list[dict]]]:
    """Split page content parts into ``(first, last, parts)`` batches so
    large PDFs fit the request size limit (one model call per batch)."""
    size = max(1, SETTINGS.pdf_pages_per_call)
    return [
        (i + 1, min(i + size, len(parts)), parts[i : i + size])
        for i in range(0, len(parts), size)
    ]


# =============================================================================
# Session state
# =============================================================================

_DEFAULTS = {
    "messages": [],          # visible chat history: {"role", "content"}
    "ocr_text": None,        # free-form OCR transcription (str)
    "extracted_df": None,    # structured extraction (DataFrame)
    "table_ref": "",         # qualified table reference in use
    "image_key": None,       # id of the current upload, to detect changes
}
for key, default in _DEFAULTS.items():
    st.session_state.setdefault(key, default)


def reset_results() -> None:
    st.session_state.messages = []
    st.session_state.ocr_text = None
    st.session_state.extracted_df = None


# =============================================================================
# Sidebar: connection status + Snowflake table reference
# =============================================================================

with st.sidebar:
    st.title(":material/document_scanner: OCR Extract")

    if SETTINGS.databricks_enabled:
        st.success(f"Databricks: `{SETTINGS.databricks_model}`", icon=":material/cloud_done:")
    else:
        st.error(
            "Databricks is not configured. Set DATABRICKS_HOST and "
            "DATABRICKS_TOKEN in `.env` (see `.env.example`).",
            icon=":material/cloud_off:",
        )

    st.divider()
    st.subheader("Reference table (optional)")
    st.caption(
        "Point to a Snowflake table so the OCR extracts data matching "
        "its layout (columns and types)."
    )

    if not SETTINGS.snowflake_enabled:
        st.info(
            "Snowflake is not configured in `.env` - OCR will produce a "
            "free-form transcription.",
            icon=":material/database_off:",
        )
    else:
        table_input = st.text_input(
            "Table (NAME, SCHEMA.NAME or DB.SCHEMA.NAME)",
            value=st.session_state.table_ref or SETTINGS.sf_default_table,
            placeholder="e.g. DB.SCHEMA.TABLE",
        )
        col_load, col_clear = st.columns(2)
        if col_load.button("Load schema", width="stretch", type="primary"):
            try:
                ref = qualify(table_input)
                load_table_schema.clear()
                load_table_sample.clear()
                load_table_schema(ref)  # validates + warms the cache
                st.session_state.table_ref = ref
                st.session_state.extracted_df = None
            except Exception as exc:
                st.error(f"Failed to load the table: {exc}")
        if col_clear.button("Clear", width="stretch"):
            st.session_state.table_ref = ""
            st.session_state.extracted_df = None

        if st.session_state.table_ref:
            st.success(f"Using `{st.session_state.table_ref}`", icon=":material/table:")
            with st.expander("Table columns"):
                st.dataframe(
                    load_table_schema(st.session_state.table_ref),
                    width="stretch",
                    hide_index=True,
                )


# =============================================================================
# Main: upload + OCR
# =============================================================================

st.header("1. Document", divider="gray")

uploaded = st.file_uploader(
    "Upload an image or PDF (invoice, receipt, table, form...)",
    type=["png", "jpg", "jpeg", "webp", "gif", "pdf"],
)

if uploaded is None:
    st.session_state.image_key = None
    reset_results()
    st.info("Upload an image or PDF to get started.", icon=":material/upload_file:")
    st.stop()

# New file replaces previous results / conversation
if st.session_state.image_key != uploaded.file_id:
    st.session_state.image_key = uploaded.file_id
    reset_results()

file_bytes = uploaded.getvalue()
mime_type = uploaded.type or "image/png"
pages, total_pages = load_document_pages(file_bytes, mime_type)
if total_pages > len(pages):
    st.warning(
        f"The PDF has {total_pages} pages; only the first {len(pages)} "
        "will be processed (PDF_MAX_PAGES).",
        icon=":material/warning:",
    )

# One image content part per page, reused in every model call.
page_parts = [llm_client.image_content(b, m) for b, m in pages]

col_img, col_ocr = st.columns([2, 3], gap="large")

with col_img:
    st.image(pages[0][0], caption=uploaded.name, width="stretch")
    if len(pages) > 1:
        with st.expander(f"View all {len(pages)} pages"):
            for i, (page_bytes, _) in enumerate(pages, start=1):
                st.image(page_bytes, caption=f"Page {i}", width="stretch")

with col_ocr:
    structured = False
    if st.session_state.table_ref:
        structured = st.toggle(
            "Extract following the reference table layout",
            value=True,
            help=(
                f"Fills the columns of `{st.session_state.table_ref}` with "
                "data from the document. Turn off for a free-form markdown "
                "transcription."
            ),
        )
    extra = st.text_area(
        "Additional instructions (optional)",
        placeholder="e.g. only consider the line-item table, ignore the footer",
    )
    label = (
        "Extract to table layout" if structured else "Run OCR (transcription)"
    )
    if st.button(label, type="primary", icon=":material/document_scanner:"):
        batches = page_batches(page_parts)
        if structured:
            schema = load_table_schema(st.session_state.table_ref)
            sample = None
            if SETTINGS.sf_sample_rows > 0:
                try:
                    sample = load_table_sample(
                        st.session_state.table_ref, SETTINGS.sf_sample_rows
                    )
                except Exception:
                    sample = None  # sample is optional; the schema suffices
            base_prompt = llm_client.build_extraction_prompt(schema, sample, extra)
            frames: list[pd.DataFrame] | None = []
            for first, last, batch in batches:
                prompt = base_prompt
                spinner = "Extracting data from the document..."
                if len(batches) > 1:
                    prompt += (
                        f"\n\nThe attached images are pages {first}-{last} of a "
                        f"{len(page_parts)}-page document; extract only what is "
                        "visible in them."
                    )
                    spinner = (
                        f"Extracting data (pages {first}-{last} of "
                        f"{len(page_parts)})..."
                    )
                with st.spinner(spinner):
                    answer = llm_client.complete([
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": prompt},
                                *batch,
                            ],
                        }
                    ])
                try:
                    frames.append(
                        llm_client.parse_rows_json(answer, schema["NAME"].tolist())
                    )
                except ValueError as exc:
                    st.error(f"{exc} (pages {first}-{last}) Raw response below:")
                    st.code(answer)
                    frames = None
                    break
            if frames is not None:
                st.session_state.extracted_df = pd.concat(frames, ignore_index=True)
                st.session_state.ocr_text = None
        else:
            base_prompt = (
                "Transcribe the full content of the document to markdown, "
                "preserving its structure (headings, tables, fields). "
                "Each image is one page; transcribe them in order. "
                "Mark illegible fragments as [illegible]."
            )
            if extra.strip():
                base_prompt += f"\n\nAdditional instructions: {extra.strip()}"
            texts: list[str] = []
            with st.chat_message("assistant"):
                for first, last, batch in batches:
                    prompt = base_prompt
                    if len(batches) > 1:
                        prompt += (
                            f"\n\nThe attached images are pages {first}-{last} "
                            f"of a {len(page_parts)}-page document; transcribe "
                            "only these pages, without any preamble."
                        )
                    texts.append(
                        st.write_stream(
                            llm_client.stream_chat([
                                {
                                    "role": "user",
                                    "content": [
                                        {"type": "text", "text": prompt},
                                        *batch,
                                    ],
                                }
                            ])
                        )
                    )
            st.session_state.ocr_text = "\n\n".join(texts)
            st.session_state.extracted_df = None


# =============================================================================
# Results + export
# =============================================================================

if st.session_state.extracted_df is not None or st.session_state.ocr_text:
    st.header("2. Result", divider="gray")

if st.session_state.extracted_df is not None:
    st.caption("Review and edit the values before exporting.")
    edited = st.data_editor(
        st.session_state.extracted_df,
        width="stretch",
        num_rows="dynamic",
        key="result_editor",
    )
    csv_bytes = edited.to_csv(index=False).encode("utf-8-sig")
    xlsx_buf = io.BytesIO()
    with pd.ExcelWriter(xlsx_buf, engine="openpyxl") as writer:
        edited.to_excel(writer, index=False, sheet_name="extraction")
    col_a, col_b = st.columns(2)
    col_a.download_button(
        "Download CSV", csv_bytes, "extraction.csv", "text/csv",
        icon=":material/download:", width="stretch",
    )
    col_b.download_button(
        "Download Excel", xlsx_buf.getvalue(), "extraction.xlsx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        icon=":material/download:", width="stretch",
    )
elif st.session_state.ocr_text:
    st.markdown(st.session_state.ocr_text)
    st.download_button(
        "Download transcription (.md)",
        st.session_state.ocr_text.encode("utf-8"),
        "transcription.md",
        "text/markdown",
        icon=":material/download:",
    )


# =============================================================================
# Chat about the document
# =============================================================================

st.header("3. Chat about the document", divider="gray")

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.write(msg["content"])

if prompt := st.chat_input("Ask something about the document...", submit_mode="disable"):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.write(prompt)

    # API messages: the document pages (and any prior result) go as
    # context in the first user turn; the visible history follows as
    # plain text.
    context_parts: list[str] = [
        "This is the document under analysis (one image per page)."
    ]
    if st.session_state.ocr_text:
        context_parts.append(
            "OCR transcription already produced:\n" + st.session_state.ocr_text
        )
    if st.session_state.extracted_df is not None:
        context_parts.append(
            "Data already extracted (CSV):\n"
            + st.session_state.extracted_df.to_csv(index=False)
        )
    api_messages: list[dict] = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "\n\n".join(context_parts)},
                *page_parts,
            ],
        },
        {
            "role": "assistant",
            "content": "Understood. I am looking at the document. What would you like to know?",
        },
        *st.session_state.messages,
    ]

    with st.chat_message("assistant"):
        try:
            response = st.write_stream(llm_client.stream_chat(api_messages))
        except Exception as exc:
            st.error(f"Error calling the model: {exc}")
            st.session_state.messages.pop()
            st.stop()
    st.session_state.messages.append({"role": "assistant", "content": response})
