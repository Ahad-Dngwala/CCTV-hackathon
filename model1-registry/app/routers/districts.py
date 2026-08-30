"""
District API router — read-only list endpoint.
GET /api/v1/districts
"""

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from shared.db.models import Camera as CameraModel
from shared.db.models import District as DistrictModel
from shared.db.session import get_db

from shared.schemas.district import District as DistrictSchema

router = APIRouter(prefix="/api/v1/districts", tags=["districts"])


@router.get("", response_model=list[DistrictSchema])
def list_districts(db: Session = Depends(get_db)):
    """List all 33 Gujarat districts with camera count."""
    rows = (
        db.query(
            DistrictModel,
            func.count(CameraModel.id).label("camera_count"),
        )
        .outerjoin(
            CameraModel,
            (CameraModel.district_id == DistrictModel.id)
            & (CameraModel.is_active == True),  # noqa: E712
        )
        .group_by(DistrictModel.id)
        .order_by(DistrictModel.name)
        .all()
    )
    result = []
    for dist, count in rows:
        result.append({
            "id": dist.id,
            "name": dist.name,
            "boundary": None,  # null until populated in Phase 5
            "created_at": dist.created_at,
            "camera_count": count,
        })
    return result
