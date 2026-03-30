"""
OS Pipeline - Pipeline chính kết nối toàn bộ:
  Phase 1 (Plan):   Agent dò đường + sinh plan.json + narrations
  Phase 2 (TTS):    Sinh audio từ narrations bằng Edge TTS
  Phase 3 (Record): Replay plan.json + quay FFmpeg
  Phase 4 (Mix):    Ghép audio vào video bằng trace_composer

Flow:
  Input:  PID ứng dụng + task description
  Output: video_final.mp4 (có tiếng thuyết minh)
"""

import json
import time
import logging
import re
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def run_os_pipeline(
    target_pid: int,
    task_description: str,
    output_dir: str = "workspace/pipeline_output",
    video_name: str = "os_video",
    voice: str = "banmai",
    max_agent_steps: int = 15,
    dry_run: bool = False,
    skip_tts: bool = False,
    app_executable: str = None,
    progress_callback=None,
    cancel_event=None,
    review_event=None,
    review_result_holder=None,
    ready_event=None,
) -> dict:
    """
    Pipeline chính cho OS-level screen recording.

    Args:
        target_pid: PID của ứng dụng đích.
        task_description: Mô tả task cho Agent (VD: "Mở File > New").
        output_dir: Thư mục output.
        video_name: Tên video output.
        voice: Giọng TTS (banmai/leminh).
        max_agent_steps: Số bước tối đa cho Agent.
        dry_run: True = không thực thi, chỉ sinh plan + TTS.
        skip_tts: True = bỏ qua TTS (chỉ quay video không tiếng).
        app_executable: Đường dẫn executable để khởi động lại (Vd: notepad.exe).

    Returns:
        Dict chứa đường dẫn các file output.
    """
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    result = {
        "plan_path": None,
        "video_raw_path": None,
        "video_final_path": None,
        "trace_path": None,
        "audio_files": [],
        "narrations": [],
    }

    # ================================================================
    # PHASE 1: Agent dò đường (Silent, không chiếm chuột)
    # ================================================================
    logger.info(f"\n{'='*60}")
    logger.info(f"  PHASE 1: Agent dò đường")
    logger.info(f"  Task: {task_description[:60]}")
    logger.info(f"  PID: {target_pid}")
    logger.info(f"{'='*60}")

    from core.os_planning_agent_v2 import OSPlanningAgent
    from core.os_executor_v2 import execute_plan

    agent = OSPlanningAgent(
        pid=target_pid,
        user_task=task_description,
        max_steps=max_agent_steps,
        output_dir=str(output_path / "agent"),
    )

    try:
        agent_result = agent.run(dry_run=dry_run)
    except RuntimeError as e:
        logger.error(f"\n  PIPELINE DỪNG: Agent thất bại - {e}")
        logger.error(f"  Gemini API có thể đang quá tải. Thử lại sau.")
        result["error"] = str(e)
        return result

    plan_path = output_path / "agent" / "plan.json"
    result["plan_path"] = str(plan_path)

    # Trích xuất narrations từ plan.json
    narrations = []
    with open(plan_path, "r", encoding="utf-8") as f:
        plan = json.load(f)

    # Kiểm tra plan có hành động thật không (không chỉ toàn pause)
    real_actions = [a for a in plan if a.get("action_type") not in ("pause",)]
    if not real_actions:
        logger.error(f"\n  PIPELINE DỪNG: Plan không có hành động nào (chỉ có pause)")
        logger.error(f"  Agent chưa hoàn thành task. Thử lại sau.")
        result["error"] = "Plan rỗng - Agent chưa sinh được hành động"
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

    # Progress callback: Phase 1 complete
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

        # Block until UI signals review is done
        review_event.wait()
        review_event.clear()

        if cancel_event and cancel_event.is_set():
            logger.info("Pipeline cancelled during Phase 2.5")
            return result

        # Apply reviewed narrations if provided
        reviewed = review_result_holder.get("reviewed_script")
        if reviewed:
            narrations = reviewed
            result["narrations"] = narrations
            logger.info(f"  Review accepted: {len(narrations)} segments")

            # Update plan.json with reviewed narrations
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
        else:
            logger.info("  Review cancelled, using original narrations")

    if not agent_result.is_complete:
        logger.warning("  Agent chưa hoàn tất task!")

    # ================================================================
    # PHASE 2: TTS - Sinh audio từ narrations
    # ================================================================
    audio_files = []

    if not skip_tts and narrations:
        logger.info(f"\n{'='*60}")
        logger.info(f"  PHASE 2: TTS ({len(narrations)} narrations)")
        logger.info(f"{'='*60}")

        audio_dir = output_path / "audio"
        audio_dir.mkdir(parents=True, exist_ok=True)

        # Dùng Edge TTS (miễn phí, không cần API key)
        try:
            from core.tts_edge import generate_speech
            tts_engine = "edge"
            logger.info("  TTS Engine: Edge TTS (miễn phí)")
        except ImportError:
            from core.tts import generate_speech
            tts_engine = "fpt"
            logger.info("  TTS Engine: FPT.AI")

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
    elif skip_tts:
        logger.info("\n  PHASE 2: TTS bo qua (skip_tts=True)")

    # ================================================================
    # PHASE 4 (Injector): Replace placeholder pauses with exact TTS durations
    # (Copy from audio_injector.inject_exact_pauses)
    # ================================================================
    if audio_files and any(a for a in audio_files if a):
        logger.info(f"\n{'='*60}")
        logger.info(f"  PHASE 4 (Injector): Exact TTS durations -> plan.json")
        logger.info(f"{'='*60}")

        padding_ms = 300  # Narration xong -> 300ms -> action bat dau

        with open(plan_path, "r", encoding="utf-8") as f:
            plan = json.load(f)

        injected_count = 0
        total_narration_ms = 0

        for step in plan:
            desc = step.get("description", "")
            match = re.match(r"\[NARRATION:(\d+)\]", desc)
            if not match:
                continue

            idx = int(match.group(1))

            # Tim audio segment tuong ung
            duration_ms = 0
            for a in audio_files:
                if a and isinstance(a, dict):
                    audio_name = f"narration_{idx:03d}.mp3"
                    if audio_name in a["path"]:
                        duration_ms = a["duration_ms"]
                        break

            if duration_ms > 0:
                exact_pause = duration_ms + padding_ms
            else:
                # Fallback: 3 seconds if TTS failed
                exact_pause = 3000

            step["duration_ms"] = exact_pause
            total_narration_ms += duration_ms
            injected_count += 1

            status = f"{duration_ms}ms + {padding_ms}ms padding = {exact_pause}ms"
            if duration_ms == 0:
                status = f"FAILED (fallback {exact_pause}ms)"
            logger.info(f"  [Injector] NARRATION:{idx} -> {status}")

        with open(plan_path, "w", encoding="utf-8") as f:
            json.dump(plan, f, indent=2, ensure_ascii=False)

        logger.info(f"  Replaced {injected_count} placeholder pauses")
        logger.info(f"  Total narration audio: {total_narration_ms}ms ({total_narration_ms / 1000:.1f}s)")

    # ================================================================
    # CLEANUP STATE (Restart App if app_executable is provided)
    # ================================================================
    current_pid = target_pid
    # Bypass Cleanup (Tạm không Kill tiến trình) nếu đó là Excel, PowerPoint hoặc Word để tránh mất file user
    if not dry_run and app_executable and "excel" not in app_executable.lower() and "powerpnt" not in app_executable.lower() and "winword" not in app_executable.lower():
        import psutil
        import subprocess
        logger.info(f"\n{'='*60}")
        logger.info(f"  CLEANUP STATE: Restarting '{app_executable}' for clean recording")
        logger.info(f"{'='*60}")
        try:
            # Kill old process
            process = psutil.Process(current_pid)
            process.terminate()
            process.wait(timeout=3)
            logger.info(f"  Killed dirty process PID: {current_pid}")
        except Exception as e:
            logger.warning(f"  Could not kill old process: {e}")

        # Start new clean process
        logger.info(f"  Starting new instance of '{app_executable}'...")
        if "excel" in app_executable.lower():
            proc = subprocess.Popen("start excel", shell=True)
            time.sleep(4)
        else:
            proc = subprocess.Popen([app_executable])
            time.sleep(2)  # Wait for window to render completely
        
        from core.window_manager import get_visible_windows
        windows = get_visible_windows()
        if "notepad" in app_executable.lower():
            n_win = next((w for w in windows if "notepad" in w["title"].lower()), None)
            current_pid = n_win["pid"] if n_win else proc.pid
        elif "excel" in app_executable.lower():
            e_win = next((w for w in windows if "excel" in w["title"].lower() or "book" in w["title"].lower()), None)
            current_pid = e_win["pid"] if e_win else proc.pid
        else:
            current_pid = proc.pid
            
        logger.info(f"  New (Clean) PID for recording: {current_pid}")

    # ================================================================
    # PHASE 3: Record-Replay (quay video tu plan.json)
    # ================================================================
    if not dry_run:
        if progress_callback:
            # UI mode: signal ready-to-record via callback, wait for ready_event
            progress_callback(3.0, "Sẵn sàng quay. Hãy reset trạng thái ứng dụng rồi bấm Xác nhận.")
            if ready_event:
                ready_event.wait()
                ready_event.clear()
            if cancel_event and cancel_event.is_set():
                logger.info("Pipeline cancelled before Phase 3")
                return result
        else:
            # CLI mode: giữ nguyên input() truyền thống
            print("\n" + "*"*60)
            print("  [DỪNG CHỜ] AGENT ĐÃ LÊN KỊCH BẢN & SINH AUDIO XONG!")
            print("  Để hình ảnh khi ghi hình được sạch sẽ và trơn tru,")
            print("  Xin bạn hãy thủ công Undo (Ctrl+Z) hoặc khôi phục file Excel")
            print("  về lại chính xác y như trạng thái ban đầu.")
            print("*"*60)
            input("  >>> BẤM PHÍM [ENTER] TẠI CỬA SỔ CMD ĐỂ TIẾN HÀNH QUAY... <<<")
        logger.info(f"\n{'='*60}")
        logger.info(f"  PHASE 3: Record-Replay")
        logger.info(f"{'='*60}")

        from core.os_planning_agent import replay_plan_with_recording

        replay_result = replay_plan_with_recording(
            plan_path=str(plan_path),
            target_pid=current_pid,
            output_dir=str(output_path),
            video_name=video_name,
        )

        result["video_raw_path"] = replay_result.get("video_path")
        result["trace_path"] = replay_result.get("trace_path")

        logger.info(f"  Video: {result['video_raw_path']}")
        logger.info(f"  Trace: {result['trace_path']}")
    else:
        logger.info("\n  PHASE 3: Record bỏ qua (dry_run=True)")

    # ================================================================
    # PHASE 4: Mix audio vào video (trace_composer)
    # ================================================================
    if (
        not dry_run
        and result["video_raw_path"]
        and result["trace_path"]
        and result.get("audio_files")
        and any(a for a in result["audio_files"] if a)
    ):
        logger.info(f"\n{'='*60}")
        logger.info(f"  PHASE 4: Mix audio + video")
        logger.info(f"{'='*60}")

        from core.trace_composer import compose_video_from_trace

        final_video = output_path / f"{video_name}_final.mp4"

        try:
            compose_video_from_trace(
                video_path=result["video_raw_path"],
                trace_path=result["trace_path"],
                audio_files=[a for a in result["audio_files"] if a],
                output_path=str(final_video),
            )
            result["video_final_path"] = str(final_video)
            logger.info(f"  Final video: {final_video}")
        except Exception as e:
            logger.error(f"  Mix failed: {e}")
            result["video_final_path"] = result["video_raw_path"]
    else:
        result["video_final_path"] = result.get("video_raw_path")

    # ================================================================
    # Kết quả
    # ================================================================
    logger.info(f"\n{'='*60}")
    logger.info(f"  PIPELINE HOÀN TẤT")
    logger.info(f"  Plan:       {result['plan_path']}")
    logger.info(f"  Video raw:  {result['video_raw_path']}")
    logger.info(f"  Video final:{result['video_final_path']}")
    logger.info(f"  Trace:      {result['trace_path']}")
    audio_count = len([a for a in result.get("audio_files", []) if a])
    logger.info(f"  Audio:      {audio_count} files")
    logger.info(f"  Narrations: {len(narrations)}")
    logger.info(f"{'='*60}")

    return result


