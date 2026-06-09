"""
User models for authentication and authorization.
"""

from pydantic import BaseModel, Field, EmailStr, field_validator
from typing import Optional, Literal
from datetime import datetime, timezone
from uuid import UUID, uuid4
import re


class UserQuota(BaseModel):
    """User quota information."""
    videos_per_month: int = 100  # Default: 100 videos/month (generous for demo)
    videos_used_this_month: int = 0
    reset_date: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class UserBase(BaseModel):
    """Base user information."""
    email: EmailStr
    name: str = Field(..., min_length=1, max_length=100)


class UserCreate(UserBase):
    """User creation request."""
    password: str = Field(..., min_length=8, max_length=100)
    
    @field_validator("password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        """Validate password strength."""
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        if not re.search(r"[A-Za-z]", v):
            raise ValueError("Password must contain at least one letter")
        if not re.search(r"\d", v):
            raise ValueError("Password must contain at least one number")
        return v


class UserLogin(BaseModel):
    """User login request."""
    email: EmailStr
    password: str


class GoogleAuthRequest(BaseModel):
    """Google Sign-In request. Frontend sends the ID Token credential."""
    credential: str = Field(..., description="Google ID Token from frontend SDK")


class UserInDB(UserBase):
    """User as stored in database."""
    user_id: UUID = Field(default_factory=uuid4)
    password_hash: Optional[str] = None  # null for Google-only users
    auth_provider: Literal["local", "google", "both"] = "local"
    google_id: Optional[str] = None  # Google sub (unique ID)
    avatar_url: Optional[str] = None  # Google profile picture
    role: Literal["user", "admin"] = "user"  # NEW: Role-based access control
    tier: Literal["free", "pro", "enterprise"] = "free"
    status: Literal["pending_verification", "active", "suspended"] = "active"
    email_verified: bool = False
    verification_token: Optional[str] = None
    verification_token_expires: Optional[datetime] = None
    reset_token: Optional[str] = None
    reset_token_expires: Optional[datetime] = None
    quota: UserQuota = Field(default_factory=UserQuota)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    last_login: Optional[datetime] = None


class UserResponse(UserBase):
    """User response (public info only)."""
    user_id: UUID
    auth_provider: str = "local"
    avatar_url: Optional[str] = None
    role: str  # NEW: Include role in response
    tier: str
    status: str
    email_verified: bool
    quota: UserQuota
    created_at: datetime
    last_login: Optional[datetime] = None


class TokenResponse(BaseModel):
    """JWT token response."""
    access_token: str
    token_type: str = "bearer"
    user: UserResponse


class RegisterResponse(BaseModel):
    """Registration response message."""
    message: str
    email: str


class ResendVerificationRequest(BaseModel):
    """Request to resend verification email."""
    email: EmailStr


class ForgotPasswordRequest(BaseModel):
    """Request to initiate password reset."""
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    """Request to complete password reset."""
    token: str
    new_password: str = Field(..., min_length=8, max_length=100)
    
    @field_validator("new_password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        """Validate password strength."""
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        if not re.search(r"[A-Za-z]", v):
            raise ValueError("Password must contain at least one letter")
        if not re.search(r"\d", v):
            raise ValueError("Password must contain at least one number")
        return v


class ChangePasswordRequest(BaseModel):
    """Request to change or set password."""
    old_password: Optional[str] = None
    new_password: str = Field(..., min_length=8, max_length=100)

    @field_validator("new_password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        """Validate password strength."""
        if len(v) < 8:
            raise ValueError("Mật khẩu phải có ít nhất 8 ký tự")
        if not re.search(r"[A-Za-z]", v):
            raise ValueError("Mật khẩu phải chứa ít nhất một chữ cái")
        if not re.search(r"\d", v):
            raise ValueError("Mật khẩu phải chứa ít nhất một chữ số")
        return v


class ChangePasswordResponse(BaseModel):
    """Response message for password change."""
    message: str
    user: UserResponse


