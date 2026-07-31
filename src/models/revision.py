"""Revision records for the edit history (undo/redo/diff)."""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class RevisionChange:
    """One element-level change inside a revision.

    ``before``/``after`` are full element dicts (``DocumentElement.to_dict``)
    or None: an insert has ``before=None``, a delete has ``after=None``.
    ``index`` is the element's position in the document list at the time
    of the change, so undo/redo can restore exact ordering.
    """

    op: str  # "update" | "insert" | "delete"
    index: int
    before: Optional[dict] = None
    after: Optional[dict] = None

    @property
    def element_id(self) -> str:
        source = self.after or self.before or {}
        return str(source.get("id", ""))

    def to_dict(self) -> dict:
        return {
            "op": self.op,
            "index": self.index,
            "before": self.before,
            "after": self.after,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "RevisionChange":
        return cls(
            op=str(data["op"]),
            index=int(data["index"]),
            before=data.get("before"),
            after=data.get("after"),
        )


@dataclass
class Revision:
    """One applied edit (AI or manual), possibly touching many elements."""

    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    timestamp: str = ""
    source: str = "manual"  # "manual" | "ai" | "restore"
    instruction: str = ""  # the user instruction that produced it, if any
    summary: str = ""
    changes: list = field(default_factory=list)  # list[RevisionChange]

    @property
    def affected_ids(self) -> list:
        return [c.element_id for c in self.changes]

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "timestamp": self.timestamp,
            "source": self.source,
            "instruction": self.instruction,
            "summary": self.summary,
            "affected_element_ids": self.affected_ids,
            "changes": [c.to_dict() for c in self.changes],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Revision":
        return cls(
            id=str(data.get("id", uuid.uuid4().hex[:8])),
            timestamp=str(data.get("timestamp", "")),
            source=str(data.get("source", "manual")),
            instruction=str(data.get("instruction", "")),
            summary=str(data.get("summary", "")),
            changes=[RevisionChange.from_dict(c) for c in data.get("changes", [])],
        )
