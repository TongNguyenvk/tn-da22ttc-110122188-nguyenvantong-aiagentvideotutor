"""
Presentation Worker - Polls Redis presentation-queue and runs the PowerPoint Online pipeline.

This acts as a standalone test worker for the "Red Carpet" Graph API feature.
Usage:
    python -m worker.presentation_worker
"""

import asyncio
import logging
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

# Setup paths
WORKER_DIR = Path(__file__).parent
AGENT_DIR = WORKER_DIR.parent
sys.path.insert(0, str(AGENT_DIR))

from backend.queue import JobQueue

# Import worker exceptions
sys.path.insert(0, str(AGENT_DIR / "worker"))
try:
    from exceptions import SessionExpiredError
except ImportError:
    class SessionExpiredError(Exception):
        pass

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s - %(message)s")
logger = logging.getLogger("presentation_worker")

QUEUE_NAME = os.getenv("WORKER_QUEUE", "presentation-queue")
POLL_TIMEOUT = int(os.getenv("POLL_TIMEOUT", "5"))
WORKER_ID = os.getenv("WORKER_ID", f"pres-worker-{os.getpid()}")

# Increase navigation timeout for slow-loading pages like OneDrive
# Default is 30s, but OneDrive can take longer especially on first load
os.environ.setdefault("TIMEOUT_NavigateToUrlEvent", "60")  # 60 seconds
os.environ.setdefault("TIMEOUT_BrowserStateRequestEvent", "45")  # 45 seconds

# Chrome profile directory
CHROME_PROFILE_DIR = os.getenv("CHROME_PROFILE_DIR", "/app/chrome_profile")

_chrome_proc = None

def _find_chromium_path() -> str:
    """Find the Playwright-installed Chromium binary."""
    pw_dir = os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "/opt/pw-browsers")
    pw_path = Path(pw_dir)
    if pw_path.exists():
        for chrome_dir in sorted(pw_path.glob("chromium-*/chrome-linux*/chrome")):
            return str(chrome_dir)
    for name in ["chromium", "chromium-browser", "google-chrome"]:
        result = subprocess.run(["which", name], capture_output=True, text=True)
        if result.returncode == 0:
            return result.stdout.strip()
    return ""  # Handled natively by Playwright in Windows fallback if needed

def launch_chrome(port: int = 9222) -> subprocess.Popen:
    """Launch headless Chrome with CDP on the given port."""
    chrome_bin = _find_chromium_path()
    if not chrome_bin:
        logger.warning("Chromium executable not found. Fallback to default Chrome if on Windows.")
        chrome_bin = "chrome"

    logger.info(f"Launching Chrome: {chrome_bin} on port {port}")

    args = [
        chrome_bin,
        "--no-sandbox",
        "--disable-gpu",
        "--disable-dev-shm-usage",
        "--disable-extensions",
        "--disable-background-networking",
        "--disable-default-apps",
        "--disable-sync",
        "--disable-translate",
        "--disable-infobars",
        "--disable-blink-features=AutomationControlled",
        # Stability flags to prevent Chrome crash during long sessions
        "--disable-background-timer-throttling",
        "--disable-backgrounding-occluded-windows",
        "--disable-renderer-backgrounding",
        "--disable-features=VizDisplayCompositor,TranslateUI",
        "--disable-hang-monitor",
        "--disable-ipc-flooding-protection",
        "--disable-component-update",
        "--memory-pressure-off",
        "--js-flags=--max-old-space-size=1024",
        f"--remote-debugging-address=0.0.0.0",
        "--remote-debugging-port=" + str(port),
        "--remote-allow-origins=*",
        "--window-position=0,0",
        "--window-size=1920,1080",
        "--start-maximized",
        f"--user-data-dir={CHROME_PROFILE_DIR}",
        "about:blank",
    ]

    proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    
    import urllib.request
    import json
    for i in range(30):
        try:
            resp = urllib.request.urlopen(f"http://localhost:{port}/json/version", timeout=1)
            data = json.loads(resp.read())
            logger.info(f"Chrome ready: {data.get('Browser', 'unknown')}")
            return proc
        except Exception:
            time.sleep(0.5)

    proc.terminate()
    raise RuntimeError("Chrome failed to start within 15s CDP timeout.")

def kill_chrome():
    global _chrome_proc
    if _chrome_proc and _chrome_proc.poll() is None:
        logger.info("Stopping Chrome...")
        _chrome_proc.terminate()
        try:
            _chrome_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _chrome_proc.kill()
        logger.info("Chrome stopped")

