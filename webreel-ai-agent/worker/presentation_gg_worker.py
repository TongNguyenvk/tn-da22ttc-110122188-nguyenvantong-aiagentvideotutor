"""
Presentation GG Worker - Polls Redis presentation-gg-queue and runs the Google Slides pipeline.

This acts as a standalone worker for Google Drive / Google Slides integration.
Usage:
    python -m worker.presentation_gg_worker
"""

import asyncio
import logging
import os
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
logger = logging.getLogger("presentation_gg_worker")

QUEUE_NAME = os.getenv("WORKER_QUEUE", "presentation-gg-queue")
POLL_TIMEOUT = int(os.getenv("POLL_TIMEOUT", "5"))
WORKER_ID = os.getenv("WORKER_ID", f"pres-gg-worker-{os.getpid()}")

# Increase navigation timeout for slow-loading pages
os.environ.setdefault("TIMEOUT_NavigateToUrlEvent", "60")  # 60 seconds
os.environ.setdefault("TIMEOUT_BrowserStateRequestEvent", "45")  # 45 seconds

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
    return ""  

def launch_chrome(port: int = 9222) -> subprocess.Popen:
    """Launch headless Chrome with CDP on the given port."""
    chrome_bin = _find_chromium_path()
    if not chrome_bin:
        logger.warning("Chromium executable not found. Fallback to default Chrome if on Windows.")
        chrome_bin = "chrome"

    # Use dedicated profile for presentation-gg-worker to avoid conflicts
    chrome_profile = os.getenv("CHROME_PROFILE_DIR", "/app/chrome_profile")
    logger.info(f"Launching Chrome: {chrome_bin} on port {port} with profile {chrome_profile}")

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
        f"--user-data-dir={chrome_profile}",
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
        except Exception as e:
            # Check if Chrome crashed during startup
            if proc.poll() is not None:
                logger.error(f"Chrome crashed during startup!")
                logger.error(f"Exit code: {proc.returncode}")
                raise RuntimeError(f"Chrome failed to start: exit code {proc.returncode}")
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

