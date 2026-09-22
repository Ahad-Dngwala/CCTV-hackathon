"""
Model 2 — Pre-Recorded Video AI Detection Worker
=================================================
Runs an isolated, on-demand video detection and tracking pipeline for uploaded
video files (.mp4, .avi, .mov, .mkv).

Features:
  - ByteTracker: 2-stage IoU + Kalman matching with persistent track continuity
  - Indian Traffic YOLOv8 + Geometric Area Filtering (correcting Car vs Bus)
  - Full-Frame High-Resolution Plate Detection & Indian PARSeq OCR
  - Temporal Character-Position Voting per track
  - Indian License Plate Pattern Validation (eliminates partial/spurious reads)
  - Cross-Track Levenshtein Plate De-duplication (merges duplicate sightings of same vehicle)
  - Smooth Pacing for jitter-free real-time streaming
"""

import base64
import logging
import os
import re
import threading
import time
import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

import cv2
import numpy as np
from sqlalchemy.orm import Session

from pipeline.detection.anpr_vehicle_detector import AnprVehicleDetector
from pipeline.detection.writer import DetectionWriter
from pipeline.plate.anpr_service import get_plate_recognizer
from pipeline.plate.plate_detector import PlateDetector
from pipeline.tracking.byte_tracker import ByteTracker
from pipeline.tracking.frame_tracker import TrackedEvent

logger = logging.getLogger("sentinel.video_worker")
logger.setLevel(logging.INFO)

SPEED_TO_INFER_EVERY = {
    "1x":  2,
    "2x":  4,
    "max": 6,
}

# Indian license plate regex & standard state codes
INDIAN_PLATE_PATTERN = re.compile(r"^[A-Z]{2}[0-9]{1,2}[A-Z]{0,3}[0-9]{4}$")
INDIAN_STATE_CODES = {
    "AP", "AR", "AS", "BR", "CG", "CH", "DD", "DL", "DN", "GA",
    "GJ", "HR", "HP", "JH", "JK", "KA", "KL", "LA", "LD", "MH",
    "ML", "MN", "MP", "MZ", "NL", "OD", "OR", "PB", "PY", "RJ",
    "SK", "TN", "TR", "TS", "UK", "UP", "WB"
}


def is_valid_indian_plate(text: str) -> bool:
    """Validates if text is a plausible Indian license plate."""
    if not text:
        return False
    clean = re.sub(r"[^A-Z0-9]", "", text.upper())
    if len(clean) < 7 or len(clean) > 11:
        return False
    if bool(INDIAN_PLATE_PATTERN.match(clean)):
        return True
    num_digits = sum(c.isdigit() for c in clean)
    num_letters = sum(c.isalpha() for c in clean)
    return num_digits >= 3 and num_letters >= 2


def _levenshtein(s1: str, s2: str) -> int:
    """Computes Levenshtein edit distance between two strings."""
    if len(s1) < len(s2):
        return _levenshtein(s2, s1)
    if len(s2) == 0:
        return len(s1)
    previous_row = range(len(s2) + 1)
    for i, c1 in enumerate(s1):
        current_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = previous_row[j + 1] + 1
            deletions = current_row[j] + 1
            substitutions = previous_row[j] + (c1 != c2)
            current_row.append(min(insertions, deletions, substitutions))
        previous_row = current_row
    return previous_row[-1]


def _sharpness(crop: Optional[np.ndarray]) -> float:
    """Laplacian variance — higher = sharper."""
    if crop is None or getattr(crop, "size", 0) == 0:
        return 0.0
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if len(crop.shape) == 3 else crop
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


