"""
CRUD operations for users.
"""

from typing import Optional, List
from datetime import datetime, timezone, timedelta
from uuid import UUID
import secrets

from backend.database import Database
from backend.models.user import UserInDB, UserQuota


async def create_user(user_data: dict) -> dict:
    """Create a new user in MongoDB."""
    from uuid import uuid4
    
    db = Database.get_db()
    
    # Generate unique user_id
    user_data["user_id"] = str(uuid4())
    
    # Set default role if not provided
    if "role" not in user_data:
        user_data["role"] = "user"
    
    # Add timestamps
    user_data["created_at"] = datetime.now(timezone.utc)
    user_data["last_login"] = None
    
    # Initialize quota
    if "quota" not in user_data:
        user_data["quota"] = {
            "videos_per_month": 100,
            "videos_used_this_month": 0,
            "reset_date": datetime.now(timezone.utc) + timedelta(days=30)
        }
    
    # Generate verification token
    if "verification_token" not in user_data:
        user_data["verification_token"] = secrets.token_urlsafe(32)
    if "verification_token_expires" not in user_data:
        user_data["verification_token_expires"] = datetime.now(timezone.utc) + timedelta(hours=24)
    
    # Status and email_verified should be set by caller
    if "status" not in user_data:
        user_data["status"] = "pending_verification"  # Default: pending email verification
    if "email_verified" not in user_data:
        user_data["email_verified"] = False
    
    result = await db.users.insert_one(user_data)
    user_data["_id"] = result.inserted_id
    
    return user_data


async def get_user_by_email(email: str) -> Optional[dict]:
    """Get user by email."""
    db = Database.get_db()
    user = await db.users.find_one({"email": email})
    return user


async def get_user_by_google_id(google_id: str) -> Optional[dict]:
    """Get user by Google sub ID."""
    db = Database.get_db()
    user = await db.users.find_one({"google_id": google_id})
    return user


async def create_google_user(google_data: dict) -> dict:
    """
    Create a new user from Google profile.
    
    Google users are auto-verified and have no password.
    """
    from uuid import uuid4
    
    db = Database.get_db()
    
    user_data = {
        "user_id": str(uuid4()),
        "email": google_data["email"],
        "name": google_data["name"],
        "auth_provider": "google",
        "google_id": google_data["google_id"],
        "avatar_url": google_data.get("avatar_url"),
        "password_hash": None,
        "role": "user",
        "tier": "free",
        "status": "active",
        "email_verified": True,
        "verification_token": None,
        "verification_token_expires": None,
        "reset_token": None,
        "reset_token_expires": None,
        "created_at": datetime.now(timezone.utc),
        "last_login": datetime.now(timezone.utc),
        "quota": {
            "videos_per_month": 100,
            "videos_used_this_month": 0,
            "reset_date": datetime.now(timezone.utc) + timedelta(days=30),
        },
    }
    
    result = await db.users.insert_one(user_data)
    user_data["_id"] = result.inserted_id
    return user_data


async def link_google_account(
    user_id: str, google_id: str, avatar_url: Optional[str] = None
) -> bool:
    """
    Link Google account to an existing local user.
    
    Sets auth_provider to "both" and stores google_id.
    """
    db = Database.get_db()
    
    update_fields = {
        "auth_provider": "both",
        "google_id": google_id,
        "email_verified": True,
    }
    if avatar_url:
        update_fields["avatar_url"] = avatar_url
    
    result = await db.users.update_one(
        {"user_id": user_id},
        {"$set": update_fields},
    )
    return result.modified_count > 0


async def get_user_by_id(user_id: str) -> Optional[dict]:
    """Get user by user_id."""
    db = Database.get_db()
    user = await db.users.find_one({"user_id": user_id})
    return user


async def update_last_login(user_id: str) -> None:
    """Update user's last login timestamp."""
    db = Database.get_db()
    await db.users.update_one(
        {"user_id": user_id},
        {"$set": {"last_login": datetime.now(timezone.utc)}}
    )


async def verify_email(verification_token: str) -> bool:
    """Verify user email with token."""
    db = Database.get_db()
    result = await db.users.update_one(
        {"verification_token": verification_token},
        {"$set": {"email_verified": True, "verification_token": None, "verification_token_expires": None}}
    )
    return result.modified_count > 0


async def verify_email_token(token: str) -> bool:
    """Verify email token, checking expiration, and activating the user."""
    db = Database.get_db()
    user = await db.users.find_one({"verification_token": token})
    if not user:
        return False
    
    expires = user.get("verification_token_expires")
    if expires:
        # Ensure it is timezone-aware
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) > expires:
            return False
            
    result = await db.users.update_one(
        {"user_id": user["user_id"]},
        {
            "$set": {
                "email_verified": True,
                "status": "active",
                "verification_token": None,
                "verification_token_expires": None
            }
        }
    )
    return result.modified_count > 0


