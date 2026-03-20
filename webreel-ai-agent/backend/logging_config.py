"""
Structured logging configuration for FastAPI backend.
Provides JSON-formatted logging with configurable log levels.
"""

import logging
import json
import sys
import os
from datetime import datetime, timezone
from typing import Any, Dict


class JSONFormatter(logging.Formatter):
    """
    Custom JSON formatter for structured logging.
    
    Formats log records as JSON objects with timestamp, level, message,
    and additional context fields.
    """
    
    def format(self, record: logging.LogRecord) -> str:
        """
        Format a log record as a JSON string.
        
        Args:
            record: Log record to format
            
        Returns:
            JSON-formatted log string
        """
        log_data: Dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        
        # Add exception info if present
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)
        
        # Add extra fields from record
        if hasattr(record, "job_id"):
            log_data["job_id"] = record.job_id
        
        if hasattr(record, "phase"):
            log_data["phase"] = record.phase
        
        if hasattr(record, "duration_ms"):
            log_data["duration_ms"] = record.duration_ms
        
        if hasattr(record, "status_code"):
            log_data["status_code"] = record.status_code
        
        if hasattr(record, "method"):
            log_data["method"] = record.method
        
        if hasattr(record, "path"):
            log_data["path"] = record.path
        
        return json.dumps(log_data)


def setup_logging() -> None:
    """
    Configure structured logging for the application.
    
    Sets up JSON-formatted logging with log level from environment variable.
    Defaults to INFO level if not specified.
    
    Requirements: 9.2, 9.4
    """
    # Get log level from environment variable (default: INFO)
    log_level_str = os.getenv("LOG_LEVEL", "INFO").upper()
    log_level = getattr(logging, log_level_str, logging.INFO)
    
    # Create JSON formatter
    json_formatter = JSONFormatter()
    
    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    
    # Remove existing handlers
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
    
    # Add console handler with JSON formatter
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(log_level)
    console_handler.setFormatter(json_formatter)
    root_logger.addHandler(console_handler)
    
    # Configure specific loggers
    logging.getLogger("backend").setLevel(log_level)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)  # Reduce uvicorn noise
    
    # Log startup message
    root_logger.info(f"Logging configured with level: {log_level_str}")
