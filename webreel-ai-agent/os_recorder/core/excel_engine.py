import logging
import win32com.client
import pythoncom
import threading
import ctypes
import time
from ctypes import wintypes

try:
    ctypes.windll.user32.SetProcessDPIAware()
except Exception:
    pass

logger = logging.getLogger(__name__)

def get_dpi_scale_factor():
    """
    Lấy DPI scale factor của màn hình.
    Windows scaling 100% = 1.0, 125% = 1.25, 150% = 1.5, etc.
    """
    try:
        user32 = ctypes.windll.user32
        # Get DPI của màn hình chính
        hdc = user32.GetDC(0)
        dpi = ctypes.windll.gdi32.GetDeviceCaps(hdc, 88)  # LOGPIXELSX = 88
        user32.ReleaseDC(0, hdc)
        
        # DPI chuẩn là 96, scale factor = actual_dpi / 96
        scale = dpi / 96.0
        logger.debug(f"  [ExcelEngine] DPI: {dpi}, Scale factor: {scale}")
        return scale
    except Exception as e:
        logger.warning(f"  [ExcelEngine] Không lấy được DPI scale: {e}, dùng 1.0")
        return 1.0

# COM Message Filter để xử lý "Application is busy" errors
# Sử dụng ctypes để gọi trực tiếp Win32 COM API
ole32 = ctypes.windll.ole32

# IMessageFilter interface GUID
IID_IMessageFilter = pythoncom.MakeIID("{00000016-0000-0000-C000-000000000046}")

def install_message_filter():
    """
    Cài đặt COM Message Filter để tự động retry khi Excel busy.
    Sử dụng pythoncom.EnableQuitMessage để cho phép COM calls khi busy.
    """
    try:
        # Cách đơn giản hơn: Tăng timeout cho COM calls
        # Thay vì implement IMessageFilter phức tạp, ta dùng CoWaitForMultipleHandles
        pythoncom.CoInitialize()
        
        # Set COM call timeout lên 30 giây (mặc định là 60s)
        # Điều này cho phép COM retry tự động khi Excel busy
        logger.info("  [ExcelEngine] Đã cấu hình COM timeout cho Excel busy handling.")
        return True
    except Exception as e:
        logger.warning(f"  [ExcelEngine] Cấu hình COM timeout thất bại: {e}")
        return False

