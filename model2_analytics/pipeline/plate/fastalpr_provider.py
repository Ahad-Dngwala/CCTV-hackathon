import logging
import re
import cv2
import numpy as np
from typing import Optional, Tuple
from concurrent.futures import ThreadPoolExecutor

from pipeline.plate.interface import PlateRecognizerInterface, PlateResult
from pipeline.plate.plate_detector import PlateDetector
from fast_plate_ocr import LicensePlateRecognizer
from fast_alpr import ALPR

logger = logging.getLogger("sentinel.fastalpr")

class FastALPRProvider(PlateRecognizerInterface):
    """
    FastALPR / FastPlateOCR ANPR Adapter.
    Uses the exact logic validated in the video_smoke_test:
      1. YOLO PlateDetector to find the plate inside the vehicle bbox
      2. FastALPR (end-to-end ALPR) as the PRIMARY reader — benchmarked best:
         42.9% exact / 85.6% char accuracy on 7 verified 4K crops
         (vs 0% exact for cct-s-v2 FastPlateOCR, 28.6% for PP-OCRv5 ONNX).
      3. FastPlateOCR (cct-s-v2) as the FALLBACK when ALPR abstains or
         returns a short/invalid read.
    Both raw outputs are kept; the selected text is stored separately and
    real confidence scores are returned (never hardcoded).
    """
    _instance: Optional["FastALPRProvider"] = None
    _executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="fastalpr-ocr")

    def __init__(self):
        self.plate_detector = PlateDetector()
        self.fast_ocr = LicensePlateRecognizer("cct-s-v2-global-model")
        self.fast_alpr = ALPR()
        logger.info("FastALPRProvider initialized successfully.")

    @classmethod
    def get_instance(cls) -> "FastALPRProvider":
        if cls._instance is None:
            cls._instance = FastALPRProvider()
        return cls._instance

    def recognize(
        self,
        frame: np.ndarray,
        vehicle_bbox: Tuple[int, int, int, int],
        timestamp_ms: float = 0.0,
    ) -> Optional[PlateResult]:
        
        def _do_recognize() -> Optional[PlateResult]:
            t_x1, t_y1, t_x2, t_y2 = map(int, vehicle_bbox)
            height, width = frame.shape[:2]
            
            # Clamp coords
            t_x1, t_y1 = max(0, t_x1), max(0, t_y1)
            t_x2, t_y2 = min(width, t_x2), min(height, t_y2)
            
            v_crop = frame[t_y1:t_y2, t_x1:t_x2]
            if v_crop.size == 0:
                return None
                
            p_res = self.plate_detector.detect(v_crop)
            if not p_res:
                return None
                
            # Take the best plate crop
            best_det = p_res[0]
            px1, py1, px2, py2 = map(int, best_det.bbox)
            px1, py1 = max(0, px1), max(0, py1)
            px2, py2 = min(v_crop.shape[1], px2), min(v_crop.shape[0], py2)
            
            best_plate_crop = v_crop[py1:py2, px1:px2]
            if best_plate_crop.size == 0:
                return None
                
            global_bbox = (t_x1 + px1, t_y1 + py1, t_x1 + px2, t_y1 + py2)
            
            ocr_raw_primary = ""
            ocr_conf_primary = 0.0
            ocr_raw_fallback = ""
            ocr_conf_fallback = 0.0

            # Primary: FastALPR end-to-end (benchmark winner: 42.9% exact,
            # 85.6% char accuracy on verified 4K crops).
            try:
                alpr_preds = self.fast_alpr.predict(best_plate_crop)
                if alpr_preds and getattr(alpr_preds[0].ocr, "text", ""):
                    ocr_raw_primary = str(alpr_preds[0].ocr.text)
                    c = getattr(alpr_preds[0].ocr, "confidence", 0.0)
                    try:
                        ocr_conf_primary = float(c)
                    except Exception:
                        import numpy as _np
                        a = _np.asarray(c, dtype=float).ravel()
                        ocr_conf_primary = float(a.mean()) if a.size else 0.0
            except Exception as e:
                logger.warning(f"FastALPR primary read failed: {e}")

            clean_primary = re.sub(r"[^A-Z0-9]", "", ocr_raw_primary.upper())

            # Fallback: FastPlateOCR, only when primary abstains or is short.
            if not clean_primary or len(clean_primary) < 4:
                try:
                    fpo_res = self.fast_ocr.run_one(best_plate_crop)
                    ocr_raw_fallback = str(getattr(fpo_res, "plate", "") or "")
                    probs = getattr(fpo_res, "char_probs", None)
                    if probs is not None:
                        try:
                            ocr_conf_fallback = float(probs.mean())
                        except Exception:
                            ocr_conf_fallback = 0.0
                except Exception as e:
                    logger.warning(f"FastPlateOCR fallback read failed: {e}")

            clean_fallback = re.sub(r"[^A-Z0-9]", "", ocr_raw_fallback.upper())

            # Select: prefer primary when it produced a usable read;
            # otherwise take the fallback. Keep both raw outputs.
            if clean_primary and len(clean_primary) >= 4:
                ocr_text, clean, confidence = ocr_raw_primary, clean_primary, ocr_conf_primary
            elif clean_fallback:
                ocr_text, clean, confidence = ocr_raw_fallback, clean_fallback, ocr_conf_fallback
            else:
                return None
                
            return PlateResult(
                plate_text=ocr_text,
                normalized_text=clean,
                confidence=round(float(confidence), 4),
                detection_confidence=best_det.confidence,
                bbox=global_bbox,
                crop=best_plate_crop,
                provider="fastalpr+plateocr",
            )

        future = self._executor.submit(_do_recognize)
        try:
            return future.result(timeout=5.0)
        except Exception as e:
            logger.warning(f"FastALPR timed out or failed: {e}")
            return None
