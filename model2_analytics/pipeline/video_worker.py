"""
Model 2 — Pre-Recorded Video AI Detection Worker
=================================================
Runs an isolated, on-demand video detection and tracking pipeline for uploaded
video files (.mp4, .avi, .mov, .mkv).

Reuses existing core components:
  - VehicleDetector: YOLOv8 Indian Traffic detection
  - InFrameTracker: Single-camera IoU + centroid tracker
  - DetectionWriter: Database persistence with real ANPR/OCR
  - AwirosPlateRecognizer: Injected via anpr_service

Temporal aggregation:
  Multiple frame reads of the same plate (e.g. GJ01AB1234 at frames 12/13/14)
  are collapsed into ONE logical sighting with best confidence, read_count,
  first_seen, last_seen, and best evidence crop.
"""

import base64
import logging
import threading
import time
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional

import cv2
from sqlalchemy.orm import Session

from pipeline.detection.vehicle_detector import VehicleDetector
from pipeline.detection.writer import DetectionWriter
from pipeline.plate.anpr_service import get_plate_recognizer
from pipeline.plate.plate_detector import PlateDetector
from pipeline.tracking.frame_tracker import InFrameTracker

logger = logging.getLogger("sentinel.video_worker")
logger.setLevel(logging.INFO)

SPEED_TO_INFER_EVERY = {
    "1x":  2,
    "2x":  4,
    "max": 6,
}

# Minimum reads before we commit a plate as "confirmed"
_MIN_READS_TO_COMMIT = 2


