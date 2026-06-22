"""
Admin routes with role-based access control.

All endpoints require admin role.
"""

from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Request
from pydantic import BaseModel, EmailStr, Field
from typing import Literal, Optional
from datetime import datetime, timedelta, timezone
import logging

from backend.auth import get_current_admin, get_current_user
from backend.auth import hash_password
from backend.crud.users import (
    list_users,
    create_user,
    get_user_by_email,
    get_user_by_id,
    update_user_tier,
    suspend_user,
    activate_user
)
from backend.crud.jobs import (
    list_jobs,
    get_job_stats,
    get_user_job_stats,
    get_job_by_id,
    cancel_job
)
from backend.queue import JobQueue
from backend.crud.agent_config import get_agent_config, update_agent_config, DEFAULT_GEMINI_MODEL

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/admin", tags=["Admin"])


ADMIN_CANCEL_REASONS = {
    "policy_violation": "Nội dung vi phạm",
    "misuse": "Dùng sai mục đích",
    "invalid_material": "Tài liệu không hợp lệ",
    "other": "Khác",
}


class AdminCreateUserRequest(BaseModel):
    email: EmailStr
    name: str = Field(..., min_length=1, max_length=100)
    password: str = Field(..., min_length=8, max_length=100)
    role: Literal["user", "admin"] = "user"
    tier: Literal["free", "pro", "enterprise"] = "free"
    videos_per_month: int = Field(default=100, ge=0, le=100000)


class AdminCancelJobRequest(BaseModel):
    reason_code: Literal["policy_violation", "misuse", "invalid_material", "other"]


def _scrub_admin_created_user(user: dict) -> dict:
    """Return a user document without sensitive auth fields."""
    safe_user = dict(user)
    if "_id" in safe_user:
        safe_user["_id"] = str(safe_user["_id"])
    for key in (
        "password_hash",
        "verification_token",
        "verification_token_expires",
        "reset_token",
        "reset_token_expires",
        "google_id",
    ):
        safe_user.pop(key, None)
    return safe_user


async def _attach_job_owner_fields(
    job: dict,
    user_cache: Optional[dict[str, Optional[dict]]] = None
) -> dict:
    """Attach minimal owner context for admin job review."""
    user_id = job.get("user_id")
    if not user_id:
        return job

    cache = user_cache if user_cache is not None else {}
    if user_id not in cache:
        cache[user_id] = await get_user_by_id(user_id)

    user = cache.get(user_id)
    if not user:
        job["user_name"] = None
        job["user_status"] = None
        job["user_tier"] = None
        return job

    job["user_name"] = user.get("name")
    job["user_status"] = user.get("status")
    job["user_tier"] = user.get("tier")
    return job


@router.get("/users")
async def admin_list_users(
    status: Optional[str] = None,
    tier: Optional[str] = None,
    role: Optional[str] = None,
    skip: int = 0,
    limit: int = 50,
    admin: dict = Depends(get_current_admin)
):
    """
    List all users (admin only).
    
    Query params:
    - status: Filter by status (active, suspended, pending_verification)
    - tier: Filter by tier (free, pro, enterprise)
    - role: Filter by role (user, admin)
    - skip: Pagination offset
    - limit: Max results (default 50)
    """
    users = await list_users(
        status=status,
        tier=tier,
        skip=skip,
        limit=limit
    )
    
    # Filter by role if specified (MongoDB doesn't support this in list_users yet)
    if role:
        users = [u for u in users if u.get("role") == role]
    
    # Convert ObjectId to string for JSON serialization
    for user in users:
        if "_id" in user:
            user["_id"] = str(user["_id"])
    
    logger.info(f"Admin {admin['email']} listed {len(users)} users")
    
    return {
        "users": users,
        "total": len(users),
        "skip": skip,
        "limit": limit
    }


