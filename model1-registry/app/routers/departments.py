"""
Department API router — read-only list endpoint.
GET /api/v1/departments
"""

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from shared.db.models import Camera as CameraModel
from shared.db.models import Department as DepartmentModel
from shared.db.session import get_db
from shared.schemas.department import Department as DepartmentSchema

router = APIRouter(prefix="/api/v1/departments", tags=["departments"])


@router.get("", response_model=list[dict])
def list_departments(db: Session = Depends(get_db)):
    """List all departments with a camera count per department."""
    rows = (
        db.query(
            DepartmentModel,
            func.count(CameraModel.id).label("camera_count"),
        )
        .outerjoin(
            CameraModel,
            (CameraModel.department_id == DepartmentModel.id)
            & (CameraModel.is_active == True),  # noqa: E712
        )
        .group_by(DepartmentModel.id)
        .order_by(DepartmentModel.name)
        .all()
    )
    return [
        {
            "id": str(dept.id),
            "name": dept.name,
            "category": dept.category,
            "created_at": dept.created_at.isoformat(),
            "camera_count": count,
        }
        for dept, count in rows
    ]
