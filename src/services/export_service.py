"""Exports: Markdown, structured JSON and standalone HTML.

All three read the *current* edited document. Page furniture (headers,
footers, page numbers) is excluded unless explicitly requested. HTML is
built from escaped text only - element content is never injected raw -
so generated pages are safe to open standalone.
"""
from __future__ import annotations

import html
import json
import re

from src.models import DocumentElement, ElementType, ExtractedDocument

# ----------------------------------------------------------------------
# Markdown
# ----------------------------------------------------------------------

def to_markdown(
    document: ExtractedDocument, include_furniture: bool = False
) -> str:
    """Clean Markdown of the current document, in reading order."""
    parts: list[str] = []
    for el in document.elements:
        if el.is_furniture and not include_furniture:
            continue
        parts.append(_markdown_block(el))
    return "\n\n".join(p for p in parts if p).strip() + "\n"


def _markdown_block(el: DocumentElement) -> str:
    page = el.source.page if el.source else None
    if el.type == ElementType.TITLE:
        return f"# {el.content}"
    if el.type == ElementType.HEADING:
        level = min(6, max(1, (el.level or 2)))
        return f"{'#' * level} {el.content}"
    if el.type in (ElementType.IMAGE, ElementType.CHART, ElementType.DIAGRAM):
        label = el.type.capitalize()
        where = f" (page {page})" if page else ""
        body = el.content or "*no description*"
        return f"> **{label}{where}:** {body}"
    if el.type == ElementType.CAPTION:
        return f"*{el.content}*"
    if el.type in (ElementType.HEADER, ElementType.FOOTER, ElementType.PAGE_NUMBER):
        return f"<!-- {el.type}: {el.content} -->"
    # paragraph, list, table: content is already Markdown
    return el.content


# ----------------------------------------------------------------------
# JSON
# ----------------------------------------------------------------------

def to_json(document: ExtractedDocument, revision_history: list) -> str:
    """Structured JSON per the export schema (document/content/revisions)."""
    payload = {
        "document": {
            "file_name": document.file_name,
            "page_count": document.page_count,
            "processed_at": document.processed_at,
            "language": document.language,
            "metadata": document.metadata,
            "warnings": document.warnings,
        },
        "content": [_json_element(el) for el in document.elements],
        "revision_history": revision_history,
    }
    return json.dumps(payload, indent=2, ensure_ascii=False)


def _json_element(el: DocumentElement) -> dict:
    source = None
    if el.source:
        source = {
            "page": el.source.page,
            "bounding_box": (
                el.source.bounding_box.to_dict()
                if el.source.bounding_box
                else None
            ),
            "extraction_method": el.source.extraction_method,
            "confidence": el.source.confidence,
        }
    item = {
        "id": el.id,
        "type": el.type,
        "content": el.content,
        "order": el.order,
        "level": el.level,
        "parent_id": el.parent_id,
        "source": source,
        "revision": {
            "edited": el.edited,
            "edited_by": el.edited_by,
            "original_content": el.original_content,
        },
    }
    if el.table_data is not None:
        item["table_data"] = el.table_data
    return item


# ----------------------------------------------------------------------
# HTML
# ----------------------------------------------------------------------

_HTML_CSS = """
  body { font-family: Georgia, 'Times New Roman', serif; line-height: 1.6;
         max-width: 46rem; margin: 2rem auto; padding: 0 1rem; color: #1a1a1a;
         background: #ffffff; }
  h1, h2, h3, h4, h5, h6 { font-family: 'Helvetica Neue', Arial, sans-serif;
         line-height: 1.25; margin-top: 1.8em; }
  table { border-collapse: collapse; margin: 1rem 0; width: 100%;
          font-size: 0.95rem; }
  th, td { border: 1px solid #b6b6b6; padding: 0.4rem 0.6rem; text-align: left; }
  th { background: #f0f0f0; }
  figure.visual { border-left: 4px solid #8a8a8a; background: #f7f7f7;
          margin: 1rem 0; padding: 0.7rem 1rem; }
  figure.visual .kind { font-weight: bold; font-family: Arial, sans-serif;
          font-size: 0.85rem; text-transform: uppercase; color: #555; }
  p.caption { font-style: italic; color: #555; font-size: 0.95rem; }
  ul, ol { padding-left: 1.6rem; }
"""

