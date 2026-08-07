"""Source traceability: where an extracted element lives in the PDF."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class BoundingBox:
    """Axis-aligned rectangle in PDF page coordinates (points, origin at
    the top-left corner, as PyMuPDF reports them)."""

    x: float
    y: float
    width: float
    height: float

    @classmethod
    def from_rect(cls, x0: float, y0: float, x1: float, y1: float) -> "BoundingBox":
        """Build from the ``(x0, y0, x1, y1)`` corner form PyMuPDF uses."""
        return cls(x=x0, y=y0, width=max(0.0, x1 - x0), height=max(0.0, y1 - y0))

    @property
    def x1(self) -> float:
        return self.x + self.width

    @property
    def y1(self) -> float:
        return self.y + self.height

    def to_dict(self) -> dict:
        return {
            "x": round(self.x, 2),
            "y": round(self.y, 2),
            "width": round(self.width, 2),
            "height": round(self.height, 2),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "BoundingBox":
        return cls(
            x=float(data["x"]),
            y=float(data["y"]),
            width=float(data["width"]),
            height=float(data["height"]),
        )


@dataclass
class SourceReference:
    """Reference from an extracted element back to the original PDF.

    ``page`` is 1-based. ``bounding_box`` may be None when the location
    could not be determined. ``extraction_method`` records which pipeline
    stage produced the element (``native_text``, ``table_detection``,
    ``scanned_page``, ``authored``).
    ``confidence`` is 0..1 when the method provides one, else None.
    """

    page: int
    bounding_box: Optional[BoundingBox] = None
    extraction_method: str = "native_text"
    confidence: Optional[float] = None

    def to_dict(self) -> dict:
        return {
            "page": self.page,
            "bounding_box": self.bounding_box.to_dict() if self.bounding_box else None,
            "extraction_method": self.extraction_method,
            "confidence": self.confidence,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "SourceReference":
        bbox = data.get("bounding_box")
        return cls(
            page=int(data["page"]),
            bounding_box=BoundingBox.from_dict(bbox) if bbox else None,
            extraction_method=str(data.get("extraction_method", "native_text")),
            confidence=data.get("confidence"),
        )