async def _prewarm_onedrive_session():
    """
    Pre-warm OneDrive session by ensuring browser has valid authentication cookies.
    This prevents "Access Denied" errors during the main task.
    
    Strategy:
    1. Get access token from MSAL (same as Graph API)
    2. Navigate to OneDrive and let it authenticate
    3. Verify session is valid
    """
    import urllib.request
    import json
    
    # Get CDP URL
    cdp_url = os.getenv("CHROME_CDP_URL", "http://localhost:9222")
    
    # Import browser-use
    sys.path.insert(0, str(AGENT_DIR / "desktop_app" / "browser-use"))
    from browser_use import Browser
    
    # Get access token to verify authentication is available
    from shared.graph_api import get_access_token
    try:
        token = get_access_token()
        logger.info("MSAL token is valid - authentication available")
    except Exception as e:
        logger.error(f"Failed to get MSAL token: {e}")
        raise RuntimeError("Cannot proceed without valid authentication")
    
    browser = Browser(cdp_url=cdp_url, keep_alive=True)
    
    try:
        await browser.start()
        
        # Get or create page
        pages = await browser.get_pages()
        if pages:
            page = pages[0]
        else:
            page = await browser.new_page()
        
        # Navigate to OneDrive home to trigger authentication flow
        # The persistent profile should have cookies, but they may be expired
        logger.info("Navigating to OneDrive to verify/refresh session...")
        
        # Strategy: Try with increasing timeouts and fallback to load event
        navigation_success = False
        last_error = None
        
        for attempt in range(3):
            try:
                timeout_ms = 30000 + (attempt * 15000)  # 30s, 45s, 60s
                wait_strategy = 'domcontentloaded' if attempt < 2 else 'load'
                
                logger.info(f"Navigation attempt {attempt + 1}/3 (timeout={timeout_ms}ms, wait={wait_strategy})")
                
                await page.goto(
                    'https://onedrive.live.com/',
                    wait_until=wait_strategy,
                    timeout=timeout_ms
                )
                
                navigation_success = True
                logger.info("Navigation successful")
                break
                
            except Exception as nav_err:
                last_error = nav_err
                logger.warning(f"Navigation attempt {attempt + 1} failed: {nav_err}")
                
                if attempt < 2:
                    # Wait a bit before retry
                    await asyncio.sleep(2)
                    
                    # Try to stop any pending navigation
                    try:
                        await page.goto('about:blank', timeout=5000)
                        await asyncio.sleep(1)
                    except:
                        pass
        
        if not navigation_success:
            logger.error(f"All navigation attempts failed. Last error: {last_error}")
            # Don't raise - let's check current URL anyway
        
        # Wait for page to settle (handle any redirects)
        await asyncio.sleep(3)
        
        # Check current URL to see if we're authenticated
        current_url = page.url
        logger.info(f"Current URL after navigation: {current_url}")
        
        if 'login.live.com' in current_url or 'login.microsoftonline.com' in current_url:
            logger.warning("Browser redirected to login page - session expired or not authenticated")
            logger.warning("This is expected on first run or after cookies expire")
            logger.info("SOLUTION: The agent will attempt to handle authentication during the main task")
            logger.info("If authentication fails, manually login to OneDrive in browser (port 9222) once")
            # Don't raise error - let agent try
            
        elif 'onedrive.live.com' in current_url:
            logger.info("OneDrive session is valid - dashboard loaded successfully")
        else:
            logger.warning(f"Unexpected URL: {current_url}")
            logger.warning("Pre-warm inconclusive - agent will attempt navigation anyway")
        
        # Navigate back to blank
        await page.goto('about:blank')
        logger.info("Pre-warm completed successfully")
        
    except Exception as e:
        logger.error(f"Pre-warm failed: {e}")
        raise
    finally:
        # Don't close browser - keep it alive for main task
        pass

