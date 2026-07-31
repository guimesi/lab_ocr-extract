"""AI descriptions for embedded images, charts and diagrams.

The extractor only knows *where* pictures are; this service crops the
region from the rendered page and asks the vision model what it shows,
classifying it (image / chart / diagram) and transcribing any text.
"""
from __future__ import annotations

import logging

from src import llm_client
from src.services import llm_support

logger = logging.getLogger(__name__)

_DESCRIBE_PROMPT = (
    "This image is a region cropped from a document page (a picture, "
    "chart or diagram). Answer ONLY with a JSON object:\n"
    '{"kind": "<image|chart|diagram>",\n'
    ' "description": "<2-4 factual sentences describing what it shows; '
    "for charts include the chart type, axes, series and the key values "
    'or trend actually visible>",\n'
    ' "text": "<any text readable inside the region, transcribed '
    'verbatim, or empty string>"}\n'
    "Be strictly factual - describe only what is visible; use "
    "[illegible] for unreadable text. No text outside the JSON."
)

_VALID_KINDS = ("image", "chart", "diagram")


def describe_region(png_bytes: bytes) -> tuple[str, str]:
    """Describe a cropped page region.

    Returns ``(kind, description)`` where ``kind`` is one of ``image``,
    ``chart``, ``diagram`` and ``description`` is Markdown text (with
    transcribed in-image text appended when present). Raises on model
    failure - callers decide whether that is fatal.
    """
    message = {
        "role": "user",
        "content": [
            {"type": "text", "text": _DESCRIBE_PROMPT},
            llm_client.image_content(png_bytes, "image/png"),
        ],
    }
    text, _ = llm_support.complete_with_retry([message])
    payload = llm_support.parse_json_payload(text)
    if not isinstance(payload, dict):
        raise ValueError("Visual analysis did not return a JSON object.")
    kind = str(payload.get("kind", "image")).strip().lower()
    if kind not in _VALID_KINDS:
        kind = "image"
    description = str(payload.get("description", "")).strip()
    inner_text = str(payload.get("text", "")).strip()
    if inner_text:
        description += f"\n\nText in {kind}: {inner_text}"
    return kind, description
