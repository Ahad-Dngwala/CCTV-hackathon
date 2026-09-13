"""
PaddleOCR Engine for License Plate Recognition
================================================
PaddleOCR 3.x (PP-OCRv4 mobile) primary reader, EasyOCR fallback.

Critical fix for Windows/CPU PaddlePaddle 3.x builds:
    PaddleOCR() with default settings crashes with
    "ConvertPirAttribute2RuntimeAttribute not support
     [pir::ArrayAttribute<pir::DoubleAttribute>]"
    This is a PIR/OneDNN executor bug in the CPU build.
    Fix: pass enable_mkldnn=False.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger("sentinel.paddle_ocr")
logger.setLevel(logging.INFO)


@dataclass
class OCRResult:
    plate_text: str      # normalized, uppercase, no spaces/hyphens
    confidence: float    # 0-1


def _clean_text(raw: str) -> str:
    """Keep only valid plate alphanumerics, uppercase."""
    return "".join(c for c in raw.upper() if c in "0123456789ABCDEFGHJKLMNPRSTUVWXYZ")


def _validate_plate(text: str) -> bool:
    """Basic sanity check for plate read."""
    if len(text) < 6 or len(text) > 12:
        return False
    digits = sum(1 for c in text if c.isdigit())
    letters = sum(1 for c in text if c.isalpha())
    return digits >= 3 and letters >= 2


class PaddleOCREngine:
    """
    PaddleOCR 3.x-based plate reader with EasyOCR fallback.

    Uses PP-OCRv4 mobile models with mkldnn disabled (required on
    Windows CPU PaddlePaddle builds to avoid the PIR/OneDNN crash).
    """

    _instance = None

    @classmethod
    def get_instance(cls, use_gpu: bool = None) -> "PaddleOCREngine":
        if cls._instance is None:
            cls._instance = PaddleOCREngine(use_gpu=use_gpu)
        return cls._instance

    def __init__(self, use_gpu: bool = None):
        # Auto-detect GPU: use GPU if CUDA is available (PaddlePaddle GPU build)
        if use_gpu is None:
            try:
                import paddle
                self.use_gpu = paddle.is_compiled_with_cuda() and paddle.device.cuda.device_count() >= 1
            except Exception:
                self.use_gpu = False
        else:
            self.use_gpu = use_gpu
        self._paddle_reader = None
        self._easy_reader = None
        self._use_paddle = True
        logger.info(f"PaddleOCREngine: use_gpu={self.use_gpu}")

    def _lazy_load_paddle(self):
        """Load PaddleOCR 3.x — GPU or CPU with the mkldnn workaround."""
        if self._paddle_reader is not None:
            return
        try:
            from paddleocr import PaddleOCR

            kwargs = dict(
                use_doc_orientation_classify=False,
                use_doc_unwarping=False,
                use_textline_orientation=False,
                text_detection_model_name="PP-OCRv5_mobile_det",
                text_recognition_model_name="PP-OCRv5_mobile_rec",
            )
            if self.use_gpu:
                # GPU path: use CUDA, no mkldnn needed
                kwargs["device"] = "gpu"
            else:
                # CPU path: enable_mkldnn=False is REQUIRED to avoid the
                # ConvertPirAttribute2RuntimeAttribute crash on Windows.
                kwargs["enable_mkldnn"] = False

            self._paddle_reader = PaddleOCR(**kwargs)
            self._use_paddle = True
            engine = "GPU (PP-OCRv5)".replace("PP-OCRv5", "PP-OCRv5") if self.use_gpu else "CPU (PP-OCRv5)"
            logger.info(f"PaddleOCR 3.x {engine} initialised (device={'gpu' if self.use_gpu else 'cpu'})")
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
        """Light preprocessing -- upscale small crops, else pass through."""
        import cv2
        if crop is None or crop.size == 0:
            return crop
        h, w = crop.shape[:2]
        if max(h, w) < 120:
            scale = 160.0 / max(h, w)
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
        if self._use_paddle:
            self._lazy_load_paddle()
            if self._paddle_reader is not None:
                result = self._read_with_paddle(crop)
                if result is not None:
                    return result
        self._lazy_load_easy()
        if self._easy_reader is not None:
            return self._read_with_easy(crop)
        return None


    def _read_with_paddle(self, crop) -> Optional[OCRResult]:
        """Read using PaddleOCR 3.x."""
        try:
            processed = self._preprocess(crop)
            raw = self._paddle_reader.predict(processed)
            reads = self._parse_predict(raw)
            if not reads:
                return None
            # Pick the longest text block as the plate read
            reads.sort(key=lambda r: len(r[0]), reverse=True)
            best_text, best_conf = reads[0]
            clean = _clean_text(best_text)
            if len(clean) >= 6:
                return OCRResult(plate_text=clean, confidence=best_conf)
            return None
        except Exception as e:
            logger.warning(f"PaddleOCR read failed: {e}")
            return None

    def _read_with_easy(self, crop) -> Optional[OCRResult]:
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
            return OCRResult(plate_text=clean_text, confidence=avg_conf)
        except Exception as e:
            logger.warning(f"EasyOCR read failed: {e}")
            return None
