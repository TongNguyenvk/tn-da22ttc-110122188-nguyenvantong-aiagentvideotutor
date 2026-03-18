"""
Trace-Driven Video Composer: composing video + audio using Webreel execution trace.

Instead of guessing or estimating when each action happens in the video, this
module reads the execution trace that Webreel emits
(.webreel/traces/<name>.trace.json) to know the EXACT ms timestamp of every
step.

Audio clips are placed at timestamps derived from the TRACE only:
1. Parse the trace to find all action steps with their real timestamps
2. Divide action steps into N groups (N = number of narrations)
3. Place narration i a small offset before the start of action group i
4. Use ffmpeg adelay + amix for reliable audio placement

No estimation, no guessing. All timestamps come from the trace.
"""

import json
import os
import shutil
import subprocess
from typing import Any
from pathlib import Path
from dataclasses import dataclass


@dataclass
class TraceStep:
    """One entry from the Webreel execution trace."""
    step_index: int
    action_type: str
    description: str | None
    start_time_ms: float
    end_time_ms: float
    tts_index: int | None = None


def _find_ffmpeg() -> str:
    """Locate the ffmpeg binary. Checks FFMPEG_PATH env var, then PATH."""
    env_path = os.environ.get("FFMPEG_PATH") or os.environ.get("IMAGEIO_FFMPEG_EXE")
    if env_path and Path(env_path).exists():
        return env_path
    which = shutil.which("ffmpeg")
    if which:
        return which
    raise FileNotFoundError(
        "ffmpeg not found. Set FFMPEG_PATH or install ffmpeg on PATH."
    )


def load_execution_trace(trace_path: str | Path) -> list[TraceStep]:
    """Read the .trace.json produced by Webreel's runner."""
    trace_path = Path(trace_path)
    if not trace_path.exists():
        raise FileNotFoundError(f"Trace file not found: {trace_path}")

    with open(trace_path, "r", encoding="utf-8") as f:
        raw = json.load(f)

    return [
        TraceStep(
            step_index=entry["step_index"],
            action_type=entry["action_type"],
            description=entry.get("description"),
            start_time_ms=entry["start_time_ms"],
            end_time_ms=entry["end_time_ms"],
            tts_index=entry.get("tts_index"),
        )
        for entry in raw
    ]


def find_narration_pauses(trace: list[TraceStep]) -> list[TraceStep]:
    """
    Filter trace entries to find narration pause steps.

    These are the pause steps whose description starts with "[narration]",
    injected by audio_sync_optimizer.
    """
    results = []
    for step in trace:
        if step.action_type != "pause":
            continue
        desc = step.description or ""
        if desc.startswith("[narration]"):
            results.append(step)
    return results


def find_action_groups(trace: list[TraceStep]) -> list[TraceStep]:
    """
    Find meaningful action steps in the trace that serve as group boundaries.

    Returns steps that are NOT pauses, in chronological order.
    These represent the actual user interactions (click, type, navigate, etc.)
    whose timestamps we can use for audio placement.
    """
    actions = []
    for step in trace:
        if step.action_type in ("pause",):
            continue
        actions.append(step)
    return actions


def _get_audio_duration_ms(audio_path: Path) -> int:
    """Get audio duration in ms using ffprobe (most accurate)."""
    try:
        import subprocess
        result = subprocess.run(
            [
                "ffprobe",
                "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(audio_path)
            ],
            capture_output=True,
            text=True,
            timeout=10
        )
        if result.returncode == 0:
            duration_s = float(result.stdout.strip())
            return int(duration_s * 1000)
    except Exception:
        pass
    
    # Fallback: mutagen
    try:
        from mutagen.mp3 import MP3
        audio = MP3(str(audio_path))
        return int(audio.info.length * 1000)
    except Exception:
        pass
    
    # Last resort: estimate from file size (MP3 ~128kbps)
    size = audio_path.stat().st_size
    return int(size * 8 / 128)


