"""
Vision Agent - Chup anh cua so va goi Gemini de tao ke hoach hanh dong.
Su dung mss de chup man hinh vung cua so va google-genai de goi AI.
"""

import json
import logging
import os
from pathlib import Path
from enum import Enum

from pydantic import BaseModel

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pydantic schema cho Structured Output tu Gemini
# ---------------------------------------------------------------------------
class ActionType(str, Enum):
    SPEAK = "speak"
    PRESS_KEY = "press_key"
    WAIT = "wait"


class ActionStep(BaseModel):
    action_type: ActionType
    target_value: str
    estimated_duration_ms: int


class ActionPlan(BaseModel):
    actions: list[ActionStep]


# ---------------------------------------------------------------------------
# Chup man hinh cua so theo PID
# ---------------------------------------------------------------------------
def capture_window_by_pid(pid: int, output_path: str = "workspace/temp_screenshot.png") -> str:
    """
    Chup anh vung cua so tuong ung voi PID da cho.

    Args:
        pid: Process ID cua cua so can chup.
        output_path: Duong dan luu file screenshot.

    Returns:
        Duong dan file screenshot da luu.
    """
    import mss
    from core.window_manager import get_window_rect_by_pid

    rect = get_window_rect_by_pid(pid)
    if not rect:
        raise ValueError(f"Cannot find window with PID {pid}")

    left, top, width, height = rect
    logger.info(f"Capturing window PID={pid}: ({left}, {top}, {width}x{height})")

    # Tao thu muc cha neu chua co
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    with mss.mss() as sct:
        monitor = {
            "left": left,
            "top": top,
            "width": width,
            "height": height,
        }
        screenshot = sct.grab(monitor)

        # Luu file PNG
        from mss.tools import to_png
        to_png(screenshot.rgb, screenshot.size, output=output_path)

    logger.info(f"Screenshot saved: {output_path}")
    return output_path


def capture_window_by_hwnd(hwnd: int, output_path: str = "workspace/temp_screenshot.png") -> str:
    """
    Chup anh cua so theo HWND (chinh xac hon PID).
    """
    import mss
    from core.window_manager import get_window_rect_by_hwnd

    rect = get_window_rect_by_hwnd(hwnd)
    if not rect:
        raise ValueError(f"Cannot find window with HWND {hwnd}")

    left, top, width, height = rect
    logger.info(f"Capturing window HWND={hwnd}: ({left}, {top}, {width}x{height})")

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    with mss.mss() as sct:
        monitor = {
            "left": left,
            "top": top,
            "width": width,
            "height": height,
        }
        screenshot = sct.grab(monitor)

        from mss.tools import to_png
        to_png(screenshot.rgb, screenshot.size, output=output_path)

    logger.info(f"Screenshot saved: {output_path}")
    return output_path


# ---------------------------------------------------------------------------
# Goi Gemini de tao ke hoach hanh dong
# ---------------------------------------------------------------------------
def generate_action_plan(image_path: str, user_prompt: str) -> list[dict]:
    """
    Goi Gemini de phan tich anh chup man hinh va sinh ke hoach hanh dong.

    Args:
        image_path: Duong dan anh chup cua so.
        user_prompt: Mo ta nhiem vu cua nguoi dung.

    Returns:
        List cac action, moi action la dict co:
            action_type: "speak" | "press_key" | "wait"
            target_value: noi dung noi / phim bam / ly do cho
            estimated_duration_ms: thoi gian uoc luong (ms)
    """
    import os
    from dotenv import load_dotenv

    load_dotenv()
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY or GOOGLE_API_KEY not found in .env")

    from google import genai

    client = genai.Client(api_key=api_key)

    # Doc file anh
    with open(image_path, "rb") as f:
        image_data = f.read()

    # System prompt
    system_prompt = (
        "You are an expert at creating step-by-step action plans for screen automation. "
        "Given a screenshot of a desktop application and a user's task description, "
        "create a precise action plan.\n\n"
        "Each action must have:\n"
        "- action_type: one of 'speak', 'press_key', 'wait'\n"
        "- target_value: the text to speak, key to press (e.g. 'space', 'f5', 'right', 'enter'), "
        "or reason for waiting\n"
        "- estimated_duration_ms: estimated time in milliseconds\n\n"
        "Respond with valid JSON only. The response must be a JSON object with an 'actions' key "
        "containing a list of action objects."
    )

    response = client.models.generate_content(
        model=os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite"),
        contents=[
            {
                "role": "user",
                "parts": [
                    {"text": f"{system_prompt}\n\nUser task: {user_prompt}"},
                    {
                        "inline_data": {
                            "mime_type": "image/png",
                            "data": __import__("base64").b64encode(image_data).decode(),
                        }
                    },
                ],
            }
        ],
    )

    # Parse response
    response_text = response.text.strip()

    # Loai bo markdown code fences neu co
    if response_text.startswith("```"):
        lines = response_text.split("\n")
        # Bo dong dau (```json) va dong cuoi (```)
        lines = [l for l in lines if not l.strip().startswith("```")]
        response_text = "\n".join(lines)

    try:
        plan_data = json.loads(response_text)
        plan = ActionPlan(**plan_data)
        actions = [action.model_dump() for action in plan.actions]
        logger.info(f"Generated {len(actions)} action(s) from Gemini")
        return actions
    except (json.JSONDecodeError, Exception) as e:
        logger.error(f"Failed to parse Gemini response: {e}")
        logger.error(f"Raw response: {response_text[:500]}")
        raise


def save_action_plan(actions: list[dict], output_path: str = "workspace/plan.json") -> str:
    """Luu ke hoach hanh dong ra file JSON."""
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(actions, f, indent=2, ensure_ascii=False)
    logger.info(f"Action plan saved: {output_path} ({len(actions)} actions)")
    return output_path
