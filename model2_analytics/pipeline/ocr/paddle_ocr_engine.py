"""
PaddleOCR Engine for License Plate Recognition
================================================
PaddleOCR 3.x (PP-OCRv4 mobile) primary reader, EasyOCR fallback.

Critical fix for Windows/CPU PaddlePaddle 3.x builds (kept from the
original file — this was already correctly diagnosed):
    PaddleOCR() with default settings crashes with
    "ConvertPirAttribute2RuntimeAttribute not support
     [pir::ArrayAttribute<pir::DoubleAttribute>]"
    This is a PIR/OneDNN executor bug in the CPU build.
    Fix: pass enable_mkldnn=False.

CHANGES vs. the previous version:
  1. read_plate() now returns ALL validated candidate texts (with their
     confidences), not just the single longest block. The old version
     discarded information PaddleOCR was already giving it for free.
  2. Candidates are validated against the Indian plate regex/character
     rules before ranking, instead of "longest wins" — a longer noisy
     string is not better than a shorter correct one.
  3. Every OCRResult now carries a `sharpness` field (Laplacian variance
     of the crop). This is NOT used to pick the winner here — it is
     threaded through so the temporal resolver (anpr_video_processor.py)
     can use it. Computing it here means every caller gets it for free
     without duplicating the Laplacian call at every call site.
  4. Preprocessing upscale threshold raised slightly (120px -> 150px)
     because Indian plates below ~150px width lose enough stroke detail
     that M/N, 8/B, 0/D confusions become common — this is a real,
     inexpensive lever: verify it helps on YOUR crops (see TESTING.md)
     before assuming it does. If it doesn't help or hurts, revert to 120.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import List, Optional

logger = logging.getLogger("sentinel.paddle_ocr")
logger.setLevel(logging.INFO)


@dataclass
class OCRResult:
    plate_text: str            # normalized, uppercase, no spaces/hyphens
    confidence: float          # 0-1
    sharpness: float = 0.0     # Laplacian variance of the crop used for this read
    all_candidates: List["OCRResult"] = field(default_factory=list)
    # all_candidates holds every validated read PaddleOCR produced for this
    # crop (excluding itself), so a caller that wants more than the single
    # best guess (e.g. to detect a bimodal disagreement) doesn't have to
    # re-run OCR — it's already here.


INDIAN_PLATE_RE = re.compile(r"^[A-Z]{2}\d{1,2}[A-Z]{1,3}\d{4}$")
# Standard Indian format: 2 letters (state), 1-2 digits (RTO code),
# 1-3 letters (series), 4 digits (number). Deliberately looser than a
# strict 10-char check because real-world plates vary (single-letter
# series, 1-digit RTO codes in older plates) and a stricter regex
# rejects correct reads outright rather than just scoring them lower.


def _clean_text(raw: str) -> str:
    """Keep only valid plate alphanumerics, uppercase."""
    return "".join(c for c in raw.upper() if c in "0123456789ABCDEFGHJKLMNPRSTUVWXYZ")


def _validate_plate(text: str) -> bool:
    """Basic sanity check for plate read — length + digit/letter mix."""
    if len(text) < 6 or len(text) > 12:
        return False
    digits = sum(1 for c in text if c.isdigit())
    letters = sum(1 for c in text if c.isalpha())
    return digits >= 3 and letters >= 2


def _plate_score(text: str, ocr_conf: float) -> float:
    """
    Rank candidate reads. A read that matches the strict Indian plate
    shape gets a bonus over one that merely passes the loose validator —
    this is what replaces "pick the longest string".
    """
    bonus = 0.15 if INDIAN_PLATE_RE.match(text) else 0.0
    return ocr_conf + bonus


def _sharpness(crop) -> float:
    """Laplacian variance -- higher = sharper. Returns 0.0 on any failure
    (missing cv2, empty crop) rather than raising, since this is an
    auxiliary signal and must never break the OCR call path."""
    try:
        import cv2
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if len(crop.shape) == 3 else crop
        return float(cv2.Laplacian(gray, cv2.CV_64F).var())
    except Exception:
        return 0.0


class PaddleOCREngine:
    """
    PaddleOCR 3.x-based plate reader with EasyOCR fallback.

    Uses PP-OCRv4 mobile models with mkldnn disabled (required on
    Windows CPU PaddlePaddle builds to avoid the PIR/OneDNN crash —
    this diagnosis was already correct in the original file).
    """

    _instance = None

    @classmethod
    def get_instance(cls, use_gpu: bool = False) -> "PaddleOCREngine":
        if cls._instance is None:
            cls._instance = PaddleOCREngine(use_gpu=use_gpu)
        return cls._instance

    def __init__(self, use_gpu: bool = False):
        self.use_gpu = use_gpu
        self._paddle_reader = None
        self._easy_reader = None
        self._use_paddle = True

    def _lazy_load_paddle(self):
        """Load PaddleOCR 3.x with the mkldnn workaround."""
        if self._paddle_reader is not None:
            return
        try:
            from paddleocr import PaddleOCR

            # enable_mkldnn=False is REQUIRED on Windows CPU PaddlePaddle
            # 3.x builds -- default mkldnn+PIR executor crashes with
            # ConvertPirAttribute2RuntimeAttribute. v4 mobile gives the
            # best accuracy/speed balance on tight plate crops.
            self._paddle_reader = PaddleOCR(
                use_doc_orientation_classify=False,
                use_doc_unwarping=False,
                use_textline_orientation=False,
                enable_mkldnn=False,
                text_detection_model_name="PP-OCRv4_mobile_det",
                text_recognition_model_name="PP-OCRv4_mobile_rec",
            )
            self._use_paddle = True
            logger.info("PaddleOCR 3.x (PP-OCRv4 mobile, mkldnn=off) initialised")
        except Exception as e:
            logger.warning(f"PaddleOCR init failed ({e}) -- falling back to EasyOCR")
            self._use_paddle = False
            self._lazy_load_easy()

    def _lazy_load_easy(self):
        """Fallback to EasyOCR."""
        if self._easy_reader is None:
            try:
                import easyocr
                self._easy_reader = easyocr.Reader(["en"], gpu=self.use_gpu, verbose=False)
                logger.info("EasyOCR initialised as fallback")
            except Exception as e:
                logger.error(f"Both PaddleOCR and EasyOCR failed: {e}")

    @staticmethod
    def _preprocess(crop):
        """Light preprocessing -- upscale small crops, else pass through.

        Threshold raised from 120px to 150px vs. the original file — see
        module docstring. This is a hypothesis, not a validated fact;
        confirm it helps on your own crops before trusting it blindly."""
        import cv2
        if crop is None or crop.size == 0:
            return crop
        h, w = crop.shape[:2]
        if max(h, w) < 150:
            scale = 200.0 / max(h, w)
            crop = cv2.resize(crop, (int(w * scale), int(h * scale)),
                              interpolation=cv2.INTER_CUBIC)
        return crop

    @staticmethod
    def _parse_predict(result) -> list:
        """Parse PaddleOCR 3.x predict() output into [(text, score), ...]."""
        out = []
        for res in result:
            data = None
            j = getattr(res, "json", None)
            if isinstance(j, dict):
                data = j.get("res", j.get("data", j))
            if data is None and isinstance(res, dict):
                data = res
            if not isinstance(data, dict):
                continue
            for t, s in zip(data.get("rec_texts") or [], data.get("rec_scores") or []):
                if t:
                    out.append((str(t), float(s)))
        return out

    def read_plate(self, crop) -> Optional[OCRResult]:
        """Read plate text from a crop image (BGR ndarray). Returns OCRResult or None."""
        if crop is None or crop.size == 0:
            return None
        sh = _sharpness(crop)
        if self._use_paddle:
            self._lazy_load_paddle()
            if self._paddle_reader is not None:
                result = self._read_with_paddle(crop, sh)
                if result is not None:
                    return result
        self._lazy_load_easy()
        if self._easy_reader is not None:
            return self._read_with_easy(crop, sh)
        return None

    def _read_with_paddle(self, crop, sharpness: float) -> Optional[OCRResult]:
        """Read using PaddleOCR 3.x. Considers ALL text blocks it finds,
        not just the longest — ranks by _plate_score (confidence + shape
        bonus) and keeps the rest as all_candidates."""
        try:
            processed = self._preprocess(crop)
            raw = self._paddle_reader.predict(processed)
            reads = self._parse_predict(raw)
            if not reads:
                return None

            candidates = []
            for text, conf in reads:
                clean = _clean_text(text)
                if len(clean) < 6 or not _validate_plate(clean):
                    continue
                candidates.append(OCRResult(plate_text=clean, confidence=conf, sharpness=sharpness))

            if not candidates:
                return None

            candidates.sort(key=lambda r: _plate_score(r.plate_text, r.confidence), reverse=True)
            best = candidates[0]
            best.all_candidates = candidates[1:]
            return best
        except Exception as e:
            logger.warning(f"PaddleOCR read failed: {e}")
            return None

    def _read_with_easy(self, crop, sharpness: float) -> Optional[OCRResult]:
        """Fallback to EasyOCR."""
        try:
            processed = self._preprocess(crop)
            results = self._easy_reader.readtext(processed)
            if not results:
                return None
            texts, confidences = [], []
            for detection in results:
                texts.append(detection[1])
                confidences.append(float(detection[2]))
            clean_text = _clean_text(" ".join(texts))
            avg_conf = sum(confidences) / len(confidences) if confidences else 0.0
            if len(clean_text) < 6:
                return None
            return OCRResult(plate_text=clean_text, confidence=avg_conf, sharpness=sharpness)
        except Exception as e:
            logger.warning(f"EasyOCR read failed: {e}")
            return None
