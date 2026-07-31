# PDF Extraction Editor

Streamlit app to **extract, review, edit and export** the content of PDF
documents, with **Claude via Databricks** (Foundation Model API, consumed
through the **OpenAI SDK**) for OCR, visual descriptions and AI editing.

> This branch (`feature/pdf-extraction-editor`) refactors the previous
> multi-PDF "Doc Patterns" app into a single-document extraction editor.

## Product objective

1. Upload a PDF.
2. The pipeline extracts the **complete** content into structured elements
   (title, headings, paragraphs, lists, tables, images/charts/diagrams,
   captions, headers/footers, page numbers), each with a **source
   reference** (page + bounding box + extraction method + confidence).
3. Review the original PDF and the extraction **side by side**: clicking an
   extracted element navigates the PDF viewer to its page and **highlights
   its exact source region**.
4. Chat with the AI about the document, or ask it to **edit** the document
   (correct, rewrite, summarize into, reorganize, reformat, translate...).
   Broad or destructive changes show a preview and ask for confirmation.
5. Every change (AI or manual) is recorded as a **revision** with
   undo/redo; the original extraction is never overwritten.
6. Download the result as **Markdown**, **JSON** (with source references
   and revision history) or standalone **HTML**.

## User workflow

Upload → *Process document* → review side by side → select elements
(target button on each element) → chat / manual edits → History tab for
undo/redo/diffs → Export tab for downloads.

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
5. **OCR** (`ocr_service.py`) - pages without native text are rendered to
   PNG and transcribed by the vision model into the same element JSON
   (types, Markdown content, normalized bounding boxes, confidence).
   OCR calls for multiple pages run in parallel (`LLM_CONCURRENCY`).
6. **Visuals** (`visual_content_analyzer.py`) - embedded images are
   cropped and described by the model (classified image/chart/diagram,
   in-image text transcribed), capped by `MAX_IMAGE_DESCRIPTIONS`.
7. **Assembly** (`source_mapper.py`) - global reading order, title
   promotion, parent-section links, language guess, timestamps.

Failures degrade gracefully: a failed OCR page or table pass becomes a
warning + placeholder, never a crash. The model is instructed to stay
grounded: `[illegible]` for unreadable fragments, never invent content.

## Source mapping & highlighting

Every element carries `SourceReference {page, bounding_box, extraction_method,
confidence}`. The PDF viewer renders pages server-side with PyMuPDF; when an
element is selected the viewer jumps to its page and draws its bounding box
onto the rendered image. References survive edits - an edited element keeps
its original source link and its pristine `original_content`.

## AI chat & editing

The chat context is the **current edited document** serialized with element
ids (plus outline-only degradation for very large documents,
`CHAT_CONTEXT_CHARS`). The model answers questions as prose; edit requests
come back as a JSON operation list (`update` / `insert_after` /
`insert_before` / `delete` per element id) that is validated and applied
through the `DocumentEditor`. Deletions or >3 operations require explicit
confirmation with a before/after preview. All applied edits become
revisions (id, timestamp, source, instruction, affected ids, before/after
content) with undo/redo and *Restore original*.

## Data model / JSON export schema

```jsonc
{
  "document": {"file_name", "page_count", "processed_at", "language",
                "metadata", "warnings"},
  "content": [
    {
      "id": "a1b2c3d4",
      "type": "paragraph",          // title|heading|paragraph|list|table|
                                     // image|chart|diagram|caption|
                                     // header|footer|page_number
      "content": "…",               // Markdown
      "order": 0, "level": null, "parent_id": "…",
      "source": {"page": 1,
                  "bounding_box": {"x": 0, "y": 0, "width": 0, "height": 0},
                  "extraction_method": "native_text|table_detection|llm_ocr|visual_analysis|authored",
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
copy .env.example .env             # then fill in the values
streamlit run app.py
```

### Environment variables (`.env`)

| Variable | Description |
|---|---|
| `DATABRICKS_HOST` | Workspace URL (without `/serving-endpoints`) |
| `DATABRICKS_TOKEN` | Personal Access Token |
| `DATABRICKS_MODEL` | Serving endpoint name, e.g. `databricks-claude-sonnet-4-5` (must accept image input) |
| `PDF_MAX_PAGES` | Max pages processed (0 = no limit) |
| `MAX_UPLOAD_MB` | Upload size limit (default 100) |
| `LLM_MAX_TOKENS` | Output-token budget per model call (default 16000) |
| `LLM_CONCURRENCY` | Parallel model calls during processing (default 6) |
| `MAX_IMAGE_DESCRIPTIONS` | Cap on AI-described visuals per document (default 12) |
| `CHAT_CONTEXT_CHARS` | Chat context budget before outline degradation (default 60000) |

Without Databricks credentials the app still extracts native-text PDFs;
OCR, visual descriptions and chat are disabled with a clear message.

### Tests

```bash
python -m pytest tests/
```

Fixture PDFs (native text, ruled tables, two-column layout, scanned
image-only pages, password-protected) are generated in-memory by
`tests/conftest.py`; all model calls are mocked.

## Structure

```
app.py                      # Streamlit entrypoint: states, layout, wiring
config/settings.py          # settings via .env
src/models/                 # ExtractedDocument, DocumentElement,
                            # SourceReference/BoundingBox, Revision
src/services/               # pdf_processor (orchestrator),
                            # native_text_extractor, table_extractor,
                            # layout_analyzer, ocr_service,
                            # visual_content_analyzer, source_mapper,
                            # document_editor, chat_service,
                            # export_service, llm_support
src/components/             # pdf_viewer, extraction_viewer, chat_panel,
                            # revision_history, export_panel
src/utils/                  # validation, file_utils, state_utils
src/llm_client.py           # Claude via Databricks (OpenAI SDK)
src/snowflake_client.py     # unused here (kept from master)
tests/                      # pytest suite + in-memory fixture PDFs
```

## Privacy & security

- Uploads are processed **in memory only**; nothing is written to disk.
- With OCR/visual/chat features enabled, page images and extracted text
  are sent to the configured **Databricks** model endpoint - and nowhere
  else. Native-text extraction is fully local.
- Credentials come from `.env` (never committed); the app fails soft when
  they are missing.
- HTML export escapes all content (no raw injection); download names are
  sanitized; file type/size are validated before processing.

## Known limitations

- OCR bounding boxes are model-estimated - highlights on scanned pages are
  approximate.
- Reverse mapping (clicking a region *inside* the PDF image to select the
  element) is not implemented; selection flows extraction → PDF.
- Complex multi-column layouts (3+ columns, wrapped figures) may not fully
  restore reading order; borderless tables can be missed by `find_tables()`.
- Undo history lives in the Streamlit session - closing the tab discards
  edits (export first).
- `Restore original` clears the revision history (the original is the
  baseline).
