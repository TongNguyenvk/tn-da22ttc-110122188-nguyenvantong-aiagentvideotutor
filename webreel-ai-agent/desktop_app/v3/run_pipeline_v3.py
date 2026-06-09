"""
V3 Pipeline: The Final Pipeline (No AI Review)

6 clean phases, no guessing, no estimation:

Phase 1 (The Scout):    browser-use runs web, produces History + Narrations
Phase 2 (The Parser):   bu_to_webreel_v3 extracts Actions + tts_script
Phase 3 (Ground-Truth): FPT TTS generates MP3s, mutagen measures exact durations
Phase 4 (The Injector): Replace placeholder pauses with exact MP3 durations
Phase 5 (The Execution):Webreel records video + emits .trace.json
Phase 6 (The Composer): ffmpeg places MP3s at trace-derived timestamps

USAGE:
    python v3/run_pipeline_v3.py "Task description" --name video_name
"""

import asyncio
import json
import os
import sys
import shutil
from pathlib import Path

# Setup paths
V3_DIR = Path(__file__).parent
AGENT_DIR = V3_DIR.parent
SRC_DIR = AGENT_DIR / "src"

sys.path.insert(0, str(V3_DIR))
sys.path.insert(0, str(SRC_DIR))
sys.path.insert(0, str(AGENT_DIR))

# V3 modules
from bu_to_webreel_v3 import convert_history_to_config_and_script
from audio_injector import generate_tts_segments, inject_exact_pauses

# Reused modules from src/
from trace_composer import compose_video_from_trace
from tts import AudioSegment

# Reuse infrastructure from webreel_runner
from webreel_runner import (
    record_video_with_webreel,
    check_chrome_debug_running,
    OUTPUT_DIR,
    CDP_URL,
    logger,
)

# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------
import logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)


# ---------------------------------------------------------------------------
# Phase 1: The Scout
# ---------------------------------------------------------------------------
async def phase1_scout(task: str, cdp_url: str) -> dict:
    """Run browser-use agent with save_narration tool to gather content."""
    logger.info("=" * 80)
    logger.info("Phase 1: The Scout (browser-use + narration extraction)")
    logger.info("=" * 80)

    # Check Chrome before starting browser-use
    if not check_chrome_debug_running(auto_start=True):
        raise RuntimeError("Chrome not available. Cannot proceed with browser-use.")

    # Import browser-use
    sys.path.insert(0, str(AGENT_DIR / "browser-use"))
    from browser_use import Agent, Browser, BrowserProfile, ChatGoogle, Controller, ActionResult

    # LLM
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY not found in .env")

    llm = ChatGoogle(
        model=os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite"),
        api_key=api_key,
    )

    # Custom action: save_narration
    controller = Controller()

    @controller.registry.action(
        "Viết lời thuyết minh cho trang hiện tại như một giảng viên đang giảng bài cho sinh viên. "
        "KHÔNG sao chép nguyên văn nội dung trang. Hãy giải thích một cách hấp dẫn, dễ hiểu. "
        "PHẢI viết tiếng Việt CÓ DẤU đầy đủ. Gọi hàm này TRƯỚC mỗi hành động trình duyệt."
    )
    async def save_narration(text: str):
        """Save narration script for the current page."""
        logger.info(f"Narration: {text[:80]}...")
        return ActionResult(
            extracted_content=f"Content saved: {text}. "
            f"If the task is now complete, please call the 'done' action immediately."
        )

    # Browser: create a new tab via BrowserProfile
    browser = Browser(
        cdp_url=cdp_url,
        keep_alive=True,
    )

    logger.info(f"Task: {task}")

    # Agent prompt
    agent_instructions = (
        "You are a charismatic Vietnamese LECTURER creating an educational video. "
        "Your job is to EXPLAIN concepts to students, NOT just read text from the page. "
        "Write narration as if you are talking to students in a classroom.\n\n"
        "CRITICAL: You MUST write in Vietnamese WITH FULL DIACRITICS (co dau). "
        "Example: 'Chung ta' is WRONG, 'Chúng ta' is CORRECT. "
        "'Bai hoc' is WRONG, 'Bài học' is CORRECT. Always use proper Vietnamese diacritics.\n\n"
        "NARRATION STYLE RULES:\n"
        "- Start with a hook: 'Chào mừng các bạn đến với bài học...'\n"
        "- Use transitional phrases: 'Bây giờ chúng ta sẽ tìm hiểu...', 'Điều đặc biệt là...'\n"
        "- Explain WHY things matter, not just WHAT they are\n"
        "- Use analogies and comparisons to make concepts relatable\n"
        "- End each narration with anticipation: 'Ở slide tiếp theo, chúng ta sẽ khám phá...'\n"
        "- Keep each narration 2-4 sentences. Do NOT write a wall of text.\n\n"
        "WORKFLOW:\n"
        "1. Read the page content carefully\n"
        "2. Call `save_narration` with your LECTURER-STYLE explanation (NOT a copy of the page text)\n"
        "3. Then perform the browser action (click next, etc.)\n\n"
        "LOOP EXIT RULES (MANDATORY): "
        "When the task is complete (e.g., last page reached, congratulation screen), "
        "call `save_narration` ONCE for a short closing remark, "
        "then IMMEDIATELY call the `done` action. "
        "DO NOT repeat `save_narration` on the same page. DO NOT summarize all slides again."
    )

    agent = Agent(
        task=task,
        llm=llm,
        browser=browser,
        controller=controller,
        extend_system_message=agent_instructions,
        max_steps=20,
    )

    logger.info("Running agent...")
    history = await agent.run()

    # Build history_data
    history_data = {
        "task": task,
        "is_done": history.is_done(),
        "is_successful": history.is_successful(),
        "final_result": history.final_result(),
        "number_of_steps": history.number_of_steps(),
        "action_names": history.action_names(),
        "urls": history.urls(),
        "model_actions": [],
    }

    for action in history.model_actions():
        if action.get("interacted_element") is not None:
            action["interacted_element"] = str(action["interacted_element"])
        history_data["model_actions"].append(action)

    logger.info(f"Completed {history.number_of_steps()} steps")
    logger.info(f"Actions: {history.action_names()}")

    return history_data


