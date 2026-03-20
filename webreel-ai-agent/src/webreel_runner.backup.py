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

OUTPUT_DIR = Path("output")
CDP_URL = "http://localhost:9222"


def check_chrome_debug_running(auto_start: bool = True) -> bool:
    """
    Check if Chrome is running with debug port enabled.
    If not running and auto_start=True, automatically start Chrome.
    """
    try:
        response = requests.get(f"{CDP_URL}/json/version", timeout=2)
        chrome_info = response.json()
        logger.info(f"Chrome detected: {chrome_info.get('Browser', 'Unknown')}")
        return True
    except Exception as e:
        logger.warning(f"Cannot connect to Chrome debug port: {e}")

        if not auto_start:
            logger.error("Please run start_chrome_debug.bat first!")
            return False

        # Auto-start Chrome with debug port
        logger.info("Attempting to start Chrome with debug port...")

        if os.name == "nt":  # Windows
            chrome_path = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
            user_data_dir = r"C:\ChromeDebugProfile"

            cmd = [
                chrome_path,
                "--remote-debugging-port=9222",
                f"--user-data-dir={user_data_dir}",
                "--no-first-run",
                "--no-default-browser-check"
            ]

            try:
                subprocess.Popen(
                    cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
                )
                logger.info("Chrome started. Waiting for debug port...")

                # Wait for Chrome to be ready
                for i in range(10):
                    time.sleep(1)
                    try:
                        response = requests.get(f"{CDP_URL}/json/version", timeout=2)
                        chrome_info = response.json()
                        logger.info(f"Chrome ready: {chrome_info.get('Browser', 'Unknown')}")
                        return True
                    except:
                        continue

                logger.error("Chrome started but debug port not responding after 10s")
                return False

            except Exception as start_error:
                logger.error(f"Failed to start Chrome: {start_error}")
                logger.error("Please run start_chrome_debug.bat manually!")
                return False
        else:
            logger.error("Auto-start only supported on Windows. Please start Chrome manually.")
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
    )
    elapsed = time.time() - start_time

    if result.stdout:
        logger.info(f"[webreel stdout]:\n{result.stdout}")
    if result.stderr:
        logger.info(f"[webreel stderr]:\n{result.stderr}")

    if result.returncode != 0:
        logger.error(f"webreel failed (exit code {result.returncode}) after {elapsed:.1f}s")
        dry_cmd = f'node "{WEBREEL_BIN}" record {video_name} -c "{config_path.absolute()}" --dry-run'
        dry = subprocess.run(dry_cmd, capture_output=True, text=True, shell=True, cwd=str(REPO_ROOT), env=env)
        if dry.stdout:
            logger.info(f"[dry-run]:\n{dry.stdout}")
        if dry.stderr:
            logger.info(f"[dry-run stderr]:\n{dry.stderr}")
    else:
        logger.info(f"webreel done in {elapsed:.1f}s")

    # Find video output - webreel outputs to <config_dir>/videos/<name>.mp4
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