_MD_TABLE_DIVIDER = re.compile(r"^\s*\|?[\s:|-]+\|?\s*$")


def to_html(document: ExtractedDocument, include_furniture: bool = False) -> str:
    """A complete standalone HTML document (all content escaped)."""
    body: list[str] = []
    for el in document.elements:
        if el.is_furniture and not include_furniture:
            continue
        block = _html_block(el)
        if block:
            body.append(block)
    title = html.escape(document.file_name or "Extracted document")
    return (
        "<!DOCTYPE html>\n"
        '<html lang="' + html.escape(document.language or "en") + '">\n'
        "<head>\n"
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{title}</title>\n"
        f"<style>{_HTML_CSS}</style>\n"
        "</head>\n<body>\n"
        + "\n".join(body)
        + "\n</body>\n</html>\n"
    )


def _inline(text: str) -> str:
    """Escape text, then apply minimal Markdown inline styling."""
    escaped = html.escape(text)
    escaped = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)
    escaped = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"<em>\1</em>", escaped)
    return escaped


def _html_block(el: DocumentElement) -> str:
    if el.type == ElementType.TITLE:
        return f"<h1>{_inline(el.content)}</h1>"
    if el.type == ElementType.HEADING:
        level = min(6, max(1, (el.level or 2)))
        return f"<h{level}>{_inline(el.content)}</h{level}>"
    if el.type == ElementType.TABLE:
        return _html_table(el)
    if el.type == ElementType.LIST:
        return _html_list(el.content)
    if el.type in (ElementType.IMAGE, ElementType.CHART, ElementType.DIAGRAM):
        page = el.source.page if el.source else None
        where = f" (page {page})" if page else ""
        return (
            '<figure class="visual">'
            f'<div class="kind">{html.escape(el.type)}{where}</div>'
            f"<div>{_inline(el.content)}</div></figure>"
        )
    if el.type == ElementType.CAPTION:
        return f'<p class="caption">{_inline(el.content)}</p>'
    if el.type in ElementType.FURNITURE:
        return f'<p class="caption">{_inline(el.content)}</p>'
    paragraphs = [p for p in el.content.split("\n\n") if p.strip()]
    return "\n".join(f"<p>{_inline(p)}</p>" for p in paragraphs)


def _html_list(content: str) -> str:
    lines = [ln.strip() for ln in content.split("\n") if ln.strip()]
    ordered = bool(lines) and bool(re.match(r"^\d+[.)]", lines[0]))
    items = []
    for line in lines:
        text = re.sub(r"^(\d+[.)]|[-*•])\s*", "", line)
        items.append(f"<li>{_inline(text)}</li>")
    tag = "ol" if ordered else "ul"
    return f"<{tag}>\n" + "\n".join(items) + f"\n</{tag}>"


def _html_table(el: DocumentElement) -> str:
    rows = el.table_data or _rows_from_markdown(el.content)
    if not rows:
        return f"<p>{_inline(el.content)}</p>"
    head, *rest = rows
    out = ["<table>", "<thead><tr>"]
    out.extend(f"<th>{_inline(str(c))}</th>" for c in head)
    out.append("</tr></thead>")
    if rest:
        out.append("<tbody>")
        for row in rest:
            out.append(
                "<tr>" + "".join(f"<td>{_inline(str(c))}</td>" for c in row) + "</tr>"
            )
        out.append("</tbody>")
    out.append("</table>")
    return "".join(out)


def _rows_from_markdown(content: str) -> list:
    """Parse a GitHub Markdown table back into rows (for OCR tables)."""
    rows = []
    for line in content.split("\n"):
        line = line.strip()
        if not line.startswith("|") or _MD_TABLE_DIVIDER.match(line):
            continue
        cells = [c.strip().replace("\\|", "|") for c in line.strip("|").split("|")]
        rows.append(cells)
    return rows
