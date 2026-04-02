"""
Webreel Runner: Infrastructure for recording videos with Webreel CLI.

Extracted from old run_pipeline_unified_chrome.py for V3 pipeline.
"""

import json
import logging
import os
import subprocess
import time
from pathlib import Path
import requests

logger = logging.getLogger(__name__)

# Log which file is being used
logger.info(f"[WEBREEL_RUNNER] Loaded from: {__file__}")

OUTPUT_DIR = Path("output")
# Read CDP URL from environment variable (for Docker), fallback to localhost
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
            # Use new browser_launcher module with Registry lookup
            try:
                # Parse port from check_url
                import urllib.parse
                parsed = urllib.parse.urlparse(check_url)
                target_port = parsed.port or 9222
                
                # Import browser launcher
                desktop_app_dir = Path(__file__).resolve().parents[1] / "desktop_app"
                sys.path.insert(0, str(desktop_app_dir))
                
                from browser_launcher import launch_chrome_with_cdp
                
                logger.info(f"[SRC] Using Registry-based Chrome launcher on port {target_port}...")
                logger.info(f"[SRC] Parsed from check_url: {check_url}")
                cdp_url = launch_chrome_with_cdp(port=target_port, kill_existing=True)
                logger.info(f"[SRC] Chrome launched via Registry: {cdp_url}")
                
                # Verify connection on the CORRECT port
                time.sleep(2)
                try:
                    response = requests.get(f"{check_url}/json/version", timeout=2)
                    chrome_info = response.json()
                    logger.info(f"Chrome ready: {chrome_info.get('Browser', 'Unknown')}")
                    return True
                except:
                    logger.error("Chrome started but CDP not responding")
                    return False
                
            except Exception as start_error:
                logger.error(f"Failed to start Chrome via Registry: {start_error}")
                logger.error("Please run start_chrome_debug.bat manually!")
                return False
        else:
            # Running in Docker/Linux - cannot auto-start Chrome on host
            logger.error("Running in Docker container. Chrome must be started on the host machine.")
            logger.error("Please run start-chrome-docker.bat on your Windows host!")
            return False



def record_video_with_webreel(config: dict, config_path: Path, video_name: str) -> Path:
    """
    Record video with webreel (calls node CLI).
    Webreel connects via CDP to replay actions with cursor animation.
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

    # Webreel binary
    WEBREEL_BIN = Path(__file__).resolve().parent.parent.parent / "packages" / "webreel" / "dist" / "index.js"
    REPO_ROOT = Path(__file__).resolve().parent.parent.parent

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
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        shell=True,
        cwd=str(REPO_ROOT),
        env=env,
        timeout=300,
        encoding='utf-8',
        errors='replace'
    )
    elapsed = time.time() - start_time

    if result.stdout:
        logger.info(f"[webreel stdout]:\n{result.stdout}")
    if result.stderr:
        logger.info(f"[webreel stderr]:\n{result.stderr}")

    if result.returncode != 0:
        logger.error(f"webreel failed (exit code {result.returncode}) after {elapsed:.1f}s")
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