@router.post("/users", status_code=status.HTTP_201_CREATED)
async def admin_create_user(
    payload: AdminCreateUserRequest,
    admin: dict = Depends(get_current_admin)
):
    """
    Create an active, email-verified user from the admin UI.
    """
    email = payload.email.lower().strip()
    name = payload.name.strip()
    password = payload.password

    if not name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Tên là bắt buộc"
        )
    if not any(ch.isalpha() for ch in password) or not any(ch.isdigit() for ch in password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Mật khẩu phải có ít nhất một chữ cái và một chữ số"
        )

    existing_user = await get_user_by_email(email)
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email đã được đăng ký"
        )

    user = await create_user({
        "email": email,
        "name": name,
        "password_hash": hash_password(password),
        "auth_provider": "local",
        "role": payload.role,
        "tier": payload.tier,
        "status": "active",
        "email_verified": True,
        "verification_token": None,
        "verification_token_expires": None,
        "reset_token": None,
        "reset_token_expires": None,
        "quota": {
            "videos_per_month": payload.videos_per_month,
            "videos_used_this_month": 0,
            "reset_date": datetime.now(timezone.utc) + timedelta(days=30),
        },
    })

    logger.warning(
        f"Admin {admin['email']} created {payload.role} user {email} "
        f"(tier={payload.tier}, quota={payload.videos_per_month})"
    )

    return {
        "message": "Đã tạo người dùng",
        "user": _scrub_admin_created_user(user),
    }


@router.get("/users/{user_id}")
async def admin_get_user(
    user_id: str,
    admin: dict = Depends(get_current_admin)
):
    """
    Get user details (admin only).
    
    Returns full user information including password_hash (for debugging).
    """
    user = await get_user_by_id(user_id)
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    # Get user's job stats
    job_stats = await get_user_job_stats(user_id)
    
    logger.info(f"Admin {admin['email']} viewed user {user_id}")
    
    return {
        "user": user,
        "job_stats": job_stats
    }


@router.put("/users/{user_id}/tier")
async def admin_update_tier(
    user_id: str,
    tier: str,
    videos_per_month: Optional[int] = None,
    admin: dict = Depends(get_current_admin)
):
    """
    Update user tier (admin only).
    
    Body:
    - tier: "free" | "pro" | "enterprise"
    - videos_per_month: Optional custom quota
    """
    # Validate tier
    if tier not in ["free", "pro", "enterprise"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid tier. Must be: free, pro, or enterprise"
        )
    
    # Build quota update
    quota = None
    if videos_per_month is not None:
        quota = {
            "videos_per_month": videos_per_month,
            "videos_used_this_month": 0  # Reset usage
        }
    
    success = await update_user_tier(user_id, tier, quota)
    
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    logger.info(f"Admin {admin['email']} updated user {user_id} tier to {tier}")
    
    return {
        "message": "Tier updated successfully",
        "user_id": user_id,
        "tier": tier,
        "quota": quota
    }


@router.put("/users/{user_id}/suspend")
async def admin_suspend_user(
    user_id: str,
    reason: str,
    admin: dict = Depends(get_current_admin)
):
    """
    Suspend user account (admin only).
    
    Body:
    - reason: Reason for suspension
    """
    if not reason or len(reason.strip()) == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Suspension reason is required"
        )
    
    success = await suspend_user(user_id, reason)
    
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    logger.warning(f"Admin {admin['email']} suspended user {user_id}: {reason}")
    
    return {
        "message": "User suspended successfully",
        "user_id": user_id,
        "reason": reason
    }


@router.put("/users/{user_id}/activate")
async def admin_activate_user(
    user_id: str,
    admin: dict = Depends(get_current_admin)
):
    """
    Activate suspended user account (admin only).
    """
    success = await activate_user(user_id)
    
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    logger.info(f"Admin {admin['email']} activated user {user_id}")
    
    return {
        "message": "User activated successfully",
        "user_id": user_id
    }


@router.get("/jobs")
async def admin_list_all_jobs(
    user_id: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 100,
    skip: int = 0,
    admin: dict = Depends(get_current_admin)
):
    """
    List all jobs across all users (admin only).
    
    Query params:
    - user_id: Filter by specific user
    - status: Filter by job status
    - limit: Max results (default 100)
    - skip: Pagination offset
    """
    jobs = await list_jobs(
        user_id=user_id,
        status=status,
        limit=limit,
        skip=skip
    )
    
    # Convert ObjectId to string
    user_cache: dict[str, Optional[dict]] = {}
    for job in jobs:
        if "_id" in job:
            job["_id"] = str(job["_id"])
        await _attach_job_owner_fields(job, user_cache)
    
    logger.info(f"Admin {admin['email']} listed {len(jobs)} jobs")
    
    return {
        "jobs": jobs,
        "total": len(jobs),
        "skip": skip,
        "limit": limit
    }


@router.get("/jobs/{job_id}")
async def admin_get_job(
    job_id: str,
    admin: dict = Depends(get_current_admin)
):
    """
    Get job details (admin only).
    
    Admins can view any job regardless of owner.
    """
    job = await get_job_by_id(job_id)
    
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Job not found"
        )
    
    # Convert ObjectId to string
    if "_id" in job:
        job["_id"] = str(job["_id"])
    await _attach_job_owner_fields(job)
    
    logger.info(f"Admin {admin['email']} viewed job {job_id}")
    
    return job


