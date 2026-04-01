"""
Generic Adapter - Xử lý các ứng dụng không có adapter chuyên biệt.

Dành cho: Chrome, Firefox, Edge, Notepad, ứng dụng bất kỳ.
Chiến lược:
  1. UIA nhanh (tìm theo Name, ControlType, AutomationId)
  2. pywinauto child_window traversal (sâu hơn UIA wrapper)
  3. Clipboard injection (paste thay vì gõ ký tự)
  4. SetFocus qua UIA cho visual feedback

Ưu điểm so với UIAAdapter:
  - Nhận diện thêm các pattern phổ biến (URL bar, address bar, tab, button)
  - Hỗ trợ inject data qua clipboard (nhanh, đáng tin cậy, hỗ trợ Unicode)
  - Tìm kiếm thông minh hơn: fuzzy match trên ControlType phù hợp
"""

import logging
import time
from typing import Tuple, List, Optional
from core.base_adapter import BaseAdapter

logger = logging.getLogger(__name__)


class GenericAdapter(BaseAdapter):
    """
    Adapter tổng quát cho mọi ứng dụng không có VIP lane riêng.
    Nhẹ hơn UIAAdapter (không WalkControl toàn bộ tree),
    thông minh hơn (nhận diện pattern theo loại ứng dụng).
    """

    def __init__(self):
        super().__init__()
        self._app = None
        self._window = None
        self._app_hint = None  # "browser", "editor", "other"

    def set_app_hint(self, hint: str):
        """Gợi ý loại ứng dụng để adapter chọn chiến lược phù hợp."""
        self._app_hint = hint

    def connect(self) -> bool:
        if self._target_pid is None:
            return False
        try:
            from pywinauto import Application
            self._app = Application(backend="uia").connect(
                process=self._target_pid, timeout=3
            )
            self._window = self._app.top_window()
            return self._window is not None
        except Exception as e:
            logger.warning(
                f"  [GenericAdapter] Ket noi that bai PID {self._target_pid}: {e}"
            )
            return False

    # ------------------------------------------------------------------
    # get_coordinates
    # ------------------------------------------------------------------
    def get_coordinates(self, target_value: str) -> Optional[Tuple[int, int]]:
        if not self._window:
            if not self.connect():
                return None

        # 1. Tim chinh xac theo title (Name)
        coords = self._find_by_title(target_value)
        if coords:
            return coords

        # 2. Tim theo AutomationId (vi du: "addressWrapper", "searchInput")
        coords = self._find_by_auto_id(target_value)
        if coords:
            return coords

        # 3. Tim mo rong: duyet children tim phan tu chua target_value
        coords = self._find_by_walk(target_value)
        if coords:
            return coords

        logger.info(
            f"  [GenericAdapter] Khong tim thay '{target_value}' trong UIA tree"
        )
        return None

    # ------------------------------------------------------------------
    # focus_element
    # ------------------------------------------------------------------
    def focus_element(self, target_value: str) -> bool:
        if not self._window:
            if not self.connect():
                return False
        try:
            wrapper = self._resolve_wrapper(target_value)
            if wrapper and wrapper.exists():
                wrapper.set_focus()
                time.sleep(0.2)
                logger.info(
                    f"  [GenericAdapter] SetFocus ngam '{target_value}'"
                )
                return True
        except Exception as e:
            logger.warning(
                f"  [GenericAdapter] Loi SetFocus '{target_value}': {e}"
            )
        return False

    # ------------------------------------------------------------------
    # get_range_coordinates
    # ------------------------------------------------------------------
    def get_range_coordinates(
        self, target_value: str
    ) -> Optional[List[Tuple[int, int]]]:
        coords = self.get_coordinates(target_value)
        if coords:
            return [coords, (coords[0] + 60, coords[1])]
        return None

    # ------------------------------------------------------------------
    # inject_data - Clipboard injection (nhanh, Unicode-safe)
    # ------------------------------------------------------------------
    def inject_data(self, target_value: str, data: str) -> bool:
        if not self._window:
            if not self.connect():
                return False
        try:
            # Tim element va focus
            wrapper = self._resolve_wrapper(target_value)
            if wrapper and wrapper.exists():
                wrapper.set_focus()
                time.sleep(0.15)

                # Thu ValuePattern truoc
                try:
                    vp = wrapper.iface_value
                    if vp:
                        vp.SetValue(data)
                        logger.info(
                            f"  [GenericAdapter] Inject qua ValuePattern: "
                            f"'{data[:40]}'"
                        )
                        return True
                except Exception:
                    pass

            # Fallback: Clipboard paste (hoan toan Unicode-safe)
            import pyperclip
            import pyautogui

            pyperclip.copy(data)
            time.sleep(0.1)
            pyautogui.hotkey("ctrl", "a")  # Select all trong field
            time.sleep(0.05)
            pyautogui.hotkey("ctrl", "v")  # Paste
            time.sleep(0.2)
            logger.info(
                f"  [GenericAdapter] Inject qua clipboard: '{data[:40]}'"
            )
            return True

        except Exception as e:
            logger.warning(
                f"  [GenericAdapter] Inject that bai: {e}"
            )
            return False

    # ==================================================================
    # Private helpers
    # ==================================================================
    def _rect_to_center(self, rect) -> Tuple[int, int]:
        return (rect.left + rect.right) // 2, (rect.top + rect.bottom) // 2

    def _resolve_wrapper(self, target_value: str):
        """Tim pywinauto wrapper cho target_value."""
        if not self._window:
            return None

        # 1. Tim theo title chinh xac
        try:
            w = self._window.child_window(title=target_value, found_index=0)
            if w.exists(timeout=0.5):
                return w
        except Exception:
            pass

        # 2. Tim theo title chua target_value (best_match)
        try:
            w = self._window.child_window(
                title_re=f".*{_escape_regex(target_value)}.*",
                found_index=0,
            )
            if w.exists(timeout=0.5):
                return w
        except Exception:
            pass

        # 3. Tim theo AutomationId
        try:
            w = self._window.child_window(
                auto_id=target_value, found_index=0
            )
            if w.exists(timeout=0.3):
                return w
        except Exception:
            pass

        return None

    def _find_by_title(self, target_value: str) -> Optional[Tuple[int, int]]:
        try:
            w = self._window.child_window(title=target_value, found_index=0)
            if w.exists(timeout=0.5):
                rect = w.rectangle()
                cx, cy = self._rect_to_center(rect)
                logger.info(
                    f"  [GenericAdapter] Tim thay '{target_value}' "
                    f"(Title chinh xac) tai ({cx}, {cy})"
                )
                return (cx, cy)
        except Exception:
            pass
        return None

    def _find_by_auto_id(
        self, target_value: str
    ) -> Optional[Tuple[int, int]]:
        try:
            w = self._window.child_window(
                auto_id=target_value, found_index=0
            )
            if w.exists(timeout=0.3):
                rect = w.rectangle()
                cx, cy = self._rect_to_center(rect)
                logger.info(
                    f"  [GenericAdapter] Tim thay '{target_value}' "
                    f"(AutomationId) tai ({cx}, {cy})"
                )
                return (cx, cy)
        except Exception:
            pass
        return None

    def _find_by_walk(self, target_value: str) -> Optional[Tuple[int, int]]:
        """Duyet cay UIA nong (max 3 cap) de tim phan tu chua target_value."""
        try:
            target_lower = target_value.lower()
            children = self._window.descendants(depth=3)

            # Gioi han so luong de tranh cham
            for child in children[:200]:
                try:
                    name = child.window_text() or ""
                    if target_lower in name.lower() and name.strip():
                        rect = child.rectangle()
                        if rect.width() > 0 and rect.height() > 0:
                            cx, cy = self._rect_to_center(rect)
                            logger.info(
                                f"  [GenericAdapter] Tim thay "
                                f"'{target_value}' trong '{name[:50]}' "
                                f"tai ({cx}, {cy})"
                            )
                            return (cx, cy)
                except Exception:
                    continue
        except Exception as e:
            logger.warning(
                f"  [GenericAdapter] Loi duyet UIA tree: {e}"
            )
        return None


def _escape_regex(text: str) -> str:
    """Escape cac ky tu dac biet trong regex."""
    import re
    return re.escape(text)
