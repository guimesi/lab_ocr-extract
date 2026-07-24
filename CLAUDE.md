# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Streamlit app for document OCR: upload an image or PDF → Claude transcribes it (free-form markdown) or extracts structured rows matching a Snowflake table's schema → chat about the document → export CSV/Excel/markdown. UI text, prompts, and user-facing error messages are in English — keep that convention.

## Commands

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env   # fill in values
streamlit run app.py
```

There are no tests or linters configured.

## Architecture

Modules with one direction of dependency: `app.py` → `src/documents.py` + `src/llm_client.py` + `src/snowflake_client.py` → `config/settings.py`.

**LLM access is Claude via Databricks, not the Anthropic API.** `src/llm_client.py` uses the OpenAI SDK pointed at `{DATABRICKS_HOST}/serving-endpoints`, with the Databricks PAT as `api_key` and the serving endpoint name (e.g. `databricks-claude-sonnet-4-5`) as `model`. Messages and images use the OpenAI format (base64 data URIs via `image_content()`); Databricks forwards them to Claude. Don't switch to the `anthropic` SDK or Anthropic message format.

**Everything the model sees is images.** `src/documents.py` normalizes an upload into `(bytes, mime)` pages: images pass through; PDFs are rendered page-by-page to PNG with PyMuPDF (~144 dpi, capped at `PDF_MAX_PAGES`, 0 = unlimited). There is no text-layer PDF parsing. Extraction and free OCR run in batches of `PDF_PAGES_PER_CALL` pages per model call (`page_batches()` in `app.py`) to stay under the request size limit — extraction concatenates the per-batch DataFrames, OCR joins the per-batch markdown. Chat sends all pages in one call.

**Two extraction modes**, chosen by a toggle in `app.py` (shown when a Snowflake table reference is loaded in `st.session_state.table_ref`; the sidebar prefills `SETTINGS.sf_default_table`):
- *Free OCR* — streaming transcription to markdown (`stream_chat`).
- *Structured* — `build_extraction_prompt()` embeds the table's `DESCRIBE TABLE` schema (plus optional real sample rows for formatting examples), the model must answer with a JSON array of row objects, and `parse_rows_json()` tolerantly parses it (fenced block or surrounding prose) into a DataFrame reordered to the table's columns. The model is instructed to use `null` for illegible fields — never invent values; preserve that in any prompt changes.

**Snowflake is optional and degrades silently.** `Settings.snowflake_enabled` / `databricks_enabled` are derived from which env vars are filled; empty vars mean the feature stays inert (sidebar shows an info message, app still does free OCR + chat). `snowflake.connector` is imported lazily inside `connect()` so the app runs without the package installed. Keep new features behind these flags rather than failing at startup.

**Connection and cache layers:** `get_shared_client()` keeps one process-wide Snowflake connection because `externalbrowser` auth opens a browser per connect; `app.py` additionally wraps schema/sample reads in `@st.cache_data(ttl=600)`. Loading a new table clears those caches explicitly.

**SQL safety model:** table references are interpolated into SQL, so `qualify()` validates every part against the unquoted-identifier regex and rejects anything else — any new query path taking user input must go through `qualify()` (identifiers) or `%s` params (values, as in `fetch_table`). `fetch_query`/`fetch_sample` deliberately use the Python-rows path (`fetchall`) instead of Arrow to avoid Snowflake's Arrow chunk-schema mismatch bug; `fetch_table` is the fast Arrow path.

**Chat context assembly** ([app.py](app.py)): the visible chat history in `st.session_state.messages` is not what's sent to the API — each turn rebuilds `api_messages` with a synthetic first user turn carrying the document pages plus any OCR text / extracted CSV as context, a canned assistant acknowledgment, then the visible history. Uploading a new file (detected via `file_id`) resets all results and chat.