# ---------------------------------------------------------------------------
# Phase 2: The Parser
# ---------------------------------------------------------------------------
def phase2_parser(history_data: dict, video_name: str) -> tuple[dict, list]:
    """Parse history into webreel config + tts_script."""
    logger.info("=" * 80)
    logger.info("Phase 2: The Parser (config + tts_script extraction)")
    logger.info("=" * 80)

    config, tts_script = convert_history_to_config_and_script(
        history_data, video_name=video_name
    )

    step_count = len(config["videos"][video_name]["steps"])
    logger.info(f"Generated {step_count} steps, {len(tts_script)} narrations")

    return config, tts_script


# ---------------------------------------------------------------------------
# Phase 3: Ground-Truth TTS
# ---------------------------------------------------------------------------
def phase3_tts(
    tts_script: list,
    output_dir: Path,
    voice: str = "banmai",
    engine: str = "fpt",
) -> list:
    """Generate TTS audio and measure exact durations."""
    logger.info("=" * 80)
    engine_name = "Edge TTS" if engine == "edge" else "FPT.AI"
    logger.info(f"Phase 3: Ground-Truth TTS ({engine_name} + mutagen)")
    logger.info("=" * 80)

    if not tts_script:
        logger.warning("No narration scripts. Skipping TTS.")
        return []

    audio_dir = output_dir / "audio"

    segments = generate_tts_segments(
        tts_script=tts_script,
        output_dir=audio_dir,
        voice=voice,
        engine=engine,
    )

    valid = sum(1 for s in segments if s is not None)
    logger.info(f"Generated {valid}/{len(segments)} audio files successfully")

    return segments


