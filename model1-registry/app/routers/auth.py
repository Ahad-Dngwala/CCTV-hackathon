"""
Auth API router — login and logout endpoints.
POST /api/v1/auth/login
POST /api/v1/auth/logout
"""

from typing import Optional
import uuid

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth.security import create_access_token, verify_password
from shared.db.models import User as UserModel
from shared.db.session import get_db

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str
    password: str


class UserResponse(BaseModel):
    id: uuid.UUID
    username: str
    role: str
    department_id: Optional[uuid.UUID] = None


class LoginResponse(BaseModel):
    status: str
    user: UserResponse


@router.post("/login", response_model=LoginResponse)
def login(
    credentials: LoginRequest,
    response: Response,
    db: Session = Depends(get_db),
):
    """Authenticate user with username and password, issuing an httpOnly JWT cookie."""
    user = (
        db.query(UserModel)
        .filter(UserModel.username == credentials.username)
        .first()
    )

    if not user or not user.is_active or not verify_password(credentials.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password.",
        )

    token_data = {
        "sub": str(user.id),
        "username": user.username,
        "role": user.role,
        "department_id": str(user.department_id) if user.department_id else None,
    }
    access_token = create_access_token(token_data)

    # Set httpOnly cookie
    response.set_cookie(
        key="access_token",
        value=access_token,
        httponly=True,
        samesite="lax",
        path="/",
    )

    return {
        "status": "success",
        "user": {
            "id": user.id,
            "username": user.username,
            "role": user.role,
            "department_id": user.department_id,
        },
    }


@router.post("/logout")
def logout(response: Response):
    """Log out current user by clearing the authentication cookie."""
    response.delete_cookie(key="access_token", path="/")
    return {"status": "logged_out"}