@router.post("/jobs/{job_id}/cancel")
async def admin_cancel_running_job(
    job_id: str,
    payload: AdminCancelJobRequest,
    admin: dict = Depends(get_current_admin)
):
    """Cancel a running job and ask the autoscaler to stop its worker."""
    job = await get_job_by_id(job_id)

    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Không tìm thấy job"
        )

    if job.get("status") != "running":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Chỉ có thể dừng job đang chạy"
        )

    reason_label = ADMIN_CANCEL_REASONS[payload.reason_code]
    cancel_message = f"Job đã bị dừng bởi quản trị viên: {reason_label}"
    success = await cancel_job(
        job_id,
        cancelled_by_role="admin",
        cancelled_by_user_id=admin.get("user_id"),
        reason_code=payload.reason_code,
        reason_label=reason_label,
        message=cancel_message,
    )

    if not success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Không thể dừng job ở trạng thái hiện tại"
        )

    queue = JobQueue()
    removed_count = queue.remove_job_from_queues(job_id)
    kill_published = queue.publish_job_kill(job_id)

    logger.warning(
        f"Admin {admin['email']} cancelled job {job_id}: {reason_label} "
        f"(removed_queue_items={removed_count}, kill_published={kill_published})"
    )

    return {
        "message": "Đã dừng job",
        "job_id": job_id,
        "status": "cancelled",
        "reason_code": payload.reason_code,
        "reason_label": reason_label,
        "removed_queue_items": removed_count,
        "kill_published": kill_published,
    }


@router.get("/stats")
async def admin_get_stats(
    admin: dict = Depends(get_current_admin)
):
    """
    Get system statistics (admin only).
    
    Returns:
    - Job stats (total, by status)
    - User stats (total, by tier, by status)
    """
    from backend.database import Database
    
    db = Database.get_db()
    if db is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database not available"
        )
    
    # Job stats
    job_stats_by_status = await get_job_stats()
    total_jobs = sum(job_stats_by_status.values()) if job_stats_by_status else 0
    
    # User stats
    total_users = await db.users.count_documents({})
    active_users = await db.users.count_documents({"status": "active"})
    suspended_users = await db.users.count_documents({"status": "suspended"})
    
    free_users = await db.users.count_documents({"tier": "free"})
    pro_users = await db.users.count_documents({"tier": "pro"})
    enterprise_users = await db.users.count_documents({"tier": "enterprise"})
    
    admin_users = await db.users.count_documents({"role": "admin"})
    regular_users = await db.users.count_documents({"role": "user"})
    
    logger.info(f"Admin {admin['email']} viewed system stats")
    
    return {
        "jobs": {
            "total": total_jobs,
            "by_status": job_stats_by_status
        },
        "users": {
            "total": total_users,
            "active": active_users,
            "suspended": suspended_users,
            "by_tier": {
                "free": free_users,
                "pro": pro_users,
                "enterprise": enterprise_users
            },
            "by_role": {
                "admin": admin_users,
                "user": regular_users
            }
        }
    }


@router.get("/queues/status")
async def get_queue_status(
    admin: dict = Depends(get_current_admin)
):
    """Get queue pause status for all queues (Circuit Breaker status)."""
    from backend.queue import JobQueue

    queue = JobQueue()
    queues = ["web-queue", "presentation-queue", "presentation-gg-queue", "office-queue"]

    status = {}
    for q_name in queues:
        is_paused = queue.is_queue_paused(q_name)
        pause_info = queue.get_queue_pause_info(q_name) if is_paused else None
        status[q_name] = {
            "paused": is_paused,
            "pause_info": pause_info,
        }

    logger.info(f"Admin {admin['email']} checked queue status")

    return {
        "queues": status
    }


@router.post("/queues/{queue_name}/resume")
async def resume_queue(
    queue_name: str,
    admin: dict = Depends(get_current_admin)
):
    """Resume a paused queue (after session re-login)."""
    from backend.queue import JobQueue

    queue = JobQueue()

    if not queue.is_queue_paused(queue_name):
        return {"message": f"Queue {queue_name} is not paused"}

    queue.resume_queue(queue_name)
    logger.warning(f"Admin {admin['email']} resumed queue {queue_name}")

    return {
        "message": f"Queue {queue_name} resumed successfully",
        "queue": queue_name
    }


