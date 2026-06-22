"""
Session Manager API - Freeze Master Chrome Profile
"""

from fastapi import APIRouter, HTTPException, Depends
import httpx
import logging
import asyncio

from backend.auth import get_current_admin

router = APIRouter(prefix="/api/session", tags=["session"])
logger = logging.getLogger(__name__)

SESSION_MANAGER_URL = "http://session-manager:8001"


@router.post("/freeze")
async def freeze_session(admin: dict = Depends(get_current_admin)):
    """
    Freeze the Chrome session by triggering graceful shutdown and archiving.
    
    This endpoint:
    1. Calls the session-manager internal API to shutdown Chrome gracefully
    2. Waits for Chrome to fully exit
    3. Archives the Chrome profile to master_profile.tar.gz
    
    Returns success when archive is complete.
    """
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(f"{SESSION_MANAGER_URL}/api/internal/freeze")
            
            if response.status_code != 200:
                error_detail = response.json().get("detail", "Unknown error")
                raise HTTPException(
                    status_code=response.status_code,
                    detail=f"Freeze failed: {error_detail}"
                )
            
            result = response.json()
            logger.info(f"Admin {admin['email']} froze session successfully: {result}")
            return result
            
    except httpx.ConnectError:
        raise HTTPException(
            status_code=503,
            detail="Session Manager not reachable. Is the container running?"
        )
    except httpx.TimeoutException:
        raise HTTPException(
            status_code=504,
            detail="Session freeze timed out"
        )
    except Exception as e:
        logger.error(f"Freeze session error: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Freeze failed: {str(e)}"
        )


@router.get("/status")
async def get_session_status(admin: dict = Depends(get_current_admin)):
    """
    Get current session manager status.
    """
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"{SESSION_MANAGER_URL}/api/internal/status")
            logger.info(f"Admin {admin['email']} checked session status")
            return response.json()
    except httpx.ConnectError:
        return {"status": "unavailable", "message": "Session Manager not running"}
    except Exception as e:
        return {"status": "error", "message": str(e)}
