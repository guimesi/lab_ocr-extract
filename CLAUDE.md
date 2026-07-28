# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

**This branch (`doc-pattern-chat`) is a variation of the OCR Extract app on `master`.** Streamlit app: upload several (large) PDFs of the same document kind → Claude analyzes each one's structure/patterns into a markdown *profile* → chat about the documents grounded in those profiles → one-click generation of an authoring template for writing a new document like them. UI text, prompts, and user-facing error messages are in English — keep that convention.

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

Modules with one direction of dependency: `app.py` → `src/documents.py` + `src/patterns.py` → `src/llm_client.py` → `config/settings.py`.

**LLM access is Claude via Databricks, not the Anthropic API.** `src/llm_client.py` uses the OpenAI SDK pointed at `{DATABRICKS_HOST}/serving-endpoints`, with the Databricks PAT as `api_key` and the serving endpoint name (e.g. `databricks-claude-sonnet-4-5`) as `model`. Messages and images use the OpenAI format (base64 data URIs via `image_content()`); Databricks forwards them to Claude. Don't switch to the `anthropic` SDK or Anthropic message format. `stream_chat`/`complete` accept an optional `system` override; this branch uses `patterns.ANALYST_SYSTEM_PROMPT` everywhere.

**Everything the model sees is images.** `src/documents.py` normalizes an upload into `(bytes, mime)` pages: images pass through; PDFs are rendered page-by-page to PNG with PyMuPDF (~144 dpi, capped at `PDF_MAX_PAGES`, 0 = unlimited).

**Map-reduce analysis is the core trick** (`src/patterns.py`): several large PDFs never fit one request, so each document is analyzed in batches of `PDF_PAGES_PER_CALL` pages (`page_batches()` in `app.py`, one `complete()` call per batch), and multi-batch notes are consolidated by a final text-only call into one *document profile*. Profiles live in `st.session_state.profiles` (`{file name: markdown}`). The prompts insist on grounded, concrete output (quote real titles/labels, `[illegible]` for unreadable fragments, never invent) — preserve that in any prompt changes.

**Chat context assembly** ([app.py](app.py)): the visible chat history in `st.session_state.messages` is not what's sent to the API — each turn rebuilds `api_messages` with a synthetic first user turn carrying `patterns.chat_context(profiles)` (all profiles as text) plus one first-page image per document, a canned assistant acknowledgment, then the visible history. **Raw pages are never sent to chat** — that's what keeps the request size flat regardless of document count/size. The "Generate authoring template" button injects `patterns.TEMPLATE_REQUEST` as a normal chat turn. Changing the set of uploaded files (detected via the tuple of `file_id`s in `docs_key`) resets profiles and chat.

**Snowflake is unused on this branch.** `src/snowflake_client.py` and the `SNOWFLAKE_*` settings are kept only to ease merges with `master`; don't wire them into this app. `Settings.databricks_enabled` still gates model access — the sidebar shows an error and calls raise when unconfigured; keep new features behind that flag rather than failing at startup.
