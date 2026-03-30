"""
Screenshot Capture Module
Chup anh man hinh tai cac thoi diem thuc thi step
"""
import logging
import pyautogui
from pathlib import Path
from typing import Optional
import time

logger = logging.getLogger(__name__)

class ScreenshotCapture:
    """Chup anh man hinh de tao document"""
    
    def __init__(self, output_dir: Path, target_pid: int = None):
        self.output_dir = output_dir
        self.screenshots_dir = output_dir / "screenshots"
        self.screenshots_dir.mkdir(exist_ok=True, parents=True)
        self.target_pid = target_pid
        logger.info(f"  [ScreenshotCapture] Khoi tao: {self.screenshots_dir}")
        if target_pid:
            logger.info(f"  [ScreenshotCapture] Target PID: {target_pid}")
    
    def capture_step(self, step_index: int, delay_ms: int = 100) -> str:
        """
        Chup anh man hinh tai thoi diem thuc thi buoc
        
        Args:
            step_index: So thu tu buoc
            delay_ms: Do tre sau khi chuot di chuyen (de PowerToys kip hien thi)
        
        Returns:
            Duong dan file anh da luu
        """
        time.sleep(delay_ms / 1000)
        
        filename = f"step_{step_index:03d}.png"
        filepath = self.screenshots_dir / filename
        
        try:
            # Neu co target_pid, thu chup chi cua so do
            if self.target_pid:
                screenshot = self._capture_window_by_pid(self.target_pid)
                if screenshot:
                    screenshot.save(filepath)
                    logger.info(f"  [ScreenshotCapture] Da chup cua so (PID={self.target_pid}): {filename}")
                    return str(filepath)
            
            # Fallback: chup toan man hinh
            screenshot = pyautogui.screenshot()
            screenshot.save(filepath)
            logger.info(f"  [ScreenshotCapture] Da chup toan man hinh: {filename}")
            return str(filepath)
        except Exception as e:
            logger.error(f"  [ScreenshotCapture] Loi chup anh: {e}")
            return None
    
    def _capture_window_by_pid(self, pid: int):
        """Chup anh chi cua so cua PID cu the"""
        try:
            import win32gui
            import win32ui
            import win32con
            from PIL import Image
            
            # Tim window handle tu PID
            def callback(hwnd, hwnds):
                import win32process
                _, found_pid = win32process.GetWindowThreadProcessId(hwnd)
                if found_pid == pid and win32gui.IsWindowVisible(hwnd):
                    hwnds.append(hwnd)
                return True
            
            hwnds = []
            win32gui.EnumWindows(callback, hwnds)
            
            if not hwnds:
                logger.warning(f"  [ScreenshotCapture] Khong tim thay window cho PID={pid}")
                return None
            
            hwnd = hwnds[0]
            
            # Lay kich thuoc cua so
            left, top, right, bottom = win32gui.GetWindowRect(hwnd)
            width = right - left
            height = bottom - top
            
            # Chup anh cua so
            hwndDC = win32gui.GetWindowDC(hwnd)
            mfcDC = win32ui.CreateDCFromHandle(hwndDC)
            saveDC = mfcDC.CreateCompatibleDC()
            
            saveBitMap = win32ui.CreateBitmap()
            saveBitMap.CreateCompatibleBitmap(mfcDC, width, height)
            saveDC.SelectObject(saveBitMap)
            
            result = saveDC.BitBlt((0, 0), (width, height), mfcDC, (0, 0), win32con.SRCCOPY)
            
            bmpinfo = saveBitMap.GetInfo()
            bmpstr = saveBitMap.GetBitmapBits(True)
            
            im = Image.frombuffer(
                'RGB',
                (bmpinfo['bmWidth'], bmpinfo['bmHeight']),
                bmpstr, 'raw', 'BGRX', 0, 1
            )
            
            # Cleanup
            win32gui.DeleteObject(saveBitMap.GetHandle())
            saveDC.DeleteDC()
            mfcDC.DeleteDC()
            win32gui.ReleaseDC(hwnd, hwndDC)
            
            return im
            
        except Exception as e:
            logger.warning(f"  [ScreenshotCapture] Loi chup cua so: {e}")
            return None
    
    def capture_region(self, x: int, y: int, width: int, height: int, step_index: int) -> str:
        """Chup mot vung cu the tren man hinh"""
        filename = f"step_{step_index:03d}_region.png"
        filepath = self.screenshots_dir / filename
        
        try:
            screenshot = pyautogui.screenshot(region=(x, y, width, height))
            screenshot.save(filepath)
            logger.info(f"  [ScreenshotCapture] Da chup vung: {filename}")
            return str(filepath)
        except Exception as e:
            logger.error(f"  [ScreenshotCapture] Loi chup vung: {e}")
            return None
    
    def highlight_click_area(self, image_path: str, x: int, y: int, radius: int = 30):
        """Ve vong tron do quanh vi tri click"""
        try:
            import cv2
            import numpy as np
            
            img = cv2.imread(image_path)
            if img is None:
                logger.error(f"  [ScreenshotCapture] Khong doc duoc anh: {image_path}")
                return
            
            cv2.circle(img, (x, y), radius, (0, 0, 255), 3)
            cv2.imwrite(image_path, img)
            logger.info(f"  [ScreenshotCapture] Da highlight click area")
        except Exception as e:
            logger.error(f"  [ScreenshotCapture] Loi highlight: {e}")
