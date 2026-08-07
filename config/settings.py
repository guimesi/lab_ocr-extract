"""
Global application settings loaded from environment variables.

Copy ``.env.example`` to ``.env`` to override the defaults. The app has
no external services - these knobs only tune local PDF processing.
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
    # PDF handling: how many pages to process (0 = no limit).
    pdf_max_pages: int = int(os.getenv("PDF_MAX_PAGES", "").strip() or "0")

    # Upload validation: reject files above this size (MB).
    max_upload_mb: int = int(os.getenv("MAX_UPLOAD_MB", "").strip() or "100")


SETTINGS = Settings()