# -----------------------------------------------------------------
# Agent runtime config (API keys + model name + TTS)
# -----------------------------------------------------------------
#
# Backed by the `agent_configs` MongoDB collection (singleton row).
# The autoscaler reads this on every job launch and injects the values
# as `-e KEY=VAL` env overrides on `docker compose run`, so changes take
# effect on the NEXT job without rebuilding/restarting any worker image.

# Whitelist of models surfaced in the admin UI. Gemini families only —
# add new IDs here as Google ships them.
SUPPORTED_GEMINI_MODELS = [
    "gemini-3.1-flash-lite",
    "gemini-3.1-flash",
    "gemini-2.5-flash",
    "gemini-2.5-pro",
    "gemini-2.0-flash",
    "gemini-2.0-flash-lite",
    "gemini-1.5-flash",
    "gemini-1.5-pro",
]

# TTS providers — `id` matches the `engine` arg in audio_injector.generate_tts_segments
# and is the value workers receive in `config.tts_engine`. `requires_key` tells the
# admin UI whether to gate enabling this provider on having an API key saved.
SUPPORTED_TTS_PROVIDERS = [
    {
        "id": "edge",
        "name": "Edge TTS (Microsoft)",
        "requires_key": False,
        "voices": [
            {"id": "vi-VN-HoaiMyNeural", "label": "Hoài My (Nữ - Miền Nam)"},
            {"id": "vi-VN-NamMinhNeural", "label": "Nam Minh (Nam - Miền Nam)"},
        ],
    },
    {
        "id": "fpt",
        "name": "FPT.AI",
        "requires_key": True,
        "voices": [
            {"id": "banmai", "label": "Ban Mai (Nữ - Miền Bắc)"},
            {"id": "leminh", "label": "Lê Minh (Nam - Miền Bắc)"},
            {"id": "myan", "label": "Mỹ An (Nữ - Miền Trung)"},
            {"id": "lannhi", "label": "Lan Nhi (Nữ - Miền Nam)"},
            {"id": "linhsan", "label": "Linh San (Nữ - Miền Nam)"},
        ],
    },
]


def _mask_secret(value: Optional[str]) -> str:
    """Show only the last 4 chars of an API key (or empty string)."""
    if not value:
        return ""
    if len(value) <= 4:
        return "*" * len(value)
    return "*" * (len(value) - 4) + value[-4:]


class AgentConfigUpdate(BaseModel):
    gemini_api_key: Optional[str] = None
    gemini_model: Optional[str] = None
    fpt_api_key: Optional[str] = None
    tts_default_provider: Optional[str] = None
    tts_default_voice: Optional[str] = None
    tts_enabled_providers: Optional[list[str]] = None


@router.get("/agent-config")
async def admin_get_agent_config(
    reveal: bool = False,
    admin: dict = Depends(get_current_admin),
):
    """Return the current agent runtime config.

    By default keys are masked. Pass `?reveal=true` to get the raw values
    (useful for one-off copy-paste; the frontend should request reveal on
    explicit user action, not by default).
    """
    cfg = await get_agent_config()

    return {
        "gemini_api_key": cfg.get("gemini_api_key", "") if reveal else _mask_secret(cfg.get("gemini_api_key")),
        "gemini_model": cfg.get("gemini_model") or "",
        "fpt_api_key": cfg.get("fpt_api_key", "") if reveal else _mask_secret(cfg.get("fpt_api_key")),
        "tts_default_provider": cfg.get("tts_default_provider") or "edge",
        "tts_default_voice": cfg.get("tts_default_voice") or "",
        "tts_enabled_providers": cfg.get("tts_enabled_providers") or ["edge"],
        "updated_at": cfg.get("updated_at"),
        "updated_by": cfg.get("updated_by"),
        "supported_models": SUPPORTED_GEMINI_MODELS,
        "supported_tts_providers": SUPPORTED_TTS_PROVIDERS,
        "is_revealed": reveal,
    }


# Public endpoint — what the user-facing Create form needs to render the
# TTS picker. Authenticated (so we don't leak choices to anon scrapers)
# but available to any logged-in user, not just admins. Returns ONLY the
# enabled providers + default voice; no secrets.
@router.get("/agent-config/public/tts")
async def public_tts_options(user: dict = Depends(get_current_user)):
    cfg = await get_agent_config()
    enabled_ids = set(cfg.get("tts_enabled_providers") or ["edge"])

    enabled_providers = [
        {"id": p["id"], "name": p["name"], "voices": p["voices"]}
        for p in SUPPORTED_TTS_PROVIDERS
        if p["id"] in enabled_ids
    ]

    default_provider = cfg.get("tts_default_provider") or "edge"
    if default_provider not in enabled_ids:
        # Defensive: admin disabled the default — fall back to edge.
        default_provider = "edge"

    return {
        "providers": enabled_providers,
        "default_provider": default_provider,
        "default_voice": cfg.get("tts_default_voice") or "",
    }


