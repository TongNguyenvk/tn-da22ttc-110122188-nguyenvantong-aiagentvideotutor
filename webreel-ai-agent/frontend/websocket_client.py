"""
WebSocket Client for Real-Time Progress Tracking

This module provides WebSocket connection functionality for receiving real-time
progress updates from the FastAPI backend during video generation.
"""
import json
import threading
import time
from typing import Callable, Optional, Dict, Any
from websocket import WebSocketApp, WebSocketException


# Backend WebSocket configuration
WS_BACKEND_URL = "ws://localhost:8000"


class ProgressTracker:
    """
    WebSocket client for tracking job progress with HTTP polling fallback.
    """
    
    def __init__(self, job_id: str, on_progress: Callable[[Dict[str, Any]], None]):
        """
        Initialize progress tracker.
        
        Args:
            job_id: UUID of the job to track
            on_progress: Callback function that receives progress updates
        """
        self.job_id = job_id
        self.on_progress = on_progress
        self.ws_url = f"{WS_BACKEND_URL}/ws/{job_id}"
        self.ws: Optional[WebSocketApp] = None
        self.thread: Optional[threading.Thread] = None
        self.is_running = False
        self.ws_failed = False
        self.stop_event = threading.Event()
    
    def _on_message(self, ws, message: str):
        """Handle incoming WebSocket message."""
        try:
            data = json.loads(message)
            self.on_progress(data)
            
            # Check if job is complete
            status = data.get("status", "")
            if status in ["completed", "failed", "interrupted"]:
                self.stop()
        except Exception as e:
            print(f"Error processing WebSocket message: {e}")
    
    def _on_error(self, ws, error):
        """Handle WebSocket error."""
        print(f"WebSocket error: {error}")
        self.ws_failed = True
    
    def _on_close(self, ws, close_status_code, close_msg):
        """Handle WebSocket connection close."""
        print(f"WebSocket connection closed: {close_status_code} - {close_msg}")
        self.is_running = False
    
    def _on_open(self, ws):
        """Handle WebSocket connection open."""
        print(f"WebSocket connected for job {self.job_id}")
    
    def start(self):
        """
        Start tracking progress via WebSocket.
        Runs in a background thread.
        """
        if self.is_running:
            return
        
        self.is_running = True
        self.ws_failed = False
        self.stop_event.clear()
        
        self.ws = WebSocketApp(
            self.ws_url,
            on_message=self._on_message,
            on_error=self._on_error,
            on_close=self._on_close,
            on_open=self._on_open
        )
        
        self.thread = threading.Thread(
            target=self._run_websocket,
            daemon=True
        )
        self.thread.start()
    
    def _run_websocket(self):
        """Run WebSocket connection in thread."""
        try:
            self.ws.run_forever()
        except Exception as e:
            print(f"WebSocket connection failed: {e}")
            self.ws_failed = True
            self.is_running = False
    
    def stop(self):
        """Stop tracking progress and close WebSocket connection."""
        self.is_running = False
        self.stop_event.set()
        
        if self.ws:
            try:
                self.ws.close()
            except:
                pass
    
    def is_connected(self) -> bool:
        """Check if WebSocket is currently connected."""
        return self.is_running and not self.ws_failed


class ProgressTrackerWithFallback:
    """
    Progress tracker with HTTP polling fallback if WebSocket fails.
    """
    
    def __init__(
        self,
        job_id: str,
        on_progress: Callable[[Dict[str, Any]], None],
        poll_interval: float = 2.0
    ):
        """
        Initialize progress tracker with fallback.
        
        Args:
            job_id: UUID of the job to track
            on_progress: Callback function that receives progress updates
            poll_interval: Seconds between HTTP polls (if WebSocket fails)
        """
        self.job_id = job_id
        self.on_progress = on_progress
        self.poll_interval = poll_interval
        self.ws_tracker: Optional[ProgressTracker] = None
        self.poll_thread: Optional[threading.Thread] = None
        self.is_running = False
        self.stop_event = threading.Event()
    
    def start(self):
        """
        Start tracking progress.
        Tries WebSocket first, falls back to HTTP polling if it fails.
        """
        if self.is_running:
            return
        
        self.is_running = True
        self.stop_event.clear()
        
        # Try WebSocket first
        self.ws_tracker = ProgressTracker(self.job_id, self.on_progress)
        self.ws_tracker.start()
        
        # Start monitoring thread to check if WebSocket fails
        monitor_thread = threading.Thread(
            target=self._monitor_and_fallback,
            daemon=True
        )
        monitor_thread.start()
    
    def _monitor_and_fallback(self):
        """Monitor WebSocket connection and fallback to HTTP polling if needed."""
        # Wait a bit to see if WebSocket connects
        time.sleep(2)
        
        # Check if WebSocket failed
        if self.ws_tracker and self.ws_tracker.ws_failed:
            print("WebSocket failed, falling back to HTTP polling")
            self._start_http_polling()
    
    def _start_http_polling(self):
        """Start HTTP polling for progress updates."""
        from .api_client import get_job_status, APIClientError
        
        self.poll_thread = threading.Thread(
            target=self._poll_loop,
            args=(get_job_status,),
            daemon=True
        )
        self.poll_thread.start()
    
    def _poll_loop(self, get_job_status_func):
        """HTTP polling loop."""
        while self.is_running and not self.stop_event.is_set():
            try:
                job_data = get_job_status_func(self.job_id, timeout=5)
                self.on_progress(job_data)
                
                # Check if job is complete
                status = job_data.get("status", "")
                if status in ["completed", "failed", "interrupted"]:
                    self.stop()
                    break
                
            except Exception as e:
                print(f"HTTP polling error: {e}")
            
            # Wait before next poll
            self.stop_event.wait(self.poll_interval)
    
    def stop(self):
        """Stop tracking progress."""
        self.is_running = False
        self.stop_event.set()
        
        if self.ws_tracker:
            self.ws_tracker.stop()
    
    def is_connected(self) -> bool:
        """Check if tracker is active (either WebSocket or polling)."""
        return self.is_running


def track_progress(
    job_id: str,
    on_progress: Callable[[Dict[str, Any]], None],
    use_fallback: bool = True
) -> ProgressTracker | ProgressTrackerWithFallback:
    """
    Create and start a progress tracker for a job.
    
    Args:
        job_id: UUID of the job to track
        on_progress: Callback function that receives progress updates.
                     Called with dict containing job status and progress info.
        use_fallback: If True, use HTTP polling fallback if WebSocket fails
    
    Returns:
        ProgressTracker or ProgressTrackerWithFallback instance
    
    Example:
        def handle_progress(data):
            print(f"Status: {data['status']}")
            if 'progress' in data:
                print(f"Phase: {data['progress']['phase_name']}")
                print(f"Message: {data['progress']['message']}")
        
        tracker = track_progress(job_id, handle_progress)
        # ... later ...
        tracker.stop()
    """
    if use_fallback:
        tracker = ProgressTrackerWithFallback(job_id, on_progress)
    else:
        tracker = ProgressTracker(job_id, on_progress)
    
    tracker.start()
    return tracker
