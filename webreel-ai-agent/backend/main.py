"""
FastAPI Backend for Webreel Video Generation
Provides REST API endpoints and WebSocket support for asynchronous video generation.
"""

from fastapi import FastAPI, HTTPException, BackgroundTasks, WebSocket, WebSocketDisconnect, UploadFile, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from contextlib import asynccontextmanager
import asyncio
import logging
import time
from pathlib import Path
from datetime import datetime, timezone
from uuid import uuid4
from typing import Optional

from backend.job_models import (
    JobSubmitRequest,
    JobSubmitResponse,
    Job,
    JobConfig,
    JobProgress,
    JobResult
)
from backend.tasks import execute_pipeline_task
from backend.websocket import manager
from backend.logging_config import setup_logging
from backend.middleware import RequestLoggingMiddleware, limiter, rate_limit_exceeded_handler
from backend.output_paths import build_video_url, resolve_output_dir
from backend.shutdown import ShutdownHandler
from backend.queue import JobQueue
from backend.database import Database
from backend.admin_routes import router as admin_router
from backend.routes.auth import router as auth_router
from backend.routes.jobs import router as jobs_router
from backend.routes.admin import router as admin_api_router
from backend.routes.browser import router as browser_router
from backend.routes.internal import router as internal_router
from backend.routes.download import router as download_router
from backend.routes.session import router as session_router
from backend.auth import get_current_user
from backend.utils.sanitize import sanitize_filename

# Setup structured logging
setup_logging()
logger = logging.getLogger(__name__)

# Global job queue with asyncio lock
job_queue: dict[str, dict] = {}
job_queue_lock = asyncio.Lock()

# Track running asyncio tasks for immediate cancellation
job_tasks: dict[str, asyncio.Task] = {}
job_tasks_lock = asyncio.Lock()

# Redis queue (production mode)
redis_queue = JobQueue()
_result_listener_task: Optional[asyncio.Task] = None

# Initialize shutdown handler
shutdown_handler = ShutdownHandler(
    job_queue=job_queue,
    job_queue_lock=job_queue_lock,
    connection_manager=manager
)