@router.put("/agent-config")
async def admin_update_agent_config(
    payload: AgentConfigUpdate,
    admin: dict = Depends(get_current_admin),
):
    """Update agent runtime config. Only changed fields need to be sent."""
    updates: dict = {}

    # Empty string means "don't change" — to clear a value, the UI should
    # not allow it; treating "" as "keep existing" prevents accidental wipe
    # when a mask-only response is round-tripped back to the server.
    if payload.gemini_api_key is not None and payload.gemini_api_key.strip() != "":
        updates["gemini_api_key"] = payload.gemini_api_key.strip()
    if payload.fpt_api_key is not None and payload.fpt_api_key.strip() != "":
        updates["fpt_api_key"] = payload.fpt_api_key.strip()
    if payload.gemini_model is not None and payload.gemini_model.strip() != "":
        model = payload.gemini_model.strip()
        if model not in SUPPORTED_GEMINI_MODELS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unsupported model: {model}. Allowed: {SUPPORTED_GEMINI_MODELS}",
            )
        updates["gemini_model"] = model

    # ---- TTS provider settings ----
    valid_provider_ids = {p["id"] for p in SUPPORTED_TTS_PROVIDERS}

    if payload.tts_default_provider is not None and payload.tts_default_provider.strip() != "":
        prov = payload.tts_default_provider.strip()
        if prov not in valid_provider_ids:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unknown TTS provider: {prov}",
            )
        updates["tts_default_provider"] = prov

    if payload.tts_default_voice is not None:
        updates["tts_default_voice"] = payload.tts_default_voice.strip()

    if payload.tts_enabled_providers is not None:
        enabled = [p.strip() for p in payload.tts_enabled_providers if p.strip()]
        unknown = [p for p in enabled if p not in valid_provider_ids]
        if unknown:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unknown TTS provider(s): {unknown}",
            )
        # Edge must always remain available — it requires no key, so
        # losing it would leave free-tier users without any working TTS.
        if "edge" not in enabled:
            enabled.append("edge")
        updates["tts_enabled_providers"] = enabled

    if not updates:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No fields to update",
        )

    new_cfg = await update_agent_config(updates, updated_by=admin.get("email"))
    logger.warning(
        f"Admin {admin.get('email')} updated agent config: "
        f"fields={list(updates.keys())} model={new_cfg.get('gemini_model')} "
        f"tts={new_cfg.get('tts_default_provider')}"
    )

    return {
        "message": "Agent config updated successfully",
        "gemini_api_key": _mask_secret(new_cfg.get("gemini_api_key")),
        "gemini_model": new_cfg.get("gemini_model"),
        "fpt_api_key": _mask_secret(new_cfg.get("fpt_api_key")),
        "tts_default_provider": new_cfg.get("tts_default_provider"),
        "tts_default_voice": new_cfg.get("tts_default_voice"),
        "tts_enabled_providers": new_cfg.get("tts_enabled_providers"),
        "updated_at": new_cfg.get("updated_at"),
        "updated_by": new_cfg.get("updated_by"),
        "note": "Changes apply to new jobs only — running workers keep their original env.",
    }


# -----------------------------------------------------------------
# Connectivity tests — verify keys / providers without submitting a job
# -----------------------------------------------------------------
#
# These hit the upstream service with a tiny request and report
# {ok, latency_ms, detail}. Used by the admin "Test" buttons so a wrong
# API key fails on save, not on the next job.

class GeminiTestPayload(BaseModel):
    api_key: Optional[str] = None  # if blank, use saved value
    model: Optional[str] = None    # if blank, use saved value


class TTSTestPayload(BaseModel):
    provider: str                  # "edge" | "fpt"
    voice: Optional[str] = None    # provider-specific id
    api_key: Optional[str] = None  # only required by paid providers (FPT)
    text: Optional[str] = None     # default "Xin chào WebReel"