async def process_job(job: dict) -> dict:
    job_id = job.get("job_id", "unknown")
    config = job.get("config", {})
    pptx_path = config.get("pptx_path", "")
    video_name = job.get("video_name", f"pres_{int(time.time())}")

    logger.info(f"Processing Presentation Job {job_id} for file {pptx_path}")

    try:
        # 0. Convert legacy .ppt to .pptx if necessary
        if pptx_path.lower().endswith('.ppt'):
            logger.info("Detected legacy .ppt file. Converting to .pptx using LibreOffice...")
            out_dir = os.path.dirname(pptx_path)
            cmd = ["soffice", "--headless", "--convert-to", "pptx", pptx_path, "--outdir", out_dir]
            res = subprocess.run(cmd, capture_output=True, text=True)
            if res.returncode != 0:
                raise RuntimeError(f"Failed to convert .ppt to .pptx: {res.stderr}")
            pptx_path = pptx_path + "x"
            logger.info(f"Conversion successful. New path: {pptx_path}")

        from shared.graph_api import upload_to_onedrive, delete_from_onedrive
        
        # 1. Upload to OneDrive
        logger.info("Uploading file to OneDrive via Graph API...")
        web_url = upload_to_onedrive(pptx_path)
        logger.info(f"File uploaded. Direct URL: {web_url}")
        
        # 1.5. Pre-warm OneDrive session (OPTIONAL - may timeout on slow connections)
        # Skipping pre-warm because we're using direct authenticated link
        # which should work even without pre-warming
        logger.info("Skipping pre-warm - using direct authenticated link instead")
        
        # Uncomment below if you want to verify session before main task:
        # try:
        #     await _prewarm_onedrive_session()
        #     logger.info("OneDrive session pre-warm completed")
        # except Exception as prewarm_err:
        #     logger.warning(f"Pre-warm encountered issues: {prewarm_err}")
        #     logger.warning("Continuing with main task - agent will handle navigation")
        
        # 2. Extract slide texts
        sys.path.insert(0, str(AGENT_DIR / "desktop_app"))
        from slide_pipeline.extractor import extract_text_from_pptx
        
        logger.info("Extracting texts from PPTX...")
        slides = extract_text_from_pptx(Path(pptx_path))
        
        file_name_only = os.path.basename(pptx_path)
        
        # 3. Build dynamic prompt using DIRECT LINK and keyboard shortcuts
        # This bypasses authentication issues with onedrive.live.com
        logger.info(f"Using direct OneDrive link: {web_url}")
        
        num_slides = len(slides)
        
        task_prompt = f"Present a PowerPoint file with {num_slides} slides:\n\n"
        task_prompt += f"1. Navigate to: {web_url}\n"
        task_prompt += f"2. Wait 15 seconds for the presentation slide show to fully load.\n"
        task_prompt += f"3. For each of the {num_slides} slides:\n"
        task_prompt += f"   - Call save_narration with a brief description of the slide content\n"
        task_prompt += f"   - Press Space or ArrowRight to advance to the next slide\n"
        task_prompt += f"4. Call done to finish the task.\n\n"
        task_prompt += f"Slide titles for reference:\n"
        
        for idx, slide in enumerate(slides):
            # Only include slide title/first line, not full content
            first_line = slide.texts[0] if slide.texts else f"Slide {idx+1}"
            # Truncate long titles
            if len(first_line) > 80:
                first_line = first_line[:77] + "..."
            task_prompt += f"   {idx+1}. {first_line}\n"
        
        logger.info(f"Generated task prompt: \n{task_prompt}")
        
        from backend.queue import JobQueue
        queue_client = JobQueue()

        async def progress_callback(phase: float, message: str, data: any = None):
            queue_client.notify_api_progress(job_id, phase, message, data)
            
            if phase == 2.5 and config.get("enable_review", True):
                queue_client.redis.set(f"job:{job_id}:status", "pending_review", ex=86400)
                queue_client.notify_api_progress(job_id, phase, "Waiting for user review", data)
                
                logger.info(f"Job {job_id} waiting for Phase 2.5 review...")
                approved_script = await queue_client.wait_for_review(job_id, timeout_seconds=1800)
                
                queue_client.redis.set(f"job:{job_id}:status", "processing", ex=86400)
                if approved_script:
                    logger.info(f"Job {job_id} review approved. Resuming pipeline.")
                    return approved_script
                else:
                    logger.warning(f"Job {job_id} review timed out. Resuming with default script.")
                    return None
            return None

        # 4. Execute standard pipeline
        from pipeline import run_pipeline_v3
        
        cdp_url = os.getenv("CHROME_CDP_URL", config.get("cdp_url", "http://localhost:9222"))
        
        try:
            logger.info("Starting run_pipeline_v3...")
            video_path = await run_pipeline_v3(
                task=task_prompt,
                video_name=video_name,
                cdp_url=cdp_url,
                enable_tts=config.get("enable_tts", True),
                tts_voice=config.get("tts_voice", "banmai"),
                tts_engine=config.get("tts_engine", "edge"),
                padding_ms=int(os.getenv("PADDING_MS") or config.get("padding_ms") or 1000),
                enable_review=config.get("enable_review", True),
                job_id=job_id,
                agent_mode="presentation",
                progress_callback=progress_callback,
            )
            
            return {
                "status": "completed",
                "job_id": job_id,
                "video_path": str(video_path),
                "video_name": video_name,
                "completed_at": time.time(),
                "worker_id": WORKER_ID,
            }
        finally:
            # 5. Cleanup from OneDrive
            file_name_only = os.path.basename(pptx_path)
            logger.info(f"Cleaning up {file_name_only} from OneDrive...")
            delete_from_onedrive(file_name_only)
            
    except SessionExpiredError as e:
        logger.error(f"Job {job_id} thất bại: Session hết hạn - {e}", exc_info=True)
        # Circuit Breaker: tạm dừng queue
        import json
        queue_client = JobQueue()
        queue_client.pause_queue(QUEUE_NAME, f"session_expired: {e}")
        queue_client.redis.publish("session-expired", json.dumps({
            "queue": QUEUE_NAME,
            "job_id": job_id,
            "error": str(e),
            "timestamp": time.time(),
        }))
        return {
            "status": "failed",
            "job_id": job_id,
            "error": f"SESSION_EXPIRED: {e}",
            "error_type": "session_expired",
            "completed_at": time.time(),
            "worker_id": WORKER_ID,
        }

    except Exception as e:
        import traceback
        trace = traceback.format_exc()
        logger.error(f"Job {job_id} failed: {e}\n{trace}")
        return {
            "status": "failed",
            "job_id": job_id,
            "error": str(e),
            "traceback": trace,
            "failed_at": time.time(),
            "worker_id": WORKER_ID,
        }

