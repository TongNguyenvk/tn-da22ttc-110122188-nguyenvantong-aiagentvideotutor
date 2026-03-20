# Frontend API Client

This module provides API client and WebSocket functionality for communicating with the FastAPI backend.

## Components

### API Client (`api_client.py`)

Provides HTTP client functions for interacting with the FastAPI backend:

- `submit_job(task, video_name, config)` - Submit a new video generation job
- `get_job_status(job_id)` - Get the status of a specific job
- `list_jobs(status, limit)` - List all jobs with optional filtering
- `get_video_url(job_id)` - Get the URL for downloading a video
- `check_backend_health()` - Check if the backend is running

### WebSocket Client (`websocket_client.py`)

Provides real-time progress tracking via WebSocket:

- `track_progress(job_id, on_progress, use_fallback)` - Start tracking job progress
- `ProgressTracker` - WebSocket-only progress tracker
- `ProgressTrackerWithFallback` - Progress tracker with HTTP polling fallback

## Usage

### Basic Job Submission

```python
from frontend.api_client import submit_job, get_job_status

# Submit a job
config = {
    "enable_tts": True,
    "tts_voice": "banmai",
    "tts_engine": "fpt",
    "cdp_url": "http://localhost:9222",
    "padding_ms": 300
}

response = submit_job(
    task="Navigate to google.com and search for Python",
    video_name="demo",
    config=config
)

job_id = response["job_id"]
print(f"Job submitted: {job_id}")

# Check job status
status = get_job_status(job_id)
print(f"Status: {status['status']}")
```

### Real-Time Progress Tracking

```python
from frontend.websocket_client import track_progress

def handle_progress(data):
    print(f"Status: {data['status']}")
    if 'progress' in data:
        progress = data['progress']
        print(f"Phase {progress['current_phase']}: {progress['message']}")

# Start tracking (with HTTP polling fallback)
tracker = track_progress(job_id, handle_progress, use_fallback=True)

# Later, stop tracking
tracker.stop()
```

### Error Handling

```python
from frontend.api_client import (
    submit_job,
    ConnectionFailedError,
    TimeoutError,
    APIClientError
)

try:
    response = submit_job(task, video_name, config)
except ConnectionFailedError:
    print("Backend is not running. Start it with: uvicorn main:app --reload")
except TimeoutError:
    print("Request timed out")
except APIClientError as e:
    print(f"API error: {e}")
```

## Configuration

The backend URL is configured in `api_client.py`:

```python
BACKEND_URL = "http://localhost:8000"
```

WebSocket URL is configured in `websocket_client.py`:

```python
WS_BACKEND_URL = "ws://localhost:8000"
```

## Testing

Run the unit tests:

```bash
python -m pytest frontend/test_api_client.py -v
```

## Integration with Streamlit

The Streamlit app (`src/app.py`) uses these modules to:

1. Submit jobs to the backend instead of running the pipeline directly
2. Track progress via WebSocket with HTTP polling fallback
3. Fetch video history from the backend API
4. Display backend health status

## Requirements

- `requests>=2.31.0` - HTTP client
- `websocket-client>=1.8.0` - WebSocket client
- `pydantic>=2.0.0` - Data validation (used by backend)

Install with:

```bash
pip install requests websocket-client pydantic
```
