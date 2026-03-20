"""
WebSocket connection manager for real-time progress updates.
Manages WebSocket connections and broadcasts messages to connected clients.
"""

from fastapi import WebSocket
from typing import Dict, List
import logging

logger = logging.getLogger(__name__)


class ConnectionManager:
    """
    Manages WebSocket connections for real-time job progress updates.
    
    Each job can have multiple WebSocket clients connected. The manager
    handles connection lifecycle and message broadcasting to all clients
    subscribed to a specific job_id.
    
    Requirements: 4.1, 4.2
    """
    
    def __init__(self):
        """Initialize the connection manager with empty connection dictionary."""
        # Dictionary mapping job_id to list of WebSocket connections
        self.active_connections: Dict[str, List[WebSocket]] = {}
    
    async def connect(self, job_id: str, websocket: WebSocket) -> None:
        """
        Accept a new WebSocket connection and store it for the given job_id.
        
        Args:
            job_id: Unique identifier for the job
            websocket: WebSocket connection to accept and store
            
        Requirements: 9.3
        """
        try:
            await websocket.accept()
            
            if job_id not in self.active_connections:
                self.active_connections[job_id] = []
            
            self.active_connections[job_id].append(websocket)
            logger.info(
                f"WebSocket connected for job {job_id}. Total connections: {len(self.active_connections[job_id])}",
                extra={"job_id": job_id, "connection_count": len(self.active_connections[job_id])}
            )
        except Exception as e:
            logger.error(
                f"Failed to accept WebSocket connection for job {job_id}: {e}",
                extra={"job_id": job_id},
                exc_info=True
            )
            raise
    
    async def disconnect(self, job_id: str, websocket: WebSocket) -> None:
        """
        Remove a WebSocket connection from the active connections list.
        
        Args:
            job_id: Unique identifier for the job
            websocket: WebSocket connection to remove
            
        Requirements: 9.3
        """
        try:
            if job_id in self.active_connections:
                if websocket in self.active_connections[job_id]:
                    self.active_connections[job_id].remove(websocket)
                    logger.info(
                        f"WebSocket disconnected for job {job_id}. Remaining connections: {len(self.active_connections[job_id])}",
                        extra={"job_id": job_id, "connection_count": len(self.active_connections[job_id])}
                    )
                
                # Clean up empty connection lists
                if not self.active_connections[job_id]:
                    del self.active_connections[job_id]
                    logger.info(
                        f"All WebSocket connections closed for job {job_id}",
                        extra={"job_id": job_id}
                    )
        except Exception as e:
            logger.error(
                f"Error during WebSocket disconnect for job {job_id}: {e}",
                extra={"job_id": job_id},
                exc_info=True
            )
    
    async def broadcast(self, job_id: str, message: dict) -> None:
        """
        Send a message to all WebSocket connections for a specific job_id.
        
        Handles connection errors gracefully by continuing to send to other
        connections even if one fails. Failed connections are automatically
        removed from the active connections list.
        
        Args:
            job_id: Unique identifier for the job
            message: Dictionary message to send (will be serialized to JSON)
            
        Requirements: 9.3
        """
        if job_id not in self.active_connections:
            return
        
        # Create a copy of the connection list to avoid modification during iteration
        connections = self.active_connections[job_id].copy()
        failed_connections = []
        
        for connection in connections:
            try:
                await connection.send_json(message)
            except Exception as e:
                logger.warning(
                    f"Failed to send message to WebSocket for job {job_id}: {e}",
                    extra={"job_id": job_id, "error": str(e)}
                )
                # Mark connection for removal
                failed_connections.append(connection)
        
        # Remove all failed connections
        for connection in failed_connections:
            try:
                await self.disconnect(job_id, connection)
            except Exception as e:
                logger.error(
                    f"Error removing failed WebSocket connection for job {job_id}: {e}",
                    extra={"job_id": job_id},
                    exc_info=True
                )


# Global connection manager instance
manager = ConnectionManager()
