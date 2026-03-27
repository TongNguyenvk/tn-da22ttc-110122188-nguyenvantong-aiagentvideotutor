from typing import Tuple, List, Optional
import abc

class BaseAdapter(abc.ABC):
    """
    Interface chuẩn cho tất cả các Adapter trong Universal Engine.
    """
    def __init__(self):
        self._target_pid = None

    def set_target_pid(self, pid: int):
        self._target_pid = pid

    @abc.abstractmethod
    def connect(self) -> bool:
        """Thực hiện kết nối tới phần mềm hoặc engine (COM/UIA)."""
        pass

    @abc.abstractmethod
    def get_coordinates(self, target_value: str) -> Optional[Tuple[int, int]]:
        """Lấy tọa độ điểm trung tâm (X, Y) để click."""
        pass

    @abc.abstractmethod
    def focus_element(self, target_value: str) -> bool:
        """
        [Mới] Đặt tiêu điểm (focus) hoặc chọn nháp (select) phần tử mục tiêu một cách ngầm.
        Mục đích: Giúp Agent thấy sự thay đổi visual (VD: viền xanh ở cell Excel) 
        mà không cần cướp chuột trong pha Planning.
        """
        pass

    @abc.abstractmethod
    def get_range_coordinates(self, target_value: str) -> Optional[List[Tuple[int, int]]]:
        """Lấy dãy tọa độ [(x1,y1), (x2,y2)] để drag_mouse."""
        pass

    @abc.abstractmethod
    def inject_data(self, target_value: str, data: str) -> bool:
        """Bơm dữ liệu trực tiếp ngầm (nếu hỗ trợ)."""
        pass
