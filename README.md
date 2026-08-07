# PDF Extraction Editor

Minimal Streamlit app: **upload a PDF → the content is extracted locally →
edit any element in place → export as Markdown, JSON or HTML**. Everything
runs with PyMuPDF - no LLM, no external services, no credentials.

> This branch (`feature/simple-extraction-editor`) strips the app down to
> the essentials. The full-featured version (side-by-side PDF viewer, AI
> chat, OCR, revision history UI) lives on `feature/pdf-extraction-editor`.

## How it works

1. **Upload** a PDF - it is validated (type, size, corruption, password)
   and extracted immediately.
2. **Extraction** (`src/services/pdf_processor.py`, all local PyMuPDF):
   native text classified into titles/headings/paragraphs/lists/captions
   by font size and style, tables via `find_tables()` (structured rows +
   Markdown), two-column reading order, repeated headers/footers/page
   numbers filtered out. Pages without a text layer (scans) get an honest
   placeholder plus a warning - there is no OCR.
3. **Edit**: every element has an *Edit* expander with its Markdown
   content; saves go through the revision-based `DocumentEditor`, so the
   original extraction is preserved and the JSON export carries the full
   change history.
4. **Export**: download buttons for **Markdown**, **JSON** (with source
   references and revision history) and standalone escaped **HTML**.

Each element keeps a `SourceReference` (page, bounding box in PDF points,
extraction method) in the JSON export, so every passage can be traced back
to its location in the original file.

## Setup & run

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1        # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

### Environment variables (`.env`, optional)

| Variable | Description |
|---|---|
| `PDF_MAX_PAGES` | Max pages processed (0 = no limit) |
| `MAX_UPLOAD_MB` | Upload size limit (default 100) |

The app runs without a `.env` - both settings have sensible defaults.

### Tests

```bash
python -m pytest tests/
```

Fixture PDFs (native text, ruled tables, two-column layout, scanned
image-only pages, password-protected) are generated in-memory by
`tests/conftest.py`.

## Structure

```
app.py                      # Streamlit entrypoint: upload -> extract -> edit -> export
config/settings.py          # settings via .env (all optional)
src/models/                 # ExtractedDocument, DocumentElement,
                            # SourceReference/BoundingBox, Revision
src/services/               # pdf_processor (orchestrator),
                            # native_text_extractor, table_extractor,
                            # layout_analyzer, source_mapper,
                            # document_editor, export_service
src/components/             # extraction_viewer (inline editing), export_panel
src/utils/                  # validation, file_utils, state_utils
tests/                      # pytest suite + in-memory fixture PDFs
```

## Privacy & security

- Uploads are processed **in memory only**; nothing is written to disk and
  nothing is sent to external services.
- HTML export escapes all content (no raw injection); download names are
  sanitized; file type/size are validated before processing.

## Known limitations

- Scanned pages (no native text layer) are not transcribed - they get a
  placeholder element and a warning.
- Complex multi-column layouts (3+ columns, wrapped figures) may not fully
  restore reading order; borderless tables can be missed by `find_tables()`.
- Edits live in the Streamlit session - closing the tab discards them
  (export first).
