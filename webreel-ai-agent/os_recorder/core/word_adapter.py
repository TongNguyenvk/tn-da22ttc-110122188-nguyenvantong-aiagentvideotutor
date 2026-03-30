import logging
import win32com.client
import pythoncom
import threading
import ctypes
import time

logger = logging.getLogger(__name__)

def get_dpi_scale_factor():
    """
    Lấy DPI scale factor của màn hình.
    Windows scaling 100% = 1.0, 125% = 1.25, etc.
    """
    try:
        user32 = ctypes.windll.user32
        hdc = user32.GetDC(0)
        dpi = ctypes.windll.gdi32.GetDeviceCaps(hdc, 88)
        user32.ReleaseDC(0, hdc)
        scale = dpi / 96.0
        return scale
    except Exception as e:
        logger.warning(f"  [WordEngine] Không lấy được DPI scale: {e}, dùng 1.0")
        return 1.0

from core.base_adapter import BaseAdapter

class WordAdapter(BaseAdapter):
    """
    Engine giao tiếp với Word qua COM để lấy tọa độ vật lý (Pixel)
    của văn bản, giúp Agent nhắm trúng ký tự thay vì ước lượng bằng phím tắt.
    """
    def __init__(self):
        super().__init__()
        self._word = None
        self.connected = False
        self._thread_id = None
    
    def connect(self) -> bool:
        try:
            pythoncom.CoInitialize()
            self._word = win32com.client.GetActiveObject("Word.Application")
            self.connected = True
            self._thread_id = threading.get_ident()
            logger.info("  [WordEngine] Đã kết nối thành công vào Word COM.")
            return True
        except Exception as e:
            try:
                pythoncom.CoInitialize()
                self._word = win32com.client.Dispatch("Word.Application")
                self.connected = True
                self._thread_id = threading.get_ident()
                logger.info("  [WordEngine] Đã Dispatch thành công Word COM.")
                return True
            except Exception as e2:
                logger.warning(f"  [WordEngine] Không thể kết nối Word COM: {e2}")
                self.connected = False
                return False

    def check_connection(self) -> bool:
        if not self.connected or self._word is None:
            return False
        if threading.get_ident() != self._thread_id:
            try:
                pythoncom.CoInitialize()
                self._thread_id = threading.get_ident()
            except Exception:
                pass
        try:
            _ = self._word.Name
            return True
        except Exception:
            return self.connect()

    def get_range_coordinates(self, target_value: str):
        """
        Tìm chuỗi 'target_text' trong Word và trả về tọa độ kéo thả (Start & End)
        dưới dạng list [(x1, y1), (x2, y2)] để drag_mouse hoặc doubleClick.
        """
        target_text = target_value
        if not self.check_connection():
            return None

        try:
            doc = self._word.ActiveDocument
            win = self._word.ActiveWindow
            
            range_obj = doc.Content
            res = range_obj.Find.Execute(FindText=target_text)
            
            if res or range_obj.Find.Found:
                # De boi den multi-line hoac doan van chuan xac nhat, ta can tach Range ra lam hai diem: Start va End
                # Thay vi GetPoint nguyen ca mot khoi (se bi keo ngang qua giua doan van)
                
                rng_start = range_obj.Duplicate
                rng_start.Collapse(Direction=1)  # 1 = wdCollapseStart
                left1, top1, width1, height1 = win.GetPoint(0, 0, 0, 0, rng_start)
                
                rng_end = range_obj.Duplicate
                rng_end.Collapse(Direction=0)  # 0 = wdCollapseEnd
                left2, top2, width2, height2 = win.GetPoint(0, 0, 0, 0, rng_end)
                
                # Check nếu cửa sổ bị minimize (tọa độ âm)
                if left1 < -10000 or top1 < -10000:
                    logger.warning(f"  [WordEngine] Word dang bi Minimize, toa do am: {left1}, {top1}")
                    return None
                
                # Toa do xuat phat: Ngay ben trai cua ky tu the nhat
                start_x = int(left1) + 2
                start_y = int(top1 + height1 / 2)
                
                # Toa do ket thuc: Ngay ben phai cua ky tu cuoi cung (cong them 5px de bao dam bao trum het)
                end_x = int(left2 + width2) + 5
                end_y = int(top2 + height2 / 2)
                
                logger.info(f"  [WordEngine] Bat thanh cong chuoi tai ({start_x}, {start_y}) den ({end_x}, {end_y})")
                return [(start_x, start_y), (end_x, end_y)]
            else:
                logger.warning(f"  [WordEngine] Không tìm thấy chuỗi '{target_text}' trong văn bản.")
                return None
        except Exception as e:
            logger.warning(f"  [WordEngine] Lỗi lấy tọa độ Word: {e}")
            return None

    def focus_element(self, target_value: str) -> bool:
        """
        Dùng COM để Select ngầm đoạn văn bản mục tiêu, tạo hiệu ứng highlight
        để Agent AI nhận thấy sự thay đổi visual.
        """
        if not self._word and not self.connect():
            return False

        try:
            doc = self._word.ActiveDocument
            rng = doc.Content
            if rng.Find.Execute(target_value):
                rng.Select()
                logger.info(f"  [WordAdapter] Đã Select ngầm chữ '{target_value}' (Visual Update)")
                return True
            return False
        except Exception as e:
            logger.warning(f"  [WordAdapter] Lỗi khi Select ngầm chữ '{target_value}': {e}")
            return False

    def get_coordinates(self, target_value: str):
        """
        Dùng khi click_element đơn giản.
        """
        target_text = target_value
        coords = self.get_range_coordinates(target_text)
        if coords and len(coords) == 2:
            return (int((coords[0][0] + coords[1][0])/2), coords[0][1])
        return None

    def inject_data(self, target_value: str, data: str) -> bool:
        """Bơm dữ liệu ngầm cho Word nếu hỗ trợ. Hiện chỉ hỗ trợ click/drag, nên stub False."""
        return False
