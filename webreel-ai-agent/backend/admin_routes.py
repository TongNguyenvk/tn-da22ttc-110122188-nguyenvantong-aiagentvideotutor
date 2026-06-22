"""
Admin routes for cookie management and system monitoring.

Endpoints:
- GET /admin/cookie-status - Check OneDrive cookies expiry
- GET /admin/novnc-url - Get noVNC URL for manual login
- POST /admin/verify-cookies - Verify cookies after manual login
"""

from fastapi import APIRouter, HTTPException, Depends, Response
from datetime import datetime, timedelta
import os
import logging
import asyncio

from backend.auth import get_current_admin
from backend.routes.browser import build_novnc_url, create_novnc_token, set_novnc_cookie

router = APIRouter(prefix="/admin", tags=["admin"])
logger = logging.getLogger("admin")

@router.get("/cookie-status")
async def get_cookie_status(admin: dict = Depends(get_current_admin)):
    """
    Check OneDrive cookies expiry status.
    
    Returns:
        status: "ok" | "warning" | "critical" | "expired"
        days_left: Number of days until expiry
        expires_at: ISO timestamp
        message: Human-readable message
        needs_login: Boolean
    """
    try:
        from playwright.async_api import async_playwright
        
        cdp_url = os.getenv("CHROME_CDP_URL", "http://localhost:9222")
        
        async with async_playwright() as p:
            browser = await p.chromium.connect_over_cdp(cdp_url)
            context = browser.contexts[0] if browser.contexts else await browser.new_context()
            
            # Get cookies
            cookies = await context.cookies()
            onedrive_cookies = [c for c in cookies if 'live.com' in c.get('domain', '')]
            
            if len(onedrive_cookies) == 0:
                return {
                    "status": "expired",
                    "days_left": 0,
                    "expires_at": None,
                    "message": "No OneDrive cookies found. Manual login required.",
                    "needs_login": True
                }
            
            # Find earliest expiry
            min_expiry = None
            for cookie in onedrive_cookies:
                expires = cookie.get('expires', -1)
                if expires > 0:
                    if min_expiry is None or expires < min_expiry:
                        min_expiry = expires
            
            if min_expiry is None:
                return {
                    "status": "unknown",
                    "days_left": None,
                    "expires_at": None,
                    "message": "Cannot determine cookie expiry",
                    "needs_login": False
                }
            
            expiry_date = datetime.fromtimestamp(min_expiry)
            days_left = (expiry_date - datetime.now()).days
            
            # Determine status
            if days_left < 0:
                status = "expired"
                message = "Cookies expired! Manual login required NOW."
                needs_login = True
            elif days_left < 7:
                status = "critical"
                message = f"Cookies expire in {days_left} days! Please login soon."
                needs_login = True
            elif days_left < 30:
                status = "warning"
                message = f"Cookies expire in {days_left} days. Consider logging in."
                needs_login = False
            else:
                status = "ok"
                message = f"Cookies are fresh. {days_left} days remaining."
                needs_login = False
            
            return {
                "status": status,
                "days_left": days_left,
                "expires_at": expiry_date.isoformat(),
                "message": message,
                "needs_login": needs_login,
                "cookie_count": len(onedrive_cookies)
            }
            
    except Exception as e:
        logger.error(f"Error checking cookie status: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/novnc-url")
async def get_novnc_url(
    response: Response,
    admin: dict = Depends(get_current_admin),
):
    """
    Get noVNC URL for embedded iframe.
    
    Returns relative path so the iframe loads through Nginx reverse proxy
    at /novnc/ without needing SSH tunnel or direct port access.
    
    Returns:
        url: noVNC relative path (served via Nginx proxy)
        instructions: Step-by-step login instructions
    """
    # noVNC is proxied through Nginx at /novnc/ (see nginx.conf).
    # No SSH tunnel needed; the admin accesses it directly via the
    # same origin as the frontend (e.g. https://domain.com/novnc/).
    
    token, expires_at = create_novnc_token(admin["email"])
    set_novnc_cookie(response, token)

    return {
        "url": build_novnc_url(),
        "expires_at": expires_at.isoformat(),
        "instructions": [
            "1. Click 'Login to OneDrive' to open the VNC window below",
            "2. In the VNC browser, navigate to https://onedrive.live.com",
            "3. Login with your Microsoft account",
            "4. IMPORTANT: Tick 'Keep me signed in' checkbox",
            "5. After login, click 'Verify Login' button above"
        ]
    }

@router.post("/verify-cookies")
async def verify_cookies(admin: dict = Depends(get_current_admin)):
    """
    Verify that cookies are valid after manual login.
    
    Returns:
        success: Boolean
        message: Verification result
    """
    try:
        from playwright.async_api import async_playwright
        
        cdp_url = os.getenv("CHROME_CDP_URL", "http://localhost:9222")
        
        async with async_playwright() as p:
            browser = await p.chromium.connect_over_cdp(cdp_url)
            context = browser.contexts[0] if browser.contexts else await browser.new_context()
            page = context.pages[0] if context.pages else await context.new_page()
            
            # Try to navigate to OneDrive
            await page.goto('https://onedrive.live.com/', wait_until='domcontentloaded', timeout=30000)
            await asyncio.sleep(3)
            
            current_url = page.url
            
            if 'login.live.com' in current_url or 'login.microsoftonline.com' in current_url:
                return {
                    "success": False,
                    "message": "Still on login page. Please complete the login process."
                }
            
            # Check cookies
            cookies = await context.cookies()
            onedrive_cookies = [c for c in cookies if 'live.com' in c.get('domain', '')]
            
            if len(onedrive_cookies) == 0:
                return {
                    "success": False,
                    "message": "No cookies found. Login may have failed."
                }
            
            return {
                "success": True,
                "message": f"Login successful! Found {len(onedrive_cookies)} cookies.",
                "cookie_count": len(onedrive_cookies)
            }
            
    except Exception as e:
        logger.error(f"Error verifying cookies: {e}")
        return {
            "success": False,
            "message": f"Verification failed: {str(e)}"
        }

@router.get("/system-status")
async def get_system_status(admin: dict = Depends(get_current_admin)):
    """
    Get overall system status including workers, queues, and cookies.
    """
    from backend.queue import JobQueue
    
    queue = JobQueue()
    
    # Get queue stats
    queue_stats = queue.get_all_queue_stats()
    
    # Get cookie status
    cookie_status = await get_cookie_status()
    
    # Get worker status (from Redis or Docker)
    # TODO: Implement worker health check
    
    return {
        "queues": queue_stats,
        "cookies": cookie_status,
        "timestamp": datetime.now().isoformat()
    }
