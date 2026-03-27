# Báo Cáo Sự Cố & Giải Quyết 

Tài liệu này tổng hợp các lỗi đã ghi nhận từ giai đoạn đầu tích hợp Webreel x Browser-Use và các bug cốt lõi sâu bên trong engine của Webreel vừa được phát hiện & xử lý.

## 1. Các Vấn Đề Từ Giai Đoạn Tích Hợp (Browser-Use)

### 1.1. Google Anti-Bot Detection
- **Vấn đề:** Google chặn hoàn toàn browser automation (ngay cả chế độ headed).
- **Nguyên nhân:** Các cơ chế bảo mật tinh vi của Google phát hiện được Playwright/Puppeteer (fingerprint, CDP leaks...).
- **Giải pháp tạm thời:** Tránh sử dụng cho các dịch vụ Google. Chỉ áp dụng cho localhost hoặc public websites ít bot-protection gay gắt (VD: Wikipedia).

### 1.2. Browser-Use Lưu Session
- **Vấn đề:** Khi chạy nhiều lần, browser-use sử dụng lại session đã lưu (đã đăng nhập sẵn từ trước), khiến Webreel không quay được màn hình quá trình đăng nhập.
- **Giải pháp:** Tắt tuỳ chọn `user_data_dir` để ép profile trắng mỗi khi ghi hình quá trình mới.

---

## 2. Các Bug Cốt Lõi Vừa Sửa (Webreel Core & Parser)

### 2.1. Selector Array Fallback Bị Lỗi (Parser & Core)
- **Vấn đề:** `ai_reviewer.py` của Gemini và webreel schema v1 đều từ chối hoặc phá vỡ cấu trúc mảng dự phòng `[xpath, css]` thành một string lỗi. Dẫn đến fallback không hoạt động.
- **Sửa chữa:** 
  - Đã cập nhật `v1.json` schema cho phép mảng chuỗi (array of strings).
  - Điều chỉnh AI Prompt để bảo tồn mảng dự phòng của XPath.
  - Sửa hàm in log `formatStep` trong Webreel Core để hiển thị mảng dễ đọc, tránh dính chùm chuỗi.

### 2.2. Lỗi Crash XPath do `document.evaluate` (Webreel Core)
- **Vấn đề:** Webreel đã hỗ trợ XPath, tuy nhiên hàm `document.evaluate` của trình duyệt rất nhạy cảm. Quăng một XPath bị lỗi cú pháp hoặc thẻ biến mất (như `<a>`), nó sẽ ném thẳng `DOMException`, làm sập toàn bộ luồng chạy thay vì từ chối nhẹ nhàng dể thử selector CSS tiếp theo.
- **Sửa chữa:** Bọc `try { document.evaluate(...) } catch { return null; }` trong `actions.ts`. Nhờ đó, Webreel tiếp tục xử lý các selector dự phòng an toàn.

### 2.3. Lỗi Silent Type Hang (Deadlock Type)
- **Vấn đề:** Khi ghi hình một thao tác diễn ra quá chậm hoặc UI bị đơ, Vòng lặp chụp màn hình `captureLoop` bị treo cứng ở Node.js, không bao giờ nhả lệnh `tick()`. Điều này khiến lệnh `typeText` chờ đợi khung hình tiếp theo tới vô tận (Deadlock).
- **Sửa chữa:** 
  - Bọc hàm `captureScreenshot` với timeout `Promise.race(2000ms)`.
  - Bọc hàm `waitForNextTick()` với timeout 1000ms.
  - Nâng giới hạn lỗi chụp màn hình cho phép lên `300` khung hình để vượt qua các đoạn frame rate bị tụt do React/Vite.

### 2.4. Khựng Timing Do React Rendering
- **Vấn đề:** Webreel chọc vào DOM và gõ nội dung trước khi React kịp render giao diện (Race condition).
- **Sửa chữa:** Bổ sung tính năng "Auto-wait (Polling)" tới 5 giây vào hàm `resolveTarget` trong `runner.ts` giúp Webreel kiên nhẫn đợi element xuất hiện giống hệt cơ chế của Playwright.

