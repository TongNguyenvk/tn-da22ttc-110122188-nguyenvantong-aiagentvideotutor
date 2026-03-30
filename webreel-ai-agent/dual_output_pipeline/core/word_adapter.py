# Copy from os_recorder/core/word_adapter.py
import logging
import win32com.client
import pythoncom
import threading
import ctypes
import time

logger = logging.getLogger(__name__)

def get_dpi_scale_factor():
    """
    Lay DPI scale factor cua man hinh.
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
        logger.warning(f"  [WordAdapter] Khong lay duoc DPI scale: {e}, dung 1.0")
        return 1.0

class WordAdapter:
    """
    Adapter de tu dong hoa Microsoft Word qua COM API.
    Dung cho Dual-Output pipeline de tao document tu dong.
    """
    def __init__(self):
        self._word = None
        self.connected = False
        self._thread_id = None
        self._doc = None
    
    def connect(self) -> bool:
        """Ket noi voi Word instance dang chay hoac tao moi"""
        try:
            pythoncom.CoInitialize()
            self._word = win32com.client.GetActiveObject("Word.Application")
            self.connected = True
            self._thread_id = threading.get_ident()
            logger.info("  [WordAdapter] Da ket noi thanh cong vao Word COM.")
            return True
        except Exception as e:
            try:
                pythoncom.CoInitialize()
                self._word = win32com.client.Dispatch("Word.Application")
                self._word.Visible = True
                self.connected = True
                self._thread_id = threading.get_ident()
                logger.info("  [WordAdapter] Da Dispatch thanh cong Word COM.")
                return True
            except Exception as e2:
                logger.warning(f"  [WordAdapter] Khong the ket noi Word COM: {e2}")
                self.connected = False
                return False

    def check_connection(self) -> bool:
        """Kiem tra ket noi Word con hoat dong khong"""
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

    def open_word(self):
        """Mo Word va tao document moi"""
        if not self.check_connection():
            if not self.connect():
                raise RuntimeError("Khong the ket noi Word")
        
        self._doc = self._word.Documents.Add()
        logger.info("  [WordAdapter] Da tao document moi")
    
    def type_text(self, text: str):
        """Go text vao document"""
        if not self._doc:
            raise RuntimeError("Chua mo document")
        
        selection = self._word.Selection
        selection.TypeText(text)
        logger.info(f"  [WordAdapter] Da go text: {text[:50]}...")
    
    def press_key(self, key: str, times: int = 1):
        """Nhan phim (enter, tab, etc.)"""
        if not self._doc:
            raise RuntimeError("Chua mo document")
        
        selection = self._word.Selection
        
        if key.lower() == 'enter':
            for _ in range(times):
                selection.TypeParagraph()
        elif key.lower() == 'tab':
            for _ in range(times):
                selection.TypeText('\t')
        elif key.lower().startswith('ctrl+'):
            # Xu ly phim tat
            pass
    
    def insert_picture(self, image_path: str):
        """Chen anh vao document"""
        if not self._doc:
            raise RuntimeError("Chua mo document")
        
        selection = self._word.Selection
        selection.InlineShapes.AddPicture(
            FileName=image_path,
            LinkToFile=False,
            SaveWithDocument=True
        )
        logger.info(f"  [WordAdapter] Da chen anh: {image_path}")
    
    def save_document(self, filename: str):
        """Luu document"""
        if not self._doc:
            raise RuntimeError("Chua mo document")
        
        self._doc.SaveAs2(filename)
        logger.info(f"  [WordAdapter] Da luu document: {filename}")
    
    def close_word(self):
        """Dong Word"""
        if self._doc:
            self._doc.Close(SaveChanges=False)
            self._doc = None
        
        if self._word:
            self._word.Quit()
            self._word = None
        
        self.connected = False
        logger.info("  [WordAdapter] Da dong Word")
