"""
OCR Engine Evaluation — Step 1: Extract real plate crops from the ANPR test videos.
Uses the existing PlateDetector (model2_analytics/pipeline/plate/plate_detector.py)
to find plates on sampled frames, saves padded crops for engine comparison.

Run from repo root:
    python ocr_eval/extract_crops.py
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import cv2

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "model2_analytics"))

from pipeline.plate.plate_detector import PlateDetector  # noqa: E402

# ── Sources ──────────────────────────────────────────────────────────
VIDEO_MAIN = _REPO_ROOT / "model2-analytics" / "ANPR bhidio" / "13052823_3840_2160_30fps.mp4"
VIDEO_SAMPLE = _REPO_ROOT / "model2-analytics" / "ANPR bhidio" / "sample.mp4"
DATASET_OCR_DIR = (
    _REPO_ROOT / "model2-analytics" / "ANPR bhidio" / "anpr dataset" / "number_plate_images_ocr"
)
DEBUG_CROPS = [
    _REPO_ROOT / "found_plate_OA41SP417.jpg",
    _REPO_ROOT / "plate_debug_60.jpg",
]

OUT_DIR = _REPO_ROOT / "ocr_eval" / "crops"

# ── Extraction config ────────────────────────────────────────────────
MAIN_EVERY = 20        # sample every Nth frame of the 4K 30fps video
MAIN_MAX_FRAMES = 1500
MAIN_MAX_CROPS = 20
SAMPLE_EVERY = 30
SAMPLE_MAX_CROPS = 12


def _aspect_ok(w: int, h: int) -> bool:
    if h <= 0:
        return False
    r = w / h
    return 1.5 <= r <= 6.5


def extract_from_video(video_path: Path, every: int, max_frames: int, max_crops: int,
                       prefix: str, out_dir: Path, det: PlateDetector) -> int:
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        print(f"  !! cannot open {video_path}")
        return 0

    saved = 0
    frame_idx = 0
    while saved < max_crops:
        ret, frame = cap.read()
        if not ret or frame_idx >= max_frames:
            break
        if frame_idx % every == 0:
            h, w = frame.shape[:2]
            plates = det.detect(frame)
            for i, p in enumerate(plates):
                x1, y1, x2, y2 = p.bbox
                pw, ph = x2 - x1, y2 - y1
                if not _aspect_ok(pw, ph):
                    continue
                pad_x, pad_y = max(2, int(pw * 0.12)), max(2, int(ph * 0.18))
                cx1, cy1 = max(0, x1 - pad_x), max(0, y1 - pad_y)
                cx2, cy2 = min(w, x2 + pad_x), min(h, y2 + pad_y)
                crop = frame[cy1:cy2, cx1:cx2]
                if crop.size == 0:
                    continue
                name = f"{prefix}_f{frame_idx:05d}_p{i}_c{int(p.confidence*100)}.jpg"
                cv2.imwrite(str(out_dir / name), crop)
                saved += 1
                print(f"  [{prefix}] frame {frame_idx}: plate crop {crop.shape[1]}x{crop.shape[0]} "
                      f"(det conf {p.confidence:.2f}) -> {name}")
                if saved >= max_crops:
                    break
        frame_idx += 1

    cap.release()
    print(f"  {video_path.name}: {saved} crops saved (scanned {frame_idx} frames)")
    return saved


def extract_realistic_from_video(video_path: Path, every: int, max_frames: int, max_crops: int,
                                 prefix: str, out_dir: Path, det: PlateDetector) -> int:
    """Mimic the production ANPRPipeline path: vehicle detect → bottom 60% region
    → 4x upscale → plate detect → padded crop (upscaled, as OCR would receive it)."""
    import logging
    logging.disable(logging.INFO)
    sys.path.insert(0, str(_REPO_ROOT / "model2_analytics"))
    from pipeline.detection.vehicle_detector import VehicleDetector

    vd = VehicleDetector(confidence_threshold=0.40)
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        print(f"  !! cannot open {video_path}")
        return 0

    saved, frame_idx = 0, 0
    while saved < max_crops:
        ret, frame = cap.read()
        if not ret or frame_idx >= max_frames:
            break
        if frame_idx % every == 0:
            h, w = frame.shape[:2]
            dets = vd.detect(frame)
            for vi, d in enumerate(dets):
                vx1, vy1, vx2, vy2 = d.bbox
                ry1, ry2 = vy1 + int((vy2 - vy1) * 0.40), vy2
                if ry2 <= ry1:
                    continue
                pcrop = frame[ry1:ry2, vx1:vx2]
                if pcrop.size == 0:
                    continue
                big = cv2.resize(pcrop, None, fx=4.0, fy=4.0, interpolation=cv2.INTER_CUBIC)
                bh, bw = big.shape[:2]
                for i, p in enumerate(det.detect(big)):
                    x1, y1, x2, y2 = p.bbox
                    pw, ph = x2 - x1, y2 - y1
                    if not _aspect_ok(pw, ph):
                        continue
                    pad_x, pad_y = max(2, int(pw * 0.12)), max(2, int(ph * 0.18))
                    cx1, cy1 = max(0, x1 - pad_x), max(0, y1 - pad_y)
                    cx2, cy2 = min(bw, x2 + pad_x), min(bh, y2 + pad_y)
                    crop = big[cy1:cy2, cx1:cx2]
                    if crop.size == 0:
                        continue
                    name = f"{prefix}R_f{frame_idx:05d}_v{vi}_p{i}_c{int(p.confidence*100)}.jpg"
                    cv2.imwrite(str(out_dir / name), crop)
                    saved += 1
                    print(f"  [{prefix}R] frame {frame_idx}: crop {crop.shape[1]}x{crop.shape[0]} "
                          f"(det conf {p.confidence:.2f}) -> {name}")
                    if saved >= max_crops:
                        break
                if saved >= max_crops:
                    break
        frame_idx += 1

    cap.release()
    print(f"  {video_path.name} (realistic path): {saved} crops saved (scanned {frame_idx} frames)")
    return saved


def main() -> None:

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    print("Loading PlateDetector (license_plate_detector.pt)…")
    det = PlateDetector(confidence_threshold=0.30)

    print(f"\n== Extracting from main video: {VIDEO_MAIN.name} ==")
    extract_from_video(VIDEO_MAIN, MAIN_EVERY, MAIN_MAX_FRAMES, MAIN_MAX_CROPS,
                       "vid1", OUT_DIR, det)

    print(f"\n== Extracting from main video (realistic vehicle-crop path): {VIDEO_MAIN.name} ==")
    extract_realistic_from_video(VIDEO_MAIN, 15, 900, 15, "vid1", OUT_DIR, det)

    print(f"\n== Extracting from sample video: {VIDEO_SAMPLE.name} ==")
    extract_from_video(VIDEO_SAMPLE, SAMPLE_EVERY, 2000, SAMPLE_MAX_CROPS,
                       "vid2", OUT_DIR, det)

    # Dataset plate images (already plate-only crops)
    print(f"\n== Copying dataset plate images from {DATASET_OCR_DIR.name} ==")
    copied = 0
    if DATASET_OCR_DIR.exists():
        for img_path in sorted(DATASET_OCR_DIR.rglob("*.jpg"))[:21]:
            dst = OUT_DIR / f"ds_{copied:02d}_{img_path.name[:24]}.jpg"
            shutil.copy2(img_path, dst)
            copied += 1
    print(f"  dataset crops copied: {copied}")

    # Root debug crops from earlier sessions
    for p in DEBUG_CROPS:
        if p.exists():
            shutil.copy2(p, OUT_DIR / f"dbg_{p.name}")
            print(f"  debug crop copied: {p.name}")

    total = len(list(OUT_DIR.glob("*.jpg")))
    print(f"\n✓ Total crops available for evaluation: {total} in {OUT_DIR}")


if __name__ == "__main__":
    main()