### 2.5. Xử Lý UI Phức Tạp (Shadow DOM & ContentEditable)
- **Vấn đề:** Các UI đặc biệt của Google (Gmail Compose, Google Docs) sử dụng Shadow DOM và `contenteditable` khiến Browser-Use "không thấy" hoặc không thể gõ chữ dù đã thấy selector.
- **Giải pháp (Kiến trúc "Tiêm Mã Ngữ Nghĩa"):**
  - Ưu tiên trích xuất **Bộ chọn Ngữ nghĩa** (Aria-label) thay vì CSS structural path.
  - Sử dụng `CDP Runtime.evaluate` để tiêm văn bản trực tiếp qua lệnh `insertText` hoặc trigger native events.
  - **Kết quả:** Vượt qua được rào cản của React/Shadow DOM mà không cần dùng OCR nặng nề, giữ video quay mượt mà và chính xác.


### 3.1. Lỗi Lệch Lời Thoại "One Step Ahead"
- **Vấn đề:** Lời thoại thuyết minh cho trang mới lại bắt đầu đọc khi đang ở trang cũ (ngay khi nhấn nút chuyển trang). Điều này khiến người xem cảm thấy âm thanh đi trước hình ảnh.
- **Nguyên nhân:** Parser `bu_to_webreel.py` đính kèm mô tả (`description`) vào hành động `click` chuyển trang. AI Reviewer sau đó chèn âm thanh bắt đầu từ thời điểm hành động đó diễn ra.
- **Sửa chữa:** Tách biệt lời thoại (`save_narration`) thành các bước `pause` (1s) đứng độc lập trong Webreel config. Lời thoại chỉ bắt đầu khi người dùng thực sự đã đặt chân lên slide/trang mới.

### 3.2. Instability & TTS 404 (FPT.AI)
- **Vấn đề:** FPT.AI đôi khi trả về lỗi 404 hoặc "Đang xử lý" quá lâu khiến quá trình download audio bị crash.
- **Sửa chữa:** 
  - Triển khai cơ chế **Retry (thử lại 3 lần)** trong `tts.py`.
  - Nâng timeout polling lên 60 giây để xử lý các đoạn text dài.
  - Kiểm tra `Content-Type` phản hồi để phân biệt file MP3 thật sự với trang báo lỗi HTML của FPT.

### 3.3. Lỗi Lồng Tiếng & Giảm Âm Lượng (ffmpeg Mix)
- **Vấn đề:** Khi trộn nhiều kênh âm thanh thuyết minh vào video, âm lượng bị nhỏ đi đáng kể hoặc gặp lỗi cú pháp `adelay`.
- **Sửa chữa (Trace Composer):**
  - Chuyển sang cú pháp `adelay=delays={ms}:all=1` giúp hỗ trợ cả track Mono và Stereo đồng nhất.
  - Bổ sung bộ lọc `volume=1.5` và tắt `normalize` trong `amix` để giữ âm lượng thuyết minh to, rõ và không bị tự động nén.

## 4. Các Vấn Đề Khi Triển Khai OS-Level Automation

### 4.1. Hạn Chế Phần Cứng & Ảo Hóa (Sandbox/Hyper-V)
- **Vấn đề:** Để có môi trường ghi hình sạch (Clean-State), phương án lý tưởng là dùng Windows Sandbox hoặc Hyper-V. Tuy nhiên, giới hạn phần cứng thực tế (16GB RAM, trống ~4.5GB) khiến việc spin-up máy ảo (VM) liên tục tốn quá nhiều tài nguyên, gây giật lag FFmpeg và làm hỏng luồng ghi hình.
- **Giải pháp:** Áp dụng mô hình **Process-Level Clean State**. Thay vì ảo hóa toàn hệ điều hành, Agent chỉ nhận diện tiến trình gốc (`app_executable`). Sau bước Agent dò đường, hệ thống sẽ tự động tắt (`kill`) tiến trình bị vấy bẩn và gọi mở lại (`spawn`) một cửa sổ ứng dụng mới tinh. Điều này mang lại môi trường ghi hình sạch tương đương Sandbox nhưng độ trễ và tiêu thụ tài nguyên gần như bằng không.

