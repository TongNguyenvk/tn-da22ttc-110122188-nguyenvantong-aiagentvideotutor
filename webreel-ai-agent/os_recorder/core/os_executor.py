"""
OS Executor v2 - Thuc thi kich ban voi mouse actions + execution trace.

Ho tro cac action type:
  - press_key: Bam phim (co whitelist)
  - click_element: Tim element trong UIA tree, di chuot muot den, click
  - move_to_element: Di chuot muot den element
  - mouse_click: Click tai toa do (x, y)
  - mouse_move: Di chuot muot den toa do (x, y)
  - type_text: Go van ban
  - scroll: Cuon chuot
  - speak: TTS placeholder (pause)
  - wait / pause: Cho N ms

An toan:
  1. KEY WHITELIST: Chan phim nguy hiem
  2. DRY-RUN MAC DINH: Khong thuc thi that
  3. TIMEOUT: Tu dong dung sau N giay
  4. FAILSAFE: Di chuot vao goc man hinh = dung
  5. EXECUTION TRACE: Ghi log tuong thich voi trace_composer.py
"""

import json
import time
import logging
import ctypes
from pathlib import Path
from datetime import datetime

try:
    ctypes.windll.user32.SetProcessDPIAware()
except Exception:
    pass

import pyautogui

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# An toan
pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.1  # Nho hon de chuot di muot hon


# ---------------------------------------------------------------------------
# Keyboard Layout Switch (bypass Telex IME)
# ---------------------------------------------------------------------------
def _switch_to_english_keyboard():
    """
    Lưu keyboard layout hiện tại và chuyển sang English US.
    Trả về handle layout cũ để restore sau.
    """
    try:
        user32 = ctypes.windll.user32
        # Lấy layout hiện tại của foreground window thread
        hwnd = user32.GetForegroundWindow()
        thread_id = user32.GetWindowThreadProcessId(hwnd, None)
        current_layout = user32.GetKeyboardLayout(thread_id)

        # Load và activate English US (0x0409)
        english_layout = user32.LoadKeyboardLayoutW("00000409", 1)
        if english_layout:
            user32.ActivateKeyboardLayout(english_layout, 0)
            logger.info("  Keyboard -> English US (bypass Telex)")

        return current_layout
    except Exception as e:
        logger.warning(f"  Switch keyboard failed: {e}")
        return None


def _restore_keyboard_layout(prev_layout):
    """Khôi phục keyboard layout cũ."""
    if prev_layout is None:
        return
    try:
        ctypes.windll.user32.ActivateKeyboardLayout(prev_layout, 0)
        logger.info("  Keyboard -> restored")
    except Exception as e:
        logger.warning(f"  Restore keyboard failed: {e}")

# ---------------------------------------------------------------------------
# Key Whitelist
# ---------------------------------------------------------------------------
SAFE_KEYS = {
    "space", "right", "left", "up", "down",
    "pageup", "pagedown", "home", "end",
    "f5", "escape", "enter", "tab",
    "volumeup", "volumedown", "volumemute",
    "1", "2", "3", "4", "5", "6", "7", "8", "9", "0",
    "a", "b", "c", "d", "e", "f", "g", "h", "i", "j", "k", "l", "m",
    "n", "o", "p", "q", "r", "s", "t", "u", "v", "w", "x", "y", "z",
    "shift", "ctrl", "alt",
    "<", ">", "[", "]",
}

DANGEROUS_KEYS = {
    "delete", "del", "backspace",
    "f4", "win", "winleft", "winright", "printscreen",
}


def is_key_safe(key: str) -> bool:
    """Kiem tra phim co an toan khong."""
    key_lower = key.lower().strip()
    if key_lower in DANGEROUS_KEYS:
        return False
    if key_lower in SAFE_KEYS:
        return True
    logger.warning(f"Key '{key}' not in whitelist, BLOCKED")
    return False