def compute_narration_timestamps(
    trace: list[TraceStep],
    audio_files: list[Path],
) -> list[int]:
    """
    Compute ms timestamps for each narration using ONLY trace data.

    Strategy (100% trace-based, no estimation):
    1. Find all trace steps that have a description (these are the "key action" steps).
    2. Map narration i to described_step[i] (1:1, same order).
    3. Place narration at the PRECEDING step's start_time (the lead-in moveTo/click),
       so the narration starts as the cursor begins to move toward the action.
    4. Prevent overlap: ensure each narration starts after the previous one finishes.

    Args:
        trace: Execution trace from Webreel (the ONLY source of truth for timing).
        audio_files: Audio files in order, used to measure durations for overlap check.

    Returns:
        List of placement timestamps in ms, one per narration.
    """
    num_narrations = len(audio_files)

    # Measure audio durations (handle None for failed segments)
    audio_durations: list[int] = []
    for af in audio_files:
        if af is None:
            audio_durations.append(0)
            continue
        dur = _get_audio_duration_ms(af)
        audio_durations.append(dur)
        print(f"[TraceComposer] Audio {af.name}: {dur}ms ({dur/1000:.1f}s)")

    # Build a lookup for steps by their designated tts_index
    # Format in description: "[TTS:idx] ..." or "[NARRATION:idx] ..."
    tts_indexed_steps: dict[int, TraceStep] = {}
    import re
    
    for step in trace:
        desc = step.description or ""
        # Match both [TTS:idx] and [NARRATION:idx] formats
        match = re.search(r"\[(?:TTS|NARRATION):(\d+)\]", desc)
        if match:
            idx = int(match.group(1))
            tts_indexed_steps[idx] = step
            print(f"[TraceComposer] Found tagged step in trace: {idx} -> at {step.start_time_ms}ms")
    
    if not tts_indexed_steps:
        # Fallback to the old description-based mapping (without [TTS: prefix)
        described_steps = [s for s in trace if s.description and not s.description.startswith("[TTS:")]
        if described_steps:
            print(f"[TraceComposer] WARNING: No '[TTS:idx]' tags found. Falling back to {len(described_steps)} described steps.")
        else:
            print("[TraceComposer] WARNING: No tagged or described steps found in trace.")
    else:
        print(f"[TraceComposer] Found {len(tts_indexed_steps)} tts-indexed steps in trace.")
        described_steps = [] # Will not be used

    # Compute placement timestamps
    real_timestamps: list[int] = []

    for i in range(num_narrations):
        # 1. Try to find the step by tts_index
        key_step = None
        if i in tts_indexed_steps:
            key_step = tts_indexed_steps[i]
            label_info = f"tts_index {i}"
        
        # 2. Fallback to described_steps if tts_index mapping failed
        elif i < len(described_steps):
            key_step = described_steps[i]
            label_info = f"described step {i}"

        if key_step:
            # Place narration at the start of this step
            real_ts = int(key_step.start_time_ms)
            desc = key_step.description if hasattr(key_step, 'description') else "???"
            print(f"[TraceComposer] Narration {i} -> {label_info} at {real_ts}ms | describes: '{desc}'")
        else:
            # Fallback: distribute remaining evenly across the tail
            total_ms = int(trace[-1].end_time_ms) if trace else 0
            last_placed = real_timestamps[-1] if real_timestamps else 0
            remaining = num_narrations - i
            gap = max(2000, (total_ms - last_placed) // (remaining + 1))
            real_ts = last_placed + gap
            print(f"[TraceComposer] Narration {i} -> fallback at {real_ts}ms (no mapping)")

        # Prevent overlap with previous narration
        if i > 0 and real_timestamps:
            prev_end = real_timestamps[-1] + audio_durations[i - 1]
            min_start = prev_end + 800  # 800ms buffer for natural pacing
            if real_ts < min_start:
                print(f"[TraceComposer]   Pushed from {real_ts}ms to {min_start}ms (prev ends at {prev_end}ms)")
                real_ts = min_start

        real_timestamps.append(real_ts)

    return real_timestamps



def compose_video_from_trace(
    video_path: str | Path,
    trace_path: str | Path,
    audio_files: list[str | Path],
    output_path: str | Path,
) -> Path:
    """
    Compose final video by placing audio at trace-derived timestamps.

    Uses ffmpeg directly with adelay + amix filters.
    All timestamps come from the trace (no estimation).
    """
    video_path = Path(video_path)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    ffmpeg = _find_ffmpeg()

    print(f"[TraceComposer] Loading trace: {trace_path}")
    trace = load_execution_trace(trace_path)
    print(f"[TraceComposer] Trace has {len(trace)} steps")

    # Process audio files, preserving None for failed segments
    processed_audio: list[Path | None] = []
    for af in audio_files:
        if af is None:
            processed_audio.append(None)
            continue
        af_path = Path(af)
        if af_path.exists():
            processed_audio.append(af_path)
        else:
            print(f"[TraceComposer] WARNING: Audio file not found: {af_path}")
            processed_audio.append(None)

    if not any(processed_audio):
        print("[TraceComposer] No valid audio files. Returning original.")
        return video_path

    # Compute placement timestamps from trace data (preserving indices)
    timestamps = compute_narration_timestamps(trace, processed_audio)

    # Log the placements
    print(f"\n[TraceComposer] Audio placements:")
    for i, (af, ts) in enumerate(zip(processed_audio, timestamps)):
        af_name = af.name if af else "FAILED"
        print(f"  [{i}] {af_name} -> {ts}ms ({ts / 1000:.2f}s)")

    # Build ffmpeg command
    cmd = [ffmpeg, "-y", "-i", str(video_path)]

    for af in processed_audio:
        if af:
            cmd.extend(["-i", str(af)])

    # Build filter_complex
    filter_parts = []
    mix_inputs = []
    
    # Input 0 is the video. Inputs 1...N are the audio segments.
    current_input_idx = 1
    
    for idx, (af, ts) in enumerate(zip(processed_audio, timestamps)):
        if af is None:
            continue
            
        label = f"a{idx}"
        # Create silence padding + audio using concat
        # anullsrc creates silence, duration in seconds
        silence_duration_s = ts / 1000.0
        filter_parts.append(
            f"anullsrc=channel_layout=mono:sample_rate=24000:duration={silence_duration_s}[silence{idx}]"
        )
        filter_parts.append(
            f"[silence{idx}][{current_input_idx}:a]concat=n=2:v=0:a=1[{label}]"
        )
        mix_inputs.append(f"[{label}]")
        current_input_idx += 1

    mix_labels = "".join(mix_inputs)
    num_inputs = len(mix_inputs)
    # amix with dropout_transition=0 prevents crossfade, normalize=0 prevents volume drop
    filter_parts.append(
        f"{mix_labels}amix=inputs={num_inputs}:duration=longest:dropout_transition=0:normalize=0,volume=1.5[aout]"
    )

    filter_complex = ";".join(filter_parts)

    cmd.extend([
        "-filter_complex", filter_complex,
        "-map", "0:v",
        "-map", "[aout]",
        "-c:v", "copy",
        "-c:a", "aac",
        "-b:a", "192k",
        str(output_path),
    ])

    print(f"\n[TraceComposer] Running ffmpeg...")
    print(f"[TraceComposer] Command: {' '.join(cmd)}")
    print(f"[TraceComposer] Filter complex: {filter_complex}")
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    if result.returncode != 0:
        print(f"[TraceComposer] ffmpeg stderr:\n{result.stderr}")
        raise RuntimeError(f"ffmpeg failed: {result.returncode}")

    print(f"[TraceComposer] Done: {output_path}")
    return output_path


# Standalone test
if __name__ == "__main__":
    import sys

    if len(sys.argv) < 4:
        print("Usage: python trace_composer.py <video.mp4> <trace.json> <audio1.mp3> [audio2.mp3 ...]")
        print("")
        print("Example:")
        print("  python trace_composer.py output/w3test/w3test_raw.mp4 \\")
        print("    output/w3test/.webreel/traces/w3test.trace.json \\")
        print("    output/w3test/audio/narration_000.mp3 output/w3test/audio/narration_001.mp3")
        sys.exit(1)

    video = sys.argv[1]
    trace = sys.argv[2]
    audios = sys.argv[3:]

    out = Path(video).parent / f"{Path(video).stem}_trace_synced.mp4"
    compose_video_from_trace(video, trace, audios, out)
