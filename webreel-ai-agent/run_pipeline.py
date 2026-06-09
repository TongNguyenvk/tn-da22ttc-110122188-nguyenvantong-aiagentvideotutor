"""
V3 Pipeline: The Final Pipeline (No AI Review)

6 clean phases, no guessing, no estimation:

Phase 1 (The Scout):    browser-use runs web, produces History + Narrations
Phase 2 (The Parser):   bu_to_webreel extracts Actions + tts_script
Phase 3 (Ground-Truth): FPT TTS generates MP3s, ffprobe measures exact durations
Phase 4 (The Injector): Replace placeholder pauses with exact MP3 durations
Phase 5 (The Execution):Webreel records video + emits .trace.json
Phase 6 (The Composer): ffmpeg places MP3s at trace-derived timestamps

USAGE:
    python run_pipeline.py "Task description" --name video_name
"""

import asyncio
import json
import os
import sys
import shutil
from pathlib import Path


# ---------------------------------------------------------------------------
# Stop flag and Review pause mechanism (per-job)
# ---------------------------------------------------------------------------
_stop_flags = {}  # job_id -> bool
_review_pause_events = {}  # job_id -> asyncio.Event
_reviewed_scripts = {}  # job_id -> list

def set_stop_flag(job_id: str, value: bool):
    """Set the stop flag for a specific job."""
    global _stop_flags
    _stop_flags[job_id] = value

def get_stop_flag(job_id: str = None) -> bool:
    """Get the stop flag for a specific job."""
    if job_id is None:
        return False
    return _stop_flags.get(job_id, False)

def clear_stop_flag(job_id: str):
    """Clear the stop flag for a job."""
    global _stop_flags
    if job_id in _stop_flags:
        del _stop_flags[job_id]

def set_review_pause_event(job_id: str, event):
    """Set the asyncio Event for Phase 2.5 pause for a specific job."""
    global _review_pause_events
    _review_pause_events[job_id] = event

def get_review_pause_event(job_id: str = None):
    """Get the asyncio Event for Phase 2.5 pause for a specific job."""
    if job_id is None:
        return None
    return _review_pause_events.get(job_id)

def clear_review_pause_event(job_id: str):
    """Clear the pause event for a job."""
    global _review_pause_events
    if job_id in _review_pause_events:
        del _review_pause_events[job_id]

def set_reviewed_script(job_id: str, script: list):
    """Set the reviewed script for a specific job."""
    global _reviewed_scripts
    _reviewed_scripts[job_id] = script

def get_reviewed_script(job_id: str = None):
    """Get the reviewed script for a specific job."""
    if job_id is None:
        return None
    return _reviewed_scripts.get(job_id)

def clear_reviewed_script(job_id: str):
    """Clear the reviewed script for a job."""
    global _reviewed_scripts
    if job_id in _reviewed_scripts:
        del _reviewed_scripts[job_id]

# Setup paths
AGENT_DIR = Path(__file__).parent
V3_DIR = AGENT_DIR / "v3"
SRC_DIR = AGENT_DIR / "src"

sys.path.insert(0, str(V3_DIR))
sys.path.insert(0, str(SRC_DIR))
sys.path.insert(0, str(AGENT_DIR))

# V3 modules
from bu_to_webreel import convert_history_to_config_and_script
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
    if not check_chrome_debug_running(auto_start=True, cdp_url=cdp_url):
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

    # Browser: connect to existing Chrome instance
    browser = Browser(
        cdp_url=cdp_url,
        keep_alive=True,
    )

    logger.info(f"Task: {task}")
    
    # Start browser connection
    await browser.start()
    
    # Strategy: Instead of creating new tab, navigate existing tab to blank
    # This ensures browser-use uses the correct tab
    try:
        all_pages = await browser.get_pages()
        if all_pages:
            # Use the first page and navigate it to blank
            page = all_pages[0]
            await page.goto('about:blank')
            logger.info(f"Navigated existing tab to blank (clean state)")
        else:
            # No pages exist, create new one
            page = await browser.new_page('about:blank')
            logger.info(f"Created new clean tab for job")
    except Exception as e:
        logger.warning(f"Failed to prepare clean tab: {e}")
        # Fallback: just create new page
        page = await browser.new_page('about:blank')
        logger.info(f"Created new tab as fallback")

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
# Phase 2.5: CLI Review TTS Script
# ---------------------------------------------------------------------------
def _print_segment(idx: int, segment: dict):
    """Pretty-print a single narration segment."""
    text = segment.get("text", "")
    print(f"  [{idx}] {text}")


