"""
ANPR Tracked Video Processor
==============================
End-to-end tracked ANPR pipeline:
    frame -> vehicle_detect -> ByteTracker
          -> plate_detect on full frame (every N frames)
          + associate plates with vehicle tracks via overlap
          + re-project plate box between detection frames
          -> OCR (PaddleOCR 3.x + EasyOCR fallback)
          -> temporal aggregation (confidence-weighted majority vote)
          -> evidence log (JSON) + annotated video

Run:
    python model2_analytics/pipeline/anpr_video_processor.py
        --video "Test Input/sample_2.mp4"
        --output "output/anpr_tracked.mp4"
        [--frames N] [--stride 1] [--plate-interval 5]
        [--db-url postgresql://...]
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import cv2

_PROJECT = Path(__file__).resolve().parents[1]
if str(_PROJECT) not in sys.path:
    sys.path.insert(0, str(_PROJECT))

from pipeline.detection.anpr_vehicle_detector import AnprVehicleDetector
from pipeline.plate.plate_detector import PlateDetector
from pipeline.ocr.onnx_ocr_engine import OnnxOCREngine, OCRResult
from pipeline.tracking.byte_tracker import ByteTracker
from pipeline.config import VEHICLE_DETECTION_IMGSZ, PER_CLASS_CONF_THRESHOLDS

logger = logging.getLogger("sentinel.anpr_tracked")
logger.setLevel(logging.INFO)
if not logging.getLogger().handlers:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")


@dataclass
class PlateRead:
    text: str
    confidence: float
    frame_idx: int
    crop_area: int = 0  # pixel area of OCR crop at time of read (px²); larger = closer/clearer


@dataclass
class TrackState:
    track_id: int
    vehicle_class: str
    color: Tuple[int, int, int]
    plate_reads: List[PlateRead] = field(default_factory=list)
    resolved_text: Optional[str] = None
    resolved_conf: float = 0.0
    rel_offset: Optional[Tuple[float, float, float, float]] = None
    best_crop_path: Optional[str] = None
    best_score: float = 0.0
    best_sharpness: float = 0.0
    best_frame: int = 0
    first_seen: int = 0
    last_seen: int = 0
    max_crop_area: int = 0  # max plate crop area seen for this track (for normalization)
    class_history: List[Tuple[int, str, float]] = field(default_factory=list)  # (frame, class_name, conf) per frame — raw post-detect sequence
    bbox_areas: List[float] = field(default_factory=list)  # bbox area per frame — for GEOMETRIC_AREA_RANGES calibration


def _sharpness(crop):
    """Laplacian variance -- higher = sharper."""
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if len(crop.shape) == 3 else crop
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def _normalize(text):
    return text.upper().replace(" ", "").replace("-", "").replace(".", "")


def _align_reads(reads: list, align_from: str = "start") -> list:
    """
    Align reads by padding shorter ones with None.
    align_from="start" → left-align (pad right)
    align_from="end" → right-align (pad left)
    """
    if not reads:
        return []
    texts = [_normalize(r.text) for r in reads]
    max_len = max(len(t) for t in texts)
    aligned = []
    for t in texts:
        if align_from == "start":
            padded = t.ljust(max_len, "\x00")
        else:
            padded = t.rjust(max_len, "\x00")
        aligned.append(padded)
    return aligned


def _position_vote(reads: list, align_from: str = "start",
                   max_crop_area: int = 0, verbose_pos: int = -1) -> tuple:
    """
    Character-position voting weighted by (ocr_confidence * normalised_crop_area * recency).

    Three compounding signals per read:
      - ocr_confidence:  how confident the OCR engine was on this crop
      - norm_area:       crop_area / max_crop_area  (larger crop = closer vehicle = clearer)
      - recency:         [0.5, 1.0] linear ramp from oldest to newest read in this track

    All three signals agree for late/close reads, making them dominate over many
    early/small/distant reads — the confirmed fix for the N-vs-M failure on Track 7.

    verbose_pos: if >= 0, emit INFO log for that position showing per-char weighted scores.
    Returns (candidate_string, avg_consensus).
    """
    if not reads:
        return "", 0.0
    aligned = _align_reads(reads, align_from)
    if not aligned:
        return "", 0.0
    max_len = len(aligned[0])
    result_chars = []
    total_consensus = 0.0
    positions_voted = 0

    # Normalisation denominator: max crop area seen for this track (passed in).
    # Fall back to the max among the current read set if caller didn't provide.
    norm_denom = max_crop_area if max_crop_area > 0 else max((r.crop_area for r in reads), default=1)
    if norm_denom == 0:
        norm_denom = 1

    n_reads = len(reads)

    for pos in range(max_len):
        char_scores = {}
        for i, padded in enumerate(aligned):
            ch = padded[pos]
            if ch == "\x00":
                continue
            conf = reads[i].confidence
            # Normalise crop area to [0, 1] relative to the largest crop seen for this track
            norm_area = reads[i].crop_area / norm_denom if reads[i].crop_area > 0 else 0.1
            # Recency factor [0.5, 1.0]: later reads (vehicle closer) count more.
            # Combined with area-weighting, both signals reinforce each other for close reads.
            recency = 0.5 + 0.5 * (i / (n_reads - 1)) if n_reads > 1 else 1.0
            # Combined weight
            weight = conf * norm_area * recency
            char_scores[ch] = char_scores.get(ch, 0.0) + weight

        if not char_scores:
            continue

        best_char = max(char_scores, key=lambda k: char_scores[k])
        total_score = sum(char_scores.values())
        consensus = char_scores[best_char] / total_score if total_score > 0 else 0.0

        # Verbose vote trace for requested position (e.g. position 4 for Track 7 M-vs-N)
        if pos == verbose_pos:
            sorted_scores = sorted(char_scores.items(), key=lambda x: -x[1])
            logger.info(
                f"[VOTE TRACE] pos={pos} align={align_from} winner='{best_char}' "
                f"consensus={consensus:.3f} | "
                + ", ".join(f"'{c}':{s:.4f}" for c, s in sorted_scores)
            )

        result_chars.append(best_char)
        total_consensus += consensus
        positions_voted += 1

    candidate = "".join(result_chars)
    avg_consensus = total_consensus / positions_voted if positions_voted > 0 else 0.0
    return candidate, avg_consensus


def _resolve_plate(ts: TrackState, min_reads: int = 3, soft_min_reads: int = 2, soft_conf: float = 0.85):
    """
    Character-position voting for plate resolution.

    Each character-position vote is weighted by (ocr_confidence * normalised_crop_area)
    so reads from larger (closer) plate crops outweigh reads from small/distant crops.

    Resolution paths:
    1. Single read >= 0.99 confidence → immediate resolve
    2. >= min_reads total reads → character-position voting with alignment
    3. >= soft_min_reads AND any read >= soft_conf → soft resolution (lower confidence threshold)
    4. Otherwise → not enough data
    """
    if not ts.plate_reads:
        return

    # Path 1: High-confidence single read
    for r in ts.plate_reads:
        if r.confidence >= 0.99:
            ts.resolved_text = _normalize(r.text)
            ts.resolved_conf = r.confidence
            return

    total = len(ts.plate_reads)
    if total < soft_min_reads:
        return

    # Path 2: Character-position voting with crop-size weighting
    if total >= min_reads:
        candidates = []
        # Emit vote trace at position 4 (the confirmed M-vs-N battleground on Track 7)
        for align_from in ["start", "end"]:
            candidate, consensus = _position_vote(
                ts.plate_reads, align_from,
                max_crop_area=ts.max_crop_area,
                verbose_pos=4,  # trace position 4 so we can verify M wins
            )
            if candidate and len(candidate) >= 6:
                candidates.append((candidate, consensus, align_from))

        if candidates:
            best = max(candidates, key=lambda c: c[1])
            candidate, consensus, align_from = best
            ts.resolved_text = candidate
            ts.resolved_conf = consensus
            logger.info(
                f"[RESOLVED] Track {ts.track_id}: '{candidate}' consensus={consensus:.3f} "
                f"via {align_from}-align, {total} reads, max_crop_area={ts.max_crop_area}"
            )
            return

    # Path 3: Soft resolution — fewer reads but high confidence
    # Only if at least one read has confidence >= soft_conf
    has_high_conf = any(r.confidence >= soft_conf for r in ts.plate_reads)
    if has_high_conf and total >= soft_min_reads:
        # Use the highest-confidence read as-is (no voting, too few reads)
        best_read = max(ts.plate_reads, key=lambda r: r.confidence)
        ts.resolved_text = _normalize(best_read.text)
        ts.resolved_conf = best_read.confidence * 0.8  # Penalize for low read count


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
        self.ocr_engine = OnnxOCREngine.get_instance()
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

        # Plate detection on FULL FRAME — now every frame since GPU is fast enough.
        # Previous plate_interval=5 caused short tracks to never accumulate enough reads.
        frame_plates = self.plate_detector.detect(frame)

        for trk in tracks:
            tid = trk["track_id"]
            if tid not in self.track_states:
                self.track_states[tid] = TrackState(
                    track_id=tid, vehicle_class=trk["class_name"],
                    color=tuple(int(c) for c in trk["color"]), first_seen=frame_idx)
            ts = self.track_states[tid]
            ts.last_seen = frame_idx
            ts.vehicle_class = trk["class_name"]
            # Diagnosis capture: raw per-frame class sequence + bbox area
            ts.class_history.append((frame_idx, trk["class_name"], trk["confidence"]))
            ts.bbox_areas.append(float((trk["bbox"][2] - trk["bbox"][0]) * (trk["bbox"][3] - trk["bbox"][1])))
            vbbox = trk["bbox"]
            vx1, vy1, vx2, vy2 = (int(c) for c in vbbox)
            vw, vh = vx2 - vx1, vy2 - vy1
            if vw < 20 or vh < 20:
                self._draw(annotated, trk, ts, None)
                continue

            plate_bbox, ocr_result, crop, plate_conf = None, None, None, 0.0
            plate_bbox, ocr_result, crop, plate_conf = self._associate_plate(
                frame, vbbox, ts, frame_plates)

            if ocr_result and ocr_result.plate_text:
                # Compute plate crop area from the plate_bbox returned by _associate_plate.
                # plate_bbox is (bx1, by1, bx2, by2) in original frame coordinates.
                if plate_bbox is not None:
                    bx1, by1, bx2, by2 = plate_bbox
                    pad = max(3, int((bx2 - bx1) * 0.15))
                    fh, fw = frame.shape[:2]
                    pcrop_h = max(0, min(fh, by2 + pad) - max(0, by1 - pad))
                    pcrop_w = max(0, min(fw, bx2 + pad) - max(0, bx1 - pad))
                    area = pcrop_h * pcrop_w
                else:
                    area = 0
                ts.plate_reads.append(
                    PlateRead(ocr_result.plate_text, ocr_result.confidence, frame_idx, area))
                # Track max crop area for this track (used to normalise voting weight)
                if area > ts.max_crop_area:
                    ts.max_crop_area = area
                _resolve_plate(ts)
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
            label += f" [{ts.resolved_text}]"
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
        all_tracks = []

        # ── Car->Bus diagnosis dump ────────────────────────────────
        # For every track that ended up labeled "Bus", print the raw
        # per-frame class/conf sequence and avg bbox area so we can
        # compare against GEOMETRIC_AREA_RANGES.
        for tid, ts in sorted(self.track_states.items()):
            if ts.vehicle_class != "Bus":
                continue
            avg_area = (sum(ts.bbox_areas) / len(ts.bbox_areas)) if ts.bbox_areas else 0.0
            seq = " | ".join(f"f{f}:{c[:2]}{int(cf*100)}" for f, c, cf in ts.class_history[:40])
            logger.info(
                f"[BUS-DIAG] track {tid}: avg_bbox_area={avg_area:.0f} "
                f"(Car range 8000-50000, Bus range 30000-200000) "
                f"frames={len(ts.class_history)} "
                f"seq={seq}"
            )
        for tid, ts in sorted(self.track_states.items()):
            # ALL confirmed tracks (Issue 5) — enables recall measurement
            all_tracks.append({
                "track_id": tid,
                "vehicle_class": ts.vehicle_class,
                "resolved_plate": ts.resolved_text,
                "first_seen_frame": ts.first_seen,
                "last_seen_frame": ts.last_seen,
                "dur_frames": ts.last_seen - ts.first_seen + 1,
                "plate_attempted": len(ts.plate_reads) > 0,
                "readings_count": len(ts.plate_reads),
            })
            # Detail records only for tracks with plate reads
            if not ts.plate_reads:
                continue
            rec = {
                "track_id": tid,
                "vehicle_class": ts.vehicle_class,
                "plate_text": ts.resolved_text,
                "ocr_confidence": round(ts.resolved_conf, 4),
                "first_seen_frame": ts.first_seen,
                "last_seen_frame": ts.last_seen,
                "first_seen_time_s": round(ts.first_seen / fps, 2),
                "last_seen_time_s": round(ts.last_seen / fps, 2),
                "camera_id": self.camera_id,
                "best_crop_path": os.path.join(self.evidence_dir, ts.best_crop_path) if ts.best_crop_path else None,
                "best_frame": getattr(ts, "best_frame", None),
                "readings_count": len(ts.plate_reads),
                "all_reads": [{"text": r.text, "conf": round(r.confidence, 4), "frame": r.frame_idx,
                              "crop_area": r.crop_area}
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
            "total_tracks_detected": len(all_tracks),
            "tracks_with_plate_reads": len(records),
            "resolved_tracks": sum(1 for r in records if r.get("plate_text")),
            "all_tracks": all_tracks,
            "track_details": records,
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
    parser.add_argument("--db-url", default=None, help="PostgreSQL URL for watchlist")
    parser.add_argument("--camera-id", default="cam01")
    args = parser.parse_args()

    proc = ANPRTrackedProcessor(
        video_path=args.video, output_path=args.output,
        process_stride=args.stride, max_frames=args.frames,
        conf_vehicle=args.conf_vehicle, conf_plate=args.conf_plate,
        plate_interval=args.plate_interval, db_url=args.db_url,
        camera_id=args.camera_id,
    )
    out = proc.run()
    print(f"\nAnnotated video: {out}")
    print(f"Evidence JSON: {proc.evidence_dir}/evidence.json")
    print(f"Crops: {proc.evidence_dir}/")


if __name__ == "__main__":
    main()
