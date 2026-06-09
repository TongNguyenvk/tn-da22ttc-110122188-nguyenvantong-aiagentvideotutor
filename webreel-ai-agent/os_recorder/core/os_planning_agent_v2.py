"""
OS Planning Agent - Agent do duong su dung Gemini.

Kien truc 2 pha:
  1. Plan-Only: Agent loop chup screenshot + doc element tree + hoi Gemini
     -> sinh file plan.json (khong quay video, khong co latency concern)
  2. Record-Replay: Doc plan.json, bam dieu khien muot + quay FFmpeg dong bo.

3 fix quan trong:
  - Fix #1 (DOM Explosion): Prune Tree chi gui interactive elements cho LLM
  - Fix #2 (Duplicate Trap): Index + toa do cho moi element
  - Fix #3 (Latency): Tach Plan va Replay thanh 2 buoc rieng biet
"""

import json
import time
import base64
import logging
import os
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Fix #1: Prune Tree - Chi lay interactive elements
# ---------------------------------------------------------------------------
INTERACTIVE_TYPES = {
    "Button", "Edit", "Document", "MenuItem", "MenuBar", "Menu",
    "Hyperlink", "Link", "ListItem", "TreeItem",
    "TabItem", "CheckBox", "RadioButton", "ComboBox",
    "SplitButton", "ToggleButton", "Slider", "ScrollBar",
    "DataItem", "DataGrid", "Table",
}

# Types phu chi gui khi co name (de giam nhieu)
CONDITIONAL_TYPES = {
    "Text", "Pane", "Group", "ToolBar",
}


@dataclass
class IndexedElement:
    """Element da duoc danh index + toa do."""
    index: int
    control_type: str
    name: str
    automation_id: str
    center_x: int
    center_y: int
    width: int
    height: int
    value: str = ""
    is_enabled: bool = True


def prune_and_index_tree(root) -> list[IndexedElement]:
    """
    Fix #1 + #2: Loc cay element chi lay interactive + danh index.

    Tra ve list IndexedElement de gui cho LLM.
    Giam tu hang tram elements xuong con vai chuc, tiet kiem token.
    """
    indexed = []
    counter = [0]  # Mutable counter cho closure

    def _collect(elem):
        is_interactive = elem.control_type in INTERACTIVE_TYPES
        is_conditional = (
            elem.control_type in CONDITIONAL_TYPES
            and elem.name
            and len(elem.name.strip()) > 0
        )

        if (is_interactive or is_conditional) and elem.is_enabled:
            cx, cy = elem.center
            indexed.append(IndexedElement(
                index=counter[0],
                control_type=elem.control_type,
                name=elem.name,
                automation_id=elem.automation_id,
                center_x=cx,
                center_y=cy,
                width=elem.width,
                height=elem.height,
                value=elem.value,
                is_enabled=elem.is_enabled,
            ))
            counter[0] += 1

        for child in elem.children:
            _collect(child)

    _collect(root)
    return indexed