async def process_job(job: dict) -> dict:
    job_id = job.get("job_id", "unknown")
    config = job.get("config", {})
    pptx_path = config.get("pptx_path", "")
    video_name = job.get("video_name", f"pres_gg_{int(time.time())}")

    # Convert relative path to absolute path if needed
    if not pptx_path.startswith("/"):
        pptx_path = f"/app/{pptx_path}"

    logger.info(f"Processing Google Presentation Job {job_id} for file {pptx_path}")

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

        from shared.google_drive_oauth import upload_to_gdrive_oauth, delete_from_gdrive_oauth
        
        # 1. Upload to Google Drive and convert to Google Slides
        logger.info("Uploading file to Google Drive via OAuth...")
        drive_info = upload_to_gdrive_oauth(pptx_path)
        file_id = drive_info["file_id"]
        presentation_url = drive_info["presentation_url"]
        logger.info(f"File uploaded. Presentation URL: {presentation_url}")
        
        # 2. Extract slide texts from local pptx
        sys.path.insert(0, str(AGENT_DIR / "desktop_app"))
        from slide_pipeline.extractor import extract_text_from_pptx
        
        logger.info("Extracting texts from PPTX...")
        slides = extract_text_from_pptx(Path(pptx_path))
        
        # 3. Build optimized prompt for Google Slides with /present URL
        logger.info(f"Using Google Slides presentation URL: {presentation_url}")
        
        num_slides = len(slides)
        
        # Build prompt optimized for Google Slides presentation mode.
        # English instructions (Gemini tokenises Vietnamese ~2.5x denser),
        # Vietnamese examples + slide titles where needed. Output (narrations
        # via save_narration) MUST be Vietnamese — that's the only thing the
        # learner ever hears.
        task_prompt = (
            f"You are a Vietnamese UNIVERSITY LECTURER recording a video "
            f"lecture from a {num_slides}-slide Google Slides deck.\n\n"
        )

        task_prompt += "=== TASK ===\n"
        task_prompt += (
            "For each slide: READ on-screen content (title + bullets + any visible "
            "notes), write a natural lecture-style narration (in Vietnamese), call "
            "`save_narration` to store it, then press ArrowRight to advance.\n\n"
        )

        task_prompt += "=== NAVIGATION ===\n"
        task_prompt += f"1. Open URL: {presentation_url}\n"
        task_prompt += "   This URL opens DIRECTLY in full-screen presentation mode — do NOT click anything to start.\n"
        task_prompt += "2. Wait 15s for slide 1 to load.\n"
        task_prompt += f"3. Loop for {num_slides} slides:\n"
        task_prompt += "   - Slide 1 (already on screen): READ content → call `save_narration` IMMEDIATELY (no keypress before).\n"
        task_prompt += "   - Then: press ArrowRight → wait 3s → READ new slide → call `save_narration` → repeat.\n"
        task_prompt += f"4. After the LAST slide ({num_slides}), call `save_narration` with a closing remark, then call `done` immediately.\n\n"

        task_prompt += "=== KEYS ===\n"
        task_prompt += "- ArrowRight or Space: next slide\n"
        task_prompt += "- NEVER click the mouse, NEVER click the slide, NEVER press Escape.\n"
        task_prompt += "- Exactly ONE ArrowRight per slide.\n\n"

        task_prompt += "=== LECTURE STYLE (MOST IMPORTANT) ===\n"
        task_prompt += (
            "This is a LECTURE VIDEO, not slide-reading. The audience is STUDENTS "
            "learning the material for the first time. Every narration must:\n\n"
        )
        task_prompt += (
            "1. **Academic but warm**: use 'chúng ta' (we), 'các bạn' (you all). "
            "Avoid robotic phrasing like 'Slide này cho thấy...' (this slide shows). "
            "Use openings like 'Chúng ta sẽ cùng tìm hiểu...', 'Điểm mấu chốt ở đây là...', "
            "'Các bạn có thể hình dung...'.\n\n"
        )
        task_prompt += (
            "2. **Explain, do NOT recite**: if the slide says 'A is B', do not just "
            "repeat it — explain WHY A is B, or what the concept MEANS. Translate "
            "abstract concepts into everyday language.\n\n"
        )
        task_prompt += (
            "3. **Illustrative example WHEN USEFUL** (not every slide): if the slide "
            "presents an abstract concept, definition, or principle, add ONE short "
            "example sentence even if the slide doesn't show one. Examples should be "
            "relatable to Vietnamese students (school life, daily life, common "
            "technology). If the slide ALREADY has a concrete example, chart, or "
            "data — skip the extra example, just guide the audience through it.\n\n"
        )
        task_prompt += (
            "4. **Smooth transitions**: from slide 2 onwards, open with a short "
            "bridging phrase referencing the previous slide ('Sau khi đã hiểu... "
            "bây giờ chúng ta sẽ...', 'Tiếp nối ý vừa rồi...'). The final slide "
            "ends with a summary or a teaser for what comes next.\n\n"
        )
        task_prompt += (
            "5. **First slide**: start with a brief greeting + topic intro "
            "('Xin chào các bạn. Hôm nay chúng ta sẽ cùng tìm hiểu về...').\n\n"
        )

        task_prompt += "=== LENGTH & LANGUAGE ===\n"
        task_prompt += "- 4-7 sentences per slide. Long enough to teach, short enough to keep pace.\n"
        task_prompt += "- Section divider / title-only slides can be shorter (2-3 sentences).\n"
        task_prompt += (
            "- Output language: VIETNAMESE WITH FULL DIACRITICS. Missing diacritics = "
            "serious error. Example: 'Bài học' (correct), 'Bai hoc' (WRONG).\n"
        )
        task_prompt += "- No emoji, no markdown, no bullet lists — write complete sentences so TTS sounds natural.\n"
        task_prompt += (
            "- Acronyms: expand on first mention, then introduce the abbreviation "
            "('Work Breakdown Structure, viết tắt là WBS').\n\n"
        )

        task_prompt += "=== SLIDE TITLES (CONTEXT) ===\n"
        for idx, slide in enumerate(slides):
            first_line = slide.texts[0] if slide.texts else f"Slide {idx + 1}"
            if len(first_line) > 80:
                first_line = first_line[:77] + "..."
            task_prompt += f"   {idx + 1}. {first_line}\n"
        task_prompt += (
            "\nNote: titles above are pre-extracted context only. When narrating, "
            "READ the actual on-screen content (slides may have bullets/notes not "
            "in this list) and base your narration on what's VISIBLE.\n"
        )
        
        logger.info(f"Generated Google Slides task prompt:\n{task_prompt}")
        
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
                agent_mode="presentation_gg",
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
            # 5. Cleanup from Google Drive
            logger.info(f"Cleaning up file ID {file_id} from Google Drive...")
            delete_from_gdrive_oauth(file_id)
            
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

    # Chrome is launched on-demand when first job arrives
    logger.info("Chrome will be launched on-demand when first job arrives")

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
                    # Kill old process if exists
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
                    # Mark job as failed and exit
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
