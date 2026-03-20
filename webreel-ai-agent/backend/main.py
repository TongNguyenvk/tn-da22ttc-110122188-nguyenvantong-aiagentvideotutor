"""
FastAPI Backend for Webreel Video Generation
Provides REST API endpoints and WebSocket support for asynchronous video generation.
"""

from fastapi import FastAPI, HTTPException, BackgroundTasks, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from contextlib import asynccontextmanager
import asyncio
import logging
from pathlib import Path
from datetime import datetime, timezone
from uuid import uuid4
from typing import Optional

from backend.models import (
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
from backend.middleware import RequestLoggingMiddleware
from backend.shutdown import ShutdownHandler

# Setup structured logging
setup_logging()
logger = logging.getLogger(__name__)

# Global job queue with asyncio lock
job_queue: dict[str, dict] = {}
job_queue_lock = asyncio.Lock()

# Initialize shutdown handler
shutdown_handler = ShutdownHandler(
    job_queue=job_queue,
    job_queue_lock=job_queue_lock,
    connection_manager=manager
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan event handler.
    
    Handles startup and shutdown events for the FastAPI application.
    
    Requirements: 10.1, 10.5
    """
    # Startup
    shutdown_handler.register_signal_handlers()
    await shutdown_handler.load_job_queue()
    logger.info("FastAPI backend started successfully")
    
    yield
    
    # Shutdown (if needed, though signal handlers handle most cases)
    logger.info("FastAPI backend shutting down")


app = FastAPI(
    title="Webreel Video Generation API",
    description="Asynchronous video generation backend with real-time progress updates",
    version="1.0.0",
    lifespan=lifespan
)

# Add request logging middleware
app.add_middleware(RequestLoggingMiddleware)

# CORS configuration for Streamlit frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8501"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static file serving for video downloads
output_dir = Path(__file__).parent.parent / "output"
output_dir.mkdir(exist_ok=True)
app.mount("/videos", StaticFiles(directory=str(output_dir)), name="videos")


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
    
    Requirements: 10.2
    """
    try:
        # Increment active task counter
        await shutdown_handler.increment_active_tasks()
        
        # Execute the pipeline task
        await execute_pipeline_task(
            job_id=job_id,
            task=task,
            video_name=video_name,
            config=config,
            update_job_status_func=update_job_status,
            broadcast_progress_func=broadcast_progress
        )
    finally:
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
    
    Creates a new job entry in the queue with pending status, spawns a background
    task to execute the pipeline, and returns the job_id and websocket_url for
    progress tracking.
    
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
    
    logger.info(
        f"Job submitted: {job_id}",
        extra={
            "job_id": job_id,
            "task": request.task[:100],  # Truncate long tasks
            "video_name": request.video_name
        }
    )
    
    # Initialize job entry
    job_entry = {
        "job_id": job_id,
        "status": "pending",
        "task": request.task,
        "video_name": request.video_name,
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
    
    # Spawn background task to execute pipeline with tracking
    background_tasks.add_task(
        execute_pipeline_with_tracking,
        job_id=job_id,
        task=request.task,
        video_name=request.video_name,
        config=request.config.model_dump()
    )
    
    # Return response with websocket URL
    return JobSubmitResponse(
        job_id=job_id,
        status="pending",
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


@app.get("/api/jobs")
async def list_jobs(status: Optional[str] = None, limit: int = 100):
    """
    List all jobs with optional status filtering and pagination.
    
    Returns jobs sorted by created_at timestamp in descending order.
    Supports filtering by status and limiting the number of results.
    
    Requirements: 8.3
    """
    async with job_queue_lock:
        jobs = list(job_queue.values())
    
    # Filter by status if provided
    if status:
        jobs = [job for job in jobs if job["status"] == status]
    
    # Sort by created_at (newest first)
    jobs.sort(key=lambda x: x["created_at"], reverse=True)
    
    # Apply limit
    jobs = jobs[:limit]
    
    return {
        "jobs": jobs,
        "total": len(jobs)
    }


@app.get("/api/jobs/{job_id}/video")
async def download_video(job_id: str):
    """
    Download the generated video file.
    
    Returns the video file with appropriate Content-Disposition header
    for download. Returns 404 if job is not completed or video file is missing.
    
    Requirements: 8.4, 8.5
    """
    async with job_queue_lock:
        if job_id not in job_queue:
            raise HTTPException(status_code=404, detail="Job not found")
        
        job_data = job_queue[job_id]
    
    # Check if job is completed
    if job_data["status"] != "completed":
        raise HTTPException(
            status_code=404,
            detail=f"Video not available. Job status: {job_data['status']}"
        )
    
    # Check if result exists
    if not job_data.get("result") or not job_data["result"].get("video_path"):
        raise HTTPException(status_code=404, detail="Video file path not found")
    
    # Get video file path
    video_path = Path(job_data["result"]["video_path"])
    
    # Check if file exists
    if not video_path.exists():
        raise HTTPException(status_code=404, detail="Video file not found on disk")
    
    # Return file with download header
    return FileResponse(
        path=video_path,
        media_type="video/mp4",
        filename=video_path.name,
        headers={"Content-Disposition": f'attachment; filename="{video_path.name}"'}
    )


@app.get("/health")
async def health_check():
    """
    Health check endpoint with job statistics.
    
    Returns API status, version, and counts of jobs by status.
    
    Requirements: 1.1
    """
    async with job_queue_lock:
        job_stats = {
            "pending": sum(1 for job in job_queue.values() if job["status"] == "pending"),
            "running": sum(1 for job in job_queue.values() if job["status"] == "running"),
            "completed": sum(1 for job in job_queue.values() if job["status"] == "completed"),
            "failed": sum(1 for job in job_queue.values() if job["status"] == "failed"),
        }
    
    return {
        "status": "healthy",
        "version": "1.0.0",
        "jobs": job_stats
    }


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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        timeout_keep_alive=300,
        reload=True
    )
