"""
Webreel Runner: Infrastructure for recording videos with Webreel CLI.

Desktop app version (self-contained).
"""

import json
import logging
import os
import subprocess
import time
import asyncio
from pathlib import Path
import requests
import sys

logger = logging.getLogger(__name__)

# Log which file is being used
logger.info(f"[WEBREEL_RUNNER] Loaded from: {__file__}")

# Desktop app paths
DESKTOP_APP_DIR = Path(__file__).parent
OUTPUT_DIR = DESKTOP_APP_DIR / "output"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Read CDP URL from environment variable, fallback to localhost
CDP_URL = os.getenv("CHROME_CDP_URL", "http://localhost:9222")


def check_chrome_debug_running(auto_start: bool = True, cdp_url: str = None) -> bool:
    """
    Check if Chrome is running with debug port enabled.
    If not running and auto_start=True, automatically start Chrome.
    
    Args:
        auto_start: Whether to auto-start Chrome if not running (only works on Windows host)
        cdp_url: CDP URL to check (defaults to CDP_URL global if not provided)
    """
    # Use provided cdp_url or fall back to global CDP_URL
    check_url = cdp_url or CDP_URL
    
    try:
        response = requests.get(f"{check_url}/json/version", timeout=2)
        chrome_info = response.json()
        logger.info(f"Chrome detected at {check_url}: {chrome_info.get('Browser', 'Unknown')}")
        return True
    except Exception as e:
        logger.warning(f"Cannot connect to Chrome debug port at {check_url}: {e}")

        if not auto_start:
            logger.error("Please run start_chrome_debug.bat first!")
            return False

        # Auto-start Chrome with debug port (only on Windows host, not in Docker)
        logger.info("Attempting to start Chrome with debug port...")

        if os.name == "nt":  # Windows
            # Use browser_launcher module with Registry lookup (local)
            try:
                # Parse port from check_url
                import urllib.parse
                parsed = urllib.parse.urlparse(check_url)
                target_port = parsed.port or 9222
                
                from browser_launcher import launch_chrome_with_cdp
                
                logger.info(f"[DESKTOP_APP] Using Registry-based Chrome launcher on port {target_port}...")
                logger.info(f"[DESKTOP_APP] Parsed from check_url: {check_url}")
                cdp_url = launch_chrome_with_cdp(port=target_port, kill_existing=False)
                logger.info(f"[DESKTOP_APP] Chrome launched via Registry: {cdp_url}")
                
                # Verify connection on the CORRECT port (retry up to 5 times)
                max_retries = 5
                for attempt in range(max_retries):
                    time.sleep(2)
                    try:
                        response = requests.get(f"{check_url}/json/version", timeout=3)
                        chrome_info = response.json()
                        logger.info(f"Chrome ready on port {target_port}: {chrome_info.get('Browser', 'Unknown')}")
                        return True
                    except Exception as e:
                        if attempt < max_retries - 1:
                            logger.warning(f"Chrome not ready yet (attempt {attempt + 1}/{max_retries}), retrying...")
                        else:
                            logger.error(f"Chrome started on port {target_port} but CDP not responding after {max_retries} attempts: {e}")
                            return False
                
            except Exception as start_error:
                logger.error(f"Failed to start Chrome via Registry: {start_error}")
                return False
        else:
            # Running in Docker/Linux - cannot auto-start Chrome on host
            logger.error("Running in Docker container. Chrome must be started on the host machine.")
            logger.error("Please run start-chrome-docker.bat on your Windows host!")
            return False



