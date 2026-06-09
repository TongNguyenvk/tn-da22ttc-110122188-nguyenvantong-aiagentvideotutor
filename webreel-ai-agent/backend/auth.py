"""
Authentication utilities: JWT, password hashing, token validation.
"""

from datetime import datetime, timedelta, timezone
from typing import Optional
from jose import JWTError, jwt
from passlib.context import CryptContext
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import os

from backend.crud.users import get_user_by_id

# JWT Configuration
SECRET_KEY = os.getenv("JWT_SECRET_KEY", "your-secret-key-change-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7  # 7 days

# Password hashing with bcrypt
# Note: Using bcrypt 4.2.0 for compatibility with passlib
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# HTTP Bearer token scheme
security = HTTPBearer()


def hash_password(password: str) -> str:
    """Hash a password using bcrypt via passlib."""
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against its hash."""
    return pwd_context.verify(plain_password, hashed_password)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Create a JWT access token."""
    to_encode = data.copy()
    
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    
    return encoded_jwt


def decode_access_token(token: str) -> Optional[dict]:
    """Decode and validate a JWT token."""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except JWTError:
        return None


async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)) -> dict:
    """
    Dependency to get current authenticated user from JWT token.
    
    Usage:
        @app.get("/api/protected")
        async def protected_route(user: dict = Depends(get_current_user)):
            return {"user_id": user["user_id"]}
    """
    token = credentials.credentials
    
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    payload = decode_access_token(token)
    if payload is None:
        raise credentials_exception
    
    user_id: str = payload.get("sub")
    if user_id is None:
        raise credentials_exception
    
    user = await get_user_by_id(user_id)
    if user is None:
        raise credentials_exception
    
    # Check if user status is active
    if user.get("status") != "active":
        detail_msg = "Account suspended"
        if user.get("status") == "pending_verification":
            detail_msg = "Email verification pending"
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=detail_msg
        )
    
    return user


async def get_current_active_user(user: dict = Depends(get_current_user)) -> dict:
    """
    Dependency to get current active user (not suspended).
    """
    if user.get("status") != "active":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account not active"
        )
    return user


async def get_current_admin(user: dict = Depends(get_current_user)) -> dict:
    """
    Dependency to require admin role.
    
    Usage:
        @app.get("/api/admin/users")
        async def list_users(admin: dict = Depends(get_current_admin)):
            # Only admins can access this
            return {"users": [...]}
    """
    if user.get("role") != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required"
        )
    return user


# TODO: Payment integration (Phase 2)
# When implementing Stripe:
# 1. Add webhook endpoint: POST /api/webhooks/stripe
# 2. Verify webhook signature
# 3. On payment success: update_user_tier(user_id, "pro")
# 4. On subscription cancel: downgrade to "free"
