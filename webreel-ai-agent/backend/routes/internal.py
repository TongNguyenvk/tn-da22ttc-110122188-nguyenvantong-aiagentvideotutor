"""
Internal API routes for OS Worker communication.

These endpoints are for internal use only (worker -> API).
Authentication via INTERNAL_API_KEY bearer token.
"""

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from typing import Optional
import logging
import json
from datetime import datetime, timezone
from pathlib import Path

from backend.utils.file_handler import (
    validate_file_type,
    validate_file_size,
    validate_job_id,
    save_upload_file,
    get_output_directory
)
from backend.database import Database
from backend.crud.jobs import get_job, update_job

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/internal", tags=["Internal"])

# Security scheme
security = HTTPBearer()


def verify_internal_api_key(credentials: HTTPAuthorizationCredentials = Depends(security)) -> bool:
    """
    Verify internal API key from Authorization header.
    
    Args:
        credentials: HTTP Bearer credentials
        
    Returns:
        bool: True if valid
        
    Raises:
        HTTPException: 401 if invalid
    """
    import os
    expected_key = os.getenv("INTERNAL_API_KEY")
    
    if not expected_key:
        logger.error("INTERNAL_API_KEY not configured in environment")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal API key not configured"
        )
    
    if credentials.credentials != expected_key:
        logger.warning(f"Invalid internal API key attempt: {credentials.credentials[:10]}...")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid internal API key"
        )
    
    return True


@router.post("/upload-result")
async def upload_result(
    job_id: str = Form(...),
    metadata: str = Form(...),
    video: Optional[UploadFile] = File(None),
    document: Optional[UploadFile] = File(None),
    pdf: Optional[UploadFile] = File(None),
    authenticated: bool = Depends(verify_internal_api_key)
):
    """
    Upload OS Worker result files.
    
    This endpoint receives video, document, and PDF files from the OS Worker
    after job completion. Files are saved to output/{job_id}/ and job status
    is updated in MongoDB.
    
    Args:
        job_id: Job UUID (form field)
        metadata: JSON string with job metadata (form field)
        video: Video file (optional, multipart)
        document: Document file (optional, multipart)
        pdf: PDF file (optional, multipart)
        authenticated: Internal API key verification
        
    Returns:
        dict: Upload confirmation with file details
        
    Raises:
        HTTPException: 400, 404, 413, 500 for various errors
    """
    logger.info(f"Upload request received for job {job_id}")
    
    # Validate job_id format (prevent path traversal)
    if not validate_job_id(job_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid job_id format"
        )
    
    # Check if job exists in MongoDB
    job = await get_job(job_id)
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job {job_id} not found"
        )
    
    # Parse metadata JSON
    try:
        metadata_dict = json.loads(metadata)
    except json.JSONDecodeError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid metadata JSON: {str(e)}"
        )
    
    # Validate at least one file is provided
    if not any([video, document, pdf]):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one file (video, document, or pdf) must be provided"
        )
    
    # Get output directory
    import os
    base_dir = os.getenv("OUTPUT_DIR", "output")
    job_dir = get_output_directory(job_id, base_dir)
    
    # Track uploaded files
    uploaded_files = {}
    file_sizes = {}
    
    # Upload video
    if video:
        if not validate_file_type(video.filename, "video"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid video file type: {video.filename}"
            )
        
        video_name = metadata_dict.get("video_name", "video")
        video_path = job_dir / f"{video_name}_final.mp4"
        
        success, error, size = await save_upload_file(video, video_path)
        if not success:
            if "too large" in error.lower():
                raise HTTPException(
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    detail=error
                )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=error
            )
        
        uploaded_files["video"] = str(video_path)
        file_sizes["video"] = size
        logger.info(f"Video uploaded: {video_path} ({size} bytes)")
    
    # Upload document
    if document:
        if not validate_file_type(document.filename, "document"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid document file type: {document.filename}"
            )
        
        video_name = metadata_dict.get("video_name", "document")
        doc_path = job_dir / f"{video_name}.docx"
        
        success, error, size = await save_upload_file(document, doc_path)
        if not success:
            if "too large" in error.lower():
                raise HTTPException(
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    detail=error
                )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=error
            )
        
        uploaded_files["document"] = str(doc_path)
        file_sizes["document"] = size
        logger.info(f"Document uploaded: {doc_path} ({size} bytes)")
    
    # Upload PDF
    if pdf:
        if not validate_file_type(pdf.filename, "pdf"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid PDF file type: {pdf.filename}"
            )
        
        video_name = metadata_dict.get("video_name", "document")
        pdf_path = job_dir / f"{video_name}.pdf"
        
        success, error, size = await save_upload_file(pdf, pdf_path)
        if not success:
            if "too large" in error.lower():
                raise HTTPException(
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    detail=error
                )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=error
            )
        
        uploaded_files["pdf"] = str(pdf_path)
        file_sizes["pdf"] = size
        logger.info(f"PDF uploaded: {pdf_path} ({size} bytes)")
    
    # Save metadata.json
    metadata_path = job_dir / "metadata.json"
    try:
        with open(metadata_path, "w", encoding="utf-8") as f:
            json.dump(metadata_dict, f, indent=2, ensure_ascii=False)
        logger.info(f"Metadata saved: {metadata_path}")
    except Exception as e:
        logger.error(f"Failed to save metadata: {e}")
        # Non-critical, continue
    
    # Upload to R2 if enabled
    video_url = f"/api/jobs/{job_id}/download/video" if video else None
    r2_key: Optional[str] = None
    if "video" in uploaded_files:
        from backend.storage import R2Storage
        import os
        r2_storage = R2Storage()
        local_video_path = Path(uploaded_files["video"])

        if r2_storage.is_enabled() and local_video_path.exists():
            logger.info(f"Uploading OS Worker video {local_video_path.name} to R2...")
            r2_result = await r2_storage.upload_video(local_video_path, job_id)
            if r2_result and "cdn_url" in r2_result:
                video_url = r2_result["cdn_url"]
                r2_key = r2_result.get("r2_key")
                logger.info(f"OS Worker video uploaded to R2: {video_url}. Deleting local file.")
                try:
                    os.remove(local_video_path)
                except Exception as e:
                    logger.warning(f"Failed to delete local video file {local_video_path}: {e}")

    # Update job in MongoDB
    result_data = {
        "video_url": video_url,
        "r2_key": r2_key,
        "document_url": f"/api/jobs/{job_id}/download/document" if document else None,
        "pdf_url": f"/api/jobs/{job_id}/download/pdf" if pdf else None,
        "video_path": uploaded_files.get("video"),
        "document_path": uploaded_files.get("document"),
        "pdf_path": uploaded_files.get("pdf"),
        "file_sizes": file_sizes,
        "metadata": metadata_dict,
    }
    
    mongo_updates = {
        "status": "completed",
        "result": result_data,
        "completed_at": datetime.now(timezone.utc),
    }
    
    try:
        await update_job(job_id, mongo_updates)
        logger.info(f"Job {job_id} marked as completed in MongoDB")
    except Exception as e:
        logger.error(f"Failed to update job in MongoDB: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update job status: {str(e)}"
        )
    
    # Return success response
    return {
        "job_id": job_id,
        "status": "completed",
        "uploaded_files": uploaded_files,
        "file_sizes": file_sizes,
        "message": "Upload successful"
    }


@router.get("/health")
async def internal_health_check(authenticated: bool = Depends(verify_internal_api_key)):
    """
    Health check endpoint for OS Worker.
    
    Verifies API connectivity and authentication.
    """
    return {
        "status": "healthy",
        "service": "webreel-api",
        "authenticated": True
    }
