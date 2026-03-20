"""
Middleware for request logging and error handling.
Logs all API requests with method, path, status code, and duration.
"""

import logging
import time
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

logger = logging.getLogger(__name__)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """
    Middleware to log all HTTP requests with timing information.
    
    Logs method, path, status code, and request duration for every API call.
    
    Requirements: 9.2, 9.4
    """
    
    def __init__(self, app: ASGIApp):
        """
        Initialize the middleware.
        
        Args:
            app: ASGI application instance
        """
        super().__init__(app)
    
    async def dispatch(self, request: Request, call_next):
        """
        Process the request and log details.
        
        Args:
            request: Incoming HTTP request
            call_next: Next middleware or route handler
            
        Returns:
            HTTP response
        """
        # Record start time
        start_time = time.time()
        
        # Extract request details
        method = request.method
        path = request.url.path
        
        # Process request
        try:
            response: Response = await call_next(request)
            status_code = response.status_code
            
        except Exception as e:
            # Log error and re-raise
            duration_ms = (time.time() - start_time) * 1000
            logger.error(
                f"Request failed: {method} {path}",
                extra={
                    "method": method,
                    "path": path,
                    "duration_ms": round(duration_ms, 2),
                    "error": str(e)
                },
                exc_info=True
            )
            raise
        
        # Calculate duration
        duration_ms = (time.time() - start_time) * 1000
        
        # Log request with details
        log_message = f"{method} {path} - {status_code} ({duration_ms:.2f}ms)"
        
        # Use different log levels based on status code
        if status_code >= 500:
            logger.error(
                log_message,
                extra={
                    "method": method,
                    "path": path,
                    "status_code": status_code,
                    "duration_ms": round(duration_ms, 2)
                }
            )
        elif status_code >= 400:
            logger.warning(
                log_message,
                extra={
                    "method": method,
                    "path": path,
                    "status_code": status_code,
                    "duration_ms": round(duration_ms, 2)
                }
            )
        else:
            logger.info(
                log_message,
                extra={
                    "method": method,
                    "path": path,
                    "status_code": status_code,
                    "duration_ms": round(duration_ms, 2)
                }
            )
        
        return response
