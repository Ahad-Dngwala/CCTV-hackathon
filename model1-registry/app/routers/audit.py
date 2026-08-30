"""
Audit Log API router — global audit trail view.
GET /api/v1/audit
"""

from typing import Optional
import uuid

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session, joinedload

from app.auth.dependencies import get_current_user
from shared.db.models import Camera as CameraModel
from shared.db.models import StatusHistory as StatusHistoryModel
from shared.db.models import User as UserModel
from shared.db.session import get_db

router = APIRouter(prefix="/api/v1/audit", tags=["audit"])


class AuditItemResponse(BaseModel):
    id: uuid.UUID
    camera_id: uuid.UUID
    camera_name: str
    changed_field: str
    old_value: Optional[str] = None
    new_value: Optional[str] = None
    changed_by_user: Optional[str] = None
    changed_at: str


@router.get("", response_model=list[AuditItemResponse])
def get_global_audit_log(
    limit: int = Query(200, ge=1, le=1000),
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
):
    """Retrieve global system audit trail, ordered by changed_at DESC."""
    rows = (
        db.query(StatusHistoryModel)
        .options(
            joinedload(StatusHistoryModel.camera),
        )
        .order_by(StatusHistoryModel.changed_at.desc())
        .limit(limit)
        .all()
    )

    # Gather unique changed_by user IDs for efficient lookup
    user_ids = {r.changed_by for r in rows if r.changed_by is not None}
    users_by_id = {}
    if user_ids:
        users = db.query(UserModel).filter(UserModel.id.in_(user_ids)).all()
        users_by_id = {u.id: u.username for u in users}

    result = []
    for r in rows:
        camera_name = r.camera.name if r.camera else "Unknown Camera"
        changed_by_username = users_by_id.get(r.changed_by, "System / Direct DB") if r.changed_by else "System / Direct DB"

        result.append(
            AuditItemResponse(
                id=r.id,
                camera_id=r.camera_id,
                camera_name=camera_name,
                changed_field=r.changed_field,
                old_value=r.old_value,
                new_value=r.new_value,
                changed_by_user=changed_by_username,
                changed_at=r.changed_at.isoformat(),
            )
        )

    return result
