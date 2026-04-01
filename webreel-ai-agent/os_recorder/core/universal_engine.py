import logging
import psutil
from typing import Tuple, List, Optional

logger = logging.getLogger(__name__)

# Singleton cache cho adapter instances (QUAN TRONG: khong tao moi moi lan)
_excel_adapter_instance = None
_word_adapter_instance = None
_ppt_adapter_instance = None
_generic_adapter_instance = None
_uia_adapter_instance = None
_vision_adapter_instance = None

def _get_excel_adapter():
    global _excel_adapter_instance
    if _excel_adapter_instance is None:
        from core.excel_adapter import ExcelAdapter
        _excel_adapter_instance = ExcelAdapter()
    return _excel_adapter_instance

def _get_word_adapter():
    global _word_adapter_instance
    if _word_adapter_instance is None:
        from core.word_adapter import WordAdapter
        _word_adapter_instance = WordAdapter()
    return _word_adapter_instance

def _get_ppt_adapter():
    global _ppt_adapter_instance
    if _ppt_adapter_instance is None:
        from core.powerpoint_adapter import PowerPointAdapter
        _ppt_adapter_instance = PowerPointAdapter()
    return _ppt_adapter_instance

def _get_generic_adapter():
    global _generic_adapter_instance
    if _generic_adapter_instance is None:
        from core.generic_adapter import GenericAdapter
        _generic_adapter_instance = GenericAdapter()
    return _generic_adapter_instance

def _get_uia_adapter():
    global _uia_adapter_instance
    if _uia_adapter_instance is None:
        from core.uia_adapter import UIAAdapter
        _uia_adapter_instance = UIAAdapter()
    return _uia_adapter_instance

def _get_vision_adapter():
    global _vision_adapter_instance
    if _vision_adapter_instance is None:
        from core.vision_adapter import VisionAdapter
        _vision_adapter_instance = VisionAdapter()
    return _vision_adapter_instance

# Mapping process name -> context
_PROCESS_CONTEXT_MAP = {
    # VIP Lanes (COM Automation)
    "excel.exe": "excel",
    "winword.exe": "word",
    "powerpnt.exe": "powerpoint",
    # Generic Lane (UIA nhe, khong can COM)
    "chrome.exe": "browser",
    "msedge.exe": "browser",
    "firefox.exe": "browser",
    "brave.exe": "browser",
    "opera.exe": "browser",
    "vivaldi.exe": "browser",
    "notepad.exe": "generic",
    "notepad++.exe": "generic",
    "code.exe": "generic",
    "windowsterminal.exe": "generic",
    "cmd.exe": "generic",
    "powershell.exe": "generic",
    "explorer.exe": "generic",
    "mspaint.exe": "generic",
    "calc.exe": "generic",
    "calculatorapp.exe": "generic",
}