@router.post("/agent-config/gemini/test")
async def admin_test_gemini(
    payload: GeminiTestPayload,
    admin: dict = Depends(get_current_admin),
):
    """Verify a Gemini API key + model by issuing a 1-token completion.

    If `api_key`/`model` are omitted, the saved values are used. The key
    sent in the body is NEVER persisted — that's still a PUT to /agent-config.
    """
    import time as _time

    cfg = await get_agent_config()
    api_key = (payload.api_key or "").strip() or cfg.get("gemini_api_key", "")
    model = (payload.model or "").strip() or cfg.get("gemini_model") or DEFAULT_GEMINI_MODEL

    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No API key provided and none saved",
        )

    try:
        from google import genai
    except ImportError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"google-genai not installed: {e}",
        ) from e

    started = _time.time()
    try:
        client = genai.Client(api_key=api_key)
        resp = client.models.generate_content(model=model, contents="ping")
        # `text` raises if no candidates; truthiness check keeps the test
        # tolerant of empty completions on weird models.
        _ = getattr(resp, "text", "") or ""
    except Exception as e:
        latency_ms = int((_time.time() - started) * 1000)
        logger.warning(f"Gemini test failed for {admin.get('email')}: {e}")
        # Don't 500 — return ok=false so the UI can show the actual error
        # without React Query treating it like a network failure.
        return {"ok": False, "latency_ms": latency_ms, "model": model, "detail": str(e)}

    latency_ms = int((_time.time() - started) * 1000)
    logger.info(
        f"Gemini test ok by {admin.get('email')}: model={model}, latency={latency_ms}ms"
    )
    return {"ok": True, "latency_ms": latency_ms, "model": model, "detail": "OK"}


# Default test sentence — short enough to keep TTS billing/quota negligible
# (~25 chars), Vietnamese so the voice's prosody actually shows.
_TTS_TEST_TEXT = "Xin chào, đây là bản kiểm tra giọng đọc WebReel."


@router.post("/agent-config/tts/test")
async def admin_test_tts(
    payload: TTSTestPayload,
    admin: dict = Depends(get_current_admin),
):
    """Sinh 1 file mp3 ngắn để verify provider + voice + key.

    Trả `{ok, latency_ms, duration_ms, audio_base64, detail}`. File mp3
    được encode base64 và trả về client để admin nghe trực tiếp; backend
    không lưu lại trên disk.
    """
    import base64
    import tempfile
    import time as _time
    from pathlib import Path as _Path

    valid_ids = {p["id"] for p in SUPPORTED_TTS_PROVIDERS}
    if payload.provider not in valid_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown TTS provider: {payload.provider}",
        )

    cfg = await get_agent_config()
    text = (payload.text or _TTS_TEST_TEXT).strip()[:200]  # cap to keep cost trivial

    # Resolve voice — fall back to provider's first voice if unspecified
    provider_meta = next(p for p in SUPPORTED_TTS_PROVIDERS if p["id"] == payload.provider)
    voice = (payload.voice or "").strip() or provider_meta["voices"][0]["id"]

    # For FPT, use the key the admin typed (if any) — otherwise the saved one.
    # Edge doesn't need a key.
    api_key = (payload.api_key or "").strip() or cfg.get("fpt_api_key", "")
    if payload.provider == "fpt" and not api_key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="FPT requires an API key (none saved, none provided)",
        )

    # Workers' src/ dir is on PYTHONPATH inside the container — import the
    # exact same generate_speech the worker uses. tts_edge / tts both expose
    # `generate_speech(text, output_path, voice, speed="", api_key=None)`.
    import sys as _sys
    src_dir = "/app/webreel-ai-agent/src"
    if src_dir not in _sys.path:
        _sys.path.insert(0, src_dir)

    if payload.provider == "edge":
        from tts_edge import generate_speech
    else:
        from tts import generate_speech

    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
        tmp_path = _Path(tmp.name)

    started = _time.time()
    try:
        # Run sync TTS in a thread so we don't block the event loop
        import asyncio as _asyncio

        def _run():
            return generate_speech(
                text=text,
                output_path=tmp_path,
                voice=voice,
                speed="",
                api_key=api_key or None,
            )

        seg = await _asyncio.to_thread(_run)
    except Exception as e:
        latency_ms = int((_time.time() - started) * 1000)
        logger.warning(f"TTS test failed for {admin.get('email')}: {e}")
        try:
            tmp_path.unlink(missing_ok=True)
        except Exception:
            pass
        return {
            "ok": False,
            "latency_ms": latency_ms,
            "duration_ms": 0,
            "detail": str(e),
        }

    latency_ms = int((_time.time() - started) * 1000)

    try:
        audio_bytes = tmp_path.read_bytes()
    finally:
        try:
            tmp_path.unlink(missing_ok=True)
        except Exception:
            pass

    logger.info(
        f"TTS test ok by {admin.get('email')}: provider={payload.provider}, "
        f"voice={voice}, audio_bytes={len(audio_bytes)}, duration={seg.duration_ms}ms"
    )

    return {
        "ok": True,
        "latency_ms": latency_ms,
        "duration_ms": seg.duration_ms,
        "audio_base64": base64.b64encode(audio_bytes).decode("ascii"),
        "audio_mime": "audio/mpeg",
        "detail": f"Generated {len(audio_bytes)} bytes",
    }