async def hydrate_job_queue_from_mongodb():
    """
    Load active jobs from MongoDB back into RAM on startup.
    
    This ensures jobs survive container restarts (RAM hydration).
    Critical for production reliability.
    """
    if not Database.is_connected():
        logger.warning("MongoDB not connected, skipping hydration")
        return
    
    from backend.crud.jobs import list_jobs
    
    try:
        # Load pending and running jobs
        pending_jobs = await list_jobs(status="pending", limit=1000)
        running_jobs = await list_jobs(status="running", limit=1000)
        pending_review_jobs = await list_jobs(status="pending_review", limit=1000)
        
        active_jobs = pending_jobs + running_jobs + pending_review_jobs
        
        if not active_jobs:
            logger.info("No active jobs to hydrate from MongoDB")
            return
        
        async with job_queue_lock:
            for job in active_jobs:
                job_id = job["job_id"]
                
                # Convert MongoDB document to in-memory format
                job_entry = {
                    "job_id": job_id,
                    "status": job["status"],
                    "task": job["task"],
                    "video_name": job["video_name"],
                    "config": job["config"],
                    "progress": job.get("progress"),
                    "result": job.get("result"),
                    "error": job.get("error"),
                    "created_at": job["created_at"].isoformat() if hasattr(job["created_at"], "isoformat") else str(job["created_at"]),
                    "started_at": job.get("started_at"),
                    "completed_at": job.get("completed_at"),
                }
                
                job_queue[job_id] = job_entry
        
        logger.info(f"✅ Hydrated {len(active_jobs)} active jobs from MongoDB into RAM")
        logger.info(f"   - Pending: {len(pending_jobs)}")
        logger.info(f"   - Running: {len(running_jobs)}")
        logger.info(f"   - Pending Review: {len(pending_review_jobs)}")
        
    except Exception as e:
        logger.error(f"Failed to hydrate job queue from MongoDB: {e}", exc_info=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan event handler.
    
    Handles startup and shutdown events for the FastAPI application.
    
    Requirements: 10.1, 10.5
    """
    global _result_listener_task
    
    # Startup
    # Check default passwords (Fail-safe credentials check)
    import os
    import sys
    
    env = os.getenv("ENVIRONMENT", "development")
    mongo_pass = os.getenv("MONGO_PASSWORD", "")
    redis_pass = os.getenv("REDIS_PASSWORD", "")
    
    if mongo_pass == "webreel_mongo_2026" or redis_pass == "webreel_secret_2026":
        if env == "production":
            logger.critical(
                "CRITICAL SECURITY ALERT: Running in PRODUCTION mode but default credentials are still in use! "
                "MONGO_PASSWORD or REDIS_PASSWORD is set to default values. Exiting for safety."
            )
            sys.exit(1)
        else:
            logger.warning(
                "SECURITY WARNING: Default credentials (MONGO_PASSWORD/REDIS_PASSWORD) are in use. "
                "Ensure these are changed in production environments."
            )

    shutdown_handler.register_signal_handlers()
    
    # Connect to MongoDB FIRST (source of truth)
    await Database.connect()
    
    # Hydrate job queue from MongoDB (CRITICAL for production!)
    await hydrate_job_queue_from_mongodb()
    
    # Then load from disk (backward compat, will be merged with MongoDB data)
    await shutdown_handler.load_job_queue()
    
    # Start Redis result listener (polls worker results in background)
    _result_listener_task = asyncio.create_task(_listen_for_worker_results())
    
    logger.info("FastAPI backend started successfully")
    if redis_queue.redis:
        logger.info(f"Redis queue connected: {redis_queue.redis_url}")
    else:
        logger.info("Redis not available, using direct execution mode only")
    
    if Database.is_connected():
        logger.info("MongoDB connected and ready")
    else:
        logger.warning("MongoDB not available, using in-memory storage only")
    
    yield
    
    # Shutdown
    if _result_listener_task:
        _result_listener_task.cancel()
    await Database.close()
    logger.info("FastAPI backend shutting down")


app = FastAPI(
    title="Webreel Video Generation API",
    description="Asynchronous video generation backend with real-time progress updates",
    version="1.0.0",
    lifespan=lifespan
)

# Proxy headers/trusted hosts middleware (placed before rate limiter)
from starlette.middleware.trustedhost import TrustedHostMiddleware
import os
allowed_hosts = os.getenv("ALLOWED_HOSTS", "*").split(",")
app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=allowed_hosts
)

# Register rate limiter state and exception handler
if limiter is not None:
    app.state.limiter = limiter
    try:
        from slowapi.errors import RateLimitExceeded
        app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)
    except ImportError:
        pass

# Add request logging middleware
app.add_middleware(RequestLoggingMiddleware)

# CORS configuration for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins for development
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static file serving for video downloads
output_dir = resolve_output_dir()
output_dir.mkdir(parents=True, exist_ok=True)
app.mount("/videos", StaticFiles(directory=str(output_dir)), name="videos")

# Include routers
app.include_router(auth_router)
app.include_router(jobs_router)  # NEW: User-scoped job routes
app.include_router(admin_api_router)  # NEW: Admin API routes
app.include_router(browser_router)  # NEW: Browser session management
app.include_router(internal_router)  # NEW: Internal API for OS Worker
app.include_router(download_router)  # NEW: Download endpoints
app.include_router(session_router)  # NEW: Session Manager API
app.include_router(admin_router)  # Legacy admin routes (cookies, etc.)


async def _listen_for_worker_results():
    """Background task that polls Redis for worker results and updates job status.
    
    When a worker completes a job, it stores the result in Redis and publishes
    a notification. This listener picks up those results and updates the
    in-memory job queue + broadcasts via WebSocket.
    """
    import json as _json
    
    if not redis_queue.redis:
        logger.info("Redis not available, result listener disabled")
        return
    
    logger.info("Redis result listener started")
    
    try:
        pubsub = redis_queue.redis.pubsub()
        pubsub.subscribe("job-updates", "session-expired")
        
        while True:
            message = pubsub.get_message(timeout=2.0)
            if message and message["type"] == "message":
                try:
                    channel = message.get("channel", "job-updates")
                    data = _json.loads(message["data"])

                    # ---------------------------------------------------------
                    # Circuit Breaker: xử lý session-expired event
                    # ---------------------------------------------------------
                    if channel == "session-expired":
                        queue_name = data.get("queue", "unknown")
                        job_id = data.get("job_id", "unknown")
                        error_msg = data.get("error", "Session expired")
                        logger.warning(
                            f"CIRCUIT BREAKER: Queue {queue_name} đã bị tạm dừng "
                            f"do session hết hạn (job {job_id}): {error_msg}"
                        )

                        # Cập nhật job status trong RAM
                        async with job_queue_lock:
                            if job_id in job_queue:
                                job_queue[job_id]["status"] = "failed"
                                job_queue[job_id]["error"] = f"SESSION_EXPIRED: {error_msg}"
                                job_queue[job_id]["completed_at"] = datetime.now(timezone.utc).isoformat()

                        # Cập nhật MongoDB
                        if Database.is_connected():
                            from backend.crud.jobs import update_job
                            await update_job(job_id, {
                                "status": "failed",
                                "error": f"SESSION_EXPIRED: {error_msg}",
                                "completed_at": datetime.now(timezone.utc),
                            })

                        # Broadcast cảnh báo tới TẤT CẢ WebSocket clients
                        await manager.broadcast_global({
                            "event": "session_expired",
                            "queue": queue_name,
                            "job_id": job_id,
                            "error": error_msg,
                            "message": f"Queue {queue_name} đã bị tạm dừng: session hết hạn. Vui lòng đăng nhập lại trên Session Manager.",
                            "timestamp": data.get("timestamp", time.time()),
                        })

                        # Broadcast cập nhật cho job cụ thể
                        await broadcast_progress(job_id)
                        continue

                    # ---------------------------------------------------------
                    # Xử lý job-updates bình thường
                    # ---------------------------------------------------------
                    job_id = data.get("job_id")
                    if not job_id:
                        continue
                    
                    event = data.get("event")
                    
                    if event == "progress":
                        progress_data = data.get("progress")
                        new_status = None
                        async with job_queue_lock:
                            if job_id in job_queue:
                                job_queue[job_id]["progress"] = progress_data
                                if progress_data.get("current_phase") == 2.5:
                                    job_queue[job_id]["status"] = "pending_review"
                                    new_status = "pending_review"
                                else:
                                    # Sync running status for other phases
                                    current = job_queue[job_id].get("status")
                                    if current in ("queued", "pending"):
                                        job_queue[job_id]["status"] = "running"
                                        new_status = "running"
                        
                        # Persist status change to MongoDB
                        if new_status and Database.is_connected():
                            from backend.crud.jobs import update_job
                            mongo_updates = {"progress": progress_data, "status": new_status}
                            if new_status == "running":
                                mongo_updates["started_at"] = datetime.now(timezone.utc)
                            await update_job(job_id, mongo_updates)
                            logger.info(f"MongoDB synced: Job {job_id} -> {new_status}")
                        
                        await broadcast_progress(job_id)
                        continue
                        
                    if event != "completed":
                        continue
                        
                    # Fetch full result from Redis
                    result = redis_queue.get_result(job_id)
                    if not result:
                        continue
                    
                    completed_at = datetime.now(timezone.utc).isoformat()
                    video_path_str = result.get("video_path", "")
                    video_url = ""
                    
                    if video_path_str:
                        from backend.storage import R2Storage
                        from pathlib import Path
                        import os
                        
                        r2_storage = R2Storage()
                        local_path = Path(video_path_str)
                        r2_key: Optional[str] = None

                        if r2_storage.is_enabled() and local_path.exists():
                            logger.info(f"Uploading video {local_path.name} to R2...")
                            r2_result = await r2_storage.upload_video(local_path, job_id)

                            if r2_result and "cdn_url" in r2_result:
                                # Keep cdn_url for backward compat but stash
                                # r2_key so /view can sign a short-lived URL
                                # on each play.
                                video_url = r2_result["cdn_url"]
                                r2_key = r2_result.get("r2_key")
                                logger.info(f"Uploaded to R2: {video_url}. Deleting local file.")
                                try:
                                    os.remove(local_path)
                                except Exception as e:
                                    logger.warning(f"Failed to delete local video file {local_path}: {e}")
                            else:
                                video_url = build_video_url(video_path_str)
                        else:
                            video_url = build_video_url(video_path_str)

                    result_status = result.get("status", "completed")
                    result_data = {
                        "video_path": video_path_str,
                        "video_url": video_url,
                        "r2_key": r2_key,
                        "duration_seconds": None,
                    }
                    
                    # Update progress to final phase when completed
                    final_progress = {
                        "current_phase": 6,
                        "phase_name": "Completed",
                        "message": "Video generation completed successfully"
                    }
                    
                    # Update in-memory job queue
                    async with job_queue_lock:
                        if job_id in job_queue:
                            job_queue[job_id]["status"] = result_status
                            job_queue[job_id]["result"] = result_data
                            job_queue[job_id]["progress"] = final_progress
                            if result.get("error"):
                                job_queue[job_id]["error"] = result["error"]
                            job_queue[job_id]["completed_at"] = completed_at
                    
                    # Persist to MongoDB
                    if Database.is_connected():
                        from backend.crud.jobs import update_job
                        mongo_updates = {
                            "status": result_status,
                            "result": result_data,
                            "progress": final_progress,
                            "completed_at": datetime.now(timezone.utc),
                        }
                        if result.get("error"):
                            mongo_updates["error"] = result["error"]
                        await update_job(job_id, mongo_updates)
                        logger.info(f"MongoDB synced: Job {job_id} -> {result_status} (completed)")
                    
                    # Broadcast to WebSocket clients
                    await broadcast_progress(job_id)
                    logger.info(f"Worker result received for Job {job_id}: {result_status}")
                    
                except Exception as e:
                    logger.warning(f"Error processing worker result: {e}")
            
            await asyncio.sleep(0.5)
    
    except asyncio.CancelledError:
        logger.info("Redis result listener stopped")
        pubsub.unsubscribe()
    except Exception as e:
        logger.error(f"Result listener error: {e}", exc_info=True)


async def update_job_status(job_id: str, updates: dict) -> None:
    """
    Thread-safe helper function to update job status in the queue.
    
    Args:
        job_id: Unique identifier for the job
        updates: Dictionary of fields to update in the job entry
    """
    async with job_queue_lock:
        if job_id in job_queue:
            job_queue[job_id].update(updates)


async def execute_pipeline_with_tracking(
    job_id: str,
    task: str,
    video_name: str,
    config: dict
):
    """
    Wrapper for execute_pipeline_task that tracks active task count.
    
    Increments active task counter before execution and decrements after completion.
    Handles task cancellation for immediate stop.
    
    Requirements: 10.2
    """
    try:
        # Increment active task counter
        await shutdown_handler.increment_active_tasks()
        
        # Setup pause event for Phase 2.5 review
        import asyncio
        pause_event = asyncio.Event()
        
        # Set pause event in pipeline module using job_id
        import sys
        from pathlib import Path
        agent_dir = Path(__file__).parent.parent
        sys.path.insert(0, str(agent_dir))
        from run_pipeline import set_review_pause_event
        set_review_pause_event(job_id, pause_event)
        
        # Execute the pipeline task
        await execute_pipeline_task(
            job_id=job_id,
            task=task,
            video_name=video_name,
            config=config,
            update_job_status_func=update_job_status,
            broadcast_progress_func=broadcast_progress
        )
    
    except asyncio.CancelledError:
        # Task was force cancelled by user
        logger.info(
            f"Job {job_id}: Task force cancelled (killed immediately)",
            extra={"job_id": job_id}
        )
        
        # Update job status if not already cancelled
        async with job_queue_lock:
            if job_id in job_queue and job_queue[job_id]["status"] != "cancelled":
                job_queue[job_id]["status"] = "cancelled"
                job_queue[job_id]["error"] = "Job force killed by user"
                job_queue[job_id]["completed_at"] = datetime.now(timezone.utc).isoformat()
        
        # Broadcast final state
        await broadcast_progress(job_id)
        
        # Re-raise to properly cancel the task
        raise
    
    finally:
        # Clean up pause event
        from run_pipeline import clear_review_pause_event
        clear_review_pause_event(job_id)
        
        # Remove task reference
        async with job_tasks_lock:
            if job_id in job_tasks:
                del job_tasks[job_id]
        
        # Always decrement counter, even if task fails
        await shutdown_handler.decrement_active_tasks()


async def broadcast_progress(job_id: str) -> None:
    """
    Broadcast current job status to all connected WebSocket clients.
    
    Args:
        job_id: Unique identifier for the job
    
    Requirements: 4.3, 4.4, 4.5
    """
    async with job_queue_lock:
        if job_id in job_queue:
            job_data = job_queue[job_id].copy()
        else:
            return
    
    # Broadcast to all connected clients for this job
    await manager.broadcast(job_id, job_data)


@app.post("/api/jobs", response_model=JobSubmitResponse, status_code=201)
async def submit_job(request: JobSubmitRequest, background_tasks: BackgroundTasks):
    """
    Submit a new video generation job.
    
    Creates a new job entry in the queue with pending status. Routes the job
    to the appropriate queue based on environment:
    - web: Execute directly in background task
    - os: Route to os-queue (Redis) for OS Worker
    - presentation: Route to presentation-queue (Redis) for Presentation Worker
    
    Returns the job_id and websocket_url for progress tracking.
    
    Requirements: 8.1, 2.3, 1.1, 3.1, 3.6, 10.1
    """
    # Check if server is accepting new jobs
    if not shutdown_handler.is_accepting_jobs():
        logger.warning("Job submission rejected: server is shutting down")
        raise HTTPException(
            status_code=503,
            detail="Service Unavailable: Server is shutting down"
        )
    
    # Generate unique job_id
    job_id = str(uuid4())
    
    environment = request.environment
    
    logger.info(
        f"Job submitted: {job_id} (environment: {environment})",
        extra={
            "job_id": job_id,
            "task": request.task[:100],  # Truncate long tasks
            "video_name": request.video_name,
            "environment": environment
        }
    )
    
    # Initialize job entry
    job_entry = {
        "job_id": job_id,
        "status": "pending",
        "task": request.task,
        "video_name": request.video_name,
        "environment": environment,
        "config": request.config.model_dump(),
        "progress": None,
        "result": None,
        "error": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "started_at": None,
        "completed_at": None
    }
    
    # Add to job queue
    async with job_queue_lock:
        job_queue[job_id] = job_entry
    
    # Route job based on environment
    if environment == "web":
        # Web environment: Execute directly in background task
        logger.info(f"Job {job_id}: Routing to web pipeline (direct execution)")
        
        # Create asyncio task for immediate cancellation support
        task = asyncio.create_task(
            execute_pipeline_with_tracking(
                job_id=job_id,
                task=request.task,
                video_name=request.video_name,
                config=request.config.model_dump()
            )
        )
        
        # Store task reference for cancellation
        async with job_tasks_lock:
            job_tasks[job_id] = task
    
    elif environment == "os":
        # OS environment: Route to os-queue for OS Worker
        if not redis_queue.redis:
            raise HTTPException(
                status_code=503,
                detail="OS Worker not available: Redis queue not connected"
            )
        
        logger.info(f"Job {job_id}: Routing to os-queue for OS Worker")
        
        # Update status to queued
        async with job_queue_lock:
            job_queue[job_id]["status"] = "queued"
        
        # Push to Redis queue
        redis_queue.push("os-queue", job_entry)
        
        # Persist to MongoDB
        if Database.is_connected():
            from backend.crud.jobs import create_job
            await create_job(job_entry)
    
    elif environment == "presentation":
        # Presentation environment: Route to presentation-queue
        if not redis_queue.redis:
            raise HTTPException(
                status_code=503,
                detail="Presentation Worker not available: Redis queue not connected"
            )
        
        logger.info(f"Job {job_id}: Routing to presentation-queue for Presentation Worker")
        
        # Update status to queued
        async with job_queue_lock:
            job_queue[job_id]["status"] = "queued"
        
        # Push to Redis queue
        redis_queue.push("presentation-queue", job_entry)
        
        # Persist to MongoDB
        if Database.is_connected():
            from backend.crud.jobs import create_job
            await create_job(job_entry)
    
    else:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid environment: {environment}"
        )
    
    # Return response with websocket URL
    return JobSubmitResponse(
        job_id=job_id,
        status=job_entry["status"],
        created_at=datetime.now(timezone.utc),
        websocket_url=f"ws://localhost:8000/ws/{job_id}"
    )


@app.get("/api/jobs/{job_id}")
async def get_job_status(job_id: str):
    """
    Retrieve job status and metadata.
    
    Returns the current status, progress, result, and error information
    for the specified job. Returns 404 if job does not exist.
    
    Requirements: 8.2, 8.5
    """
    async with job_queue_lock:
        if job_id not in job_queue:
            raise HTTPException(status_code=404, detail="Job not found")
        
        job_data = job_queue[job_id].copy()
    
    return job_data


@app.get("/api/jobs/{job_id}/script")
async def get_job_script(job_id: str):
    """
    Retrieve the TTS script for a job in Phase 2.5.
    """
    # Try in-memory first
    video_name = None
    async with job_queue_lock:
        if job_id in job_queue:
            video_name = job_queue[job_id].get("video_name")
    
    # If not in memory, try MongoDB
    if not video_name and Database.is_connected():
        from backend.crud.jobs import get_job
        job_doc = await get_job(job_id)
        if job_doc:
            video_name = job_doc.get("video_name")
    
    if not video_name:
        raise HTTPException(status_code=404, detail="Job not found or video_name missing")
        
    output_dir = resolve_output_dir()
    script_path = output_dir / video_name / "tts_script.json"
    
    if not script_path.exists():
        # Return empty script if no script yet
        return {"script": {"segments": [], "total_segments": 0, "review_status": "pending"}}
        
    try:
        import json
        with open(script_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        # data is either a list of segments or already a dict
        if isinstance(data, list):
            segments = [
                {
                    "id": f"seg_{i:03d}",
                    "text": seg.get("narration", seg.get("text", "")),
                    "timing": seg.get("duration", seg.get("timing")),
                    "action_type": seg.get("action_type", ""),
                }
                for i, seg in enumerate(data)
            ]
            return {
                "script": {
                    "segments": segments,
                    "total_segments": len(segments),
                    "reviewed_segments": 0,
                    "approved_segments": 0,
                    "review_status": "pending",
                }
            }
        else:
            # Already structured
            return {"script": data}
    except Exception as e:
        logger.error(f"Failed to read script: {e}")
        raise HTTPException(status_code=500, detail="Failed to read script")


# DEPRECATED: Old job endpoints without authentication
# These are replaced by /api/jobs routes with user isolation
# Kept for backward compatibility but should not be used

# @app.get("/api/jobs")
# async def list_jobs_old(status: Optional[str] = None, limit: int = 100):
#     """DEPRECATED: Use /api/jobs with authentication instead."""
#     async with job_queue_lock:
#         jobs = list(job_queue.values())
#     
#     if status:
#         jobs = [job for job in jobs if job["status"] == status]
#     
#     jobs.sort(key=lambda x: x["created_at"], reverse=True)
#     jobs = jobs[:limit]
#     
#     return {
#         "jobs": jobs,
#         "total": len(jobs)
#     }


@app.post("/api/jobs/{job_id}/review")
async def submit_review(job_id: str, request: dict):
    """
    Submit reviewed TTS script and resume pipeline execution.
    
    Args:
        job_id: UUID of the job
        request: Dictionary containing:
            - tts_script: list of reviewed narration segments
    
    Returns:
        dict: Confirmation message
    """
    # Get video_name from memory or MongoDB
    video_name = None
    async with job_queue_lock:
        if job_id in job_queue:
            job_data = job_queue[job_id]
            video_name = job_data.get("video_name")
            current_status = job_data.get("status")
        else:
            current_status = None
    
    # If not in memory, try MongoDB
    if not video_name and Database.is_connected():
        from backend.crud.jobs import get_job
        job_doc = await get_job(job_id)
        if job_doc:
            video_name = job_doc.get("video_name")
            current_status = job_doc.get("status")
    
    if not video_name:
        raise HTTPException(status_code=404, detail="Job not found")
    
    # Check if job is waiting for review (accept both pending_review and running)
    if current_status not in ["pending_review", "running"]:
        raise HTTPException(
            status_code=400,
            detail=f"Job is not waiting for review (status: {current_status})"
        )
    
    # Get reviewed script
    tts_script = request.get("tts_script", [])
    if not tts_script:
        raise HTTPException(status_code=400, detail="tts_script is required")
    
    logger.info(
        f"Job {job_id}: Received reviewed TTS script with {len(tts_script)} segments",
        extra={"job_id": job_id, "segment_count": len(tts_script)}
    )
    
    # Save reviewed script back to file (overwrite original)
    output_dir = resolve_output_dir()
    script_path = output_dir / video_name / "tts_script.json"
    
    try:
        import json
        # Convert to the format worker expects (list of dicts with 'text' and 'narration')
        script_data = [
            {
                "text": seg.get("text", seg.get("narration", "")),
                "narration": seg.get("text", seg.get("narration", "")),
                "narration_index": i,
                "duration": seg.get("timing"),
                "action_type": seg.get("action_type", ""),
                "edited": seg.get("edited", False),
                "approved": seg.get("approved", True),
            }
            for i, seg in enumerate(tts_script)
        ]
        
        with open(script_path, "w", encoding="utf-8") as f:
            json.dump(script_data, f, ensure_ascii=False, indent=2)
        
        logger.info(f"Job {job_id}: Saved reviewed script to {script_path}")
    except Exception as e:
        logger.error(f"Failed to save reviewed script: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to save script: {str(e)}")
    
    # Submit review via Redis Pub/Sub to unblock worker
    try:
        redis_queue.submit_review(job_id, tts_script)
        logger.info(f"Job {job_id}: Review submitted to Redis, unblocking worker")
        
        # Update status in memory and MongoDB
        async with job_queue_lock:
            if job_id in job_queue:
                job_queue[job_id]["status"] = "running"
        
        if Database.is_connected():
            from backend.crud.jobs import update_job
            await update_job(job_id, {"status": "running"})
        
        await broadcast_progress(job_id)
        
        return {
            "job_id": job_id,
            "message": "Review submitted, pipeline resumed",
            "segment_count": len(tts_script)
        }
    
    except Exception as e:
        logger.error(f"Failed to resume pipeline: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to resume pipeline: {str(e)}")


@app.delete("/api/jobs/{job_id}")
async def cancel_job(job_id: str):
    """
    Cancel a running job immediately.
    
    For jobs running on Docker workers (queued/running via Redis):
      - Publishes a job-kill event to Redis Pub/Sub.
      - The autoscaler picks up the event and stops the worker container.
    
    For jobs running directly (asyncio tasks on the API server):
      - Cancels the asyncio task immediately.
    
    Returns:
        dict: Updated job status
    """
    async with job_queue_lock:
        if job_id not in job_queue:
            raise HTTPException(status_code=404, detail="Job not found")
        
        job_data = job_queue[job_id]
        current_status = job_data["status"]
        
        # Allow cancelling pending, queued, running, and pending_review jobs
        if current_status not in ["pending", "queued", "running", "pending_review"]:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot cancel job with status: {current_status}"
            )
        
        # Update job status
        job_data["status"] = "cancelled"
        job_data["error"] = "Job cancelled by user (force killed)"
        job_data["completed_at"] = datetime.now(timezone.utc).isoformat()
    
    logger.info(
        f"Job {job_id}: Force cancellation requested",
        extra={"job_id": job_id, "previous_status": current_status}
    )
    
    # Kill the asyncio task immediately (for direct-execution jobs)
    async with job_tasks_lock:
        if job_id in job_tasks:
            task = job_tasks[job_id]
            if not task.done():
                task.cancel()
                logger.info(f"Job {job_id}: Asyncio task cancelled (force kill)")
            # Remove task reference
            del job_tasks[job_id]
    
    # For jobs routed to Redis workers: publish kill event to autoscaler
    if redis_queue.redis:
        import json as _json
        redis_queue.redis.publish(
            "job-kill",
            _json.dumps({"job_id": job_id}),
        )
        logger.info(f"Job {job_id}: Published job-kill event to autoscaler")
        
        # Also remove from queue if still queued (not yet picked up by worker)
        job_environment = job_data.get("environment", "")
        queue_mapping = {
            "os": "os-queue",
            "presentation": "presentation-queue",
        }
        queue_name = queue_mapping.get(job_environment)
        job_type = job_data.get("job_type", "")
        if job_type == "presentation_gg":
            queue_name = "presentation-gg-queue"
        elif job_type == "presentation":
            queue_name = "presentation-queue"
        
        if queue_name and current_status == "queued":
            # Try to remove from the waiting queue
            try:
                payload = _json.dumps(job_data, ensure_ascii=False, default=str)
                removed = redis_queue.redis.lrem(queue_name, 0, payload)
                if removed:
                    logger.info(f"Job {job_id}: Removed from {queue_name}")
            except Exception as e:
                logger.warning(f"Failed to remove job from queue: {e}")
    
    # Persist cancellation to MongoDB
    if Database.is_connected():
        from backend.crud.jobs import update_job
        await update_job(job_id, {
            "status": "cancelled",
            "error": "Job cancelled by user (force killed)",
            "completed_at": datetime.now(timezone.utc),
        })
    
    # Broadcast cancellation to WebSocket clients
    await broadcast_progress(job_id)
    
    # Also set stop flag as backup (in case task checks it)
    try:
        import sys
        from pathlib import Path
        agent_dir = Path(__file__).parent.parent
        sys.path.insert(0, str(agent_dir))
        from run_pipeline import set_stop_flag
        set_stop_flag(job_id, True)
    except Exception as e:
        logger.warning(f"Failed to set stop flag: {e}")
    
    return {
        "job_id": job_id,
        "status": "cancelled",
        "message": "Job force killed immediately"
    }



@app.get("/api/jobs/{job_id}/video")
async def download_video(job_id: str):
    """
    Download the generated video file.
    
    For R2-hosted videos: proxies the download server-side to avoid CORS issues.
    The browser's fetch() with Authorization header cannot follow a 302 redirect
    to a different domain (R2 CDN) without triggering CORS blocks. By proxying
    through the backend, the frontend only talks to its own origin.
    
    For local videos: returns the file directly via FileResponse.
    
    Requirements: 8.4, 8.5
    """
    job_data = None
    async with job_queue_lock:
        if job_id in job_queue:
            job_data = job_queue[job_id]
            
    if not job_data:
        from backend.crud.jobs import get_job
        job_data = await get_job(job_id)
        
    if not job_data:
        raise HTTPException(status_code=404, detail="Job not found")
    
    # Check if job is completed
    if job_data["status"] != "completed":
        raise HTTPException(
            status_code=404,
            detail=f"Video not available. Job status: {job_data['status']}"
        )
    
    # Check if result exists
    if not job_data.get("result"):
        raise HTTPException(status_code=404, detail="Video result not found")
    
    video_url = job_data["result"].get("video_url")
    video_path_str = job_data["result"].get("video_path")
    
    # If video is hosted on R2 CDN, proxy the download server-side
    if video_url and video_url.startswith("http"):
        import httpx
        from fastapi.responses import StreamingResponse
        
        # Extract filename from URL or use job_id
        url_filename = video_url.rsplit("/", 1)[-1] if "/" in video_url else f"{job_id}.mp4"
        
        try:
            async with httpx.AsyncClient(timeout=300.0, follow_redirects=True) as client:
                r2_response = await client.get(video_url)
                
                if r2_response.status_code != 200:
                    logger.error(f"R2 proxy failed: {r2_response.status_code} for {video_url}")
                    raise HTTPException(
                        status_code=502,
                        detail=f"Failed to fetch video from storage (status {r2_response.status_code})"
                    )
                
                # Stream the R2 response content to the client
                content_length = r2_response.headers.get("content-length")
                headers = {
                    "Content-Disposition": f'attachment; filename="{url_filename}"',
                }
                if content_length:
                    headers["Content-Length"] = content_length
                
                return StreamingResponse(
                    content=iter([r2_response.content]),
                    media_type="video/mp4",
                    headers=headers,
                )
        except httpx.TimeoutException:
            logger.error(f"R2 proxy timeout for {video_url}")
            raise HTTPException(status_code=504, detail="Timeout fetching video from storage")
        except httpx.RequestError as e:
            logger.error(f"R2 proxy request error: {e}")
            raise HTTPException(status_code=502, detail="Failed to connect to video storage")
    
    # Fallback to local file if not external
    if not video_path_str:
        raise HTTPException(status_code=404, detail="Video file path not found")
        
    video_path = Path(video_path_str)
    
    # Check if file exists
    if not video_path.exists():
        raise HTTPException(status_code=404, detail="Video file not found on disk (may have been uploaded to R2 and deleted locally)")
    
    # Return file with download header
    return FileResponse(
        path=video_path,
        media_type="video/mp4",
        filename=video_path.name,
        headers={"Content-Disposition": f'attachment; filename="{video_path.name}"'}
    )


@app.post("/api/upload-pptx")
async def upload_pptx(
    file: UploadFile,
    task: str = "Create a lecture video explaining each slide",
    tts_voice: str = "vi-VN-HoaiMyNeural",
    tts_engine: str = "edge",
    padding_ms: int = 500,
    language: str = "Vietnamese",
    enable_review: bool = True,
    user: dict = Depends(get_current_user),
):
    """Upload a PPTX/PDF file and start the Slide-to-Video pipeline.
    
    Requires: Authorization header with Bearer token.
    
    Flow:
      1. Receives .pptx or .pdf file
      2. Saves to output directory
      3. Submits job to presentation-queue
      4. Saves job record to MongoDB
      5. Returns job_id + websocket URL for tracking
    """
    if not file.filename or not file.filename.lower().endswith((".pptx", ".ppt", ".pdf")):
        raise HTTPException(status_code=400, detail="Only .pptx, .ppt, or .pdf files are accepted")
    
    # Read file content
    content = await file.read()
    if len(content) > 100 * 1024 * 1024:  # 100MB limit
        raise HTTPException(status_code=400, detail="File too large. Maximum 100MB.")
    
    # Generate job ID and video name
    job_id = str(uuid4())
    safe_filename = sanitize_filename(file.filename)
    video_name = f"slide_{Path(safe_filename).stem}_{job_id[:8]}"
    
    # Save file to output directory
    import os
    output_dir = resolve_output_dir()
    upload_dir = output_dir / video_name / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    
    file_path = upload_dir / safe_filename
    with open(file_path, "wb") as f:
        f.write(content)
    
    logger.info(f"PPTX uploaded: {safe_filename} ({len(content)} bytes) -> {file_path}")
    
    # Extract user info from token
    user_id = user["user_id"]
    user_email = user["email"]
    
    # Submit to presentation-queue
    job_data = {
        "job_id": job_id,
        "video_name": video_name,
        "config": {
            "pptx_path": str(file_path),
            "task": task,
            "tts_voice": tts_voice,
            "tts_engine": tts_engine,
            "padding_ms": padding_ms,
            "language": language,
            "enable_review": enable_review,
        },
        "job_type": "presentation",
        "user_id": user_id,
        "user_email": user_email,
    }
    
    redis_queue.push("presentation-queue", job_data)
    
    # Build job entry for both RAM and MongoDB
    job_entry = {
        "job_id": job_id,
        "status": "queued",
        "task": task,
        "video_name": video_name,
        "config": job_data["config"],
        "job_type": "presentation",
        "queue": "presentation-queue",
        "user_id": user_id,
        "user_email": user_email,
        "progress": None,
        "result": None,
        "error": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "started_at": None,
        "completed_at": None,
    }
    async with job_queue_lock:
        job_queue[job_id] = job_entry
    
    # Persist to MongoDB so frontend can see it
    if Database.is_connected():
        from backend.crud.jobs import create_job
        await create_job(job_entry)
        
    logger.info(f"Submitted to presentation-queue: {job_id} (user: {user_email})")
    
    return {
        "job_id": job_id,
        "video_name": video_name,
        "status": "queued",
        "file_name": file.filename,
        "file_size": len(content),
        "ws_url": f"/ws/{job_id}",
        "result_url": f"/api/queue/result/{job_id}",
    }


@app.post("/api/upload-pptx-gg")
async def upload_pptx_gg(
    file: UploadFile,
    task: str = "Create a lecture video explaining each slide",
    tts_voice: str = "vi-VN-HoaiMyNeural",
    tts_engine: str = "edge",
    padding_ms: int = 500,
    language: str = "Vietnamese",
    enable_review: bool = True,
    user: dict = Depends(get_current_user),
):
    """Upload a PPTX file and start the Google Slides pipeline.
    
    Requires: Authorization header with Bearer token.
    
    Flow:
      1. Receives .pptx or .ppt file
      2. Saves to output directory
      3. Submits job to presentation-gg-queue (Google Drive + Google Slides)
      4. Saves job record to MongoDB
      5. Returns job_id + websocket URL for tracking
    
    Differences from /api/upload-pptx:
      - Uses Google Drive OAuth instead of OneDrive Graph API
      - Converts to Google Slides (native format)
      - Uses /present URL for auto-start presentation mode
      - Optimized prompt for Google Slides navigation
    """
    if not file.filename or not file.filename.lower().endswith((".pptx", ".ppt")):
        raise HTTPException(status_code=400, detail="Only .pptx or .ppt files are accepted")
    
    # Read file content
    content = await file.read()
    if len(content) > 100 * 1024 * 1024:  # 100MB limit
        raise HTTPException(status_code=400, detail="File too large. Maximum 100MB.")
    
    # Generate job ID and video name
    job_id = str(uuid4())
    safe_filename = sanitize_filename(file.filename)
    video_name = f"slide_gg_{Path(safe_filename).stem}_{job_id[:8]}"
    
    # Save file to output directory
    import os
    output_dir = resolve_output_dir()
    upload_dir = output_dir / video_name / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    
    file_path = upload_dir / safe_filename
    with open(file_path, "wb") as f:
        f.write(content)
    
    logger.info(f"PPTX uploaded for Google Slides: {safe_filename} ({len(content)} bytes) -> {file_path}")
    
    # Extract user info from token
    user_id = user["user_id"]
    user_email = user["email"]
    
    # Submit to presentation-gg-queue
    job_data = {
        "job_id": job_id,
        "video_name": video_name,
        "config": {
            "pptx_path": str(file_path),
            "task": task,
            "tts_voice": tts_voice,
            "tts_engine": tts_engine,
            "padding_ms": padding_ms,
            "language": language,
            "enable_review": enable_review,
        },
        "job_type": "presentation_gg",
        "user_id": user_id,
        "user_email": user_email,
    }
    
    redis_queue.push("presentation-gg-queue", job_data)
    
    # Build job entry for both RAM and MongoDB
    job_entry = {
        "job_id": job_id,
        "status": "queued",
        "task": task,
        "video_name": video_name,
        "config": job_data["config"],
        "job_type": "presentation_gg",
        "queue": "presentation-gg-queue",
        "user_id": user_id,
        "user_email": user_email,
        "progress": None,
        "result": None,
        "error": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "started_at": None,
        "completed_at": None,
    }
    async with job_queue_lock:
        job_queue[job_id] = job_entry
    
    # Persist to MongoDB so frontend can see it
    if Database.is_connected():
        from backend.crud.jobs import create_job
        await create_job(job_entry)
        
    logger.info(f"Submitted to presentation-gg-queue: {job_id} (user: {user_email})")
    
    return {
        "job_id": job_id,
        "video_name": video_name,
        "status": "queued",
        "file_name": file.filename,
        "file_size": len(content),
        "ws_url": f"/ws/{job_id}",
        "result_url": f"/api/queue/result/{job_id}",
        "platform": "google_slides",
    }


@app.get("/health")
async def health_check():
    """
    Health check endpoint with job statistics, queue stats, and shutdown status.
    """
    async with job_queue_lock:
        job_stats = {
            "pending": sum(1 for job in job_queue.values() if job["status"] == "pending"),
            "running": sum(1 for job in job_queue.values() if job["status"] == "running"),
            "completed": sum(1 for job in job_queue.values() if job["status"] == "completed"),
            "failed": sum(1 for job in job_queue.values() if job["status"] == "failed"),
        }
    
    # Redis queue stats
    queue_stats = redis_queue.get_all_queue_stats() if redis_queue.redis else {}
    
    return {
        "status": "healthy",
        "version": "2.0.0",
        "jobs": job_stats,
        "queues": queue_stats,
        "redis_connected": redis_queue.redis is not None,
        "is_shutting_down": shutdown_handler.is_shutting_down,
        "active_tasks": shutdown_handler.active_task_count
    }


@app.post("/api/admin/reset-shutdown")
async def reset_shutdown_flag():
    """
    Reset the shutdown flag (for debugging/recovery after uvicorn reload).
    
    This endpoint allows manually resetting the is_shutting_down flag
    in case it gets stuck after a uvicorn reload or false signal.
    """
    old_value = shutdown_handler.is_shutting_down
    shutdown_handler.is_shutting_down = False
    
    logger.warning(
        f"Shutdown flag manually reset from {old_value} to False",
        extra={"old_value": old_value, "new_value": False}
    )
    
    return {
        "message": "Shutdown flag reset successfully",
        "old_value": old_value,
        "new_value": False
    }


# =========================================================================
# Queue-based endpoints (production mode with Redis workers)
# =========================================================================

class QueueJobRequest(BaseModel):
    """Request model for queue-based job submission."""
    task: str
    video_name: str = ""
    job_type: str = "web"  # "web", "office", "os", "presentation"
    config: dict = {}
    # user_id and user_email are auto-extracted from JWT token


@app.post("/api/queue/submit")
@limiter.limit("10/minute")
async def submit_queue_job(request: Request, job_req: QueueJobRequest, user: dict = Depends(get_current_user)):
    """Submit a job to Redis queue for worker processing.
    
    Requires: Authorization header with Bearer token
    
    Routes to the correct queue based on job_type:
      - web -> web-queue (Linux Docker worker)
      - office -> office-queue (Linux Docker worker)
      - os -> os-queue (Windows worker)
      - presentation -> presentation-queue (PowerPoint worker)
    """
    if not redis_queue.redis:
        raise HTTPException(status_code=503, detail="Redis not available. Use /api/jobs for direct execution.")
    
    # Check user quota
    from backend.crud.users import check_quota, increment_quota_usage
    
    if not await check_quota(user["user_id"]):
        quota = user.get("quota", {})
        limit = quota.get("videos_per_month", 100)
        raise HTTPException(
            status_code=429,
            detail=f"Monthly quota exceeded ({limit} videos/month). Your quota will reset on {quota.get('reset_date')}."
        )
    
    queue_map = {
        "web": "web-queue",
        "office": "office-queue",
        "os": "os-queue",
        "presentation": "presentation-queue",
        "presentation_gg": "presentation-gg-queue",
    }
    queue_name = queue_map.get(job_req.job_type)
    if not queue_name:
        raise HTTPException(status_code=400, detail=f"Invalid job_type: {job_req.job_type}. Must be web, office, os, presentation, or presentation_gg.")
    
    import time as _time
    job_id = str(uuid4())
    video_name = job_req.video_name or f"video_{int(_time.time())}"
    
    # Auto-extract user info from token (no need for client to send)
    user_id = user["user_id"]
    user_email = user["email"]
    
    # Push to Redis queue
    redis_queue.push(queue_name, {
        "job_id": job_id,
        "task": job_req.task,
        "video_name": video_name,
        "config": job_req.config,
        "job_type": job_req.job_type,
        "user_id": user_id,
        "user_email": user_email,
    })
    
    # Also track in memory for status queries
    job_entry = {
        "job_id": job_id,
        "status": "queued",
        "task": job_req.task,
        "video_name": video_name,
        "config": job_req.config,
        "job_type": job_req.job_type,
        "queue": queue_name,
        "user_id": user_id,
        "user_email": user_email,
        "progress": None,
        "result": None,
        "error": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "started_at": None,
        "completed_at": None,
    }
    async with job_queue_lock:
        job_queue[job_id] = job_entry
    
    # Save to MongoDB
    if Database.is_connected():
        from backend.crud.jobs import create_job
        await create_job(job_entry)
    
    # Increment quota usage
    await increment_quota_usage(user_id)
    
    logger.info(f"Queue job submitted: {job_id} -> {queue_name} (user: {user_email})")
    
    return {
        "job_id": job_id,
        "queue": queue_name,
        "status": "queued",
        "websocket_url": f"ws://localhost:8000/ws/{job_id}",
    }


@app.get("/api/queue/stats")
async def get_queue_stats():
    """Get current queue lengths and worker status."""
    if not redis_queue.redis:
        return {"error": "Redis not connected", "queues": {}}
    
    return {
        "queues": redis_queue.get_all_queue_stats(),
        "redis_connected": True,
    }


@app.get("/api/queue/result/{job_id}")
async def get_queue_result(job_id: str):
    """Get result of a queue-processed job directly from Redis."""
    # Check in-memory first
    async with job_queue_lock:
        if job_id in job_queue:
            return job_queue[job_id]
    
    # Check Redis
    if redis_queue.redis:
        result = redis_queue.get_result(job_id)
        status = redis_queue.get_status(job_id)
        if result or status:
            return {
                "job_id": job_id,
                "status": status or "unknown",
                "result": result,
            }
    
    raise HTTPException(status_code=404, detail="Job not found")


@app.websocket("/ws/{job_id}")
async def websocket_endpoint(websocket: WebSocket, job_id: str):
    """
    WebSocket endpoint for real-time job progress updates.
    
    Accepts WebSocket connections for a specific job_id, sends initial job status,
    and keeps the connection alive to receive progress updates. Handles disconnections
    gracefully.
    
    Requirements: 4.1, 4.2, 4.5, 4.6, 9.3
    """
    # Connect the WebSocket
    await manager.connect(job_id, websocket)
    
    try:
        # Send initial job status
        async with job_queue_lock:
            if job_id in job_queue:
                initial_status = job_queue[job_id].copy()
                await websocket.send_json(initial_status)
                logger.info(f"WebSocket connection established for job {job_id}")
            else:
                # Job not found, send error and close
                logger.warning(f"WebSocket connection attempted for non-existent job {job_id}")
                await websocket.send_json({
                    "error": "Job not found",
                    "job_id": job_id
                })
                await manager.disconnect(job_id, websocket)
                return
        
        # Keep connection alive and handle ping/pong
        while True:
            # Wait for messages from client (ping/pong or close)
            data = await websocket.receive_text()
            
            # Echo back for ping/pong
            if data == "ping":
                await websocket.send_text("pong")
    
    except WebSocketDisconnect:
        # Client disconnected, clean up
        logger.info(f"WebSocket client disconnected for job {job_id}")
        await manager.disconnect(job_id, websocket)
    
    except Exception as e:
        # Handle other errors gracefully
        logger.error(
            f"WebSocket error for job {job_id}: {e}",
            extra={"job_id": job_id},
            exc_info=True
        )
        await manager.disconnect(job_id, websocket)


# Mount frontend static files LAST (after all API routes)
# This ensures API routes take precedence over static file serving
frontend_dir = Path(__file__).parent.parent / "frontend_web"
if frontend_dir.exists():
    app.mount("/", StaticFiles(directory=str(frontend_dir), html=True), name="frontend")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        timeout_keep_alive=300,
        reload=True
    )