async def generate_new_verification_token(email: str) -> Optional[str]:
    """Generate a new verification token and expiration for the given email."""
    db = Database.get_db()
    user = await db.users.find_one({"email": email})
    if not user:
        return None
        
    new_token = secrets.token_urlsafe(32)
    expires = datetime.now(timezone.utc) + timedelta(hours=24)
    
    await db.users.update_one(
        {"user_id": user["user_id"]},
        {
            "$set": {
                "verification_token": new_token,
                "verification_token_expires": expires,
                "status": "pending_verification",
                "email_verified": False
            }
        }
    )
    return new_token


async def check_quota(user_id: str) -> bool:
    """Check if user has remaining quota."""
    user = await get_user_by_id(user_id)
    if not user:
        return False
    
    quota = user.get("quota", {})
    
    # Reset quota if past reset date
    reset_date = quota.get("reset_date")
    if reset_date:
        # Ensure reset_date is timezone-aware
        if reset_date.tzinfo is None:
            reset_date = reset_date.replace(tzinfo=timezone.utc)
        
        if datetime.now(timezone.utc) > reset_date:
            await reset_monthly_quota(user_id)
            return True
    
    # Check quota
    videos_used = quota.get("videos_used_this_month", 0)
    videos_limit = quota.get("videos_per_month", 100)
    
    return videos_used < videos_limit


async def increment_quota_usage(user_id: str) -> None:
    """Increment user's quota usage."""
    db = Database.get_db()
    await db.users.update_one(
        {"user_id": user_id},
        {"$inc": {"quota.videos_used_this_month": 1}}
    )


async def reset_monthly_quota(user_id: str) -> None:
    """Reset user's monthly quota."""
    db = Database.get_db()
    next_reset = datetime.now(timezone.utc) + timedelta(days=30)
    
    await db.users.update_one(
        {"user_id": user_id},
        {
            "$set": {
                "quota.videos_used_this_month": 0,
                "quota.reset_date": next_reset
            }
        }
    )


async def list_users(
    status: Optional[str] = None,
    tier: Optional[str] = None,
    skip: int = 0,
    limit: int = 50
) -> List[dict]:
    """List users with optional filters."""
    db = Database.get_db()
    
    query = {}
    if status:
        query["status"] = status
    if tier:
        query["tier"] = tier
    
    cursor = db.users.find(query).sort("created_at", -1).skip(skip).limit(limit)
    users = await cursor.to_list(length=limit)
    
    return users


async def update_user_tier(user_id: str, tier: str, quota: Optional[dict] = None) -> bool:
    """Update user tier and quota (for admin)."""
    db = Database.get_db()
    
    update_data = {"tier": tier}
    if quota:
        update_data["quota"] = quota
    
    result = await db.users.update_one(
        {"user_id": user_id},
        {"$set": update_data}
    )
    
    return result.modified_count > 0


async def suspend_user(user_id: str, reason: str) -> bool:
    """Suspend user account."""
    db = Database.get_db()
    
    result = await db.users.update_one(
        {"user_id": user_id},
        {"$set": {"status": "suspended", "suspension_reason": reason}}
    )
    
    return result.modified_count > 0


async def activate_user(user_id: str) -> bool:
    """Activate suspended user account."""
    db = Database.get_db()
    
    result = await db.users.update_one(
        {"user_id": user_id},
        {"$set": {"status": "active", "suspension_reason": None}}
    )
    
    return result.modified_count > 0


async def save_password_reset_token(email: str, token: str, expires: datetime) -> bool:
    """Save password reset token and expiration for a user."""
    db = Database.get_db()
    result = await db.users.update_one(
        {"email": email},
        {"$set": {"reset_token": token, "reset_token_expires": expires}}
    )
    return result.modified_count > 0


async def get_user_by_reset_token(token: str) -> Optional[dict]:
    """Get user by reset token."""
    db = Database.get_db()
    user = await db.users.find_one({"reset_token": token})
    return user


async def reset_password_with_token(user_id: str, new_password_hash: str) -> bool:
    """Reset user password and clear reset token fields."""
    db = Database.get_db()
    result = await db.users.update_one(
        {"user_id": user_id},
        {
            "$set": {
                "password_hash": new_password_hash,
                "reset_token": None,
                "reset_token_expires": None
            }
        }
    )
    return result.modified_count > 0


async def change_user_password(
    user_id: str, new_password_hash: str, set_both_provider: bool = False
) -> bool:
    """Change or set user password, optionally updating auth_provider to 'both'."""
    db = Database.get_db()
    update_data = {
        "password_hash": new_password_hash,
    }
    if set_both_provider:
        update_data["auth_provider"] = "both"
        
    result = await db.users.update_one(
        {"user_id": user_id},
        {"$set": update_data}
    )
    return result.modified_count > 0


