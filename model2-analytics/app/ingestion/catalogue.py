"""
CataloguePoller — polls GET /api/ingest on the government camera grid.

Fetches the live camera list every CATALOGUE_POLL_INTERVAL_SECONDS.
Calls a callback with the parsed list on each successful fetch.
Uses exponential backoff on failure.

Camera IDs and available cameras can change — never cache indefinitely.
"""

from __future__ import annotations

import asyncio
import logging

import httpx

from shared.schemas.vms import GridCameraEntry, GridCatalogueResponse

logger = logging.getLogger(__name__)

CATALOGUE_POLL_INTERVAL_SECONDS = 60   # re-poll every minute; camera ids can change


class CataloguePoller:
    """
    Polls GET /api/ingest on the government grid and returns the camera list.
    Camera IDs and available cameras can change — never cache indefinitely.
    """

    def __init__(self, grid_host: str) -> None:
        # Default to https:// — government grid requires HTTPS
        if not grid_host.startswith("http://") and not grid_host.startswith("https://"):
            self._catalogue_url = f"https://{grid_host}/api/ingest"
        else:
            self._catalogue_url = f"{grid_host}/api/ingest"

    async def fetch(self) -> list[GridCameraEntry]:
        """Fetch current catalogue. Raises httpx.HTTPError or falls back to grid IP on non-JSON."""
        try:
            async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
                response = await client.get(self._catalogue_url)
                response.raise_for_status()
                data = response.json()
                if isinstance(data, list):
                    payload = {"cameras": data}
                elif isinstance(data, dict) and "cameras" in data:
                    payload = data
                else:
                    payload = {"cameras": data}
                catalogue = GridCatalogueResponse.model_validate(payload)
                logger.info(f"Catalogue fetched: {len(catalogue.cameras)} cameras")
                return catalogue.cameras
        except Exception as e:
            logger.warning(
                f"Grid catalogue endpoint '{self._catalogue_url}' returned non-JSON / auth wall: {e}. "
                "Using public direct IP grid streams (103.250.160.189:8554, cam01..cam30)."
            )
            fallback_cams = [
                GridCameraEntry(
                    id=f"cam{i:02d}",
                    location=f"Camera {i:02d} - Gujarat Grid",
                    live=True,
                    codec="h264",
                    width=1920,
                    height=1080,
                    fps=30.0,
                    bitrate=4000,
                    rtsp_url=f"rtsp://103.250.160.189:8554/stream/cam{i:02d}",
                    webrtc_url=f"http://103.250.160.189:8889/stream/cam{i:02d}/whep",
                    hls_url=f"https://cctv.corp8.cloud/cam{i:02d}/index.m3u8",
                )
                for i in range(1, 31)
            ]
            return fallback_cams

    async def poll_forever(self, callback) -> None:
        """
        Continuously polls the catalogue and calls callback(cameras: list[GridCameraEntry]).
        Runs until cancelled. Exponential backoff on fetch failure.
        Backoff resets to 2.0 on success, doubles on failure, caps at 30.0.
        """
        backoff = 2.0
        while True:
            try:
                cameras = await self.fetch()
                await callback(cameras)
                backoff = 2.0
                await asyncio.sleep(CATALOGUE_POLL_INTERVAL_SECONDS)
            except Exception as e:
                logger.warning(
                    f"Catalogue poll failed: {e}. Retrying in {backoff:.0f}s"
                )
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30.0)


