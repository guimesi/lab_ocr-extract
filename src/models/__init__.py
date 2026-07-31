"""Data models for the PDF extraction editor.

Everything is a plain dataclass with ``to_dict``/``from_dict`` so the
whole document (elements, source references, revisions) round-trips
through JSON for exports and for ``st.session_state`` persistence.
"""
from src.models.source_reference import BoundingBox, SourceReference
from src.models.document_element import DocumentElement, ElementType
from src.models.document import ExtractedDocument
from src.models.revision import Revision, RevisionChange

__all__ = [
    "BoundingBox",
    "SourceReference",
    "DocumentElement",
    "ElementType",
    "ExtractedDocument",
    "Revision",
    "RevisionChange",
]
