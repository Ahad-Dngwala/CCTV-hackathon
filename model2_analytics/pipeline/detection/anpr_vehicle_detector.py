"""
ANPR Vehicle Detector (ANPR-SPECIFIC FORK — do not use from website/shared code)
================================================================================
This file is a fork of pipeline/detection/vehicle_detector.py (the SHARED
detector used by the website vehicle-detection feature — that file must stay
pristine). ALL ANPR-specific tuning lives ONLY here:

  - imgsz=960 (VEHICLE_DETECTION_IMGSZ) instead of hardcoded 480
  - per-class confidence thresholds (PER_CLASS_CONF_THRESHOLDS) applied after
    YOLO's single global conf floor
  - unmapped_class_threshold for class names not in the per-class table
  - runtime config confirmation logging

Class renamed VehicleDetector -> AnprVehicleDetector to avoid import ambiguity.
"""

import logging
import os
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np

# Auto-detect CUDA availability
try:
    import torch
    _CUDA_AVAILABLE = torch.cuda.is_available()
except ImportError:
    _CUDA_AVAILABLE = False

from pipeline.config import (
    PER_CLASS_CONF_THRESHOLDS,
    VEHICLE_DETECTION_IMGSZ,
)

logger = logging.getLogger("sentinel.anpr_detector")
logger.setLevel(logging.INFO)

# ── Weights path (inside Docker: /app/model2_analytics/pipeline/detection/) ────
_HERE = Path(__file__).resolve().parent
INDIAN_WEIGHTS = _HERE / "indian_traffic_yolov8.pt"
FALLBACK_MODEL = "yolov8n.pt"   # standard COCO — auto-downloaded by ultralytics

# HuggingFace mirror for Indian traffic weights
HF_URL = "https://huggingface.co/abrarhameem398/traffice-detection-best/resolve/main/best.pt"

# ── Indian traffic class normalization ─────────────────────────────
#    Maps raw model class names (lower) → clean display name
INDIAN_CLASS_MAP: Dict[str, str] = {
    "cng":        "Auto Rickshaw",
    "rickshaw":   "Auto Rickshaw",
    "auto":       "Auto Rickshaw",
    "bike":       "Motorcycle",
    "motorcycle": "Motorcycle",
    "scooter":    "Motorcycle",
    "car":        "Car",
    "bus":        "Bus",
    "truck":      "Truck",
    "mini-truck": "Mini-Truck",
    "minitruck":  "Mini-Truck",
    "van":        "Van",
    "cycle":      "Bicycle",
    "bicycle":    "Bicycle",
}

# ── COCO fallback class IDs (used when Indian model unavailable) ───
COCO_VEHICLE: Dict[int, str] = {
    2: "Car",
    3: "Motorcycle",
    5: "Bus",
    7: "Truck",
}


@dataclass
class RawDetection:
    """Single vehicle detection from one frame."""
    bbox:       Tuple[int, int, int, int]   # (x1, y1, x2, y2) absolute pixels
    confidence: float
    class_id:   int
    class_name: str
    crop:       Optional[np.ndarray] = None  # cropped BGR region


