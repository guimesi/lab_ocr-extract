"""Document editing with full revision history, undo and redo.

The editor owns two documents: the pristine original extraction (never
mutated after construction) and the current working copy. Every change -
AI or manual - is applied through :meth:`DocumentEditor.apply_operations`
which records a :class:`Revision` with per-element before/after
snapshots, so undo/redo restore exact content *and* ordering.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from src.models import DocumentElement, ExtractedDocument, Revision, RevisionChange
from src.models.document_element import ElementType, new_element_id
from src.models.source_reference import SourceReference

logger = logging.getLogger(__name__)


class EditError(Exception):
    """An edit could not be applied; message is safe to display."""


@dataclass
class EditOperation:
    """One requested change.

    ``op`` is ``update`` (replace content of ``element_id``),
    ``insert_after`` / ``insert_before`` (new element anchored at
    ``element_id``) or ``delete``.
    """

    op: str
    element_id: str
    content: Optional[str] = None
    element_type: str = ElementType.PARAGRAPH
    level: Optional[int] = None

    VALID_OPS = ("update", "insert_after", "insert_before", "delete")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class DocumentEditor:
    """Holds the working document plus undo/redo stacks."""

    def __init__(self, document: ExtractedDocument):
        self.original: ExtractedDocument = document.copy()
        self.document: ExtractedDocument = document
        self._undo: list[Revision] = []
        self._redo: list[Revision] = []

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    @property
    def history(self) -> list:
        """Applied revisions, oldest first."""
        return list(self._undo)

    @property
    def can_undo(self) -> bool:
        return bool(self._undo)

    @property
    def can_redo(self) -> bool:
        return bool(self._redo)

    def revision_history_dicts(self) -> list:
        return [rev.to_dict() for rev in self._undo]

    # ------------------------------------------------------------------
    # Applying edits
    # ------------------------------------------------------------------

    def apply_operations(
        self,
        operations: list,
        source: str,
        instruction: str = "",
        summary: str = "",
    ) -> Revision:
        """Apply operations sequentially and record one revision.

        ``source`` is ``"ai"`` or ``"manual"``. Raises :class:`EditError`
        (without partial application) when any operation is invalid.
        """
        if not operations:
            raise EditError("No changes to apply.")
        self._validate(operations)

        elements = self.document.elements
        changes: list[RevisionChange] = []
        for op in operations:
            index = self.document.index_of(op.element_id)
            if index == -1:
                # Element vanished mid-batch (e.g. deleted twice).
                self._rollback(changes)
                raise EditError(
                    f"Element {op.element_id} is no longer in the document."
                )
            if op.op == "update":
                element = elements[index]
                before = element.to_dict()
                element.record_edit(
                    op.content or "", "ai" if source == "ai" else "manual"
                )
                if op.level is not None:
                    element.level = op.level
                changes.append(
                    RevisionChange("update", index, before, element.to_dict())
                )
            elif op.op in ("insert_after", "insert_before"):
                anchor = elements[index]
                new_element = DocumentElement(
                    id=new_element_id(),
                    type=op.element_type or ElementType.PARAGRAPH,
                    content=op.content or "",
                    level=op.level,
                    parent_id=anchor.parent_id,
                    edited_by="ai" if source == "ai" else "manual",
                    source=SourceReference(
                        page=anchor.source.page if anchor.source else 1,
                        bounding_box=None,
                        extraction_method="authored",
                    ),
                )
                insert_at = index + (1 if op.op == "insert_after" else 0)
                elements.insert(insert_at, new_element)
                changes.append(
                    RevisionChange("insert", insert_at, None, new_element.to_dict())
                )
            elif op.op == "delete":
                removed = elements.pop(index)
                changes.append(
                    RevisionChange("delete", index, removed.to_dict(), None)
                )
        self._renumber()

        revision = Revision(
            timestamp=_now(),
            source=source,
            instruction=instruction,
            summary=summary or self._default_summary(changes),
            changes=changes,
        )
        self._undo.append(revision)
        self._redo.clear()
        logger.info(
            "Applied revision %s (%s): %d change(s)",
            revision.id, source, len(changes),
        )
        return revision

    def _validate(self, operations: list) -> None:
        for op in operations:
            if op.op not in EditOperation.VALID_OPS:
                raise EditError(f'Unknown operation "{op.op}".')
            if self.document.get(op.element_id) is None:
                raise EditError(
                    f'The change references element "{op.element_id}", which '
                    "does not exist in the document."
                )
            if op.op != "delete" and op.content is None:
                raise EditError(
                    f'Operation "{op.op}" on {op.element_id} has no content.'
                )

    def _rollback(self, changes: list) -> None:
        """Revert partially applied changes after a mid-batch failure."""
        for change in reversed(changes):
            self._revert_change(change)
        self._renumber()

    # ------------------------------------------------------------------
    # Undo / redo / restore
    # ------------------------------------------------------------------

    def undo(self) -> Optional[Revision]:
        if not self._undo:
            return None
        revision = self._undo.pop()
        for change in reversed(revision.changes):
            self._revert_change(change)
        self._renumber()
        self._redo.append(revision)
        return revision

    def redo(self) -> Optional[Revision]:
        if not self._redo:
            return None
        revision = self._redo.pop()
        for change in revision.changes:
            self._apply_change(change)
        self._renumber()
        self._undo.append(revision)
        return revision

    def restore_original(self) -> None:
        """Reset the working copy to the pristine extraction.

        Clears the undo/redo stacks - the original extraction is the
        canonical baseline, so history before the reset no longer
        applies.
        """
        self.document = self.original.copy()
        self._undo.clear()
        self._redo.clear()

    def _revert_change(self, change: RevisionChange) -> None:
        elements = self.document.elements
        if change.op == "update":
            elements[change.index] = DocumentElement.from_dict(change.before)
        elif change.op == "insert":
            elements.pop(change.index)
        elif change.op == "delete":
            elements.insert(change.index, DocumentElement.from_dict(change.before))

    def _apply_change(self, change: RevisionChange) -> None:
        elements = self.document.elements
        if change.op == "update":
            elements[change.index] = DocumentElement.from_dict(change.after)
        elif change.op == "insert":
            elements.insert(change.index, DocumentElement.from_dict(change.after))
        elif change.op == "delete":
            elements.pop(change.index)

    def _renumber(self) -> None:
        for order, element in enumerate(self.document.elements):
            element.order = order

    @staticmethod
    def _default_summary(changes: list) -> str:
        ops = [c.op for c in changes]
        parts = []
        for kind, label in (("update", "updated"), ("insert", "added"), ("delete", "removed")):
            count = ops.count(kind)
            if count:
                parts.append(f"{count} element(s) {label}")
        return ", ".join(parts) or "No-op"
