"""The extracted document: metadata plus the ordered element list."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterator, Optional

from src.models.document_element import DocumentElement


@dataclass
class ExtractedDocument:
    """Full extraction result for one PDF.

    ``elements`` are in reading order. ``warnings`` collects non-fatal
    pipeline problems (failed OCR on a page, undetected tables, ...) so
    the UI can surface a "completed with warnings" state.
    """

    file_name: str
    page_count: int
    processed_at: str = ""
    language: str = ""
    metadata: dict = field(default_factory=dict)
    elements: list = field(default_factory=list)  # list[DocumentElement]
    warnings: list = field(default_factory=list)  # list[str]

    def get(self, element_id: str) -> Optional[DocumentElement]:
        for el in self.elements:
            if el.id == element_id:
                return el
        return None

    def index_of(self, element_id: str) -> int:
        for i, el in enumerate(self.elements):
            if el.id == element_id:
                return i
        return -1

    def body_elements(self) -> Iterator[DocumentElement]:
        """Elements that belong to the content flow (no page furniture)."""
        return (el for el in self.elements if not el.is_furniture)

    def elements_on_page(self, page: int) -> Iterator[DocumentElement]:
        return (
            el for el in self.elements if el.source and el.source.page == page
        )

    def to_dict(self) -> dict:
        return {
            "file_name": self.file_name,
            "page_count": self.page_count,
            "processed_at": self.processed_at,
            "language": self.language,
            "metadata": self.metadata,
            "elements": [el.to_dict() for el in self.elements],
            "warnings": list(self.warnings),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ExtractedDocument":
        return cls(
            file_name=str(data.get("file_name", "")),
            page_count=int(data.get("page_count", 0)),
            processed_at=str(data.get("processed_at", "")),
            language=str(data.get("language", "")),
            metadata=dict(data.get("metadata") or {}),
            elements=[
                DocumentElement.from_dict(el) for el in data.get("elements", [])
            ],
            warnings=list(data.get("warnings", [])),
        )

    def copy(self) -> "ExtractedDocument":
        return ExtractedDocument.from_dict(self.to_dict())