class AnprVehicleDetector:
    """
    Indian Traffic YOLO detector — ANPR fork.
    Uses indian_traffic_yolov8.pt when available; falls back to yolov8n.pt.
    Lazy-loads on first detect() call.
    """

    def __init__(
        self,
        confidence_threshold: float = 0.10,
        iou_threshold: float = 0.45,
        imgsz: int = VEHICLE_DETECTION_IMGSZ,
        device: Optional[str] = None,
        per_class_thresholds: Optional[Dict[str, float]] = None,
        unmapped_class_threshold: float = 0.30,
    ):
        self.confidence_threshold = confidence_threshold
        self.iou_threshold        = iou_threshold
        self.imgsz                = imgsz
        # Auto-detect CUDA: use GPU if available and not explicitly overridden
        if device is None:
            self.device = "cuda" if _CUDA_AVAILABLE else None
        else:
            self.device = device
        self.per_class_thresholds = per_class_thresholds if per_class_thresholds is not None else PER_CLASS_CONF_THRESHOLDS
        self.unmapped_class_threshold = unmapped_class_threshold

        self._model        = None
        self._is_indian    = False
        self._target_cls:  Optional[List[int]] = None

        logger.info(f"AnprVehicleDetector: device={'GPU (CUDA)' if self.device == 'cuda' else 'CPU'}, CUDA available={_CUDA_AVAILABLE}")

    # ── Weight resolution ──────────────────────────────────────────
    def _resolve_weights(self) -> str:
        if INDIAN_WEIGHTS.exists():
            logger.info(f"Using Indian traffic weights: {INDIAN_WEIGHTS}")
            return str(INDIAN_WEIGHTS)

        # Try downloading via huggingface_hub or urllib
        logger.info("indian_traffic_yolov8.pt not found — downloading from HuggingFace…")
        try:
            from huggingface_hub import hf_hub_download
            import shutil
            downloaded = hf_hub_download(repo_id="abrarhameem398/traffice-detection-best", filename="best.pt")
            shutil.copy2(downloaded, str(INDIAN_WEIGHTS))
            logger.info(f"Downloaded Indian traffic weights via HF Hub → {INDIAN_WEIGHTS}")
            return str(INDIAN_WEIGHTS)
        except Exception as hf_err:
            logger.warning(f"HF Hub download failed ({hf_err}), trying direct URL…")
            try:
                urllib.request.urlretrieve(HF_URL, str(INDIAN_WEIGHTS))
                logger.info(f"Downloaded Indian traffic weights → {INDIAN_WEIGHTS}")
                return str(INDIAN_WEIGHTS)
            except Exception as e:
                logger.warning(f"Download failed ({e}). Falling back to {FALLBACK_MODEL}.")
                return FALLBACK_MODEL

    # ── Model loading ──────────────────────────────────────────────
    def _load(self):
        if self._model is not None:
            return
        from ultralytics import YOLO

        weights = self._resolve_weights()
        logger.info(f"Loading YOLO model: {weights}")
        self._model = YOLO(weights)

        # Inspect class names — ACTUAL raw class_id -> class_name mapping
        names = self._model.names            # {id: name}
        logger.info(f"RAW MODEL NAMES (class_id -> class_name): {names}")

        # Detect whether this is the Indian traffic model
        indian_keys = {"cng", "rickshaw", "auto", "mini-truck", "minitruck"}
        if any(n in indian_keys for n in (str(v).lower() for v in names.values())):
            self._is_indian   = True
            # Only detect vehicles (filter out people/pedestrians)
            self._target_cls  = [
                idx for idx, name in names.items()
                if str(name).lower() not in {"people", "person", "human"}
            ]
            logger.info(f"✅ Indian Traffic model active — vehicle classes: {self._target_cls}")
        else:
            self._is_indian   = False
            self._target_cls  = sorted(COCO_VEHICLE.keys())
            logger.info(f"⚠️  COCO fallback model active — filtering classes: {self._target_cls}")

        # ── Runtime config confirmation log ────────────────────────
        logger.info(
            f"AnprVehicleDetector config: imgsz={self.imgsz}, "
            f"predict_conf={self.confidence_threshold}, "
            f"iou={self.iou_threshold}, "
            f"per_class_thresholds={self.per_class_thresholds}, "
            f"unmapped_class_threshold={self.unmapped_class_threshold}, "
            f"is_indian={self._is_indian}, target_cls={self._target_cls}"
        )

    # ── Inference ──────────────────────────────────────────────────
    def detect(self, frame: np.ndarray, pts_ms: float = 0.0) -> List[RawDetection]:
        """
        Run vehicle detection on a single BGR frame.
        Always returns a list — never raises.
        """
        if frame is None or frame.size == 0:
            return []

        try:
            self._load()
        except Exception as e:
            logger.error(f"Model load failed: {e}")
            return []

        try:
            results = self._model.predict(
                source=frame,
                imgsz=self.imgsz,
                conf=self.confidence_threshold,
                iou=self.iou_threshold,
                classes=self._target_cls,
                device=self.device,
                verbose=False,
            )
        except Exception as e:
            logger.warning(f"predict() failed: {e}")
            return []

        detections: List[RawDetection] = []
        if not results:
            return detections

        h, w = frame.shape[:2]
        boxes = results[0].boxes
        if boxes is None or len(boxes) == 0:
            return detections

        for box in boxes:
            cls_id = int(box.cls[0].item())
            conf   = float(box.conf[0].item())
            xyxy   = box.xyxy[0].tolist()

            x1 = max(0, int(xyxy[0]));  y1 = max(0, int(xyxy[1]))
            x2 = min(w, int(xyxy[2]));  y2 = min(h, int(xyxy[3]))

            if (x2 - x1) < 20 or (y2 - y1) < 20:
                continue

            crop = frame[y1:y2, x1:x2].copy()

            # ── Class name resolution ──────────────────────────────
            if self._is_indian:
                raw = str(self._model.names.get(cls_id, "vehicle")).lower()
                class_name = INDIAN_CLASS_MAP.get(raw, raw.title())
            else:
                class_name = COCO_VEHICLE.get(cls_id, "Vehicle")

            # ── Per-class confidence threshold ─────────────────────
            # predict() uses one global conf; apply per-class floor now.
            # Unmapped class names get unmapped_class_threshold (not the
            # permissive predict() floor).
            class_threshold = self.per_class_thresholds.get(class_name, self.unmapped_class_threshold)
            if conf < class_threshold:
                continue

            detections.append(RawDetection(
                bbox=(x1, y1, x2, y2),
                confidence=conf,
                class_id=cls_id,
                class_name=class_name,
                crop=crop,
            ))

        return detections
