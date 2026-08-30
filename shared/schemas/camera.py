"""
Pydantic schemas for the cameras table.

Matches the Camera object shape from docs/API_Contract.md §1 exactly:
  id, name, department_id, location {type, coordinates}, district,
  camera_type, ownership, connectivity_status, storage_type,
  retention_days, vms_url, created_at, updated_at.
"""

import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel


# ── GeoJSON helpers ─────────────────────────────────────────────


class GeoJSONPoint(BaseModel):
    """GeoJSON Point — ``{"type": "Point", "coordinates": [lon, lat]}``."""
    type: str = "Point"
    coordinates: list[float]  # [lon, lat]


# ── Camera schemas ──────────────────────────────────────────────


class CameraBase(BaseModel):
    name: str
    department_id: Optional[uuid.UUID] = None
    district_id: Optional[uuid.UUID] = None
    camera_type: Optional[str] = None
    ownership: Optional[str] = None
    storage_type: Optional[str] = None
    retention_days: Optional[int] = None
    vms_url: Optional[str] = None
    connectivity_status: str = "offline"


class CameraCreate(CameraBase):
    """POST /api/v1/cameras — manual entry."""
    latitude: Optional[float] = None
    longitude: Optional[float] = None


class CameraUpdate(BaseModel):
    """PATCH /api/v1/cameras/{id} — partial update, all fields optional."""
    name: Optional[str] = None
    department_id: Optional[uuid.UUID] = None
    district_id: Optional[uuid.UUID] = None
    camera_type: Optional[str] = None
    ownership: Optional[str] = None
    storage_type: Optional[str] = None
    retention_days: Optional[int] = None
    vms_url: Optional[str] = None
    connectivity_status: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None


class Camera(BaseModel):
    """
    Full camera read model — matches API_Contract.md §1's Camera object.
    """
    id: uuid.UUID
    name: str
    department_id: Optional[uuid.UUID] = None
    department_name: Optional[str] = None
    district_id: Optional[uuid.UUID] = None
    district_name: Optional[str] = None
    location: Optional[GeoJSONPoint] = None
    location_label: Optional[str] = None
    camera_type: Optional[str] = None
    ownership: Optional[str] = None
    connectivity_status: str
    storage_type: Optional[str] = None
    retention_days: Optional[int] = None
    vms_url: Optional[str] = None
    is_active: bool
    source_grid_id: Optional[str] = None
    codec: Optional[str] = None
    stream_width: Optional[int] = None
    stream_height: Optional[int] = None
    stream_fps: Optional[float] = None
    bitrate_kbps: Optional[int] = None
    rtsp_url: Optional[str] = None
    whep_url: Optional[str] = None
    hls_url: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class BulkImportResult(BaseModel):
    created: int
    skipped: int
    errored: int
    errors: list[str] = []
