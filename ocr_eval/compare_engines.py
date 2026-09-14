"""
OCR Engine Evaluation — Step 2: Head-to-head engine comparison on real plate crops.
Engines:
  1. EasyOCR        — current default (pipeline/ocr/ocr_engine.py wrapper, Indian validation)
  2. PaddleOCR 3.7  — NEW 3.x pipeline API (ocr.predict + rec_texts/rec_scores)
  3. onnxocr        — ONNX-runtime port of PaddleOCR (CPU friendly)

Run from repo root (after extract_crops.py):
    python ocr_eval/compare_engines.py
"""

from __future__ import annotations

import csv
import json
import sys
import time
from pathlib import Path
from typing import Any, List, Optional, Tuple

import cv2
import numpy as np

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "model2_analytics"))

from pipeline.ocr.ocr_engine import EasyOCREngine, _format_plate  # noqa: E402

CROPS_DIR = _REPO_ROOT / "ocr_eval" / "crops"
RESULTS_JSON = _REPO_ROOT / "ocr_eval" / "results.json"
RESULTS_CSV = _REPO_ROOT / "ocr_eval" / "results.csv"


# ── Engine 1: EasyOCR (current wrapper, includes Indian validation) ──
def make_easyocr():
    eng = EasyOCREngine.get_instance(gpu=False)

    def run(crop: np.ndarray) -> Tuple[Optional[Tuple[str, float]], float]:
        t0 = time.perf_counter()
        res = eng.read_plate(crop)
        dt = time.perf_counter() - t0
        return ((res.plate_text, res.confidence) if res else (None, None)), dt

    return run


# ── Engine 2: PaddleOCR 3.x (new pipeline API) ───────────────────────
def make_paddle3():
    from paddleocr import PaddleOCR

    init_kwargs: dict = dict(
        use_doc_orientation_classify=False,
        use_doc_unwarping=False,
        use_textline_orientation=False,
    )
    try:
        ocr = PaddleOCR(**init_kwargs)
    except Exception as e:
        print(f"  PaddleOCR default init failed ({e}) — retrying with explicit v5 models")
        ocr = PaddleOCR(
            text_detection_model_name="PP-OCRv5_mobile_det",
            text_recognition_model_name="PP-OCRv5_mobile_rec",
            **init_kwargs,
        )
    print(f"  PaddleOCR 3.x initialised (lang={getattr(ocr, 'lang', '?')})")

    def _parse(result: Any) -> List[Tuple[str, float]]:
        """Parse 3.x predict() output into [(text, score), ...]."""
        out: List[Tuple[str, float]] = []
        for res in result:
            data = None
            if hasattr(res, "json"):
                j = res.json
                if isinstance(j, dict):
                    data = j.get("res", j.get("data", j))
            if data is None and isinstance(res, dict):
                data = res
            if not isinstance(data, dict):
                continue
            texts = data.get("rec_texts") or []
            scores = data.get("rec_scores") or []
            for t, s in zip(texts, scores):
                if t:
                    out.append((str(t), float(s)))
        return out

    def run(crop: np.ndarray) -> Tuple[Optional[Tuple[str, float]], float]:
        t0 = time.perf_counter()
        try:
            result = ocr.predict(crop)
        except Exception as e:
            print(f"  paddle3 predict error: {e}")
            return (None, None), time.perf_counter() - t0
        dt = time.perf_counter() - t0
        reads = _parse(result)
        if not reads:
            return (None, None), dt
        best = max(reads, key=lambda r: r[1])
        return best, dt

    return run

