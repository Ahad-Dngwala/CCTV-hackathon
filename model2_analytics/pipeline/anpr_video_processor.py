"""
ANPR Tracked Video Processor
==============================
End-to-end tracked ANPR pipeline:
    frame -> vehicle_detect -> ByteTracker
          -> plate_detect on full frame (every N frames)
          + associate plates with vehicle tracks via overlap
          + re-project plate box between detection frames
          -> OCR (PaddleOCR 3.x + EasyOCR fallback)
          -> temporal aggregation (sharpness-gated character-position vote)
          -> evidence log (JSON) + annotated video

CHANGES vs. the previous version (all in the resolver + a few plumbing
spots needed to feed it — nothing about detection/tracking touched):

  1. PlateRead now carries `sharpness` (Laplacian variance of the crop
     that produced it), populated at the two call sites where OCR runs
     (_associate_plate and the reprojected-frame path in _process_frame).

  2. _resolve_plate is replaced by _resolve_plate_v2:
       - whole-string majority voting -> character-position voting.
         The old version treated "MW4498" and "NW4498" as two totally
         unrelated strings competing for votes. Position voting treats
         each of the 10 characters independently, so a systematic error
         confined to ONE position (e.g. only position 4 flips M->N)
         only costs that one position, not the whole string's votes.
       - reads are gated by sharpness before voting whenever enough
         sharp reads exist. This is the actual fix for the "10 wrong,
         confident, blurry reads outvote 4 correct sharp reads" failure
         mode: majority voting assumes independent errors, but a blur-
         induced character confusion is a CORRELATED error that repeats
         identically across many frames. More repeats of a correlated
         error is not more evidence. Filtering by sharpness first means
         you're voting only among reads where that correlated error
         mode is less likely to have triggered at all.
       - a single very-high-confidence read (>= high_conf) still short-
         circuits immediately, same behavior as before.
       - if too few reads survive the sharpness filter, falls back to
         voting on the FULL unfiltered set rather than failing outright
         — never worse than the old behavior, only better when the
         filter has enough survivors to work with.

  3. SHARPNESS_FLOOR is NOT hardcoded to a made-up number. It defaults
     to None (no filtering, i.e. old behavior) until you've measured
     your own crops' sharpness distribution — see TESTING.md for the
     exact one-command way to derive it from evidence.json. Running
     with SHARPNESS_FLOOR=None still gets you the character-position
     voting improvement, which alone should help independent of the
     sharpness question.

Run:
    python model2_analytics/pipeline/anpr_video_processor.py
        --video "Test Input/sample_2.mp4"
        --output "output/anpr_tracked.mp4"
        [--frames N] [--stride 1] [--plate-interval 5]
        [--sharpness-floor 60.0]
        [--db-url postgresql://...]
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import cv2

_PROJECT = Path(__file__).resolve().parents[1]
if str(_PROJECT) not in sys.path:
    sys.path.insert(0, str(_PROJECT))

from pipeline.detection.anpr_vehicle_detector import AnprVehicleDetector
from pipeline.plate.plate_detector import PlateDetector
from pipeline.plate.anpr_service import get_plate_recognizer
from pipeline.ocr.paddle_ocr_engine import PaddleOCREngine, OCRResult
from pipeline.tracking.byte_tracker import ByteTracker
from pipeline.config import PER_CLASS_CONF_THRESHOLDS, VEHICLE_DETECTION_IMGSZ

logger = logging.getLogger("sentinel.anpr_tracked")
logger.setLevel(logging.INFO)
if not logging.getLogger().handlers:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")


@dataclass
class PlateRead:
    text: str
    confidence: float
    frame_idx: int
    sharpness: float = 0.0


@dataclass
class TrackState:
    track_id: int
    vehicle_class: str
    color: Tuple[int, int, int]
    plate_reads: List[PlateRead] = field(default_factory=list)
    resolved_text: Optional[str] = None
    resolved_conf: float = 0.0
    resolution_method: str = "unresolved"   # "high_conf" | "position_vote_sharp" | "position_vote_all"
    ambiguous_positions: List[int] = field(default_factory=list)  # positions with a close 2nd place
    rel_offset: Optional[Tuple[float, float, float, float]] = None
    best_crop_path: Optional[str] = None
    best_score: float = 0.0
    best_sharpness: float = 0.0
    best_frame: int = 0
    first_seen: int = 0
    last_seen: int = 0


def _sharpness(crop) -> float:
    """Laplacian variance -- higher = sharper."""
    if crop is None or crop.size == 0:
        return 0.0
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if len(crop.shape) == 3 else crop
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def _normalize(text: str) -> str:
    return text.upper().replace(" ", "").replace("-", "").replace(".", "")


def _resolve_plate_v2(
    ts: TrackState,
    min_reads: int = 3,
    high_conf: float = 0.99,
    sharpness_floor: Optional[float] = None,
    min_sharp_reads: int = 3,
):
    """
    Sharpness-gated character-position vote.

    Step 1: any single near-certain read short-circuits (unchanged from
            the old behavior).
    Step 2: if sharpness_floor is set and enough reads clear it, vote
            ONLY among those reads. Otherwise vote among all reads.
    Step 3: vote per character position (not whole-string), confidence-
            weighted. Track positions with a close top-2 (within 15% of
            each other's weight) as "ambiguous_positions" so the UI can
            flag "MW4498 or MN4498 — verify" instead of asserting one
            confidently when the evidence genuinely doesn't decide it.

    This does NOT invent a sharpness threshold for you. sharpness_floor
    defaults to None (behaves like plain position-voting over all reads)
    until you measure your own crops -- see TESTING.md.
    """
    if not ts.plate_reads:
        return

    for r in ts.plate_reads:
        if r.confidence >= high_conf:
            ts.resolved_text = _normalize(r.text)
            ts.resolved_conf = r.confidence
            ts.resolution_method = "high_conf"
            return

    reads = ts.plate_reads
    method = "position_vote_all"
    if sharpness_floor is not None:
        sharp = [r for r in reads if r.sharpness >= sharpness_floor]
        if len(sharp) >= min_sharp_reads:
            reads = sharp
            method = "position_vote_sharp"

    if len(reads) < min_reads:
        return

    # Character-position voting, confidence-weighted.
    positions: Dict[int, Counter] = {}
    for r in reads:
        t = _normalize(r.text)
        for i, ch in enumerate(t):
            positions.setdefault(i, Counter())
            positions[i][ch] += r.confidence

    if not positions:
        return

    length = max(positions.keys()) + 1
    resolved_chars = []
    ambiguous = []
    for i in range(length):
        counter = positions.get(i)
        if not counter:
            resolved_chars.append("?")
            continue
        ranked = counter.most_common(2)
        resolved_chars.append(ranked[0][0])
        if len(ranked) > 1:
            top_w, second_w = ranked[0][1], ranked[1][1]
            if top_w > 0 and (top_w - second_w) / top_w < 0.15:
                ambiguous.append(i)

    ts.resolved_text = "".join(resolved_chars)
    ts.resolved_conf = sum(r.confidence for r in reads) / len(reads)
    ts.resolution_method = method
    ts.ambiguous_positions = ambiguous


class ANPRTrackedProcessor:
    def __init__(
        self,
        video_path: str,
        output_path: str = "output/anpr_tracked.mp4",
        process_stride: int = 1,
        max_frames: Optional[int] = None,
        conf_vehicle: float = 0.10,
        conf_plate: float = 0.40,
        plate_interval: int = 5,
        db_url: Optional[str] = None,
        camera_id: str = "cam01",
        evidence_dir: Optional[str] = None,
        sharpness_floor: Optional[float] = None,
    ):
        self.video_path = video_path
        self.output_path = output_path
        self.process_stride = max(1, process_stride)
        self.max_frames = max_frames
        self.conf_vehicle = conf_vehicle
        self.conf_plate = conf_plate
        self.plate_interval = plate_interval
        self.db_url = db_url
        self.camera_id = camera_id
        self.evidence_dir = evidence_dir or str(Path(output_path).parent / "anpr_evidence")
        self.sharpness_floor = sharpness_floor
        self.vehicle_detector = None
        self.plate_detector = None
        self.ocr_engine = None
        self.tracker = None
        self.track_states: Dict[int, TrackState] = {}

    def _init_models(self):
        self.vehicle_detector = AnprVehicleDetector(
            confidence_threshold=self.conf_vehicle,
            iou_threshold=0.45,
            imgsz=VEHICLE_DETECTION_IMGSZ,
            per_class_thresholds=PER_CLASS_CONF_THRESHOLDS,
        )
        self.plate_detector = PlateDetector(confidence_threshold=self.conf_plate)
        self.ocr_engine = get_plate_recognizer() or PaddleOCREngine.get_instance()
        self.tracker = ByteTracker(high_thresh=0.10)
        os.makedirs(self.evidence_dir, exist_ok=True)
        os.makedirs(str(Path(self.output_path).parent), exist_ok=True)
        if self.db_url:
            logger.info("DB watchlist wiring requested (--db-url)")

    def _process_frame(self, frame, frame_idx):
        annotated = frame.copy()
        detections = self.vehicle_detector.detect(frame)
        det_dicts = [
            {"bbox": list(d.bbox), "confidence": d.confidence,
             "class_id": d.class_id, "class_name": d.class_name}
            for d in detections
        ]
        tracks = self.tracker.update(det_dicts)

        # Plate detection on FULL FRAME every N frames.
        # The plate detector works on full-frame input; upscaling a small
        # vehicle crop distorts aspect ratio and yields zero detections.
        do_detect = frame_idx % self.plate_interval == 0
        frame_plates = self.plate_detector.detect(frame) if do_detect else []

        for trk in tracks:
            tid = trk["track_id"]
            if tid not in self.track_states:
                self.track_states[tid] = TrackState(
                    track_id=tid, vehicle_class=trk["class_name"],
                    color=tuple(int(c) for c in trk["color"]), first_seen=frame_idx)
            ts = self.track_states[tid]
            ts.last_seen = frame_idx
            ts.vehicle_class = trk["class_name"]  # refresh from rolling class vote every frame
            vbbox = trk["bbox"]
            vx1, vy1, vx2, vy2 = (int(c) for c in vbbox)
            vw, vh = vx2 - vx1, vy2 - vy1
            if vw < 20 or vh < 20:
                self._draw(annotated, trk, ts, None)
                continue

            plate_bbox, ocr_result, crop, plate_conf = None, None, None, 0.0
            if do_detect:
                plate_bbox, ocr_result, crop, plate_conf = self._associate_plate(
                    frame, vbbox, ts, frame_plates)
            else:
                plate_bbox = self._reproject_plate(ts, vx1, vy1, vw, vh)
                if plate_bbox:
                    crop = self._crop_plate(frame, plate_bbox)
                    if crop is not None and crop.size > 0:
                        ocr_result = self.ocr_engine.read_plate(crop)

            if ocr_result and ocr_result.plate_text:
                read_sharpness = getattr(ocr_result, "sharpness", 0.0) or _sharpness(crop)
                ts.plate_reads.append(
                    PlateRead(ocr_result.plate_text, ocr_result.confidence,
                               frame_idx, read_sharpness))
                _resolve_plate_v2(ts, sharpness_floor=self.sharpness_floor)
                self._update_best_frame(ts, crop, ocr_result.confidence, plate_conf, frame_idx)

            self._draw(annotated, trk, ts, plate_bbox)

        cv2.putText(annotated, f"Frame {frame_idx}", (20, 40),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 255, 255), 2)
        return annotated

    def _associate_plate(self, frame, vbbox, ts, frame_plates):
        """Pick the full-frame plate overlapping this vehicle, OCR it."""
        if not frame_plates:
            return None, None, None, 0.0
        vx1, vy1, vx2, vy2 = (int(c) for c in vbbox)
        vw, vh = vx2 - vx1, vy2 - vy1
        best = None
        best_score = -1.0
        for p in frame_plates:
            bx1, by1, bx2, by2 = p.bbox
            ox = max(0, min(bx2, vx2) - max(bx1, vx1))
            oy = max(0, min(by2, vy2) - max(by1, vy1))
            overlap = ox * oy
            if overlap <= 0:
                continue
            score = overlap * p.confidence
            if score > best_score:
                best_score = score
                best = p
        if best is None:
            return None, None, None, 0.0

        bx1, by1, bx2, by2 = best.bbox
        plate_bbox = (bx1, by1, bx2, by2)
        if vw > 0 and vh > 0:
            ts.rel_offset = ((bx1 - vx1) / vw, (by1 - vy1) / vh,
                             (bx2 - vx1) / vw, (by2 - vy1) / vh)
        h, w = frame.shape[:2]
        pad = max(3, int((bx2 - bx1) * 0.15))
        pcrop = frame[max(0, by1 - pad):min(h, by2 + pad),
                      max(0, bx1 - pad):min(w, bx2 + pad)]
        ocr_result = self.ocr_engine.read_plate(pcrop) if pcrop.size > 0 else None
        return plate_bbox, ocr_result, pcrop, best.confidence

    def _reproject_plate(self, ts, vx1, vy1, vw, vh):
        if ts.rel_offset is None:
            return None
        rx1, ry1, rx2, ry2 = ts.rel_offset
        return (int(vx1 + rx1 * vw), int(vy1 + ry1 * vh),
                int(vx1 + rx2 * vw), int(vy1 + ry2 * vh))

    def _crop_plate(self, frame, plate_bbox):
        h, w = frame.shape[:2]
        x1, y1, x2, y2 = (int(c) for c in plate_bbox)
        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(w, x2), min(h, y2)
        if x2 <= x1 or y2 <= y1:
            return None
        return frame[y1:y2, x1:x2]

    def _update_best_frame(self, ts, crop, ocr_conf, plate_conf, frame_idx):
        if crop is None or crop.size == 0:
            return
        score = ocr_conf * max(plate_conf, 0.01)
        sh = _sharpness(crop)
        if score > ts.best_score or (score == ts.best_score and sh > ts.best_sharpness):
            ts.best_score = score
            ts.best_sharpness = sh
            fname = f"track{ts.track_id}_best.jpg"
            cv2.imwrite(os.path.join(self.evidence_dir, fname), crop)
            ts.best_crop_path = fname
            ts.best_frame = frame_idx

    def _draw(self, frame, trk, ts, plate_bbox):
        color = ts.color
        x1, y1, x2, y2 = (int(c) for c in trk["bbox"])
        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
        label = f"ID:{ts.track_id} {ts.vehicle_class}"
        if ts.resolved_text:
            marker = "?" if ts.ambiguous_positions else ""
            label += f" [{ts.resolved_text}{marker}]"
        cv2.putText(frame, label, (x1, max(24, y1 - 6)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)
        if plate_bbox:
            px1, py1, px2, py2 = (int(c) for c in plate_bbox)
            cv2.rectangle(frame, (px1, py1), (px2, py2), (0, 255, 255), 1)

    def run(self):
        self._init_models()
        cap = cv2.VideoCapture(self.video_path)
        if not cap.isOpened():
            raise RuntimeError(f"Cannot open video: {self.video_path}")
        fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        sw = max(1, self.process_stride)
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        out = cv2.VideoWriter(self.output_path, fourcc, fps / sw, (w, h))
        if not out.isOpened():
            raise RuntimeError(f"Cannot open writer: {self.output_path}")

        t0 = time.perf_counter()
        frame_idx = 0
        processed = 0
        while True:
            ret, frame = cap.read()
            if not ret or (self.max_frames and frame_idx >= self.max_frames):
                break
            if frame_idx % sw == 0:
                annotated = self._process_frame(frame, frame_idx)
                out.write(annotated)
                processed += 1
            frame_idx += 1

        elapsed = time.perf_counter() - t0
        cap.release()
        out.release()
        inf_fps = processed / elapsed if elapsed > 0 else 0
        self._write_evidence(elapsed, inf_fps, frame_idx, fps)
        logger.info(f"Done: {processed}/{frame_idx} frames in {elapsed:.1f}s = {inf_fps:.2f} FPS")
        return self.output_path

    def _write_evidence(self, elapsed, inf_fps, total_frames, fps):
        records = []
        for tid, ts in sorted(self.track_states.items()):
            if not ts.plate_reads:
                continue
            rec = {
                "track_id": tid,
                "vehicle_class": ts.vehicle_class,
                "plate_text": ts.resolved_text,
                "ocr_confidence": round(ts.resolved_conf, 4),
                "resolution_method": ts.resolution_method,
                "ambiguous_positions": ts.ambiguous_positions,
                "first_seen_frame": ts.first_seen,
                "last_seen_frame": ts.last_seen,
                "first_seen_time_s": round(ts.first_seen / fps, 2),
                "last_seen_time_s": round(ts.last_seen / fps, 2),
                "camera_id": self.camera_id,
                "best_crop_path": os.path.join(self.evidence_dir, ts.best_crop_path) if ts.best_crop_path else None,
                "best_frame": getattr(ts, "best_frame", None),
                "readings_count": len(ts.plate_reads),
                "all_reads": [{"text": r.text, "conf": round(r.confidence, 4),
                               "frame": r.frame_idx, "sharpness": round(r.sharpness, 2)}
                              for r in ts.plate_reads],
            }
            records.append(rec)
            if self.db_url and ts.resolved_text:
                self._check_watchlist(ts)
        evidence = {
            "video": self.video_path,
            "camera_id": self.camera_id,
            "total_frames": total_frames,
            "processing_time_s": round(elapsed, 2),
            "inference_fps": round(inf_fps, 2),
            "sharpness_floor_used": self.sharpness_floor,
            "tracks": records,
        }
        epath = os.path.join(self.evidence_dir, "evidence.json")
        with open(epath, "w") as f:
            json.dump(evidence, f, indent=2)
        logger.info(f"Evidence written: {epath}")

    def _check_watchlist(self, ts):
        try:
            import sqlalchemy as sa
            from pipeline.events.anpr_alert_pipeline import AnprAlertPipeline
            engine = sa.create_engine(self.db_url)
            Session = sa.orm.sessionmaker(bind=engine)
            pipeline = AnprAlertPipeline(db_session_factory=Session)
            pipeline.process_plate(
                plate_text=ts.resolved_text, camera_id=self.camera_id,
                camera_name=self.camera_id, vehicle_class=ts.vehicle_class,
                confidence=ts.resolved_conf,
                crop_path=os.path.join(self.evidence_dir, ts.best_crop_path) if ts.best_crop_path else None,
            )
        except Exception as e:
            logger.warning(f"Watchlist check failed track {ts.track_id}: {e}")


def main():
    parser = argparse.ArgumentParser(description="ANPR Tracked Video Processor")
    parser.add_argument("--video", required=True, help="Input video path")
    parser.add_argument("--output", default="output/anpr_tracked.mp4")
    parser.add_argument("--stride", type=int, default=1, help="Process every Nth frame")
    parser.add_argument("--frames", type=int, default=None, help="Max frames")
    parser.add_argument("--plate-interval", type=int, default=5,
                        help="Plate detection every N frames; re-project between")
    parser.add_argument("--conf-vehicle", type=float, default=0.10)
    parser.add_argument("--conf-plate", type=float, default=0.40)
    parser.add_argument("--sharpness-floor", type=float, default=None,
                        help="Min Laplacian variance for a read to count in "
                             "voting when enough reads clear it. Leave unset "
                             "until you've measured your own crops (see "
                             "TESTING.md) -- an unvalidated guess here can "
                             "hurt as easily as help.")
    parser.add_argument("--db-url", default=None, help="PostgreSQL URL for watchlist")
    parser.add_argument("--camera-id", default="cam01")
    args = parser.parse_args()

    proc = ANPRTrackedProcessor(
        video_path=args.video, output_path=args.output,
        process_stride=args.stride, max_frames=args.frames,
        conf_vehicle=args.conf_vehicle, conf_plate=args.conf_plate,
        plate_interval=args.plate_interval, db_url=args.db_url,
        camera_id=args.camera_id, sharpness_floor=args.sharpness_floor,
    )
    out = proc.run()
    print(f"\nAnnotated video: {out}")
    print(f"Evidence JSON: {proc.evidence_dir}/evidence.json")
    print(f"Crops: {proc.evidence_dir}/")


if __name__ == "__main__":
    main()