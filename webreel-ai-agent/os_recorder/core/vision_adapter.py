import logging

logger = logging.getLogger(__name__)

try:
    import cv2
    import numpy as np
    import mss
    HAS_CV = True
except ImportError:
    HAS_CV = False
    logger.warning("  [VisionAdapter] Thieu thu vien cv2/numpy/mss. Vision Fallback bi vo hieu hoa.")
    
from core.base_adapter import BaseAdapter

class VisionAdapter(BaseAdapter):
    """
    Fallback Lane (CV Adapter) sử dụng Computer Vision (Template Matching / OCR)
    để tìm kiếm tọa độ phần tử trên các ứng dụng không hỗ trợ COM/UIA (WebRTC, Game, Remote Desktop).
    """
    def __init__(self):
        super().__init__()
        if HAS_CV:
            self.sct = mss.mss()
        else:
            self.sct = None

    def connect(self) -> bool:
        """
        Vision adapter không cần 'kết nối' theo nghĩa đen, nó hoạt động trực tiếp
        trên bộ đệm màn hình. Trả về True luôn.
        """
        return True

    def get_coordinates(self, target_value: str):
        """
        Sử dụng Template Matching hoặc OCR để tìm `target_value` trên màn hình.
        Tạm thời stub phần Template Matching.
        Nếu dùng Pytesseract/EasyOCR, sẽ import và nhận diện text box.
        """
        logger.warning(f"  [VisionAdapter] Đang gọi fallback CV mạo hiểm cho '{target_value}'. Tính năng OCR/TemplateMatching chưa triển khai đầy đủ.")
        
        # TODO: Triển khai pipeline OCR ở đây để lấy bounding box văn bản
        # if target_value.endswith('.png') or target_value.endswith('.jpg'):
        #     return self._template_match(target_value)
        # else:
        #     return self._ocr_match(target_value)

        return None

    def get_range_coordinates(self, target_value: str):
        """
        Trả về dãy điểm để kéo thả.
        """
        coords = self.get_coordinates(target_value)
        if coords:
            return [coords, (coords[0] + 50, coords[1])]
        return None

    def inject_data(self, target_value: str, data: str) -> bool:
        """
        Không thể inject data trực tiếp qua màn hình pixel được.
        Phải dùng Action/Keyboard, nên Adapter trả về False để đẩy về luồng Keyboard.
        """
        return False
        
    def focus_element(self, target_value: str) -> bool:
        """
        Vision adapter không thay đổi trạng thái UI để focus, chỉ quét pixel bề mặt. 
        Luôn trả về False để đẩy về luồng chuột thật.
        """
        return False
        
    def _template_match(self, image_path: str):
        # Implementation of cv2 template matching on self.sct.grab(self.sct.monitors[1])
        pass
        
    def _ocr_match(self, text: str):
        # Implementation of pytesseract/easyocr
        pass
