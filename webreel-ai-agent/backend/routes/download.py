"""
Download routes for job result files.

Users can download video, document, and PDF files from completed jobs.
Requires user ownership verification.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse, RedirectResponse
from pathlib import Path
import logging

from backend.auth import get_current_user
from backend.crud.jobs import get_job
from backend.utils.file_handler import get_output_directory

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/jobs", tags=["Downloads"])


def _check_job_access(job: dict, user: dict, job_id: str) -> None:
    """Raise 403/400/404 if `user` cannot read `job`'s result files.

    Admins can view any job; regular users only their own. Job must be
    in a terminal state with a result attached.
    """
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Job not found"
        )

    job_user_id = job.get("user_id")
    is_admin = user.get("role") == "admin"
    if not is_admin and job_user_id != user["user_id"]:
        logger.warning(
            f"User {user['user_id']} tried to access job {job_id} owned by {job_user_id}"
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: not your job",
        )

    job_status = job.get("status")
    if job_status not in ("completed", "pending_review"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Job not ready yet (status: {job_status})",
        )


@router.get("/{job_id}/view")
async def view_video(
    job_id: str,
    json: bool = False,
    user: dict = Depends(get_current_user),
):
    """Issue a short-lived signed URL for in-browser playback.

    Owner (or admin) only. The permanent R2 public URL is never sent
    to the client; every "Xem" click hits this endpoint, which checks
    ownership and returns a fresh URL valid for 10 minutes.

    Pass `?json=true` to get `{url, expires_in}` JSON instead of a 302
    redirect — the React app uses this so it can attach the JWT header
    (browsers can't add Authorization to a plain <video src> request).

    Falls back to streaming the local file if R2 was disabled when this
    job ran.
    """
    job = await get_job(job_id)
    _check_job_access(job, user, job_id)

    result = job.get("result") or {}
    r2_key = result.get("r2_key")

    # Backward compat: old jobs only stored video_url (the permanent CDN
    # URL), no r2_key. Recover the key from the URL on the fly so they
    # still play after we cut over to signed URLs.
    if not r2_key:
        from backend.storage import R2Storage

        r2_key = R2Storage.derive_r2_key_from_url(result.get("video_url"))

    if r2_key:
        from backend.storage import R2Storage

        signed = R2Storage().generate_presigned_url(r2_key, expires_in=600, inline=True)
        if signed:
            logger.info(
                f"User {user['user_id']} viewing job {job_id} via signed URL "
                f"(role={user.get('role')}, expires=600s, mode={'json' if json else 'redirect'})"
            )
            if json:
                return {"url": signed, "expires_in": 600}
            return RedirectResponse(url=signed, status_code=status.HTTP_302_FOUND)
        logger.warning(f"R2 signing failed for {r2_key}, falling back to local file")

    # Local file fallback (R2 disabled or signing failed)
    video_path_str = result.get("video_path")
    if not video_path_str:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Video not available for this job",
        )
    video_path = Path(video_path_str)
    if not video_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Video file missing on server",
        )
    if json:
        # Local-mode JSON path: tell the frontend to hit this same
        # endpoint without ?json so the FileResponse streams. The
        # frontend has to attach JWT but that's fine for an <a>
        # opened via JS — see api.ts.
        from urllib.parse import quote

        return {"url": f"/api/jobs/{quote(job_id)}/view", "expires_in": 0}
    return FileResponse(
        path=video_path,
        media_type="video/mp4",
    )


@router.get("/{job_id}/download/{file_type}")
async def download_file(
    job_id: str,
    file_type: str,
    user: dict = Depends(get_current_user)
):
    """
    Download result file from completed job.

    Users can only download files from their own jobs.

    Args:
        job_id: Job UUID
        file_type: Type of file to download (video, document, pdf)
        user: Current authenticated user

    Returns:
        FileResponse: File download with proper headers

    Raises:
        HTTPException: 403, 404, 400 for various errors
    """
    # Validate file_type
    valid_types = ["video", "document", "pdf"]
    if file_type not in valid_types:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid file_type. Must be one of: {', '.join(valid_types)}"
        )

    # Get job from MongoDB
    job = await get_job(job_id)
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Job not found"
        )

    # Check ownership (admins bypass)
    job_user_id = job.get("user_id")
    is_admin = user.get("role") == "admin"
    if not is_admin and job_user_id != user["user_id"]:
        logger.warning(
            f"User {user['user_id']} attempted to download file from job {job_id} owned by {job_user_id}"
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: not your job"
        )
    
    # Check if job is completed
    if job.get("status") != "completed":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Job not completed yet (status: {job.get('status')})"
        )
    
    # Get file path from result
    result = job.get("result", {})
    file_path_key = f"{file_type}_path"
    file_path_str = result.get(file_path_key)

    # For video files, prefer R2 (signed URL) if available
    r2_key = result.get("r2_key") if file_type == "video" else None
    video_url = result.get("video_url") if file_type == "video" else None

    if not file_path_str and not r2_key and not video_url:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{file_type.capitalize()} file not available for this job"
        )

    # If local file path exists, try to serve it
    if file_path_str:
        file_path = Path(file_path_str)

        if file_path.exists():
            # Determine media type
            media_types = {
                "video": "video/mp4",
                "document": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                "pdf": "application/pdf"
            }
            media_type = media_types.get(file_type, "application/octet-stream")

            # Return file with download header
            logger.info(f"User {user['user_id']} downloading {file_type} from job {job_id}")

            return FileResponse(
                path=file_path,
                media_type=media_type,
                filename=file_path.name,
                headers={
                    "Content-Disposition": f'attachment; filename="{file_path.name}"'
                }
            )

    # R2 fallback: redirect to a short-lived signed URL (force-download).
    # Previously this proxied the whole file through the API server —
    # huge bandwidth waste. The signed URL is the same authz boundary
    # because we already checked ownership above.
    if file_type == "video" and not r2_key:
        # Old jobs may have only video_url; recover the key.
        from backend.storage import R2Storage

        r2_key = R2Storage.derive_r2_key_from_url(video_url)

    if r2_key:
        from backend.storage import R2Storage

        signed = R2Storage().generate_presigned_url(r2_key, expires_in=600, inline=False)
        if signed:
            logger.info(
                f"User {user['user_id']} downloading job {job_id} via signed R2 URL"
            )
            return RedirectResponse(url=signed, status_code=status.HTTP_302_FOUND)
        logger.error(f"R2 signing failed for {r2_key}")

    logger.error(f"File not found on disk: {file_path_str}")
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"{file_type.capitalize()} file not found on server"
    )

