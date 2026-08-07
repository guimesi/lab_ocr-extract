# PDF Text Extractor

Minimal Streamlit app: **upload a PDF → the text is extracted locally →
edit it as Markdown in one text box → download as Markdown, JSON or
HTML**. PyMuPDF only - no LLM, no external services, no credentials.

> This branch (`feature/simple-extraction-editor`) is the stripped-down
> version. The full-featured app (structured elements, side-by-side PDF
> viewer, AI chat, OCR) lives on `feature/pdf-extraction-editor`.

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
| `PDF_MAX_PAGES` | Max pages extracted (0 = no limit) |
| `MAX_UPLOAD_MB` | Upload size limit (default 100) |

The app runs without a `.env` - both settings have sensible defaults.

### Tests

```bash
python -m pytest tests/
```

## Structure

```
app.py                # the whole app: upload -> extract -> edit -> export
config/settings.py    # optional .env settings
src/extractor.py      # PDF bytes -> text (PyMuPDF)
src/exporters.py      # text -> Markdown / JSON / HTML
src/validation.py     # upload checks (type, size, corruption, password)
src/file_utils.py     # content hash + safe download names
tests/                # pytest suite with in-memory fixture PDFs
```

## Notes

- Uploads are processed **in memory only**; nothing is written to disk
  and nothing is sent to external services.
- Scanned pages (no native text layer) are not transcribed - they get a
  visible placeholder and a warning. There is no OCR.
- The HTML export escapes all content; download names are sanitized.
- Edits live in the browser session - closing the tab discards them
  (export first).
