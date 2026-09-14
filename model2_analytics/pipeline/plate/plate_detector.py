"""
License Plate Detector (YOLOv8)
================================
Downloads license_plate_detector.pt (from Muhammad-Zeerak-Khan's
Automatic-License-Plate-Recognition-using-YOLOv8) if not present.

Pipeline:
  raw frame -> YOLO plate detect -> (x1,y1,x2,y2,confidence) boxes

CHANGE vs. the previous version:
  detect() now takes an optional `retry_upscale` flag. If the first pass
  at self.imgsz finds nothing, it re-runs on a 1.5x upscaled copy of the
  frame before giving up. Small/distant plates are the single biggest
  source of "vehicle detected but plate never even found" in traffic
  footage, and YOLO detectors are sensitive to absolute pixel size of
  the target relative to imgsz -- a plate that's a handful of pixels
  wide at native resolution can clear the detector's minimum receptive
  field once the frame is upscaled, even with identical weights.
  This roughly doubles detector inference cost ONLY on frames where the
  first pass found zero plates, which in typical traffic footage with
  intermittent plate visibility is a minority of frames -- but you
  should confirm the FPS impact is acceptable in your setup (see
  TESTING.md). Disable with retry_upscale=False if it's not worth it.
"""

from __future__ import annotations

import logging
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np

logger = logging.getLogger("sentinel.plate_detector")
logger.setLevel(logging.INFO)


def _workspace_root() -> Path:
    """Walk up to the workspace root robustly (path depth differs between
    local checkout and Docker: /model2-analytics/pipeline/plate/...)."""
    p = Path(__file__).resolve()
    for ancestor in p.parents:
        if ancestor.name in ("HEHE", "model2-analytics") or ancestor == Path(ancestor.anchor):
            return ancestor.parent if ancestor.name == "model2-analytics" else ancestor
    return p.parents[-1]


_WORKSPACE = _workspace_root()
_WEIGHTS = Path(__file__).resolve().parent / "license_plate_detector.pt"

# Repo 2's trained YOLOv8 plate detector
PLATE_WEIGHTS_URL = (
    "https://raw.githubusercontent.com/Muhammad-Zeerak-Khan/"
    "Automatic-License-Plate-Recognition-using-YOLOv8/main/"
    "license_plate_detector.pt"
)

# Fallback location in shared /weights dir (same repo copy)
_WEIGHTS_SHARED = _WORKSPACE / "weights" / "license_plate_detector.pt"


@dataclass
class PlateDetection:
    """One license plate detected in a frame."""
    bbox:        Tuple[int, int, int, int]   # (x1, y1, x2, y2)
    confidence:  float


class PlateDetector:
    """
    YOLOv8 license-plate detector.
    Lazy-loads the model on first call; auto-downloads weights if missing.
    """

    def __init__(
        self,
        confidence_threshold: float = 0.20,  # lowered to detect more plates
        imgsz: int = 640,
        device: Optional[str] = None,
        model_path: Optional[str] = None,
        retry_upscale: bool = True,
    ):
        self.confidence_threshold = confidence_threshold
        self.imgsz                = imgsz
        self.device               = device
        self._model               = None
        self._custom_model_path   = model_path
        self.retry_upscale        = retry_upscale

    # ── Weight resolution ───────────────────────────────────────
    def _resolve_weights(self) -> Optional[str]:
        """Return a path to plate detector weights, downloading if needed."""
        if self._custom_model_path:
            p = Path(self._custom_model_path)
            if p.exists() and p.stat().st_size > 100_000:
                logger.info(f"Using custom plate model: {p}")
                return str(p)
            else:
                logger.warning(f"Custom model not found: {p}, falling back to default")

        candidates = [
            _WEIGHTS,
            _WEIGHTS_SHARED,
            _WORKSPACE / "weights" / "license_plate_detector.pt",
        ]
        for p in candidates:
            if p.exists() and p.stat().st_size > 100_000:   # 6.2 MB real file
                logger.info(f"Plate weights found: {p}")
                return str(p)

        logger.info("Plate weights missing — downloading from GitHub…")
        _WEIGHTS.parent.mkdir(parents=True, exist_ok=True)
        try:
            urllib.request.urlretrieve(PLATE_WEIGHTS_URL, str(_WEIGHTS))
            if _WEIGHTS.exists() and _WEIGHTS.stat().st_size > 100_000:
                logger.info(f"Downloaded plate weights → {_WEIGHTS}")
                return str(_WEIGHTS)
        except Exception as e:
            logger.error(f"Plate weight download failed: {e}")
        return None

    # ── Model load ──────────────────────────────────────────────
    def _load(self) -> None:
        if self._model is not None:
            return
        weights = self._resolve_weights()
        if weights is None:
            raise RuntimeError(
                "license_plate_detector.pt unavailable — "
                "cannot run plate detection."
            )
        from ultralytics import YOLO
        self._model = YOLO(weights)
        logger.info(f"Loaded plate detector: {Path(weights).name}")

    # ── Inference ───────────────────────────────────────────────
    def _run_once(self, frame: np.ndarray, scale: float = 1.0) -> List[PlateDetection]:
        """One YOLO pass, optionally on an upscaled copy of `frame`.
        Coordinates are mapped back to ORIGINAL frame space before return."""
        import cv2
        h0, w0 = frame.shape[:2]
        if scale != 1.0:
            work = cv2.resize(frame, (int(w0 * scale), int(h0 * scale)),
                               interpolation=cv2.INTER_CUBIC)
        else:
            work = frame
        h, w = work.shape[:2]

        try:
            results = self._model.predict(
                source=work,
                imgsz=self.imgsz,
                conf=self.confidence_threshold,
                iou=0.45,
                device=self.device,
                verbose=False,
            )
        except Exception as e:
            logger.warning(f"Plate predict() failed (scale={scale}): {e}")
            return []

        plates: List[PlateDetection] = []
        if not results:
            return plates
        boxes = results[0].boxes
        if boxes is None or len(boxes) == 0:
            return plates

        for box in boxes:
            conf = float(box.conf[0].item())
            xyxy = box.xyxy[0].tolist()
            # map back to original-frame coordinates
            x1 = max(0, int(xyxy[0] / scale));  y1 = max(0, int(xyxy[1] / scale))
            x2 = min(w0, int(xyxy[2] / scale));  y2 = min(h0, int(xyxy[3] / scale))

            if (x2 - x1) < 12 or (y2 - y1) < 8:
                continue

            plates.append(PlateDetection(bbox=(x1, y1, x2, y2), confidence=conf))

        return plates

    def detect(self, frame: np.ndarray) -> List[PlateDetection]:
        """
        Run plate detection on a full BGR frame.
        Returns up to N plate boxes; never raises.

        If the first pass finds nothing and retry_upscale is enabled,
        retries once on a 1.5x upscaled copy — see module docstring for
        why, and confirm the tradeoff is worth it for your footage.
        """
        if frame is None or frame.size == 0:
            return []
        try:
            self._load()
        except Exception as e:
            logger.error(f"Plate model load failed: {e}")
            return []

        plates = self._run_once(frame, scale=1.0)
        if not plates and self.retry_upscale:
            plates = self._run_once(frame, scale=1.5)
        return plates
