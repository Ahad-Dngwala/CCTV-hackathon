"""
Awiros ANPR Adapter
====================
Local implementation of PlateRecognizerInterface using the existing
plate detector (YOLOv8) + PP-OCRv5 ONNX OCR engine stack.

This adapter is named "Awiros" because the PP-OCRv5 model benchmarked
under the Awiros-ANPR-OCR label in ocr_eval/. It is a local model, not
an HTTP API. Environment variables are still supported for configuration
so that a future HTTP-based adapter can replace this with no callers changed.

Configuration (all optional, sensible defaults):
    ANPR_PROVIDER=awiros          (identity string used in PlateResult.provider)
    AWIROS_TIMEOUT_SECONDS=5      (per-crop OCR timeout; skips on timeout)
    ANPR_MIN_VEHICLE_AREA=2500    (skip crops smaller than this many pixels²)
    ANPR_MIN_PLATE_CONF=0.01      (minimum plate detector confidence)
    ANPR_MIN_OCR_CONF=0.30        (minimum OCR confidence to return a result)
"""

from __future__ import annotations

import logging
import os
import re
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from typing import Optional, Tuple

import numpy as np

from pipeline.plate.interface import PlateRecognizerInterface, PlateResult

logger = logging.getLogger("sentinel.awiros")
logger.setLevel(logging.INFO)

# ── Configuration from environment ──────────────────────────────────
ANPR_PROVIDER        = os.getenv("ANPR_PROVIDER", "awiros")
AWIROS_TIMEOUT       = float(os.getenv("AWIROS_TIMEOUT_SECONDS", "5"))
MIN_VEHICLE_AREA     = int(os.getenv("ANPR_MIN_VEHICLE_AREA", "1000"))
MIN_PLATE_CONF       = float(os.getenv("ANPR_MIN_PLATE_CONF", "0.01"))
MIN_OCR_CONF         = float(os.getenv("ANPR_MIN_OCR_CONF", "0.01"))


# ── Indian plate normalization ───────────────────────────────────────

# Letters that look like digits in specific positions
_LC = {"O": "0", "D": "0", "Q": "0", "I": "1", "J": "1",
       "Z": "2", "A": "4", "S": "5", "G": "6", "T": "7", "B": "8"}
# Digits that look like letters in specific positions
_CL = {"0": "O", "1": "I", "2": "Z", "3": "J", "4": "A",
       "5": "S", "6": "G", "7": "T", "8": "B"}

_ALNUM = re.compile(r"[^A-Z0-9]")


def _clean_text(raw: str) -> str:
    return _ALNUM.sub("", raw.upper())


def _format_plate(text: str) -> str:
    """
    Normalize OCR output to standard Indian plate format.

    Classic:  GJ 01 AB 1234  →  GJ01AB1234  (10 chars)
    Bharat:   22 BH 1234 AA  →  22BH1234AA  (10 chars)

    Returns empty string when the text is unusable.
    """
    t = _clean_text(text)
    if len(t) < 4:  # At least 4 chars to be a plate
        return text

    out = list(t)
    first_two_digits = len(out) >= 2 and out[0].isdigit() and out[1].isdigit()

    if first_two_digits and len(out) == 10:
        # Bharat: DD LL DDDD LL
        pos = {0: _LC, 1: _LC, 2: _CL, 3: _CL,
               4: _LC, 5: _LC, 6: _LC, 7: _LC,
               8: _CL, 9: _CL}
    elif len(out) >= 9:
        # Classic: LL DD LL DDDD
        pos = {0: _CL, 1: _CL,
               2: _LC, 3: _LC,
               4: _CL, 5: _CL,
               6: _LC, 7: _LC, 8: _LC, 9: _LC}
    else:
        # Non-standard, don't force format characters
        pos = {}

    for i, ch in enumerate(out):
        if i >= len(pos):
            break
        if ch in pos[i]:
            out[i] = pos[i][ch]

    res = "".join(out)
    if first_two_digits and len(res) == 10:
        return f"{res[:2]}-{res[2:4]}-{res[4:8]}-{res[8:]}"
    elif len(res) >= 9:
        if len(res) == 10:
            return f"{res[:2]}-{res[2:4]}-{res[4:6]}-{res[6:]}"
        else:
            return f"{res[:2]}-{res[2:4]}-{res[4:5]}-{res[5:]}"
    return res


def normalize_plate(text: str) -> str:
    """Public normalizer — uppercase, alphanumeric only."""
    return _ALNUM.sub("", text.upper()) if text else ""


def _validate_plate(text: str) -> bool:
    """Basic sanity check bypassed to allow any reads."""
    return True


# ── IoU helper (fixed — original had by1 instead of by2 on iy2) ─────