# -----------------------------------------------------------------
# Google Drive OAuth token management
# -----------------------------------------------------------------
#
# Workers that upload to Google Drive (presentation-gg-worker) read a
# pickled Credentials object from the shared `output_data` volume. The
# token must be generated OUT OF BAND (on a developer machine, via the
# `refresh_google_oauth_token.py` helper) — we never try to launch a
# browser inside the container, since that's what was causing the
# `webbrowser.Error: could not locate runnable browser` crash on every job.

# Max 256KB — a pickled Credentials object is ~2KB; anything larger is
# either wrong or malicious.
MAX_TOKEN_BYTES = 256 * 1024


@router.get("/agent-config/google-oauth")
async def admin_get_google_oauth_status(
    admin: dict = Depends(get_current_admin),
):
    """Inspect the on-disk Google OAuth token without exposing the secret."""
    from shared.google_drive_oauth import get_token_status

    info = get_token_status()
    logger.info(
        f"Admin {admin.get('email')} checked Google OAuth status: "
        f"level={info['warning_level']}"
    )
    return info


@router.post("/agent-config/google-oauth/upload")
async def admin_upload_google_oauth_token(
    file: UploadFile = File(...),
    admin: dict = Depends(get_current_admin),
):
    """Replace the on-disk OAuth token with an admin-uploaded pickle file.

    The admin generates the pickle on their own machine by running
    `python webreel-ai-agent/refresh_google_oauth_token.py` (or any
    `InstalledAppFlow.run_local_server` script), then uploads the
    resulting `google_oauth_token.pickle` here. The file is validated
    by `pickle.loads` + isinstance check before being written.
    """
    from shared.google_drive_oauth import save_uploaded_token

    contents = await file.read()
    if len(contents) > MAX_TOKEN_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Token file too large ({len(contents)} bytes, max {MAX_TOKEN_BYTES})",
        )
    if not contents:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Empty file uploaded",
        )

    try:
        new_status = save_uploaded_token(contents)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e

    logger.warning(
        f"Admin {admin.get('email')} uploaded new Google OAuth token "
        f"(scopes={new_status['scopes']}, expiry={new_status['expiry']})"
    )

    return {
        "message": "Token uploaded successfully",
        "status": new_status,
    }


# -----------------------------------------------------------------
# Google OAuth web flow (production-friendly alternative to CLI helper)
# -----------------------------------------------------------------
#
# The desktop helper script `refresh_google_oauth_token.py` requires a
# local browser, which doesn't exist on a VPS. These two endpoints let
# the admin log in to Google directly from the deployed admin UI:
#
#   1. UI calls GET  /agent-config/google-oauth/authorize → returns
#      {auth_url, state}. UI opens auth_url in a popup.
#   2. User picks a Google account, grants Drive.file scope.
#   3. Google redirects to /agent-config/google-oauth/callback?code=…&state=…
#   4. Backend exchanges code → token, saves pickle to volume, closes popup.
#
# REQUIRED Google Cloud Console setup (one-time):
#   - The redirect URI used at step 3 MUST be whitelisted on the OAuth
#     client. For a Desktop-type client (which ours is), Google accepts
#     any http://localhost:* — but for a production https://… host you
#     must convert the OAuth client to "Web application" type and add
#     the exact callback URL to "Authorized redirect URIs".
#
# Env var GOOGLE_OAUTH_REDIRECT_URI overrides the default localhost URL.
# Set it to the public callback URL in production (e.g.
# https://yourdomain.com/api/admin/agent-config/google-oauth/callback).

# In-memory state store. Process-local because the flow takes seconds
# and a single API container handles both ends of the round-trip. If
# you ever run multiple API replicas behind a load balancer, swap this
# for a Redis SET with a short TTL.
_oauth_state_store: dict[str, dict] = {}
_OAUTH_STATE_TTL_SEC = 600  # 10 min — plenty for the consent screen