class _TrackPlateBuffer:
    """Accumulates per-frame plate reads for one track, then flushes best result."""

    def __init__(self, track_id: int):
        self.track_id   = track_id
        self.reads: List[Dict] = []   # each: {text, normalized, ocr_conf, plate_conf, provider, crop, pts_ms}
        self.first_seen_ms: Optional[float] = None
        self.last_seen_ms:  Optional[float] = None

    def add(self, plate_result, pts_ms: float):
        if self.first_seen_ms is None:
            self.first_seen_ms = pts_ms
        self.last_seen_ms = pts_ms
        self.reads.append({
            "text":       plate_result.plate_text,
            "normalized": plate_result.normalized_text,
            "ocr_conf":   plate_result.confidence,
            "plate_conf": plate_result.detection_confidence,
            "provider":   plate_result.provider,
            "crop":       plate_result.crop,
            "pts_ms":     pts_ms,
        })

    def best(self) -> Optional[Dict]:
        """Return the highest-OCR-confidence read, or None if no reads."""
        if not self.reads:
            return None
        return max(self.reads, key=lambda r: r["ocr_conf"] or 0.0)

    @property
    def read_count(self) -> int:
        return len(self.reads)

    @property
    def normalized_plate(self) -> Optional[str]:
        b = self.best()
        return b["normalized"] if b else None


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
        self.job_id            = job_id
        self.file_path         = file_path
        self.camera_uuid       = camera_uuid
        self.camera_name       = camera_name
        self.speed             = speed if speed in SPEED_TO_INFER_EVERY else "1x"
        self.anpr_rate         = max(1, anpr_rate)
        self.event_callback    = event_callback
        self.db_session_factory = db_session_factory

        self.tracker  = InFrameTracker(
            camera_id=f"rec-{job_id[:8]}",
            min_confirmed_frames=2,
            iou_threshold=0.25,
        )
        self.detector = VehicleDetector(confidence_threshold=0.15)
        self.plate_detector = PlateDetector(confidence_threshold=0.20)
        
        from concurrent.futures import ThreadPoolExecutor
        self._ocr_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="video-ocr")
        self._last_ocr_pts: Dict[int, float] = {}
        self._sighting_ids: Dict[int, str] = {}

        _recognizer = get_plate_recognizer()   # None if ANPR disabled
        self.writer  = DetectionWriter(
            plate_recognizer = _recognizer,
            alert_callback   = event_callback,
        )

        # Per-track plate aggregation buffer: track_id → _TrackPlateBuffer
        self._plate_buffers: Dict[int, _TrackPlateBuffer] = {}

        self._thread:      Optional[threading.Thread] = None
        self._pause_event  = threading.Event()
        self._pause_event.set()   # starts unpaused
        self._stop_event   = threading.Event()

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

    # ── Temporal aggregation helpers ─────────────────────────────────

    def _record_plate_for_track(self, track_id: int, plate_result, pts_ms: float):
        """Add a plate read to the per-track buffer."""
        if track_id not in self._plate_buffers:
            self._plate_buffers[track_id] = _TrackPlateBuffer(track_id)
        self._plate_buffers[track_id].add(plate_result, pts_ms)

    def _emit_aggregated_sighting(self, track_id: int):
        """Emit SIGHTING_AGGREGATED for a completed track."""
        buf = self._plate_buffers.get(track_id)
        if buf is None or buf.read_count == 0:
            return
        best = buf.best()
        if best:
            self._emit("SIGHTING_AGGREGATED", {
                "job_id":          self.job_id,
                "track_id":        track_id,
                "plate":           best["normalized"],
                "ocr_confidence":  best["ocr_conf"],
                "plate_confidence": best["plate_conf"],
                "read_count":      buf.read_count,
                "first_seen_ms":   buf.first_seen_ms,
                "last_seen_ms":    buf.last_seen_ms,
                "anpr_provider":   best["provider"],
            })

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

        try:
            while not self._stop_event.is_set():
                self._pause_event.wait()
                if self._stop_event.is_set():
                    break

                loop_t0 = time.time()
                ok, frame = cap.read()
                if not ok:
                    break

                frame_idx  += 1
                self.current_frame = frame_idx
                fps_frames_count   += 1
                pts_ms = cap.get(cv2.CAP_PROP_POS_MSEC) or (frame_idx * 1000.0 / self.fps)

                now = time.time()
                elapsed_chk = now - t_fps_checkpoint
                if elapsed_chk >= 1.0:
                    self.processing_fps  = round(fps_frames_count / elapsed_chk, 1)
                    fps_frames_count     = 0
                    t_fps_checkpoint     = now

                should_infer = (frame_idx % infer_every == 0)
                if should_infer:
                    raw_dets = self.detector.detect(frame, pts_ms=pts_ms)
                    new_events, active_tracks = self.tracker.update(raw_dets, pts_ms=pts_ms)
                    h, w = frame.shape[:2]

                    last_boxes_payload = [
                        {
                            "track_id":   trk.track_id,
                            "bbox": [
                                round(trk.bbox[0] / w, 4),
                                round(trk.bbox[1] / h, 4),
                                round(trk.bbox[2] / w, 4),
                                round(trk.bbox[3] / h, 4),
                            ],
                            "class_name": trk.class_name,
                            "confidence": round(trk.best_conf * 100, 1),
                        }
                        for trk in active_tracks
                        if trk.missed_frames == 0
                    ]
                    last_active_tracks_len = len(active_tracks)

                    # ── Full Frame Plate Detection & Fine-Tuned Indian PARSeq OCR ────
                    if self.writer.plate_recognizer and active_tracks:
                        try:
                            frame_plates = self.plate_detector.detect(frame)
                            for pd in frame_plates:
                                px1, py1, px2, py2 = map(int, pd.bbox)
                                pw, ph = px2 - px1, py2 - py1
                                if pw < 18 or ph < 8:
                                    continue
                                pad_x = int(pw * 0.10)
                                pad_y = int(ph * 0.12)
                                pcrop = frame[max(0, py1 - pad_y):min(h, py2 + pad_y),
                                              max(0, px1 - pad_x):min(w, px2 + pad_x)]
                                if pcrop.size == 0:
                                    continue

                                # Associate plate to nearest vehicle in active_tracks
                                pcx, pcy = (px1 + px2) / 2.0, (py1 + py2) / 2.0
                                cand = []
                                for trk in active_tracks:
                                    vx1, vy1, vx2, vy2 = trk.bbox
                                    vw, vh = max(1, vx2 - vx1), max(1, vy2 - vy1)
                                    if pcy < vy1 + 0.15 * vh or pcy > vy2 + 0.20 * vh:
                                        continue
                                    dx = abs(pcx - (vx1 + vx2) / 2.0) / vw
                                    dy = abs(pcy - (vy1 + vy2 * 0.80)) / vh
                                    pen = 0.0 if (vx1 - 0.15 * vw <= pcx <= vx2 + 0.15 * vw) else 1.5
                                    cand.append((dx + dy + pen, trk))

                                if cand:
                                    matched_trk = min(cand, key=lambda c: c[0])[1]
                                    read_res = self.writer.plate_recognizer.read_plate(pcrop)
                                    clean = read_res.get("text") or getattr(read_res, "plate_text", "")
                                    conf = float(read_res.get("confidence") or getattr(read_res, "confidence", 0.0))
                                    if clean and len(clean) >= 4 and conf >= 0.55:
                                        class _PR:
                                            plate_text = read_res.get("raw_text") or clean
                                            normalized_text = clean
                                            confidence = conf
                                            detection_confidence = pd.confidence
                                            provider = read_res.get("provider") or "indian_parseq"
                                            crop = pcrop
                                        self._record_plate_for_track(matched_trk.track_id, _PR(), pts_ms)
                                        det_id = self._sighting_ids.get(matched_trk.track_id)
                                        if det_id and self.db_session_factory:
                                            db_upd = self.db_session_factory()
                                            try:
                                                self.writer.update_sighting_plate(
                                                    db_upd, det_id, _PR(), self.camera_uuid, self.camera_name, matched_trk.class_name
                                                )
                                            finally:
                                                db_upd.close()
                        except Exception as p_err:
                            logger.warning(f"Plate detect/OCR error in video worker: {p_err}")

                    # ── Async OCR on active tracks ────────────────
                    if self.writer.plate_recognizer and self.db_session_factory:
                        ocr_delay_ms = 1000.0 / self.anpr_rate
                        for trk in active_tracks:
                            if trk.missed_frames == 0 and trk.persisted and trk.best_crop is not None:
                                last_pts = self._last_ocr_pts.get(trk.track_id, -1000)
                                if pts_ms - last_pts >= ocr_delay_ms:
                                    self._last_ocr_pts[trk.track_id] = pts_ms
                                    crop_copy = trk.best_crop.copy()
                                    bbox_copy = trk.bbox
                                    tid = trk.track_id
                                    cname = trk.class_name
                                    
                                    def _do_ocr(track_id, crop, bbox, pts, class_name):
                                        res = self.writer.plate_recognizer.recognize(
                                            crop, (0, 0, crop.shape[1], crop.shape[0]), pts
                                        )
                                        if res:
                                            self._record_plate_for_track(track_id, res, pts)
                                            # Check if this is the new best plate!
                                            buf = self._plate_buffers.get(track_id)
                                            best = buf.best() if buf else None
                                            # If this read is the best so far, update the DB
                                            if best and best["pts_ms"] == pts:
                                                det_id = self._sighting_ids.get(track_id)
                                                if det_id:
                                                    db_upd = self.db_session_factory()
                                                    try:
                                                        self.writer.update_sighting_plate(
                                                            db_upd, det_id, res, self.camera_uuid, self.camera_name, class_name
                                                        )
                                                    finally:
                                                        db_upd.close()
                                                        
                                    self._ocr_executor.submit(_do_ocr, tid, crop_copy, bbox_copy, pts_ms, cname)

                    # ── Persist confirmed sightings ────────────────
                    if new_events and self.db_session_factory:
                        db = self.db_session_factory()
                        if db is not None:
                            try:
                                for event in new_events:
                                    meta = self.writer.persist_sighting(
                                        db                 = db,
                                        camera_uuid        = self.camera_uuid,
                                        event              = event,
                                        source_type        = "recorded",
                                        video_timestamp_ms = pts_ms,
                                    )
                                    self._sighting_ids[event.track_id] = meta["detection_id"]
                                    self.total_detections += 1

                                    # Buffer plate read for aggregation
                                    if meta.get("detected_plate") and self.writer.plate_recognizer:
                                        # Re-use the result stored in meta
                                        # Build a lightweight proxy for the buffer
                                        class _PR:
                                            plate_text           = meta["plate_text_raw"]
                                            normalized_text      = meta["detected_plate"]
                                            confidence           = meta.get("ocr_confidence") or 0.0
                                            detection_confidence = meta.get("plate_confidence")
                                            provider             = meta.get("anpr_provider") or "indian_parseq"
                                            crop                 = None
                                        self._record_plate_for_track(event.track_id, _PR(), pts_ms)

                                    self._emit("NEW_DETECTION", {
                                        "job_id":            self.job_id,
                                        "detection_id":      meta["detection_id"],
                                        "track_id":          event.track_id,
                                        "camera_name":       self.camera_name,
                                        "class_name":        event.class_name,
                                        "confidence":        round(event.confidence * 100, 1),
                                        "timestamp":         event.timestamp.strftime("%H:%M:%S"),
                                        "pts_ms":            round(pts_ms, 1),
                                        "detected_plate":    meta.get("detected_plate"),
                                        "ocr_confidence":    meta.get("ocr_confidence"),
                                        "plate_confidence":  meta.get("plate_confidence"),
                                        "watchlist_match":   meta.get("watchlist_match", False),
                                        "alert_id":          meta.get("alert_id"),
                                        "anpr_provider":     meta.get("anpr_provider"),
                                        "crop_path":         meta.get("crop_path"),
                                        "plate_crop_path":   meta.get("plate_crop_path"),
                                        "vehicle_track_id":  meta.get("vehicle_track_id"),
                                        "read_count":        self._plate_buffers.get(
                                            event.track_id, _TrackPlateBuffer(0)
                                        ).read_count,
                                    })
                            finally:
                                db.close()

                # Emit bounding boxes
                self._emit("FRAME_BOXES", {
                    "job_id":        self.job_id,
                    "frame_n":       frame_idx,
                    "boxes":         last_boxes_payload,
                    "active_tracks": last_active_tracks_len,
                })

                # JPEG encode + transmit video frame
                h, w = frame.shape[:2]
                target_w = min(w, 960)
                if target_w < w:
                    target_h  = int(h * (target_w / w))
                    disp_frame = cv2.resize(frame, (target_w, target_h),
                                            interpolation=cv2.INTER_AREA)
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

                # Playback pacing
                if frame_delay > 0:
                    elapsed    = time.time() - loop_t0
                    sleep_time = frame_delay - elapsed
                    if sleep_time > 0.002:
                        time.sleep(sleep_time)

            # ── End of video ──────────────────────────────────────
            # Flush aggregated sightings for all buffered tracks
            for tid in list(self._plate_buffers.keys()):
                self._emit_aggregated_sighting(tid)

            if self._stop_event.is_set():
                self.state = "stopped"
                logger.info(f"[{self.job_id}] Stopped by user.")
            else:
                self.state = "completed"
                logger.info(
                    f"[{self.job_id}] Completed. "
                    f"Processed {frame_idx}/{self.total_frames} frames, "
                    f"{self.total_detections} detections."
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
        self._pause_event.set()   # unblock if paused
        self.state = "stopped"
        logger.info(f"[{self.job_id}] Stop requested.")
