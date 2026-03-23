"""
Background task executor for video generation pipeline.
Handles asynchronous execution of the 6-phase pipeline with progress tracking.
"""

import sys
from pathlib import Path
from datetime import datetime, timezone
import logging

# Setup paths to import pipeline modules
BACKEND_DIR = Path(__file__).parent
AGENT_DIR = BACKEND_DIR.parent
sys.path.insert(0, str(AGENT_DIR))

from run_pipeline import run_pipeline_v3

logger = logging.getLogger(__name__)


# Phase names for progress updates
PHASE_NAMES = {
    1: "Scout",
    2: "Parser",
    3: "TTS",
    4: "Injector",
    5: "Execution",
    6: "Composer"
}


async def execute_pipeline_task(
    job_id: str,
    task: str,
    video_name: str,
    config: dict,
    update_job_status_func,
    broadcast_progress_func=None
):
    """
    Execute the video generation pipeline as a background task.
    
    This function runs the 6-phase pipeline asynchronously, updating job status
    and broadcasting progress updates via WebSocket connections.
    
    Args:
        job_id: Unique identifier for the job
        task: Task description for the pipeline
        video_name: Output video name
        config: Pipeline configuration dictionary
        update_job_status_func: Async function to update job status in queue
        broadcast_progress_func: Optional async function to broadcast progress via WebSocket
    
    Requirements: 3.1, 3.3, 3.4, 3.5, 9.1, 9.5
    """
    try:
        # Update job status to running
        await update_job_status_func(job_id, {
            "status": "running",
            "started_at": datetime.now(timezone.utc).isoformat()
        })
        
        logger.info(
            f"Job {job_id}: Starting pipeline execution",
            extra={"job_id": job_id, "video_name": video_name}
        )
        
        # Log status transition
        logger.info(
            f"Job {job_id}: Status transition: pending -> running",
            extra={"job_id": job_id, "status": "running"}
        )
        
        # Create progress callback for pipeline
        async def progress_callback(phase: int, message: str):
            """Callback function called by pipeline at each phase."""
            phase_name = PHASE_NAMES.get(phase, f"Phase {phase}")
            
            # Update job progress
            await update_job_status_func(job_id, {
                "progress": {
                    "current_phase": phase,
                    "phase_name": phase_name,
                    "message": message,
                    "logs": []
                }
            })
            
            logger.info(
                f"Job {job_id}: Phase {phase} ({phase_name}) - {message}",
                extra={
                    "job_id": job_id,
                    "phase": phase,
                    "phase_name": phase_name,
                    "progress_message": message
                }
            )
            
            # Broadcast progress update via WebSocket if available
            if broadcast_progress_func:
                await broadcast_progress_func(job_id)
        
        # Execute pipeline with progress callback
        # NOTE: enable_review is always False for web UI (CLI-only feature)
        video_path = await run_pipeline_v3(
            task=task,
            video_name=video_name,
            cdp_url=config.get("cdp_url", "http://localhost:9222"),
            enable_tts=config.get("enable_tts", True),
            tts_voice=config.get("tts_voice", "banmai"),
            tts_engine=config.get("tts_engine", "fpt"),
            padding_ms=config.get("padding_ms", 300),
            enable_review=False,
            progress_callback=progress_callback
        )
        
        # Update job status to completed with result
        video_url = f"/videos/{video_name}/{video_path.name}"
        await update_job_status_func(job_id, {
            "status": "completed",
            "result": {
                "video_path": str(video_path),
                "video_url": video_url,
                "duration_seconds": None  # Could be calculated if needed
            },
            "completed_at": datetime.now(timezone.utc).isoformat()
        })
        
        logger.info(
            f"Job {job_id}: Pipeline completed successfully",
            extra={
                "job_id": job_id,
                "video_path": str(video_path),
                "video_url": video_url
            }
        )
        
        # Log status transition
        logger.info(
            f"Job {job_id}: Status transition: running -> completed",
            extra={"job_id": job_id, "status": "completed"}
        )
        
        # Send final completion broadcast
        if broadcast_progress_func:
            await broadcast_progress_func(job_id)
        
    except Exception as e:
        # Update job status to failed with error message
        error_message = str(e)
        
        # Get current phase if available for better error context
        import traceback
        stack_trace = traceback.format_exc()
        
        logger.error(
            f"Job {job_id}: Pipeline failed with error: {error_message}",
            extra={
                "job_id": job_id,
                "error": error_message,
                "timestamp": datetime.now(timezone.utc).isoformat()
            },
            exc_info=True
        )
        
        # Log status transition
        logger.error(
            f"Job {job_id}: Status transition: running -> failed",
            extra={"job_id": job_id, "status": "failed", "error": error_message}
        )
        
        await update_job_status_func(job_id, {
            "status": "failed",
            "error": error_message,
            "completed_at": datetime.now(timezone.utc).isoformat()
        })
        
        # Send final failure broadcast
        if broadcast_progress_func:
            await broadcast_progress_func(job_id)
