# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

**This branch (`feature/pdf-extraction-editor`) is the PDF Extraction Editor.** Streamlit app: upload one PDF → the pipeline extracts its full content into structured, source-mapped elements → review the original PDF and the extraction side by side (selecting an element highlights its bounding box in the PDF) → edit via AI chat or manually, with revision history and undo/redo → export Markdown/JSON/HTML. UI text, prompts, and user-facing error messages are in English — keep that convention.

## Commands

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1     # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
copy .env.example .env          # fill in values
streamlit run app.py
python -m pytest tests/         # all model calls are mocked; no .env needed
```

## Architecture

Dependency direction: `app.py` → `src/components/*` → `src/services/*` → `src/models/*` + `src/llm_client.py` → `config/settings.py`. Components render UI and own no business logic; services are Streamlit-free and fully unit-tested — keep both properties.

**LLM access is Claude via Databricks, not the Anthropic API.** `src/llm_client.py` uses the OpenAI SDK pointed at `{DATABRICKS_HOST}/serving-endpoints`, with the Databricks PAT as `api_key` and the serving endpoint name as `model`. Don't switch to the `anthropic` SDK or Anthropic message format. All service-level calls go through `src/services/llm_support.py` (`complete_with_retry`: 429 backoff with jitter, one immediate retry otherwise; `parse_json_payload`: tolerant JSON extraction) — route new model calls through it too.

**Extraction pipeline** (`src/services/pdf_processor.py` orchestrates): validation → native text per page (PyMuPDF `get_text("dict")` blocks classified by font size/boldness/list markers in `native_text_extractor.py`) → tables (`find_tables()` → `table_data` rows + Markdown, overlapping text suppressed) → layout (`layout_analyzer.py`: column splitting/ordering, repeated header/footer/page-number detection) → OCR for pages with <30 native chars (`ocr_service.py`: page PNG → model → JSON elements with percentage bboxes converted back to points) → visual descriptions for embedded images (`visual_content_analyzer.py`, capped by `MAX_IMAGE_DESCRIPTIONS`) → assembly (`source_mapper.py`: order, title promotion, parent links, language). Failures become warnings + placeholder elements, never crashes — preserve that. PyMuPDF objects and the `progress` callback stay on the calling thread; only pure model calls go into the `ThreadPoolExecutor`.

**Everything is source-mapped.** Each `DocumentElement` has an 8-hex `id` and a `SourceReference` (1-based page, `BoundingBox` in PDF points top-left origin, extraction method, confidence). The PDF viewer (`src/components/pdf_viewer.py`) renders pages server-side and draws the selected element's box — there is no browser-side PDF.js. Edits must never strip `id` or `source`; the first edit snapshots `original_content`.

**Editing is revision-based** (`src/services/document_editor.py`): `DocumentEditor` holds the pristine `original` (never mutated) and the working document; every change goes through `apply_operations()` (update/insert_after/insert_before/delete) which records a `Revision` with per-element before/after dicts and list indices, enabling exact undo/redo. Don't mutate `editor.document.elements` directly.

**Chat protocol** (`src/services/chat_service.py`): context = current document serialized with `[id]` markers (outline degradation over `CHAT_CONTEXT_CHARS`), rebuilt every turn. The model replies either prose (answer) or a single JSON object `{"action":"edit","summary":…,"edits":[…]}`; `parse_chat_response` validates ids and converts to `EditOperation`s. Deletes or >3 ops require user confirmation via `st.session_state.pending_edit` before applying. Keep prompts grounded (never invent content, `[illegible]` markers) in any prompt changes.

**App state** lives in `st.session_state` (keys in `src/utils/state_utils.py`), keyed by upload content hash — the extraction runs once per file and reruns reuse the session copy. Exports (`export_service.py`) read the current edited document; HTML output must stay fully escaped (`_inline` escapes before styling).

**Snowflake is unused on this branch.** `src/snowflake_client.py` and the `SNOWFLAKE_*` settings are kept only to ease merges with `master`; don't wire them in. `Settings.databricks_enabled` gates all model features — extraction of native-text PDFs must keep working without credentials, and new AI features belong behind that flag rather than failing at startup.
