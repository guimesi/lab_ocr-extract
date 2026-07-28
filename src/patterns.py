"""
Cross-document pattern analysis for the template-authoring variation.

Everything the model sees is images, and several large PDFs never fit
one request - so each document goes through a map-reduce pass: page
batches are analyzed one model call each ("map"), then the per-batch
notes are consolidated into a single markdown *document profile*
("reduce"). Chat and template generation run over those text profiles
instead of raw pages, which keeps the chat request size flat no matter
how many or how large the PDFs are.

``analyze_documents`` orchestrates the whole run in parallel: every
page batch of every document goes into one shared queue served by
``LLM_CONCURRENCY`` worker threads (the calls are pure I/O), and a
document's consolidation call is submitted as soon as *its* batches
finish - no document waits for the others.
"""
from __future__ import annotations

from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
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


def _complete_with_retry(messages: list[dict], truncation_note: str) -> str:
    """One analysis call, retried once on any error (transient network /
    throttling hiccups are common when several calls run in parallel)."""
    try:
        text, truncated = llm_client.complete(
            messages, system=ANALYST_SYSTEM_PROMPT
        )
    except Exception:
        text, truncated = llm_client.complete(
            messages, system=ANALYST_SYSTEM_PROMPT
        )
    if truncated:
        text += f"\n\n[Note: {truncation_note}]"
    return text


def _batch_notes(
    doc_name: str, total_pages: int, first: int, last: int, parts: list[dict]
) -> str:
    return _complete_with_retry(
        [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": _batch_prompt(doc_name, first, last, total_pages),
                    },
                    *parts,
                ],
            }
        ],
        "these notes hit the output-token limit and may be missing "
        "their tail.",
    )


def _consolidated_profile(doc_name: str, total_pages: int, joined: str) -> str:
    return _complete_with_retry(
        [
            {
                "role": "user",
                "content": (
                    _consolidation_prompt(doc_name, total_pages) + "\n\n" + joined
                ),
            }
        ],
        "this profile hit the output-token limit and may be missing "
        "its tail.",
    )


def analyze_documents(
    docs: dict[str, tuple[int, list[tuple[int, int, list[dict]]]]],
    concurrency: int = 6,
    progress: Optional[Callable[[int, int, str], None]] = None,
) -> tuple[dict[str, str], list[str]]:
    """Analyze every document in parallel; return ``(profiles, warnings)``.

    ``docs`` maps file name -> ``(total_pages, batches)``, where
    ``batches`` is the output of ``page_batches()`` in ``app.py``. All
    page batches of all documents share one pool of ``concurrency``
    worker threads; each document's consolidation call is submitted the
    moment its own batches are done. ``progress(done, total, label)`` is
    invoked from the calling thread only, so it is safe to update
    Streamlit widgets from it.

    A batch that fails (after one retry) becomes a placeholder note
    inside the profile instead of sinking the whole document; a failed
    consolidation falls back to the concatenated batch notes. Both are
    reported in ``warnings``.
    """
    total_steps = sum(
        len(batches) + (1 if len(batches) > 1 else 0)
        for _, batches in docs.values()
    )
    done = 0
    notes: dict[str, list[Optional[str]]] = {
        name: [None] * len(batches) for name, (_, batches) in docs.items()
    }
    remaining = {name: len(batches) for name, (_, batches) in docs.items()}
    results: dict[str, str] = {}
    warnings: list[str] = []

    def report(label: str) -> None:
        if progress:
            progress(done, total_steps, f"{label} ({done}/{total_steps} steps)")

    def joined_notes(name: str) -> str:
        ranges = [(f, l) for f, l, _ in docs[name][1]]
        return "\n\n".join(
            f"### Notes for pages {first}-{last}\n\n{text}"
            for (first, last), text in zip(ranges, notes[name])
        )

    with ThreadPoolExecutor(max_workers=max(1, concurrency)) as pool:
        tasks: dict[Future, tuple] = {}
        for name, (total_pages, batches) in docs.items():
            for idx, (first, last, parts) in enumerate(batches):
                fut = pool.submit(
                    _batch_notes, name, total_pages, first, last, parts
                )
                tasks[fut] = ("batch", name, idx, first, last)

        pending = set(tasks)
        while pending:
            finished, pending = wait(pending, return_when=FIRST_COMPLETED)
            for fut in finished:
                kind, name, *rest = tasks.pop(fut)
                done += 1
                if kind == "batch":
                    idx, first, last = rest
                    exc = fut.exception()
                    if exc is None:
                        notes[name][idx] = fut.result()
                        report(f"{name}: pages {first}-{last} analyzed")
                    else:
                        notes[name][idx] = (
                            f"[Analysis of pages {first}-{last} failed: {exc}]"
                        )
                        warnings.append(
                            f"{name}: pages {first}-{last} could not be "
                            f"analyzed ({exc}); the profile marks them as "
                            "missing."
                        )
                        report(f"{name}: pages {first}-{last} failed")
                    remaining[name] -= 1
                    if remaining[name] == 0:
                        if len(notes[name]) == 1:
                            results[name] = notes[name][0]
                        else:
                            cfut = pool.submit(
                                _consolidated_profile,
                                name,
                                docs[name][0],
                                joined_notes(name),
                            )
                            tasks[cfut] = ("consolidate", name)
                            pending.add(cfut)
                else:  # consolidate
                    exc = fut.exception()
                    if exc is None:
                        results[name] = fut.result()
                        report(f"{name}: profile consolidated")
                    else:
                        results[name] = joined_notes(name)
                        warnings.append(
                            f"{name}: consolidation failed ({exc}); using "
                            "the raw per-batch notes as the profile."
                        )
                        report(f"{name}: consolidation failed")

    # Keep the upload order in the returned profiles.
    return {name: results[name] for name in docs if name in results}, warnings


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
