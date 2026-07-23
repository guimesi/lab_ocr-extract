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


@dataclass(frozen=True)
class Settings:
    # Databricks Foundation Model API (Claude served via Databricks).
    # The OpenAI SDK talks to ``<host>/serving-endpoints`` using the
    # personal access token as api_key and the serving endpoint name as
    # the model id.
    databricks_host: str = os.getenv("DATABRICKS_HOST", "").rstrip("/")
    databricks_token: str = os.getenv("DATABRICKS_TOKEN", "")
    databricks_model: str = os.getenv(
        "DATABRICKS_MODEL", "databricks-claude-sonnet-4-5"
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

    @property
    def databricks_enabled(self) -> bool:
        return bool(self.databricks_host and self.databricks_token)

    @property
    def snowflake_enabled(self) -> bool:
        return bool(self.sf_account and self.sf_user)


SETTINGS = Settings()
