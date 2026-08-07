# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

**This branch (`feature/simple-extraction-editor`) is the minimal PDF Text Extractor - keep it that way.** Single-page Streamlit app: upload one PDF → its text is extracted locally with PyMuPDF into one Markdown string → the user edits it in a single `st.text_area` → download as Markdown/JSON/HTML. UI text and user-facing error messages are in English — keep that convention.

**No LLM, no external services, no credentials, no structured document model.** There are no element types, source mapping, revision history or chat here — all of that lives on `feature/pdf-extraction-editor`. Don't reintroduce those layers or any network dependency; simplicity is the point of this branch.

## Commands

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1     # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
python -m pytest tests/         # no .env needed
```

`.env` is optional — only `PDF_MAX_PAGES` and `MAX_UPLOAD_MB` exist (see `.env.example`).

## Architecture

Flat and small — `app.py` is the whole UI; `src/*` modules are Streamlit-free and unit-tested:

- `src/extractor.py` — `extract_text(bytes) -> (text, warnings)`: PyMuPDF text blocks joined with blank lines; pages with <30 native chars are treated as scanned and get a visible placeholder plus a warning (no OCR). Failures raise `ExtractionError` with a user-safe message.
- `src/exporters.py` — `to_markdown` / `to_json` / `to_html`. HTML output must stay fully escaped (`html.escape` before any markup).
- `src/validation.py` — upload checks (empty, oversized, non-PDF, corrupted, password-protected); raises `ValidationError` with user-safe messages.
- `src/file_utils.py` — `content_hash` (extraction cache key) and `safe_stem` (sanitized download names).
- `config/settings.py` — the two optional `.env` knobs.

App state is three `st.session_state` keys managed inline in `app.py`: `doc_hash` (extraction runs once per file content), `text` (the editable Markdown, also the `st.text_area` widget key) and `warnings`. Assign `st.session_state.text` only before the widget is instantiated.
