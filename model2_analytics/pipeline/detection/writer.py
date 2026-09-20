"""
Detection Writer
=================
Persists one detection record per confirmed vehicle sighting.
Integrates real ANPR/OCR (via injected PlateRecognizerInterface),
watchlist matching, and alert generation.

Architecture
------------
DetectionWriter.persist_sighting()
    ↓
    AwirosPlateRecognizer.recognize()   → PlateResult | None
    ↓
    WatchlistMatcher.check_plate()      → WatchlistMatch | None
    ↓
    AlertService.create_alert()         → alert_id | None
    ↓
    INSERT detections row (extended ANPR columns)
    ↓
    Save vehicle crop + plate crop to detection-image/
    ↓
    Return metadata dict for WebSocket broadcast

No fake plates. Never returns a fabricated plate value.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, Optional

import cv2
import numpy as np
from sqlalchemy import text
from sqlalchemy.orm import Session

from pipeline.plate.interface import PlateRecognizerInterface, PlateResult
from pipeline.tracking.associator_interface import (
    TrackAssociatorInterface,
    TrackAssociatorStub,
)
from pipeline.tracking.frame_tracker import TrackedEvent

logger = logging.getLogger("sentinel.writer")
logger.setLevel(logging.INFO)

# ── Detection image directory ────────────────────────────────────────
_CROPS_CANDIDATES = [
    Path("/model2-analytics/detection-image"),
    Path("/app/model2_analytics/detection-image"),
    Path(__file__).resolve().parents[2] / "detection-image",
]
CROPS_BASE = next((p for p in _CROPS_CANDIDATES if p.is_dir()), _CROPS_CANDIDATES[0])
CROPS_BASE.mkdir(parents=True, exist_ok=True)


def _save_image(image, filename: str) -> Optional[str]:
    """Save a BGR numpy image to CROPS_BASE. Returns web path or None."""
    if image is None:
        return None
    try:
        arr = image if isinstance(image, np.ndarray) else np.array(image)
        if arr.size == 0:
            return None
        CROPS_BASE.mkdir(parents=True, exist_ok=True)
        path = CROPS_BASE / filename
        cv2.imwrite(str(path), arr, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
        return f"/detection-image/{filename}"
    except Exception as e:
        logger.warning(f"Could not save image {filename}: {e}")
        return None


class DetectionWriter:
    """
    Writes one detection record per TrackedEvent.

    Parameters
    ----------
    plate_recognizer :
        Real ANPR provider. Pass None only from tests that don't need ANPR.
        Production code should always inject a real recognizer.
    track_associator :
        Cross-camera track linker (stub by default).
    alert_callback :
        Callable receiving the WS event dict for watchlist alerts.
        Wired up by the runner/worker from the on_detection_event function.
    """

    def __init__(
        self,
        plate_recognizer: Optional[PlateRecognizerInterface] = None,
        track_associator: Optional[TrackAssociatorInterface] = None,
        alert_callback: Optional[Callable[[Dict], None]] = None,
    ):
        self.plate_recognizer = plate_recognizer  # None → ANPR disabled
        self.track_associator = track_associator or TrackAssociatorStub()
        self.alert_callback   = alert_callback

        # Lazy-load watchlist and alert services
        self._matcher = None
        self._alert_service = None

    def _get_matcher(self):
        if self._matcher is None:
            from pipeline.events.watchlist_matcher import WatchlistMatcher
            self._matcher = WatchlistMatcher()
        return self._matcher

    def _get_alert_service(self):
        if self._alert_service is None:
            from pipeline.events.alert_service import AlertService
            self._alert_service = AlertService(
                on_detection_event=self.alert_callback or (lambda _: None)
            )
        return self._alert_service

    # ── Main entry point ─────────────────────────────────────────────
    def persist_sighting(
        self,
        db: Session,
        camera_uuid: uuid.UUID,
        event: TrackedEvent,
        source_type: str = "live",
        video_timestamp_ms: Optional[float] = None,
    ) -> Dict:
        """
        Persist one detection sighting.

        Returns a metadata dict for WebSocket broadcast containing:
        detection_id, detected_plate, normalized_plate, ocr_confidence,
        plate_confidence, watchlist_match, alert_id, anpr_provider,
        vehicle_track_id, crop_path, plate_crop_path.
        """
        detection_id = str(uuid.uuid4())

        # ── 1. Plate recognition ────────────────────────────────────
        plate_result: Optional[PlateResult] = None
        plate_text:   Optional[str] = None
        normalized:   Optional[str] = None
        ocr_conf:     Optional[float] = None
        plate_conf:   Optional[float] = None
        provider:     Optional[str] = None

        if self.plate_recognizer is not None and event.crop is not None:
            try:
                plate_result = self.plate_recognizer.recognize(
                    frame        = event.crop,
                    vehicle_bbox = event.bbox,
                    timestamp_ms = video_timestamp_ms or event.pts_ms,
                )
            except Exception as e:
                logger.warning(f"[{event.camera_id}] ANPR recognize() error: {e}")

        if plate_result is not None:
            plate_text = plate_result.plate_text
            normalized = plate_result.normalized_text or plate_result.plate_text
            ocr_conf   = plate_result.confidence
            plate_conf = plate_result.detection_confidence
            provider   = plate_result.provider

        # ── 2. Cross-camera track association ───────────────────────
        vehicle_track_id: Optional[str] = None
        try:
            assoc = self.track_associator.associate(
                camera_id    = event.camera_id,
                timestamp    = event.timestamp,
                vehicle_crop = event.crop,
                plate        = normalized,
            )
            if assoc:
                vehicle_track_id = str(assoc)
                db.execute(
                    text("""
                        INSERT INTO vehicle_tracks
                            (id, plate_number, vehicle_type, first_seen, last_seen)
                        VALUES (:id, :plate, :vtype, :first_seen, :last_seen)
                        ON CONFLICT (id) DO UPDATE
                        SET last_seen    = EXCLUDED.last_seen,
                            plate_number = COALESCE(
                                vehicle_tracks.plate_number,
                                EXCLUDED.plate_number
                            )
                    """),
                    {
                        "id":         vehicle_track_id,
                        "plate":      normalized,
                        "vtype":      event.class_name,
                        "first_seen": event.timestamp,
                        "last_seen":  event.timestamp,
                    },
                )
        except Exception as e:
            logger.warning(f"[{event.camera_id}] vehicle_tracks upsert failed: {e}")

        # ── 3. Save vehicle crop image ───────────────────────────────
        crop_path = None
        if event.crop is not None:
            crop_path = _save_image(event.crop, f"{detection_id}.jpg")

        # ── 4. Save plate crop image (separate file) ─────────────────
        plate_crop_path = None
        if plate_result is not None and plate_result.crop is not None:
            plate_crop_path = _save_image(
                plate_result.crop, f"{detection_id}_plate.jpg"
            )

        # ── 5. Watchlist match ───────────────────────────────────────
        watchlist_match = False
        alert_id: Optional[str] = None

        if normalized:
            try:
                match = self._get_matcher().check_plate(db, normalized)
                if match:
                    watchlist_match = True
                    alert_id = self._get_alert_service().create_alert(
                        db           = db,
                        detection_id = detection_id,
                        match        = match,
                        camera_name  = event.camera_id,
                        plate_text   = normalized,
                        vehicle_class = event.class_name,
                        crop_path    = crop_path,
                        confidence   = ocr_conf,
                    )
            except Exception as e:
                logger.warning(f"[{event.camera_id}] Watchlist check error: {e}")

        # ── 6. DB INSERT ─────────────────────────────────────────────
        try:
            db.execute(
                text("""
                    INSERT INTO detections (
                        id, camera_id, "timestamp", event_type,
                        detected_plate, vehicle_type, confidence,
                        cropped_image_path, vehicle_track_id,
                        ocr_confidence, plate_confidence,
                        plate_crop_path, anpr_provider,
                        source_type, video_timestamp_ms
                    ) VALUES (
                        :id, :camera_id, :ts, 'vehicle_detection',
                        :plate, :vtype, :conf,
                        :crop_path, :track_id,
                        :ocr_conf, :plate_conf,
                        :plate_crop_path, :provider,
                        :source_type, :video_ts_ms
                    )
                """),
                {
                    "id":              detection_id,
                    "camera_id":       str(camera_uuid),
                    "ts":              event.timestamp,
                    "plate":           normalized,
                    "vtype":           event.class_name,
                    "conf":            round(event.confidence, 4),
                    "crop_path":       crop_path,
                    "track_id":        vehicle_track_id,
                    "ocr_conf":        round(ocr_conf, 4) if ocr_conf else None,
                    "plate_conf":      round(plate_conf, 4) if plate_conf else None,
                    "plate_crop_path": plate_crop_path,
                    "provider":        provider,
                    "source_type":     source_type,
                    "video_ts_ms":     video_timestamp_ms,
                },
            )
            db.commit()
            logger.info(
                f"[{event.camera_id}] Persisted {detection_id} "
                f"({event.class_name} conf={event.confidence:.2f} "
                f"plate={normalized or '—'} "
                f"watchlist={'YES' if watchlist_match else 'no'})"
            )
        except Exception as e:
            db.rollback()
            logger.error(f"[{event.camera_id}] DB insert failed: {e}")

        return {
            "detection_id":     detection_id,
            "detected_plate":   normalized,
            "plate_text_raw":   plate_text,
            "ocr_confidence":   ocr_conf,
            "plate_confidence": plate_conf,
            "anpr_provider":    provider,
            "watchlist_match":  watchlist_match,
            "alert_id":         alert_id,
            "vehicle_track_id": vehicle_track_id,
            "crop_path":        crop_path,
            "plate_crop_path":  plate_crop_path,
        }

    def update_sighting_plate(
        self,
        db: Session,
        detection_id: str,
        plate_result: object,
        camera_uuid: uuid.UUID,
        camera_name: str,
        vehicle_class: str,
    ):
        """Update an existing detection record when a new best plate read is obtained."""
        if not plate_result or not detection_id:
            return

        normalized = getattr(plate_result, "normalized_text", None) or getattr(plate_result, "plate_text", None)
        plate_text = getattr(plate_result, "plate_text", "")
        ocr_conf = getattr(plate_result, "confidence", 0.0)
        plate_conf = getattr(plate_result, "detection_confidence", None)
        provider = getattr(plate_result, "provider", "indian_parseq")
        crop = getattr(plate_result, "crop", None)

        plate_crop_path = None
        if crop is not None and getattr(crop, "size", 0) > 0:
            import cv2
            fname = f"plate_{detection_id}.jpg"
            dest_dir = Path(__file__).resolve().parents[2] / "detection-image"
            dest_dir.mkdir(parents=True, exist_ok=True)
            cv2.imwrite(str(dest_dir / fname), crop)
            plate_crop_path = f"/detection-image/{fname}"

        # Check watchlist
        watchlist_match = False
        alert_id = None
        if normalized:
            try:
                matcher = self._get_matcher()
                matched, entry = matcher.match(normalized)
                if matched and entry:
                    watchlist_match = True
                    alert_service = self._get_alert_service()
                    alert_id = alert_service.raise_alert(
                        db=db,
                        camera_uuid=camera_uuid,
                        detection_id=detection_id,
                        plate_number=normalized,
                        vehicle_type=vehicle_class,
                        camera_name=camera_name,
                        crop_path=plate_crop_path,
                        watchlist_id=entry.get("id"),
                    )
            except Exception as e:
                logger.warning(f"Watchlist check on update failed: {e}")

        try:
            db.execute(
                text("""
                    UPDATE detections SET
                        detected_plate = :plate,
                        ocr_confidence = :ocr_conf,
                        plate_confidence = :plate_conf,
                        plate_crop_path = COALESCE(:plate_crop_path, plate_crop_path),
                        anpr_provider = :provider
                    WHERE id = :id
                """),
                {
                    "id": detection_id,
                    "plate": normalized,
                    "ocr_conf": round(float(ocr_conf), 4) if ocr_conf else None,
                    "plate_conf": round(float(plate_conf), 4) if plate_conf else None,
                    "plate_crop_path": plate_crop_path,
                    "provider": provider,
                }
            )
            db.commit()
            logger.info(f"Updated detection {detection_id} with plate={normalized} (conf={ocr_conf:.2f}, prov={provider})")
        except Exception as e:
            db.rollback()
            logger.error(f"Failed to update detection {detection_id} plate: {e}")