def record_video_with_webreel(config: dict, config_path: Path, video_name: str, cancel_event=None) -> Path:
    """
    Record video with webreel (calls node CLI).
    Webreel connects via CDP to replay actions with cursor animation.

    Args:
        config: Webreel config dict.
        config_path: Path to save config JSON.
        video_name: Name of the video.
        cancel_event: Optional asyncio.Event; if set, the subprocess will be killed.
    """
    logger.info("=" * 80)
    logger.info("Phase 5: webreel Record (with cursor)")
    logger.info("=" * 80)

    # Prune non-schema properties before saving to satisfy Webreel's strict JSON validation
    # NOTE: cdpUrl is a VALID schema property, so we keep it
    import copy
    clean_config = copy.deepcopy(config)
    for v_name, v_cfg in clean_config.get("videos", {}).items():
        # Remove only custom properties that are NOT part of schema
        for step in v_cfg.get("steps", []):
            if "tts_index" in step:
                del step["tts_index"]

    # Save config
    config_path.parent.mkdir(parents=True, exist_ok=True)
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(clean_config, f, indent=2, ensure_ascii=False)
    logger.info(f"Config saved: {config_path}")

    # Webreel binary (local copy in desktop_app)
    DESKTOP_APP_DIR = Path(__file__).resolve().parent
    WEBREEL_BIN = DESKTOP_APP_DIR / "webreel" / "packages" / "webreel" / "dist" / "index.js"
    REPO_ROOT = DESKTOP_APP_DIR  # Use desktop_app as working directory

    # Env variables
    env = os.environ.copy()
    if os.name != "nt":  # Not Windows
        env["FFMPEG_PATH"] = "/usr/bin/ffmpeg"

    headless_shell_path = Path.home() / ".webreel" / "bin" / "chrome-headless-shell"
    if headless_shell_path.exists():
        if os.name == "nt":  # Windows
            for item in headless_shell_path.rglob("chrome-headless-shell.exe"):
                env["CHROME_HEADLESS_PATH"] = str(item)
                logger.info(f"Set CHROME_HEADLESS_PATH={item}")
                break
        else:
            linux_shell = headless_shell_path / "chrome-headless-shell-linux64" / "chrome-headless-shell"
            if linux_shell.exists():
                env["CHROME_HEADLESS_PATH"] = str(linux_shell)
                logger.info(f"Set CHROME_HEADLESS_PATH={linux_shell}")

    cmd = f'node "{WEBREEL_BIN}" record {video_name} -c "{config_path.absolute()}" --verbose'
    logger.info(f"Running: {cmd}")

    start_time = time.time()

    # Use Popen so we can kill the process on cancel.
    # IMPORTANT: We use threads to drain stdout/stderr continuously to prevent
    # a deadlock where the child process blocks because the OS pipe buffer is
    # full (typically 4KB-64KB) while the parent waits for the child to finish.
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        shell=True,
        cwd=str(REPO_ROOT),
        env=env,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
    )

    # Drain stdout/stderr in background threads to prevent pipe buffer deadlock
    import threading
    stdout_chunks = []
    stderr_chunks = []

    def _drain_pipe(pipe, chunks):
        """Read from pipe until EOF, appending to chunks list."""
        try:
            while True:
                data = pipe.read(4096)
                if not data:
                    break
                chunks.append(data)
        except Exception:
            pass

    stdout_thread = threading.Thread(target=_drain_pipe, args=(proc.stdout, stdout_chunks), daemon=True)
    stderr_thread = threading.Thread(target=_drain_pipe, args=(proc.stderr, stderr_chunks), daemon=True)
    stdout_thread.start()
    stderr_thread.start()

    # Poll loop: check cancel_event every 0.5s
    cancelled = False
    while proc.poll() is None:
        if cancel_event and cancel_event.is_set():
            logger.info("Cancel requested, killing webreel subprocess...")
            _kill_process_tree(proc.pid)
            cancelled = True
            break
        time.sleep(0.5)

    # Wait for drain threads to finish (they will EOF when process exits)
    stdout_thread.join(timeout=5)
    stderr_thread.join(timeout=5)

    elapsed = time.time() - start_time

    if cancelled:
        raise asyncio.CancelledError("Webreel recording cancelled by user")

    stdout_data = b"".join(stdout_chunks).decode("utf-8", errors="replace")
    stderr_data = b"".join(stderr_chunks).decode("utf-8", errors="replace")

    if stdout_data:
        logger.info(f"[webreel stdout]:\n{stdout_data}")
    if stderr_data:
        logger.info(f"[webreel stderr]:\n{stderr_data}")

    if proc.returncode != 0:
        logger.error(f"webreel failed (exit code {proc.returncode}) after {elapsed:.1f}s")
        dry_cmd = f'node "{WEBREEL_BIN}" record {video_name} -c "{config_path.absolute()}" --dry-run'
        dry = subprocess.run(dry_cmd, capture_output=True, text=True, shell=True, cwd=str(REPO_ROOT), env=env, encoding='utf-8', errors='replace')
        if dry.stdout:
            logger.info(f"[dry-run]:\n{dry.stdout}")
        if dry.stderr:
            logger.info(f"[dry-run stderr]:\n{dry.stderr}")
    else:
        logger.info(f"webreel done in {elapsed:.1f}s")

    # Find video output - webreel outputs to different locations depending on version
    # Priority order:
    # 1. .webreel/raw/<name>.mp4 (current webreel behavior)
    # 2. videos/<name>.mp4 (older behavior)
    # 3. .webreel/videos/<name>.mp4 (even older)
    # 4. <config_dir>/*.mp4 (fallback, skip _final/_raw files)
    
    # Check .webreel/raw/ first (current webreel output location)
    raw_dir = config_path.parent / ".webreel" / "raw"
    if raw_dir.exists():
        for mp4 in raw_dir.glob("*.mp4"):
            logger.info(f"Video output: {mp4}")
            return mp4
    
    # Check videos/ directory
    video_dir = config_path.parent / "videos"
    if video_dir.exists():
        for mp4 in video_dir.glob("*.mp4"):
            logger.info(f"Video output: {mp4}")
            return mp4

    # Fallback: .webreel/videos/ (older webreel versions)
    webreel_dir = config_path.parent / ".webreel" / "videos"
    if webreel_dir.exists():
        for mp4 in webreel_dir.glob("*.mp4"):
            logger.info(f"Video output: {mp4}")
            return mp4

    # Fallback: search output directory (skip _final/_raw files)
    for mp4 in config_path.parent.glob("*.mp4"):
        if "_final" not in mp4.stem and "_raw" not in mp4.stem:
            logger.info(f"Video output: {mp4}")
            return mp4

    logger.error("No .mp4 output found")
    return config_path.parent / f"{video_name}.mp4"


def _kill_process_tree(pid: int):
    """Kill a process and all its children (Windows-compatible)."""
    try:
        if os.name == "nt":
            subprocess.run(
                f"taskkill /F /T /PID {pid}",
                shell=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        else:
            import signal
            os.killpg(os.getpgid(pid), signal.SIGTERM)
    except Exception as e:
        logger.warning(f"Failed to kill process tree {pid}: {e}")