# ---------------------------------------------------------------------------
# Phase 4: The Injector
# ---------------------------------------------------------------------------
def phase4_injector(
    config: dict,
    video_name: str,
    segments: list,
    padding_ms: int = 800,
) -> dict:
    """Replace placeholder pauses with exact TTS durations."""
    logger.info("=" * 80)
    logger.info("Phase 4: The Injector (exact pause replacement)")
    logger.info("=" * 80)

    if not segments:
        logger.warning("No audio segments. Skipping injection.")
        return config

    config = inject_exact_pauses(
        config=config,
        video_name=video_name,
        segments=segments,
        padding_ms=padding_ms,
    )

    return config


# ---------------------------------------------------------------------------
# Phase 5: The Execution
# ---------------------------------------------------------------------------
def phase5_execution(
    config: dict,
    config_path: Path,
    video_name: str,
    cdp_url: str,
) -> Path:
    """Record video with Webreel (also emits .trace.json)."""
    logger.info("=" * 80)
    logger.info("Phase 5: The Execution (Webreel recording)")
    logger.info("=" * 80)

    # Pass CDP URL directly to Webreel (standard Chrome CDP)
    config["videos"][video_name]["cdpUrl"] = cdp_url

    # Record
    video_path = record_video_with_webreel(config, config_path, video_name)

    return video_path


