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

class WordEngine:
    """
    Engine giao tiếp với Word qua COM để lấy tọa độ vật lý (Pixel)
    của văn bản, giúp Agent nhắm trúng ký tự thay vì ước lượng bằng phím tắt.
    """
    def __init__(self):
        self._word = None
        self.connected = False
        self._thread_id = None
        self._target_pid = None

    def set_target_pid(self, pid: int):
        self._target_pid = pid
    
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

    def get_text_range_coords(self, target_text: str):
        """
        Tìm chuỗi 'target_text' trong Word và trả về tọa độ kéo thả (Start & End)
        dưới dạng list [(x1, y1), (x2, y2)] để drag_mouse hoặc doubleClick.
        """
        if not self.check_connection():
            return None

        try:
            doc = self._word.ActiveDocument
            win = self._word.ActiveWindow
            
            range_obj = doc.Content
            res = range_obj.Find.Execute(FindText=target_text)
            
            if res or range_obj.Find.Found:
                # Word COM GetPoint:
                # Trả về tuple (Left, Top, Width, Height) theo Tọa độ Vật lý
                left, top, width, height = win.GetPoint(0, 0, 0, 0, range_obj)
                
                # Check nếu cửa sổ bị minimize (tọa độ âm)
                if left < -10000 or top < -10000:
                    logger.warning(f"  [WordEngine] Word đang bị Minimize, tọa độ viễn tưởng: {left}, {top}")
                    return None

                scale = get_dpi_scale_factor()
                
                # Để kéo thả chữ chính xác, ta click từ góc trái giữa của khung bao và kéo sang phải
                start_x = int(left) + 5  # xích vào 5 pixel để chắc chắn trúng chữ đầu
                start_y = int(top + height/2)
                
                end_x = int(left + width) - 5 # xích lùi 5 pixel trúng chữ cuối
                end_y = int(top + height/2)
                
                logger.info(f"  [WordEngine] Bắt thành công '{target_text}' tại X1={start_x}, X2={end_x}")
                return [(start_x, start_y), (end_x, end_y)]
            else:
                logger.warning(f"  [WordEngine] Không tìm thấy chuỗi '{target_text}' trong văn bản.")
                return None
        except Exception as e:
            logger.warning(f"  [WordEngine] Lỗi lấy tọa độ Word: {e}")
            return None

    def get_text_center(self, target_text: str):
        """
        Dùng khi click_element đơn giản.
        """
        coords = self.get_text_range_coords(target_text)
        if coords and len(coords) == 2:
            return (int((coords[0][0] + coords[1][0])/2), coords[0][1])
        return None
