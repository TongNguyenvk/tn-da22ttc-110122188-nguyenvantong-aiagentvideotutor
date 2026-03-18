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


def measure_audio_duration_ms(audio_path: Path) -> int:
    """
    Measure exact duration of an audio file in milliseconds.

    Uses ffprobe for accurate duration measurement (more reliable than mutagen).

    Args:
        audio_path: Path to MP3/WAV audio file.

    Returns:
        Duration in milliseconds (integer).
    """
    audio_path = Path(audio_path)
    
    # Try ffprobe first (most accurate)
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
    except Exception as e:
        print(f"  [measure_audio] ffprobe failed: {e}, trying mutagen...")
    
    # Fallback to mutagen
    try:
        from mutagen.mp3 import MP3
        audio = MP3(str(audio_path))
        return int(audio.info.length * 1000)
    except ImportError:
        # Fallback: estimate from file size (128kbps MP3)
        size_bytes = audio_path.stat().st_size
        estimated_seconds = size_bytes / (128 * 1024 / 8)
        return int(estimated_seconds * 1000)
    except Exception as e:
        print(f"  [measure_audio] Warning: could not measure {audio_path}: {e}")
        # Very rough fallback: assume 2 seconds
        return 2000

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
    start_time: float = 0.0   # giây, vị trí bắt đầu trong timeline video
    duration_ms: int = 0  # duoc dien sau khi download (optional)


