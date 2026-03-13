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
- **Sửa chữa:** Bổ sung tính năng "Auto-wait (Polling)" tới 5 giây vào hàm `resolveTarget` trong `runner.ts` giúp Webreel kiên nhẫn đợi element xuất hiện giống hệt cơ chế của Playwright The.
