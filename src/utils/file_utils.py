"""Small file helpers: content hashing and safe download names."""
from __future__ import annotations

import hashlib
import re


def content_hash(file_bytes: bytes) -> str:
    """Stable key for caching extraction results per file content."""
    return hashlib.sha256(file_bytes).hexdigest()[:16]


def safe_stem(file_name: str) -> str:
    """A filesystem-safe stem for download file names.

    Strips any path components and keeps only word characters, dots and
    dashes so exported names can never traverse directories.
    """
    stem = file_name.replace("\\", "/").rsplit("/", 1)[-1]
    stem = stem.rsplit(".", 1)[0] if "." in stem else stem
    stem = re.sub(r"[^\w.-]+", "_", stem).strip("._")
    return stem or "document"
