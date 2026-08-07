"""Turn the edited text into the three download formats."""
from __future__ import annotations

import html
import json

_HTML_TEMPLATE = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>{title}</title>
<style>
body {{ max-width: 48rem; margin: 2rem auto; padding: 0 1rem;
       font-family: Georgia, serif; line-height: 1.6; }}
</style>
</head>
<body>
{body}
</body>
</html>
"""


def to_markdown(text: str) -> str:
    return text if text.endswith("\n") else text + "\n"


def to_json(file_name: str, text: str) -> str:
    return json.dumps(
        {"file_name": file_name, "text": text},
        ensure_ascii=False,
        indent=2,
    )


def to_html(file_name: str, text: str) -> str:
    """Standalone HTML page; all content is escaped, never injected raw."""
    paragraphs = [
        "<p>" + html.escape(chunk).replace("\n", "<br>\n") + "</p>"
        for chunk in text.split("\n\n")
        if chunk.strip()
    ]
    return _HTML_TEMPLATE.format(
        title=html.escape(file_name),
        body="\n".join(paragraphs) or "<p></p>",
    )