# ---------------------------------------------------------------------------
# Phase 6: The Composer
# ---------------------------------------------------------------------------
def phase6_composer(
    video_path: Path,
    config_path: Path,
    segments: list,
    output_dir: Path,
    video_name: str,
) -> Path:
    """Place MP3s at trace-derived timestamps using ffmpeg."""
    logger.info("=" * 80)
    logger.info("Phase 6: The Composer (trace-driven ffmpeg)")
    logger.info("=" * 80)

    if not video_path.exists():
        logger.error(f"Video not found: {video_path}")
        return video_path

    if not segments or not any(segments):
        logger.info("No audio segments. Returning raw video.")
        return video_path

    # Preserve raw video
    raw_video_path = video_path.parent / f"{video_path.stem}_raw{video_path.suffix}"
    shutil.copy2(video_path, raw_video_path)
    logger.info(f"Raw video preserved: {raw_video_path}")

    # Find trace
    trace_path = config_path.parent / ".webreel" / "traces" / f"{video_name}.trace.json"
    if not trace_path.exists():
        logger.error(f"Trace not found: {trace_path}")
        logger.warning("Cannot compose without trace. Returning raw video.")
        return raw_video_path

    # Collect audio file paths
    audio_files = [
        seg.audio_path if seg else None
        for seg in segments
    ]

    final_path = output_dir / f"{video_name}_final.mp4"

    try:
        result = compose_video_from_trace(
            video_path=raw_video_path,
            trace_path=trace_path,
            audio_files=audio_files,
            output_path=final_path,
        )
        logger.info(f"Final video: {result}")
        return Path(result)
    except Exception as e:
        logger.error(f"Compose failed: {e}")
        import traceback
        traceback.print_exc()
        return raw_video_path


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------
async def run_pipeline_v3(
    task: str,
    video_name: str = "demo",
    cdp_url: str = CDP_URL,
    enable_tts: bool = True,
    tts_voice: str = "banmai",
    tts_engine: str = "fpt",
    padding_ms: int = 300,
    progress = None,
) -> Path:
    """
    V3 Pipeline: 6 phases, no AI review, deterministic.

    Args:
        task: Task description for browser-use agent.
        video_name: Output video name.
        cdp_url: Chrome DevTools Protocol URL.
        enable_tts: Enable TTS generation.
        tts_voice: Voice name (banmai/leminh/etc).
        tts_engine: TTS engine ("fpt" or "edge").
        padding_ms: Padding added to each narration pause.
        progress: Optional progress tracker for UI updates.
    """
    output_dir = OUTPUT_DIR / video_name
    output_dir.mkdir(parents=True, exist_ok=True)

    # Phase 1: The Scout (includes Chrome check with auto-start)
    if progress:
        progress.update(1, "Phase 1: Browser-use agent running...")
    history_data = await phase1_scout(task, cdp_url)

    # Save history
    history_path = output_dir / "browser_use_history.json"
    with open(history_path, "w", encoding="utf-8") as f:
        json.dump(history_data, f, indent=2, ensure_ascii=False, default=str)
    logger.info(f"History saved: {history_path}")

    # Phase 2: The Parser
    if progress:
        progress.update(2, "Phase 2: Parsing actions...")
    config, tts_script = phase2_parser(history_data, video_name)

    # Save tts_script for debugging
    tts_script_path = output_dir / "tts_script.json"
    with open(tts_script_path, "w", encoding="utf-8") as f:
        json.dump(tts_script, f, indent=2, ensure_ascii=False)
    logger.info(f"TTS script: {tts_script_path} ({len(tts_script)} segments)")

    # Phase 3: Ground-Truth TTS
    segments = []
    if enable_tts and tts_script:
        if progress:
            progress.update(3, "Phase 3: Generating TTS audio...")
        segments = await phase3_tts(tts_script, output_dir, voice=tts_voice, engine=tts_engine)

    # Phase 4: The Injector
    if segments:
        if progress:
            progress.update(4, "Phase 4: Injecting audio pauses...")
        config = phase4_injector(config, video_name, segments, padding_ms)

    # Phase 5: The Execution
    if progress:
        progress.update(5, "Phase 5: Recording video with Webreel...")
    config_path = output_dir / "webreel_pipeline.config.json"
    video_path = phase5_execution(config, config_path, video_name, cdp_url)

    # Phase 6: The Composer
    final_video_path = video_path
    if segments and video_path and video_path.exists():
        if progress:
            progress.update(6, "Phase 6: Composing final video...")
        final_video_path = phase6_composer(
            video_path=video_path,
            config_path=config_path,
            segments=segments,
            output_dir=output_dir,
            video_name=video_name,
        )

    # Summary
    logger.info("=" * 80)
    logger.info("V3 PIPELINE COMPLETED!")
    logger.info("=" * 80)
    logger.info(f"History:     {history_path}")
    logger.info(f"TTS Script:  {tts_script_path}")
    logger.info(f"Config:      {config_path}")
    logger.info(f"Video (raw): {video_path}")
    if final_video_path != video_path:
        logger.info(f"Video (TTS): {final_video_path}")

    trace_path = config_path.parent / ".webreel" / "traces" / f"{video_name}.trace.json"
    if trace_path.exists():
        logger.info(f"Trace:       {trace_path}")
    logger.info("=" * 80)

    if progress:
        progress.update(6, "Pipeline completed!")

    return final_video_path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="V3 Pipeline: The Final Pipeline (No AI Review)"
    )
    parser.add_argument("task", help="Task description")
    parser.add_argument("--name", "-n", default="demo", help="Video name")
    parser.add_argument("--cdp-url", default=CDP_URL, help="Chrome CDP URL")
    parser.add_argument("--no-tts", action="store_true", help="Disable TTS")
    parser.add_argument(
        "--voice",
        default="banmai",
        choices=["banmai", "leminh", "myan", "lannhi", "linhsan"],
        help="TTS voice (default: banmai)",
    )
    parser.add_argument(
        "--engine",
        default="fpt",
        choices=["fpt", "edge"],
        help="TTS engine: fpt (FPT.AI) or edge (Edge TTS) (default: fpt)",
    )
    parser.add_argument(
        "--padding",
        type=int,
        default=300,
        help="Padding ms added to each narration pause (default: 300)",
    )

    args = parser.parse_args()

    # Load .env
    from dotenv import load_dotenv
    env_path = AGENT_DIR / ".env"
    if env_path.exists():
        load_dotenv(env_path)

    video_path = asyncio.run(run_pipeline_v3(
        task=args.task,
        video_name=args.name,
        cdp_url=args.cdp_url,
        enable_tts=not args.no_tts,
        tts_voice=args.voice,
        tts_engine=args.engine,
        padding_ms=args.padding,
    ))

    if video_path:
        print(f"\nDone! Video: {video_path}")
    else:
        print("\nFailed!")
        sys.exit(1)
