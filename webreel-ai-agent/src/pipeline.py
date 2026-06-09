"""
Core pipeline: Natural Language -> webreel.config.json -> record video.

Tach ra de ca CLI (main.py) va Streamlit UI (app.py) cung su dung.
"""
import os
import subprocess
from pathlib import Path
from typing import Callable, Optional
from dotenv import load_dotenv

from .parser import parse_natural_language
from .vision import VisionLocator, locate_element_by_vision
from .locator import extract_selector_from_coordinates, extract_input_selector, validate_selector
from .generator import generate_webreel_config, save_config
from .models import ParsedAction, ResolvedAction

load_dotenv()

# Progress callback type: (step, total_steps, message)
ProgressCallback = Callable[[int, int, str], None]

# Set MOCK_MODE=1 in .env to test the UI without any API or browser.
MOCK_MODE: bool = os.environ.get("MOCK_MODE", "0") == "1"


def _no_op_callback(step: int, total: int, message: str) -> None:
    """Default no-op callback (CLI mode)."""
    print(f"[{step}/{total}] {message}")


def _run_mock_pipeline(
    user_input: str,
    video_name: str,
    output_dir: str,
    callback: ProgressCallback,
) -> Path:
    """Simulate the full pipeline with fake delays - use for UI testing."""
    import time
    TOTAL = 4
    steps = [
        (1, "Phan tich kich ban (DEMO MODE)..."),
        (2, "Mo trinh duyet gia - tim elements (DEMO MODE)..."),
        (3, "Tao file cau hinh webreel (DEMO MODE)..."),
        (4, "Quay video (DEMO MODE)..."),
    ]
    for step_num, msg in steps:
        callback(step_num, TOTAL, msg)
        time.sleep(1.5)

    # Write a tiny placeholder config so the path chain doesn't crash
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    fake_video = out / f"{video_name}-demo.mp4"
    fake_video.write_bytes(b"")  # empty placeholder
    callback(TOTAL, TOTAL, f"DEMO HOAN THANH - file gia: {fake_video}")
    return fake_video


def run_pipeline(
    user_input: str,
    video_name: str = "demo",
    output_dir: str = "videos",
    on_progress: Optional[ProgressCallback] = None,
) -> Path:
    """
    Full pipeline: NL -> parse -> vision -> config -> record.

    Args:
        user_input: Lenh tu nguoi dung (tieng Viet hoac tieng Anh).
        video_name: Ten video va config key.
        output_dir: Thu muc luu video.
        on_progress: Callback nhan (current_step, total_steps, message).
                     Neu None, in ra stdout.

    Returns:
        Path den file video da quay.

    Raises:
        ValueError: Neu khong tim thay URL trong input.
        RuntimeError: Neu webreel CLI that bai.
    """
    callback = on_progress or _no_op_callback
    _fpt_key = os.environ.get("FPT_TTS_API_KEY", "")
    TOTAL_STEPS = 5 if _fpt_key else 4

    if MOCK_MODE:
        return _run_mock_pipeline(user_input, video_name, output_dir, callback)

    # --- Step 1: Parse NL ---
    callback(1, TOTAL_STEPS, "Phan tich kich ban...")

    actions: list[ParsedAction] = parse_natural_language(user_input)

    navigate_action = next(
        (a for a in actions if a.action == "navigate" and a.url), None
    )
    if not navigate_action:
        raise ValueError(
            "Khong tim thay URL trong kich ban. "
            "Vui long them website can mo (vi du: 'Mo vnexpress.net')."
        )
    start_url: str = navigate_action.url  # type: ignore[assignment]

    # --- Step 2: Vision AI + DOM selector ---
    callback(2, TOTAL_STEPS, f"Mo trinh duyet - tim elements tren {start_url}...")

    resolved_actions: list[ResolvedAction] = []

    with VisionLocator() as locator:
        locator.navigate(start_url)

        for action in actions:
            if action.action in ("click", "type") and action.target:
                screenshot_b64 = locator.screenshot_base64()
                coords = locate_element_by_vision(screenshot_b64, action.target)

                selector = None
                if coords.x >= 0 and coords.y >= 0:
                    if action.action == "type":
                        selector = extract_input_selector(locator.page, coords.x, coords.y)
                    if not selector:
                        selector = extract_selector_from_coordinates(
                            locator.page, coords.x, coords.y
                        )
                    if selector:
                        validate_selector(locator.page, selector, coords.x, coords.y)

                resolved_actions.append(
                    ResolvedAction(**action.model_dump(), selector=selector, coordinates=coords)
                )
            else:
                resolved_actions.append(ResolvedAction(**action.model_dump()))

    # --- Step 3: Generate webreel config ---
    callback(3, TOTAL_STEPS, "Tao file cau hinh webreel...")

    config = generate_webreel_config(video_name, start_url, resolved_actions)
    save_config(config)

    # --- Step 4: Record video ---
    callback(4, TOTAL_STEPS, "Dang quay video (co the mat 30-60 giay)...")

    webreel_bin = os.environ.get("WEBREEL_BIN")
    if not webreel_bin:
        monorepo_dist = (
            Path(__file__).resolve().parents[2]
            / "packages" / "webreel" / "dist" / "index.js"
        )
        webreel_bin = f"node {monorepo_dist}" if monorepo_dist.exists() else "npx webreel"

    cmd = f"{webreel_bin} record {video_name}"
    result = subprocess.run(
        cmd, shell=True, env={**os.environ},
        capture_output=True, text=True,
    )

    if result.returncode != 0:
        raise RuntimeError(
            f"webreel that bai (exit {result.returncode}):\n{result.stderr}"
        )

    output_path = Path(output_dir) / f"{video_name}.mp4"

    # --- Step 5 (optional): TTS voiceover ---
    if _fpt_key:
        callback(5, TOTAL_STEPS, "Tao giong doc huong dan (FPT TTS)...")
        try:
            from .tts import build_narration_texts, generate_speech_batch
            narrations = build_narration_texts(resolved_actions)
            audio_dir = Path(output_dir) / f"{video_name}_audio"
            generate_speech_batch(narrations, audio_dir, api_key=_fpt_key)
            callback(5, TOTAL_STEPS, f"Da tao {len(narrations)} file audio trong {audio_dir}")
        except Exception as tts_err:
            # TTS that bai khong lam dung pipeline, chi bao cao
            callback(5, TOTAL_STEPS, f"TTS bi bo qua: {tts_err}")

    callback(TOTAL_STEPS, TOTAL_STEPS, f"Hoan thanh! Video: {output_path}")
    return output_path


def get_parsed_preview(user_input: str) -> list[ParsedAction]:
    """
    Chi parse NL, khong chay browser.
    Dung de preview cac buoc truoc khi generate.
    """
    return parse_natural_language(user_input)
