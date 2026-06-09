# PRD: Auth Enhancement - Google OAuth + Email Verification + Password Reset

## 1. Tong quan

WebReel hien tai chi ho tro dang nhap bang email/password. PRD nay mo ta viec bo sung:

1. **Google Sign-In** (frontend SDK + backend token verification)
2. **Xac nhan email** cho nguoi dung dang ky bang email/password (Gmail SMTP outbound)
3. **Quen/Dat lai mat khau** qua link email
4. **Xu ly dual auth provider** (Google user khong co mat khau, local user phai verify email)

## 2. Nguoi dung muc tieu

- Nguoi dung moi muon dang ky nhanh bang Google
- Nguoi dung hien tai dang ky bang email/password
- Admin quan ly tai khoan

## 3. Yeu cau chuc nang

### 3.1 Google Sign-In

- Frontend su dung `@react-oauth/google` SDK, hien nut "Dang nhap bang Google"
- Backend nhan Google ID Token, verify bang `google.oauth2.id_token`
- Lan dau: tu dong tao account, `auth_provider: "google"`, `email_verified: true`, `password_hash: null`
- Khong bat tao mat khau, lay `name` va `picture` tu Google profile
- Neu email da ton tai (local user): tu dong link, `auth_provider` chuyen thanh `"both"`

### 3.2 Email Verification

- Khi dang ky bang email/password: `status: "pending_verification"`, gui email chua link xac nhan
- Token het han sau 24 gio
- Cho phep gui lai email xac nhan
- Sau khi xac nhan: `status: "active"`, `email_verified: true`
- Chua xac nhan thi khong cho dang nhap

### 3.3 Quen / Dat lai mat khau

- Nhap email, nhan link reset (token het han 1 gio)
- Google-only user: hien thong bao "Ban da dang nhap bang Google, vui long su dung Google Sign-In"
- Local/Both user: gui email chua link reset
- Form dat mat khau moi + xac nhan

### 3.4 Doi mat khau

- User da dang nhap co the doi mat khau (yeu cau nhap mat khau cu)
- Google user co the "Dat mat khau" (khong can mat khau cu vi chua co)

### 3.5 Database Schema

Truong moi/sua tren collection `users`:

| Field                        | Type                            | Mo ta                        |
| ---------------------------- | ------------------------------- | ---------------------------- |
| `auth_provider`              | `"local" \| "google" \| "both"` | Phuong thuc dang ky          |
| `google_id`                  | `string \| null`                | Google sub (unique ID)       |
| `avatar_url`                 | `string \| null`                | Google profile picture       |
| `password_hash`              | `string \| null`                | `null` cho Google-only users |
| `verification_token_expires` | `datetime \| null`              | Het han token xac nhan       |
| `reset_token`                | `string \| null`                | Token reset mat khau         |
| `reset_token_expires`        | `datetime \| null`              | Het han token reset          |

Index moi: `google_id` (unique, sparse).

## 4. Yeu cau ky thuat

- SMTP outbound (khong mo port): `smtp.gmail.com:587` voi Gmail App Password
- Sender: "WebReel Team"
- Frontend env: `VITE_GOOGLE_CLIENT_ID`
- Backend env: `GOOGLE_OAUTH_CLIENT_ID`, `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `FRONTEND_URL`
- Chạy hoàn toàn trong môi trường Docker bằng `docker-compose.prod.yml`. Backend container (`api`) truy cập internet để gửi SMTP và gọi Google OAuth API. MongoDB chạy nội bộ không expose port ra ngoài để đảm bảo bảo mật.

## 5. Ngoai pham vi

- OAuth providers khac (Facebook, GitHub)
- Two-factor authentication (2FA)
- Social login account deletion
- Payment/Stripe integration

## 6. Trạng thái triển khai (Implementation Progress)

- [x] **Task 1: Google Sign-In** - **ĐÃ HOÀN THÀNH**
  - Đã tích hợp frontend `@react-oauth/google` SDK.
  - Đã viết backend verification hỗ trợ bù lệch giờ (clock skew) 60 giây.
  - Đã bổ sung cơ chế link tài khoản (`auth_provider` = `"both"`).
- [x] **Task 2: Xác nhận Email (Email Verification)** - **ĐÃ HOÀN THÀNH**
  - Triển khai SMTP helper bất đồng bộ (sử dụng `asyncio.to_thread` tránh chặn Event Loop).
  - Tích hợp trạng thái `pending_verification` khi đăng ký tài khoản cục bộ mới, chặn đăng nhập (trả về 403 Forbidden) cho tới khi verify thành công.
  - Thêm trang `VerifyEmail` của frontend để tự động xử lý token kích hoạt tài khoản.
  - Cập nhật trang `Register` hiển thị thông báo check email và trang `Login` hiển thị banner cảnh báo tài khoản chưa xác thực kèm nút gửi lại link xác thực tại chỗ.
  - Thiết kế toàn bộ giao diện thông báo, phản hồi API và email hiển thị bằng Tiếng Việt có dấu hoàn chỉnh.
  - Viết kịch bản test tự động `test_email_verification.py` chạy trực tiếp trong container `webreel-api` kết nối MongoDB để kiểm chứng toàn bộ luồng hoạt động chính xác.
- [x] **Task 3: Quên / Đặt lại mật khẩu (Password Reset)** - **ĐÃ HOÀN THÀNH**
  - Triển khai Pydantic schemas `ForgotPasswordRequest` và `ResetPasswordRequest` đi kèm validation độ mạnh mật khẩu (ít nhất 8 ký tự, bao gồm chữ cái và chữ số).
  - Thêm các API endpoints `/forgot-password` và `/reset-password` tại backend, tích hợp kiểm tra loại trừ đối với tài khoản Google-only để từ chối đổi mật khẩu và trả về hướng dẫn đăng nhập Google Sign-In cụ thể.
  - Xây dựng màn hình `ForgotPassword.tsx` và `ResetPassword.tsx` đẹp mắt, tương thích hoàn toàn hệ thống CSS/Dark-Mode và xử lý định tuyến tự động.
  - Viết kịch bản kiểm thử tích hợp tự động `test_password_reset.py` chạy trực tiếp trong container kết nối MongoDB để kiểm chứng toàn bộ luồng tạo, xác thực token và đăng nhập với mật khẩu mới.
- [ ] **Task 4: Đổi mật khẩu (Change Password)** - _Chưa bắt đầu_
