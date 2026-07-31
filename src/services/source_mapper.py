"""Final assembly: ordering, hierarchy and document-level metadata.

Takes the per-page element lists produced by the extractors and builds
the :class:`ExtractedDocument`: global reading order, title promotion,
parent-section links and a lightweight language guess.
"""
from __future__ import annotations

import re
from collections import Counter
from datetime import datetime, timezone

from src.models import DocumentElement, ElementType, ExtractedDocument

# Tiny stopword sets - enough to tell the common cases apart without a
# language-detection dependency.
_STOPWORDS = {
    "en": {"the", "and", "of", "to", "in", "is", "for", "with", "that", "on"},
    "pt": {"de", "da", "do", "que", "em", "para", "com", "uma", "os", "não"},
    "es": {"de", "la", "el", "que", "en", "los", "por", "con", "una", "para"},
    "fr": {"de", "la", "le", "et", "les", "des", "en", "un", "une", "pour"},
    "de": {"der", "die", "und", "das", "von", "mit", "für", "ist", "den", "im"},
}


def guess_language(elements: list) -> str:
    """Best-effort ISO code from stopword frequency; '' when unclear."""
    words = Counter()
    for el in elements:
        for token in re.findall(r"[a-zà-öø-ÿ]+", el.content.lower())[:2000]:
            words[token] += 1
    if not words:
        return ""
    scores = {
        lang: sum(words[w] for w in stops) for lang, stops in _STOPWORDS.items()
    }
    best = max(scores, key=scores.get)
    return best if scores[best] >= 5 else ""


def _promote_title(elements: list) -> None:
    """The most prominent heading on page 1 becomes the document title."""
    first_page_headings = [
        el
        for el in elements
        if el.type == ElementType.HEADING
        and el.source
        and el.source.page == 1
    ]
    if not first_page_headings:
        return
    top = min(first_page_headings, key=lambda el: (el.level or 9, el.order))
    if (top.level or 9) <= 2:
        top.type = ElementType.TITLE
        top.level = None


def _assign_parents(elements: list) -> None:
    """Link every element to its enclosing section heading."""
    stack: list = []  # [(level, id)] of open headings
    for el in elements:
        if el.is_furniture:
            continue
        if el.type == ElementType.TITLE:
            stack = [(0, el.id)]
            continue
        if el.type == ElementType.HEADING:
            level = el.level or 6
            while stack and stack[-1][0] >= level:
                stack.pop()
            el.parent_id = stack[-1][1] if stack else None
            stack.append((level, el.id))
        else:
            el.parent_id = stack[-1][1] if stack else None


def finalize(
    file_name: str,
    page_count: int,
    pages_elements: dict,
    warnings: list,
    metadata: dict | None = None,
) -> ExtractedDocument:
    """Build the final document from per-page element lists."""
    elements: list[DocumentElement] = []
    for page in sorted(pages_elements):
        elements.extend(pages_elements[page])
    for order, el in enumerate(elements):
        el.order = order
    _promote_title(elements)
    _assign_parents(elements)
    return ExtractedDocument(
        file_name=file_name,
        page_count=page_count,
        processed_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        language=guess_language(elements),
        metadata=dict(metadata or {}),
        elements=elements,
        warnings=list(warnings),
    )
