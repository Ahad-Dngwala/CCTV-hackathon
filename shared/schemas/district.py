"""Pydantic schemas for the districts table."""

import uuid
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel


class DistrictBase(BaseModel):
    name: str


class DistrictCreate(DistrictBase):
    pass


class District(DistrictBase):
    id: uuid.UUID
    boundary: Optional[Any] = None  # GeoJSON or null
    created_at: datetime
    camera_count: int = 0

    model_config = {"from_attributes": True}
