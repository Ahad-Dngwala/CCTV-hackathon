"""
Pluggable Plate Recognizer Interface
=====================================
Defines the abstract interface and PlateResult dataclass.
The PlateRecognizerStub has been removed — no fake plates.
All implementations must return real results or None.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple


@dataclass
class PlateResult:
    """
    Unified result from any ANPR/OCR provider.

    Attributes
    ----------
    plate_text:           Raw OCR output (may contain spaces or hyphens).
    normalized_text:      Cleaned, uppercase, alphanumeric-only plate string.
    confidence:           OCR confidence (0.0–1.0).
    detection_confidence: Plate detector confidence (0.0–1.0 or None if not available).
    bbox:                 Plate bounding box in the *original frame* coordinates
                          (x1, y1, x2, y2), or None if unavailable.
    crop:                 Numpy BGR image of the plate crop, or None.
    provider:             Identifier string for the ANPR provider used.
    """
    plate_text:           str
    normalized_text:      str
    confidence:           float
    detection_confidence: Optional[float]
    bbox:                 Optional[Tuple[int, int, int, int]]
    crop:                 Optional[object]   # numpy ndarray
    provider:             str


class PlateRecognizerInterface:
    """
    Abstract base class for all ANPR/OCR engines.

    Implementations must:
    - Return a PlateResult when a reliable plate read is obtained.
    - Return None when no plate can be confidently read.
    - Never raise exceptions (catch internally and return None).
    - Never return fabricated or stub plate values.
    """

    def recognize(
        self,
        frame,                              # numpy BGR frame (full resolution)
        vehicle_bbox: Tuple[int, int, int, int],  # (x1, y1, x2, y2)
        timestamp_ms: float = 0.0,
    ) -> Optional[PlateResult]:
        raise NotImplementedError
