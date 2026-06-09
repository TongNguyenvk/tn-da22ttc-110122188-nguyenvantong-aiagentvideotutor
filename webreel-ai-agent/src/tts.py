"""
TTS Module - Text-to-Speech bang FPT.AI

API docs: https://fpt.ai/tts
POST https://api.fpt.ai/hmi/tts/v5
  Header: api-key, speed, voice
  Body:   raw UTF-8 text
  Response: {"error": 0, "async": "<url_to_download_mp3>", "request_id": "..."}
"""
import os
import time
import requests
from pathlib import Path
from dataclasses import dataclass

FPT_TTS_URL = "https://api.fpt.ai/hmi/tts/v5"

# Giong ho tro
# banmai  - Nu mien Bac (default)
# leminh  - Nam mien Bac
# myan    - Nu mien Nam
# lannhi  - Nu mien Nam (tre)
# linhsan - Nu mien Trung
DEFAULT_VOICE = "banmai"


@dataclass
class AudioSegment:
    text: str
    audio_path: Path
    duration_ms: int = 0  # duoc dien sau khi download (optional)
    start_time: float = 0.0  # for compatibility with audio_injector


def measure_audio_duration_ms(audio_path: Path) -> int:
    """
    Measure audio duration in milliseconds using ffprobe.

    Args:
        audio_path: Path to audio file (MP3, WAV, etc.)

    Returns:
        Duration in milliseconds
    """
    import subprocess
    try:
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

    # Fallback: estimate from file size (MP3 ~128kbps)
    size = Path(audio_path).stat().st_size
    return int(size * 8 / 128)


def generate_speech(
    text: str,
    output_path: Path,
    voice: str = DEFAULT_VOICE,
    speed: str = "",
    api_key: str | None = None,
    max_wait_sec: int = 30,
) -> AudioSegment:
    """
    Chuyen van ban thanh file MP3 dung FPT.AI TTS.

    Args:
        text: Van ban can doc (tieng Viet).
        output_path: Duong dan luu file .mp3.
        voice: Ten giong (banmai / leminh / myan / lannhi / linhsan).
        speed: Toc do doc ("" = mac dinh, "-2" = cham, "2" = nhanh).
        api_key: FPT API key. Neu None, doc tu env FPT_TTS_API_KEY.
        max_wait_sec: So giay doi toi da cho async URL san sang.

    Returns:
        AudioSegment voi duong dan file da luu.

    Raises:
        ValueError: API key khong co hoac van ban rong.
        RuntimeError: FPT API tra loi loi hoac download that bai.
    """
    if not text.strip():
        raise ValueError("Van ban TTS khong duoc de trong.")

    key = api_key or os.environ.get("FPT_TTS_API_KEY", "")
    if not key:
        raise ValueError(
            "FPT_TTS_API_KEY chua duoc dat. "
            "Them vao .env hoac truyen truc tiep qua tham so api_key."
        )

    headers = {
        "api-key": key,
        "speed": speed,
        "voice": voice,
    }

    # Buoc 1: Gui yeu cau TTS
    resp = requests.post(
        FPT_TTS_URL,
        data=text.encode("utf-8"),
        headers=headers,
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()

    if data.get("error") != 0:
        raise RuntimeError(f"FPT TTS loi: {data}")

    async_url: str = data.get("async", "")
    if not async_url:
        raise RuntimeError(f"FPT TTS khong tra ve async URL: {data}")

    # Buoc 2: Cho async URL san sang va download
    audio_bytes: bytes | None = None
    deadline = time.time() + max_wait_sec

    while time.time() < deadline:
        dl = requests.get(async_url, timeout=15)
        if dl.status_code == 200 and dl.content:
            audio_bytes = dl.content
            break
        time.sleep(1.5)

    if audio_bytes is None:
        raise RuntimeError(
            f"Khong download duoc audio sau {max_wait_sec}s. URL: {async_url}"
        )

    # Buoc 3: Luu file
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(audio_bytes)

    return AudioSegment(text=text, audio_path=output_path)


def generate_speech_batch(
    texts: list[str],
    output_dir: Path,
    voice: str = DEFAULT_VOICE,
    speed: str = "",
    api_key: str | None = None,
) -> list[AudioSegment]:
    """
    Tao audio cho nhieu doan van ban.

    Args:
        texts: Danh sach van ban.
        output_dir: Thu muc luu cac file .mp3.
        voice: Ten giong.
        speed: Toc do.
        api_key: FPT API key.

    Returns:
        Danh sach AudioSegment tuong ung.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    segments: list[AudioSegment] = []

    for i, text in enumerate(texts):
        out_path = output_dir / f"segment_{i:03d}.mp3"
        seg = generate_speech(text, out_path, voice=voice, speed=speed, api_key=api_key)
        segments.append(seg)

    return segments


def build_narration_texts(actions: list) -> list[str]:
    """
    Tao van ban thuyet minh cho tung action de doc bang TTS.

    Args:
        actions: Danh sach ParsedAction hoac ResolvedAction.

    Returns:
        Danh sach chuoi van ban mieu ta hanh dong.
    """
    texts: list[str] = []
    for action in actions:
        act_type = action.action.value if hasattr(action.action, "value") else action.action

        if act_type == "navigate":
            texts.append(f"Mo trang web {action.url or ''}.")
        elif act_type == "click":
            label = action.target or "nut"
            texts.append(f"Nhan vao {label}.")
        elif act_type == "type":
            txt = action.text or ""
            target = action.target or "o nhap lieu"
            texts.append(f"Nhap noi dung: {txt} vao {target}.")
        elif act_type == "key":
            key = action.key or ""
            key_viet = {"Enter": "phim Enter", "Tab": "phim Tab", "Escape": "phim Escape"}.get(key, key)
            texts.append(f"Nhan {key_viet}.")
        elif act_type == "scroll":
            direction = action.direction or "xuong"
            texts.append(f"Cuon trang {direction}.")
        elif act_type == "pause":
            texts.append("Cho mot chut.")
        else:
            texts.append(f"Thuc hien buoc: {act_type}.")

    return texts
