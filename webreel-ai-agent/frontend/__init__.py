"""
Frontend API Client Package

This package provides API client and WebSocket functionality for communicating
with the FastAPI backend.
"""
from .api_client import (
    submit_job,
    get_job_status,
    list_jobs,
    get_video_url,
    check_backend_health,
    APIClientError,
    ConnectionFailedError,
    TimeoutError,
)
from .websocket_client import (
    track_progress,
    ProgressTracker,
    ProgressTrackerWithFallback,
)

__all__ = [
    "submit_job",
    "get_job_status",
    "list_jobs",
    "get_video_url",
    "check_backend_health",
    "APIClientError",
    "ConnectionFailedError",
    "TimeoutError",
    "track_progress",
    "ProgressTracker",
    "ProgressTrackerWithFallback",
]
