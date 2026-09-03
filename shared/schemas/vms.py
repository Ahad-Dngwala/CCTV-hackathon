"""
Pydantic schemas for the government camera grid catalogue.

These model the shape of GET /api/ingest on the government grid —
they do NOT duplicate or replace shared/schemas/camera.py, which is
the DB read model for the cameras table.

  GridCameraEntry  — one entry from the external grid API response
  GridCatalogueResponse — full response wrapper (list of entries)
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


class GridCameraEntry(BaseModel):
    """Mirrors one entry from GET /api/ingest on the government grid."""

    id: str                          # grid's own id e.g. "1", "2" — this is source_grid_id in our DB
    location: str                    # raw location label
    live: bool
    codec: Optional[str] = None      # "h264" | "hevc" | "" (blank = unknown)
    width: Optional[int] = None
    height: Optional[int] = None
    fps: Optional[float] = None
    bitrate: Optional[int] = None    # kbps
    rtsp_url: Optional[str] = None
    webrtc_url: Optional[str] = None  # grid calls it webrtc_url; it's WHEP specifically
    hls_url: Optional[str] = None


class GridCatalogueResponse(BaseModel):
    """Full response from GET /api/ingest."""

    cameras: list[GridCameraEntry]
