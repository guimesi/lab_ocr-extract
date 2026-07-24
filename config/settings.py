"""
Global application settings loaded from environment variables.

Copy ``.env.example`` to ``.env`` and fill in your values. Nothing here
has a real default on purpose - credentials must never live in the repo.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

# Load .env from project root
_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_ROOT / ".env")


def _normalize_host(raw: str) -> str:
    """Workspace URL only: users often paste the OpenAI ``base_url``
    (``.../serving-endpoints``), but the client appends that path itself -
    keeping it here would double it and Databricks answers 404."""
    host = raw.strip().rstrip("/")
    if host.endswith("/serving-endpoints"):
        host = host[: -len("/serving-endpoints")].rstrip("/")
    return host


@dataclass(frozen=True)
class Settings:
    # Databricks Foundation Model API (Claude served via Databricks).
    # The OpenAI SDK talks to ``<host>/serving-endpoints`` using the
    # personal access token as api_key and the serving endpoint name as
    # the model id.
    databricks_host: str = _normalize_host(os.getenv("DATABRICKS_HOST", ""))
    databricks_token: str = os.getenv("DATABRICKS_TOKEN", "").strip()
    # ``or`` (not a getenv default) so an empty var in .env also falls
    # back instead of producing a malformed request path.
    databricks_model: str = (
        os.getenv("DATABRICKS_MODEL", "").strip() or "databricks-claude-sonnet-4-5"
    )

    # Snowflake. externalbrowser auth by default; empty values mean
    # "not configured" and the table-reference feature stays inert.
    sf_account: str = os.getenv("SNOWFLAKE_ACCOUNT", "")
    sf_user: str = os.getenv("SNOWFLAKE_USER", "")
    sf_authenticator: str = os.getenv("SNOWFLAKE_AUTHENTICATOR", "externalbrowser")
    sf_warehouse: str = os.getenv("SNOWFLAKE_WAREHOUSE", "")
    sf_database: str = os.getenv("SNOWFLAKE_DATABASE", "")
    sf_schema: str = os.getenv("SNOWFLAKE_SCHEMA", "")
    sf_role: str = os.getenv("SNOWFLAKE_ROLE", "")

    # Sample rows fetched from the referenced table to show the model
    # real formatting examples (0 = schema only, no sample rows).
    sf_sample_rows: int = int(os.getenv("SNOWFLAKE_SAMPLE_ROWS", "5"))

    # Reference table offered by default in the sidebar; the structured
    # extraction follows this table's columns and types.
    sf_default_table: str = os.getenv(
        "SNOWFLAKE_DEFAULT_TABLE", "INSIGHTS_DB.UC_EPCDF_PRD_RSTR.GP_WBS_HISTORICAL"
    )

    # PDF handling: how many pages to render (0 = no limit) and how many
    # pages go to the model per call - large PDFs are processed in
    # batches to stay under the request size limit.
    pdf_max_pages: int = int(os.getenv("PDF_MAX_PAGES", "").strip() or "0")
    pdf_pages_per_call: int = int(os.getenv("PDF_PAGES_PER_CALL", "").strip() or "10")

    # Output-token budget per model call. The Databricks endpoint default
    # is low enough that dense extractions get cut off mid-JSON; set this
    # high explicitly (Claude Sonnet supports far more than the default).
    llm_max_tokens: int = int(os.getenv("LLM_MAX_TOKENS", "").strip() or "16000")

    @property
    def databricks_enabled(self) -> bool:
        return bool(self.databricks_host and self.databricks_token)

    @property
    def snowflake_enabled(self) -> bool:
        return bool(self.sf_account and self.sf_user)


SETTINGS = Settings()
