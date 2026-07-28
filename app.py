"""
Doc Patterns - Streamlit app (variation of OCR Extract).

Upload several (large) PDFs of the same document kind -> Claude
analyzes each one's structure and patterns, in page batches (via
Databricks serving endpoint, OpenAI SDK) -> chat about the documents
grounded in those analyses -> generate a template / authoring guide
for writing a new document like them.

Run: streamlit run app.py
"""
from __future__ import annotations

import streamlit as st

from config.settings import SETTINGS
from src import documents, llm_client, patterns

st.set_page_config(
    page_title="Doc Patterns",
    page_icon=":material/description:",
    layout="wide",
)


# =============================================================================
# Cached data access
# =============================================================================

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
    "messages": [],       # visible chat history: {"role", "content"}
    "profiles": None,     # per-document analysis: {file name: markdown}
    "docs_key": None,     # ids of the current uploads, to detect changes
}
for key, default in _DEFAULTS.items():
    st.session_state.setdefault(key, default)


def reset_results() -> None:
    st.session_state.messages = []
    st.session_state.profiles = None


# =============================================================================
# Sidebar: connection status
# =============================================================================

with st.sidebar:
    st.title(":material/description: Doc Patterns")
    st.caption(
        "Upload reference documents of the same kind; the model analyzes "
        "their structure and patterns so you can chat about them and "
        "generate an authoring template for new documents."
    )

    if SETTINGS.databricks_enabled:
        st.success(
            f"Databricks: `{SETTINGS.databricks_model}`",
            icon=":material/cloud_done:",
        )
    else:
        st.error(
            "Databricks is not configured. Set DATABRICKS_HOST and "
            "DATABRICKS_TOKEN in `.env` (see `.env.example`).",
            icon=":material/cloud_off:",
        )

    st.divider()
    st.caption(
        f"Documents are analyzed {SETTINGS.pdf_pages_per_call} page(s) "
        "per model call (PDF_PAGES_PER_CALL); large PDFs take one call "
        "per batch plus one to consolidate. Up to "
        f"{SETTINGS.llm_concurrency} calls run in parallel "
        "(LLM_CONCURRENCY)."
    )


# =============================================================================
# 1. Reference documents
# =============================================================================

st.header("1. Reference documents", divider="gray")

uploads = st.file_uploader(
    "Upload the reference documents (PDFs or images) - ideally several "
    "examples of the same document kind.",
    type=["pdf", "png", "jpg", "jpeg", "webp", "gif"],
    accept_multiple_files=True,
)

if not uploads:
    st.session_state.docs_key = None
    reset_results()
    st.info(
        "Upload one or more documents to get started.",
        icon=":material/upload_file:",
    )
    st.stop()

# A change in the set of files replaces previous results / conversation.
docs_key = tuple(f.file_id for f in uploads)
if st.session_state.docs_key != docs_key:
    st.session_state.docs_key = docs_key
    reset_results()

# Load pages for every document up front (cached per file content).
docs: list[tuple[str, list[tuple[bytes, str]], int]] = []
total_calls = 0
for f in uploads:
    pages, total = load_document_pages(f.getvalue(), f.type or "image/png")
    if total > len(pages):
        st.warning(
            f"{f.name}: the PDF has {total} pages; only the first "
            f"{len(pages)} will be processed (PDF_MAX_PAGES).",
            icon=":material/warning:",
        )
    docs.append((f.name, pages, total))
    n_batches = len(page_batches([None] * len(pages)))
    total_calls += n_batches + (1 if n_batches > 1 else 0)

st.caption(
    f"{len(docs)} document(s), "
    f"{sum(len(pages) for _, pages, _ in docs)} page(s) in total - "
    f"the analysis will take about {total_calls} model call(s)."
)
with st.expander("Preview (first page of each document)"):
    cols = st.columns(min(len(docs), 4))
    for i, (name, pages, total) in enumerate(docs):
        with cols[i % len(cols)]:
            st.image(pages[0][0], caption=f"{name} ({total} pages)", width="stretch")

