# Logging Implementation

This document describes the structured logging implementation for the FastAPI backend.

## Overview

The backend uses structured JSON logging to provide consistent, machine-readable logs for monitoring, debugging, and analysis. All logs are formatted as JSON objects with standardized fields.

## Features

- JSON-formatted logs for easy parsing and analysis
- Configurable log levels via environment variable
- Request logging middleware with timing information
- Job status transition logging
- Phase execution logging with context
- Error logging with stack traces
- WebSocket connection lifecycle logging

## Configuration

### Log Level

Set the log level using the `LOG_LEVEL` environment variable:

```bash
# Windows
set LOG_LEVEL=DEBUG

# Linux/Mac
export LOG_LEVEL=DEBUG
```

Available levels: `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`

Default: `INFO`

### Example .env file

```env
LOG_LEVEL=INFO
```

## Log Format

All logs follow this JSON structure:

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

### Standard Fields

- `timestamp`: ISO 8601 timestamp in UTC
- `level`: Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
- `logger`: Logger name (module path)
- `message`: Human-readable log message

### Context Fields

Additional fields are included based on the log context:

#### Job Context
- `job_id`: Unique job identifier
- `video_name`: Output video name
- `status`: Job status (pending, running, completed, failed)

#### Phase Context
- `phase`: Phase number (1-6)
- `phase_name`: Phase name (Scout, Parser, TTS, Injector, Execution, Composer)

#### Request Context
- `method`: HTTP method (GET, POST, etc.)
- `path`: Request path
- `status_code`: HTTP status code
- `duration_ms`: Request duration in milliseconds

#### Error Context
- `error`: Error message
- `exception`: Full stack trace (for errors)

## Log Examples

### Job Submission
```json
{
  "timestamp": "2026-03-20T07:26:24.559634+00:00",
  "level": "INFO",
  "logger": "backend.main",
  "message": "Job submitted: abc-123",
  "job_id": "abc-123",
  "task": "Navigate to example.com",
  "video_name": "demo"
}
```

### Status Transition
```json
{
  "timestamp": "2026-03-20T07:26:25.123456+00:00",
  "level": "INFO",
  "logger": "backend.tasks",
  "message": "Job abc-123: Status transition: pending -> running",
  "job_id": "abc-123",
  "status": "running"
}
```

### Phase Execution
```json
{
  "timestamp": "2026-03-20T07:26:26.789012+00:00",
  "level": "INFO",
  "logger": "backend.tasks",
  "message": "Job abc-123: Phase 1 (Scout) - Running browser-use agent...",
  "job_id": "abc-123",
  "phase": 1,
  "phase_name": "Scout",
  "message": "Running browser-use agent..."
}
```

### Request Logging
```json
{
  "timestamp": "2026-03-20T07:26:24.560000+00:00",
  "level": "INFO",
  "logger": "backend.middleware",
  "message": "POST /api/jobs - 201 (45.23ms)",
  "method": "POST",
  "path": "/api/jobs",
  "status_code": 201,
  "duration_ms": 45.23
}
```

### Error Logging
```json
{
  "timestamp": "2026-03-20T07:26:30.123456+00:00",
  "level": "ERROR",
  "logger": "backend.tasks",
  "message": "Job abc-123: Pipeline failed with error: Connection refused",
  "job_id": "abc-123",
  "error": "Connection refused",
  "timestamp": "2026-03-20T07:26:30.123456+00:00",
  "exception": "Traceback (most recent call last):\n  File \"tasks.py\", line 45, in execute_pipeline_task\n    video_path = await run_pipeline_v3(...)\nConnectionError: Connection refused"
}
```

### WebSocket Logging
```json
{
  "timestamp": "2026-03-20T07:26:24.600000+00:00",
  "level": "INFO",
  "logger": "backend.websocket",
  "message": "WebSocket connected for job abc-123. Total connections: 1",
  "job_id": "abc-123",
  "connection_count": 1
}
```

## Components

### logging_config.py

Configures structured logging with JSON formatter:
- `JSONFormatter`: Custom formatter that outputs JSON
- `setup_logging()`: Initializes logging configuration

### middleware.py

Request logging middleware:
- `RequestLoggingMiddleware`: Logs all HTTP requests with timing
- Logs different levels based on status code (4xx = warning, 5xx = error)

### Integration

Logging is integrated into:
- `main.py`: API endpoint logging, WebSocket lifecycle
- `tasks.py`: Job execution, phase progress, status transitions
- `websocket.py`: Connection management, broadcast errors

## Usage

### In Application Code

```python
import logging

logger = logging.getLogger(__name__)

# Basic logging
logger.info("Operation completed")

# Logging with context
logger.info(
    "Job started",
    extra={
        "job_id": job_id,
        "video_name": video_name
    }
)

# Error logging
try:
    risky_operation()
except Exception as e:
    logger.error(
        "Operation failed",
        extra={"job_id": job_id},
        exc_info=True
    )
```

## Testing

Run the logging test suite:

```bash
.\venv\Scripts\python.exe backend/test_logging.py
```

This verifies:
- JSON formatting works correctly
- Log levels are respected
- Extra fields are included
- Exception logging includes stack traces

## Log Analysis

### Parsing Logs

Since logs are JSON, they can be easily parsed and analyzed:

```python
import json

with open("backend.log") as f:
    for line in f:
        log = json.loads(line)
        if log["level"] == "ERROR":
            print(f"Error in {log['logger']}: {log['message']}")
```

### Filtering by Job

```python
job_id = "abc-123"
with open("backend.log") as f:
    for line in f:
        log = json.loads(line)
        if log.get("job_id") == job_id:
            print(log["message"])
```

### Monitoring Request Performance

```python
with open("backend.log") as f:
    for line in f:
        log = json.loads(line)
        if "duration_ms" in log and log["duration_ms"] > 1000:
            print(f"Slow request: {log['method']} {log['path']} - {log['duration_ms']}ms")
```

## Best Practices

1. Always include `job_id` in job-related logs
2. Use appropriate log levels (INFO for normal operations, ERROR for failures)
3. Include context fields using the `extra` parameter
4. Use `exc_info=True` when logging exceptions
5. Keep log messages concise and descriptive
6. Avoid logging sensitive information (passwords, tokens, etc.)

## Requirements Satisfied

- Requirement 9.2: Structured logging with configurable log levels
- Requirement 9.4: API request logging with method, path, status code, and duration
- Requirement 9.1: Phase failure logging with phase name, timestamp, and stack trace
- Requirement 9.5: Job status transition logging
- Requirement 9.3: WebSocket error handling and logging
