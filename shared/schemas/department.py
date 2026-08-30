"""Pydantic schemas for the departments table."""

import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class DepartmentBase(BaseModel):
    name: str
    category: Optional[str] = None


class DepartmentCreate(DepartmentBase):
    pass


class Department(DepartmentBase):
    id: uuid.UUID
    created_at: datetime

    model_config = {"from_attributes": True}
