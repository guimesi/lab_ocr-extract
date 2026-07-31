"""Smoke test: the Streamlit script runs without raising (no upload)."""
from pathlib import Path

from streamlit.testing.v1 import AppTest

APP = Path(__file__).resolve().parent.parent / "app.py"


def test_app_renders_upload_state():
    at = AppTest.from_file(str(APP), default_timeout=30)
    at.run()
    assert not at.exception
    # The no-document state shows the upload hint.
    assert any("Upload a PDF" in str(info.value) for info in at.info)