def _default_redirect_uri(request_url: str) -> str:
    """Reconstruct the callback URL from the request that started the flow.

    Lets local dev (http://localhost:3000) and prod (https://domain.com)
    both work without per-env config. Override with env var when the
    public URL differs from what the API sees (e.g. behind a CDN that
    strips the original host).
    """
    import os
    from urllib.parse import urlparse

    override = os.getenv("GOOGLE_OAUTH_REDIRECT_URI", "").strip()
    if override:
        return override

    parsed = urlparse(request_url)
    return f"{parsed.scheme}://{parsed.netloc}/api/admin/agent-config/google-oauth/callback"


@router.get("/agent-config/google-oauth/authorize")
async def admin_google_oauth_authorize(
    request: Request,
    admin: dict = Depends(get_current_admin),
):
    """Start the Google OAuth web flow. Returns the URL to open in a popup."""
    from shared.google_drive_oauth import build_authorize_url
    import time

    redirect_uri = _default_redirect_uri(str(request.url))

    try:
        auth_url, state = build_authorize_url(redirect_uri)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Could not build OAuth URL: {e}",
        ) from e

    # Remember state + which admin started the flow so the callback can
    # confirm the same person finished it (defense in depth on top of CSRF)
    _oauth_state_store[state] = {
        "admin_email": admin.get("email"),
        "redirect_uri": redirect_uri,
        "created_at": time.time(),
    }
    # Drop expired states so the dict can't grow unbounded
    cutoff = time.time() - _OAUTH_STATE_TTL_SEC
    for s, v in list(_oauth_state_store.items()):
        if v.get("created_at", 0) < cutoff:
            del _oauth_state_store[s]

    logger.info(
        f"Admin {admin.get('email')} started Google OAuth flow "
        f"(redirect_uri={redirect_uri})"
    )

    return {"auth_url": auth_url, "state": state, "redirect_uri": redirect_uri}


@router.get("/agent-config/google-oauth/callback")
async def admin_google_oauth_callback(
    code: Optional[str] = None,
    state: Optional[str] = None,
    error: Optional[str] = None,
):
    """OAuth redirect target. Exchanges `code` for a token and saves it.

    Returns a tiny HTML page that closes the popup and notifies the
    opener. Doesn't require admin auth on this hop because (a) the
    `state` must match a value we issued seconds earlier from an
    authenticated call, and (b) the response is just "close yourself",
    not data exposure.
    """
    from fastapi.responses import HTMLResponse
    from shared.google_drive_oauth import exchange_code_for_token

    def _popup_html(ok: bool, message: str) -> str:
        # Communicate result to the opener via postMessage, then close.
        # Falls back to plain text if opener is gone (user closed parent
        # tab manually).
        safe = message.replace("'", "\\'").replace("\n", " ")
        return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>OAuth</title></head>
<body style="font-family:system-ui;padding:2rem;color:{"#16a34a" if ok else "#dc2626"};">
<h2>{"✓ Đăng nhập thành công" if ok else "✗ Đăng nhập thất bại"}</h2>
<p>{message}</p>
<p style="color:#888;">Tab này sẽ tự đóng…</p>
<script>
  try {{
    if (window.opener) {{
      window.opener.postMessage(
        {{type: 'google-oauth-result', ok: {str(ok).lower()}, message: '{safe}'}},
        '*'
      );
    }}
  }} catch (e) {{}}
  setTimeout(() => window.close(), 1500);
</script>
</body></html>"""

    if error:
        return HTMLResponse(_popup_html(False, f"Google trả lỗi: {error}"))

    if not code or not state:
        return HTMLResponse(_popup_html(False, "Thiếu code hoặc state"))

    state_info = _oauth_state_store.pop(state, None)
    if state_info is None:
        return HTMLResponse(
            _popup_html(False, "State không khớp hoặc đã hết hạn — thử lại từ admin UI")
        )

    redirect_uri = state_info["redirect_uri"]
    admin_email = state_info.get("admin_email", "unknown")

    try:
        new_status = exchange_code_for_token(code, redirect_uri)
    except Exception as e:
        logger.error(f"OAuth callback exchange failed for {admin_email}: {e}")
        return HTMLResponse(_popup_html(False, f"Đổi code thất bại: {e}"))

    logger.warning(
        f"Admin {admin_email} completed Google OAuth web flow "
        f"(scopes={new_status['scopes']}, expiry={new_status['expiry']})"
    )

    return HTMLResponse(
        _popup_html(True, f"Token mới đã lưu. Scopes: {', '.join(new_status['scopes'])}")
    )
