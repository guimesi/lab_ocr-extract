"""
Claude via Databricks Foundation Model API, through the OpenAI SDK.

Databricks serving endpoints expose an OpenAI-compatible API at
``<workspace-url>/serving-endpoints``; the personal access token is the
``api_key`` and the endpoint name (e.g. ``databricks-claude-sonnet-4-5``)
is the ``model``. Images travel as base64 data URIs in the standard
OpenAI vision content format, which Databricks forwards to Claude.
"""
from __future__ import annotations

import base64
import json
import re
from typing import Iterable, Iterator, Optional

import pandas as pd
from openai import OpenAI

from config.settings import SETTINGS

SYSTEM_PROMPT = (
    "You are an OCR and data-extraction assistant. You receive documents "
    "as images - one image per page, for PDFs - (invoices, receipts, "
    "tables, forms, screenshots) and must transcribe and structure their "
    "content faithfully. Never invent values: when a field is illegible, "
    "use null and say so. Respond in English, except when transcribing "
    "literal content from a document written in another language."
)


def get_client() -> OpenAI:
    if not SETTINGS.databricks_enabled:
        raise RuntimeError(
            "Databricks is not configured: set DATABRICKS_HOST and "
            "DATABRICKS_TOKEN in .env (see .env.example)."
        )
    return OpenAI(
        api_key=SETTINGS.databricks_token,
        base_url=f"{SETTINGS.databricks_host}/serving-endpoints",
    )


def image_content(image_bytes: bytes, mime_type: str) -> dict:
    """Build the OpenAI-format image content part (base64 data URI)."""
    b64 = base64.b64encode(image_bytes).decode("ascii")
    return {
        "type": "image_url",
        "image_url": {"url": f"data:{mime_type};base64,{b64}"},
    }


def stream_chat(
    messages: list[dict], system: Optional[str] = None
) -> Iterator[str]:
    """Stream a chat completion, yielding text deltas.

    ``messages`` follow the OpenAI format; the system prompt is
    prepended here so callers only manage the visible conversation
    (``system`` overrides the default OCR-oriented prompt).
    """
    client = get_client()
    stream = client.chat.completions.create(
        model=SETTINGS.databricks_model,
        messages=[
            {"role": "system", "content": system or SYSTEM_PROMPT},
            *messages,
        ],
        max_tokens=SETTINGS.llm_max_tokens,
        stream=True,
    )
    for chunk in stream:
        if chunk.choices and chunk.choices[0].delta.content:
            yield chunk.choices[0].delta.content


def complete(
    messages: list[dict], system: Optional[str] = None
) -> tuple[str, bool]:
    """Non-streaming completion.

    Returns ``(text, truncated)`` - ``truncated`` is True when the
    response hit the output-token limit (``finish_reason == "length"``),
    meaning the tail of the answer is missing. ``system`` overrides the
    default OCR-oriented system prompt.
    """
    client = get_client()
    resp = client.chat.completions.create(
        model=SETTINGS.databricks_model,
        messages=[
            {"role": "system", "content": system or SYSTEM_PROMPT},
            *messages,
        ],
        max_tokens=SETTINGS.llm_max_tokens,
    )
    choice = resp.choices[0]
    return choice.message.content or "", choice.finish_reason == "length"


# =============================================================================
# Structured extraction guided by a Snowflake table schema
# =============================================================================

def build_extraction_prompt(
    schema: pd.DataFrame,
    sample: Optional[pd.DataFrame],
    extra_instructions: str = "",
    guide: str = "",
    file_name: str = "",
) -> str:
    """Prompt asking for a JSON array of rows matching the table columns.

    ``schema`` is the DataFrame returned by
    :meth:`src.snowflake_client.SnowflakeClient.describe_table`.
    ``guide`` is optional domain guidance (a ``prompts/*.md`` file) that
    teaches the model how this document type maps onto the columns; it
    may add extra keys (e.g. a version label) on top of the schema.
    """
    col_lines = []
    for _, row in schema.iterrows():
        line = f"- {row['NAME']} ({row['TYPE']})"
        comment = str(row.get("COMMENT") or "").strip()
        if comment and comment.lower() != "none":
            line += f" — {comment}"
        col_lines.append(line)

    parts = [
        "Extract the data from the document (each image is one page) "
        "following the layout of the table below.",
        "Target table columns:",
        "\n".join(col_lines),
    ]
    if sample is not None and not sample.empty:
        parts.append(
            "Real sample rows from the table (follow the same formatting "
            "for dates, numbers and codes):\n"
            + sample.head(5).to_csv(index=False)
        )
    if file_name.strip():
        parts.append(
            f'Source file name: "{file_name.strip()}" - file names '
            "sometimes encode metadata such as a project id."
        )
    parts.append(
        "Answer ONLY with a JSON array of objects - one object per "
        "row/record identified in the document, with the keys above "
        "(uppercase). Extract every record you can identify, even "
        "if incomplete - use null for fields the document does not show "
        "or that are illegible. Only if the pages contain no extractable "
        "records at all, answer with an empty array: []. Do not include "
        "any explanation outside the JSON."
    )
    if guide.strip():
        parts.append(
            "Domain guidance for this document type - follow it closely; "
            "it explains where the data lives and how it maps onto the "
            "columns, and it may add extra keys on top of the schema:\n\n"
            + guide.strip()
        )
    if extra_instructions.strip():
        parts.append(f"Additional user instructions: {extra_instructions.strip()}")
    return "\n\n".join(parts)


def _repair_truncated_array(candidate: str) -> Optional[list]:
    """Recover the complete row objects from a truncated JSON array.

    When the response hits the output-token limit it stops mid-row; cut
    the text back to the last fully closed object and close the array,
    dropping the partial trailing row. Returns None when nothing
    parseable can be recovered.
    """
    if not candidate.lstrip().startswith("["):
        return None
    end = candidate.rfind("}")
    if end == -1:
        return None
    try:
        data = json.loads(candidate[: end + 1].rstrip().rstrip(",") + "]")
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, list) else None


def parse_rows_json(text: str, columns: Iterable[str]) -> pd.DataFrame:
    """Parse the model's JSON answer into a DataFrame with ``columns``.

    Tolerates a ```json fenced block or leading/trailing prose around
    the array; raises ``ValueError`` when no JSON array can be parsed.
    """
    candidate = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", candidate, re.DOTALL)
    if fence:
        candidate = fence.group(1).strip()
    if not candidate.startswith("["):
        start, end = candidate.find("["), candidate.rfind("]")
        if start == -1 or end <= start:
            raise ValueError("No JSON array found in the model response.")
        candidate = candidate[start : end + 1]
    try:
        data = json.loads(candidate)
    except json.JSONDecodeError as exc:
        data = _repair_truncated_array(candidate)
        if data is None:
            raise ValueError(
                f"Could not parse the model response as JSON ({exc.msg})."
            ) from exc
    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list):
        raise ValueError("The model response is not a JSON list.")
    if not data:
        return pd.DataFrame(columns=list(columns))
    df = pd.DataFrame(data)
    df.columns = [str(c).upper() for c in df.columns]
    ordered = [c for c in columns if c in df.columns]
    extras = [c for c in df.columns if c not in ordered]
    return df[ordered + extras]
