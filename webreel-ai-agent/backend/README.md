# FastAPI Backend for Webreel Video Generation

This directory contains the FastAPI backend implementation for the Webreel video generation system. The backend provides RESTful API endpoints for job management and will support WebSocket connections for real-time progress updates.

## Architecture

The backend uses:
- **FastAPI**: Asynchronous web framework for building APIs
- **Pydantic**: Data validation and serialization
- **In-memory job queue**: Dictionary-based queue with asyncio locks for thread safety
- **Static file serving**: For video downloads

## API Endpoints

### Job Management

#### POST /api/jobs
Submit a new video generation job.

**Request Body:**
```json
{
  "task": "Navigate to example.com and explain the homepage",
  "video_name": "test_video",
  "config": {
    "enable_tts": true,
    "tts_voice": "banmai",
    "tts_engine": "fpt",
    "cdp_url": "http://localhost:9222",
    "padding_ms": 300
  }
}
```

**Response (201 Created):**
```json
{
  "job_id": "uuid",
  "status": "pending",
  "created_at": "2024-01-15T10:30:00Z",
  "websocket_url": "ws://localhost:8000/ws/uuid"
}
```

#### GET /api/jobs/{job_id}
Retrieve job status and metadata.

**Response (200 OK):**
```json
{
  "job_id": "uuid",
  "status": "pending",
  "task": "Navigate to example.com",
  "video_name": "test_video",
  "config": {...},
  "progress": null,
  "result": null,
  "error": null,
  "created_at": "2024-01-15T10:30:00Z",
  "started_at": null,
  "completed_at": null
}
```

#### GET /api/jobs
List all jobs with optional filtering and pagination.

**Query Parameters:**
- `status` (optional): Filter by job status (pending, running, completed, failed)
- `limit` (optional): Maximum number of jobs to return (default: 100)

**Response (200 OK):**
```json
{
  "jobs": [...],
  "total": 10
}
```

#### GET /api/jobs/{job_id}/video
Download the generated video file.

**Response (200 OK):**
- Content-Type: video/mp4
- Content-Disposition: attachment; filename="video.mp4"
- Binary video data

**Error Response (404 Not Found):**
```json
{
  "detail": "Video not available. Job status: pending"
}
```

### WebSocket Connection

#### WS /ws/{job_id}
WebSocket endpoint for real-time job progress updates.

**Connection:**
```javascript
const ws = new WebSocket('ws://localhost:8000/ws/{job_id}');

ws.onopen = () => {
  console.log('Connected to job progress updates');
};

ws.onmessage = (event) => {
  const data = JSON.parse(event.data);
  console.log('Job status:', data.status);
  console.log('Progress:', data.progress);
};
```

**Initial Message (sent on connection):**
```json
{
  "job_id": "uuid",
  "status": "running",
  "task": "Navigate to example.com",
  "progress": {
    "current_phase": 1,
    "phase_name": "Scout",
    "message": "Running browser-use agent...",
    "logs": []
  },
  "created_at": "2024-01-15T10:30:00Z",
  "started_at": "2024-01-15T10:30:01Z"
}
```

**Progress Update Messages:**
```json
{
  "job_id": "uuid",
  "status": "running",
  "progress": {
    "current_phase": 3,
    "phase_name": "TTS",
    "message": "Generating audio narration...",
    "logs": []
  }
}
```

**Completion Message:**
```json
{
  "job_id": "uuid",
  "status": "completed",
  "result": {
    "video_path": "/output/test/video.mp4",
    "video_url": "/videos/test/video.mp4",
    "duration_seconds": 120.5
  },
  "completed_at": "2024-01-15T10:35:00Z"
}
```

**Error Handling:**
- If job_id does not exist, receives error message and connection closes
- Connection automatically closes when job completes or fails
- Supports ping/pong for keep-alive (send "ping", receive "pong")
- Multiple clients can connect to the same job_id

### Health Check

#### GET /health
Check API health and get job statistics.

**Response (200 OK):**
```json
{
  "status": "healthy",
  "version": "1.0.0",
  "jobs": {
    "pending": 2,
    "running": 3,
    "completed": 150,
    "failed": 5
  }
}
```

