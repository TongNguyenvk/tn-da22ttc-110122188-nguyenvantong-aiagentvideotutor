"""
Audio Injector: Replace placeholder pauses with exact TTS durations.

This module does TWO things:
1. Generate TTS audio files from tts_script using FPT.AI or Edge TTS
2. Replace [NARRATION:idx] placeholder pauses (1000ms) with exact durations

No estimation, no AI. Just measured MP3 duration + buffer.
"""

import os
import re
from pathlib import Path
from typing import Any

# Import TTS modules
from tts import AudioSegment, measure_audio_duration_ms


def generate_tts_segments(
    tts_script: list[dict[str, str]],
    output_dir: Path,
    voice: str = "banmai",
    speed: str = "",
    api_key: str | None = None,
    engine: str = "fpt",
) -> list[AudioSegment | None]:
    """
    Phase 3: Generate TTS audio files and measure exact durations.

    Args:
        tts_script: List of narration texts with indices.
        output_dir: Directory to save audio files.
        voice: Voice name (banmai/leminh/etc).
        speed: Speed adjustment.
        api_key: API key (only for FPT engine).
        engine: TTS engine to use ("fpt" or "edge").

    Returns list of AudioSegment (or None for failed segments).
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Clean old audio files from previous runs
    import glob
    for old_file in glob.glob(str(output_dir / "narration_*.mp3")):
        os.unlink(old_file)

    # Select TTS engine
    if engine == "edge":
        from tts_edge import generate_speech
        print(f"[TTS] Using Edge TTS engine (voice: {voice})")
    else:
        from tts import generate_speech
        if api_key is None:
            api_key = os.getenv("FPT_API_KEY") or os.getenv("FPT_TTS_API_KEY")
        if not api_key:
            raise ValueError("FPT_API_KEY or FPT_TTS_API_KEY not found in environment")
        print(f"[TTS] Using FPT.AI TTS engine (voice: {voice})")

    segments: list[AudioSegment | None] = []

    for i, item in enumerate(tts_script):
        text = item.get("text", "").strip()
        if not text:
            segments.append(None)
            continue

        out_path = output_dir / f"narration_{i:03d}.mp3"

        try:
            seg = generate_speech(
                text=text,
                output_path=out_path,
                voice=voice,
                speed=speed,
                api_key=api_key,
            )

            # Ground-truth duration measurement
            seg.duration_ms = measure_audio_duration_ms(out_path)
            seg.start_time = 0.0  # Will be set by trace_composer

            segments.append(seg)
            print(
                f"  [TTS] {i+1}/{len(tts_script)}: "
                f"'{text[:50]}...' -> {out_path.name} "
                f"({seg.duration_ms}ms)"
            )

        except Exception as e:
            print(f"  [TTS WARN] Failed segment {i}: {e}")
            segments.append(None)

    return segments


def inject_exact_pauses(
    config: dict[str, Any],
    video_name: str,
    segments: list[AudioSegment | None],
    padding_ms: int = 800,
) -> dict[str, Any]:
    """
    Phase 4: Replace [NARRATION:idx] placeholder pauses with exact durations.

    Walks through config steps, finds [NARRATION:idx] tags in description,
    and replaces the placeholder 1000ms with (measured_duration + padding).

    Args:
        config: Webreel config with placeholder pauses
        video_name: Video name key in config
        segments: Measured TTS segments from Phase 3
        padding_ms: Extra buffer added to each pause (default 800ms)

    Returns:
        Modified config with exact pause durations
    """
    steps = config["videos"][video_name]["steps"]
    injected_count = 0
    total_narration_ms = 0

    for step in steps:
        desc = step.get("description", "")
        match = re.match(r"\[NARRATION:(\d+)\]", desc)
        if not match:
            continue

        idx = int(match.group(1))

        if idx < len(segments) and segments[idx] is not None:
            duration_ms = segments[idx].duration_ms
            exact_pause = duration_ms + padding_ms
        else:
            # Fallback: 3 seconds if TTS failed
            exact_pause = 3000
            duration_ms = 0

        step["ms"] = exact_pause
        total_narration_ms += duration_ms
        injected_count += 1

        status = f"{duration_ms}ms + {padding_ms}ms padding = {exact_pause}ms"
        if duration_ms == 0:
            status = f"FAILED (fallback {exact_pause}ms)"
        print(f"  [Injector] NARRATION:{idx} -> {status}")

    print(f"\n[Injector] Done!")
    print(f"  Replaced {injected_count} placeholder pauses")
    print(f"  Total narration audio: {total_narration_ms}ms ({total_narration_ms / 1000:.1f}s)")

    return config
