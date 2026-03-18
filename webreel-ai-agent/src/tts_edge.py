"""
TTS Edge Module - Text-to-Speech using Edge TTS (Microsoft Azure TTS)

This is a temporary replacement for FPT.AI TTS during network issues.
Uses edge-tts library for Vietnamese text-to-speech.

Compatible interface with tts.py for drop-in replacement.
"""
import os
import asyncio
from pathlib import Path
from dataclasses import dataclass

# Import from parent src/
import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from tts import AudioSegment, measure_audio_duration_ms


# Vietnamese voices available in Edge TTS
# https://speech.microsoft.com/portal/voicegallery
EDGE_VOICES = {
    "banmai": "vi-VN-HoaiMyNeural",      # Female, Northern accent (default)
    "leminh": "vi-VN-NamMinhNeural",     # Male, Northern accent
    "myan": "vi-VN-HoaiMyNeural",        # Female (fallback to HoaiMy)
    "lannhi": "vi-VN-HoaiMyNeural",      # Female (fallback to HoaiMy)
    "linhsan": "vi-VN-HoaiMyNeural",     # Female (fallback to HoaiMy)
}

DEFAULT_VOICE = "banmai"


async def _generate_speech_async(
    text: str,
    output_path: Path,
    voice: str = DEFAULT_VOICE,
    rate: str = "+0%",
) -> AudioSegment:
    """
    Generate speech using edge-tts (async).

    Args:
        text: Vietnamese text to synthesize.
        output_path: Path to save .mp3 file.
        voice: Voice name (banmai/leminh/etc).
        rate: Speech rate ("+0%" = normal, "-10%" = slower, "+10%" = faster).

    Returns:
        AudioSegment with audio_path and duration_ms.
    """
    try:
        import edge_tts
    except ImportError:
        raise ImportError(
            "edge-tts not installed. Install with: pip install edge-tts"
        )

    # Map voice name to Edge TTS voice ID
    edge_voice = EDGE_VOICES.get(voice, EDGE_VOICES[DEFAULT_VOICE])

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Generate speech
    communicate = edge_tts.Communicate(text, edge_voice, rate=rate)
    await communicate.save(str(output_path))

    # Measure duration
    duration = measure_audio_duration_ms(output_path)

    return AudioSegment(
        text=text,
        audio_path=output_path,
        duration_ms=duration,
    )


def generate_speech(
    text: str,
    output_path: Path,
    voice: str = DEFAULT_VOICE,
    speed: str = "",
    api_key: str | None = None,
    max_wait_sec: int = 90,
) -> AudioSegment:
    """
    Generate speech using edge-tts (sync wrapper).

    Compatible interface with tts.py for drop-in replacement.

    Args:
        text: Vietnamese text to synthesize.
        output_path: Path to save .mp3 file.
        voice: Voice name (banmai/leminh/etc).
        speed: Speed adjustment ("" = normal, "-2" = slower, "2" = faster).
        api_key: Not used (for compatibility).
        max_wait_sec: Not used (for compatibility).

    Returns:
        AudioSegment with audio_path and duration_ms.
    """
    # Convert speed to rate format
    rate = "+0%"
    if speed:
        try:
            speed_int = int(speed)
            # Map speed (-2 to +2) to rate percentage (-20% to +20%)
            rate_percent = speed_int * 10
            rate = f"{rate_percent:+d}%"
        except ValueError:
            pass

    # Check if we're already in an event loop
    try:
        loop = asyncio.get_running_loop()
        # We're in an event loop, create task and wait for it
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as executor:
            future = executor.submit(
                lambda: asyncio.run(_generate_speech_async(text, output_path, voice, rate))
            )
            return future.result(timeout=max_wait_sec)
    except RuntimeError:
        # No event loop running, safe to use asyncio.run()
        return asyncio.run(_generate_speech_async(text, output_path, voice, rate))


def generate_speech_batch(
    texts: list[str],
    output_dir: Path,
    voice: str = DEFAULT_VOICE,
    speed: str = "",
    api_key: str | None = None,
) -> list[AudioSegment]:
    """
    Generate audio for multiple texts.

    Args:
        texts: List of texts.
        output_dir: Directory to save .mp3 files.
        voice: Voice name.
        speed: Speed adjustment.
        api_key: Not used (for compatibility).

    Returns:
        List of AudioSegments.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    segments: list[AudioSegment] = []

    for i, text in enumerate(texts):
        out_path = output_dir / f"segment_{i:03d}.mp3"
        seg = generate_speech(text, out_path, voice=voice, speed=speed)
        segments.append(seg)

    return segments


# Alias for compatibility
generate_audio_from_text = generate_speech