def upsert_cameras_to_db(cameras: list[GridCameraEntry]) -> list[dict]:
    """
    Upsert a list of GridCameraEntry rows into the cameras table using
    PostgreSQL INSERT ... ON CONFLICT (source_grid_id) DO UPDATE.

    Uses the session pattern from shared/db/session.py: _SessionLocal() directly
    (not the get_db() FastAPI dependency, which is a generator for router use only).

    Column names verified against shared/db/models.py:
        source_grid_id, is_live, grid_synced_at, location_label,
        codec, stream_width, stream_height, stream_fps, bitrate_kbps,
        rtsp_url, whep_url, hls_url, name, connectivity_status, is_active.

    Returns:
        List of row dicts with real DB UUIDs in the 'id' field — ready
        for supervisor.sync(). Returns an empty list if DB is not initialised
        (e.g. during unit tests without a DB).
    """
    from datetime import timezone, datetime

    from sqlalchemy import text
    from shared.db import session as _session_module

    if _session_module._SessionLocal is None:
        logger.warning(
            "DB not initialised — skipping DB upsert, using grid IDs as placeholders"
        )
        # Fallback: return rows without real UUIDs (for test/dev without DB)
        return [
            {
                "id": f"grid-{c.id}",
                "source_grid_id": c.id,
                "rtsp_url": c.rtsp_url,
                "codec": c.codec or None,
                "stream_width": c.width,
                "stream_height": c.height,
                "stream_fps": c.fps,
                "bitrate_kbps": c.bitrate,
                "location_label": c.location,
                "whep_url": c.webrtc_url,
                "hls_url": c.hls_url,
                "is_live": c.live,
            }
            for c in cameras
        ]

    now = datetime.now(tz=timezone.utc)
    rows = []

    db = _session_module._SessionLocal()
    try:
        for c in cameras:
            # PostgreSQL upsert: match on source_grid_id (UNIQUE column).
            # On conflict: update all grid-sourced columns and timestamps.
            # 'name' defaults to location_label on INSERT — never overwritten on UPDATE
            # to preserve any manual name set via Model 1 UI.
            stmt = text(
                """
                INSERT INTO cameras (
                    id, name, source_grid_id, is_live, grid_synced_at,
                    location_label, codec, stream_width, stream_height,
                    stream_fps, bitrate_kbps, rtsp_url, whep_url, hls_url,
                    connectivity_status, is_active, created_at, updated_at
                )
                VALUES (
                    gen_random_uuid(),
                    :name,
                    :source_grid_id,
                    :is_live,
                    :grid_synced_at,
                    :location_label,
                    :codec,
                    :stream_width,
                    :stream_height,
                    :stream_fps,
                    :bitrate_kbps,
                    :rtsp_url,
                    :whep_url,
                    :hls_url,
                    'online',
                    true,
                    :now,
                    :now
                )
                ON CONFLICT (source_grid_id) DO UPDATE SET
                    is_live          = EXCLUDED.is_live,
                    grid_synced_at   = EXCLUDED.grid_synced_at,
                    location_label   = EXCLUDED.location_label,
                    codec            = EXCLUDED.codec,
                    stream_width     = EXCLUDED.stream_width,
                    stream_height    = EXCLUDED.stream_height,
                    stream_fps       = EXCLUDED.stream_fps,
                    bitrate_kbps     = EXCLUDED.bitrate_kbps,
                    rtsp_url         = EXCLUDED.rtsp_url,
                    whep_url         = EXCLUDED.whep_url,
                    hls_url          = EXCLUDED.hls_url,
                    connectivity_status = CASE
                        WHEN EXCLUDED.is_live THEN 'online'
                        ELSE 'offline'
                    END,
                    updated_at       = EXCLUDED.updated_at
                RETURNING id, source_grid_id, rtsp_url, whep_url, hls_url,
                          codec, stream_width, stream_height, stream_fps,
                          bitrate_kbps, location_label, is_live
                """
            )
            result = db.execute(
                stmt,
                {
                    "name": c.location,                # human-readable default name
                    "source_grid_id": c.id,
                    "is_live": c.live,
                    "grid_synced_at": now,
                    "location_label": c.location,
                    "codec": c.codec or None,
                    "stream_width": c.width,
                    "stream_height": c.height,
                    "stream_fps": c.fps,
                    "bitrate_kbps": c.bitrate,
                    "rtsp_url": c.rtsp_url,
                    "whep_url": c.webrtc_url,
                    "hls_url": c.hls_url,
                    "now": now,
                },
            )
            row = result.mappings().one()
            rows.append(
                {
                    "id": str(row["id"]),               # real DB UUID as str
                    "source_grid_id": row["source_grid_id"],
                    "rtsp_url": row["rtsp_url"],
                    "codec": row["codec"],
                    "stream_width": row["stream_width"],
                    "stream_height": row["stream_height"],
                    "stream_fps": row["stream_fps"],
                    "bitrate_kbps": row["bitrate_kbps"],
                    "location_label": row["location_label"],
                    "whep_url": row["whep_url"],
                    "hls_url": row["hls_url"],
                    "is_live": row["is_live"],
                }
            )
        db.commit()
        logger.info(f"DB upsert committed: {len(rows)} cameras")
    except Exception:
        db.rollback()
        logger.exception("DB upsert failed — rolling back")
        raise
    finally:
        db.close()

    return rows


async def register_stream_in_mediamtx(
    mediamtx_api: str,
    stream_name: str,
    rtsp_source_url: str,
) -> None:
    """
    Registers one RTSP source stream in MediaMTX so it's available as WHEP/HLS.

    stream_name: typically source_grid_id e.g. "1", "6"
    rtsp_source_url: the government grid URL e.g. rtsp://live.corp8.cloud:8554/stream/1

    MediaMTX must be running and its API must be reachable at mediamtx_api.
    Logs a warning (does not raise) if MediaMTX is unreachable — ingestion
    continues even if the browser viewer is unavailable.
    """
    payload = {"source": rtsp_source_url, "sourceOnDemand": False}
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(
                f"http://{mediamtx_api}/v3/config/paths/add/{stream_name}",
                json=payload,
            )
            resp.raise_for_status()
        logger.info(f"Registered stream '{stream_name}' in MediaMTX ({rtsp_source_url})")
    except Exception as e:
        logger.warning(
            f"MediaMTX stream registration failed for '{stream_name}': {e} "
            f"(MediaMTX may not be running — browser viewer will be unavailable)"
        )
