"""
Session Manager Internal API
Runs in the session-manager container to handle freeze operations.
"""

from fastapi import FastAPI, HTTPException
import subprocess
import time
import os
import signal
import logging
import asyncio
from pathlib import Path
import shutil
import glob

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Session Manager Internal API")

CHROME_PROFILE_DIR = os.getenv("CHROME_PROFILE_DIR", "/app/chrome_master")
ARCHIVE_PATH = "/app/chrome_master/master_profile.tar.gz"


def find_chrome_processes():
    """Find active Chrome/Chromium processes (excluding zombies)."""
    try:
        result = subprocess.run(
            ["ps", "-eo", "pid,state,args"],
            capture_output=True,
            text=True
        )
        if result.returncode != 0:
            return []
            
        pids = []
        for line in result.stdout.strip().split("\n")[1:]:
            parts = line.strip().split(None, 2)
            if len(parts) >= 3:
                pid, state, cmd = parts[0], parts[1], parts[2]
                # Bo qua cac tien trinh Zombie (Z)
                if ("chrome" in cmd or "chromium" in cmd) and state != 'Z':
                    pids.append(pid)
        return pids
    except Exception as e:
        logger.error(f"Error finding Chrome processes: {e}")
        return []


async def graceful_shutdown_chrome(max_wait: int = 10):
    """
    Gracefully shutdown Chrome processes.
    Returns True if all processes stopped, False if timeout.
    """
    pids = find_chrome_processes()
    
    if not pids:
        logger.info("No Chrome processes found")
        return True
    
    logger.info(f"Found {len(pids)} Chrome processes: {pids}")
    
    # Send SIGTERM to all processes
    for pid in pids:
        try:
            os.kill(int(pid), signal.SIGTERM)
            logger.info(f"Sent SIGTERM to Chrome PID {pid}")
        except ProcessLookupError:
            pass
        except Exception as e:
            logger.warning(f"Failed to kill Chrome {pid}: {e}")
    
    # Wait for processes to exit gracefully
    for i in range(max_wait):
        await asyncio.sleep(1)
        remaining = find_chrome_processes()
        if not remaining:
            logger.info("All Chrome processes stopped gracefully")
            return True
        logger.info(f"Waiting for Chrome to exit... ({i+1}/{max_wait}) remaining: {remaining}")
    
    # Force kill if still running
    remaining = find_chrome_processes()
    if remaining:
        logger.warning(f"Chrome still running after {max_wait}s, force killing: {remaining}")
        for pid in remaining:
            try:
                os.kill(int(pid), signal.SIGKILL)
                logger.info(f"Force killed Chrome PID {pid}")
            except Exception:
                pass
        await asyncio.sleep(2)  # Wait for force kill to take effect
    
    final_check = find_chrome_processes()
    if final_check:
        logger.error(f"Chrome still running after force kill: {final_check}")
        return False
    
    return True


def start_chrome():
    """Start Chrome process after freezing."""
    chrome_bin = None
    if shutil.which("google-chrome"):
        chrome_bin = "google-chrome"
    else:
        paths = glob.glob("/opt/pw-browsers/chromium-*/chrome-linux64/chrome")
        if not paths:
            paths = glob.glob("/opt/pw-browsers/chromium-*/chrome-linux/chrome")
        if paths:
            chrome_bin = paths[0]
        elif shutil.which("chromium-browser"):
            chrome_bin = "chromium-browser"
            
    if not chrome_bin:
        logger.error("Chrome binary not found")
        return False
        
    cmd = [
        chrome_bin,
        "--display=:99",
        "--disable-gpu",
        "--no-sandbox",
        "--remote-debugging-port=9221",
        "--remote-debugging-address=127.0.0.1",
        "--remote-allow-origins=*",
        "--window-size=1280,800",
        "--window-position=0,0",
        "--disable-dev-shm-usage",
        "--disable-background-networking",
        "--disable-default-apps",
        "--disable-extensions",
        "--disable-sync",
        "--disable-translate",
        "--start-maximized",
        "--home-page", "https://www.office.com",
        f"--user-data-dir={CHROME_PROFILE_DIR}"
    ]
    
    logger.info(f"Starting Chrome again: {cmd}")
    try:
        # Chạy background và redirect stdout/stderr giống shell script
        with open("/tmp/chrome.log", "a") as log_file:
            subprocess.Popen(cmd, stdout=log_file, stderr=log_file)
        logger.info("Chrome started successfully from API")
        return True
    except Exception as e:
        logger.error(f"Failed to start Chrome from API: {e}")
        return False


def create_archive():
    """Create tar.gz archive of Chrome profile."""
    profile_dir = Path(CHROME_PROFILE_DIR)
    
    if not profile_dir.exists():
        raise Exception(f"Chrome profile directory not found: {CHROME_PROFILE_DIR}")
    
    # Remove existing archive if present
    archive_path = Path(ARCHIVE_PATH)
    if archive_path.exists():
        archive_path.unlink()
        logger.info(f"Removed existing archive: {archive_path}")
    
    # Create new archive in /tmp first to avoid "file changed as we read it"
    tmp_archive = Path("/tmp/master_profile.tar.gz")
    if tmp_archive.exists():
        tmp_archive.unlink()
        
    cmd = [
        "tar", "-czf", str(tmp_archive),
        "-C", str(profile_dir.parent),
        "chrome_master"
    ]
    
    logger.info(f"Creating archive: {cmd}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    if result.returncode != 0:
        raise Exception(f"Archive creation failed: {result.stderr}")
        
    # Move to final location
    import shutil
    shutil.move(str(tmp_archive), str(archive_path))
    
    # Get archive size
    size = archive_path.stat().st_size
    logger.info(f"Archive created and moved: {archive_path} ({size / 1024 / 1024:.2f} MB)")
    
    return {
        "archive_path": str(archive_path),
        "size_bytes": size,
        "size_mb": round(size / 1024 / 1024, 2)
    }


@app.post("/api/internal/freeze")
async def freeze_session():
    """
    Internal endpoint to freeze the Chrome session.
    1. Gracefully shutdown Chrome
    2. Wait for processes to exit
    3. Create tar.gz archive
    """
    logger.info("Received freeze request")
    
    # Step 1: Graceful shutdown
    if not await graceful_shutdown_chrome(max_wait=10):
        raise HTTPException(
            status_code=500,
            detail="Failed to shutdown Chrome gracefully"
        )
    
    # Small delay to ensure all file handles are released
    await asyncio.sleep(2)
    
    # Step 2: Create archive
    try:
        archive_info = create_archive()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
        
    # Step 3: Start Chrome again so user doesn't lose the VNC screen
    start_chrome()
    
    return {
        "status": "success",
        "message": "Session frozen, archived and restarted",
        "archive": archive_info
    }


@app.get("/api/internal/status")
async def get_status():
    """Get session manager status."""
    chrome_pids = find_chrome_processes()
    
    profile_dir = Path(CHROME_PROFILE_DIR)
    profile_exists = profile_dir.exists()
    
    archive_path = Path(ARCHIVE_PATH)
    archive_exists = archive_path.exists()
    archive_size = archive_path.stat().st_size if archive_exists else 0
    
    return {
        "status": "running",
        "chrome_processes": len(chrome_pids),
        "chrome_pids": chrome_pids,
        "profile_exists": profile_exists,
        "profile_path": str(profile_dir),
        "archive_exists": archive_exists,
        "archive_size_mb": round(archive_size / 1024 / 1024, 2) if archive_exists else 0
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)