def phase2_5_review_tts_script(tts_script: list, config: dict, video_name: str) -> list:
    """Interactive CLI review of TTS narration segments.

    Users can view, edit, delete, or add segments before TTS generation.
    Returns the (possibly modified) tts_script list.
    """
    logger.info("=" * 80)
    logger.info("Phase 2.5: Review TTS Script (interactive CLI)")
    logger.info("=" * 80)

    if not tts_script:
        print("\n  (No narration segments to review.)")
        return tts_script

    # Show all segments
    def _show_all():
        print("\n" + "=" * 60)
        print(f"  TTS Script - {len(tts_script)} segment(s)")
        print("=" * 60)
        for i, seg in enumerate(tts_script):
            _print_segment(i, seg)
            print()
        print("=" * 60)

    _show_all()

    print("\n  Commands:")
    print("    e <n>       Edit segment n")
    print("    d <n>       Delete segment n")
    print("    a <n>       Add new segment after n (use -1 for start)")
    print("    s           Show all segments again")
    print("    ok          Accept and continue pipeline")
    print("    q           Abort pipeline\n")

    while True:
        try:
            cmd = input("  review> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            raise SystemExit("Pipeline aborted by user.")

        if not cmd:
            continue

        parts = cmd.split(maxsplit=1)
        action = parts[0].lower()

        # --- Accept ---
        if action == "ok":
            break

        # --- Abort ---
        if action == "q":
            raise SystemExit("Pipeline aborted by user.")

        # --- Show ---
        if action == "s":
            _show_all()
            continue

        # --- Edit ---
        if action == "e":
            if len(parts) < 2 or not parts[1].isdigit():
                print("  Usage: e <segment_number>")
                continue
            idx = int(parts[1])
            if idx < 0 or idx >= len(tts_script):
                print(f"  Invalid index. Valid range: 0-{len(tts_script) - 1}")
                continue
            print(f"  Current text [{idx}]:")
            print(f"    {tts_script[idx]['text']}")
            print("  Enter new text (empty line to cancel):")
            try:
                new_text = input("    > ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\n  Edit cancelled.")
                continue
            if new_text:
                old_text = tts_script[idx]["text"]
                tts_script[idx]["text"] = new_text
                # Also update the corresponding pause description in config
                _sync_narration_to_config(config, video_name, idx, new_text)
                print(f"  Segment [{idx}] updated.")
            else:
                print("  Edit cancelled.")
            continue

        # --- Delete ---
        if action == "d":
            if len(parts) < 2 or not parts[1].isdigit():
                print("  Usage: d <segment_number>")
                continue
            idx = int(parts[1])
            if idx < 0 or idx >= len(tts_script):
                print(f"  Invalid index. Valid range: 0-{len(tts_script) - 1}")
                continue
            print(f"  Deleting segment [{idx}]: {tts_script[idx]['text'][:60]}...")
            _remove_narration_from_config(config, video_name, idx)
            tts_script.pop(idx)
            # Re-index remaining segments
            for i, seg in enumerate(tts_script):
                seg["narration_index"] = i
            _reindex_narrations_in_config(config, video_name, tts_script)
            print(f"  Deleted. {len(tts_script)} segment(s) remaining.")
            continue

        # --- Add ---
        if action == "a":
            if len(parts) < 2 or not parts[1].lstrip("-").isdigit():
                print("  Usage: a <position> (insert after this index, -1 for start)")
                continue
            pos = int(parts[1])
            if pos < -1 or pos >= len(tts_script):
                print(f"  Invalid position. Valid range: -1 to {len(tts_script) - 1}")
                continue
            print("  Enter narration text (empty line to cancel):")
            try:
                new_text = input("    > ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\n  Add cancelled.")
                continue
            if new_text:
                insert_at = pos + 1
                new_seg = {"text": new_text, "narration_index": insert_at}
                tts_script.insert(insert_at, new_seg)
                # Re-index
                for i, seg in enumerate(tts_script):
                    seg["narration_index"] = i
                _insert_narration_into_config(config, video_name, insert_at, new_text)
                _reindex_narrations_in_config(config, video_name, tts_script)
                print(f"  Inserted segment [{insert_at}]. {len(tts_script)} segment(s) total.")
            else:
                print("  Add cancelled.")
            continue

        print(f"  Unknown command: {action}. Type 'ok' to continue or 's' to show segments.")

    logger.info(f"Review complete. {len(tts_script)} segment(s) accepted.")
    return tts_script


# ---------------------------------------------------------------------------
# Config sync helpers for Phase 2.5
# ---------------------------------------------------------------------------
def _find_narration_steps(config: dict, video_name: str) -> list[tuple[int, dict]]:
    """Find all pause steps that are narration placeholders, returns (step_index, step)."""
    steps = config["videos"][video_name]["steps"]
    results = []
    for i, step in enumerate(steps):
        desc = step.get("description", "")
        if step.get("action") == "pause" and desc.startswith("[NARRATION:"):
            results.append((i, step))
    return results


def _sync_narration_to_config(config: dict, video_name: str, narration_idx: int, new_text: str):
    """Update the pause step description for a given narration index."""
    narration_steps = _find_narration_steps(config, video_name)
    for step_i, step in narration_steps:
        desc = step.get("description", "")
        if desc.startswith(f"[NARRATION:{narration_idx}]"):
            step["description"] = f"[NARRATION:{narration_idx}] {new_text}"
            break


def _remove_narration_from_config(config: dict, video_name: str, narration_idx: int):
    """Remove the pause step for a deleted narration."""
    steps = config["videos"][video_name]["steps"]
    for i, step in enumerate(steps):
        desc = step.get("description", "")
        if step.get("action") == "pause" and desc.startswith(f"[NARRATION:{narration_idx}]"):
            steps.pop(i)
            break


def _insert_narration_into_config(config: dict, video_name: str, insert_at: int, text: str):
    """Insert a new narration pause step into config at the right position."""
    steps = config["videos"][video_name]["steps"]
    narration_steps = _find_narration_steps(config, video_name)

    if not narration_steps:
        # No existing narrations; insert before the tail pause
        insert_pos = max(0, len(steps) - 1)
    elif insert_at > 0 and insert_at - 1 < len(narration_steps):
        # Insert after the previous narration step
        insert_pos = narration_steps[insert_at - 1][0] + 1
    elif insert_at == 0:
        # Insert before the first narration step
        insert_pos = narration_steps[0][0]
    else:
        # Insert after the last narration step
        insert_pos = narration_steps[-1][0] + 1

    new_step = {
        "action": "pause",
        "ms": 1000,
        "description": f"[NARRATION:{insert_at}] {text}",
    }
    steps.insert(insert_pos, new_step)


def _reindex_narrations_in_config(config: dict, video_name: str, tts_script: list):
    """Re-number all [NARRATION:X] descriptions to match current tts_script order."""
    import re as _re
    steps = config["videos"][video_name]["steps"]
    narration_counter = 0
    for step in steps:
        desc = step.get("description", "")
        if step.get("action") == "pause" and desc.startswith("[NARRATION:"):
            if narration_counter < len(tts_script):
                text = tts_script[narration_counter]["text"]
                step["description"] = f"[NARRATION:{narration_counter}] {text}"
                narration_counter += 1


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
    logger.info(f"Phase 3: Ground-Truth TTS ({engine_name} + ffprobe)")
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
    enable_review: bool = False,
    job_id: str = None,
    progress = None,
    progress_callback = None,
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
        job_id: Unique job identifier for stop flag tracking.
        progress: Optional progress tracker for UI updates (legacy).
        progress_callback: Optional async callback function(phase: int, message: str) for progress updates.
    """
    output_dir = OUTPUT_DIR / video_name
    output_dir.mkdir(parents=True, exist_ok=True)

    # Phase 1: The Scout (includes Chrome check with auto-start)
    if progress_callback:
        await progress_callback(1, "Phase 1: Browser-use agent running...")
    if progress:
        progress.update(1, "Phase 1: Browser-use agent running...")
    
    if job_id and get_stop_flag(job_id):
        logger.info(f"Job {job_id}: Stopped before Phase 1")
        raise SystemExit("Pipeline stopped by user")
    
    history_data = await phase1_scout(task, cdp_url)

    # Check stop flag after Phase 1
    if job_id and get_stop_flag(job_id):
        logger.info(f"Job {job_id}: Stopped after Phase 1")
        raise SystemExit("Pipeline stopped by user")

    # Save history
    history_path = output_dir / "browser_use_history.json"
    with open(history_path, "w", encoding="utf-8") as f:
        json.dump(history_data, f, indent=2, ensure_ascii=False, default=str)
    logger.info(f"History saved: {history_path}")

    # Phase 2: The Parser
    if progress_callback:
        await progress_callback(2, "Phase 2: Parsing actions...")
    if progress:
        progress.update(2, "Phase 2: Parsing actions...")
    
    if job_id and get_stop_flag(job_id):
        logger.info(f"Job {job_id}: Stopped before Phase 2")
        raise SystemExit("Pipeline stopped by user")
    
    config, tts_script = phase2_parser(history_data, video_name)

    # Check stop flag after Phase 2
    if job_id and get_stop_flag(job_id):
        logger.info(f"Job {job_id}: Stopped after Phase 2")
        raise SystemExit("Pipeline stopped by user")

    # Save tts_script for debugging
    tts_script_path = output_dir / "tts_script.json"
    with open(tts_script_path, "w", encoding="utf-8") as f:
        json.dump(tts_script, f, indent=2, ensure_ascii=False)
    logger.info(f"TTS script: {tts_script_path} ({len(tts_script)} segments)")

    # Phase 2.5: Review TTS Script (CLI only)
    if enable_review and tts_script:
        if progress_callback:
            await progress_callback(2, "Phase 2.5: Waiting for TTS script review...")
        if progress:
            progress.update(2, "Phase 2.5: Waiting for TTS script review...")
        tts_script = phase2_5_review_tts_script(tts_script, config, video_name)
        # Save updated tts_script
        with open(tts_script_path, "w", encoding="utf-8") as f:
            json.dump(tts_script, f, indent=2, ensure_ascii=False)
        logger.info(f"TTS script updated after review: {len(tts_script)} segments")
    
    # Phase 2.5 Web: Pause for web UI review
    elif not enable_review and tts_script:
        # Web UI mode - pause and wait for user review
        if progress_callback:
            await progress_callback(2.5, "Phase 2.5: Waiting for user to review TTS script...")
        if progress:
            progress.update(2.5, "Phase 2.5: Waiting for user to review TTS script...")
        
        logger.info("=" * 80)
        logger.info("Phase 2.5: Web UI Review (waiting for user input)")
        logger.info("=" * 80)
        
        # Get the pause event
        pause_event = get_review_pause_event(job_id)
        if pause_event:
            # Wait for user to submit reviewed script
            logger.info("Waiting for user to review and submit TTS script...")
            await pause_event.wait()
            
            # Check stop flag after resume
            if job_id and get_stop_flag(job_id):
                logger.info(f"Job {job_id}: Stopped during Phase 2.5 review")
                raise SystemExit("Pipeline stopped by user")
            
            # Get reviewed script from global state
            reviewed = get_reviewed_script(job_id)
            if reviewed:
                tts_script = reviewed
                clear_reviewed_script(job_id)
                
                # Update config with reviewed script
                for i, seg in enumerate(tts_script):
                    seg["narration_index"] = i
                _reindex_narrations_in_config(config, video_name, tts_script)
                
                # Save updated tts_script
                with open(tts_script_path, "w", encoding="utf-8") as f:
                    json.dump(tts_script, f, indent=2, ensure_ascii=False)
                logger.info(f"TTS script updated after web review: {len(tts_script)} segments")
            else:
                logger.warning("No reviewed script received, using original")
        else:
            logger.warning("No pause event set, skipping web review")

    # Phase 3: Ground-Truth TTS
    segments = []
    if enable_tts and tts_script:
        if progress_callback:
            await progress_callback(3, "Phase 3: Generating TTS audio...")
        if progress:
            progress.update(3, "Phase 3: Generating TTS audio...")
        
        if job_id and get_stop_flag(job_id):
            logger.info(f"Job {job_id}: Stopped before Phase 3")
            raise SystemExit("Pipeline stopped by user")
        
        segments = phase3_tts(tts_script, output_dir, voice=tts_voice, engine=tts_engine)
        
        if job_id and get_stop_flag(job_id):
            logger.info(f"Job {job_id}: Stopped after Phase 3")
            raise SystemExit("Pipeline stopped by user")

    # Phase 4: The Injector
    if segments:
        if progress_callback:
            await progress_callback(4, "Phase 4: Injecting audio pauses...")
        if progress:
            progress.update(4, "Phase 4: Injecting audio pauses...")
        
        if job_id and get_stop_flag(job_id):
            logger.info(f"Job {job_id}: Stopped before Phase 4")
            raise SystemExit("Pipeline stopped by user")
        
        config = phase4_injector(config, video_name, segments, padding_ms)

    # Phase 5: The Execution
    if progress_callback:
        await progress_callback(5, "Phase 5: Recording video with Webreel...")
    if progress:
        progress.update(5, "Phase 5: Recording video with Webreel...")
    
    if job_id and get_stop_flag(job_id):
        logger.info(f"Job {job_id}: Stopped before Phase 5")
        raise SystemExit("Pipeline stopped by user")
    
    config_path = output_dir / "webreel_pipeline.config.json"
    video_path = phase5_execution(config, config_path, video_name, cdp_url)
    
    if job_id and get_stop_flag(job_id):
        logger.info(f"Job {job_id}: Stopped after Phase 5")
        raise SystemExit("Pipeline stopped by user")

    # Phase 6: The Composer
    final_video_path = video_path
    if segments and video_path and video_path.exists():
        if progress_callback:
            await progress_callback(6, "Phase 6: Composing final video...")
        if progress:
            progress.update(6, "Phase 6: Composing final video...")
        
        if job_id and get_stop_flag(job_id):
            logger.info(f"Job {job_id}: Stopped before Phase 6")
            raise SystemExit("Pipeline stopped by user")
        
        final_video_path = phase6_composer(
            video_path=video_path,
            config_path=config_path,
            segments=segments,
            output_dir=output_dir,
            video_name=video_name,
        )
        
        if job_id and get_stop_flag(job_id):
            logger.info(f"Job {job_id}: Stopped after Phase 6")
            raise SystemExit("Pipeline stopped by user")

    # Clean up job-specific state
    if job_id:
        clear_stop_flag(job_id)
        clear_review_pause_event(job_id)
        clear_reviewed_script(job_id)
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
    parser.add_argument(
        "--review",
        action="store_true",
        default=False,
        help="Pause after Phase 2 to review/edit TTS narration scripts in CLI",
    )
    parser.add_argument(
        "--no-review",
        dest="review",
        action="store_false",
        help="Skip TTS script review (default behavior)",
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
        enable_review=args.review,
    ))

    if video_path:
        print(f"\nDone! Video: {video_path}")
    else:
        print("\nFailed!")
        sys.exit(1)