## Running the Backend

### Development Mode

```bash
cd webreel-ai-agent
python backend/main.py
```

The server will start on `http://localhost:8000` with auto-reload enabled.

### Production Mode

```bash
cd webreel-ai-agent
uvicorn backend.main:app --host 0.0.0.0 --port 8000
```

## Testing

### Automated Tests

Run the test suite:

```bash
cd webreel-ai-agent
python -m pytest backend/test_main.py -v
```

### Manual API Testing

Start the backend server, then run:

```bash
python backend/test_api_manual.py
```

Or use curl:

```bash
# Health check
curl http://localhost:8000/health

# Submit a job
curl -X POST http://localhost:8000/api/jobs \
  -H "Content-Type: application/json" \
  -d '{"task": "Test task", "video_name": "test_video"}'

# Get job status
curl http://localhost:8000/api/jobs/{job_id}

# List all jobs
curl http://localhost:8000/api/jobs

# List pending jobs
curl http://localhost:8000/api/jobs?status=pending
```

## Files

- `main.py`: FastAPI application with API endpoints and WebSocket server
- `models.py`: Pydantic data models for request/response validation
- `tasks.py`: Background task executor for pipeline execution
- `websocket.py`: WebSocket connection manager for real-time updates
- `logging_config.py`: Structured JSON logging configuration
- `middleware.py`: Request logging middleware
- `test_main.py`: Automated test suite for API endpoints
- `test_task3.py`: Tests for background task processing
- `test_task3_integration.py`: Integration tests for pipeline execution
- `test_websocket.py`: Unit tests for WebSocket functionality
- `test_websocket_integration.py`: Integration tests for WebSocket updates
- `test_logging.py`: Tests for logging configuration
- `test_api_manual.py`: Manual testing script for API endpoints
- `README.md`: This file
- `LOGGING.md`: Comprehensive logging documentation

## Logging

The backend uses structured JSON logging for all operations. See [LOGGING.md](LOGGING.md) for detailed documentation.

Key features:
- JSON-formatted logs for easy parsing
- Configurable log levels via `LOG_LEVEL` environment variable
- Request logging with timing information
- Job status transition logging
- Phase execution logging
- Error logging with stack traces
- WebSocket connection lifecycle logging

Example log output:
```json
{
  "timestamp": "2026-03-20T07:26:24.559634+00:00",
  "level": "INFO",
  "logger": "backend.main",
  "message": "Job submitted: abc-123",
  "job_id": "abc-123",
  "video_name": "demo"
}
```

## Implementation Status

### Completed
- [x] Task 1: FastAPI backend foundation
- [x] Task 2: Job management API endpoints
- [x] Task 3: Background task processing with pipeline integration
- [x] Task 4: WebSocket server for real-time updates
  - [x] ConnectionManager class for managing WebSocket connections
  - [x] WebSocket endpoint at /ws/{job_id}
  - [x] Progress broadcasting integrated with background tasks
  - [x] Comprehensive test coverage (unit and integration tests)
- [x] Task 7: Error handling and logging
  - [x] Structured JSON logging with configurable log levels
  - [x] Request logging middleware with timing information
  - [x] Job status transition and phase execution logging
  - [x] Error logging with stack traces
  - [x] WebSocket connection lifecycle logging

### Pending (Future Tasks)
- [ ] Task 5: Backend testing checkpoint
- [ ] Task 6: Streamlit frontend integration
- [ ] Task 8: Graceful shutdown handling
- [ ] Task 9: Deployment configuration and documentation
- [ ] Task 10: End-to-end testing

## Dependencies

Required packages (added to requirements.txt):
- fastapi>=0.115.0
- uvicorn>=0.32.0
- python-multipart>=0.0.12
- websockets>=14.0
- httpx>=0.27.0 (for testing)

## Notes

- The job queue is currently in-memory and will be lost on server restart
- Background task processing will be implemented in Task 3
- WebSocket support for real-time progress updates will be added in Task 4
- All datetime objects use timezone-aware UTC timestamps