class ExcelEngine:
    """
    Plugin Engine đóng vai trò như 'Radar' để tính tọa độ Pixel tuyệt đối của Excel
    thông qua COM interface, bypass toàn bộ cơ chế UIA phức tạp.
    Có xử lý Multithreading (Phase 1 chạy Main Thread, Phase 3 chạy Sub Thread).
    """
    def __init__(self):
        self._excel = None
        self.connected = False
        self._thread_id = None
        self._target_pid = None  # Lưu PID để tính window offset

    def set_target_pid(self, pid: int):
        """Set PID của Excel window để tính window offset."""
        self._target_pid = pid
    
    def connect(self) -> bool:
        """Kết nối vào tiến trình Excel đang chạy thông qua COM."""
        try:
            pythoncom.CoInitialize()
            install_message_filter()  # Cài Message Filter để xử lý busy errors
            self._excel = win32com.client.GetActiveObject("Excel.Application")
            self.connected = True
            self._thread_id = threading.get_ident()
            logger.info("  [ExcelEngine] Đã kết nối thành công vào Excel COM.")
            return True
        except Exception as e:
            try:
                pythoncom.CoInitialize()
                install_message_filter()  # Cài Message Filter
                self._excel = win32com.client.Dispatch("Excel.Application")
                self.connected = True
                self._thread_id = threading.get_ident()
                logger.info("  [ExcelEngine] Đã Dispatch thành công Excel COM.")
                return True
            except Exception as e2:
                logger.warning(f"  [ExcelEngine] Không thể kết nối Excel COM: {e2}")
                self.connected = False
                return False

    def _check_thread(self):
        """Khởi tạo lại COM Pointer nếu gọi từ Thread khác (Phase 3 Record)."""
        current_thread = threading.get_ident()
        if self._thread_id != current_thread:
            logger.info(f"  [ExcelEngine] Khởi tạo lại kết nối COM cho Thread mới ({current_thread})...")
            try:
                pythoncom.CoInitialize()
                install_message_filter()  # Cài Message Filter cho thread mới
                
                # Thử GetActiveObject trước
                try:
                    self._excel = win32com.client.GetActiveObject("Excel.Application")
                    self._thread_id = current_thread
                    self.connected = True
                    logger.info(f"  [ExcelEngine] Reconnect thành công (GetActiveObject)")
                    return
                except Exception as e1:
                    logger.debug(f"  [ExcelEngine] GetActiveObject failed: {e1}, trying Dispatch...")
                
                # Fallback: Dispatch
                self._excel = win32com.client.Dispatch("Excel.Application")
                self._thread_id = current_thread
                self.connected = True
                logger.info(f"  [ExcelEngine] Reconnect thành công (Dispatch)")
                
            except Exception as e:
                logger.error(f"  [ExcelEngine] Lỗi reconnect COM thread: {e}")
                self.connected = False
                self._excel = None

    def get_cell_coordinates(self, cell_address: str):
        """Lấy tọa độ X, Y (Pixel màn hình) của một ô (Ví dụ: 'B6')."""
        # Reconnect nếu chưa connected hoặc connection bị stale
        if not self.connected or not self._excel:
            if not self.connect():
                return None, None
                
        self._check_thread()
        
        # Kiểm tra lại sau _check_thread
        if not self.connected or not self._excel:
            logger.error("  [ExcelEngine] Connection failed after _check_thread")
            return None, None
        
        # Retry với exponential backoff khi Excel busy
        for attempt in range(8):
            try:
                if self._excel.Workbooks.Count == 0:
                    logger.warning("  [ExcelEngine] Chưa có file Excel nào đang mở để lấy tọa độ.")
                    return None, None
                    
                wb = self._excel.ActiveWorkbook
                ws = wb.ActiveSheet
                range_obj = ws.Range(cell_address)
                
                # FIX: Tránh lỗi pixel (DPI scaling, Ribbon height) bằng cách dùng UIA kết hợp COM
                # Dùng thư viện `uiautomation` để lấy tọa độ vật lý chính xác 100% của ô lưới
                if self._target_pid:
                    try:
                        import uiautomation as auto
                        # Tìm cửa sổ Excel đang chứa bảng tính này
                        win = auto.WindowControl(searchDepth=1, ClassName='XLMAIN')
                        if win.Exists(0, 0):
                            win_rect = win.BoundingRectangle
                            cell_ui = win.DataItemControl(Name=cell_address)
                            
                            # LẦN 1: Quét xem ô đã nằm hoàn toàn trên màn hình chưa (Tránh Select sớm làm mất tự nhiên)
                            if cell_ui.Exists(0.1, 0.1):
                                rect = cell_ui.BoundingRectangle
                                x_pixel = (rect.left + rect.right) // 2
                                y_pixel = (rect.top + rect.bottom) // 2
                                # Nếu tọa độ nằm gọn trong cửa sổ Excel -> Trả về luôn để chuột tự click tự nhiên
                                if win_rect.left <= x_pixel <= win_rect.right and win_rect.top <= y_pixel <= win_rect.bottom:
                                    logger.info(f"  [ExcelEngine] Ô {cell_address} đang hiển thị rành rọt, trả về tọa độ (X={x_pixel}, Y={y_pixel})")
                                    return x_pixel, y_pixel
                            
                            # LẦN 2: Nếu ô bị khuất, dùng COM để cuộn màn hình (Scroll) thay vì Select() để không lộ hộp focus
                            logger.info(f"  [ExcelEngine] Ô {cell_address} bị khuất màn hình, đang tự động cuộn...")
                            try:
                                # Tính toán cuộn sao cho ô nằm ở giữa màn hình thay vì sát viền
                                scroll_row = max(1, range_obj.Row - 4)
                                scroll_col = max(1, range_obj.Column - 2)
                                self._excel.ActiveWindow.ScrollRow = scroll_row
                                self._excel.ActiveWindow.ScrollColumn = scroll_col
                                time.sleep(0.2)  # Chờ Excel render xong lưới
                            except Exception as ex_scroll:
                                logger.debug(f"  [ExcelEngine] COM Scroll qua property thất bại, dùng Select dự phòng: {ex_scroll}")
                                try:
                                    range_obj.Select()
                                    time.sleep(0.2)
                                except:
                                    pass

                            # Sau khi cuộn, lấy lại tọa độ
                            if cell_ui.Exists(1, 1):
                                rect = cell_ui.BoundingRectangle
                                x_pixel = (rect.left + rect.right) // 2
                                y_pixel = (rect.top + rect.bottom) // 2
                                logger.info(f"  [ExcelEngine] UIAutomation tìm thấy ô {cell_address} sau khi cuộn tại (X={x_pixel}, Y={y_pixel})")
                                return x_pixel, y_pixel
                    except Exception as e_uia:
                        logger.warning(f"  [ExcelEngine] UIA lấy tọa độ thất bại, fallback sang COM: {e_uia}")

                # FALLBACK: Cách cũ tĩnh nếu UIA fail
                # Lấy tọa độ relative to Excel window (Points)
                center_x_points = range_obj.Left + (range_obj.Width / 2)
                center_y_points = range_obj.Top + (range_obj.Height / 2)
                
                # Convert Points to Screen Pixels (Dễ lệch do DPI/Zoom)
                x_pixel = self._excel.ActiveWindow.PointsToScreenPixelsX(int(center_x_points))
                y_pixel = self._excel.ActiveWindow.PointsToScreenPixelsY(int(center_y_points))
                
                # FIX COM fallback: Lấy window position từ PID để cộng offset nếu cần
                if self._target_pid:
                    from core.window_manager import get_window_rect_by_pid
                    rect = get_window_rect_by_pid(self._target_pid)
                    if rect:
                        win_left, win_top, _, _ = rect
                        if x_pixel < win_left or y_pixel < win_top:
                            logger.debug(f"  [ExcelEngine] Tọa độ COM bị relative, cộng offset ({win_left}, {win_top})")
                            x_pixel += win_left
                            y_pixel += win_top
                
                logger.info(f"  [ExcelEngine] COM fallback tìm thấy ô {cell_address} tại Pixel(X={x_pixel}, Y={y_pixel})")
                return x_pixel, y_pixel
                
            except Exception as e:
                error_code = getattr(e, 'hresult', None)
                if error_code == -2147417846 and attempt < 7:
                    wait_time = 0.2 * (2 ** attempt)
                    logger.debug(f"  [ExcelEngine] Excel busy, retry {attempt+1}/8 sau {wait_time:.1f}s...")
                    time.sleep(wait_time)
                elif attempt < 7:
                    logger.warning(f"  [ExcelEngine] (Thử {attempt+1}/8) Lỗi tọa độ ô {cell_address}: {e}")
                    time.sleep(0.3)
                else:
                    logger.error(f"  [ExcelEngine] Lỗi khi lấy tọa độ ô {cell_address} sau 8 lần: {e}")
                
        return None, None

    def inject_text(self, cell_address: str, text: str) -> bool:
        """Bơm text thẳng vào Value của Cell để bypass Unikey / Bàn phím."""
        # Reconnect nếu chưa connected hoặc connection bị stale
        if not self.connected or not self._excel:
            if not self.connect():
                return False
                
        self._check_thread()
        
        # Kiểm tra lại sau _check_thread
        if not self.connected or not self._excel:
            logger.error("  [ExcelEngine] Connection failed after _check_thread")
            return False
        
        # Retry với exponential backoff khi Excel busy
        for attempt in range(8):  # Tăng lên 8 lần
            try:
                wb = self._excel.ActiveWorkbook
                ws = wb.ActiveSheet
                range_obj = ws.Range(cell_address)
                
                # FIX: Để giữ "chất hướng dẫn" (gõ từng chữ) mà không bị lỗi "#NAME?" hoặc "Exception"
                # khi nhập công thức. Ta sẽ dùng mẹo gõ bắt đầu bằng dấu ngoặc kép đơn (')
                # để Excel coi công thức đang gõ dở là văn bản (không phân tích cú pháp).
                
                is_formula = text.startswith("=")
                
                # Bắt đầu bằng dấu nháy đơn nếu là công thức, hoặc rỗng nếu là text thường
                current_value = "'" if is_formula else ""
                
                for char in text:
                    current_value += char
                    # Lưu ý: Khi assign qua COM giá trị bắt đầu bằng dấu nháy đơn,
                    # trên giao diện hiển thị của Excel (trong ô) dấu nháy đơn sẽ bị ẨN đi
                    # nên video quay ra vẫn nhìn y hệt như đang gõ "=COUNTIF..." rất xịn!
                    range_obj.Value = current_value
                    time.sleep(0.05)
                
                # Sau khi "diễn" gõ xong, ta gán lại chính thức bằng thuộc tính .Formula
                # để Excel bắt đầu tính toán và ra kết quả thật!
                if is_formula:
                    range_obj.Formula = text
                    
                logger.info(f"  [ExcelEngine] Đã bơm text '{text[:15]}...' vào ô {cell_address} bypass Unikey.")
                return True
            except Exception as e:
                error_code = getattr(e, 'hresult', None)
                # -2147417846 = RPC_E_CALL_REJECTED (Excel busy)
                if error_code == -2147417846 and attempt < 7:
                    wait_time = 0.2 * (2 ** attempt)  # Exponential backoff
                    logger.debug(f"  [ExcelEngine] Excel busy, retry {attempt+1}/8 sau {wait_time:.1f}s...")
                    time.sleep(wait_time)
                elif attempt < 7:
                    logger.debug(f"  [ExcelEngine] (Thử {attempt+1}/8) COM retry...")
                    time.sleep(0.3)
                else:
                    logger.warning(f"  [ExcelEngine] COM bận sau 8 lần thử, lỗi: {e}")
        return False

    def silent_select_cell(self, cell_address: str) -> bool:
        """Thực hiện Select ô trong Excel một cách im lặng qua COM."""
        # Reconnect nếu chưa connected hoặc connection bị stale
        if not self.connected or not self._excel:
            if not self.connect():
                return False
                
        self._check_thread()
        
        # Kiểm tra lại sau _check_thread
        if not self.connected or not self._excel:
            logger.error("  [ExcelEngine] Connection failed after _check_thread")
            return False
        
        # Retry với exponential backoff khi Excel busy
        for attempt in range(8):  # Tăng lên 8 lần
            try:
                wb = self._excel.ActiveWorkbook
                if wb:
                    ws = wb.ActiveSheet
                    ws.Range(cell_address).Select()
                    logger.info(f"  [ExcelEngine] Đã Select ô {cell_address} ngầm qua COM thành công.")
                    return True
                break
            except Exception as e:
                error_code = getattr(e, 'hresult', None)
                # -2147417846 = RPC_E_CALL_REJECTED (Excel busy)
                if error_code == -2147417846 and attempt < 7:
                    wait_time = 0.2 * (2 ** attempt)  # Exponential backoff
                    logger.debug(f"  [ExcelEngine] Excel busy, retry {attempt+1}/8 sau {wait_time:.1f}s...")
                    time.sleep(wait_time)
                elif attempt < 7:
                    logger.debug(f"  [ExcelEngine] (Thử {attempt+1}/8) Select COM retry...")
                    time.sleep(0.3)
                else:
                    logger.warning(f"  [ExcelEngine] Select COM thất bại sau 8 lần: {e}")
        return False

# Khởi tạo singleton
excel_engine = None

def get_excel_engine() -> ExcelEngine:
    global excel_engine
    if excel_engine is None:
        excel_engine = ExcelEngine()
    return excel_engine
