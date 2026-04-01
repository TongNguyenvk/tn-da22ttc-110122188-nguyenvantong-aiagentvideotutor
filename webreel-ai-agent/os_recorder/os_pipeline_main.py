"""
OS Pipeline V3 with Dual Output - Pipeline tích hợp đầy đủ:
  Phase 1 (Plan):   Agent dò đường + sinh plan.json + narrations
  Phase 2 (TTS):    Sinh audio từ narrations bằng Edge TTS
  Phase 2.5 (Inject): Inject exact TTS durations vào plan.json
  Phase 3 (Record): Replay plan.json + quay FFmpeg + chụp screenshots
  Phase 4 (Mix):    Ghép audio vào video bằng trace_composer
  Phase 5 (Render): Tạo DOCX + PDF từ screenshots (parallel)

Flow:
  Input:  PID ứng dụng + task description
  Output: video_final.mp4 + tutorial.docx + tutorial.pdf
"""

import json
import time
import logging
import re
import sys
import asyncio
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def run_os_pipeline_v3_dual(
    target_pid: int,
    task_description: str,
    output_dir: str = "workspace/output",
    video_name: str = "os_video",
    voice: str = "banmai",
    max_agent_steps: int = 15,
    dry_run: bool = False,
    skip_tts: bool = False,
    app_executable: str = None,
    enable_dual_output: bool = True,
    progress_callback=None,
    cancel_event=None,
    review_event=None,
    review_result_holder=None,
    ready_event=None,
) -> dict:
    """
    Pipeline V3 với Dual Output: Video + Document + PDF

    Args:
        target_pid: PID của ứng dụng đích.
        task_description: Mô tả task cho Agent.
        output_dir: Thư mục output gốc (sẽ tạo subfolder cho mỗi video).
        video_name: Tên video output.
        voice: Giọng TTS (banmai/leminh).
        max_agent_steps: Số bước tối đa cho Agent.
        dry_run: True = không thực thi, chỉ sinh plan + TTS.
        skip_tts: True = bỏ qua TTS.
        app_executable: Đường dẫn executable để khởi động lại.
        enable_dual_output: True = tạo cả document và PDF, False = chỉ video.

    Returns:
        Dict chứa đường dẫn các file output.
    """
    # Tạo cấu trúc thư mục giống desktop_app
    # output/video_name/
    base_output = Path(output_dir)
    project_dir = base_output / video_name
    project_dir.mkdir(parents=True, exist_ok=True)
    
    # Tạo các subfolder
    agent_dir = project_dir / "agent"
    audio_dir = project_dir / "audio"
    screenshots_dir = project_dir / "screenshots"
    
    agent_dir.mkdir(exist_ok=True)
    audio_dir.mkdir(exist_ok=True)
    if enable_dual_output:
        screenshots_dir.mkdir(exist_ok=True)

    result = {
        "plan_path": None,
        "video_raw_path": None,
        "video_final_path": None,
        "trace_path": None,
        "audio_files": [],
        "narrations": [],
        "screenshots": [],
        "document_path": None,
        "pdf_path": None,
    }

    # Khởi tạo screenshot capture (sẽ update PID sau khi restart)
    screenshot_capture = None
    if enable_dual_output:
        # Add dual_output_pipeline to path
        DUAL_OUTPUT_DIR = Path(__file__).parent.parent / "dual_output_pipeline"
        sys.path.insert(0, str(DUAL_OUTPUT_DIR / "core"))
        
        from screenshot_capture import ScreenshotCapture
        screenshot_capture = ScreenshotCapture(screenshots_dir, target_pid=target_pid)
        logger.info(f"  [Dual-Output] Screenshot capture enabled (PID={target_pid})")

    # ================================================================
    # PHASE 1: Agent dò đường (Silent, không chiếm chuột)
    # ================================================================
    logger.info(f"\n{'='*60}")
    logger.info(f"  PHASE 1: Agent dò đường")
    logger.info(f"  Task: {task_description[:60]}")
    logger.info(f"  PID: {target_pid}")
    logger.info(f"{'='*60}")

    from core.os_planning_agent_v2 import OSPlanningAgent

    agent = OSPlanningAgent(
        pid=target_pid,
        user_task=task_description,
        max_steps=max_agent_steps,
        output_dir=str(agent_dir),
    )

    try:
        agent_result = agent.run(dry_run=dry_run)
    except RuntimeError as e:
        logger.error(f"\n  PIPELINE DỪNG: Agent thất bại - {e}")
        result["error"] = str(e)
        return result

    plan_path = agent_dir / "plan.json"
    result["plan_path"] = str(plan_path)

    # Trích xuất narrations từ plan.json
    narrations = []
    with open(plan_path, "r", encoding="utf-8") as f:
        plan = json.load(f)

    # Kiểm tra plan có hành động thật không
    real_actions = [a for a in plan if a.get("action_type") not in ("pause",)]
    if not real_actions:
        logger.error(f"\n  PIPELINE DỪNG: Plan không có hành động nào")
        result["error"] = "Plan rỗng"
        return result

    for item in plan:
        desc = item.get("description", "")
        match = re.search(r"\[NARRATION:(\d+)\]\s*(.*)", desc)
        if match:
            narr_idx = int(match.group(1))
            narr_text = match.group(2).strip()
            if narr_text:
                narrations.append({"index": narr_idx, "text": narr_text})

    result["narrations"] = narrations
    logger.info(f"  Plan: {plan_path} ({len(plan)} actions, {len(real_actions)} thật)")
    logger.info(f"  Narrations: {len(narrations)}")

    # Progress callback
    if progress_callback:
        progress_callback(1.0, f"Phase 1 hoàn tất: {len(real_actions)} hành động, {len(narrations)} lời thoại")

    # Check cancellation
    if cancel_event and cancel_event.is_set():
        logger.info("Pipeline cancelled after Phase 1")
        return result

    # ================================================================
    # PHASE 2.5: Review TTS Script (UI callback)
    # ================================================================
    if narrations and review_event and review_result_holder is not None:
        logger.info(f"\n{'='*60}")
        logger.info(f"  PHASE 2.5: Review TTS Script ({len(narrations)} segments)")
        logger.info(f"{'='*60}")

        if progress_callback:
            progress_callback(2.5, "Phase 2.5: Chờ review lời thoại...", narrations)

        review_event.wait()
        review_event.clear()

        if cancel_event and cancel_event.is_set():
            logger.info("Pipeline cancelled during Phase 2.5")
            return result

        # Apply reviewed narrations
        reviewed = review_result_holder.get("reviewed_script")
        if reviewed:
            narrations = reviewed
            result["narrations"] = narrations
            logger.info(f"  Review accepted: {len(narrations)} segments")

            # Update plan.json
            narration_idx = 0
            for step in plan:
                desc = step.get("description", "")
                match_step = re.match(r"\[NARRATION:(\d+)\]", desc)
                if match_step and narration_idx < len(narrations):
                    step["description"] = f"[NARRATION:{narration_idx}] {narrations[narration_idx]['text']}"
                    narration_idx += 1

            with open(plan_path, "w", encoding="utf-8") as f:
                json.dump(plan, f, indent=2, ensure_ascii=False)
            logger.info("  Plan.json updated with reviewed narrations")

    # ================================================================
    # PHASE 2: TTS - Sinh audio từ narrations (PARALLEL)
    # ================================================================
    audio_files = []

    if not skip_tts and narrations:
        logger.info(f"\n{'='*60}")
        logger.info(f"  PHASE 2: TTS ({len(narrations)} narrations) - PARALLEL")
        logger.info(f"{'='*60}")

        # audio_dir already created at the beginning

        try:
            import edge_tts
            logger.info("  TTS Engine: Edge TTS (Async)")
            use_edge = True
        except ImportError:
            from core.tts import generate_speech
            logger.info("  TTS Engine: FPT.AI (Sequential)")
            use_edge = False

        if use_edge:
            # Parallel TTS generation with asyncio.gather
            from core.tts_edge import _generate_speech_async, EDGE_VOICES, DEFAULT_VOICE
            
            async def generate_all_tts():
                tasks = []
                for narr in narrations:
                    idx = narr["index"]
                    text = narr["text"]
                    audio_path = audio_dir / f"narration_{idx:03d}.mp3"
                    logger.info(f"  [{idx}] Queued: {text[:50]}...")
                    tasks.append(_generate_speech_async(text, audio_path, voice))
                
                logger.info(f"  Executing {len(tasks)} TTS requests in parallel...")
                results = await asyncio.gather(*tasks, return_exceptions=True)
                return results
            
            tts_results = asyncio.run(generate_all_tts())
            
            for idx, (narr, tts_result) in enumerate(zip(narrations, tts_results)):
                if isinstance(tts_result, Exception):
                    logger.error(f"  [{narr['index']}] TTS failed: {tts_result}")
                    audio_files.append(None)
                else:
                    audio_files.append({"path": str(tts_result.audio_path), "duration_ms": tts_result.duration_ms})
                    logger.info(f"  [{narr['index']}] -> {tts_result.audio_path.name} ({tts_result.duration_ms}ms)")
        else:
            # Fallback: Sequential for FPT.AI
            for narr in narrations:
                idx = narr["index"]
                text = narr["text"]
                audio_path = audio_dir / f"narration_{idx:03d}.mp3"

                try:
                    logger.info(f"  [{idx}] {text[:50]}...")
                    seg = generate_speech(
                        text=text,
                        output_path=audio_path,
                        voice=voice,
                    )
                    audio_files.append({"path": str(audio_path), "duration_ms": seg.duration_ms})
                    logger.info(f"       -> {audio_path.name} ({seg.duration_ms}ms)")
                except Exception as e:
                    logger.error(f"       -> TTS failed: {e}")
                    audio_files.append(None)

        result["audio_files"] = [a["path"] if a else None for a in audio_files]

    # Check cancellation after TTS
    if cancel_event and cancel_event.is_set():
        logger.info("Pipeline cancelled after Phase 2 (TTS)")
        return result

    # ================================================================
    # PHASE 2.5: Inject exact TTS durations
    # ================================================================
    if audio_files and any(a for a in audio_files if a):
        logger.info(f"\n{'='*60}")
        logger.info(f"  PHASE 2.5 (Injector): Exact TTS durations")
        logger.info(f"{'='*60}")

        padding_ms = 300

        with open(plan_path, "r", encoding="utf-8") as f:
            plan = json.load(f)

        for step in plan:
            desc = step.get("description", "")
            match = re.match(r"\[NARRATION:(\d+)\]", desc)
            if not match:
                continue

            idx = int(match.group(1))
            duration_ms = 0
            for a in audio_files:
                if a and isinstance(a, dict):
                    audio_name = f"narration_{idx:03d}.mp3"
                    if audio_name in a["path"]:
                        duration_ms = a["duration_ms"]
                        break

            exact_pause = (duration_ms + padding_ms) if duration_ms > 0 else 3000
            step["duration_ms"] = exact_pause

        with open(plan_path, "w", encoding="utf-8") as f:
            json.dump(plan, f, indent=2, ensure_ascii=False)

    # ================================================================
    # CLEANUP STATE - Bo qua, nguoi dung tu reset o buoc "San sang quay"
    # ================================================================
    current_pid = target_pid


    # ================================================================
    # PHASE 3: Record-Replay + Screenshot Capture (SONG SONG)
    # ================================================================
    if not dry_run:
        if progress_callback:
            progress_callback(3.0, "Sẵn sàng quay. Hãy reset trạng thái ứng dụng rồi bấm Xác nhận.")
            if ready_event:
                ready_event.wait()
                ready_event.clear()
            if cancel_event and cancel_event.is_set():
                logger.info("Pipeline cancelled before Phase 3")
                return result
        else:
            print("\n" + "*"*60)
            print("  [DỪNG CHỜ] AGENT ĐÃ LÊN KỊCH BẢN & SINH AUDIO XONG!")
            print("  Xin bạn hãy thủ công Undo (Ctrl+Z) hoặc khôi phục file")
            print("  về lại chính xác y như trạng thái ban đầu.")
            print("*"*60)
            input("  >>> BẤM PHÍM [ENTER] ĐỂ TIẾN HÀNH QUAY... <<<")
        
        logger.info(f"\n{'='*60}")
        logger.info(f"  PHASE 3: Record-Replay + Screenshot Capture")
        logger.info(f"{'='*60}")

        from core.os_planning_agent import replay_plan_with_recording

        # Tạo callback để chụp ảnh sau mỗi action
        if enable_dual_output and screenshot_capture:
            logger.info(f"  [Dual-Output] Screenshot capture enabled during replay")
            
            def screenshot_callback(step_index, step_data):
                """Callback được gọi sau mỗi action"""
                try:
                    screenshot_path = screenshot_capture.capture_step_with_highlight(
                        step_index=step_index,
                        step_data=step_data,
                        delay_ms=100,
                        max_retries=3
                    )
                    
                    if screenshot_path:
                        result["screenshots"].append(screenshot_path)
                        logger.info(f"    [Screenshot] Step {step_index}: {screenshot_path}")
                    else:
                        # Fallback: placeholder
                        placeholder = screenshot_capture.create_placeholder_image(
                            step_index, "Screenshot failed"
                        )
                        result["screenshots"].append(placeholder)
                        logger.warning(f"    [Screenshot] Step {step_index}: Using placeholder")
                        
                except Exception as e:
                    logger.error(f"    [Screenshot] Error at step {step_index}: {e}")
        else:
            screenshot_callback = None

        # Chạy replay với screenshot callback
        replay_result = replay_plan_with_recording(
            plan_path=str(plan_path),
            target_pid=current_pid,
            output_dir=str(project_dir),
            video_name=video_name,
            screenshot_callback=screenshot_callback,
            cancel_event=cancel_event,
        )

        # Check if replay was cancelled
        if replay_result.get("cancelled"):
            logger.info("Pipeline cancelled during Phase 3 (Recording)")
            return result

        result["video_raw_path"] = replay_result.get("video_path")
        result["trace_path"] = replay_result.get("trace_path")

        logger.info(f"  Video: {result['video_raw_path']}")
        logger.info(f"  Trace: {result['trace_path']}")
        logger.info(f"  Screenshots: {len(result['screenshots'])} captured")

    # ================================================================
    # PHASE 4: Mix audio vào video
    # ================================================================
    if (
        not dry_run
        and result["video_raw_path"]
        and result["trace_path"]
        and result.get("audio_files")
        and any(a for a in result["audio_files"] if a)
    ):
        # Check cancellation before Phase 4
        if cancel_event and cancel_event.is_set():
            logger.info("Pipeline cancelled before Phase 4 (Mix)")
            result["video_final_path"] = result.get("video_raw_path")
            return result

        logger.info(f"\n{'='*60}")
        logger.info(f"  PHASE 4: Mix audio + video")
        logger.info(f"{'='*60}")

        from core.trace_composer import compose_video_from_trace

        final_video = project_dir / f"{video_name}_final.mp4"

        try:
            compose_video_from_trace(
                video_path=result["video_raw_path"],
                trace_path=result["trace_path"],
                audio_files=[a for a in result["audio_files"] if a],
                output_path=str(final_video),
                cancel_event=cancel_event,
            )
            result["video_final_path"] = str(final_video)
            logger.info(f"  Final video: {final_video}")
        except Exception as e:
            logger.error(f"  Mix failed: {e}")
            result["video_final_path"] = result["video_raw_path"]
    else:
        result["video_final_path"] = result.get("video_raw_path")

    # ================================================================
    # PHASE 5: Generate Document + PDF (PARALLEL)
    # ================================================================
    if enable_dual_output and result["screenshots"]:
        logger.info(f"\n{'='*60}")
        logger.info(f"  PHASE 5: Generate Document + PDF (parallel)")
        logger.info(f"{'='*60}")

        # Add renderers to path
        DUAL_OUTPUT_DIR = Path(__file__).parent.parent / "dual_output_pipeline"
        sys.path.insert(0, str(DUAL_OUTPUT_DIR / "renderers"))
        
        from document_renderer import DocumentRenderer
        from pdf_renderer import PDFRenderer

        # Map screenshots theo index
        screenshot_map = {}
        for screenshot_path in result["screenshots"]:
            # Match both normal and placeholder screenshots
            match = re.search(r'step_(\d+)(?:_placeholder)?\.png', screenshot_path)
            if match:
                step_idx = int(match.group(1))
                screenshot_map[step_idx] = screenshot_path
                logger.info(f"    Mapped: step_{step_idx} -> {Path(screenshot_path).name}")
            else:
                logger.warning(f"    Cannot parse screenshot: {Path(screenshot_path).name}")
        
        logger.info(f"  Screenshot map: {len(screenshot_map)} entries")

        # Load trace de lay narrations
        # Trace chua narrations sau khi recording
        trace_path = result.get("trace_path")
        if trace_path and Path(trace_path).exists():
            with open(trace_path, 'r', encoding='utf-8') as f:
                trace = json.load(f)
        else:
            trace = plan  # Fallback to plan if trace not found

        # Extract narrations tu trace VA map theo step_index
        # Narration co format: "[NARRATION:X] text..."
        narration_map = {}  # step_index -> narration text
        for step in trace:
            desc = step.get('description', '')
            step_idx = step.get('step_index')
            if '[NARRATION:' in desc:
                # Extract narration text (remove prefix)
                narration_text = re.sub(r'\[NARRATION:\d+\]\s*', '', desc)
                if step_idx is not None:
                    narration_map[step_idx] = narration_text
                    logger.info(f"  Narration at step_index {step_idx}: {narration_text[:60]}...")
        
        logger.info(f"  Extracted {len(narration_map)} narrations: {list(narration_map.keys())}")

        # Tạo render plan
        render_plan = {
            'name': video_name,
            'title': f'Hướng dẫn: {task_description}',
            'steps': []
        }

        # Build steps: Moi narration tuong ung voi 1 step trong document
        # Tim screenshot tot nhat cho moi narration
        sorted_screenshot_indices = sorted(screenshot_map.keys())
        logger.info(f"  Processing screenshots at indices: {sorted_screenshot_indices}")
        
        # Strategy: Moi narration tao 1 step, chon screenshot sau narration
        # Vi du: narration o step 1 -> chon screenshot o step 2 (action step)
        used_screenshots = set()
        
        for narration_idx in sorted(narration_map.keys()):
            narration = narration_map[narration_idx]
            
            # Tim screenshot tot nhat: screenshot SAU narration (action step)
            best_screenshot_idx = None
            for screenshot_idx in sorted_screenshot_indices:
                if screenshot_idx > narration_idx and screenshot_idx not in used_screenshots:
                    best_screenshot_idx = screenshot_idx
                    break
            
            # Fallback: dung screenshot o chinh narration_idx
            if not best_screenshot_idx:
                if narration_idx in screenshot_map and narration_idx not in used_screenshots:
                    best_screenshot_idx = narration_idx
            
            if best_screenshot_idx:
                used_screenshots.add(best_screenshot_idx)
                
                # Tim action type
                matching_step = None
                for step in plan:
                    if step.get('step_index') == best_screenshot_idx:
                        matching_step = step
                        break
                
                render_plan['steps'].append({
                    'action': matching_step.get('action_type') if matching_step else 'unknown',
                    'narration': narration,
                    'screenshot_index': best_screenshot_idx,
                })
                logger.info(f"  Narration at step {narration_idx} -> screenshot at step {best_screenshot_idx}")

        # Tạo ordered screenshots
        ordered_screenshots = []
        for step in render_plan['steps']:
            step_idx = step['screenshot_index']
            if step_idx in screenshot_map:
                screenshot_path = screenshot_map[step_idx]
                ordered_screenshots.append(screenshot_path)
                logger.info(f"    Step {step_idx} -> {Path(screenshot_path).name}")
            else:
                logger.warning(f"    Step {step_idx} -> NO SCREENSHOT FOUND")
        
        artifacts = {
            'screenshots': ordered_screenshots,
            'audio': result.get("audio_files", []),
            'metadata': {}
        }
        
        logger.info(f"  Render plan: {len(render_plan['steps'])} steps")
        logger.info(f"  Ordered screenshots: {len(ordered_screenshots)} files")
        logger.info(f"  Screenshot paths: {[Path(p).name for p in ordered_screenshots]}")

        # Render song song
        async def render_documents():
            doc_renderer = DocumentRenderer(project_dir)
            pdf_renderer = PDFRenderer(project_dir)

            tasks = [
                asyncio.to_thread(doc_renderer.render, render_plan, artifacts),
                asyncio.to_thread(pdf_renderer.render, render_plan, artifacts)
            ]

            results = await asyncio.gather(*tasks)
            return results

        try:
            doc_path, pdf_path = asyncio.run(render_documents())
            result["document_path"] = doc_path
            result["pdf_path"] = pdf_path
            logger.info(f"  Document: {doc_path}")
            logger.info(f"  PDF: {pdf_path}")
        except Exception as e:
            logger.error(f"  Document rendering failed: {e}")

    # ================================================================
    # Kết quả
    # ================================================================
    logger.info(f"\n{'='*60}")
    logger.info(f"  PIPELINE V3 DUAL HOÀN TẤT")
    logger.info(f"  Plan:       {result['plan_path']}")
    logger.info(f"  Video final:{result['video_final_path']}")
    logger.info(f"  Document:   {result['document_path']}")
    logger.info(f"  PDF:        {result['pdf_path']}")
    logger.info(f"  Screenshots:{len(result['screenshots'])}")
    logger.info(f"{'='*60}")

    return result