def run_worker():
    """Main worker - processes ONE job then exits."""
    global _chrome_proc

    # Chrome is launched on-demand when a job arrives, not at startup.
    logger.info("Chrome will be launched on-demand when a job arrives")

    import atexit
    atexit.register(kill_chrome)

    queue = JobQueue()
    container_name = socket.gethostname()

    logger.info(f"Worker {WORKER_ID} started (container: {container_name})")
    logger.info(f"Queue: {QUEUE_NAME}")
    logger.info(f"Redis: {queue._sanitize_url(queue.redis_url)}")
    logger.info("Waiting for a job...")

    def is_chrome_alive():
        """Check if Chrome CDP is responsive."""
        import urllib.request
        import json as _json
        try:
            resp = urllib.request.urlopen("http://localhost:9222/json/version", timeout=2)
            return resp.status == 200
        except Exception:
            return False

    while True:
        try:
            job = queue.poll(QUEUE_NAME, timeout=POLL_TIMEOUT)
            if job is None:
                continue

            job_id = job.get("job_id", "unknown")
            logger.info(f"Picked up Job {job_id} from {QUEUE_NAME}")

            # Register this container as the worker for this job (for kill support)
            queue.register_worker(job_id, container_name)

            # Ensure Chrome is running before processing job
            if not is_chrome_alive():
                logger.info("Chrome not running. Starting for job...")
                try:
                    if _chrome_proc and _chrome_proc.poll() is None:
                        _chrome_proc.terminate()
                        try:
                            _chrome_proc.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            _chrome_proc.kill()
                    _chrome_proc = launch_chrome(port=9222)
                    logger.info("Chrome started successfully")
                except Exception as e:
                    logger.error(f"Chrome start failed: {e}")
                    queue.set_result(job_id, {
                        "status": "failed",
                        "error": f"Chrome failed to start: {e}",
                        "failed_at": time.time(),
                        "worker_id": WORKER_ID,
                    })
                    queue.ack(QUEUE_NAME, job)
                    queue.notify_api(job_id)
                    queue.unregister_worker(job_id)
                    break

            result = asyncio.run(process_job(job))

            queue.set_result(job_id, result)
            queue.ack(QUEUE_NAME, job)
            queue.notify_api(job_id)
            queue.unregister_worker(job_id)

            status = result.get("status", "unknown")
            logger.info(f"Job {job_id} -> {status}")

            # Single-job mode: exit after processing one job
            logger.info(f"Single-job mode: exiting after job {job_id}")
            break

        except KeyboardInterrupt:
            logger.info("Worker shutting down (Ctrl+C)")
            break
        except Exception as e:
            logger.error(f"Worker error: {e}", exc_info=True)
            time.sleep(2)

    kill_chrome()
    logger.info(f"Worker {WORKER_ID} stopped")

if __name__ == "__main__":
    run_worker()
