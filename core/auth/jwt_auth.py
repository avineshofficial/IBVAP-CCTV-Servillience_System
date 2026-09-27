"""
IBVAP — JWT Authentication & RBAC
====================================
JWT token management and role-based access control.
"""

import time
import hashlib
import hmac
import logging
from datetime import datetime, timedelta
from typing import Optional
from fastapi import Depends, HTTPException, status, Header
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import jwt, JWTError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from core.config import CoreConfig
from core.database import get_db

logger = logging.getLogger(__name__)

security = HTTPBearer(auto_error=False)

# Role hierarchy
ROLE_HIERARCHY = {
    "admin": 4,
    "hq_analyst": 3,
    "post_commander": 2,
    "field_officer": 1,
}

# Password hashing salt (prototype; production should use argon2/bcrypt)
_PW_SALT = b"ibvap-prototype-salt-2026"


def hash_password(password: str) -> str:
    """Hash password using HMAC-SHA256. Prototype-grade; use argon2 in production."""
    return hmac.new(_PW_SALT, password.encode("utf-8"), hashlib.sha256).hexdigest()


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return hmac.compare_digest(hash_password(plain_password), hashed_password)


def create_token(data: dict, expires_minutes: int = None) -> str:
    """Create a JWT access token."""
    to_encode = data.copy()
    expires = datetime.utcnow() + timedelta(
        minutes=expires_minutes or CoreConfig.JWT_EXPIRY_MINUTES
    )
    to_encode.update({"exp": expires})
    return jwt.encode(to_encode, CoreConfig.SECRET_KEY, algorithm=CoreConfig.JWT_ALGORITHM)


def decode_token(token: str) -> Optional[dict]:
    """Decode and validate a JWT token."""
    try:
        payload = jwt.decode(token, CoreConfig.SECRET_KEY, algorithms=[CoreConfig.JWT_ALGORITHM])
        return payload
    except JWTError:
        return None


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db),
):
    """FastAPI dependency to extract and validate the current user from JWT."""
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required — provide a Bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    payload = decode_token(credentials.credentials)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    from core.models import User
    result = await db.execute(select(User).where(User.id == int(payload.get("sub"))))
    user = result.scalar_one_or_none()

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return user


def require_role(min_role: str):
    """Dependency factory for role-based access control."""
    def role_checker(user=Depends(get_current_user)):
        # get_current_user already raises 401 if no valid token,
        # so user is always a real User object here.
        user_level = ROLE_HIERARCHY.get(user.role, 0)
        required_level = ROLE_HIERARCHY.get(min_role, 0)
        if user_level < required_level:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requires {min_role} role or higher",
            )
        return user
    return role_checker


async def require_edge_api_key(
    x_edge_api_key: Optional[str] = Header(None, alias="X-Edge-API-Key"),
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
):
    """Validate shared secret for machine-to-machine edge endpoints."""
    key = x_edge_api_key or x_api_key
    if not key or key != CoreConfig.EDGE_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing Edge API key",
            headers={"WWW-Authenticate": "ApiKey"},
        )
    return key

