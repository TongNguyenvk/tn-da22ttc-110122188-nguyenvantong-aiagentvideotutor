import logging
import psutil
from typing import Tuple, List, Optional

logger = logging.getLogger(__name__)

# Singleton cache cho adapter instances (QUAN TRONG: khong tao moi moi lan)
_excel_adapter_instance = None
_word_adapter_instance = None
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

class UniversalEngine:
    """
    Smart Router: Đóng vai trò phễu xử lý chung cho mọi ứng dụng.
    - Luồng VIP: Excel, Word COM.
    - Luồng Standard: UIA TextPattern.
    - Fallback: Computer Vision (CV).
    """

    def _determine_context(self, target_pid: int) -> str:
        try:
            process = psutil.Process(target_pid)
            name = process.name().lower()
            if name == "excel.exe":
                return "excel"
            elif name == "winword.exe":
                return "word"
            return "general"
        except Exception as e:
            logger.warning(f"  [UniversalEngine] Không thể lấy context từ PID {target_pid}: {e}")
            return "general"

    def get_coordinates(self, target_value: str, target_pid: int) -> Optional[Tuple[int, int]]:
        """Lấy tọa độ điểm giữa của mục tiêu (X, Y) để click chuột."""
        context = self._determine_context(target_pid)
        logger.info(f"  [UniversalEngine] Tìm '{target_value}' (Context: {context})")

        # 1. VIP Lanes (Excel / Word) - Cao nhất
        if context == "excel":
            excel_adapter = _get_excel_adapter()
            if excel_adapter:
                excel_adapter.set_target_pid(target_pid)
                if excel_adapter.connect():
                    cx_cy = excel_adapter.get_coordinates(target_value)
                    if cx_cy:
                        return cx_cy
                    
        elif context == "word":
            word_adapter = _get_word_adapter()
            if word_adapter:
                word_adapter.set_target_pid(target_pid)
                if word_adapter.connect():
                    cx_cy = word_adapter.get_coordinates(target_value)
                    if cx_cy:
                        return cx_cy

        # 2. Standard Lane (UIA TextPattern)
        uia_adapter = _get_uia_adapter()
        if uia_adapter:
            uia_adapter.set_target_pid(target_pid)
            if uia_adapter.connect():
                cx_cy = uia_adapter.get_coordinates(target_value)
                if cx_cy:
                    return cx_cy

        # 3. Fallback Lane (Computer Vision - Stub)
        vision_adapter = _get_vision_adapter()
        if vision_adapter:
            vision_adapter.set_target_pid(target_pid)
            cx_cy = vision_adapter.get_coordinates(target_value)
            if cx_cy:
                return cx_cy

        return None

    def focus_element(self, target_value: str, target_pid: int) -> bool:
        """
        [Mới] Focus/Select elements ngầm để thay đổi Visual (phục vụ Planning phase).
        Chạy qua các lớp adapter như get_coordinates.
        """
        context = self._determine_context(target_pid)
        logger.info(f"  [UniversalEngine] Focus ngầm '{target_value}' (Context: {context})")
        
        # 1. VIP Lanes
        if context == "excel":
            excel_adapter = _get_excel_adapter()
            if excel_adapter:
                excel_adapter.set_target_pid(target_pid)
                if excel_adapter.connect() and excel_adapter.focus_element(target_value):
                    return True
        elif context == "word":
            word_adapter = _get_word_adapter()
            if word_adapter:
                word_adapter.set_target_pid(target_pid)
                if word_adapter.connect() and word_adapter.focus_element(target_value):
                    return True
                    
        # 2. Standard Lane
        uia_adapter = _get_uia_adapter()
        if uia_adapter:
            uia_adapter.set_target_pid(target_pid)
            if uia_adapter.connect() and uia_adapter.focus_element(target_value):
                return True
                
        # 3. Vision Lane không xoay visual được ngầm
        return False
        
    def get_range_coordinates(self, target_value: str, target_pid: int) -> Optional[List[Tuple[int, int]]]:
        """
        Lấy dãy tọa độ start và end [(x1,y1), (x2,y2)] để drag_mouse.
        """
        context = self._determine_context(target_pid)
        
        if context == "excel":
            adapter = _get_excel_adapter()
            adapter.set_target_pid(target_pid)
            if adapter.connect():
                return adapter.get_range_coordinates(target_value)

        elif context == "word":
            adapter = _get_word_adapter()
            adapter.set_target_pid(target_pid)
            if adapter.connect():
                res = adapter.get_range_coordinates(target_value)
                if res: return res

        # 2. Standard Lane
        uia_adapter = _get_uia_adapter()
        if uia_adapter:
            uia_adapter.set_target_pid(target_pid)
            if uia_adapter.connect():
                res = uia_adapter.get_range_coordinates(target_value)
                if res: return res

        # 3. Fallback Lane
        vision_adapter = _get_vision_adapter()
        if vision_adapter:
            vision_adapter.set_target_pid(target_pid)
            res = vision_adapter.get_range_coordinates(target_value)
            if res: return res

        return None

    def inject_data(self, target_value: str, data: str, target_pid: int) -> bool:
        """
        Bơm dữ liệu trực tiếp vào ứng dụng (bỏ qua mô phỏng bàn phím nếu có thể).
        """
        context = self._determine_context(target_pid)
        
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

        # 2. Standard Lane
        uia_adapter = _get_uia_adapter()
        if uia_adapter:
            uia_adapter.set_target_pid(target_pid)
            if uia_adapter.connect():
                if uia_adapter.inject_data(target_value, data):
                    return True

        # 3. Fallback Lane
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
