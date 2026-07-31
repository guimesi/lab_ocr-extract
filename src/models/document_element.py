"""A single extracted element (paragraph, heading, table, image, ...)."""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Optional

from src.models.source_reference import SourceReference


class ElementType:
    """Element type constants (plain strings so they serialize as-is)."""

    TITLE = "title"
    HEADING = "heading"
    PARAGRAPH = "paragraph"
    LIST = "list"
    TABLE = "table"
    IMAGE = "image"
    CHART = "chart"
    DIAGRAM = "diagram"
    CAPTION = "caption"
    HEADER = "header"
    FOOTER = "footer"
    PAGE_NUMBER = "page_number"

    ALL = (
        TITLE, HEADING, PARAGRAPH, LIST, TABLE, IMAGE, CHART,
        DIAGRAM, CAPTION, HEADER, FOOTER, PAGE_NUMBER,
    )
    # Page furniture: excluded from the main content flow and exports
    # unless the user explicitly asks for it.
    FURNITURE = (HEADER, FOOTER, PAGE_NUMBER)


def new_element_id() -> str:
    """Short unique id, stable for the lifetime of the document."""
    return uuid.uuid4().hex[:8]


@dataclass
class DocumentElement:
    """One unit of extracted content with its source mapping.

    ``content`` is Markdown-flavored text (tables are GitHub Markdown;
    images/charts hold their generated description). ``original_content``
    is filled the first time the element is edited so the pristine
    extraction is always recoverable per element. ``edited_by`` is None
    for untouched content, ``"ai"`` or ``"manual"`` after edits.
    """

    id: str
    type: str
    content: str
    source: Optional[SourceReference] = None
    order: int = 0
    level: Optional[int] = None
    parent_id: Optional[str] = None
    edited_by: Optional[str] = None
    original_content: Optional[str] = None
    table_data: Optional[list] = None  # list[list[str]] for tables
    metadata: dict = field(default_factory=dict)

    @property
    def edited(self) -> bool:
        return self.edited_by is not None

    @property
    def is_furniture(self) -> bool:
        return self.type in ElementType.FURNITURE

    def record_edit(self, new_content: str, edited_by: str) -> None:
        """Change content, preserving the first extracted version."""
        if self.original_content is None:
            self.original_content = self.content
        self.content = new_content
        self.edited_by = edited_by

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "type": self.type,
            "content": self.content,
            "source": self.source.to_dict() if self.source else None,
            "order": self.order,
            "level": self.level,
            "parent_id": self.parent_id,
            "edited_by": self.edited_by,
            "original_content": self.original_content,
            "table_data": self.table_data,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "DocumentElement":
        source = data.get("source")
        return cls(
            id=str(data["id"]),
            type=str(data["type"]),
            content=str(data.get("content", "")),
            source=SourceReference.from_dict(source) if source else None,
            order=int(data.get("order", 0)),
            level=data.get("level"),
            parent_id=data.get("parent_id"),
            edited_by=data.get("edited_by"),
            original_content=data.get("original_content"),
            table_data=data.get("table_data"),
            metadata=dict(data.get("metadata") or {}),
        )

    def copy(self) -> "DocumentElement":
        return DocumentElement.from_dict(self.to_dict())
