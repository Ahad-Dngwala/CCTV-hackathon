"""
model3_federation.schemas.models
---------------------------------
Pydantic models used across adapters, the event bus, the
correlation engine, and the REST/WebSocket API.

Design notes:
  - All timestamps are UTC-aware datetimes.
  - `raw_payload` preserves the original vendor JSON for audit trails.
  - Plate normalisation (uppercase, strip spaces/hyphens) is applied
    centrally in the correlation engine — not here — so adapters can
    store exactly what the vendor sent.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator


def _now_utc() -> datetime:
    return datetime.now(tz=timezone.utc)


def _new_id() -> str:
    return str(uuid4())


# ---------------------------------------------------------------------------
# Camera descriptor — one per physical camera in a federated VMS
# ---------------------------------------------------------------------------

class FederatedCamera(BaseModel):
    external_id: str                          # camera ID in the source VMS
    name: str
    system_name: str                          # which VMS this camera belongs to
    vendor: str                               # Milestone | Hikvision | Dahua
    department: str                           # Police | RTO | Municipal
    lat: Optional[float] = None
    lng: Optional[float] = None
    location_label: Optional[str] = None
    is_active: bool = True


# ---------------------------------------------------------------------------
# Detection event — normalised form of whatever a VMS adapter receives
# ---------------------------------------------------------------------------

class FederatedEvent(BaseModel):
    id: str = Field(default_factory=_new_id)
    system_id: str                            # UUID of the vms_systems DB row
    system_name: str                          # e.g. "Gujarat Police VMS (Milestone)"
    vendor: str
    camera_external_id: str
    camera_name: str
    event_type: str                           # "vehicle_detection" | "person_detection" | "intrusion"
    detected_plate: Optional[str] = None
    confidence: Optional[float] = None
    vehicle_type: Optional[str] = None
    snapshot_url: Optional[str] = None
    source_timestamp: datetime = Field(default_factory=_now_utc)
    received_at: datetime = Field(default_factory=_now_utc)
    raw_payload: dict[str, Any] = Field(default_factory=dict)

    class Config:
        # Allow serialisation of datetime objects
        json_encoders = {datetime: lambda v: v.isoformat()}


# ---------------------------------------------------------------------------
# Cross-system correlation — same plate seen in 2+ VMS systems
# ---------------------------------------------------------------------------

class CorrelationResult(BaseModel):
    id: str = Field(default_factory=_new_id)
    plate_number: str
    systems_involved: list[str]               # names of VMS systems that saw this plate
    first_seen: datetime
    last_seen: datetime
    travel_time_secs: Optional[int] = None
    camera_sequence: list[dict[str, Any]] = Field(default_factory=list)
    # [{camera_name, system_name, timestamp, lat, lng}]
    is_watchlisted: bool = False

    class Config:
        json_encoders = {datetime: lambda v: v.isoformat()}


# ---------------------------------------------------------------------------
# Federated watchlist alert — generated when detected_plate hits watchlist
# ---------------------------------------------------------------------------

class FederatedAlert(BaseModel):
    id: str = Field(default_factory=_new_id)
    event_id: str                             # FederatedEvent.id that triggered this
    plate_number: str
    system_name: str
    camera_name: str
    severity: str = "high"                    # low | medium | high | critical
    created_at: datetime = Field(default_factory=_now_utc)
    acknowledged: bool = False

    class Config:
        json_encoders = {datetime: lambda v: v.isoformat()}


# ---------------------------------------------------------------------------
# VMS system descriptor — one per federated department VMS
# ---------------------------------------------------------------------------

class FederatedSystem(BaseModel):
    id: str                                   # UUID from vms_systems table
    name: str
    vendor: str
    department: str
    status: str = "connected"                 # connected | disconnected | error | degraded
    camera_count: int = 0
    events_per_minute: float = 0.0
    last_heartbeat: Optional[datetime] = None

    class Config:
        json_encoders = {datetime: lambda v: v.isoformat()}


# ---------------------------------------------------------------------------
# VMS system manual-onboarding requests (Finding 1) — request bodies for
# POST/PATCH /api/v3/systems. Unlike FederatedSystem above (a read model
# for the API's own GET response), these are the *write* side: a
# dept_admin/operator registering or editing a vms_systems row for an
# integration that doesn't (yet, or ever) have a Python VMSAdapter.
# ---------------------------------------------------------------------------

def _validate_ownership(v: Optional[str]) -> Optional[str]:
    if v is not None and v not in ("government", "private"):
        raise ValueError("ownership must be 'government' or 'private'")
    return v


class VMSSystemCreate(BaseModel):
    name: str
    vendor: Optional[str] = None
    # Integration mechanism, same free-text convention as
    # vms_systems.protocol elsewhere (onvif, vendor-sdk, simulated, ...).
    # "manual" is the sensible default here specifically: a system
    # created through this endpoint has no adapter behind it (that's the
    # point of this endpoint existing), so unless the caller knows the
    # VMS actually speaks a real protocol, this is usually correct as-is.
    protocol: str = "manual"
    ownership: str = "government"
    department_id: Optional[str] = None
    # NEW: config-driven onboarding. When adapter_type is set, `config`
    # must satisfy that type's CONFIG_FIELDS (see
    # model3_federation/adapters/registry.py) and create_system() will
    # actually try to connect before saving — this is what turns "add a
    # VMS" from a record-only placeholder into a live source. Leave both
    # unset for the old record-only behavior (unchanged).
    adapter_type: Optional[str] = None
    config: Optional[dict] = None

    _validate_ownership = field_validator("ownership")(_validate_ownership)


class VMSSystemUpdate(BaseModel):
    """All fields optional — only ones actually present in the request
    body are changed (the endpoint reads this with model_dump(exclude_unset=True),
    so sending department_id: null explicitly clears it, while omitting
    department_id entirely leaves it untouched)."""
    name: Optional[str] = None
    vendor: Optional[str] = None
    ownership: Optional[str] = None
    department_id: Optional[str] = None

    _validate_ownership = field_validator("ownership")(_validate_ownership)


# ---------------------------------------------------------------------------
# WebSocket push envelope — wraps any payload sent to /ws/federation
# ---------------------------------------------------------------------------

class WSMessage(BaseModel):
    type: str                                 # "event" | "alert" | "correlation" | "heartbeat"
    payload: dict[str, Any]

    class Config:
        json_encoders = {datetime: lambda v: v.isoformat()}