class _TrackPlateBuffer:
    """
    Accumulates per-frame plate reads for a single vehicle track,
    calculates crop sharpness, and applies confidence-weighted
    character-position voting.
    """

    def __init__(self, track_id: int):
        self.track_id        = track_id
        self.reads: List[Dict] = []
        self.first_seen_ms: Optional[float] = None
        self.last_seen_ms:  Optional[float] = None
        self.best_crop: Optional[np.ndarray] = None
        self.best_score: float = 0.0
        self.best_plate_conf: float = 0.0
        self.resolved_plate: Optional[str] = None
        self.resolved_conf: float = 0.0
        self.resolution_method: str = "none"

    def add(self, text: str, ocr_conf: float, plate_conf: float, sharpness: float, pts_ms: float, crop: Optional[np.ndarray], provider: str):
        clean = re.sub(r"[^A-Z0-9]", "", text.upper())
        if len(clean) < 4 or ocr_conf < 0.40:
            return  # Filter out low-confidence fragmented noise

        if self.first_seen_ms is None:
            self.first_seen_ms = pts_ms
        self.last_seen_ms = pts_ms

        self.reads.append({
            "text": clean,
            "ocr_conf": ocr_conf,
            "plate_conf": plate_conf,
            "sharpness": sharpness,
            "pts_ms": pts_ms,
            "provider": provider,
        })

        score = ocr_conf * (1.0 + min(sharpness / 200.0, 1.0))
        if score > self.best_score or self.best_crop is None:
            self.best_score = score
            self.best_plate_conf = plate_conf
            if crop is not None and crop.size > 0:
                self.best_crop = crop.copy()

        self._resolve()

    def _resolve(self):
        if not self.reads:
            return

        # 1. Single high-confidence valid plate short-circuits
        for r in self.reads:
            if r["ocr_conf"] >= 0.88 and is_valid_indian_plate(r["text"]):
                self.resolved_plate = r["text"]
                self.resolved_conf = r["ocr_conf"]
                self.resolution_method = "high_confidence"
                return

        # 2. Filter valid length reads
        valid_reads = [r for r in self.reads if is_valid_indian_plate(r["text"])]
        target_reads = valid_reads if valid_reads else [r for r in self.reads if len(r["text"]) >= 7 and r["ocr_conf"] >= 0.50]

        if not target_reads:
            best = max(self.reads, key=lambda r: r["ocr_conf"])
            if best["ocr_conf"] >= 0.65 and len(best["text"]) >= 7:
                self.resolved_plate = best["text"]
                self.resolved_conf = best["ocr_conf"]
                self.resolution_method = "max_confidence"
            return

        # Frequency consensus
        text_counts = Counter(r["text"] for r in target_reads)
        most_common_text, count = text_counts.most_common(1)[0]
        matching_reads = [r for r in target_reads if r["text"] == most_common_text]
        avg_conf = sum(r["ocr_conf"] for r in matching_reads) / len(matching_reads)

        # 3. Confidence + sharpness weighted character-position voting if multiple reads
        if count > 1 or len(target_reads) >= 3:
            target_len = Counter(len(r["text"]) for r in target_reads).most_common(1)[0][0]
            aligned = [r for r in target_reads if len(r["text"]) == target_len] or target_reads

            positions: Dict[int, Counter] = {}
            for r in aligned:
                t = r["text"]
                weight = r["ocr_conf"] * (1.0 + min(r.get("sharpness", 0.0) / 300.0, 0.5))
                for i, ch in enumerate(t):
                    positions.setdefault(i, Counter())
                    positions[i][ch] += weight

            resolved_chars = []
            for i in range(target_len):
                if i in positions and positions[i]:
                    resolved_chars.append(positions[i].most_common(1)[0][0])
                else:
                    resolved_chars.append("?")

            res = "".join(resolved_chars)
            avg_aligned = sum(r["ocr_conf"] for r in aligned) / len(aligned)
            if "?" not in res and (is_valid_indian_plate(res) or avg_aligned >= 0.60):
                self.resolved_plate = res
                self.resolved_conf = round(avg_aligned, 4)
                self.resolution_method = "position_vote"
                return

        self.resolved_plate = most_common_text
        self.resolved_conf = round(avg_conf, 4)
        self.resolution_method = "frequency_consensus" if count > 1 else "highest_confidence"

    @property
    def read_count(self) -> int:
        return len(self.reads)


