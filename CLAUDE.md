# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

**This branch (`feature/simple-extraction-editor`) is the simplified PDF Extraction Editor - no LLM anywhere.** Streamlit app: upload one PDF → the pipeline extracts its native content into structured, source-mapped elements → review the original PDF and the extraction side by side (selecting an element highlights its bounding box in the PDF) → edit manually, with revision history and undo/redo → export Markdown/JSON/HTML. UI text and user-facing error messages are in English — keep that convention.

There are **no model calls, no external services and no credentials**: OCR, AI visual descriptions and the AI chat were removed on this branch (they live on `feature/pdf-extraction-editor`). Don't reintroduce network dependencies; pages without native text get an honest placeholder element (`extraction_method="scanned_page"`) plus a warning.

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

Dependency direction: `app.py` → `src/components/*` → `src/services/*` → `src/models/*` → `config/settings.py`. Components render UI and own no business logic; services are Streamlit-free and fully unit-tested — keep both properties.

**Extraction pipeline** (`src/services/pdf_processor.py` orchestrates, all local PyMuPDF): validation → native text per page (PyMuPDF `get_text("dict")` blocks classified by font size/boldness/list markers in `native_text_extractor.py`) → tables (`find_tables()` → `table_data` rows + Markdown, overlapping text suppressed) → layout (`layout_analyzer.py`: column splitting/ordering, repeated header/footer/page-number detection) → scanned-page placeholders for pages with <30 native chars → assembly (`source_mapper.py`: order, title promotion, parent links, language). Failures become warnings + placeholder elements, never crashes — preserve that.

**Everything is source-mapped.** Each `DocumentElement` has an 8-hex `id` and a `SourceReference` (1-based page, `BoundingBox` in PDF points top-left origin, extraction method, confidence). The PDF viewer (`src/components/pdf_viewer.py`) renders pages server-side and draws the selected element's box — there is no browser-side PDF.js. Edits must never strip `id` or `source`; the first edit snapshots `original_content`.

**Editing is revision-based** (`src/services/document_editor.py`): `DocumentEditor` holds the pristine `original` (never mutated) and the working document; every change goes through `apply_operations()` (update/insert_after/insert_before/delete) which records a `Revision` with per-element before/after dicts and list indices, enabling exact undo/redo. Don't mutate `editor.document.elements` directly.

**App state** lives in `st.session_state` (keys in `src/utils/state_utils.py`), keyed by upload content hash — the extraction runs once per file and reruns reuse the session copy. Exports (`export_service.py`) read the current edited document; HTML output must stay fully escaped (`_inline` escapes before styling).
