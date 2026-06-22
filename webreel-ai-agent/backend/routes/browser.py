"""
Browser Session Management Routes
Handles noVNC access and browser profile login tracking
"""

from fastapi import APIRouter, HTTPException, Depends, Request, Response, status
from pydantic import BaseModel
from datetime import datetime, timezone, timedelta
from typing import Optional
from urllib.parse import parse_qs, quote, urlparse
from jose import JWTError, jwt
import logging
import os

from backend.auth import ALGORITHM, SECRET_KEY, get_current_admin
from backend.database import Database

router = APIRouter(prefix="/api/browser", tags=["browser"])
logger = logging.getLogger(__name__)
NOVNC_TOKEN_TTL_MINUTES = int(os.getenv("NOVNC_TOKEN_TTL_MINUTES", "120"))


def create_novnc_token(admin_email: str) -> tuple[str, datetime]:
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=NOVNC_TOKEN_TTL_MINUTES)
    payload = {
        "sub": "novnc",
        "scope": "novnc",
        "admin": admin_email,
        "exp": expires_at,
    }
    token = jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)
    return token, expires_at


def build_novnc_url(token: str | None = None) -> str:
    if token:
        encoded_token = quote(token, safe="")
        websocket_path = quote(f"websockify?novnc_token={token}", safe="")
        return (
            "/novnc/vnc.html?autoconnect=true&resize=scale"
            f"&novnc_token={encoded_token}&path={websocket_path}"
        )

    return "/novnc/vnc.html?autoconnect=true&resize=scale&path=websockify"


def set_novnc_cookie(response: Response, token: str):
    response.set_cookie(
        key="novnc_token",
        value=token,
        max_age=NOVNC_TOKEN_TTL_MINUTES * 60,
        httponly=True,
        secure=True,
        samesite="strict",
        path="/",
    )


def validate_novnc_token(token: str) -> dict:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid noVNC token",
        )

    if payload.get("sub") != "novnc" or payload.get("scope") != "novnc":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid noVNC token scope",
        )

    return payload


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
async def get_vnc_urls(
    response: Response,
    current_user = Depends(get_current_admin),
):
    """
    Get noVNC URLs for all workers.
    Returns relative paths served via Nginx reverse proxy at /novnc/.
    No SSH tunnel required.
    """
    token, expires_at = create_novnc_token(current_user["email"])
    set_novnc_cookie(response, token)
    novnc_url = build_novnc_url(token)

    return {
        "web": {
            "url": novnc_url,
            "port": 6080,
            "worker": "web-worker",
            "expires_at": expires_at.isoformat(),
        },
        "presentation": {
            "url": novnc_url,
            "port": 6080,
            "worker": "presentation-worker",
            "expires_at": expires_at.isoformat(),
        }
    }


@router.get("/novnc-auth", status_code=status.HTTP_204_NO_CONTENT)
async def authorize_novnc_proxy(request: Request):
    """
    Internal Nginx auth_request endpoint for noVNC HTML and WebSocket access.
    The admin UI obtains a short-lived token from /api/browser/vnc-urls.
    """
    original_uri = request.headers.get("x-original-uri", "")
    query = urlparse(original_uri).query
    token = parse_qs(query).get("novnc_token", [""])[0]
    if not token:
        token = request.cookies.get("novnc_token", "")

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing noVNC token",
        )

    validate_novnc_token(token)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