# CLI
if __name__ == "__main__":
    import sys
    import argparse

    sys.path.insert(0, str(Path(__file__).parent))

    parser = argparse.ArgumentParser(description="OS Pipeline")
    parser.add_argument("--pid", type=int, help="PID ứng dụng đích")
    parser.add_argument("--task", type=str, required=True, help="Mô tả task")
    parser.add_argument("--output", type=str, default="workspace/pipeline_output", help="Thư mục output")
    parser.add_argument("--name", type=str, default="os_video", help="Tên video")
    parser.add_argument("--voice", type=str, default="banmai", help="Giọng TTS")
    parser.add_argument("--max-steps", type=int, default=15, help="Số bước tối đa")
    parser.add_argument("--dry-run", action="store_true", help="Chỉ plan + TTS, không quay")
    parser.add_argument("--skip-tts", action="store_true", help="Bỏ qua TTS")
    parser.add_argument("--notepad", action="store_true", help="Tự mở Notepad")
    parser.add_argument("--excel", action="store_true", help="Tự mở Excel")
    parser.add_argument("--ppt", action="store_true", help="Tự mở PowerPoint")
    parser.add_argument("--word", action="store_true", help="Tự mở Word")
    args = parser.parse_args()

    pid = args.pid
    app_executable = None
    if args.excel:
        from core.window_manager import get_visible_windows
        import os
        app_executable = "excel.exe"
        windows = get_visible_windows()
        
        def is_excel(w):
            t = w["title"].lower()
            return ("excel" in t or "book" in t) and "visual studio code" not in t and ".py" not in t
            
        app_win = next((w for w in windows if is_excel(w)), None)
        if not app_win:
            os.system("start excel")
            time.sleep(4)
            windows = get_visible_windows()
            app_win = next((w for w in windows if is_excel(w)), None)
        if app_win:
            pid = app_win["pid"]
            print(f"Sử dụng Excel (PID={pid})")
        else:
            print("Lỗi: Không tìm thấy cửa sổ Excel sau khi bật!")
            sys.exit(1)
            
    elif args.ppt:
        from core.window_manager import get_visible_windows
        import os
        app_executable = "powerpnt.exe"
        windows = get_visible_windows()
        
        def is_ppt(w):
            t = w["title"].lower()
            return ("powerpoint" in t or "presentation" in t) and "visual studio code" not in t and ".py" not in t
            
        app_win = next((w for w in windows if is_ppt(w)), None)
        if not app_win:
            os.system("start powerpnt")
            time.sleep(4)
            windows = get_visible_windows()
            app_win = next((w for w in windows if is_ppt(w)), None)
        if app_win:
            pid = app_win["pid"]
            print(f"Sử dụng PowerPoint (PID={pid})")
        else:
            print("Lỗi: Không tìm thấy cửa sổ PowerPoint sau khi bật!")
            sys.exit(1)
    elif args.word:
        from core.window_manager import get_visible_windows
        import os
        app_executable = "winword.exe"
        windows = get_visible_windows()
        
        def is_word(w):
            t = w["title"].lower()
            return ("word" in t or "document" in t) and "visual studio code" not in t and ".py" not in t
            
        app_win = next((w for w in windows if is_word(w)), None)
        if not app_win:
            os.system("start winword")
            time.sleep(4)
            windows = get_visible_windows()
            app_win = next((w for w in windows if is_word(w)), None)
        if app_win:
            pid = app_win["pid"]
            print(f"Sử dụng Word (PID={pid})")
        else:
            print("Lỗi: Không tìm thấy cửa sổ Word sau khi bật!")
            sys.exit(1)

    elif args.notepad or not pid:
        from core.window_manager import get_visible_windows
        import subprocess

        app_executable = "notepad.exe"
        windows = get_visible_windows()
        notepad = next((w for w in windows if "notepad" in w["title"].lower()), None)
        if not notepad:
            proc = subprocess.Popen([app_executable])
            time.sleep(2)
            windows = get_visible_windows()
            notepad_new = next((w for w in windows if "notepad" in w["title"].lower()), None)
            if notepad_new:
                pid = notepad_new["pid"]
                print(f"Khởi động Notepad mới (PID={pid})")
            else:
                pid = proc.pid
                print(f"Khởi động Notepad mới qua Popen (PID={pid})")
        else:
            pid = notepad["pid"]
            print(f"Sử dụng Notepad hiện tại: {notepad['title']} (PID={pid})")
            
    if not pid:
        print("Không có PID hợp lệ để chạy pipeline!")
        sys.exit(1)

    result = run_os_pipeline(
        target_pid=pid,
        task_description=args.task,
        output_dir=args.output,
        video_name=args.name,
        voice=args.voice,
        max_agent_steps=args.max_steps,
        dry_run=args.dry_run,
        skip_tts=args.skip_tts,
        app_executable=app_executable,
    )
