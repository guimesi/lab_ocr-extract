"""Shared helpers for model calls: retry policy and tolerant JSON parsing.

Every service that talks to the model (OCR, visual analysis, chat) goes
through :func:`complete_with_retry` so rate limits are handled in one
place. The Databricks limit is per *minute*, so 429s back off through
increasing waits with jitter; other errors get one immediate retry.
"""
from __future__ import annotations

import json
import logging
import random
import re
import time
from typing import Optional

from src import llm_client

logger = logging.getLogger(__name__)

_RATE_LIMIT_WAITS = (15, 30, 60, 90)


class LLMError(Exception):
    """A model call failed after retries; message is safe to display."""


def _is_rate_limit(exc: Exception) -> bool:
    if getattr(exc, "status_code", None) == 429:
        return True
    text = str(exc)
    return (
        "429" in text
        or "REQUEST_LIMIT_EXCEEDED" in text
        or "rate limit" in text.lower()
    )


def complete_with_retry(
    messages: list, system: Optional[str] = None
) -> tuple[str, bool]:
    """Non-streaming completion with backoff; returns ``(text, truncated)``."""
    rate_limit_attempt = 0
    other_attempt = 0
    while True:
        try:
            return llm_client.complete(messages, system=system)
        except Exception as exc:
            if _is_rate_limit(exc):
                if rate_limit_attempt >= len(_RATE_LIMIT_WAITS):
                    raise LLMError(f"Model rate limit not recovering: {exc}") from exc
                wait = _RATE_LIMIT_WAITS[rate_limit_attempt]
                logger.info("429 from model; backing off %ss", wait)
                time.sleep(wait * (0.8 + 0.4 * random.random()))
                rate_limit_attempt += 1
            else:
                if other_attempt >= 1:
                    raise LLMError(f"Model call failed: {exc}") from exc
                logger.info("Model call failed (%s); retrying once", exc)
                other_attempt += 1


def parse_json_payload(text: str):
    """Extract and parse the first JSON value (object or array) in ``text``.

    Tolerates ```json fences and prose around the payload. Raises
    ``ValueError`` when nothing parseable is found.
    """
    candidate = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", candidate, re.DOTALL)
    if fence:
        candidate = fence.group(1).strip()
    if not candidate.startswith(("[", "{")):
        starts = [i for i in (candidate.find("["), candidate.find("{")) if i != -1]
        if not starts:
            raise ValueError("No JSON payload found in the model response.")
        start = min(starts)
        closer = "]" if candidate[start] == "[" else "}"
        end = candidate.rfind(closer)
        if end <= start:
            raise ValueError("No complete JSON payload in the model response.")
        candidate = candidate[start : end + 1]
    try:
        return json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Could not parse the model response as JSON ({exc.msg})."
        ) from exc
