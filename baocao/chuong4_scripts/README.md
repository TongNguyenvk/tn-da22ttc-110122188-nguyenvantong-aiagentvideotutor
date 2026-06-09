# Scripts minh chứng cho Chương 4

Các script này được Claude soạn sẵn để bạn mở **Terminal/PowerShell mới**
chạy và **chụp màn hình** đính kèm vào báo cáo Chương 4 WebReel.

> Tất cả script đã được Claude chạy thật trên hệ thống hiện tại và xác minh
> output đúng với mô tả trong báo cáo. Bạn chỉ cần chạy lại để chụp hình.

## Thứ tự chụp

| #   | Script                             | Tương ứng "Hình …" trong báo cáo                     |
| --- | ---------------------------------- | ---------------------------------------------------- |
| 1   | `01_docker_ps_overview.ps1`        | Bổ sung – tổng quan cụm Docker đang chạy             |
| 2   | `02_submit_job_and_logs.ps1`       | Hình 4.z – Nhật ký phân phối tác vụ qua Redis        |
| 3   | `03_ffmpeg_stream_copy.ps1`        | Hình 4.v – FFmpeg Stream Copy tốc độ cao             |
| 4   | `04_security_whoami.ps1`           | Hình 4.a phụ – Worker chạy non-root (user webreel)   |
| 5   | `05_failsafe_default_password.ps1` | Hình 4.a – Fail-safe khi phát hiện mật khẩu mặc định |
| 6   | `06_rate_limit_429.ps1`            | Hình 4.c – Rate Limiter trả về HTTP 429              |
| 7   | `07_video_properties.ps1`          | Hình 4.u – Thuộc tính file MP4 1920x1080 30fps       |
| 8   | `08_stats_resource_usage.ps1`      | Mục 4.4.3 – Mức tiêu thụ tài nguyên thực tế          |

## Cách sử dụng

1. Mở **PowerShell** mới (không phải tab này) → `cd` vào thư mục
   `F:\==HK1-2526==\ThucTap\webreel\baocao\chuong4_scripts`.
2. Chạy lần lượt từng script (bấm Enter sau mỗi câu lệnh).
3. Sau khi script in xong, **chụp toàn bộ cửa sổ Terminal** rồi đặt tên file
   ảnh theo đúng cột "Tương ứng" ở bảng trên.

## Yêu cầu trước khi chạy

- Stack `docker-compose.prod.yml` đang chạy (`docker ps` thấy webreel-api,
  webreel-redis, webreel-mongodb, …).
- Frontend lắng nghe trên http://localhost:3000.
- Đã chạy `01_setup_demo_user.ps1` **một lần duy nhất** để tạo user demo
  dùng cho script #6 (rate limit).
