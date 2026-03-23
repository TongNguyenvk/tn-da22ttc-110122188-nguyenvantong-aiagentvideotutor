"""
Graceful shutdown handler for FastAPI backend.
Handles SIGTERM and SIGINT signals, waits for background tasks, and persists state.
"""

import signal
import asyncio
import json
import logging
from pathlib import Path
from datetime import datetime, timezone
from typing import Callable, Optional

logger = logging.getLogger(__name__)


class ShutdownHandler:
    """
    Manages graceful shutdown of the FastAPI backend.
    
    Responsibilities:
    - Register signal handlers for SIGTERM and SIGINT
    - Track active background tasks
    - Stop accepting new job submissions during shutdown
    - Wait for running tasks to complete (up to 30 seconds)
    - Update interrupted jobs and close WebSocket connections
    - Persist job queue state to disk
    
    Requirements: 10.1, 10.2, 10.3, 10.4, 10.5
    """
    
    def __init__(
        self,
        job_queue: dict,
        job_queue_lock: asyncio.Lock,
        connection_manager,
        state_file: Path = None
    ):
        """
        Initialize the shutdown handler.
        
        Args:
            job_queue: Reference to the in-memory job queue dictionary
            job_queue_lock: Asyncio lock for thread-safe job queue access
            connection_manager: WebSocket connection manager instance
            state_file: Path to persist job queue state (default: backend/job_queue_state.json)
        """
        self.job_queue = job_queue
        self.job_queue_lock = job_queue_lock
        self.connection_manager = connection_manager
        self.state_file = state_file or Path(__file__).parent / "job_queue_state.json"
        
        # Shutdown state
        self.is_shutting_down = False
        self.active_task_count = 0
        self.task_count_lock = asyncio.Lock()
        
        # Shutdown timeout (30 seconds)
        self.shutdown_timeout = 30
    
    def register_signal_handlers(self):
        """
        Register SIGTERM and SIGINT signal handlers.
        
        Note: Signal handlers can only be registered in the main thread.
        This method will silently skip registration if called from a non-main thread
        (e.g., during testing with TestClient).
        
        Requirements: 10.1
        """
        try:
            signal.signal(signal.SIGTERM, self._signal_handler)
            signal.signal(signal.SIGINT, self._signal_handler)
            logger.info("Registered shutdown signal handlers (SIGTERM, SIGINT)")
        except ValueError as e:
            # Signal handlers can only be registered in the main thread
            # This is expected during testing with TestClient
            logger.debug(f"Could not register signal handlers: {e}")
    
    def _signal_handler(self, signum, frame):
        """
        Signal handler that triggers graceful shutdown.
        
        Args:
            signum: Signal number
            frame: Current stack frame
        """
        signal_name = "SIGTERM" if signum == signal.SIGTERM else "SIGINT"
        logger.warning(f"Received {signal_name} signal, initiating graceful shutdown")
        
        # Set shutdown flag
        self.is_shutting_down = True
        
        # Create shutdown task
        asyncio.create_task(self.shutdown())
    
    def is_accepting_jobs(self) -> bool:
        """
        Check if the server is accepting new job submissions.
        
        Returns:
            False if shutting down, True otherwise
            
        Requirements: 10.1
        """
        return not self.is_shutting_down
    
    async def increment_active_tasks(self):
        """
        Increment the active background task counter.
        
        Should be called when a background task starts execution.
        
        Requirements: 10.2
        """
        async with self.task_count_lock:
            self.active_task_count += 1
            logger.debug(f"Active tasks: {self.active_task_count}")
    
    async def decrement_active_tasks(self):
        """
        Decrement the active background task counter.
        
        Should be called when a background task completes (success or failure).
        
        Requirements: 10.2
        """
        async with self.task_count_lock:
            self.active_task_count = max(0, self.active_task_count - 1)
            logger.debug(f"Active tasks: {self.active_task_count}")
    
    async def wait_for_tasks(self) -> bool:
        """
        Wait for active background tasks to complete.
        
        Waits up to 30 seconds for all active tasks to finish.
        
        Returns:
            True if all tasks completed, False if timeout reached
            
        Requirements: 10.2
        """
        logger.info(f"Waiting for {self.active_task_count} active tasks to complete (timeout: {self.shutdown_timeout}s)")
        
        start_time = asyncio.get_event_loop().time()
        
        while True:
            async with self.task_count_lock:
                if self.active_task_count == 0:
                    logger.info("All background tasks completed successfully")
                    return True
            
            # Check timeout
            elapsed = asyncio.get_event_loop().time() - start_time
            if elapsed >= self.shutdown_timeout:
                async with self.task_count_lock:
                    remaining = self.active_task_count
                logger.warning(f"Shutdown timeout reached. {remaining} tasks still running")
                return False
            
            # Wait a bit before checking again
            await asyncio.sleep(0.5)
    
    async def update_interrupted_jobs(self):
        """
        Update status of running jobs to "interrupted".
        
        Called when shutdown timeout is reached and tasks are still running.
        
        Requirements: 10.3
        """
        interrupted_count = 0
        
        async with self.job_queue_lock:
            for job_id, job_data in self.job_queue.items():
                if job_data["status"] == "running":
                    job_data["status"] = "interrupted"
                    job_data["completed_at"] = datetime.now(timezone.utc).isoformat()
                    job_data["error"] = "Job interrupted due to server shutdown"
                    interrupted_count += 1
                    
                    logger.info(
                        f"Job {job_id} marked as interrupted",
                        extra={"job_id": job_id, "status": "interrupted"}
                    )
        
        if interrupted_count > 0:
            logger.warning(f"Marked {interrupted_count} jobs as interrupted")
    
    async def close_websocket_connections(self):
        """
        Close all active WebSocket connections with 1001 status code.
        
        Status code 1001 indicates "Going Away" - server is shutting down.
        
        Requirements: 10.4
        """
        logger.info("Closing all WebSocket connections")
        
        closed_count = 0
        
        # Iterate through all job connections
        for job_id, connections in list(self.connection_manager.active_connections.items()):
            for websocket in connections.copy():
                try:
                    await websocket.close(code=1001, reason="Server shutting down")
                    closed_count += 1
                except Exception as e:
                    logger.error(
                        f"Error closing WebSocket for job {job_id}: {e}",
                        extra={"job_id": job_id},
                        exc_info=True
                    )
        
        # Clear all connections
        self.connection_manager.active_connections.clear()
        
        logger.info(f"Closed {closed_count} WebSocket connections")
    
    async def persist_job_queue(self):
        """
        Serialize job queue to JSON file on disk.
        
        Handles datetime serialization and errors gracefully.
        
        Requirements: 10.5
        """
        try:
            logger.info(f"Persisting job queue state to {self.state_file}")
            
            # Copy job queue data
            async with self.job_queue_lock:
                queue_data = dict(self.job_queue)
            
            # Serialize to JSON (datetime objects are already ISO strings)
            with open(self.state_file, 'w', encoding='utf-8') as f:
                json.dump(queue_data, f, indent=2, ensure_ascii=False)
            
            logger.info(f"Successfully persisted {len(queue_data)} jobs to disk")
            
        except Exception as e:
            logger.error(
                f"Failed to persist job queue state: {e}",
                exc_info=True
            )
    
    async def load_job_queue(self):
        """
        Load job queue from JSON file on startup.
        
        If the state file exists, loads it into the job queue.
        Handles deserialization errors gracefully.
        
        Requirements: 10.5
        """
        if not self.state_file.exists():
            logger.info("No persisted job queue state found")
            return
        
        try:
            logger.info(f"Loading job queue state from {self.state_file}")
            
            with open(self.state_file, 'r', encoding='utf-8') as f:
                queue_data = json.load(f)
            
            # Load into job queue
            async with self.job_queue_lock:
                self.job_queue.clear()
                self.job_queue.update(queue_data)
            
            logger.info(f"Successfully loaded {len(queue_data)} jobs from disk")
            
            # Optionally delete the state file after loading
            # self.state_file.unlink()
            
        except Exception as e:
            logger.error(
                f"Failed to load job queue state: {e}",
                exc_info=True
            )
    
    async def shutdown(self):
        """
        Execute graceful shutdown sequence.
        
        Steps:
        1. Stop accepting new jobs (already set by signal handler)
        2. Wait for active tasks to complete (up to 30 seconds)
        3. Update interrupted jobs if timeout reached
        4. Close all WebSocket connections
        5. Persist job queue state to disk
        6. Log shutdown completion
        
        Requirements: 10.1, 10.2, 10.3, 10.4, 10.5
        """
        logger.info("Starting graceful shutdown sequence")
        
        # Step 1: Already stopped accepting jobs (is_shutting_down = True)
        logger.info("Stopped accepting new job submissions")
        
        # Step 2: Wait for active tasks
        all_completed = await self.wait_for_tasks()
        
        # Step 3: Update interrupted jobs if timeout reached
        if not all_completed:
            await self.update_interrupted_jobs()
        
        # Step 4: Close WebSocket connections
        await self.close_websocket_connections()
        
        # Step 5: Persist job queue state
        await self.persist_job_queue()
        
        # Step 6: Log completion
        logger.info("Graceful shutdown completed")
        
        # Exit the process
        import sys
        sys.exit(0)
