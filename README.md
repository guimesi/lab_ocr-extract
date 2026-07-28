# Doc Patterns (variation of OCR Extract)

Streamlit app that learns the *pattern* of a document kind from examples,
with **Claude via Databricks** (Foundation Model API, consumed through the
**OpenAI SDK**). Upload several (large) PDFs of the same kind → the model
analyzes each one's structure and conventions → chat about the documents →
generate a complete **authoring template** for writing a new one like them.

> This branch (`doc-pattern-chat`) is a variation of the original OCR
> Extract app (branch `master`), which focuses on OCR + structured
> extraction into a Snowflake table layout.

## Features

1. **Multi-document upload** (PDFs or images) — ideally ~5 examples of the
   same document kind. PDFs are rendered page by page into images (PyMuPDF).
2. **Pattern analysis** — each document is analyzed in page batches (one
   model call per batch, plus one consolidation call for large PDFs),
   producing a markdown *profile* per document: structure, sections, layout,
   formatting, data conventions, style. Profiles are shown and downloadable.
3. **Chat grounded in the analyses** — the chat context is the document
   profiles (plus one first-page image per document for visual reference),
   not the raw pages, so any number/size of PDFs keeps working.
4. **Template generation** — one click asks the model for a full authoring
   guide: required sections, formatting and data conventions, style, a
   fill-in-the-blanks skeleton and a validation checklist. Any answer can be
   downloaded as `.md`.

## Setup

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env   # then fill in the values
streamlit run app.py
```

## Configuration (`.env`)

### Databricks (required)

| Variable | Description |
|---|---|
| `DATABRICKS_HOST` | Workspace URL, e.g. `https://adb-123...azuredatabricks.net` (without `/serving-endpoints`) |
| `DATABRICKS_TOKEN` | Personal Access Token (User Settings → Developer → Access tokens) |
| `DATABRICKS_MODEL` | Serving endpoint name, e.g. `databricks-claude-sonnet-4-5` |

The OpenAI SDK points to `{DATABRICKS_HOST}/serving-endpoints`, with the PAT
as `api_key` and the endpoint name as `model`. The endpoint must accept image
input (the pay-per-token Claude endpoints do).

### PDF handling

`PDF_MAX_PAGES` (default 0 = no limit) caps how many pages are rendered.
`PDF_PAGES_PER_CALL` (default 10) controls how many pages go to the model per
analysis call — large PDFs are analyzed in batches and the notes consolidated.
`LLM_MAX_TOKENS` (default 16000) is the output budget per call; raise it if
analyses or templates come back truncated.

### Snowflake (unused on this branch)

The Snowflake variables and `src/snowflake_client.py` are kept for easy
merging with `master`, but this app does not use them.

## Structure

```
app.py                    # Streamlit UI (upload, analysis, chat, template)
config/settings.py        # settings via .env
src/documents.py          # image/PDF -> pages (PyMuPDF)
src/llm_client.py         # Claude via Databricks (OpenAI SDK)
src/patterns.py           # per-document map-reduce analysis + chat/template prompts
src/snowflake_client.py   # unused here (kept from master)
```

## Notes

- The model is instructed to **stay grounded**: it quotes real section
  titles and labels, marks illegible fragments as `[illegible]`, and never
  invents content.
- The chat never receives the raw pages of every document — only the
  analysis profiles and one first-page image per document — so re-run the
  analysis if you need details the profiles missed (or point the model at
  them via chat and re-analyze).