# ---------------------------------------------------------------------------
# Execution Trace (tuong thich voi trace_composer.py)
# ---------------------------------------------------------------------------
class ExecutionTrace:
    """Ghi nhat ky thuc thi voi timestamps, tuong thich voi trace_composer.py."""

    def __init__(self):
        self.entries = []
        self._start_time = None

    def start(self, start_time: float = None):
        """Bat dau ghi trace (reset dong ho)."""
        self._start_time = start_time if start_time is not None else time.time()

    def _elapsed_ms(self) -> float:
        """Thoi gian da troi tu khi bat dau (ms)."""
        if self._start_time is None:
            return 0
        return (time.time() - self._start_time) * 1000

    def log_step(
        self,
        step_index: int,
        action_type: str,
        description: str = "",
        start_ms: float = None,
        end_ms: float = None,
    ):
        """Ghi mot buoc vao trace."""
        entry = {
            "step_index": step_index,
            "action_type": action_type,
            "description": description,
            "start_time_ms": start_ms if start_ms is not None else self._elapsed_ms(),
            "end_time_ms": end_ms if end_ms is not None else self._elapsed_ms(),
        }
        self.entries.append(entry)

    def save(self, output_path: str) -> str:
        """Luu trace ra file JSON."""
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(self.entries, f, indent=2, ensure_ascii=False)
        logger.info(f"Trace saved: {output_path} ({len(self.entries)} steps)")
        return output_path


# ---------------------------------------------------------------------------
# Focus cua so
# ---------------------------------------------------------------------------
def focus_window_by_pid(pid: int) -> bool:
    """Dua cua so len foreground theo PID."""
    try:
        from pywinauto import Application
        app = Application(backend="uia").connect(process=pid)
        main_window = app.top_window()
        main_window.set_focus()
        time.sleep(0.5)
        logger.info(f"Focused PID={pid}: {main_window.window_text()}")
        return True
    except Exception as e:
        logger.error(f"Failed to focus PID={pid}: {e}")
        return False


def focus_window_by_hwnd(hwnd: int) -> bool:
    """Dua cua so len foreground theo HWND."""
    import ctypes
    try:
        ctypes.windll.user32.SetForegroundWindow(hwnd)
        time.sleep(0.3)
        return True
    except Exception as e:
        logger.error(f"Failed to focus HWND={hwnd}: {e}")
        return False