def generate_speech(
    text: str,
    output_path: Path,
    voice: str = DEFAULT_VOICE,
    speed: str = "",
    api_key: str | None = None,
    max_wait_sec: int = 90,
) -> AudioSegment:
    """
    Chuyen van ban thanh file MP3 dung FPT.AI TTS with retries.

    Args:
        text: Van ban can doc (tieng Viet).
        output_path: Duong dan luu file .mp3.
        voice: Ten giong (banmai / leminh / myan / lannhi / linhsan).
        speed: Toc do doc ("" = mac dinh, "-2" = cham, "2" = nhanh).
        api_key: FPT.AI API key (neu None, lay tu env FPT_API_KEY).
        max_wait_sec: Thoi gian cho toi da (giay).

    Returns:
        AudioSegment voi audio_path da duoc download.
    """
    if api_key is None:
        api_key = os.getenv("FPT_API_KEY") or os.getenv("FPT_TTS_API_KEY")
    if not api_key:
        raise ValueError("FPT_API_KEY or FPT_TTS_API_KEY not found in environment")

    headers = {
        "api-key": api_key,
        "voice": voice,
    }
    if speed:
        headers["speed"] = speed

    max_retries = 3
    last_exception = None

    for attempt in range(max_retries):
        try:
            # Request TTS
            response = requests.post(FPT_TTS_URL, headers=headers, data=text.encode("utf-8"), timeout=30)
            response.raise_for_status()
            data = response.json()

            if data.get("error") != 0:
                # Retry on busy/server errors
                if data.get("error") in [429, 500, 1]:
                    print(f"  [TTS] FPT service busy (error {data.get('error')}). Retry {attempt+1}/{max_retries}...")
                    time.sleep(3 * (attempt + 1))
                    continue
                raise RuntimeError(f"FPT TTS error: {data}")

            async_url = data.get("async")
            if not async_url:
                raise RuntimeError(f"No async URL in response: {data}")

            # Download MP3 with exponential backoff polling
            start_time = time.time()
            output_path.parent.mkdir(parents=True, exist_ok=True)
            
            # FPT needs time to process. Longer texts need more time.
            # Estimate: ~1s per 50 chars, minimum 3s
            estimated_wait = max(3, len(text) // 50)
            time.sleep(estimated_wait)
            
            poll_interval = 2  # Start with 2s, increase on each 404
            last_poll_error = ""
            while time.time() - start_time < max_wait_sec:
                try:
                    mp3_resp = requests.get(async_url, timeout=15)
                    if mp3_resp.status_code == 200:
                        content_type = mp3_resp.headers.get("Content-Type", "")
                        # Verify it's actually audio content (FPT returns 'text/html' if not ready)
                        if "audio" in content_type or mp3_resp.content.startswith(b"ID3") or mp3_resp.content.startswith(b"\xff\xfb"):
                            with open(output_path, "wb") as f:
                                f.write(mp3_resp.content)
                            
                            duration = measure_audio_duration_ms(output_path)
                            return AudioSegment(
                                text=text,
                                audio_path=output_path,
                                duration_ms=duration,
                            )
                        else:
                            last_poll_error = f"Processing... ({content_type})"
                    elif mp3_resp.status_code == 404:
                        last_poll_error = "HTTP 404 (File not ready)"
                        # Increase poll interval on 404 (file still being generated)
                        poll_interval = min(poll_interval + 1, 6)
                    else:
                        last_poll_error = f"HTTP {mp3_resp.status_code}"
                except requests.exceptions.RequestException as e:
                    last_poll_error = str(e)
                
                time.sleep(poll_interval)
            
            raise TimeoutError(f"Failed to download MP3 from {async_url} after {max_wait_sec}s. Last error: {last_poll_error}")

        except (requests.exceptions.RequestException, RuntimeError, TimeoutError) as e:
            last_exception = e
            print(f"  [TTS] Attempt {attempt + 1} failed: {e}. Retrying...")
            time.sleep(3 * (attempt + 1))

    raise last_exception or RuntimeError(f"TTS failed after {max_retries} attempts.")


# Alias for compatibility
def generate_audio_from_text(
    text: str,
    output_path: Path,
    voice: str = DEFAULT_VOICE,
    speed: str = "",
    api_key: str | None = None,
) -> AudioSegment:
    """Alias for generate_speech."""
    return generate_speech(text, output_path, voice, speed, api_key)


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


def build_narration_from_config(webreel_config: dict) -> list[dict]:
    """
    Đọc webreel config JSON (schema mới) và tạo narration texts + timing.

    Webreel config schema:
      navigate → {"action": "navigate", "value": "<url>"}
      click    → {"action": "click", "target": "<selector>"}
      type     → {"action": "type", "target": "<selector>", "value": "<text>"}
      pause    → {"action": "pause", "value": <ms>}

    Returns:
        List of dicts: [{"text": "...", "start_time": float}, ...]
        start_time tính bằng giây.
    """
    narrations: list[dict] = []

    # Lấy video đầu tiên trong config
    videos = webreel_config.get("videos", {})
    if not videos:
        return narrations

    video_key = next(iter(videos))
    video_cfg = videos[video_key]
    steps = video_cfg.get("steps", [])

    current_time = 1.0  # bắt đầu sau 1s (cho trang load)

    for step in steps:
        action = step.get("action", "")
        text = ""

        if action == "navigate":
            url = step.get("value", "")
            # Rút gọn URL cho dễ nghe
            domain = url.replace("https://", "").replace("http://", "").split("/")[0]
            text = f"Mở trang web {domain}."

        elif action == "click":
            target = step.get("target", "phần tử")
            # Rút gọn selector cho dễ nghe
            label = _simplify_selector(target)
            text = f"Nhấn vào {label}."

        elif action == "type":
            value = step.get("value", "")
            target = step.get("target", "ô nhập liệu")
            label = _simplify_selector(target)
            text = f"Nhập '{value}' vào {label}."

        elif action == "pause":
            ms = step.get("value", 0)
            if isinstance(ms, (int, float)):
                current_time += ms / 1000.0
            continue  # Không tạo narration cho pause

        else:
            continue  # Bỏ qua action không xác định

        if text:
            narrations.append({
                "text": text,
                "start_time": current_time,
            })
            # Ước lượng: mỗi narration ~2.5s
            current_time += 2.5

    return narrations


def _simplify_selector(selector: str) -> str:
    """Rút gọn CSS selector thành dạng dễ đọc."""
    if not selector:
        return "phần tử"

    # #id → tên id
    if selector.startswith("#"):
        return selector[1:].replace("-", " ")

    # input[name="search"] → ô tìm kiếm
    if "name=" in selector:
        import re
        m = re.search(r'name="([^"]+)"', selector)
        if m:
            name = m.group(1).replace("_", " ")
            return f"ô {name}"

    # button.classname → nút
    if selector.startswith("button"):
        return "nút"

    # a.classname → liên kết
    if selector.startswith("a.") or selector.startswith("a["):
        return "liên kết"

    # input.classname → ô nhập liệu
    if selector.startswith("input"):
        return "ô nhập liệu"

    # Fallback: trả nguyên
    if len(selector) > 30:
        return "phần tử trên trang"

    return selector


def generate_narration_from_config(
    webreel_config: dict,
    output_dir: Path,
    voice: str = DEFAULT_VOICE,
    speed: str = "",
    api_key: str | None = None,
) -> list[AudioSegment]:
    """
    Đọc webreel config → sinh narration texts → gọi TTS → trả AudioSegments.

    Args:
        webreel_config: Dict webreel config JSON đã parse.
        output_dir: Thư mục lưu file audio.
        voice: Giọng TTS.
        speed: Tốc độ.
        api_key: FPT API key.

    Returns:
        List AudioSegment với start_time đã set.
    """
    narrations = build_narration_from_config(webreel_config)

    if not narrations:
        return []

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    segments: list[AudioSegment] = []
    for i, item in enumerate(narrations):
        out_path = output_dir / f"narration_{i:03d}.mp3"

        try:
            seg = generate_speech(
                text=item["text"],
                output_path=out_path,
                voice=voice,
                speed=speed,
                api_key=api_key,
            )
            # Ghi đè start_time từ narration
            seg.start_time = item["start_time"]
            segments.append(seg)
            print(f"  [TTS] {i+1}/{len(narrations)}: '{item['text'][:50]}...' → {out_path.name}")
        except Exception as e:
            print(f"  [TTS WARN] Bỏ qua segment {i}: {e}")

    return segments