### 4.2. Xung Đột Bộ Gõ Tiếng Việt (Unikey/EVKey Hooking)
- **Vấn đề:** Khi mô phỏng gõ phím ở cấp OS bằng `pyautogui`, bộ gõ tiếng Việt chạy ngầm sẽ chặn ngang (keyboard hooking). Ví dụ: Agent gõ chữ tiếng Anh `test`, Unikey lập tức nối chuỗi thành `tét`, làm sai lệch kịch bản quay. Dùng Clipboard (`Ctrl+V`) giải quyết được độ chính xác nhưng lại làm mất đi hiệu ứng "gõ lạch cạch từng phím" chân thật của video.
- **Sửa chữa:** Chuyển sang sử dụng `win.type_keys()` của kiến trúc `pywinauto`. Lệnh này bơm trực tiếp các gói lệnh `WM_CHAR` (chứa toàn bộ Text đa ngôn ngữ) vào API của Application Window, hoàn toàn "tàng hình" khỏi mắt của Unikey/EVKey. Kết quả: Khắc phục sự phá bĩnh của hệ thống Telex, hỗ trợ nhập 100% tiếng Việt nguyên gốc, lại được tham số hóa `pause=0.05` để giữ chất lượng hiệu ứng ấn phím tự nhiên trên Video thành phẩm.

### 4.3. Lỗi Lệch Tọa Độ (Offset) & Hàm Nhập Bị Crash Trên Excel
- **Vấn đề:** 
  - (1) Hàm tọa độ ảo COM (`PointsToScreenPixels`) bị sai số trầm trọng khi màn hình dùng DPI Scale khác 100% hoặc thu phóng thanh Ribbon. Chuột đáp trượt khung ô làm thao tác thất bại.
  - (2) Truyền công thức chứa phép tính (bắt đầu bằng `=`) qua vòng lặp theo thời gian thực (từng ký tự) vào COM `.Value` khiến Excel ném Exception `NAME_NOT_FOUND (-2146827284)` vì cố thông dịch công thức dở dang. Hơn nữa, việc lặp lại `Range.Select()` tạo ra viền xanh bao quanh ô trước khi chuột tiến lại, phá vỡ tính "người thật" (human-like) của luồng tutorial.
- **Sửa chữa:**
  - **Tọa độ UIA Tuyệt Đối:** Bỏ COM tĩnh, dùng thư viện `uiautomation` bắn thẳng tia quét vào `DataItemControl` trên màn hình lấy giá trị pixel vật lý cuối cùng (`BoundingRectangle`), đảm bảo độ chính xác 100% vĩnh viễn. Thay thế `Range.Select()` bằng `ActiveWindow.ScrollRow` để nhẹ nhàng cuộn mục tiêu vào tầm nhìn mà không làm bôi đen vật thể.
  - **Thủ thuật (') Ảo Thuật Formular:** Tích hợp logic chèn ký tự nháy đơn (`'`) dẫn đầu chuỗi mô phỏng gõ tay (`'=COUNTIF`). Excel sẽ khóa cửa kiểm tra lỗi cú pháp vì quy chụp đó là văn bản. Cuối quá trình gõ, lệnh `Range.Formula` sẽ tước bỏ nháy đơn và trả về công thức số liệu chuẩn xác, giữ nguyên vẹn giá trị trị trực quan trên Video FFmpeg.

### 4.4. Mất Môi Trường PowerPoint & FFmpeg Negative Bounds
- **Vấn đề:** Kịch bản Dọn dẹp (`Cleanup State`) tự tắt (`Kill`) tiến trình PowerPoint làm văng cả Slide đang mở sẵn của Editor, sau đó tự spawn lại bằng Popen gây lỗi `FileNotFoundError` vì App không nằm ở PATH root. Cùng lúc đó khi bật SlideShow Toàn màn hình, hệ điều hành trả về tọa độ âm (Ví dụ `Left: -9, Top: -9`). FFmpeg `gdigrab` cự tuyệt quay phim và `exited immediately`.
- **Sửa chữa:**
  - Định tuyến lại `os_pipeline.py` với cờ `--ppt`, gán quyền không Kill Process cho `powerpnt.exe` giống như quy định cũ của Excel.
  - Bổ sung lưới tọa độ (`Clamping`) dùng `min/max` cùng thuật toán quét `GetSystemMetrics` trực tiếp vào `media_engine.py`. Ép mốc âm lùi về `0` và vạt bớt `Width/Height` cho bằng với màn vật lý, giúp FFmpeg record vô tư với mọi chế độ FullScreen của Application.

