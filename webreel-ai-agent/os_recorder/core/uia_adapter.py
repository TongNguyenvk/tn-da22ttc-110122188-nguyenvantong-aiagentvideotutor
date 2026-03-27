import logging
import time
import uiautomation as auto
from core.base_adapter import BaseAdapter

logger = logging.getLogger(__name__)

class UIAAdapter(BaseAdapter):
    """
    Standard Lane (UIA Adapter) giao tiếp với các ứng dụng desktop thông thường
    thông qua Windows UIAutomation (đặc biệt là TextPattern).
    """
    def __init__(self):
        super().__init__()
        self._window = None

    def connect(self) -> bool:
        """
        Kết nối tới cửa sổ của ứng dụng dựa trên PID.
        Nếu PID = None, coi như tìm kiếm toàn cầu.
        """
        if self._target_pid is None:
            self._window = auto.GetRootControl()
            return True
            
        try:
            self._window = auto.WindowControl(searchDepth=2, ProcessId=self._target_pid)
            if self._window.Exists(0, 0):
                return True
            return False
        except Exception as e:
            logger.warning(f"  [UIAAdapter] Lỗi kết nối UIA tới PID {self._target_pid}: {e}")
            return False

    def focus_element(self, target_value: str) -> bool:
        """
        Dùng UIA để SetFocus ngầm, có thể tạo ra viền focus hoặc đổi màu
        để Agent AI nhận thấy sự thay đổi visual.
        """
        if not self._window and not self.connect():
            return False

        try:
            elem = self._window.Control(Name=target_value)
            if elem.Exists(0.5, 0.5):
                elem.SetFocus()
                logger.info(f"  [UIAAdapter] Đã SetFocus ngầm '{target_value}' (Visual Update)")
                import time
                time.sleep(0.3)
                return True
            return False
        except Exception as e:
            logger.warning(f"  [UIAAdapter] Lỗi SetFocus ngầm '{target_value}': {e}")
            return False

    def get_coordinates(self, target_value: str):
        """
        Dùng UIA để tìm TextControl hoặc ListItem chứa `target_value` và trả về tọa độ trung tâm.
        """
        if not self._window and not self.connect():
            return None

        try:
            # 1. Tìm chính xác theo Name (văn bản)
            elem = self._window.Control(Name=target_value)
            if elem.Exists(0.5, 0.5):
                rect = elem.BoundingRectangle
                x = (rect.left + rect.right) // 2
                y = (rect.top + rect.bottom) // 2
                logger.info(f"  [UIAAdapter] Tìm thấy '{target_value}' (Chính xác) tại tọa độ ({x}, {y})")
                return (x, y)
            
            # 2. Thử tìm gần đúng (Search) trong các TextControl
            # UIAutomation Python không hỗ trợ Regex Name trực tiếp trong GetChildren nếu không dùng hàm filter.
            # Duyệt qua các TextControl để đối chiếu chuỗi.
            for control, depth in auto.WalkControl(self._window, maxDepth=5):
                if target_value in control.Name:
                    rect = control.BoundingRectangle
                    x = (rect.left + rect.right) // 2
                    y = (rect.top + rect.bottom) // 2
                    logger.info(f"  [UIAAdapter] Tìm thấy '{target_value}' (Gần đúng) trong '{control.Name}' tại ({x}, {y})")
                    return (x, y)

            logger.warning(f"  [UIAAdapter] Không tìm thấy phần tử nào chứa '{target_value}'.")
            return None
        except Exception as e:
            logger.warning(f"  [UIAAdapter] Lỗi tìm tọa độ UIA: {e}")
            return None

    def get_range_coordinates(self, target_value: str):
        """
        Trả về tọa độ kéo thả [(x1,y1), (x2,y2)] dựa vào TextPattern nếu hỗ trợ.
        """
        # Hiện tại trả về click chuột ở giữa là điểm Start, và mớm điểm End lệch 20 pixel để giả drag.
        # Lý tưởng là dùng DocumentControl và TextPattern.GetBoundingRectangles().
        coords = self.get_coordinates(target_value)
        if coords:
            # Fake Drag
            return [coords, (coords[0] + 50, coords[1])]
        return None

    def inject_data(self, target_value: str, data: str) -> bool:
        """
        Bơm dữ liệu ngầm bằng ValuePattern.
        """
        if not self._window and not self.connect():
            return False

        try:
            elem = self._window.Control(Name=target_value)
            # Thử set ValuePattern
            if elem.Exists(0.5, 0.5):
                import uiautomation.uiautomation as uia
                # UIA Python wrapper có hàm GetValuePattern
                if elem.NativeWindowHandle:
                    # Rất khó để setValue nếu control ko hỗ trợ ValuePattern. Dùng TypeKeys tạm.
                    elem.SetFocus()
                    time.sleep(0.1)
                    auto.SendKeys(data)
                    return True
            return False
        except Exception as e:
            logger.warning(f"  [UIAAdapter] Không thể inject data qua UIA: {e}")
            return False
