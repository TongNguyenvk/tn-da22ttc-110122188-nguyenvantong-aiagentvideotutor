"""
API Client for FastAPI Backend Communication

This module provides functions to interact with the FastAPI backend for video generation.
It handles job submission, status queries, and job listing with proper error handling.
"""
import requests
from typing import Dict, List, Optional, Any
from requests.exceptions import ConnectionError, Timeout, RequestException


# Backend configuration
BACKEND_URL = "http://localhost:8000"
DEFAULT_TIMEOUT = 30  # seconds


class APIClientError(Exception):
    """Base exception for API client errors."""
    pass


class ConnectionFailedError(APIClientError):
    """Raised when connection to backend fails."""
    pass


class TimeoutError(APIClientError):
    """Raised when request times out."""
    pass


def submit_job(
    task: str,
    video_name: str,
    config: Dict[str, Any],
    timeout: int = DEFAULT_TIMEOUT
) -> Dict[str, Any]:
    """
    Submit a new video generation job to the backend.
    
    Args:
        task: Task description for the video generation
        video_name: Name for the output video
        config: Configuration dictionary containing:
            - enable_tts: bool
            - tts_voice: str
            - tts_engine: str ("fpt" or "edge")
            - cdp_url: str
            - padding_ms: int
        timeout: Request timeout in seconds
    
    Returns:
        Dictionary containing:
            - job_id: str (UUID)
            - status: str
            - created_at: str (ISO timestamp)
            - websocket_url: str
    
    Raises:
        ConnectionFailedError: If connection to backend fails
        TimeoutError: If request times out
        APIClientError: For other API errors
    """
    try:
        response = requests.post(
            f"{BACKEND_URL}/api/jobs",
            json={
                "task": task,
                "video_name": video_name,
                "config": config
            },
            timeout=timeout
        )
        response.raise_for_status()
        return response.json()
    
    except ConnectionError as e:
        raise ConnectionFailedError(
            f"Failed to connect to backend at {BACKEND_URL}. "
            "Make sure the FastAPI backend is running."
        ) from e
    
    except Timeout as e:
        raise TimeoutError(
            f"Request timed out after {timeout} seconds"
        ) from e
    
    except RequestException as e:
        raise APIClientError(f"API request failed: {str(e)}") from e


def get_job_status(
    job_id: str,
    timeout: int = DEFAULT_TIMEOUT
) -> Dict[str, Any]:
    """
    Get the status of a specific job.
    
    Args:
        job_id: UUID of the job
        timeout: Request timeout in seconds
    
    Returns:
        Dictionary containing job details:
            - job_id: str
            - status: str ("pending", "running", "completed", "failed", "interrupted")
            - task: str
            - video_name: str
            - config: dict
            - progress: dict (optional, if running)
            - result: dict (optional, if completed)
            - error: str (optional, if failed)
            - created_at: str
            - started_at: str (optional)
            - completed_at: str (optional)
    
    Raises:
        ConnectionFailedError: If connection to backend fails
        TimeoutError: If request times out
        APIClientError: For other API errors (including 404 if job not found)
    """
    try:
        response = requests.get(
            f"{BACKEND_URL}/api/jobs/{job_id}",
            timeout=timeout
        )
        response.raise_for_status()
        return response.json()
    
    except ConnectionError as e:
        raise ConnectionFailedError(
            f"Failed to connect to backend at {BACKEND_URL}"
        ) from e
    
    except Timeout as e:
        raise TimeoutError(
            f"Request timed out after {timeout} seconds"
        ) from e
    
    except RequestException as e:
        if hasattr(e, 'response') and e.response is not None:
            if e.response.status_code == 404:
                raise APIClientError(f"Job {job_id} not found") from e
        raise APIClientError(f"API request failed: {str(e)}") from e


def list_jobs(
    status: Optional[str] = None,
    limit: int = 100,
    timeout: int = DEFAULT_TIMEOUT
) -> List[Dict[str, Any]]:
    """
    List all jobs, optionally filtered by status.
    
    Args:
        status: Optional status filter ("pending", "running", "completed", "failed", "interrupted")
        limit: Maximum number of jobs to return
        timeout: Request timeout in seconds
    
    Returns:
        List of job dictionaries, each containing:
            - job_id: str
            - status: str
            - task: str
            - video_name: str
            - created_at: str
            - completed_at: str (optional)
            - result: dict (optional, if completed)
    
    Raises:
        ConnectionFailedError: If connection to backend fails
        TimeoutError: If request times out
        APIClientError: For other API errors
    """
    try:
        params = {"limit": limit}
        if status:
            params["status"] = status
        
        response = requests.get(
            f"{BACKEND_URL}/api/jobs",
            params=params,
            timeout=timeout
        )
        response.raise_for_status()
        data = response.json()
        return data.get("jobs", [])
    
    except ConnectionError as e:
        raise ConnectionFailedError(
            f"Failed to connect to backend at {BACKEND_URL}"
        ) from e
    
    except Timeout as e:
        raise TimeoutError(
            f"Request timed out after {timeout} seconds"
        ) from e
    
    except RequestException as e:
        raise APIClientError(f"API request failed: {str(e)}") from e


def get_video_url(job_id: str) -> str:
    """
    Get the URL for downloading a completed video.
    
    Args:
        job_id: UUID of the completed job
    
    Returns:
        URL string for video download
    """
    return f"{BACKEND_URL}/api/jobs/{job_id}/video"


def check_backend_health(timeout: int = 5) -> bool:
    """
    Check if the backend is running and healthy.
    
    Args:
        timeout: Request timeout in seconds
    
    Returns:
        True if backend is healthy, False otherwise
    """
    try:
        response = requests.get(
            f"{BACKEND_URL}/health",
            timeout=timeout
        )
        return response.status_code == 200
    except:
        return False
