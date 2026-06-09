"""
Job routes with user isolation.

Users can only access their own jobs.
Admins can access all jobs via /api/admin/jobs.
"""

from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File
from typing import Optional
import logging
from pathlib import Path
import os
import shutil
from uuid import uuid4

from backend.auth import get_current_user
from backend.crud.jobs import list_jobs, get_job_by_id, cancel_job
from backend.storage import R2Storage
from backend.utils.sanitize import sanitize_filename

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/jobs", tags=["Jobs"])

# File upload configuration
MAX_FILE_SIZE_MB = 100  # 100MB limit
ALLOWED_EXTENSIONS = {
    # Office files
    ".xlsx", ".xls",  # Excel
    ".docx", ".doc",  # Word
    ".pptx", ".ppt",  # PowerPoint
    # Other common formats
    ".pdf", ".txt", ".csv",
}
UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", "C:/webreel_uploads"))

# Initialize R2 storage
r2_storage = R2Storage()


@router.get("/")
async def list_my_jobs(
    status: Optional[str] = None,
    limit: int = 50,
    user: dict = Depends(get_current_user)
):
    """
    List jobs for current user only.
    
    Users can only see their own jobs.
    Use /api/admin/jobs to see all jobs (admin only).
    """
    jobs = await list_jobs(
        user_id=user["user_id"],
        status=status,
        limit=limit
    )

    # Convert ObjectId to string + strip any leaked direct R2 URLs.
    # The owner-only /view endpoint mints fresh signed URLs on demand,
    # so the client never needs (and must not see) the permanent CDN URL.
    for job in jobs:
        if "_id" in job:
            job["_id"] = str(job["_id"])
        _scrub_video_url(job)

    return {
        "jobs": jobs,
        "total": len(jobs),
        "user_id": user["user_id"]
    }


def _scrub_video_url(job: dict) -> None:
    """Drop R2 CDN URLs from a job dict before sending it to the client.

    `result.video_url` historically held a permanent public R2 URL —
    knowing the URL was enough to fetch the video. The new model uses
    short-lived signed URLs minted by /view, so we replace `video_url`
    with a boolean-ish marker that just tells the frontend whether a
    video exists, without leaking how to reach it.
    """
    result = job.get("result")
    if not isinstance(result, dict):
        return
    raw_url = result.get("video_url")
    if raw_url:
        result["video_url"] = f"/api/jobs/{job.get('job_id')}/view"
        result["has_video"] = True


@router.get("/{job_id}")
async def get_my_job(
    job_id: str,
    user: dict = Depends(get_current_user)
):
    """
    Get job details (only if owned by user).
    
    Returns 403 if job belongs to another user.
    """
    job = await get_job_by_id(job_id)
    
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Job not found"
        )
    
    # Check ownership
    job_user_id = job.get("user_id")
    if job_user_id != user["user_id"]:
        logger.warning(
            f"User {user['user_id']} attempted to access job {job_id} owned by {job_user_id}"
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: not your job"
        )
    
    # Convert ObjectId to string
    if "_id" in job:
        job["_id"] = str(job["_id"])
    _scrub_video_url(job)

    return job


@router.delete("/{job_id}")
async def cancel_my_job(
    job_id: str,
    user: dict = Depends(get_current_user)
):
    """
    Cancel job (only if owned by user).
    
    Returns 403 if job belongs to another user.
    """
    job = await get_job_by_id(job_id)
    
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Job not found"
        )
    
    # Check ownership
    job_user_id = job.get("user_id")
    if job_user_id != user["user_id"]:
        logger.warning(
            f"User {user['user_id']} attempted to cancel job {job_id} owned by {job_user_id}"
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: not your job"
        )
    
    # Cancel the job
    success = await cancel_job(job_id)
    
    if not success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot cancel job in current status"
        )
    
    logger.info(f"User {user['user_id']} cancelled job {job_id}")
    
    return {
        "message": "Job cancelled successfully",
        "job_id": job_id
    }


@router.post("/upload-file")
async def upload_job_file(
    file: UploadFile = File(...),
    user: dict = Depends(get_current_user)
):
    """
    Upload file for OS job (Excel, Word, PowerPoint, PDF, etc.).
    
    File is saved to R2 storage (if enabled) or local storage.
    Returns file URL that can be used in job config.
    
    Limits:
    - Max file size: 100MB
    - Allowed extensions: .xlsx, .xls, .docx, .doc, .pptx, .ppt, .pdf, .txt, .csv
    
    Returns:
        {
            "file_url": "https://cdn.example.com/uploads/abc123_file.xlsx",
            "file_name": "file.xlsx",
            "file_size_bytes": 1234567,
            "storage_type": "r2" | "local"
        }
    """
    try:
        # Validate file extension
        file_ext = Path(file.filename).suffix.lower()
        if file_ext not in ALLOWED_EXTENSIONS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"File type not allowed. Allowed: {', '.join(ALLOWED_EXTENSIONS)}"
            )
        
        # Read file content
        file_content = await file.read()
        file_size_mb = len(file_content) / (1024 * 1024)
        
        # Validate file size
        if file_size_mb > MAX_FILE_SIZE_MB:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"File too large ({file_size_mb:.1f}MB). Max: {MAX_FILE_SIZE_MB}MB"
            )
        
        # Generate unique filename
        unique_id = str(uuid4())[:8]
        safe_filename = f"{unique_id}_{sanitize_filename(file.filename)}"
        
        # Try R2 storage first
        if r2_storage.is_enabled():
            # Save to temp file
            temp_path = Path(f"/tmp/{safe_filename}")
            temp_path.write_bytes(file_content)
            
            try:
                # Upload to R2
                file_url = await r2_storage.upload_file(temp_path, prefix="uploads")
                
                if file_url:
                    logger.info(
                        f"User {user['user_id']} uploaded file to R2: {safe_filename} ({file_size_mb:.2f}MB)"
                    )
                    
                    # Cleanup temp file
                    temp_path.unlink(missing_ok=True)
                    
                    return {
                        "file_url": file_url,
                        "file_name": file.filename,
                        "file_size_bytes": len(file_content),
                        "storage_type": "r2"
                    }
            finally:
                # Cleanup temp file if still exists
                temp_path.unlink(missing_ok=True)
        
        # Fallback to local storage
        UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        local_path = UPLOAD_DIR / safe_filename
        
        # Save file
        local_path.write_bytes(file_content)
        
        # Generate local URL (will be downloaded by worker)
        # Format: file://C:/webreel_uploads/abc123_file.xlsx
        file_url = f"file://{local_path.as_posix()}"
        
        logger.info(
            f"User {user['user_id']} uploaded file to local storage: {safe_filename} ({file_size_mb:.2f}MB)"
        )
        
        return {
            "file_url": file_url,
            "file_name": file.filename,
            "file_size_bytes": len(file_content),
            "storage_type": "local"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"File upload failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"File upload failed: {str(e)}"
        )