class UniversalEngine:
    """
    Smart Router: pheu xu ly chung cho moi ung dung.
    - Luong VIP: Excel, Word, PowerPoint (COM Automation).
    - Luong Generic: Browser, Notepad, v.v. (pywinauto UIA nhe).
    - Luong Standard: UIA TextPattern (fallback UIA day du).
    - Fallback: Computer Vision (CV).
    """

    def _determine_context(self, target_pid: int) -> str:
        try:
            process = psutil.Process(target_pid)
            name = process.name().lower()
            ctx = _PROCESS_CONTEXT_MAP.get(name)
            if ctx:
                return ctx
            # Khong nam trong map -> generic (thay vi general)
            return "generic"
        except Exception as e:
            logger.warning(
                f"  [UniversalEngine] Khong the lay context tu PID "
                f"{target_pid}: {e}"
            )
            return "generic"

    def get_coordinates(self, target_value: str, target_pid: int) -> Optional[Tuple[int, int]]:
        """Lay toa do diem giua cua muc tieu (X, Y) de click chuot."""
        context = self._determine_context(target_pid)
        logger.info(f"  [UniversalEngine] Tim '{target_value}' (Context: {context})")

        # 1. VIP Lanes (Excel / Word / PowerPoint) - COM Automation
        if context == "excel":
            adapter = _get_excel_adapter()
            if adapter:
                adapter.set_target_pid(target_pid)
                if adapter.connect():
                    cx_cy = adapter.get_coordinates(target_value)
                    if cx_cy:
                        return cx_cy

        elif context == "word":
            adapter = _get_word_adapter()
            if adapter:
                adapter.set_target_pid(target_pid)
                if adapter.connect():
                    cx_cy = adapter.get_coordinates(target_value)
                    if cx_cy:
                        return cx_cy

        elif context == "powerpoint":
            adapter = _get_ppt_adapter()
            if adapter:
                adapter.set_target_pid(target_pid)
                if adapter.connect():
                    cx_cy = adapter.get_coordinates(target_value)
                    if cx_cy:
                        return cx_cy

        # 2. Generic Lane (Browser, Notepad, v.v.) - pywinauto UIA nhe
        if context in ("browser", "generic"):
            generic = _get_generic_adapter()
            if generic:
                generic.set_target_pid(target_pid)
                generic.set_app_hint(context)
                if generic.connect():
                    cx_cy = generic.get_coordinates(target_value)
                    if cx_cy:
                        return cx_cy

        # 3. Standard Lane (UIA TextPattern - fallback day du)
        uia_adapter = _get_uia_adapter()
        if uia_adapter:
            uia_adapter.set_target_pid(target_pid)
            if uia_adapter.connect():
                cx_cy = uia_adapter.get_coordinates(target_value)
                if cx_cy:
                    return cx_cy

        # 4. Fallback Lane (Computer Vision)
        vision_adapter = _get_vision_adapter()
        if vision_adapter:
            vision_adapter.set_target_pid(target_pid)
            cx_cy = vision_adapter.get_coordinates(target_value)
            if cx_cy:
                return cx_cy

        return None

    def focus_element(self, target_value: str, target_pid: int) -> bool:
        """
        Focus/Select elements ngam de thay doi Visual (phuc vu Planning phase).
        Chay qua cac lop adapter nhu get_coordinates.
        """
        context = self._determine_context(target_pid)
        logger.info(f"  [UniversalEngine] Focus ngam '{target_value}' (Context: {context})")

        # 1. VIP Lanes
        if context == "excel":
            adapter = _get_excel_adapter()
            if adapter:
                adapter.set_target_pid(target_pid)
                if adapter.connect() and adapter.focus_element(target_value):
                    return True
        elif context == "word":
            adapter = _get_word_adapter()
            if adapter:
                adapter.set_target_pid(target_pid)
                if adapter.connect() and adapter.focus_element(target_value):
                    return True
        elif context == "powerpoint":
            adapter = _get_ppt_adapter()
            if adapter:
                adapter.set_target_pid(target_pid)
                if adapter.connect() and adapter.focus_element(target_value):
                    return True

        # 2. Generic Lane
        if context in ("browser", "generic"):
            generic = _get_generic_adapter()
            if generic:
                generic.set_target_pid(target_pid)
                generic.set_app_hint(context)
                if generic.connect() and generic.focus_element(target_value):
                    return True

        # 3. Standard Lane
        uia_adapter = _get_uia_adapter()
        if uia_adapter:
            uia_adapter.set_target_pid(target_pid)
            if uia_adapter.connect() and uia_adapter.focus_element(target_value):
                return True

        # 4. Vision Lane khong xoay visual duoc ngam
        return False
        
    def get_range_coordinates(self, target_value: str, target_pid: int) -> Optional[List[Tuple[int, int]]]:
        """
        Lay day toa do start va end [(x1,y1), (x2,y2)] de drag_mouse.
        """
        context = self._determine_context(target_pid)

        # 1. VIP Lanes
        if context == "excel":
            adapter = _get_excel_adapter()
            adapter.set_target_pid(target_pid)
            if adapter.connect():
                return adapter.get_range_coordinates(target_value)
        elif context == "word":
            adapter = _get_word_adapter()
            adapter.set_target_pid(target_pid)
            if adapter.connect():
                return adapter.get_range_coordinates(target_value)
        elif context == "powerpoint":
            adapter = _get_ppt_adapter()
            adapter.set_target_pid(target_pid)
            if adapter.connect():
                return adapter.get_range_coordinates(target_value)

        # 2. Generic Lane
        if context in ("browser", "generic"):
            generic = _get_generic_adapter()
            if generic:
                generic.set_target_pid(target_pid)
                generic.set_app_hint(context)
                if generic.connect():
                    res = generic.get_range_coordinates(target_value)
                    if res:
                        return res

        # 3. Standard Lane
        uia_adapter = _get_uia_adapter()
        if uia_adapter:
            uia_adapter.set_target_pid(target_pid)
            if uia_adapter.connect():
                res = uia_adapter.get_range_coordinates(target_value)
                if res:
                    return res

        # 4. Fallback Lane
        vision_adapter = _get_vision_adapter()
        if vision_adapter:
            vision_adapter.set_target_pid(target_pid)
            res = vision_adapter.get_range_coordinates(target_value)
            if res:
                return res

        return None

    def inject_data(self, target_value: str, data: str, target_pid: int) -> bool:
        """
        Bom du lieu truc tiep vao ung dung (bo qua mo phong ban phim neu co the).
        """
        context = self._determine_context(target_pid)

        # 1. VIP Lanes
        if context == "excel":
            adapter = _get_excel_adapter()
            adapter.set_target_pid(target_pid)
            if adapter.connect():
                return adapter.inject_data(target_value, data)
        elif context == "word":
            adapter = _get_word_adapter()
            adapter.set_target_pid(target_pid)
            if adapter.connect():
                if adapter.inject_data(target_value, data):
                    return True

        # 2. Generic Lane (clipboard injection for browser, notepad, v.v.)
        if context in ("browser", "generic"):
            generic = _get_generic_adapter()
            if generic:
                generic.set_target_pid(target_pid)
                generic.set_app_hint(context)
                if generic.connect():
                    if generic.inject_data(target_value, data):
                        return True

        # 3. Standard Lane
        uia_adapter = _get_uia_adapter()
        if uia_adapter:
            uia_adapter.set_target_pid(target_pid)
            if uia_adapter.connect():
                if uia_adapter.inject_data(target_value, data):
                    return True

        # 4. Fallback Lane
        vision_adapter = _get_vision_adapter()
        if vision_adapter:
            vision_adapter.set_target_pid(target_pid)
            if vision_adapter.inject_data(target_value, data):
                return True

        return False

# Cung cấp singleton
_engine_instance = None
def get_universal_engine() -> UniversalEngine:
    global _engine_instance
    if _engine_instance is None:
        _engine_instance = UniversalEngine()
    return _engine_instance
