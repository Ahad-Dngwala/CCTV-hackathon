"""
SQLAlchemy ORM models — mirrors shared/db/schema.sql column-for-column.

Do NOT add columns here that aren't in schema.sql.  The DB is the source
of truth; this file describes it, it doesn't extend it.
"""

import uuid
from datetime import datetime

from geoalchemy2 import Geography
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    REAL,
    String,
    Text,
    CheckConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


# ── Shared foundation ──────────────────────────────────────────


class Department(Base):
    __tablename__ = "departments"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(Text, nullable=False, unique=True)
    category = Column(Text)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default="now()")

    cameras = relationship("Camera", back_populates="department")
    users = relationship("User", back_populates="department")


class District(Base):
    __tablename__ = "districts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(Text, nullable=False, unique=True)
    boundary = Column(Geography("MULTIPOLYGON", srid=4326))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default="now()")

    cameras = relationship("Camera", back_populates="district")

    __table_args__ = (
        Index("idx_districts_boundary", "boundary", postgresql_using="gist"),
    )


class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    username = Column(Text, nullable=False, unique=True)
    email = Column(Text, unique=True)
    hashed_password = Column(Text, nullable=False)
    role = Column(
        Text,
        nullable=False,
        info={"check": "role IN ('dept_admin', 'operator', 'viewer')"},
    )
    department_id = Column(
        UUID(as_uuid=True), ForeignKey("departments.id", ondelete="SET NULL")
    )
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default="now()")

    department = relationship("Department", back_populates="users")

    __table_args__ = (
        CheckConstraint(
            "role IN ('dept_admin', 'operator', 'viewer')", name="users_role_check"
        ),
        Index("idx_users_department", "department_id"),
    )


# ── Model 1 — Registry & GIS ───────────────────────────────────


class Camera(Base):
    __tablename__ = "cameras"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(Text, nullable=False)

    # Registry / onboarding fields
    department_id = Column(
        UUID(as_uuid=True), ForeignKey("departments.id", ondelete="RESTRICT")
    )
    district_id = Column(
        UUID(as_uuid=True), ForeignKey("districts.id", ondelete="SET NULL")
    )
    location = Column(Geography("POINT", srid=4326))
    camera_type = Column(Text)
    ownership = Column(Text)
    storage_type = Column(Text)
    retention_days = Column(Integer)
    vms_url = Column(Text)
    connectivity_status = Column(
        Text, nullable=False, server_default="offline"
    )
    is_active = Column(Boolean, nullable=False, default=True)
    decommissioned_at = Column(DateTime(timezone=True))

    # Grid catalogue fields (mirrored from GET /api/ingest)
    source_grid_id = Column(Text, unique=True)
    location_label = Column(Text)
    is_live = Column(Boolean)
    codec = Column(Text)
    stream_width = Column(Integer)
    stream_height = Column(Integer)
    stream_fps = Column(REAL)
    bitrate_kbps = Column(Integer)
    rtsp_url = Column(Text)
    whep_url = Column(Text)
    hls_url = Column(Text)
    grid_synced_at = Column(DateTime(timezone=True))

    created_at = Column(DateTime(timezone=True), nullable=False, server_default="now()")
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default="now()")

    department = relationship("Department", back_populates="cameras")
    district = relationship("District", back_populates="cameras")
    status_history = relationship("StatusHistory", back_populates="camera")

    __table_args__ = (
        CheckConstraint(
            "connectivity_status IN ('online', 'offline', 'maintenance')",
            name="cameras_connectivity_status_check",
        ),
        Index("idx_cameras_location", "location", postgresql_using="gist"),
        Index("idx_cameras_department", "department_id"),
        Index("idx_cameras_district", "district_id"),
        Index("idx_cameras_status", "connectivity_status"),
        Index("idx_cameras_active", "is_active"),
    )


class StatusHistory(Base):
    __tablename__ = "status_history"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    camera_id = Column(
        UUID(as_uuid=True),
        ForeignKey("cameras.id", ondelete="RESTRICT"),
        nullable=False,
    )
    changed_field = Column(Text, nullable=False)
    old_value = Column(Text)
    new_value = Column(Text)
    changed_by = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    changed_at = Column(DateTime(timezone=True), nullable=False, server_default="now()")

    camera = relationship("Camera", back_populates="status_history")

    __table_args__ = (
        Index("idx_status_history_camera", "camera_id", text("changed_at DESC")),
    )
