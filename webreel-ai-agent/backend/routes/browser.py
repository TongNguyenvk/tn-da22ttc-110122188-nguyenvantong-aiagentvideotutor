"""
Browser Session Management Routes
Handles noVNC access and browser profile login tracking
"""

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from datetime import datetime, timezone, timedelta
from typing import Optional
import logging

from backend.auth import get_current_admin
from backend.database import Database

router = APIRouter(prefix="/api/browser", tags=["browser"])
logger = logging.getLogger(__name__)


class BrowserSessionUpdate(BaseModel):
    worker_type: str  # "web" or "presentation"
    last_login: datetime


class BrowserSessionResponse(BaseModel):
    worker_type: str
    last_login: Optional[datetime]
    days_since_login: Optional[int]
    needs_refresh: bool
    warning_level: str  # "ok", "warning", "critical"


@router.get("/sessions", response_model=list[BrowserSessionResponse])
async def get_browser_sessions(current_user = Depends(get_current_admin)):
    """
    Get browser session status for all workers.
    Returns last login time and warning level.
    """
    if not Database.is_connected():
        raise HTTPException(status_code=503, detail="Database not connected")
    
    try:
        db = Database.get_db()
        sessions_collection = db["browser_sessions"]
        
        # Get sessions for both workers
        workers = ["web", "presentation"]
        results = []
        
        for worker_type in workers:
            try:
                session = await sessions_collection.find_one({"worker_type": worker_type})
            except Exception as e:
                logger.warning(f"Failed to query session for {worker_type}: {e}")
                session = None
            
            if session and session.get("last_login"):
                last_login = session["last_login"]
                if isinstance(last_login, str):
                    last_login = datetime.fromisoformat(last_login.replace('Z', '+00:00'))
                
                now = datetime.now(timezone.utc)
                days_since = (now - last_login).days
                
                # Determine warning level
                if days_since < 30:
                    warning_level = "ok"
                    needs_refresh = False
                elif days_since < 60:
                    warning_level = "warning"
                    needs_refresh = False
                else:
                    warning_level = "critical"
                    needs_refresh = True
                
                results.append(BrowserSessionResponse(
                    worker_type=worker_type,
                    last_login=last_login,
                    days_since_login=days_since,
                    needs_refresh=needs_refresh,
                    warning_level=warning_level
                ))
            else:
                # No session found
                results.append(BrowserSessionResponse(
                    worker_type=worker_type,
                    last_login=None,
                    days_since_login=None,
                    needs_refresh=True,
                    warning_level="critical"
                ))
        
        return results
    
    except Exception as e:
        logger.error(f"Failed to get browser sessions: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/sessions/update")
async def update_browser_session(
    data: BrowserSessionUpdate,
    current_user = Depends(get_current_admin)
):
    """
    Update last login timestamp for a worker.
    Called by admin after manually logging in via noVNC.
    """
    if not Database.is_connected():
        raise HTTPException(status_code=503, detail="Database not connected")
    
    if data.worker_type not in ["web", "presentation"]:
        raise HTTPException(status_code=400, detail="Invalid worker_type")
    
    try:
        db = Database.get_db()
        sessions_collection = db["browser_sessions"]
        
        # Upsert session
        await sessions_collection.update_one(
            {"worker_type": data.worker_type},
            {
                "$set": {
                    "worker_type": data.worker_type,
                    "last_login": data.last_login,
                    "updated_by": current_user["email"],
                    "updated_at": datetime.now(timezone.utc)
                }
            },
            upsert=True
        )
        
        logger.info(f"Updated browser session for {data.worker_type} by {current_user['email']}")
        
        return {
            "message": "Browser session updated successfully",
            "worker_type": data.worker_type,
            "last_login": data.last_login
        }
    
    except Exception as e:
        logger.error(f"Failed to update browser session: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/vnc-urls")
async def get_vnc_urls(current_user = Depends(get_current_admin)):
    """
    Get noVNC URLs for all workers.
    Returns relative paths served via Nginx reverse proxy at /novnc/.
    No SSH tunnel required.
    """
    return {
        "web": {
            "url": "/novnc/vnc.html?autoconnect=true&resize=scale",
            "port": 6080,
            "worker": "web-worker"
        },
        "presentation": {
            "url": "/novnc/vnc.html?autoconnect=true&resize=scale",
            "port": 6080,
            "worker": "presentation-worker"
        }
    }