class PreRecordedVideoWorker:
    """Processes uploaded video files asynchronously in an independent daemon thread."""

    def __init__(
        self,
        job_id: str,
        file_path: str,
        camera_uuid: uuid.UUID,
        camera_name: str = "Recorded Video Source",
        speed: str = "1x",
        anpr_rate: int = 5,
        event_callback: Optional[Callable[[Dict], None]] = None,
        db_session_factory: Optional[Callable[[], Session]] = None,
    ):
        self.job_id             = job_id
        self.file_path          = file_path
        self.camera_uuid        = camera_uuid
        self.camera_name        = camera_name
        self.speed              = speed if speed in SPEED_TO_INFER_EVERY else "1x"
        self.anpr_rate          = max(1, anpr_rate)
        self.event_callback     = event_callback
        self.db_session_factory = db_session_factory

        # Upgraded to ByteTracker with Kalman filtering & geometric Car vs Bus correction
        self.tracker = ByteTracker(
            high_thresh=0.15,
            low_thresh=0.08,
            match_thresh=0.20,
            max_time_lost=25,
        )
        self.detector       = AnprVehicleDetector(confidence_threshold=0.15)
        self.plate_detector = PlateDetector(confidence_threshold=0.20)

        _recognizer = get_plate_recognizer()
        self.writer = DetectionWriter(
            plate_recognizer = _recognizer,
            alert_callback   = event_callback,
        )

        # Buffers & De-duplication structures
        self._plate_buffers: Dict[int, _TrackPlateBuffer] = {}
        self._seen_plates: Dict[str, Dict] = {}        # canonical plate -> sighting record
        self._track_sighting_ids: Dict[int, str] = {}  # track_id -> detection_id
        self._track_frames_alive: Dict[int, int] = defaultdict(int)
        self._persisted_tracks: set = set()
        self._best_vehicle_crops: Dict[int, Dict] = {} # track_id -> {'score': float, 'crop': np.ndarray}
        self._last_emitted_plates: Dict[int, str] = {} # track_id -> last emitted plate string


        self._thread      = None
        self._pause_event = threading.Event()
        self._pause_event.set()
        self._stop_event  = threading.Event()

        self.state:            str   = "idle"
        self.total_detections: int   = 0
        self.current_frame:    int   = 0
        self.total_frames:     int   = 0
        self.fps:              float = 25.0
        self.processing_fps:   float = 0.0

    @property
    def is_running(self) -> bool:
        return self.state in ("running", "paused")

    def _emit(self, event_type: str, data: Dict):
        if self.event_callback:
            try:
                self.event_callback({"type": event_type, "data": data})
            except Exception as e:
                logger.warning(f"[{self.job_id}] event_callback error: {e}")

    def _find_matching_plate(self, plate: str) -> Optional[str]:
        """Finds if plate was already observed within Levenshtein distance <= 2."""
        if not plate:
            return None
        if plate in self._seen_plates:
            return plate
        for prev in self._seen_plates:
            # Match if edit distance <= 2 for plates of similar length
            if abs(len(prev) - len(plate)) <= 1:
                if _levenshtein(prev, plate) <= (1 if len(plate) < 9 else 2):
                    return prev
        return None

    # ── Main worker thread ───────────────────────────────────────────

    def _run(self):
        logger.info(f"[{self.job_id}] PreRecordedVideoWorker started: {self.file_path}")
        cap = cv2.VideoCapture(self.file_path)

        if not cap.isOpened():
            self.state = "error"
            self._emit("JOB_ERROR", {
                "job_id": self.job_id,
                "error": f"Failed to open video file: {self.file_path}",
            })
            logger.error(f"[{self.job_id}] Cannot open video: {self.file_path}")
            return

        self.total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 1
        self.fps          = float(cap.get(cv2.CAP_PROP_FPS)) or 25.0
        infer_every  = SPEED_TO_INFER_EVERY.get(self.speed, 2)
        frame_delay  = 0.0 if self.speed == "max" else (
            1.0 / (self.fps * (2.0 if self.speed == "2x" else 1.0))
        )

        self.state = "running"
        frame_idx  = 0
        fps_frames_count  = 0
        t_fps_checkpoint  = time.time()
        last_boxes_payload      = []
        last_active_tracks_len  = 0
        active_tracks           = []

        try:
            while not self._stop_event.is_set():
                self._pause_event.wait()
                if self._stop_event.is_set():
                    break

                loop_t0 = time.time()
                ok, frame = cap.read()
                if not ok:
                    break

                frame_idx += 1
                self.current_frame = frame_idx
                fps_frames_count  += 1
                pts_ms = cap.get(cv2.CAP_PROP_POS_MSEC) or (frame_idx * 1000.0 / self.fps)

                now = time.time()
                elapsed_chk = now - t_fps_checkpoint
                if elapsed_chk >= 1.0:
                    self.processing_fps = round(fps_frames_count / elapsed_chk, 1)
                    fps_frames_count    = 0
                    t_fps_checkpoint    = now

                vehicle_infer_interval = 2
                plate_infer_interval = max(2, min(self.anpr_rate, 4))

                should_infer_vehicles = (frame_idx % vehicle_infer_interval == 0 or frame_idx == 1)
                should_infer_plates = (frame_idx % plate_infer_interval == 0)


                h, w = frame.shape[:2]

                if should_infer_vehicles:
                    raw_dets = self.detector.detect(frame, pts_ms=pts_ms)
                    det_dicts = [
                        {
                            "bbox": list(d.bbox),
                            "confidence": d.confidence,
                            "class_id": d.class_id,
                            "class_name": d.class_name,
                            "crop": d.crop,
                        }
                        for d in raw_dets
                    ]
                    active_tracks = self.tracker.update(det_dicts)

                    for trk in active_tracks:
                        tid = trk["track_id"]
                        self._track_frames_alive[tid] += 1

                        # Cache best high-resolution, padded vehicle crop
                        vx1, vy1, vx2, vy2 = trk["bbox"]
                        vw, vh = max(1, vx2 - vx1), max(1, vy2 - vy1)
                        area = vw * vh
                        if area > 1200:
                            pad_vx = int(vw * 0.08)
                            pad_vy = int(vh * 0.08)
                            cx1 = max(0, int(vx1 - pad_vx))
                            cy1 = max(0, int(vy1 - pad_vy))
                            cx2 = min(w, int(vx2 + pad_vx))
                            cy2 = min(h, int(vy2 + pad_vy))
                            cand_crop = frame[cy1:cy2, cx1:cx2]
                            if cand_crop.size > 0:
                                c_sh = _sharpness(cand_crop)
                                c_score = area * (1.0 + min(c_sh / 200.0, 1.0))
                                if tid not in self._best_vehicle_crops or c_score > self._best_vehicle_crops[tid]["score"]:
                                    self._best_vehicle_crops[tid] = {
                                        "score": c_score,
                                        "crop": cand_crop.copy(),
                                    }

                # ── Plate Detection & Fine-Tuned Indian PARSeq OCR ────
                current_frame_plates = []
                if should_infer_plates and self.writer.plate_recognizer and active_tracks:
                    try:
                        frame_plates = self.plate_detector.detect(frame)
                        for pd in frame_plates:
                            px1, py1, px2, py2 = map(int, pd.bbox)
                            pw, ph = px2 - px1, py2 - py1
                            if pw < 16 or ph < 8:
                                continue
                            pad_x = int(pw * 0.08)
                            pad_y = int(ph * 0.12)
                            pcrop = frame[max(0, py1 - pad_y):min(h, py2 + pad_y),
                                          max(0, px1 - pad_x):min(w, px2 + pad_x)]
                            if pcrop.size == 0:
                                continue

                            current_frame_plates.append(pd)

                            # Associate plate to nearest vehicle track (with 60px margin in 4K resolution)
                            pcx, pcy = (px1 + px2) / 2.0, (py1 + py2) / 2.0
                            best_trk = None
                            best_dist = float("inf")
                            for trk in active_tracks:
                                vx1, vy1, vx2, vy2 = trk["bbox"]
                                if vx1 - 60 <= pcx <= vx2 + 60 and vy1 - 60 <= pcy <= vy2 + 60:
                                    vcx = (vx1 + vx2) / 2.0
                                    vcy = (vy1 + vy2) / 2.0
                                    dist = np.hypot(pcx - vcx, pcy - vcy)
                                    if dist < best_dist:
                                        best_dist = dist
                                        best_trk = trk

                            if best_trk is not None:
                                tid = best_trk["track_id"]
                                read_res = self.writer.plate_recognizer.read_plate(pcrop)
                                clean = read_res.get("text") or getattr(read_res, "plate_text", "")
                                conf = float(read_res.get("confidence") or getattr(read_res, "confidence", 0.0))
                                prov = read_res.get("provider") or "indian_parseq"
                                sh = _sharpness(pcrop)

                                if tid not in self._plate_buffers:
                                    self._plate_buffers[tid] = _TrackPlateBuffer(tid)
                                self._plate_buffers[tid].add(
                                    text=clean,
                                    ocr_conf=conf,
                                    plate_conf=pd.confidence,
                                    sharpness=sh,
                                    pts_ms=pts_ms,
                                    crop=pcrop,
                                    provider=prov,
                                )
                    except Exception as p_err:
                        logger.warning(f"Plate detect/OCR error in video worker: {p_err}")

                # Build last_boxes_payload with plate annotations attached
                last_boxes_payload = []
                for trk in active_tracks:
                    tid = trk["track_id"]
                    buf = self._plate_buffers.get(tid)
                    res_plate = buf.resolved_plate if (buf and buf.resolved_plate and is_valid_indian_plate(buf.resolved_plate)) else None
                    res_conf = round(buf.resolved_conf * 100, 1) if (buf and res_plate) else None

                    last_boxes_payload.append({
                        "track_id": trk["track_id"],
                        "bbox": [
                            round(trk["bbox"][0] / w, 4),
                            round(trk["bbox"][1] / h, 4),
                            round(trk["bbox"][2] / w, 4),
                            round(trk["bbox"][3] / h, 4),
                        ],
                        "class_name": trk["class_name"],
                        "confidence": round(trk["confidence"] * 100, 1),
                        "plate": res_plate,
                        "plate_conf": res_conf,
                    })

                last_active_tracks_len = len(active_tracks)

                # ── Evaluate and Persist Confirmed Sightings ────────
                for trk in active_tracks:
                    tid = trk["track_id"]
                    buf = self._plate_buffers.get(tid)
                    resolved_plate = buf.resolved_plate if buf else None
                    has_plate = bool(resolved_plate and is_valid_indian_plate(resolved_plate))

                    # Check if vehicle has already been persisted for this track
                    existing_det_id = self._track_sighting_ids.get(tid)

                    if has_plate:
                        if existing_det_id:
                            # Track already persisted -> only update DB and UI if plate changed or improved
                            last_plate = self._last_emitted_plates.get(tid)
                            prev_best = self._seen_plates.get(resolved_plate, {}).get("best_conf", 0.0)
                            if resolved_plate != last_plate or buf.resolved_conf > (prev_best + 0.03):
                                self._last_emitted_plates[tid] = resolved_plate
                                best_v_crop = self._best_vehicle_crops.get(tid, {}).get("crop")

                                if self.db_session_factory:
                                    db_upd = self.db_session_factory()
                                    try:
                                        class _PR:
                                            plate_text           = resolved_plate
                                            normalized_text      = resolved_plate
                                            confidence           = buf.resolved_conf
                                            detection_confidence = buf.best_plate_conf
                                            provider             = "indian_parseq"
                                            crop                 = buf.best_crop
                                        self.writer.update_sighting_plate(
                                            db_upd, existing_det_id, _PR(), self.camera_uuid, self.camera_name, trk["class_name"], vehicle_crop=best_v_crop
                                        )
                                    finally:
                                        db_upd.close()

                                self._seen_plates[resolved_plate] = {
                                    "detection_id":  existing_det_id,
                                    "track_id":      tid,
                                    "plate":         resolved_plate,
                                    "class_name":    trk["class_name"],
                                    "best_conf":     buf.resolved_conf,
                                    "read_count":    buf.read_count,
                                    "first_seen_ms": pts_ms,
                                    "last_seen_ms":  pts_ms,
                                }

                                self._emit("DETECTION_UPDATED", {
                                    "job_id":            self.job_id,
                                    "detection_id":      existing_det_id,
                                    "track_id":          tid,
                                    "detected_plate":    resolved_plate,
                                    "ocr_confidence":    round(buf.resolved_conf, 4),
                                    "plate_confidence":  round(buf.best_plate_conf, 4),
                                    "crop_path":         f"/detection-image/{existing_det_id}.jpg" if best_v_crop is not None else None,
                                    "plate_crop_path":   f"/detection-image/plate_{existing_det_id}.jpg" if buf.best_crop is not None else None,
                                    "read_count":        buf.read_count,
                                    "anpr_provider":     "indian_parseq",
                                })
                        else:
                            # 1. Cross-track plate de-duplication
                            match_key = self._find_matching_plate(resolved_plate)

                            if match_key:
                                seen_info = self._seen_plates[match_key]
                                target_det_id = seen_info["detection_id"]
                                self._track_sighting_ids[tid] = target_det_id
                                seen_info["read_count"] += 1
                                seen_info["last_seen_ms"] = pts_ms

                                if buf.resolved_conf > seen_info.get("best_conf", 0.0) or buf.best_crop is not None:
                                    if buf.resolved_conf > seen_info.get("best_conf", 0.0):
                                        seen_info["best_conf"] = buf.resolved_conf
                                        seen_info["plate"] = resolved_plate
                                    best_v_crop = self._best_vehicle_crops.get(tid, {}).get("crop")
                                    if self.db_session_factory:
                                        db_upd = self.db_session_factory()
                                        try:
                                            class _PR:
                                                plate_text           = resolved_plate
                                                normalized_text      = resolved_plate
                                                confidence           = buf.resolved_conf
                                                detection_confidence = buf.best_plate_conf
                                                provider             = "indian_parseq"
                                                crop                 = buf.best_crop
                                            self.writer.update_sighting_plate(
                                                db_upd, target_det_id, _PR(), self.camera_uuid, self.camera_name, trk["class_name"], vehicle_crop=best_v_crop
                                            )
                                        finally:
                                            db_upd.close()

                                    self._emit("DETECTION_UPDATED", {
                                        "job_id":            self.job_id,
                                        "detection_id":      target_det_id,
                                        "track_id":          tid,
                                        "detected_plate":    resolved_plate,
                                        "ocr_confidence":    round(buf.resolved_conf, 4),
                                        "plate_confidence":  round(buf.best_plate_conf, 4),
                                        "crop_path":         f"/detection-image/{target_det_id}.jpg" if best_v_crop is not None else None,
                                        "plate_crop_path":   f"/detection-image/plate_{target_det_id}.jpg" if buf.best_crop is not None else None,
                                        "read_count":        buf.read_count,
                                        "anpr_provider":     "indian_parseq",
                                    })
                            else:
                                # New unique vehicle with valid plate
                                best_v_crop = self._best_vehicle_crops.get(tid, {}).get("crop")
                                if best_v_crop is None:
                                    vx1, vy1, vx2, vy2 = trk["bbox"]
                                    vw, vh = max(1, vx2 - vx1), max(1, vy2 - vy1)
                                    pad_vx, pad_vy = int(vw * 0.08), int(vh * 0.08)
                                    best_v_crop = frame[max(0, int(vy1 - pad_vy)):min(h, int(vy2 + pad_vy)),
                                                        max(0, int(vx1 - pad_vx)):min(w, int(vx2 + pad_vx))]

                                if self.db_session_factory:
                                    db = self.db_session_factory()
                                    try:
                                        sighting_uuid = str(uuid.uuid4())
                                        event = TrackedEvent(
                                            sighting_id = sighting_uuid,
                                            track_id    = tid,
                                            camera_id   = f"rec-{self.job_id[:8]}",
                                            class_name  = trk["class_name"],
                                            confidence  = trk["confidence"],
                                            bbox        = tuple(map(int, trk["bbox"])),
                                            crop        = best_v_crop if getattr(best_v_crop, "size", 0) > 0 else None,
                                            pts_ms      = pts_ms,
                                            timestamp   = datetime.now(timezone.utc),
                                        )
                                        meta = self.writer.persist_sighting(
                                            db                 = db,
                                            camera_uuid        = self.camera_uuid,
                                            event              = event,
                                            source_type        = "recorded",
                                            video_timestamp_ms = pts_ms,
                                        )
                                        det_id = meta["detection_id"]

                                        # Update sighting with resolved plate details
                                        class _PR:
                                            plate_text           = resolved_plate
                                            normalized_text      = resolved_plate
                                            confidence           = buf.resolved_conf
                                            detection_confidence = buf.best_plate_conf
                                            provider             = "indian_parseq"
                                            crop                 = buf.best_crop
                                        self.writer.update_sighting_plate(
                                            db, det_id, _PR(), self.camera_uuid, self.camera_name, trk["class_name"], vehicle_crop=best_v_crop
                                        )
                                    finally:
                                        db.close()
                                else:
                                    det_id = str(uuid.uuid4())[:8]
                                    meta = {
                                        "detection_id": det_id,
                                        "crop_path": f"/detection-image/{det_id}.jpg" if best_v_crop is not None else None,
                                        "watchlist_match": False,
                                        "alert_id": None,
                                        "vehicle_track_id": f"trk-{tid}",
                                    }

                                self._track_sighting_ids[tid] = det_id
                                self._persisted_tracks.add(tid)
                                self._last_emitted_plates[tid] = resolved_plate
                                self.total_detections += 1

                                self._seen_plates[resolved_plate] = {
                                    "detection_id":  det_id,
                                    "track_id":      tid,
                                    "plate":         resolved_plate,
                                    "class_name":    trk["class_name"],
                                    "best_conf":     buf.resolved_conf,
                                    "read_count":    buf.read_count,
                                    "first_seen_ms": pts_ms,
                                    "last_seen_ms":  pts_ms,
                                }

                                self._emit("NEW_DETECTION", {
                                    "job_id":            self.job_id,
                                    "detection_id":      det_id,
                                    "track_id":          tid,
                                    "camera_name":       self.camera_name,
                                    "class_name":        trk["class_name"],
                                    "confidence":        round(trk["confidence"] * 100, 1),
                                    "timestamp":         datetime.now(timezone.utc).strftime("%H:%M:%S"),
                                    "pts_ms":            round(pts_ms, 1),
                                    "detected_plate":    resolved_plate,
                                    "ocr_confidence":    round(buf.resolved_conf, 4),
                                    "plate_confidence":  round(buf.best_plate_conf, 4),
                                    "watchlist_match":   meta.get("watchlist_match", False),
                                    "alert_id":          meta.get("alert_id"),
                                    "anpr_provider":     "indian_parseq",
                                    "crop_path":         meta.get("crop_path"),
                                    "plate_crop_path":   f"/detection-image/plate_{det_id}.jpg" if buf.best_crop is not None else None,
                                    "vehicle_track_id":  meta.get("vehicle_track_id"),
                                    "read_count":        buf.read_count,
                                })
                    else:
                        # Vehicle has no plate read yet: only persist if prominent vehicle (area >= 1.2% frame) and alive >= 25 frames
                        vx1, vy1, vx2, vy2 = trk["bbox"]
                        v_area = max(0, vx2 - vx1) * max(0, vy2 - vy1) / (w * h)
                        if tid not in self._persisted_tracks and self._track_frames_alive[tid] >= 25 and v_area >= 0.012:
                            best_v_crop = self._best_vehicle_crops.get(tid, {}).get("crop")
                            if best_v_crop is None:
                                vw, vh = max(1, vx2 - vx1), max(1, vy2 - vy1)
                                pad_vx, pad_vy = int(vw * 0.08), int(vh * 0.08)
                                best_v_crop = frame[max(0, int(vy1 - pad_vy)):min(h, int(vy2 + pad_vy)),
                                                    max(0, int(vx1 - pad_vx)):min(w, int(vx2 + pad_vx))]

                            if self.db_session_factory:
                                db = self.db_session_factory()
                                try:
                                    sighting_uuid = str(uuid.uuid4())
                                    event = TrackedEvent(
                                        sighting_id = sighting_uuid,
                                        track_id    = tid,
                                        camera_id   = f"rec-{self.job_id[:8]}",
                                        class_name  = trk["class_name"],
                                        confidence  = trk["confidence"],
                                        bbox        = tuple(map(int, trk["bbox"])),
                                        crop        = best_v_crop if getattr(best_v_crop, "size", 0) > 0 else None,
                                        pts_ms      = pts_ms,
                                        timestamp   = datetime.now(timezone.utc),
                                    )
                                    meta = self.writer.persist_sighting(
                                        db                 = db,
                                        camera_uuid        = self.camera_uuid,
                                        event              = event,
                                        source_type        = "recorded",
                                        video_timestamp_ms = pts_ms,
                                    )
                                    det_id = meta["detection_id"]
                                finally:
                                    db.close()
                            else:
                                det_id = str(uuid.uuid4())[:8]
                                meta = {
                                    "detection_id": det_id,
                                    "crop_path": f"/detection-image/{det_id}.jpg" if best_v_crop is not None else None,
                                    "watchlist_match": False,
                                    "alert_id": None,
                                    "vehicle_track_id": f"trk-{tid}",
                                }

                            self._track_sighting_ids[tid] = det_id
                            self._persisted_tracks.add(tid)
                            self.total_detections += 1

                            self._emit("NEW_DETECTION", {
                                "job_id":            self.job_id,
                                "detection_id":      det_id,
                                "track_id":          tid,
                                "camera_name":       self.camera_name,
                                "class_name":        trk["class_name"],
                                "confidence":        round(trk["confidence"] * 100, 1),
                                "timestamp":         datetime.now(timezone.utc).strftime("%H:%M:%S"),
                                "pts_ms":            round(pts_ms, 1),
                                "detected_plate":    None,
                                "ocr_confidence":    None,
                                "plate_confidence":  None,
                                "watchlist_match":   False,
                                "alert_id":          None,
                                "anpr_provider":     None,
                                "crop_path":         meta.get("crop_path"),
                                "plate_crop_path":   None,
                                "vehicle_track_id":  meta.get("vehicle_track_id"),
                                "read_count":        0,
                            })


                # Emit bounding boxes (with plate tags and plate bboxes)
                plate_boxes_payload = [
                    {
                        "bbox": [
                            round(p.bbox[0] / w, 4),
                            round(p.bbox[1] / h, 4),
                            round(p.bbox[2] / w, 4),
                            round(p.bbox[3] / h, 4),
                        ],
                        "confidence": round(p.confidence * 100, 1),
                    }
                    for p in current_frame_plates
                ]


                self._emit("FRAME_BOXES", {
                    "job_id":        self.job_id,
                    "frame_n":       frame_idx,
                    "boxes":         last_boxes_payload,
                    "plate_boxes":   plate_boxes_payload,
                    "active_tracks": last_active_tracks_len,
                })

                # JPEG encode + transmit video frame
                h, w = frame.shape[:2]
                target_w = min(w, 960)
                if target_w < w:
                    target_h   = int(h * (target_w / w))
                    disp_frame = cv2.resize(frame, (target_w, target_h), interpolation=cv2.INTER_AREA)
                else:
                    disp_frame = frame

                encode_ok, buffer = cv2.imencode(
                    ".jpg", disp_frame, [int(cv2.IMWRITE_JPEG_QUALITY), 65]
                )
                if encode_ok:
                    b64_frame = base64.b64encode(buffer).decode("ascii")
                    self._emit("VIDEO_FRAME", {
                        "job_id":       self.job_id,
                        "frame_n":      frame_idx,
                        "total_frames": self.total_frames,
                        "pts_ms":       round(pts_ms, 1),
                        "jpeg_b64":     b64_frame,
                    })

                # Periodic progress
                if frame_idx % 5 == 0 or frame_idx == self.total_frames:
                    pct = round((frame_idx / self.total_frames) * 100, 1)
                    self._emit("JOB_PROGRESS", {
                        "job_id":           self.job_id,
                        "frame_n":          frame_idx,
                        "total_frames":     self.total_frames,
                        "pct":              min(100.0, pct),
                        "processing_fps":   self.processing_fps,
                        "state":            self.state,
                        "total_detections": self.total_detections,
                    })

                # Pacing
                if frame_delay > 0:
                    elapsed    = time.time() - loop_t0
                    sleep_time = frame_delay - elapsed
                    if sleep_time > 0.001:
                        time.sleep(sleep_time)

            # ── End of video ──────────────────────────────────────
            # Final summary emission for all observed unique plates
            for p, pdata in self._seen_plates.items():
                self._emit("SIGHTING_AGGREGATED", {
                    "job_id":           self.job_id,
                    "track_id":         pdata["track_id"],
                    "plate":            pdata["plate"],
                    "ocr_confidence":   pdata["best_conf"],
                    "plate_confidence": 0.85,
                    "read_count":       pdata["read_count"],
                    "first_seen_ms":    pdata["first_seen_ms"],
                    "last_seen_ms":     pdata["last_seen_ms"],
                    "anpr_provider":    "indian_parseq",
                })

            if self._stop_event.is_set():
                self.state = "stopped"
                logger.info(f"[{self.job_id}] Stopped by user.")
            else:
                self.state = "completed"
                logger.info(
                    f"[{self.job_id}] Completed. "
                    f"Processed {frame_idx}/{self.total_frames} frames, "
                    f"{self.total_detections} clean deduplicated detections."
                )
                self._emit("JOB_DONE", {
                    "job_id":           self.job_id,
                    "total_frames":     frame_idx,
                    "total_detections": self.total_detections,
                })

        except Exception as err:
            self.state = "error"
            logger.exception(f"[{self.job_id}] Worker exception: {err}")
            self._emit("JOB_ERROR", {"job_id": self.job_id, "error": str(err)})
        finally:
            cap.release()

    def start(self):
        if self.state in ("running", "paused"):
            return
        self._stop_event.clear()
        self._pause_event.set()
        self._thread = threading.Thread(
            target=self._run,
            name=f"RecordedWorker-{self.job_id[:8]}",
            daemon=True,
        )
        self._thread.start()

    def pause(self):
        if self.state == "running":
            self._pause_event.clear()
            self.state = "paused"
            self._emit("JOB_PROGRESS", {
                "job_id": self.job_id,
                "state":  "paused",
                "pct":    round((self.current_frame / self.total_frames) * 100, 1),
            })
            logger.info(f"[{self.job_id}] Paused.")

    def resume(self):
        if self.state == "paused":
            self._pause_event.set()
            self.state = "running"
            self._emit("JOB_PROGRESS", {
                "job_id": self.job_id,
                "state":  "running",
                "pct":    round((self.current_frame / self.total_frames) * 100, 1),
            })
            logger.info(f"[{self.job_id}] Resumed.")

    def stop(self):
        self._stop_event.set()
        self._pause_event.set()
        self.state = "stopped"
        logger.info(f"[{self.job_id}] Stop requested.")
