# OCR Extract

Streamlit app for document OCR with **Claude via Databricks** (Foundation
Model API, consumed through the **OpenAI SDK**), with chat about the document
and structured extraction following a **Snowflake table** layout.

## Features

1. **Image or PDF upload** (invoice, receipt, table, form, screenshot...).
   PDFs are rendered page by page into images (PyMuPDF); all pages go to the
   model, in batches for large files.
2. **Free-form OCR** — faithful markdown transcription, preserving structure.
3. **Extraction following a Snowflake table layout** — the sidebar comes
   prefilled with the default reference table
   (`INSIGHTS_DB.UC_EPCDF_PRD_RSTR.GP_WWBS_HISTORICAL`, configurable via
   `SNOWFLAKE_DEFAULT_TABLE`); the app reads the schema (`DESCRIBE TABLE`)
   and a few sample rows, and the model returns the document data as rows of
   that table (JSON → editable DataFrame). A toggle switches between this
   structured extraction and the free-form transcription.
4. **Chat** — talk to the model about the document (the pages and any
   extracted results are sent as context).
5. **Export** — CSV / Excel for the structured extraction (after review in
   the editor) or `.md` for the transcription.

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

### Snowflake (optional — enables the reference table)

`SNOWFLAKE_ACCOUNT`, `SNOWFLAKE_USER`,
`SNOWFLAKE_AUTHENTICATOR=externalbrowser`, `SNOWFLAKE_WAREHOUSE`,
`SNOWFLAKE_DATABASE`, `SNOWFLAKE_SCHEMA`, `SNOWFLAKE_ROLE`. Without them the
app still works with free-form OCR + chat.

`SNOWFLAKE_SAMPLE_ROWS` (default 5) controls how many real rows of the table
are shown to the model as formatting examples (0 = schema only).

`SNOWFLAKE_DEFAULT_TABLE` sets the reference table suggested in the sidebar
(default: `INSIGHTS_DB.UC_EPCDF_PRD_RSTR.GP_WWBS_HISTORICAL`).

### PDF handling

`PDF_MAX_PAGES` (default 0 = no limit) caps how many pages are rendered.
`PDF_PAGES_PER_CALL` (default 10) controls how many pages go to the model per
call — large PDFs are processed in batches and the results concatenated.

## Structure

```
app.py                    # Streamlit UI (upload, OCR, chat, export)
config/settings.py        # settings via .env
src/documents.py          # image/PDF -> pages (PyMuPDF)
src/llm_client.py         # Claude via Databricks (OpenAI SDK) + prompts + JSON parsing
src/snowflake_client.py   # Snowflake connection (adapted from lab_data-quali-score)
```

## Notes

- The Snowflake connection uses `externalbrowser` by default (opens the
  browser on the first query) and is shared process-wide to avoid repeated
  authentications.
- The model is instructed to **never invent values**: illegible fields become
  `null` in the structured extraction and `[illegible]` in the transcription.
- Always review the extraction in the editor before exporting — LLM OCR is
  good, but not infallible.