if st.button(
    "Analyze documents", type="primary", icon=":material/manage_search:"
):
    doc_inputs: dict[str, tuple[int, list[tuple[int, int, list[dict]]]]] = {}
    for name, pages, _ in docs:
        parts = [llm_client.image_content(b, m) for b, m in pages]
        doc_inputs[name] = (len(parts), page_batches(parts))
    bar = st.progress(0.0, text="Queueing the analysis...")
    try:
        profiles, warnings = patterns.analyze_documents(
            doc_inputs,
            concurrency=SETTINGS.llm_concurrency,
            progress=lambda done, total, label: bar.progress(
                done / total, text=label
            ),
        )
    except Exception as exc:
        bar.empty()
        st.error(f"Analysis failed: {exc}")
        st.stop()
    bar.empty()
    for warning in warnings:
        st.warning(warning, icon=":material/error:")
    if profiles:
        st.session_state.profiles = profiles
        st.session_state.messages = []


# =============================================================================
# 2. Analyses
# =============================================================================

profiles = st.session_state.profiles
if profiles:
    st.header("2. Document analyses", divider="gray")
    st.caption(
        "One structural profile per document - this is the context the "
        "chat reasons over."
    )
    for name, profile in profiles.items():
        with st.expander(f":material/description: {name}"):
            st.markdown(profile)
    combined = "\n\n---\n\n".join(
        f"# {name}\n\n{profile}" for name, profile in profiles.items()
    )
    st.download_button(
        "Download all analyses (.md)",
        combined.encode("utf-8"),
        "document_analyses.md",
        "text/markdown",
        icon=":material/download:",
    )


# =============================================================================
# 3. Chat + template generation
# =============================================================================

st.header("3. Chat about the documents", divider="gray")

if not profiles:
    st.info(
        "Run the analysis first - the chat answers based on the "
        "document profiles.",
        icon=":material/manage_search:",
    )
    st.stop()

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.write(msg["content"])

prompt = st.chat_input(
    "Ask about the documents, their patterns, or how to write a new one...",
    submit_mode="disable",
)
if st.button(
    "Generate authoring template",
    icon=":material/edit_document:",
    help=(
        "Asks the model for a complete template: required sections, "
        "formatting and data conventions, style guidance, a fill-in "
        "skeleton and a validation checklist."
    ),
):
    prompt = patterns.TEMPLATE_REQUEST

if prompt:
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.write(prompt)

    # API messages: the document profiles (plus one first-page image per
    # document, as visual reference) go as context in the first user
    # turn; the visible history follows as plain text. Raw pages are NOT
    # sent - five large PDFs would not fit one request.
    context_content: list[dict] = [
        {"type": "text", "text": patterns.chat_context(profiles)}
    ]
    for name, pages, _ in docs:
        context_content.append(
            {"type": "text", "text": f'First page of "{name}":'}
        )
        context_content.append(llm_client.image_content(*pages[0]))
    api_messages: list[dict] = [
        {"role": "user", "content": context_content},
        {
            "role": "assistant",
            "content": (
                "Understood. I have the analysis profiles of every "
                "reference document. What would you like to know?"
            ),
        },
        *st.session_state.messages,
    ]

    with st.chat_message("assistant"):
        try:
            response = st.write_stream(
                llm_client.stream_chat(
                    api_messages, system=patterns.ANALYST_SYSTEM_PROMPT
                )
            )
        except Exception as exc:
            st.error(f"Error calling the model: {exc}")
            st.session_state.messages.pop()
            st.stop()
    st.session_state.messages.append({"role": "assistant", "content": response})

if st.session_state.messages and st.session_state.messages[-1]["role"] == "assistant":
    st.download_button(
        "Download last answer (.md)",
        str(st.session_state.messages[-1]["content"]).encode("utf-8"),
        "answer.md",
        "text/markdown",
        icon=":material/download:",
    )
