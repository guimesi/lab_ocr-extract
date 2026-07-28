"""
Cross-document pattern analysis for the template-authoring variation.

Everything the model sees is images, and several large PDFs never fit
one request - so each document goes through a map-reduce pass: page
batches are analyzed one model call at a time ("map"), then the
per-batch notes are consolidated into a single markdown *document
profile* ("reduce"). Chat and template generation run over those text
profiles instead of raw pages, which keeps the chat request size flat
no matter how many or how large the PDFs are.
"""
from __future__ import annotations

from typing import Callable, Optional

from src import llm_client

ANALYST_SYSTEM_PROMPT = (
    "You are a document-analysis assistant. You receive reference "
    "documents as images (one image per page) or as previously produced "
    "analysis notes, and your job is to understand their structure, "
    "content patterns and conventions well enough that a new document "
    "of the same kind could be authored from scratch. Be precise and "
    "grounded: describe only what the documents actually show, quote "
    "real section titles and field labels, and never invent content. "
    "Respond in English, unless the user writes in another language - "
    "then answer in that language."
)

# Canned chat message behind the "Generate template" quick action.
TEMPLATE_REQUEST = (
    "Based on the patterns shared across ALL the analyzed reference "
    "documents, write a complete authoring guide (template) for creating "
    "a new document of the same kind. Include:\n"
    "1. The required section structure, in order, with the purpose and "
    "expected content of each section.\n"
    "2. Formatting and layout conventions (titles, tables, headers/"
    "footers, page numbering, visual elements).\n"
    "3. Data conventions (date, number and identifier formats, "
    "terminology, units).\n"
    "4. Writing style and tone guidance.\n"
    "5. A fill-in-the-blanks skeleton of the document in markdown, with "
    "placeholders like {PROJECT_NAME}.\n"
    "6. A final checklist to validate a new document before publishing.\n"
    "Where the reference documents diverge from each other, point out "
    "the divergence and recommend one convention."
)


def _batch_prompt(doc_name: str, first: int, last: int, total: int) -> str:
    scope = (
        f"The attached images are pages {first}-{last} of the "
        f"{total}-page document."
        if total > 1
        else "The attached image is the full document."
    )
    return (
        f'You are analyzing the reference document "{doc_name}". {scope}\n\n'
        "Produce detailed analysis notes in markdown for these pages, "
        "covering:\n"
        "- **Structure**: sections and headings in order (quote the real "
        "titles), and how the content is organized within them.\n"
        "- **Layout & formatting**: page layout, headers/footers, logos, "
        "typography cues, numbering schemes, tables and their exact "
        "columns, fields and their labels.\n"
        "- **Content**: what information each section carries, and at "
        "what level of detail.\n"
        "- **Conventions**: date/number/identifier formats, units, "
        "terminology, language, writing style and tone.\n"
        "- **Recurring patterns**: any element that repeats across "
        "pages.\n\n"
        "These notes will later be merged with notes from other pages "
        "and other documents to derive a reusable authoring template, so "
        "be concrete and exhaustive - keep real titles, labels and "
        "format examples. Mark illegible fragments as [illegible]; never "
        "guess."
    )


def _consolidation_prompt(doc_name: str, total: int) -> str:
    return (
        f"Below are analysis notes produced for consecutive page ranges "
        f'of the {total}-page reference document "{doc_name}". Merge '
        "them into ONE coherent document profile in markdown: keep the "
        "document's overall order, deduplicate repeated observations, "
        "and preserve the concrete details (real section titles, field "
        "labels, table columns, format examples) - do not summarize away "
        "specifics that would be needed to recreate a document like "
        "this one."
    )


def analyze_document(
    doc_name: str,
    total_pages: int,
    batches: list[tuple[int, int, list[dict]]],
    progress: Optional[Callable[[str], None]] = None,
) -> str:
    """Analyze one document and return its markdown profile.

    ``batches`` is the output of ``page_batches()`` in ``app.py``:
    ``(first, last, image_parts)`` tuples, one model call each. With a
    single batch its notes are the profile; otherwise a final call
    consolidates the per-batch notes.
    """
    notes: list[tuple[int, int, str]] = []
    for first, last, parts in batches:
        if progress:
            progress(
                f"Analyzing {doc_name} - pages {first}-{last} of "
                f"{total_pages}..."
            )
        text, truncated = llm_client.complete(
            [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": _batch_prompt(
                                doc_name, first, last, total_pages
                            ),
                        },
                        *parts,
                    ],
                }
            ],
            system=ANALYST_SYSTEM_PROMPT,
        )
        if truncated:
            text += (
                "\n\n[Note: these notes hit the output-token limit and "
                "may be missing their tail.]"
            )
        notes.append((first, last, text))

    if len(notes) == 1:
        return notes[0][2]

    if progress:
        progress(f"Consolidating the analysis of {doc_name}...")
    joined = "\n\n".join(
        f"### Notes for pages {first}-{last}\n\n{text}"
        for first, last, text in notes
    )
    text, truncated = llm_client.complete(
        [
            {
                "role": "user",
                "content": (
                    _consolidation_prompt(doc_name, total_pages)
                    + "\n\n"
                    + joined
                ),
            }
        ],
        system=ANALYST_SYSTEM_PROMPT,
    )
    if truncated:
        text += (
            "\n\n[Note: this profile hit the output-token limit and may "
            "be missing its tail.]"
        )
    return text


def chat_context(profiles: dict[str, str]) -> str:
    """The text block carrying every document profile into the chat."""
    header = (
        f"You previously analyzed {len(profiles)} reference document(s) "
        "of the same kind; their detailed analysis profiles follow, one "
        "per document. Ground every answer in these profiles (and in the "
        "attached first-page images, included for visual reference). "
        "When the user asks for a template or authoring instructions, "
        "derive them from the patterns shared across ALL documents, "
        "noting where the documents diverge."
    )
    sections = [
        f"## Document: {name}\n\n{profile}"
        for name, profile in profiles.items()
    ]
    return "\n\n".join([header, *sections])