# CLI
if __name__ == "__main__":
    import sys
    import argparse

    sys.path.insert(0, str(Path(__file__).parent))

    parser = argparse.ArgumentParser(description="OS Pipeline V3 with Dual Output")
    parser.add_argument("--pid", type=int, help="PID ung dung dich")
    parser.add_argument("--task", type=str, required=True, help="Mo ta task")
    parser.add_argument("--output", type=str, default="workspace/pipeline_v3_dual", help="Thu muc output")
    parser.add_argument("--name", type=str, default="os_video", help="Ten video")
    parser.add_argument("--voice", type=str, default="banmai", help="Giong TTS")
    parser.add_argument("--max-steps", type=int, default=15, help="So buoc toi da")
    parser.add_argument("--dry-run", action="store_true", help="Chi plan + TTS, khong quay")
    parser.add_argument("--skip-tts", action="store_true", help="Bo qua TTS")
    parser.add_argument("--notepad", action="store_true", help="Tu mo Notepad")
    parser.add_argument("--excel", action="store_true", help="Tu mo Excel")
    parser.add_argument("--word", action="store_true", help="Tu mo Word")
    parser.add_argument("--chrome", action="store_true", help="Tu mo Google Chrome")
    parser.add_argument("--edge", action="store_true", help="Tu mo Microsoft Edge")
    parser.add_argument("--firefox", action="store_true", help="Tu mo Mozilla Firefox")
    parser.add_argument("--app", type=str, default=None, help="Ten process ung dung bat ky (VD: mspaint.exe)")
    parser.add_argument("--no-dual-output", action="store_true", help="Tat dual output (chi quay video)")
    args = parser.parse_args()

    pid = args.pid
    app_executable = None

    # IDE exclusion helper
    def _not_ide(title):
        t = title.lower()
        return not any(x in t for x in ["visual studio code", "cursor", "kiro", ".py"])

    def _find_or_launch(exe, filter_fn, start_cmd, label, wait_s=4):
        """Tim cua so ung dung, neu khong thay thi khoi dong va tim lai."""
        from core.window_manager import get_visible_windows
        import subprocess as _sp

        wins = get_visible_windows()
        win = next((w for w in wins if filter_fn(w)), None)
        if not win:
            _sp.Popen(start_cmd, shell=True)
            time.sleep(wait_s)
            wins = get_visible_windows()
            win = next((w for w in wins if filter_fn(w)), None)
        if win:
            print(f"Su dung {label} (PID={win['pid']})")
            return win["pid"], exe
        return None, exe

    if args.excel:
        pid, app_executable = _find_or_launch(
            "excel.exe",
            lambda w: ("excel" in w["title"].lower() or "book" in w["title"].lower()) and _not_ide(w["title"]),
            "start excel", "Excel",
        )

    elif args.word:
        pid, app_executable = _find_or_launch(
            "winword.exe",
            lambda w: ("word" in w["title"].lower() or "document" in w["title"].lower()) and _not_ide(w["title"]),
            "start winword", "Word",
        )

    elif args.chrome:
        pid, app_executable = _find_or_launch(
            "chrome.exe",
            lambda w: ("google chrome" in w["title"].lower() or ("chrome" in w["title"].lower() and "edge" not in w["title"].lower())),
            'start chrome "about:blank"', "Chrome",
        )

    elif args.edge:
        pid, app_executable = _find_or_launch(
            "msedge.exe",
            lambda w: "edge" in w["title"].lower() or "msedge" in w["title"].lower(),
            'start msedge "about:blank"', "Edge",
        )

    elif args.firefox:
        pid, app_executable = _find_or_launch(
            "firefox.exe",
            lambda w: "firefox" in w["title"].lower() or "mozilla" in w["title"].lower(),
            'start firefox "about:blank"', "Firefox",
        )

    elif args.app:
        # Generic: any application by process name
        app_name = args.app
        if not app_name.lower().endswith(".exe"):
            app_name += ".exe"
        base = app_name.replace(".exe", "").lower()
        pid, app_executable = _find_or_launch(
            app_name,
            lambda w, b=base: b in w["title"].lower(),
            f"start {app_name}", app_name,
        )

    elif args.notepad or not pid:
        from core.window_manager import get_visible_windows
        import subprocess

        app_executable = "notepad.exe"
        windows = get_visible_windows()

        def is_real_notepad(w):
            title = w["title"].lower()
            if "notepad" not in title:
                return False
            if any(x in title for x in ["kiro", "visual studio", "vscode", "code - ", "cursor"]):
                return False
            return " - notepad" in title or title == "notepad"

        notepad = next((w for w in windows if is_real_notepad(w)), None)
        if not notepad:
            proc = subprocess.Popen([app_executable])
            time.sleep(2)
            windows = get_visible_windows()
            notepad_new = next((w for w in windows if is_real_notepad(w)), None)
            pid = notepad_new["pid"] if notepad_new else proc.pid
            print(f"Khoi dong Notepad moi (PID={pid})")
        else:
            pid = notepad["pid"]
            print(f"Su dung Notepad hien tai (PID={pid}, Title='{notepad['title']}')")

    if not pid:
        print("Khong co PID hop le!")
        sys.exit(1)

    result = run_os_pipeline_v3_dual(
        target_pid=pid,
        task_description=args.task,
        output_dir=args.output,
        video_name=args.name,
        voice=args.voice,
        max_agent_steps=args.max_steps,
        dry_run=args.dry_run,
        skip_tts=args.skip_tts,
        app_executable=app_executable,
        enable_dual_output=not args.no_dual_output,
    )

