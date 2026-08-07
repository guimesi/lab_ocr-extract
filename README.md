# PDF Extraction Editor

Streamlit app to **extract, review, edit and export** the content of PDF
documents. Everything runs **locally with PyMuPDF** - no LLM, no external
services, no credentials.

> This branch (`feature/simple-extraction-editor`) strips the app down to
> the essentials: upload → extraction → manual editing → export. OCR,
> AI visual descriptions and the AI chat were removed.

## Product objective

1. Upload a PDF.
2. The pipeline extracts the native content into structured elements
   (title, headings, paragraphs, lists, tables, image placeholders,
   captions, headers/footers, page numbers), each with a **source
   reference** (page + bounding box + extraction method).
3. Review the original PDF and the extraction **side by side**: clicking an
   extracted element navigates the PDF viewer to its page and **highlights
   its exact source region**.
4. Edit the content **manually**; every change is recorded as a
   **revision** with undo/redo - the original extraction is never
   overwritten.
5. Download the result as **Markdown**, **JSON** (with source references
   and revision history) or standalone **HTML**.

Pages without a native text layer (scanned images) are marked with an
honest placeholder - there is no OCR in this app.

## User workflow

Upload → *Process document* → review side by side → select elements
(target button on each element) → manual edits in the Document tab →
History tab for undo/redo/diffs → Export tab for downloads.

## Extraction pipeline

Stage by stage (`src/services/pdf_processor.py` orchestrates):

1. **Validation** (`src/utils/validation.py`) - file type/size, corrupted,
   password-protected, empty PDFs.
2. **Native text** (`native_text_extractor.py`) - PyMuPDF layout blocks;
   headings vs paragraphs vs lists vs captions classified by font size
   (relative to the document's dominant body size), boldness and list
   markers; hyphenation undone; bounding boxes preserved.
3. **Tables** (`table_extractor.py`) - PyMuPDF `find_tables()`; each table
   becomes structured rows (`table_data`) + GitHub Markdown; overlapping
   text blocks are suppressed.
4. **Layout** (`layout_analyzer.py`) - two-column reading order (with
   splitting of blocks that straddle columns) and detection of repeated
   headers/footers/page numbers, which are excluded from the content flow.
5. **Assembly** (`source_mapper.py`) - global reading order, title
   promotion, parent-section links, language guess, timestamps.

Failures degrade gracefully: a failed table pass or a scanned page becomes
a warning + placeholder element, never a crash.

## Source mapping & highlighting

Every element carries `SourceReference {page, bounding_box, extraction_method,
confidence}`. The PDF viewer renders pages server-side with PyMuPDF; when an
element is selected the viewer jumps to its page and draws its bounding box
onto the rendered image. References survive edits - an edited element keeps
its original source link and its pristine `original_content`.

## Editing

All edits go through the `DocumentEditor` (`update` / `insert_after` /
`insert_before` / `delete`). Applied edits become revisions (id, timestamp,
source, affected ids, before/after content) with undo/redo and *Restore
original*.

## Data model / JSON export schema

```jsonc
{
  "document": {"file_name", "page_count", "processed_at", "language",
                "metadata", "warnings"},
  "content": [
    {
      "id": "a1b2c3d4",
      "type": "paragraph",          // title|heading|paragraph|list|table|
                                     // image|caption|header|footer|page_number
      "content": "…",               // Markdown
      "order": 0, "level": null, "parent_id": "…",
      "source": {"page": 1,
                  "bounding_box": {"x": 0, "y": 0, "width": 0, "height": 0},
                  "extraction_method": "native_text|table_detection|scanned_page|authored",
                  "confidence": 0.9},
      "revision": {"edited": false, "edited_by": null, "original_content": null},
      "table_data": [["…"]]          // tables only
    }
  ],
  "revision_history": [
    {"id", "timestamp", "source", "instruction", "summary",
     "affected_element_ids", "changes": [{"op", "index", "before", "after"}]}
  ]
}
```

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
app.py                      # Streamlit entrypoint: states, layout, wiring
config/settings.py          # settings via .env (all optional)
src/models/                 # ExtractedDocument, DocumentElement,
                            # SourceReference/BoundingBox, Revision
src/services/               # pdf_processor (orchestrator),
                            # native_text_extractor, table_extractor,
                            # layout_analyzer, source_mapper,
                            # document_editor, export_service
src/components/             # pdf_viewer, extraction_viewer,
                            # revision_history, export_panel
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
- Reverse mapping (clicking a region *inside* the PDF image to select the
  element) is not implemented; selection flows extraction → PDF.
- Complex multi-column layouts (3+ columns, wrapped figures) may not fully
  restore reading order; borderless tables can be missed by `find_tables()`.
- Undo history lives in the Streamlit session - closing the tab discards
  edits (export first).
- `Restore original` clears the revision history (the original is the
  baseline).