# ---------------------------------------------------------------------------
# Thuc thi kich ban
# ---------------------------------------------------------------------------
def execute_plan(
    plan: list[dict],
    target_pid: int,
    dry_run: bool = True,
    timeout_seconds: int = 120,
    mouse_duration: float = 0.5,
    element_tree=None,
    recording_start_time: float = None,
) -> ExecutionTrace:
    """
    Thuc thi kich ban hanh dong voi mouse + keyboard + execution trace.

    Args:
        plan: List cac action. Moi action la dict voi:
            - action_type: "press_key", "click_element", "move_to_element",
                           "mouse_click", "mouse_move", "type_text",
                           "scroll", "speak", "wait", "pause"
            - target_value: gia tri tuong ung (ten element, toa do, phim, text...)
            - Cac truong phu: x, y, duration_ms, name, control_type, automation_id
        target_pid: PID cua cua so dich.
        dry_run: True = chi in ra, khong thuc thi that.
        timeout_seconds: Tu dong dung sau N giay.
        mouse_duration: Thoi gian di chuyen chuot (giay), mac dinh 0.5s.
        element_tree: UIElement tree da cache (neu None thi se lay tu PID).

    Returns:
        ExecutionTrace chua lich su thuc thi tuong thich voi trace_composer.py.
    """
    trace = ExecutionTrace()
    start_time = time.time()

    mode_str = "DRY-RUN" if dry_run else "LIVE"
    logger.info(f"{'='*60}")
    logger.info(f"  Execute plan: {len(plan)} step(s) | Mode: {mode_str}")
    logger.info(f"  PID: {target_pid} | Timeout: {timeout_seconds}s")
    logger.info(f"{'='*60}")

    # Focus cua so truoc
    if not dry_run:
        focus_window_by_pid(target_pid)

    # Lay element tree neu can
    if element_tree is None and not dry_run:
        try:
            from core.ui_inspector import get_element_tree
            element_tree = get_element_tree(target_pid, max_depth=4)
            logger.info(f"Loaded element tree for PID={target_pid}")
        except Exception as e:
            logger.warning(f"Could not get element tree: {e}")

    # Bat dau trace dong bo voi record
    trace.start(recording_start_time)

    for i, action in enumerate(plan):
        # Timeout check
        if time.time() - start_time > timeout_seconds:
            logger.error(f"TIMEOUT after {timeout_seconds}s")
            trace.log_step(i, "timeout", "Execution timed out")
            break

        action_type = action.get("action_type", "")
        target_value = action.get("target_value", "")
        duration_ms = action.get("duration_ms", action.get("estimated_duration_ms", 1000))
        description = action.get("description", "")

        step_start_ms = trace._elapsed_ms()
        step_desc = description or f"{action_type}: {target_value}"

        logger.info(f"  [{i}] {action_type} -> {target_value[:60]} ({duration_ms}ms)")

        # --- PRESS KEY ---
        if action_type == "press_key":
            if not is_key_safe(target_value):
                trace.log_step(i, action_type, f"BLOCKED: {target_value}", step_start_ms)
                continue
            if not dry_run:
                pyautogui.press(target_value)
                time.sleep(0.2)
            trace.log_step(i, action_type, step_desc, step_start_ms)

        # --- PRESS HOTKEY ---
        elif action_type == "press_hotkey":
            keys = action.get("keys", [])
            repeat = action.get("repeat", 1)
            safe = all(is_key_safe(k) for k in keys) if keys else False
            if not safe or not keys:
                trace.log_step(i, action_type, f"BLOCKED or INVALID: {keys}", step_start_ms)
                continue
            if not dry_run:
                from pywinauto import keyboard as py_kb
                modifier_map = {'shift': '+', 'ctrl': '^', 'alt': '%'}
                mods_str = "".join(modifier_map.get(m.lower(), "") for m in keys[:-1])
                main_key = keys[-1].upper()
                if len(main_key) > 1 or main_key in ["SPACE", "ENTER"]:
                    send_str = f"{mods_str}{{{main_key} {repeat}}}"
                else:
                    send_str = f"{mods_str}{main_key}" * repeat
                py_kb.send_keys(send_str, pause=0.05)
                time.sleep(0.2)
            trace.log_step(i, action_type, f"{step_desc} (x{repeat})", step_start_ms)

        # --- DRAG MOUSE (Bôi đen) ---
        elif action_type == "drag_mouse":
            word_target = action.get("target_text")
            if action.get("engine") == "word_com" and word_target:
                from core.word_engine import WordEngine
                engine = WordEngine()
                engine.set_target_pid(target_pid)
                if engine.connect():
                    coords = engine.get_text_range_coords(word_target)
                    if coords and len(coords) == 2:
                        sx, sy = coords[0]
                        ex, ey = coords[1]
                        if not dry_run:
                            pyautogui.moveTo(sx, sy, duration=mouse_duration, tween=pyautogui.easeInOutQuad)
                            time.sleep(0.1)
                            pyautogui.mouseDown(button='left')
                            time.sleep(0.05)
                            pyautogui.dragTo(ex, ey, duration=max(0.3, mouse_duration), tween=pyautogui.easeInOutQuad)
                            time.sleep(0.1)
                            pyautogui.mouseUp(button='left')
                            time.sleep(0.2)
                        trace.log_step(i, action_type, f"{step_desc} | Kéo chọn chữ '{word_target}' @({sx},{sy}) -> @({ex},{ey})", step_start_ms)
                continue
                
            def get_coords(sel, fallback_c):
                eng = sel.get("engine")
                if eng == "excel_com":
                    from core.excel_engine import get_excel_engine
                    engine = get_excel_engine()
                    engine.set_target_pid(target_pid)
                    return engine.get_cell_coordinates(sel.get("excel_range"))
                
                cx, cy = None, None
                aid = sel.get("automation_id")
                ctrl = sel.get("control_type")
                name = sel.get("name")
                if (aid or ctrl) and not dry_run:
                    from pywinauto import Application
                    try:
                        _app = Application(backend="uia").connect(process=target_pid)
                        win = _app.top_window()
                        if aid:
                            criteria = {"auto_id": aid}
                            if ctrl: criteria["control_type"] = ctrl
                            wrapper = win.child_window(**criteria)
                            if wrapper.exists():
                                rect = wrapper.rectangle()
                                return (rect.left + rect.right) // 2, (rect.top + rect.bottom) // 2
                        if name and ctrl:
                            wrapper = win.child_window(title=name, control_type=ctrl)
                            if wrapper.exists():
                                rect = wrapper.rectangle()
                                return (rect.left + rect.right) // 2, (rect.top + rect.bottom) // 2
                    except Exception: pass
                
                if element_tree:
                    from core.ui_inspector import find_element
                    target_elem = find_element(element_tree, name=name or None, control_type=ctrl, automation_id=aid)
                    if target_elem:
                        cx, cy = target_elem.center
                
                if cx is None and fallback_c and fallback_c.get("x", 0) > 0:
                    cx, cy = fallback_c["x"], fallback_c["y"]
                return cx, cy

            start_sel = action.get("start_selector", {})
            end_sel = action.get("end_selector", {})
            start_fall = action.get("start_fallback_coords", {})
            end_fall = action.get("end_fallback_coords", {})
            
            sx, sy = get_coords(start_sel, start_fall)
            ex, ey = get_coords(end_sel, end_fall)
            
            if sx is not None and ex is not None:
                if not dry_run:
                    pyautogui.moveTo(sx, sy, duration=mouse_duration, tween=pyautogui.easeInOutQuad)
                    time.sleep(0.1)
                    pyautogui.mouseDown(button='left')
                    time.sleep(0.05)
                    pyautogui.moveTo(ex, ey, duration=mouse_duration, tween=pyautogui.easeInOutQuad)
                    time.sleep(0.1)
                    pyautogui.mouseUp(button='left')
                    time.sleep(0.2)
                trace.log_step(i, action_type, f"{step_desc} | @({sx},{sy}) -> @({ex},{ey})", step_start_ms)
            else:
                logger.warning("    -> Drag failed: could not resolve start or end coordinates")
                trace.log_step(i, action_type, "FAILED DRAG", step_start_ms)

        # --- CLICK ELEMENT (UIA selector hoặc tìm trong tree) ---
        elif action_type == "click_element":
            # Bước 1: Ưu tiên tìm bằng UIA selector (từ plan.json mới)
            selector = action.get("selector", {})
            fallback = action.get("fallback_coords", {})
            engine_type = selector.get("engine")
            elem_name = selector.get("name") or action.get("name", target_value)
            elem_ctrl = selector.get("control_type") or action.get("control_type")
            elem_aid = selector.get("automation_id") or action.get("automation_id")

            # Xử lý đặc biệt cho Excel (Bypass UIA, dùng trực tiếp COM)
            if engine_type == "excel_com":
                cell_address = selector.get("excel_range") or target_value
                logger.info(f"    -> Dùng COM Engine tìm tọa độ ô: {cell_address}")
                from core.excel_engine import get_excel_engine
                engine = get_excel_engine()
                engine.set_target_pid(target_pid)  # Set PID để tính window offset
                cx, cy = engine.get_cell_coordinates(cell_address)
                
                if cx is not None and cy is not None:
                    if not dry_run:
                        pyautogui.moveTo(cx, cy, duration=mouse_duration, tween=pyautogui.easeInOutQuad)
                        time.sleep(0.1)
                        pyautogui.click(cx, cy)
                        time.sleep(0.3)
                    trace.log_step(i, action_type, f"{step_desc} | COM Excel \"{cell_address}\" @({cx},{cy})", step_start_ms)
                    continue
                else:
                    logger.warning(f"    -> COM lấy tọa độ thất bại cho ô {cell_address}, fallback qua các cách thông thường...")

            # Xử lý đặc biệt cho Word (Bypass UIA, dùng trực tiếp COM)
            elif engine_type == "word_com":
                target_text = selector.get("target_text") or target_value
                logger.info(f"    -> Dùng COM Engine tìm tọa độ chữ: '{target_text}'")
                from core.word_engine import WordEngine
                engine = WordEngine()
                engine.set_target_pid(target_pid)
                if engine.connect():
                    cx, cy = engine.get_text_center(target_text)
                    if cx is not None and cy is not None:
                        if not dry_run:
                            pyautogui.moveTo(cx, cy, duration=mouse_duration, tween=pyautogui.easeInOutQuad)
                            time.sleep(0.1)
                            pyautogui.doubleClick(cx, cy)  # Double click works well for a single word
                            time.sleep(0.3)
                        trace.log_step(i, action_type, f"{step_desc} | COM Word '{target_text}' @({cx},{cy})", step_start_ms)
                        continue
                    else:
                        logger.warning(f"    -> COM lấy tọa độ thất bại cho chữ '{target_text}', fallback qua các cách thông thường...")

            target_elem = None

            # Cách 1: Tìm bằng pywinauto UIA (chính xác nhất)
            if (elem_aid or elem_ctrl) and not dry_run:
                try:
                    from pywinauto import Application
                    _app = Application(backend="uia").connect(process=target_pid)
                    win = _app.top_window()

                    if elem_aid:
                        criteria = {"auto_id": elem_aid}
                        if elem_ctrl:
                            criteria["control_type"] = elem_ctrl
                        wrapper = win.child_window(**criteria)
                        if wrapper.exists():
                            rect = wrapper.rectangle()
                            cx = (rect.left + rect.right) // 2
                            cy = (rect.top + rect.bottom) // 2
                            logger.info(f"    -> UIA found: {elem_ctrl} \"{elem_name}\" #{elem_aid} @({cx},{cy})")
                            pyautogui.moveTo(cx, cy, duration=mouse_duration)
                            time.sleep(0.1)
                            pyautogui.click(cx, cy)
                            time.sleep(0.3)
                            trace.log_step(i, action_type,
                                f"{step_desc} | UIA {elem_ctrl} \"{elem_name}\" @({cx},{cy})",
                                step_start_ms)
                            continue
                    if elem_name and elem_ctrl:
                        wrapper = win.child_window(title=elem_name, control_type=elem_ctrl)
                        if wrapper.exists():
                            rect = wrapper.rectangle()
                            cx = (rect.left + rect.right) // 2
                            cy = (rect.top + rect.bottom) // 2
                            logger.info(f"    -> UIA found: {elem_ctrl} \"{elem_name}\" @({cx},{cy})")
                            pyautogui.moveTo(cx, cy, duration=mouse_duration)
                            time.sleep(0.1)
                            pyautogui.click(cx, cy)
                            time.sleep(0.3)
                            trace.log_step(i, action_type,
                                f"{step_desc} | UIA {elem_ctrl} \"{elem_name}\" @({cx},{cy})",
                                step_start_ms)
                            continue
                except Exception as e:
                    logger.warning(f"    -> UIA search failed: {e}, trying fallback...")

            # Cách 2: Tìm trong element_tree (cache)
            if element_tree:
                from core.ui_inspector import find_element
                target_elem = find_element(
                    element_tree,
                    name=elem_name or None,
                    control_type=elem_ctrl,
                    automation_id=elem_aid,
                )

            if target_elem:
                cx, cy = target_elem.center
                if not dry_run:
                    pyautogui.moveTo(cx, cy, duration=mouse_duration)
                    time.sleep(0.1)
                    pyautogui.click(cx, cy)
                    time.sleep(0.3)
                trace.log_step(i, action_type,
                    f"{step_desc} | {target_elem.control_type} \"{target_elem.name}\" @({cx},{cy})",
                    step_start_ms)
                logger.info(f"    -> Found: {target_elem.control_type} \"{target_elem.name}\" @({cx},{cy})")

            # Cách 3: Fallback - dùng tọa độ backup
            elif fallback and fallback.get("x", 0) > 0:
                fx, fy = fallback["x"], fallback["y"]
                logger.warning(f"    -> Element not found by selector, using fallback @({fx},{fy})")
                if not dry_run:
                    pyautogui.moveTo(fx, fy, duration=mouse_duration)
                    time.sleep(0.1)
                    pyautogui.click(fx, fy)
                    time.sleep(0.3)
                trace.log_step(i, action_type,
                    f"{step_desc} | FALLBACK @({fx},{fy})",
                    step_start_ms)

            else:
                trace.log_step(i, action_type, f"NOT FOUND: {elem_name}", step_start_ms)
                logger.warning(f"    -> Element not found: {elem_name}")

        # --- MOVE TO ELEMENT ---
        elif action_type == "move_to_element":
            elem_name = action.get("name", target_value)
            elem_ctrl = action.get("control_type")

            target_elem = None
            if element_tree:
                from core.ui_inspector import find_element
                target_elem = find_element(element_tree, name=elem_name or None, control_type=elem_ctrl)

            if target_elem:
                cx, cy = target_elem.center
                if not dry_run:
                    pyautogui.moveTo(cx, cy, duration=mouse_duration)
                trace.log_step(i, "moveTo", f"moveTo \"{target_elem.name}\" @({cx},{cy})", step_start_ms)
            else:
                trace.log_step(i, "moveTo", f"NOT FOUND: {elem_name}", step_start_ms)

        # --- MOUSE CLICK (toa do cu the) ---
        elif action_type == "mouse_click":
            x = action.get("x", 0)
            y = action.get("y", 0)
            if not dry_run:
                pyautogui.moveTo(x, y, duration=mouse_duration)
                time.sleep(0.1)
                pyautogui.click(x, y)
                time.sleep(0.3)
            trace.log_step(i, "click", f"click @({x},{y})", step_start_ms)

        # --- MOUSE MOVE (toa do cu the) ---
        elif action_type == "mouse_move":
            x = action.get("x", 0)
            y = action.get("y", 0)
            dur = action.get("move_duration", mouse_duration)
            if not dry_run:
                pyautogui.moveTo(x, y, duration=dur)
            trace.log_step(i, "moveTo", f"moveTo @({x},{y})", step_start_ms)

        # --- TYPE TEXT ---
        elif action_type == "type_text":
            text = action.get("text", target_value)
            char_delay = action.get("char_delay", 0.05)
            selector = action.get("selector", {})
            engine_type = selector.get("engine")
            
            # Xử lý bơm text qua COM cho Excel
            if engine_type == "excel_com" and not dry_run:
                cell_address = selector.get("excel_range")
                if cell_address:
                    logger.info(f"  -> Dùng COM Engine bơm text vào ô: {cell_address}")
                    from core.excel_engine import get_excel_engine
                    engine = get_excel_engine()
                    success = engine.inject_text(cell_address, text)
                    if success:
                        trace.log_step(i, "type", f"type (COM) \"{text[:40]}\"", step_start_ms)
                        continue

            if not dry_run:
                logger.info(f"  -> PyWinAuto Type: {text[:40]}...")
                try:
                    from pywinauto import Application
                    _app = Application(backend="uia").connect(process=target_pid)
                    win = _app.top_window()
                    # type_keys hỗ trợ Unicode, có hiệu ứng gõ từng phím và tự động bypass Telex
                    win.type_keys(text, with_spaces=True, pause=char_delay)
                    time.sleep(0.5)
                except Exception as e:
                    logger.warning(f"  -> pywinauto type_keys failed: {e}")
                    import pyperclip
                    pyperclip.copy(text)
                    pyautogui.hotkey('ctrl', 'v')
            trace.log_step(i, "type", f"type \"{text[:40]}\"", step_start_ms)

        # --- SCROLL ---
        elif action_type == "scroll":
            amount = action.get("amount", action.get("y", 3))
            if not dry_run:
                pyautogui.scroll(amount)
                time.sleep(0.5)
            trace.log_step(i, "scroll", f"scroll {amount}", step_start_ms)

        # --- SPEAK (TTS placeholder, ghi narration marker vao trace) ---
        elif action_type == "speak":
            narration_idx = action.get("narration_index", i)
            trace.log_step(i, "pause",
                f"[NARRATION:{narration_idx}] {target_value}",
                step_start_ms)
            if not dry_run:
                time.sleep(duration_ms / 1000.0)

        # --- WAIT / PAUSE ---
        elif action_type in ("wait", "pause"):
            if not dry_run:
                time.sleep(duration_ms / 1000.0)
            trace.log_step(i, "pause", step_desc, step_start_ms)

        else:
            logger.warning(f"    Unknown action type: {action_type}")
            trace.log_step(i, action_type, f"UNKNOWN: {step_desc}", step_start_ms)

        # Cap nhat end_time cho step cuoi
        if trace.entries:
            trace.entries[-1]["end_time_ms"] = trace._elapsed_ms()

    logger.info(f"Execution completed: {len(trace.entries)} traced steps")
    return trace