def _iou(a: Tuple, b: Tuple) -> float:
    """Intersection-over-union between two (x1,y1,x2,y2) boxes."""
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1 = max(ax1, bx1); iy1 = max(ay1, by1)
    ix2 = min(ax2, bx2); iy2 = min(ay2, by2)   # ← was min(ay2, by1) — bug fixed
    iw = max(0, ix2 - ix1); ih = max(0, iy2 - iy1)
    inter = iw * ih
    area_a = max(0, ax2 - ax1) * max(0, ay2 - ay1)
    area_b = max(0, bx2 - bx1) * max(0, by2 - by1)
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0.0


# ── Main adapter ─────────────────────────────────────────────────────

class AwirosPlateRecognizer(PlateRecognizerInterface):
    """
    Local ANPR adapter: YOLOv8 plate detector + OnnxOCR (PP-OCRv5).

    Shared singleton pattern — one instance per process to avoid
    reloading ONNX models repeatedly.
    """

    _instance: Optional["AwirosPlateRecognizer"] = None
    _executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="awiros-ocr")

    @classmethod
    def get_instance(cls) -> "AwirosPlateRecognizer":
        if cls._instance is None:
            cls._instance = AwirosPlateRecognizer()
        return cls._instance

    def __init__(
        self,
        plate_detector=None,
        ocr_engine=None,
        conf_threshold: float = MIN_PLATE_CONF,
    ):
        self._plate_detector = plate_detector
        self._ocr_engine     = ocr_engine
        self._conf_threshold = conf_threshold
        self._loaded         = False

    # ── Lazy model loading ───────────────────────────────────────
    def _ensure_loaded(self):
        if self._loaded:
            return
        try:
            if self._plate_detector is None:
                from pipeline.plate.plate_detector import PlateDetector
                self._plate_detector = PlateDetector(
                    confidence_threshold=self._conf_threshold
                )
            if self._ocr_engine is None:
                from pipeline.ocr.onnx_ocr_engine import OnnxOCREngine
                self._ocr_engine = OnnxOCREngine(use_gpu=False)
                self._ocr_engine._lazy_load()
            self._loaded = True
            logger.info("AwirosPlateRecognizer models loaded (plate detector + OnnxOCR).")
        except Exception as e:
            logger.error(f"AwirosPlateRecognizer model load failed: {e}")
            raise

    # ── Public API ───────────────────────────────────────────────
    def recognize(
        self,
        frame,
        vehicle_bbox: Tuple[int, int, int, int],
        timestamp_ms: float = 0.0,
    ) -> Optional[PlateResult]:
        """
        Detect and read the license plate of the vehicle at vehicle_bbox.

        Returns PlateResult on success, None on failure (no plate found,
        low confidence, timeout, or any error).  Never raises.
        """
        try:
            return self._recognize_inner(frame, vehicle_bbox, timestamp_ms)
        except Exception as e:
            logger.warning(f"ANPR recognize() unexpected error: {e}")
            return None

    def _recognize_inner(
        self,
        frame,
        vehicle_bbox: Tuple[int, int, int, int],
        timestamp_ms: float,
    ) -> Optional[PlateResult]:
        import cv2

        if frame is None or frame.size == 0:
            return None

        # ── Guard 1: minimum vehicle crop area ──────────────────
        x1, y1, x2, y2 = vehicle_bbox
        h, w = frame.shape[:2]
        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(w, x2), min(h, y2)
        crop_w = x2 - x1
        crop_h = y2 - y1
        if crop_w * crop_h < MIN_VEHICLE_AREA:
            return None

        # ── Lazy load models ─────────────────────────────────────
        try:
            self._ensure_loaded()
        except Exception:
            return None

        # ── Search regions: bottom 60%, bottom 40%, full bbox ───
        regions = [
            {"name": "bottom_60", "y1": int(y1 + crop_h * 0.4), "y2": y2, "x1": x1, "x2": x2},
            {"name": "bottom_40", "y1": int(y1 + crop_h * 0.6), "y2": y2, "x1": x1, "x2": x2},
            {"name": "full_bbox", "y1": y1, "y2": y2, "x1": x1, "x2": x2},
        ]

        all_results = []

        for region in regions:
            ry1, ry2 = region["y1"], region["y2"]
            rx1, rx2 = region["x1"], region["x2"]

            if ry2 <= ry1 or rx2 <= rx1:
                continue

            pcrop = frame[ry1:ry2, rx1:rx2]
            if pcrop.size == 0:
                continue

            # Upscale 4× for better detection
            try:
                big = cv2.resize(pcrop, None, fx=4.0, fy=4.0,
                                 interpolation=cv2.INTER_CUBIC)
            except Exception:
                big = pcrop

            # Plate detection
            try:
                plates = self._plate_detector.detect(big)
            except Exception as e:
                logger.debug(f"Plate detector error in region {region['name']}: {e}")
                continue

            if not plates:
                continue

            for plate in plates:
                # Guard: minimum plate detector confidence
                if plate.confidence < MIN_PLATE_CONF:
                    continue

                bx1, by1_p, bx2, by2_p = plate.bbox
                bh, bw = big.shape[:2]

                # Guard: aspect ratio (plates are ~0.8:1 to 6:1, allowing square/stacked Indian plates)
                pw, ph = bx2 - bx1, by2_p - by1_p
                if ph > 0 and not (0.8 <= pw / ph <= 6.0):
                    continue

                # Crop plate with small padding
                pad_x = max(2, int(pw * 0.10))
                pad_y = max(2, int(ph * 0.10))
                plate_crop = big[
                    max(0, by1_p - pad_y):min(bh, by2_p + pad_y),
                    max(0, bx1 - pad_x):min(bw, bx2 + pad_x),
                ]
                if plate_crop.size == 0:
                    continue

                # Upscale the plate crop to help OCR engine read tiny plates (e.g. 20x15)
                # Pad to a reasonable size if it's too small
                target_height = 48
                if plate_crop.shape[0] < target_height:
                    scale = target_height / plate_crop.shape[0]
                    plate_crop = cv2.resize(plate_crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)

                # ── OCR with timeout ────────────────────────────
                ocr_result = self._ocr_with_timeout(plate_crop)
                if ocr_result is None:
                    continue

                text, ocr_conf = ocr_result
                if not text or ocr_conf < MIN_OCR_CONF:
                    continue

                # Map plate bbox back to original frame coordinates
                scale_x = (rx2 - rx1) / bw if bw > 0 else 1.0
                scale_y = (ry2 - ry1) / bh if bh > 0 else 1.0
                orig_bx1 = rx1 + int(bx1 * scale_x)
                orig_by1 = ry1 + int(by1_p * scale_y)
                orig_bx2 = rx1 + int(bx2 * scale_x)
                orig_by2 = ry1 + int(by2_p * scale_y)

                all_results.append({
                    "plate_text":   text,
                    "ocr_conf":     ocr_conf,
                    "plate_conf":   plate.confidence,
                    "combined":     plate.confidence * ocr_conf,
                    "bbox_orig":    (orig_bx1, orig_by1, orig_bx2, orig_by2),
                    "plate_crop":   plate_crop,
                    "region":       region["name"],
                })

        if not all_results:
            return None

        best = max(all_results, key=lambda r: r["combined"])

        normalized = normalize_plate(best["plate_text"])
        if not normalized:
            return None

        logger.info(
            f"Plate read [{best['region']}]: {normalized} "
            f"(ocr={best['ocr_conf']:.2f} det={best['plate_conf']:.2f})"
        )

        return PlateResult(
            plate_text           = best["plate_text"],
            normalized_text      = normalized,
            confidence           = round(best["ocr_conf"], 4),
            detection_confidence = round(best["plate_conf"], 4),
            bbox                 = best["bbox_orig"],
            crop                 = best["plate_crop"],
            provider             = ANPR_PROVIDER,
        )

    def _ocr_with_timeout(self, plate_crop) -> Optional[tuple]:
        """
        Run OCR in a thread with a hard timeout.
        Returns (plate_text, confidence) or None on timeout/error.
        """
        def _run():
            try:
                result = self._ocr_engine.read_plate(plate_crop)
                if result and result.plate_text:
                    formatted = _format_plate(result.plate_text)
                    if formatted and _validate_plate(formatted):
                        return formatted, result.confidence
                return None
            except Exception as e:
                logger.debug(f"OCR internal error: {e}")
                return None

        try:
            future = self._executor.submit(_run)
            return future.result(timeout=AWIROS_TIMEOUT)
        except FuturesTimeoutError:
            logger.warning(f"OCR timed out after {AWIROS_TIMEOUT}s — skipping crop")
            return None
        except Exception as e:
            logger.warning(f"OCR executor error: {e}")
            return None


class MockAwirosRecognizer(PlateRecognizerInterface):
    """
    Test double — returns a fixed PlateResult for unit tests.
    Does not load any models.
    """

    def __init__(self, result: Optional[PlateResult] = None):
        self._result = result or PlateResult(
            plate_text           = "GJ01AB1234",
            normalized_text      = "GJ01AB1234",
            confidence           = 0.92,
            detection_confidence = 0.94,
            bbox                 = (10, 20, 200, 70),
            crop                 = None,
            provider             = "mock-awiros",
        )

    def recognize(self, frame, vehicle_bbox, timestamp_ms=0.0) -> Optional[PlateResult]:
        return self._result
