import uuid
import logging
import json
from typing import Optional, Any
from sqlalchemy.orm import Session
from sqlalchemy import text
from shared.db.models import User as UserModel

logger = logging.getLogger(__name__)

def log_audit_event(
    db: Session,
    action: str,
    resource_type: str,
    resource_id: Optional[str] = None,
    details: Optional[dict[str, Any]] = None,
    user: Optional[UserModel] = None,
):
    """
    Persists a security-sensitive action into the audit_logs table.
    """
    try:
        user_id = user.id if user else None
        department_id = user.department_id if user else None
        
        db.execute(text(
            """
            INSERT INTO audit_logs (id, action, resource_type, resource_id, details, user_id, department_id)
            VALUES (:id, :action, :resource_type, :resource_id, :details, :user_id, :department_id)
            """
        ), {
            "id": str(uuid.uuid4()),
            "action": action,
            "resource_type": resource_type,
            "resource_id": resource_id,
            "details": json.dumps(details) if details else None,
            "user_id": user_id,
            "department_id": department_id
        })
        db.commit()
    except Exception as e:
        # Don't crash the main transaction if audit logging fails
        logger.error(f"Failed to write audit log: {e}")
        db.rollback()
