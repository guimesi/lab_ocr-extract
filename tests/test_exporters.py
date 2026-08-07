"""Export formats: Markdown passthrough, JSON payload, escaped HTML."""
import json

from src import exporters


def test_markdown_ends_with_newline():
    assert exporters.to_markdown("# Title") == "# Title\n"
    assert exporters.to_markdown("# Title\n") == "# Title\n"


def test_json_roundtrip():
    payload = json.loads(exporters.to_json("doc.pdf", "Hello & <world>"))
    assert payload == {"file_name": "doc.pdf", "text": "Hello & <world>"}


def test_html_escapes_content():
    html_out = exporters.to_html(
        "doc.pdf", "Hello <script>alert(1)</script>\n\nSecond & paragraph"
    )
    assert "<script>" not in html_out
    assert "&lt;script&gt;" in html_out
    assert html_out.count("<p>") == 2
    assert "Second &amp; paragraph" in html_out
