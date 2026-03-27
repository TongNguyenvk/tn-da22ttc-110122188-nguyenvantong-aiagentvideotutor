"""
Sync Recorder - Quay video DONG BO voi thuc thi kich ban.

Workflow:
  1. Focus cua so dich
  2. Bat dau quay FFmpeg gdigrab (capture vung cua so)
  3. Cho FFmpeg on dinh (1s)
  4. Thuc thi tung buoc trong plan, ghi execution trace
  5. Dung quay FFmpeg
  6. Tra ve (video_path, trace_path)

Trace output tuong thich 100% voi trace_composer.py de ghep audio sau.
"""

import time
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def record_with_script(
    plan: list[dict],
    target_pid: int,
    output_dir: str = "workspace",
    video_name: str = "recording",
    dry_run: bool = True,
    timeout_seconds: int = 120,
    mouse_duration: float = 0.5,
    framerate: int = 30,
) -> dict:
    """
    Quay video dong bo voi thuc thi kich ban.

    Args:
        plan: List cac action (tu vision_agent hoac tu tay).
        target_pid: PID cua cua so dich.
        output_dir: Thu muc output.
        video_name: Ten video (khong co .mp4).
        dry_run: True = chi mo phong, khong quay/bam that.
        timeout_seconds: Timeout tong.
        mouse_duration: Thoi gian di chuyen chuot (giay).
        framerate: FPS cho video.

    Returns:
        Dict voi:
            video_path: Duong dan file mp4 (None neu dry_run)
            trace_path: Duong dan file trace.json
            trace: ExecutionTrace object
    """
    from core.os_executor_v2 import execute_plan, focus_window_by_pid
    from core.media_engine import start_screen_recording, stop_recording
    from core.ui_inspector import get_element_tree

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    video_path = output_path / f"{video_name}.mp4"
    trace_path = output_path / f"{video_name}.trace.json"

    logger.info(f"{'='*60}")
    logger.info(f"  Sync Recorder: {video_name}")
    logger.info(f"  Mode: {'DRY-RUN' if dry_run else 'RECORDING'}")
    logger.info(f"  PID: {target_pid}")
    logger.info(f"  Steps: {len(plan)}")
    logger.info(f"{'='*60}")

    # Buoc 1: Focus cua so
    logger.info("Step 1: Focus window")
    if not dry_run:
        focus_window_by_pid(target_pid)
        time.sleep(0.5)

    # Buoc 2: Lay element tree (cache de khong phai lay lai moi buoc)
    logger.info("Step 2: Load element tree")
    element_tree = None
    if not dry_run:
        try:
            element_tree = get_element_tree(target_pid, max_depth=4)
            logger.info(f"Element tree loaded")
        except Exception as e:
            logger.warning(f"Could not get element tree: {e}")

    # Buoc 3: Bat dau quay video
    ffmpeg_process = None
    recording_start_time = time.time()
    if not dry_run:
        logger.info("Step 3: Start recording")
        ffmpeg_process = start_screen_recording(
            target_pid,
            str(video_path),
            framerate=framerate,
        )
        if ffmpeg_process is None:
            logger.error("Failed to start FFmpeg recording")
            return {
                "video_path": None,
                "trace_path": None,
                "trace": None,
                "error": "FFmpeg failed to start",
            }
        # Cho FFmpeg on dinh
        time.sleep(1.5)
        logger.info("Recording started, FFmpeg ready")
    else:
        logger.info("Step 3: [DRY-RUN] Skip recording")

    # Buoc 4: Thuc thi kich ban
    logger.info("Step 4: Execute plan")
    try:
        trace = execute_plan(
            plan=plan,
            target_pid=target_pid,
            dry_run=dry_run,
            timeout_seconds=timeout_seconds,
            mouse_duration=mouse_duration,
            element_tree=element_tree,
            recording_start_time=recording_start_time,
        )
    except Exception as e:
        logger.error(f"Execution error: {e}")
        # Van dung recording neu co loi
        if ffmpeg_process:
            stop_recording(ffmpeg_process)
        raise

    # Buoc 5: Dung quay
    if ffmpeg_process:
        logger.info("Step 5: Stop recording")
        # Cho 1 giay de video co tail pause
        time.sleep(1)
        stop_recording(ffmpeg_process)
        logger.info(f"Video saved: {video_path}")

    # Buoc 6: Luu trace
    logger.info("Step 6: Save trace")
    trace.save(str(trace_path))

    # Ket qua
    result = {
        "video_path": str(video_path) if not dry_run and video_path.exists() else None,
        "trace_path": str(trace_path),
        "trace": trace,
    }

    logger.info(f"{'='*60}")
    logger.info(f"  Done! Video: {result['video_path']}")
    logger.info(f"  Trace: {result['trace_path']} ({len(trace.entries)} steps)")
    logger.info(f"{'='*60}")

    return result


def record_demo(
    target_pid: int,
    output_dir: str = "workspace",
    dry_run: bool = True,
) -> dict:
    """
    Demo recording: kich ban don gian de test.
    Mo cua so, cho, di chuot quanh, bam vai phim.
    """
    demo_plan = [
        {
            "action_type": "wait",
            "target_value": "Waiting for window ready",
            "duration_ms": 1000,
        },
        {
            "action_type": "mouse_move",
            "target_value": "Move to center",
            "x": 500,
            "y": 400,
            "move_duration": 0.8,
        },
        {
            "action_type": "wait",
            "target_value": "Pause",
            "duration_ms": 500,
        },
        {
            "action_type": "mouse_move",
            "target_value": "Move to top-right area",
            "x": 900,
            "y": 200,
            "move_duration": 0.6,
        },
        {
            "action_type": "press_key",
            "target_value": "space",
            "duration_ms": 500,
        },
        {
            "action_type": "wait",
            "target_value": "Final pause",
            "duration_ms": 2000,
        },
    ]

    return record_with_script(
        plan=demo_plan,
        target_pid=target_pid,
        output_dir=output_dir,
        video_name="demo_recording",
        dry_run=dry_run,
    )