# ── Engine 3: onnxocr (ONNX port, 2.x-style .ocr() interface) ────────
def make_onnxocr():
    from onnxocr.onnx_paddleocr import ONNXPaddleOcr

    eng = ONNXPaddleOcr(use_angle_cls=True, use_gpu=False)
    print("  onnxocr initialised")

    def _parse(result: Any) -> List[Tuple[str, float]]:
        out: List[Tuple[str, float]] = []
        if result is None:
            return out
        items = result
        if isinstance(items, tuple) and len(items) >= 1:   # (results, elapse)
            items = items[0]
        if not isinstance(items, (list, tuple)):
            return out
        for item in items:
            if isinstance(item, (list, tuple)) and len(item) == 2:
                _box, payload = item
                if isinstance(payload, (list, tuple)) and len(payload) >= 2:
                    out.append((str(payload[0]), float(payload[1])))
                elif isinstance(payload, str):
                    out.append((payload, 0.0))
        return out

    def run(crop: np.ndarray) -> Tuple[Optional[Tuple[str, float]], float]:
        t0 = time.perf_counter()
        try:
            result = eng.ocr(crop)
        except Exception as e:
            print(f"  onnxocr error: {e}")
            return (None, None), time.perf_counter() - t0
        dt = time.perf_counter() - t0
        reads = _parse(result)
        if not reads:
            return (None, None), dt
        best = max(reads, key=lambda r: r[1])
        return best, dt

    return run


ENGINES = [
    ("easyocr", "EasyOCR (current)", make_easyocr),
    ("paddle3", "PaddleOCR 3.7 (new API)", make_paddle3),
    ("onnxocr", "onnxocr (ONNX)", make_onnxocr),
]


def main() -> None:
    crops = sorted(CROPS_DIR.glob("*.jpg"))
    print(f"Found {len(crops)} plate crops in {CROPS_DIR}\n")
    if not crops:
        print("No crops — run extract_crops.py first")
        sys.exit(1)

    results: List[dict] = []
    for key, label, factory in ENGINES:
        print(f"── Initialising {label} …")
        try:
            run = factory()
        except Exception as e:
            print(f"  !! {label} init FAILED: {e}")
            for c in crops:
                results.append({"crop": c.name, "engine": key, "text": "",
                                "conf": "", "formatted": "", "time_s": "", "error": str(e)[:120]})
            continue

        # Warm-up on first crop (model compile/init — excluded from timing)
        warm = cv2.imread(str(crops[0]))
        try:
            run(warm)
        except Exception:
            pass

        print(f"── Running {label} on {len(crops)} crops …")
        n_reads, total_t = 0, 0.0
        for c in crops:
            img = cv2.imread(str(c))
            (text, conf), dt = run(img)
            total_t += dt
            if text:
                n_reads += 1
            results.append({
                "crop": c.name,
                "engine": key,
                "text": text or "",
                "conf": round(conf, 4) if text else "",
                "formatted": _format_plate(text) if text else "",
                "time_s": round(dt, 3),
                "error": "",
            })
            shown = f"{text} ({conf:.2f})" if text else "—"
            print(f"   {c.name:<44} {shown:<28} {dt:.2f}s")
        mean_t = total_t / max(len(crops), 1)
        print(f"   → {label}: {n_reads}/{len(crops)} reads, mean {mean_t:.2f}s/crop\n")

    RESULTS_JSON.write_text(json.dumps(results, indent=2))
    with open(RESULTS_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["crop", "engine", "text", "conf", "formatted", "time_s", "error"])
        w.writeheader()
        w.writerows(results)

    # ── Side-by-side table ──
    print("\n" + "=" * 110)
    print("SIDE-BY-SIDE (per crop)")
    print("=" * 110)
    by_crop: dict = {}
    for r in results:
        by_crop.setdefault(r["crop"], {})[r["engine"]] = r
    for crop, row in by_crop.items():
        print(f"\n{crop}")
        for key, label, _ in ENGINES:
            r = row.get(key, {})
            if r.get("error"):
                print(f"  {label:<24} ERROR: {r['error'][:80]}")
            elif r.get("text"):
                print(f"  {label:<24} {r['text']:<20} conf={r['conf']:<8} formatted={r['formatted']}")
            else:
                print(f"  {label:<24} (no read)")

    print(f"\n✓ Results saved: {RESULTS_JSON} and {RESULTS_CSV}")


if __name__ == "__main__":
    main()