def format_elements_for_llm(elements: list[IndexedElement]) -> str:
    """
    Fix #2: Format element list de gui cho LLM.
    Compact, de doc, co index + toa do.
    """
    lines = []
    for e in elements:
        name_str = f' "{e.name}"' if e.name else ""
        val_str = f" ={e.value}" if e.value else ""
        aid_str = f" #{e.automation_id}" if e.automation_id else ""
        lines.append(
            f"[{e.index}] {e.control_type}{name_str}{aid_str}{val_str} "
            f"({e.center_x},{e.center_y}) {e.width}x{e.height}"
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Gemini client
# ---------------------------------------------------------------------------
def _get_gemini_client():
    """Tao Gemini client tu API key trong .env."""
    from dotenv import load_dotenv
    load_dotenv()

    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise ValueError(
            "GEMINI_API_KEY hoac GOOGLE_API_KEY chua duoc dat trong .env\n"
            "Tao file os_recorder/.env voi noi dung:\n"
            "GEMINI_API_KEY=your_key_here"
        )

    from google import genai
    return genai.Client(api_key=api_key)


# ---------------------------------------------------------------------------
# System prompt cho Gemini
# ---------------------------------------------------------------------------
SYSTEM_PROMPT = """You are an OS Automation Agent. You look at a screenshot of a desktop application and its interactive UI elements, then decide the NEXT SINGLE action to perform.

AVAILABLE UI ELEMENTS (indexed):
Each element has: [index] ControlType "Name" (centerX, centerY) widthXheight

AVAILABLE ACTIONS:
- click_element: Click an element by its index. Use "element_index" field. (To click specific text or a specific cell block, use the "target_value" field instead).
- drag_mouse: Drag the mouse from one element to another to select/highlight. Use "start_index" and "end_index" fields from the UI ELEMENTS list. (To highlight a specific phrase or drag across a cell range, use the "target_value" field containing the exact phrase/range).
- type_text: Type text into the focused element. Use "text" field.
- press_key: Press a SAFE key. Allowed: a-z, 0-9, space, enter, tab, escape, right, left, up, down, f5, pageup, pagedown, home, end. Use "key" field. Optional use "repeat" integer field.
- press_hotkey: Press a combination of keys together. Use "keys" array field (e.g. ["ctrl", "b"]). You can also optionally use "repeat" integer field to press it multiple times. Allowed modifiers: shift, ctrl, alt, win plus all regular keys. **CRITICAL: You MUST use `press_hotkey` for ALL text formatting (bold, color, size, alignment) and slide navigation (F5, next) instead of clicking the Ribbon UI!** Do not click Ribbon buttons!
- scroll: Scroll mouse wheel. Use "amount" field (positive=up, negative=down).
- wait: Wait for a duration. Use "duration_ms" field.
- done: Task is complete. No more actions needed.

RESPONSE FORMAT (JSON only):
{
  "thought": "Brief analysis of current screen state and what to do next",
  "action": {
    "action_type": "click_element",
    "target_value": "B6"
  },
  "narration": "Vietnamese narration for this step (2-3 sentences, lecturer style, WITH DIACRITICS)",
  "is_done": false
}

RULES:
1. Return EXACTLY ONE action per response.
2. The "narration" field is for video voiceover. Write in Vietnamese WITH FULL DIACRITICS. Be engaging like a lecturer.
3. Set "is_done": true ONLY when the FULL MULTI-PART task is 100% complete. If the task asks for multiple things (e.g., "increase size AND italicize"), you MUST perform one action, and on the next turn perform the other action. Do NOT set is_done=true until ALL requirements of the user task are met! Include a closing narration when actually done.
4. **IMPORTANT FOR PRESENTATIONS**: When navigating through slides (PowerPoint, PDF, etc.), do NOT mark is_done=true until you see a clear END indicator (e.g., "Thank You" slide, black screen after last slide, or the presentation exits slideshow mode). Keep pressing navigation keys (right, space, pagedown) until you reach the actual end. Do NOT assume you are at the end just because the current slide looks like a conclusion.
5. For click_element on UI buttons, menus, Ribbon tabs, dropdowns (e.g. Font Size, Insert, Bold): ALWAYS use the "element_index" from the UI ELEMENTS list! DO NOT use "target_value" for UI controls!
6. ONLY use "target_value" when you want to interact with TEXT CONTENT inside the document/spreadsheet workspace itself (e.g. clicking a specific sentence, dragging a cell range, or targeting a text you just typed).
7. For type_text, the text will be typed into whatever element currently has focus.
8. NEVER use dangerous keys (delete, backspace, win).
9. If the UI has changed after an action, analyze the NEW screenshot before deciding.
10. CRITICAL: When using 'press_hotkey', your 'narration' MUST explicitly read out loud the key combination being pressed so the viewer can learn it. Examples: "ấn tổ hợp phím Control và B", "sử dụng phím tắt Control, Shift và phím lớn hơn".

RECOMMENDED HOTKEYS (Use these INSTEAD OF click_element):
- **Word / Excel Formatting**:
  - `["ctrl", "b"]`: Bold
  - `["ctrl", "i"]`: Italic
  - `["ctrl", "u"]`: Underline
  - `["ctrl", "e"]`: Align Center
  - `["ctrl", "l"]`: Align Left
  - `["ctrl", "r"]`: Align Right
  - `["ctrl", "j"]`: Justify
  - `["ctrl", "]"]`: Increase Font Size (Use "repeat": 5 to make it visibly larger)
  - `["ctrl", "["]`: Decrease Font Size (Use "repeat": 5 to make it visibly smaller)
  - `["ctrl", "z"]`: Undo
  - `["ctrl", "y"]`: Redo
- **PowerPoint Navigation**:
  - `["f5"]`: Start Slide Show from beginning
  - `["shift", "f5"]`: Start Slide Show from current slide
  - `["space"]` or `["right"]` or `["enter"]` or `["pagedown"]`: Next Slide / Next Animation
  - `["left"]` or `["pageup"]` or `["backspace"]`: Previous Slide
  - `["esc"]`: End Slide Show
"""

# PowerPoint-specific prompt (giảng viên giảng bài)
POWERPOINT_PROMPT = """You are a LECTURER presenting a PowerPoint presentation. You look at a screenshot of the presentation and decide the NEXT action to navigate through slides.

AVAILABLE ACTIONS:
- press_hotkey: Press a combination of keys. Use "keys" array field (e.g. ["f5"], ["right"]).
- press_key: Press a single key. Use "key" field (e.g. "right", "space", "escape").
- done: Presentation is complete.

RESPONSE FORMAT (JSON only):
{
  "thought": "Brief analysis of current slide content",
  "action": {
    "action_type": "press_key",
    "key": "right"
  },
  "narration": "Vietnamese lecture content explaining THIS SLIDE (3-5 sentences, AS IF you are a professor teaching students, WITH DIACRITICS)",
  "is_done": false
}

CRITICAL RULES FOR NARRATION:
1. **ACT AS A LECTURER**: Your narration should explain the CONTENT of the current slide, NOT the technical action.
2. **EXPLAIN THE SLIDE**: Read and interpret what you see on the slide. Explain concepts, data, images as if teaching students.
3. **BE EDUCATIONAL**: Use phrases like "Như các bạn thấy trên slide...", "Điểm quan trọng ở đây là...", "Chúng ta có thể thấy rằng..."
4. **DO NOT SAY**: "Tôi sẽ nhấn phím...", "Chúng ta chuyển sang slide tiếp theo...", "Sử dụng phím tắt..."
5. **INSTEAD SAY**: Explain what the slide shows, what students should learn, key takeaways.
6. Write in Vietnamese WITH FULL DIACRITICS.
7. 3-5 sentences per slide, engaging and educational.

NAVIGATION RULES:
1. Start presentation with F5 hotkey: `{"action_type": "press_hotkey", "keys": ["f5"]}`
2. Navigate to next slide: `{"action_type": "press_key", "key": "right"}` or `{"action_type": "press_key", "key": "space"}`
3. Set "is_done": true ONLY when you see "End of slide show" black screen or presentation exits slideshow mode.
4. Do NOT mark done just because a slide looks like conclusion. Keep going until you see the actual end.

EXAMPLE NARRATIONS (GOOD):
- "Chào mừng các bạn đến với bài giảng hôm nay về giải pháp tài chính cá nhân. Trong bài này, chúng ta sẽ tìm hiểu về các phương pháp quản lý tài chính hiệu quả và xây dựng kế hoạch đầu tư thông minh."
- "Như các bạn thấy trên slide, đồng cảm là yếu tố then chốt trong giao tiếp. Khi chúng ta thực sự lắng nghe và hiểu cảm xúc của người khác, chúng ta có thể xây dựng mối quan hệ bền vững hơn."
- "Phân tích cạnh tranh cho thấy thị trường hiện tại có nhiều cơ hội phát triển. Các doanh nghiệp cần tập trung vào điểm mạnh của mình để tạo ra lợi thế cạnh tranh bền vững."

EXAMPLE NARRATIONS (BAD - DO NOT DO THIS):
- "Tôi sẽ nhấn phím F5 để bắt đầu trình chiếu." (WRONG)
- "Chúng ta chuyển sang slide tiếp theo bằng phím mũi tên phải." (WRONG)
- "Tiếp tục bài giảng, sử dụng phím tắt để di chuyển." (WRONG)

POWERPOINT NAVIGATION KEYS:
- `["f5"]`: Start Slide Show from beginning
- `["right"]`, `["space"]`, `["pagedown"]`: Next Slide
- `["escape"]`: End Slide Show
"""

# Browser-specific prompt (OS-level control, no UIA for web content)
BROWSER_PROMPT = """You are an OS Automation Agent controlling a web browser (Chrome/Edge/Firefox) using OS-level input.

CRITICAL LIMITATION:
- You CANNOT see or click individual web page elements via the UI element list. The browser only exposes its toolbar (address bar, tabs) to the OS, NOT the web page content.
- You CAN see everything in the SCREENSHOT. Use the screenshot to identify clickable areas visually.
- For web page interactions, you MUST use "mouse_click" with (x, y) coordinates from the screenshot.

COORDINATE SIZING (Bounding Box Mode):
- You MUST output the target element's location as a 2D bounding box `[ymin, xmin, ymax, xmax]` normalized to a 1000x1000 scale.
- 0 means top/left edge, 1000 means bottom/right edge of the screenshot.
- Example: If a button is at the exact center of the screen, the bounding box might be `[480, 480, 520, 520]`.
- For web page interactions, you MUST use "mouse_click" with the "box" field.

SPECIAL SHORTCUTS FOR COMMON TASKS:
1. GOOGLE SEARCH: Instead of clicking the search box, use press_hotkey ["ctrl", "l"] to focus address bar, then type_text the query, then press_key "enter". This is MORE RELIABLE than clicking.
2. NAVIGATE TO URL: Use press_hotkey ["ctrl", "l"], then type_text the URL, then press_key "enter".
3. NEW TAB: Use press_hotkey ["ctrl", "t"].
4. CLOSE TAB: Use press_hotkey ["ctrl", "w"].

AVAILABLE ACTIONS:
- mouse_click: Click at a specific bounding box. Use the "box" field (array of 4 numbers [ymin, xmin, ymax, xmax]). Use this for ALL web page elements.
- type_text: Type text into the focused element. Use "text" field.
- press_key: Press a key. Use "key" field. Allowed: a-z, 0-9, space, enter, tab, escape, right, left, up, down, f5, pageup, pagedown, home, end.
- press_hotkey: Press key combination. Use "keys" array field. Allowed modifiers: shift, ctrl, alt.
- scroll: Scroll mouse wheel. Use "amount" field (positive=up, negative=down).
- wait: Wait for page load. Use "duration_ms" field.
- done: Task is complete.

RESPONSE FORMAT (JSON only):
{
  "thought": "I see the Google search page. Instead of clicking the search box, I'll use Ctrl+L to focus the address bar",
  "action": {
    "action_type": "press_hotkey",
    "keys": ["ctrl", "l"]
  },
  "narration": "Vietnamese narration (2-3 sentences, WITH DIACRITICS)",
  "is_done": false
}

BROWSER TIPS (MUST follow):
- To focus the ADDRESS BAR: Use press_hotkey ["ctrl", "l"]. NEVER click on the address bar directly.
- To type a URL: First press_hotkey ["ctrl", "l"], then type_text with the URL, then press_key "enter".
- For GOOGLE SEARCH: Use press_hotkey ["ctrl", "l"], type_text the query, press_key "enter". DO NOT try to click the search box.
- Tab key can cycle focus between input fields on a web page.

EMAIL COMPOSE WORKFLOW (Gmail/Outlook):
- When a compose popup opens, the "To" field is ALREADY FOCUSED. Just use type_text directly.
- After typing the recipient email, press Enter FIRST to CONFIRM the autocomplete suggestion. This is critical: without Enter, the email is not confirmed.
- After pressing Enter (confirm recipient), press Tab to move to the Subject field.
- After Tab, the Subject field is focused. Use type_text directly WITHOUT clicking.
- Complete field navigation sequence: type_text (recipient) -> press_key "enter" (confirm) -> press_key "tab" (move to Subject) -> type_text (subject) -> press_key "tab" (move to Body) -> type_text (body).
- To send the email: press_hotkey ["ctrl", "enter"].
- IMPORTANT: The compose popup appears at the BOTTOM-RIGHT corner of the browser. Its coordinates are at HIGH x values (x > 1200) and HIGH y values (y > 400). NEVER click at low x values (< 800) to interact with the compose popup.

RULES:
1. Return EXACTLY ONE action per response.
2. For web page elements: ALWAYS use "mouse_click" with the "box" field.
3. In your "thought", explain your bounding box choice based on the visual screenshot.
4. NEVER click directly on the browser address bar. Use press_hotkey ["ctrl", "l"] instead.
5. For GOOGLE SEARCH, ALWAYS use Ctrl+L shortcut instead of clicking the search box.
6. When a field is ALREADY FOCUSED (after Tab or after opening compose), use type_text directly. DO NOT click first.
7. Coordinates should be the CENTER of the target element.
8. Write narrations in Vietnamese WITH FULL DIACRITICS.
9. Set "is_done": true ONLY when the FULL task is 100% complete.
10. If a page is loading, use "wait" with appropriate duration.
11. NEVER use dangerous keys (delete, backspace, win).
"""

# ---------------------------------------------------------------------------
# Coordinate Grid Overlay (giup model nhe uoc toa do chinh xac hon)
# ---------------------------------------------------------------------------
def _add_coordinate_grid(
    image_path: str,
    output_path: str,
    grid_spacing: int = 200,
) -> str:
    """
    Ve luoi toa do len screenshot de giup LLM uoc toa do chinh xac.
    Luoi nhe, mau do nhat, khong che noi dung.
    """
    try:
        from PIL import Image, ImageDraw, ImageFont

        img = Image.open(image_path)
        draw = ImageDraw.Draw(img, "RGBA")
        w, h = img.size

        # Mau do nhat ban trong
        line_color = (255, 0, 0, 60)
        text_color = (255, 0, 0, 180)
        bg_color = (255, 255, 255, 140)

        try:
            font = ImageFont.truetype("arial.ttf", 14)
        except Exception:
            font = ImageFont.load_default()

        # Ve duong doc + nhan x
        for x in range(grid_spacing, w, grid_spacing):
            draw.line([(x, 0), (x, h)], fill=line_color, width=1)
            label = str(x)
            bbox = font.getbbox(label)
            tw = bbox[2] - bbox[0]
            th = bbox[3] - bbox[1]
            draw.rectangle([x + 2, 2, x + tw + 6, th + 6], fill=bg_color)
            draw.text((x + 4, 2), label, fill=text_color, font=font)

        # Ve duong ngang + nhan y
        for y in range(grid_spacing, h, grid_spacing):
            draw.line([(0, y), (w, y)], fill=line_color, width=1)
            label = str(y)
            bbox = font.getbbox(label)
            tw = bbox[2] - bbox[0]
            th = bbox[3] - bbox[1]
            draw.rectangle([2, y + 2, tw + 6, y + th + 6], fill=bg_color)
            draw.text((4, y + 2), label, fill=text_color, font=font)

        # Them goc toa do (0,0)
        draw.text((4, 2), "0,0", fill=text_color, font=font)

        img.save(output_path)
        return output_path
    except Exception as e:
        logger.warning(f"  Grid overlay failed: {e}, using original")
        return image_path


# ---------------------------------------------------------------------------
# Agent step result
# ---------------------------------------------------------------------------
@dataclass
class AgentStep:
    """Ket qua mot buoc cua agent."""
    step_index: int
    thought: str
    action: dict
    narration: str
    is_done: bool
    screenshot_path: str = ""
    elements_count: int = 0


@dataclass
class AgentResult:
    """Ket qua toan bo qua trinh planning."""
    steps: list[AgentStep]
    plan: list[dict]  # Danh sach action de replay
    is_complete: bool
    total_narrations: int


# ---------------------------------------------------------------------------
# OS Planning Agent
# ---------------------------------------------------------------------------
class OSPlanningAgent:
    """
    Agent do duong: nhin man hinh + doc element tree + hoi Gemini.

    Fix #3: Chi DO DUONG, khong quay video.
    Output la plan.json de replay sau.
    """

    def __init__(
        self,
        pid: int,
        user_task: str,
        max_steps: int = 15,
        output_dir: str = "workspace",
        model: str = os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite"),
        app_type: str = "auto",
    ):
        self.pid = pid
        self.user_task = user_task
        self.max_steps = max_steps
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.model = model
        self.app_type = app_type

        self.client = _get_gemini_client()
        self.steps: list[AgentStep] = []
        self.history: list[dict] = []
        self.current_slide_number = 0
        
        # Parse slide scripts from user_task if provided
        self.slide_scripts = self._parse_slide_scripts(user_task)
        if self.slide_scripts:
            logger.info(f"  Parsed {len(self.slide_scripts)} slide scripts from user task")
        
        # Auto-detect app type
        if self.app_type == "auto":
            self.app_type = self._detect_app_type()
            logger.info(f"  Auto-detected app type: {self.app_type}")
    
    def _parse_slide_scripts(self, task: str) -> dict:
        """
        Parse slide scripts from user task.
        Format: "Slide 1: content\nSlide 2: content\n..."
        Returns: {1: "content", 2: "content", ...}
        """
        import re
        scripts = {}
        
        # Pattern: "Slide X:" hoặc "Slide X -" hoặc "Trang X:"
        pattern = r'(?:Slide|slide|Trang|trang)\s*(\d+)\s*[:\-]\s*(.+?)(?=(?:Slide|slide|Trang|trang)\s*\d+\s*[:\-]|$)'
        matches = re.findall(pattern, task, re.DOTALL | re.IGNORECASE)
        
        for slide_num, content in matches:
            scripts[int(slide_num)] = content.strip()
        
        return scripts
    
    def _detect_app_type(self) -> str:
        """Detect application type based on window title."""
        try:
            from pywinauto import Application
            app = Application(backend="uia").connect(process=self.pid)
            window_title = app.top_window().window_text()

            if "PowerPoint" in window_title or ".pptx" in window_title or ".ppt" in window_title:
                return "powerpoint"
            elif "Word" in window_title or ".docx" in window_title or ".doc" in window_title:
                return "word"
            elif "Excel" in window_title or ".xlsx" in window_title or ".xls" in window_title:
                return "excel"
            # Browser detection
            elif any(b in window_title for b in [
                "Chrome", "Google Chrome", "Edge", "Firefox", "Brave",
                "Opera", "Vivaldi",
            ]):
                return "browser"
            else:
                return "general"
        except Exception as e:
            logger.warning(f"  Failed to detect app type: {e}, using 'general'")
            return "general"

    def run(self, dry_run: bool = False) -> AgentResult:
        """
        Chạy agent loop.

        Bước 2 (Silent Phase 1): Dùng pywinauto API thay vì pyautogui.
        -> Không chiếm chuột vật lý, bạn vẫn dùng máy bình thường.

        Args:
            dry_run: True = chỉ chụp screenshot + gọi Gemini, KHÔNG thực thi.
                     False = thực thi bằng pywinauto silent API, KHÔNG quay video.
        """
        from core.ui_inspector import get_element_tree
        from core.vision_agent import capture_window_by_pid
        from core.os_executor import is_key_safe

        mode_str = "DRY-RUN" if dry_run else "PLAN-ONLY (silent, không chiếm chuột)"
        logger.info(f"{'='*60}")
        logger.info(f"  OS Planning Agent: {self.user_task[:50]}")
        logger.info(f"  Mode: {mode_str}")
        logger.info(f"  PID: {self.pid} | Max steps: {self.max_steps}")
        logger.info(f"{'='*60}")

        # Kết nối pywinauto (cho silent execution)
        from pywinauto import Application
        app = Application(backend="uia").connect(process=self.pid)

        gemini_error = None

        for step_idx in range(self.max_steps):
            logger.info(f"\n--- Step {step_idx + 1}/{self.max_steps} ---")

            # 1. Focus cửa sổ (silent: dùng pywinauto set_focus)
            if not dry_run:
                try:
                    app.top_window().set_focus()
                    time.sleep(0.3)
                except Exception as e:
                    logger.warning(f"  Focus failed: {e}")

            # 2. Chup screenshot va lay window rect
            screenshot_path = str(self.output_dir / f"step_{step_idx:03d}.png")
            from core.window_manager import get_window_rect_by_pid
            win_rect = get_window_rect_by_pid(self.pid)  # (left, top, w, h)
            capture_window_by_pid(self.pid, screenshot_path)
            img_w = win_rect[2] if win_rect else 1920
            img_h = win_rect[3] if win_rect else 1080
            logger.info(f"  Screenshot: {screenshot_path} ({img_w}x{img_h})")

            # 2.5 Bo qua tao Grid, su dung Native Bounding Box
            gemini_screenshot = screenshot_path

            # 3. Lay element tree + prune + index
            root = get_element_tree(self.pid, max_depth=4)
            indexed_elements = prune_and_index_tree(root)
            elements_text = format_elements_for_llm(indexed_elements)
            logger.info(f"  Elements: {len(indexed_elements)} interactive (pruned)")

            # 4. Goi Gemini (co retry, raise neu that bai het)
            try:
                agent_step = self._call_gemini(
                    step_idx, gemini_screenshot, elements_text, indexed_elements,
                    image_size=(img_w, img_h),
                )
            except RuntimeError as e:
                gemini_error = e
                logger.error(f"  Gemini thất bại, dừng agent: {e}")
                break

            agent_step.screenshot_path = screenshot_path
            agent_step.elements_count = len(indexed_elements)
            self.steps.append(agent_step)

            logger.info(f"  Thought: {agent_step.thought[:80]}")
            logger.info(f"  Action: {agent_step.action}")
            logger.info(f"  Narration: {agent_step.narration[:60]}")
            logger.info(f"  Done: {agent_step.is_done}")

            # 5. Anti-loop: Phát hiện loop thực sự (không áp dụng cho phím điều hướng slide)
            action = agent_step.action
            action_type = action.get("action_type", "")

            # Danh sách phím được phép lặp (dùng cho PowerPoint, PDF viewer, etc.)
            ALLOWED_REPEAT_KEYS = {
                "space", "right", "left", "down", "up", 
                "page_down", "page_up", "pagedown", "pageup",
                "enter", "return"
            }

            if len(self.steps) >= 5:  # Tăng từ 3 lên 5 để tránh false positive
                recent_actions = [
                    (s.action.get("action_type"), s.action.get("key", "").lower(), s.action.get("target_value"))
                    for s in self.steps[-5:]
                ]
                
                # Kiểm tra xem có phải là phím điều hướng được phép lặp không
                is_navigation_key = False
                if action_type in ("press_key", "press_hotkey"):
                    key = action.get("key", "").lower()
                    keys = action.get("keys", [])
                    if key in ALLOWED_REPEAT_KEYS or any(k.lower() in ALLOWED_REPEAT_KEYS for k in keys):
                        is_navigation_key = True
                
                # Chỉ phát hiện loop nếu KHÔNG phải phím điều hướng và lặp 5 lần liên tục
                if not is_navigation_key and len(set(recent_actions)) == 1:
                    logger.warning(
                        f"  LOOP DETECTED: '{recent_actions[0]}' lap 5 lan -> Tu dong chuyen buoc"
                    )
                    # Giu lai step nay nhung gia lap thanh done de thoat
                    agent_step.is_done = True

            # 6. Thuc thi hanh dong (Silent - pywinauto API)
            if not dry_run and action_type != "done" and not agent_step.is_done:
                self._execute_silent(
                    action, action_type, indexed_elements, app, root
                )
                time.sleep(0.5)  # Cho UI update

            # 6. Kiểm tra done
            if agent_step.is_done:
                logger.info("Agent báo hiệu: HOÀN TẤT!")
                break

        # Reset trạng thái ứng dụng sau khi dò đường
        # Đếm hành động đã thay đổi state (type, press_key, click)
        if not dry_run:
            undo_count = 0
            for s in self.steps:
                act = s.action.get("action_type", "")
                if act in ("type_text", "press_key", "click_element"):
                    undo_count += 1

            if undo_count > 0:
                logger.info(f"\n  Resetting state: Ctrl+Z x {undo_count + 2}")
                try:
                    win = app.top_window()
                    win.set_focus()
                    time.sleep(0.3)
                    # Undo nhiều hơn số action 1 chút cho chắc
                    for _ in range(undo_count + 2):
                        win.type_keys("^z", pause=0.1)
                    time.sleep(0.5)
                    logger.info("  State reset OK")
                except Exception as e:
                    logger.warning(f"  State reset failed: {e}")

        # Sinh plan.json để replay (kể cả khi lỗi, lưu những gì đã làm)
        plan = self._build_replay_plan()
        plan_path = self.output_dir / "plan.json"
        with open(plan_path, "w", encoding="utf-8") as f:
            json.dump(plan, f, indent=2, ensure_ascii=False)
        logger.info(f"Plan saved: {plan_path} ({len(plan)} actions)")

        # Nếu Gemini lỗi -> raise để pipeline dừng ngay
        if gemini_error:
            raise gemini_error

        total_narrations = sum(1 for s in self.steps if s.narration.strip())

        result = AgentResult(
            steps=self.steps,
            plan=plan,
            is_complete=any(s.is_done for s in self.steps),
            total_narrations=total_narrations,
        )

        logger.info(f"{'='*60}")
        logger.info(f"  Agent complete: {len(self.steps)} steps, {total_narrations} narrations")
        logger.info(f"  Plan: {plan_path} ({len(plan)} replay actions)")
        logger.info(f"{'='*60}")

        return result

    def _execute_silent(self, action, action_type, indexed_elements, app, root):
        """
        Bước 2: Thực thi hành động bằng pywinauto API (silent, không chiếm chuột).
        Lưu UIA selector vào action để build plan.json (Bước 1).
        """
        from core.os_executor import is_key_safe
        from core.ui_inspector import find_element

        # Xử lý dò đường Universal
        target_val = action.get("target_value")
        if target_val:
            from core.universal_engine import get_universal_engine
            engine = get_universal_engine()
            
            # Thoát chế độ Edit Mode của Excel trước khi thao tác COM nếu đang bị kẹt
            if engine._determine_context(app.process) == "excel":
                try:
                    win = app.top_window()
                    win.type_keys("{ESC}")
                except:
                    pass

            if action_type == "click_element":
                if engine.get_coordinates(target_val, app.process):
                    # Thực hiện focus (thay đổi visual) để screenshot tiếp theo Agent nhận ra đã click
                    engine.focus_element(target_val, app.process)
                    action.pop("element_index", None)
                    time.sleep(0.5)
                    return
            elif action_type == "type_text":
                text = action.get("text", "")
                if engine.inject_data(target_val, text, app.process):
                    time.sleep(0.5)
                    return
            elif action_type == "drag_mouse":
                if engine.get_range_coordinates(target_val, app.process):
                    # Thực hiện focus (thay đổi visual) để screenshot tiếp theo Agent nhận ra đã drag bôi đen
                    engine.focus_element(target_val, app.process)
                    action.pop("start_index", None)
                    action.pop("end_index", None)
                    time.sleep(0.5)
                    return

        if action_type == "click_element":
            elem_idx = action.get("element_index", -1)
            if 0 <= elem_idx < len(indexed_elements):
                elem = indexed_elements[elem_idx]
                # Bước 1: Lưu UIA selector vào action (thay vì tọa độ)
                action["selector"] = {
                    "control_type": elem.control_type,
                    "name": elem.name,
                    "automation_id": elem.automation_id,
                    "index": elem.index,
                }
                # Lưu tọa độ backup (fallback)
                action["fallback_coords"] = {
                    "x": elem.center_x, "y": elem.center_y,
                }
                logger.info(
                    f"  -> Silent click [{elem_idx}] "
                    f"{elem.control_type} \"{elem.name}\" #{elem.automation_id}"
                )
                # Silent click: dùng pywinauto .click() (không chiếm chuột)
                try:
                    uia_elem = self._find_uia_wrapper(app, elem)
                    if uia_elem:
                        uia_elem.click()
                    else:
                        # Fallback: invoke
                        logger.warning(f"  -> Wrapper not found, trying invoke")
                except Exception as e:
                    logger.warning(f"  -> Silent click failed: {e}")
            else:
                logger.warning(f"  -> Element index {elem_idx} out of range!")

        elif action_type == "type_text":
            text = action.get("text", "")
            if text:
                logger.info(f"  -> Silent type: {text[:40]}")
                try:
                    # Dùng pywinauto type_keys (không chiếm chuột)
                    win = app.top_window()
                    win.type_keys(text, with_spaces=True, pause=0.03)
                except Exception as e:
                    logger.warning(f"  -> Silent type failed: {e}")

        elif action_type == "press_key":
            key = action.get("key", "")
            repeat = action.get("repeat", 1)
            if is_key_safe(key):
                logger.info(f"  -> Silent press: {key} (x{repeat})")
                try:
                    import pyautogui
                    for _ in range(repeat):
                        pyautogui.press(key)
                        time.sleep(0.05)
                except Exception as e:
                    logger.warning(f"  -> Silent key failed: {e}")
            else:
                logger.warning(f"  -> Key '{key}' BLOCKED")

        elif action_type == "press_hotkey":
            keys = action.get("keys", [])
            repeat = action.get("repeat", 1)
            safe = all(is_key_safe(k) for k in keys) if keys else False
            if safe:
                logger.info(f"  -> Silent hotkey: {keys} (x{repeat})")
                try:
                    import pyautogui
                    try:
                        win = app.top_window()
                        win.set_focus()
                    except:
                        pass
                    for _ in range(repeat):
                        pyautogui.hotkey(*[k.lower() for k in keys])
                        time.sleep(0.01)
                    time.sleep(0.05)
                except Exception as e:
                    logger.warning(f"  -> Silent hotkey failed: {e}")
            else:
                logger.warning(f"  -> Hotkey {keys} BLOCKED or INVALID")

        elif action_type == "drag_mouse":
            start_idx = action.get("start_index", -1)
            end_idx = action.get("end_index", -1)
            
            if 0 <= start_idx < len(indexed_elements) and 0 <= end_idx < len(indexed_elements):
                s_elem = indexed_elements[start_idx]
                e_elem = indexed_elements[end_idx]
                
                action["start_selector"] = {
                    "control_type": s_elem.control_type,
                    "name": s_elem.name,
                    "automation_id": s_elem.automation_id,
                    "index": s_elem.index,
                }
                action["start_fallback"] = {"x": s_elem.center_x, "y": s_elem.center_y}
                
                action["end_selector"] = {
                    "control_type": e_elem.control_type,
                    "name": e_elem.name,
                    "automation_id": e_elem.automation_id,
                    "index": e_elem.index,
                }
                action["end_fallback"] = {"x": e_elem.center_x, "y": e_elem.center_y}
                
                logger.info(f"  -> Silent drag from [{start_idx}] to [{end_idx}]")
            else:
                logger.warning(f"  -> Drag index out of range!")

        elif action_type == "scroll":
            amount = action.get("amount", 0)
            logger.info(f"  -> Silent scroll: {amount}")
            try:
                import pyautogui
                pyautogui.scroll(amount)  # Scroll vẫn cần pyautogui
            except Exception:
                pass

        elif action_type == "wait":
            dur = action.get("duration_ms", 1000)
            logger.info(f"  -> Wait: {dur}ms")
            time.sleep(dur / 1000.0)

        elif action_type == "mouse_click":
            # Toa do tu Gemini la window-relative (theo anh screenshot)
            # Can chuyen sang screen coords bang cach cong window offset
            img_x = action.get("x", 0)
            img_y = action.get("y", 0)
            try:
                from core.window_manager import get_window_rect_by_pid
                win_rect = get_window_rect_by_pid(self.pid)
                if win_rect:
                    screen_x = win_rect[0] + img_x
                    screen_y = win_rect[1] + img_y
                else:
                    screen_x, screen_y = img_x, img_y
                logger.info(f"  -> Silent mouse_click: img({img_x},{img_y}) -> screen({screen_x},{screen_y})")
                import pyautogui
                pyautogui.click(screen_x, screen_y)
            except Exception as e:
                logger.warning(f"  -> mouse_click failed: {e}")

    def _find_uia_wrapper(self, app, elem: IndexedElement):
        """
        Tìm pywinauto wrapper cho element (để gọi .click() silent).
        """
        try:
            win = app.top_window()
            # Tìm theo automation_id trước (chính xác nhất)
            if elem.automation_id:
                try:
                    found = win.child_window(
                        auto_id=elem.automation_id,
                        control_type=elem.control_type,
                    )
                    if found.exists():
                        return found
                except Exception:
                    pass
            # Tìm theo name + control_type
            if elem.name:
                try:
                    found = win.child_window(
                        title=elem.name,
                        control_type=elem.control_type,
                    )
                    if found.exists():
                        return found
                except Exception:
                    pass
            # Fallback: chỉ theo control_type
            try:
                found = win.child_window(control_type=elem.control_type)
                if found.exists():
                    return found
            except Exception:
                pass
        except Exception as e:
            logger.warning(f"  -> UIA wrapper search failed: {e}")
        return None

    def _call_gemini(
        self,
        step_idx: int,
        screenshot_path: str,
        elements_text: str,
        indexed_elements: list[IndexedElement],
        max_retries: int = 3,
        image_size: tuple[int, int] = None,
    ) -> AgentStep:
        """Goi Gemini voi screenshot + element list. Retry khi 503/429."""

        # Doc screenshot
        with open(screenshot_path, "rb") as f:
            image_bytes = f.read()

        # Build history context
        history_text = ""
        if self.steps:
            history_lines = []
            for s in self.steps[-5:]:
                act = s.action.get("action_type", "")
                tgt = str(s.action.get("element_index", s.action.get("text", s.action.get("key", ""))))
                history_lines.append(f"Step {s.step_index}: {act} -> {tgt}")
            history_text = "\nPREVIOUS ACTIONS:\n" + "\n".join(history_lines)

        # Select appropriate prompt based on app type
        if self.app_type == "powerpoint":
            system_prompt = POWERPOINT_PROMPT
        elif self.app_type == "browser":
            system_prompt = BROWSER_PROMPT
        else:
            system_prompt = SYSTEM_PROMPT

        # User prompt - them kich thuoc anh de Gemini biet coordinate space
        size_hint = ""
        if image_size:
            size_hint = f"\nSCREENSHOT SIZE: {image_size[0]}x{image_size[1]} pixels. All mouse_click x,y coordinates must be within this range (0 <= x < {image_size[0]}, 0 <= y < {image_size[1]}).\n"

        user_prompt = (
            f"USER TASK: {self.user_task}\n\n"
            f"{size_hint}"
            f"INTERACTIVE UI ELEMENTS:\n{elements_text}\n"
            f"{history_text}\n\n"
            f"Step {step_idx + 1}: Analyze the screenshot and UI elements. "
            f"What is the NEXT single action to perform?"
        )

        last_error = None

        for attempt in range(max_retries):
            try:
                response = self.client.models.generate_content(
                    model=self.model,
                    contents=[
                        {
                            "role": "user",
                            "parts": [
                                {"text": system_prompt + "\n\n" + user_prompt},
                                {
                                    "inline_data": {
                                        "mime_type": "image/png",
                                        "data": base64.b64encode(image_bytes).decode(),
                                    }
                                },
                            ],
                        }
                    ],
                )

                # Extract text from response
                response_text = ""
                try:
                    response_text = response.text or ""
                except Exception:
                    if response.candidates:
                        for part in response.candidates[0].content.parts:
                            if hasattr(part, "text") and part.text:
                                response_text = part.text
                                break

                response_text = response_text.strip()
                if not response_text:
                    raise ValueError("Empty response from Gemini")

                logger.info(f"  Gemini raw ({len(response_text)} chars): {response_text[:100]}...")

                # Strip markdown fences
                if response_text.startswith("```"):
                    lines = response_text.split("\n")
                    lines = [l for l in lines if not l.strip().startswith("```")]
                    response_text = "\n".join(lines)

                # Extract JSON
                import re
                json_match = re.search(r'\{[\s\S]*\}', response_text)
                if json_match:
                    response_text = json_match.group(0)

                data = json.loads(response_text)

                # Override narration with slide script if available (for PowerPoint)
                narration = data.get("narration", "")
                if self.app_type == "powerpoint" and self.slide_scripts:
                    # Increment slide number when navigating forward
                    action_type = data.get("action", {}).get("action_type", "")
                    if action_type in ("press_key", "press_hotkey"):
                        key = data.get("action", {}).get("key", "")
                        keys = data.get("action", {}).get("keys", [])
                        # Check if it's a forward navigation key
                        if key in ("right", "space", "pagedown", "enter") or \
                           any(k in ("right", "space", "pagedown", "enter") for k in keys):
                            self.current_slide_number += 1
                        # F5 starts from slide 1
                        elif key == "f5" or "f5" in keys:
                            self.current_slide_number = 1
                    
                    # Use script if available for current slide
                    if self.current_slide_number in self.slide_scripts:
                        narration = self.slide_scripts[self.current_slide_number]
                        logger.info(f"  Using slide script for slide {self.current_slide_number}")

                return AgentStep(
                    step_index=step_idx,
                    thought=data.get("thought", ""),
                    action=data.get("action", {"action_type": "done"}),
                    narration=narration,
                    is_done=data.get("is_done", False),
                )

            except Exception as e:
                last_error = e
                error_str = str(e)

                # Retry nếu là lỗi tạm thời (503, 429, 500)
                is_retryable = any(code in error_str for code in ["503", "429", "500", "UNAVAILABLE", "overloaded"])

                if is_retryable and attempt < max_retries - 1:
                    wait_sec = 5 * (attempt + 1)  # 5s, 10s, 15s
                    logger.warning(
                        f"  Gemini lỗi tạm ({error_str[:60]}...). "
                        f"Retry {attempt + 1}/{max_retries} sau {wait_sec}s..."
                    )
                    time.sleep(wait_sec)
                    continue

                # Hết retry hoặc lỗi không thể retry -> raise để pipeline dừng ngay
                logger.error(f"  Gemini thất bại sau {attempt + 1} lần: {e}")
                raise RuntimeError(f"Gemini API thất bại: {e}")

    def _build_replay_plan(self) -> list[dict]:
        """
        Bước 1: Chuyển agent steps thành replay plan với UIA selectors.
        Replay sẽ tìm element bằng selector, không dùng tọa độ cứng.
        """
        replay_plan = []
        narr_idx = 0

        replay_plan.append({
            "action_type": "pause",
            "target_value": "Start",
            "duration_ms": 1500,
        })

        for step in self.steps:
            action = step.action
            action_type = action.get("action_type", "")

            if action_type == "done":
                break

            # Narration trước hành động
            if step.narration.strip():
                replay_plan.append({
                    "action_type": "pause",
                    "target_value": "Narration pause",
                    "description": f"[NARRATION:{narr_idx}] {step.narration}",
                    "duration_ms": 2000,
                })
                narr_idx += 1

            # Hành động
            if action_type == "click_element":
                target_val = action.get("target_value")
                if target_val:
                    replay_plan.append({
                        "action_type": "click_element",
                        "target_value": target_val,
                        "move_duration": 1.0,
                    })
                else:
                    # Dung UIA selector thay toa do cung
                    selector = action.get("selector", {})
                    fallback = action.get("fallback_coords", {})
                    replay_plan.append({
                        "action_type": "click_element",
                        "target_value": f"Click {selector.get('control_type', '')} \"{selector.get('name', '')}\"",
                        "selector": selector,
                        "fallback_coords": fallback,
                        "move_duration": 0.5,
                    })

            elif action_type == "mouse_click":
                box = action.get("box")
                if isinstance(box, list) and len(box) == 4:
                    from PIL import Image
                    try:
                        with Image.open(step.screenshot_path) as img:
                            img_w, img_h = img.size
                    except Exception:
                        img_w, img_h = 1920, 1080
                    ymin, xmin, ymax, xmax = box
                    center_x_norm = (xmin + xmax) / 2
                    center_y_norm = (ymin + ymax) / 2
                    x = int(center_x_norm * img_w / 1000)
                    y = int(center_y_norm * img_h / 1000)
                    logger.info(f"  [Bounding Box] Parsed box [y={ymin}:{ymax}, x={xmin}:{xmax}] -> Center ({x}, {y})")
                else:
                    # Fallback for old x,y format
                    x = action.get("x", 0)
                    y = action.get("y", 0)

                replay_plan.append({
                    "action_type": "mouse_click",
                    "target_value": f"Click at ({x}, {y})",
                    "x": x,
                    "y": y,
                    "is_window_relative": True,
                    "screenshot_path": step.screenshot_path,
                    "move_duration": 0.8,
                })

            elif action_type == "type_text":
                target_val = action.get("target_value")
                if target_val:
                    # FIX: Tự động chèn bước di chuột (click_element) nếu Gemini xuất type_text thẳng mặt
                    # Tránh video thiếu diễn biến chuột.
                    last_click_target = None
                    for p in reversed(replay_plan):
                        if p["action_type"] == "click_element" and p.get("target_value") == target_val:
                            last_click_target = target_val
                            break
                        if p["action_type"] not in ("pause", "type_text"):
                            break
                    
                    if last_click_target != target_val:
                        logger.info(f"  [Auto-Fix] Chèn thêm thao tác di chuột vào {target_val} trước khi gõ chữ.")
                        replay_plan.append({
                            "action_type": "click_element",
                            "target_value": target_val,
                            "move_duration": 1.0,
                        })
                        replay_plan.append({
                            "action_type": "pause",
                            "target_value": "Focus delay",
                            "duration_ms": 300,
                        })

                    replay_plan.append({
                        "action_type": "type_text",
                        "target_value": target_val,
                        "text": action.get("text", ""),
                        "char_delay": 0.05,
                    })
                else:
                    replay_plan.append({
                        "action_type": "type_text",
                        "target_value": "Type text",
                        "text": action.get("text", ""),
                        "char_delay": 0.05,
                    })
            
            elif action_type == "drag_mouse":
                target_val = action.get("target_value")
                if target_val:
                    replay_plan.append({
                        "action_type": "drag_mouse",
                        "target_value": target_val,
                        "move_duration": 1.0,
                    })
                else:
                    replay_plan.append(action)

            elif action_type == "press_key":
                replay_plan.append({
                    "action_type": "press_key",
                    "target_value": action.get("key", ""),
                    "repeat": action.get("repeat", 1),
                    "duration_ms": 300,
                })

            elif action_type == "press_hotkey":
                keys = action.get("keys", [])
                replay_plan.append({
                    "action_type": "press_hotkey",
                    "target_value": "+".join(keys) if keys else "hotkey",
                    "keys": keys,
                    "repeat": action.get("repeat", 1),
                    "duration_ms": 300,
                })

            elif action_type == "drag_mouse":
                start_selector = action.get("start_selector", {})
                end_selector = action.get("end_selector", {})
                start_fallback = action.get("start_fallback", {})
                end_fallback = action.get("end_fallback", {})

                # Check if it's excel range
                if "start_excel_range" in action and "end_excel_range" in action:
                    replay_plan.append({
                        "action_type": "drag_mouse",
                        "target_value": f"Drag {action['start_excel_range']} to {action['end_excel_range']}",
                        "start_selector": {
                            "engine": "excel_com",
                            "excel_range": action["start_excel_range"]
                        },
                        "end_selector": {
                            "engine": "excel_com",
                            "excel_range": action["end_excel_range"]
                        },
                        "move_duration": 1.0,
                    })
                else:
                    target_str = f"Drag {start_selector.get('control_type', '')} to {end_selector.get('control_type', '')}"
                    replay_plan.append({
                        "action_type": "drag_mouse",
                        "target_value": target_str,
                        "start_selector": start_selector,
                        "end_selector": end_selector,
                        "start_fallback_coords": start_fallback,
                        "end_fallback_coords": end_fallback,
                        "move_duration": 1.0,
                    })

            elif action_type == "scroll":
                replay_plan.append({
                    "action_type": "scroll",
                    "target_value": "Scroll",
                    "amount": action.get("amount", 0),
                })

            elif action_type == "wait":
                replay_plan.append({
                    "action_type": "pause",
                    "target_value": "Wait",
                    "duration_ms": action.get("duration_ms", 1000),
                })

            # Pause nhẹ sau hành động (cho UI update)
            replay_plan.append({
                "action_type": "pause",
                "target_value": "Post-action pause",
                "duration_ms": 300,
            })

        # --- DEDUPLICATE ACTIONS ---
        # Gemini thường sinh ra cùng 1 action ở bước N và bước N+1 (để mark Done: True)
        # Ta cần lọc các action thực thi trùng lặp liên tiếp để tránh click/drag/type 2 lần
        # NHƯNG: Cho phép phím điều hướng (space, arrow keys) lặp nhiều lần (cho PowerPoint, PDF, etc.)
        
        ALLOWED_REPEAT_KEYS = {
            "space", "right", "left", "down", "up", 
            "page_down", "page_up", "pagedown", "pageup",
            "enter", "return"
        }
        
        deduped_plan = []
        last_real_action = None
        for a in replay_plan:
            if a["action_type"] not in ("pause", "wait"):
                if last_real_action and last_real_action["action_type"] == a["action_type"]:
                    # Kiểm tra xem có phải phím điều hướng được phép lặp không
                    is_navigation_key = False
                    if a["action_type"] in ("press_key", "press_hotkey"):
                        target_val = a.get("target_value", "").lower()
                        keys = a.get("keys", [])
                        if target_val in ALLOWED_REPEAT_KEYS or any(k.lower() in ALLOWED_REPEAT_KEYS for k in keys):
                            is_navigation_key = True
                    
                    # Chỉ deduplicate nếu KHÔNG phải phím điều hướng
                    if not is_navigation_key and \
                       a.get("target_value") == last_real_action.get("target_value") and \
                       a.get("text") == last_real_action.get("text"):
                        logger.info(f"  [Auto-Fix] Bỏ qua hành động {a['action_type']} trùng lặp: {a.get('target_value')}")
                        # Xoá luôn pause dư thừa được tạo ra ngay trước hành động trùng này (Narration pause)
                        if deduped_plan and deduped_plan[-1]["action_type"] == "pause":
                            # Chỉ xóa narration pause của step trùng
                            if "Narration pause" in deduped_plan[-1].get("target_value", ""):
                                deduped_plan.pop()
                                
                        continue
                last_real_action = a
            deduped_plan.append(a)
            
        replay_plan = deduped_plan

        # Closing narration (chỉ thêm nếu KHÁC narration cuối)
        closing_step = next(
            (s for s in reversed(self.steps) if s.is_done and s.narration.strip()),
            None
        )
        if closing_step:
            closing_text = closing_step.narration.strip()
            # Lấy tất cả description đã append vào replay_plan
            added_narrations = [
                p.get("description", "") 
                for p in replay_plan 
                if p.get("action_type") == "pause" and p.get("description", "").startswith("[NARRATION:")
            ]
            import re
            added_texts = [re.sub(r'\[NARRATION:\d+\]\s*', '', d).strip() for d in added_narrations]
            
            if closing_text not in added_texts:
                replay_plan.append({
                    "action_type": "pause",
                    "target_value": "Closing",
                    "description": f"[NARRATION:{narr_idx}] {closing_text}",
                    "duration_ms": 3000,
                })
            else:
                logger.info(f"  Closing narration trùng lặp, bỏ qua")

        replay_plan.append({
            "action_type": "pause",
            "target_value": "End",
            "duration_ms": 2000,
        })

        return replay_plan


# ---------------------------------------------------------------------------
# Replay module (Fix #3)
# ---------------------------------------------------------------------------
def replay_plan_with_recording(
    plan_path: str,
    target_pid: int,
    output_dir: str = "workspace",
    video_name: str = "replay_video",
    framerate: int = 30,
) -> dict:
    """
    Fix #3: Doc plan.json va dien lai muot ma + quay FFmpeg.

    Day la buoc 2 cua quy trinh:
    1. plan-only: Agent do duong, sinh plan.json
    2. record-replay: Doc plan.json, quay video muot.
    """
    from core.sync_recorder import record_with_script

    with open(plan_path, "r", encoding="utf-8") as f:
        plan = json.load(f)

    logger.info(f"{'='*60}")
    logger.info(f"  Record-Replay: {video_name}")
    logger.info(f"  Plan: {plan_path} ({len(plan)} actions)")
    logger.info(f"  PID: {target_pid}")
    logger.info(f"{'='*60}")

    result = record_with_script(
        plan=plan,
        target_pid=target_pid,
        output_dir=output_dir,
        video_name=video_name,
        dry_run=False,  # Quay that
        timeout_seconds=None,  # Auto-calculate from plan duration
        framerate=framerate,
    )

    return result
