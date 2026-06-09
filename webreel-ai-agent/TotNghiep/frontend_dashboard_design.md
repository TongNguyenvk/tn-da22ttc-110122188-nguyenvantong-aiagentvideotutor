# TÀI LIỆU THIẾT KẾ PHÁC THẢO GIAO DIỆN NGƯỜI DÙNG VÀ LUỒNG TƯƠNG TÁC

# (WEBREEL FRONTEND DASHBOARD SKETCH DESIGN)

Tài liệu này cung cấp thiết kế phác thảo chi tiết cho tất cả giao diện người dùng và luồng tương tác của hệ thống WebReel. Phân hệ Frontend được xây dựng bằng React, Vite, Tailwind CSS và shadcn/ui dưới dạng ứng dụng trang đơn (Single Page Application - SPA). Tài liệu này được biên soạn để mô tả toàn bộ cấu trúc màn hình từ các trang công cộng cho đến không gian làm việc của người dùng và quản trị viên, giúp lập trình viên nắm bắt bố cục trực quan và logic xử lý giao diện.

---

## 1. PHÂN KHU GIAO DIỆN VÀ KHUNG BỐ CỤC CHUNG (LAYOUT AND SIDEBAR)

Toàn bộ các trang dành cho người dùng đã đăng nhập đều chia sẻ chung một khung bố cục (AppLayout) chứa thanh điều hướng bên cạnh (Sidebar) và khu vực hiển thị nội dung chính bên phải. Bố cục này thay đổi linh hoạt tùy theo vai trò của tài khoản (Người dùng thường hoặc Quản trị viên).

### 1.1. Phác thảo Bố cục Sidebar chung cho Người dùng thường

```
+-------------------------------------------------------------+
| WebReel                                                     |
|                                                             |
| +---------------------------------------------------------+ |
| | [Icon: User]                                            | |
| | Nguyen Van A                                            | |
| | vana@email.com                                          | |
| +---------------------------------------------------------+ |
|                                                             |
| [Icon: LayoutDashboard] Tong quan                           |
| [Icon: Video] Tao moi                                       |
|                                                             |
| ----------------------------------------------------------- |
| Giao dien: [ Sang ] [ Toi ]                                 |
|                                                             |
| [Icon: Key] Doi mat khau                                    |
| [Icon: LogOut] Dang xuat                                    |
+-------------------------------------------------------------+
```

### 1.2. Phác thảo Bố cục Sidebar chung cho Quản trị viên (Admin)

```
+-------------------------------------------------------------+
| WebReel (Admin)                                             |
|                                                             |
| +---------------------------------------------------------+ |
| | [Icon: User]                                            | |
| | Admin System                                            | |
| | admin@webreel.vn                                        | |
| +---------------------------------------------------------+ |
|                                                             |
| [Icon: LayoutDashboard] Tong quan                           |
| [Icon: Users] Nguoi dung                                    |
| [Icon: Video] Cong viec                                     |
| [Icon: Monitor] Trinh duyet                                 |
| [Icon: Snowflake] Session Manager                           |
|                                                             |
| ----------------------------------------------------------- |
| Giao dien: [ Sang ] [ Toi ]                                 |
|                                                             |
| [Icon: Key] Doi mat khau                                    |
| [Icon: LogOut] Dang xuat                                    |
+-------------------------------------------------------------+
```

---

## 2. NHÓM GIAO DIỆN CÔNG CỘNG VÀ XÁC THỰC (PUBLIC AND GUEST PAGES)

Các trang thuộc nhóm này được sử dụng khi người dùng chưa đăng nhập hệ thống. Giao diện tập trung vào tính tối giản, bảo mật và thân thiện.

### 2.1. Trang Đăng nhập (Login Page)

Đường dẫn truy cập: `/login`

Trang đăng nhập hỗ trợ cả hai phương thức đăng nhập qua tài khoản cục bộ (Email/Mật khẩu) và đăng nhập nhanh qua Google OAuth.

#### Phác thảo Giao diện

```
+-----------------------------------------------------------------+
|                         Logo WebReel                            |
|                            WebReel                              |
|                   Dang nhap de tiep tuc                         |
|                                                                 |
| +-------------------------------------------------------------+ |
| | Dang nhap                                                   | |
| | Nhap email va mat khau cua ban                              | |
| |                                                             | |
| | [ THONG BAO: Tai khoan chua xac thuc email.               ] | |
| | [ Click vao day de: Gui lai email xac thuc                ] | |
| |                                                             | |
| |               +---------------------------+                 | |
| |               |    Sign In with Google    |                 | |
| |               +---------------------------+                 | |
| |                                                             | |
| | --------------------------- hoac -------------------------- | |
| |                                                             | |
| | Email                                                       | |
| | [ your@email.com__________________________________________] | |
| |                                                             | |
| | Mat khau                             [ Quen mat khau? ]     | |
| | [ ********________________________________________________] | |
| |                                                             | |
| | +---------------------------------------------------------+ |
| | |                       Dang nhap                         | |
| | +---------------------------------------------------------+ |
| |                                                             | |
| | Chua co tai khoan? [ Dang ky ngay ]                         | |
| +-------------------------------------------------------------+ |
+-----------------------------------------------------------------+
```

- **Xử lý Banner xác thực:** Nếu đăng nhập thất bại với thông báo chưa xác thực email, banner cảnh báo xuất hiện kèm liên kết kích hoạt gửi lại email xác thực (HTTP POST `/api/auth/resend-verification`).

### 2.2. Trang Đăng ký (Register Page)

Đường dẫn truy cập: `/register`

Hỗ trợ tạo tài khoản mới bằng email và mật khẩu hoặc liên kết tài khoản Google trực tiếp.

#### Phác thảo Giao diện

```
+-----------------------------------------------------------------+
|                         Logo WebReel                            |
|                            WebReel                              |
|                       Tao tai khoan moi                         |
|                                                                 |
| +-------------------------------------------------------------+ |
| | Dang ky                                                     | |
| | Dien thong tin de tao tai khoan                             | |
| |                                                             | |
| |               +---------------------------+                 | |
| |               |    Sign Up with Google    |                 | |
| |               +---------------------------+                 | |
| |                                                             | |
| | --------------------------- hoac -------------------------- | |
| |                                                             | |
| | Ho va ten                                                   | |
| | [ Nguyen Van A____________________________________________] | |
| |                                                             | |
| | Email                                                       | |
| | [ your@email.com__________________________________________] | |
| |                                                             | |
| | Mat khau                                                    | |
| | [ ********________________________________________________] | |
| | * It nhat 8 ky tu, co chu cai va so                         | |
| |                                                             | |
| | Xac nhan mat khau                                           | |
| | [ ********________________________________________________] | |
| | [ Canh bao: Mat khau khong khop (neu co)                  ] | |
| |                                                             | |
| | +---------------------------------------------------------+ |
| | |                        Dang ky                          | |
| | +---------------------------------------------------------+ |
| |                                                             | |
| | Da co tai khoan? [ Dang nhap ]                              | |
| +-------------------------------------------------------------+ |
+-----------------------------------------------------------------+
```

- **Xử lý đăng ký thành công:** Giao diện hiển thị card thông báo gửi mail xác thực.

#### Phác thảo Card Thông báo Đăng ký Thành công

```
+-----------------------------------------------------------------+
|                         Logo WebReel                            |
|                            WebReel                              |
|                                                                 |
| +-------------------------------------------------------------+ |
| |                   [Icon: Mail - animate]                    | |
| |                   Kiem tra email cua ban                    | |
| |                                                             | |
| | Chung toi da gui mot lien ket xac thuc tai khoan den email  | |
| | vana@email.com. Vui long kiem tra hop thu (va hop thu rac)  | |
| | de hoan tat kich hoat.                                      | |
| |                                                             | |
| | +---------------------------------------------------------+ |
| | |                  Quay lai dang nhap                     | |
| | +---------------------------------------------------------+ |
| +-------------------------------------------------------------+ |
+-----------------------------------------------------------------+
```

### 2.3. Trang Xác thực Email (Verify Email Page)

Đường dẫn truy cập: `/verify-email?token=xyz`

Trang này tự động đọc tham số `token` từ URL để gửi yêu cầu xác minh tới Backend (HTTP GET `/api/auth/verify-email/{token}`).

#### Phác thảo các trạng thái hiển thị

```
Trang thai 1: Dang kiem tra xac thuc (Loading)
+-----------------------------------------------------------------+
|                   [Icon: Loader - Xoay]                         |
|                       Dang xac thuc                             |
| Vui long cho trong giay lat, chung toi dang kiem tra token...   |
+-----------------------------------------------------------------+

Trang thai 2: Xac thuc thanh cong (Success)
+-----------------------------------------------------------------+
|                   [Icon: CheckCircle]                           |
|                    Xac thuc thanh cong                          |
| Email cua ban da duoc xac thuc. Tai khoan san sang hoat dong.   |
|                                                                 |
| +-------------------------------------------------------------+ |
| |                       Dang nhap ngay                        | |
| +-------------------------------------------------------------+ |
+-----------------------------------------------------------------+

Trang thai 3: Xac thuc that bai (Error)
+-----------------------------------------------------------------+
|                     [Icon: XCircle]                             |
|                    Xac thuc that bai                            |
| [ Thong bao loi: Duong dan da het han hoac ma khong hop le ]    |
|                                                                 |
| Nhap email cua ban de nhan lai link xac thuc:                   |
| [ email@yourdomain.com______________________________________]   |
|                                                                 |
| +-------------------------------------------------------------+ |
| |                    Gui lai email xac thuc                   | |
| +-------------------------------------------------------------+ |
|                                                                 |
|                     [ Quay lai dang nhap ]                      |
+-----------------------------------------------------------------+
```

### 2.4. Trang Quên Mật Khẩu (Forgot Password Page)

Đường dẫn truy cập: `/forgot-password`

Yêu cầu hệ thống gửi liên kết đặt lại mật khẩu cho người dùng quên mật khẩu cục bộ.

#### Phác thảo Giao diện

```
+-----------------------------------------------------------------+
|                          Logo Key                               |
|                          WebReel                                |
|                 Khoi phuc mat khau tai khoan                    |
|                                                                 |
| +-------------------------------------------------------------+ |
| | Quen mat khau?                                              | |
| | Nhap email cua ban. Chung toi se gui link khoi phuc.         | |
| |                                                             | |
| | [ CANH BAO: Tai khoan dang ky bang Google. Hay quay lai   ] | |
| | [ trang dang nhap va chon Sign In with Google.             ] | |
| |                                                             | |
| | Dia chi Email                                               | |
| | [ your@email.com__________________________________________] | |
| |                                                             | |
| | +---------------------------------------------------------+ |
| | |             Gui lien ket dat lai mat khau               | |
| | +---------------------------------------------------------+ |
| |                                                             | |
| |                     [ Quay lai dang nhap ]                  | |
| +-------------------------------------------------------------+ |
+-----------------------------------------------------------------+
```

- **Xử lý tài khoản Google:** Nếu API trả về lỗi tài khoản thuộc Google Sign-In, giao diện hiển thị banner hướng dẫn sử dụng đăng nhập Google.
- **Thành công:** Tương tự như trang đăng ký, hiển thị card thông báo kiểm tra hòm thư nhận liên kết đặt lại mật khẩu.

### 2.5. Trang Đặt Lại Mật Khẩu (Reset Password Page)

Đường dẫn truy cập: `/reset-password?token=xyz`

Nhập mật khẩu mới sau khi truy cập liên kết khôi phục từ email.

#### Phác thảo Giao diện

```
Trang thai loi: Thieu token hoac token khong hop le
+-----------------------------------------------------------------+
|                         [Icon: XCircle]                         |
|                     Duong dan khong hop le                      |
| Ma xac thuc dat lai mat khau thieu hoac khong chinh xac.        |
|                                                                 |
| +-------------------------------------------------------------+ |
| |                    Yeu cau lien ket moi                     | |
| +-------------------------------------------------------------+ |
+-----------------------------------------------------------------+

Trang thai nhap mat khau moi
+-----------------------------------------------------------------+
|                          Logo Key                               |
|                          WebReel                                |
|                        Dat mat khau moi                         |
|                                                                 |
| +-------------------------------------------------------------+ |
| | Tao mat khau moi                                            | |
| | Nhap mat khau moi va xac nhan de cap nhat tai khoan.         | |
| |                                                             | |
| | Mat khau moi                                                | |
| | [ ********________________________________________________] | |
| | * It nhat 8 ky tu, bao gom ca chu va so                     | |
| |                                                             | |
| | Xac nhan mat khau moi                                       | |
| | [ ********________________________________________________] | |
| |                                                             | |
| | +---------------------------------------------------------+ |
| | |                   Cap nhat mat khau                     | |
| | +---------------------------------------------------------+ |
| |                                                             | |
| |                     [ Quay lai dang nhap ]                  | |
| +-------------------------------------------------------------+ |
+-----------------------------------------------------------------+
```

---

## 3. NHÓM GIAO DIỆN NGƯỜI DÙNG THƯỜNG (USER WORKSPACE)

Khu vực làm việc sau khi đăng nhập thành công. Cho phép người dùng theo dõi các tác vụ đang thực thi, xem và tải video, tạo tác vụ mới và duyệt kịch bản thuyết minh.

### 3.1. Hộp thoại Đổi mật khẩu (Change Password Dialog)

Xuất hiện dưới dạng cửa sổ popup (Modal) khi nhấn nút Đổi mật khẩu ở chân Sidebar.

#### Phác thảo Giao diện

```
+-----------------------------------------------------------------+
| [Icon: Lock] Thay doi mat khau                          [ X ]   |
| --------------------------------------------------------------- |
| [ CANH BAO: Tai khoan dang nhap bang Google. Thiet lap mat  ]   |
| [ khau tai day de dang nhap truc tiep bang email.             ]   |
|                                                                 |
| Mat khau cu (an neu la Google Account)                          |
| [ ********__________________________________________________]   |
|                                                                 |
| Mat khau moi                                                    |
| [ ********__________________________________________________]   |
|                                                                 |
| Yeu cau mat khau:                                               |
| [x] It nhat 8 ky tu                                             |
| [ ] Chua it nhat 1 chu cai                                      |
| [ ] Chua it nhat 1 chu so                                       |
|                                                                 |
| Xac nhan mat khau moi                                           |
| [ ********__________________________________________________]   |
|                                                                 |
|                                         [ Huy ]  [ Cap nhat ]   |
+-----------------------------------------------------------------+
```

### 3.2. Trang Dashboard Tổng quan của Người dùng

Đường dẫn truy cập: `/`

#### Phác thảo Giao diện

```
Tong quan
He thong quan tri va giam sat trang thai render video.  [+ Tao Video Moi]
-------------------------------------------------------------------------
+-------------------+ +-------------------+ +-------------------+ +-------------------+
| Tong Video        | | Dang xu lu        | | Cho Review        | | Ty le thanh cong  |
| 15                | | 2                 | | 1                 | | 86.7%             |
| Tat ca cac job    | | Dang chay pipeline| | Can duyet kich ban| | Thong ke toan t.g |
+-------------------+ +-------------------+ +-------------------+ +-------------------+

Video gan day                                               [ Refresh ]
+-----------------------------------------------------------------------+
| Media   | Tieu de                 | Trang thai    | L.Luong | H.Dong  |
|---------+-------------------------+---------------+---------+---------|
| [Thumb] | Huong dan mua sam       | Hoan thanh    | 02:15   | [Xem]   |
|         | 25/05/2026 14:00        |               |         | [Tai]   |
|---------+-------------------------+---------------+---------+---------|
| [Edit]  | Bao cao tai chinh Excel | Cho Review    | -       | [Review]|
|         | 25/05/2026 13:45        |               |         |         |
|---------+-------------------------+---------------+---------+---------|
| [Clock] | PowerPoint Gioi thieu   | Dang xu ly    | -       | [Loader]|
|         | 25/05/2026 13:30        |               |         |         |
|---------+-------------------------+---------------+---------+---------|
| [Alert] | Huong dan cai dat Git   | That bai      | -       | [Chi    |
|         | 25/05/2026 12:00        |               |         | tiet]   |
+-----------------------------------------------------------------------+
```

### 3.3. Hộp thoại Chi tiết Công việc (Job Detail Dialog)

Hiển thị khi click vào một hàng công việc trên bảng Dashboard.

#### Phác thảo Giao diện

```
+-----------------------------------------------------------------+
| Chi tiet Job                                            [ X ]   |
| job_8f9a2c4e-1234-5678-abcd-ef1234567890                        |
| --------------------------------------------------------------- |
| Trang thai: [ Hoan thanh ]                                      |
|                                                                 |
| Noi dung:                                                       |
| [ Huong dan tao va lam viec voi repositories tren Github     ]  |
|                                                                 |
| Tien trinh Pipeline:                                            |
| [Check] Phase 1: Scout (browser-use)                            |
| [Check] Phase 2: Parser (config + tts)                          |
| [Check] Phase 2.5: Review kich ban TTS                          |
| [Check] Phase 3: Tao am thanh TTS                               |
| [Loader] Phase 4: Injector (nhung pause)                        |
| [Circle] Phase 5: Ghi hinh (Webreel record)                     |
| [Circle] Phase 6: Composer (ffmpeg sync)                        |
|                                                                 |
| [ Chi tiet loi neu co: ... ]                                    |
|                                                                 |
| Tao luc: 25/05/2026 13:30:00  | Bat dau: 25/05/2026 13:30:05    |
| --------------------------------------------------------------- |
| [ Dong ]                                  [ Review ] [ Tai Video] |
+-----------------------------------------------------------------+
```

### 3.4. Trang Tạo mới Công việc (Create Video Page)

Đường dẫn truy cập: `/create`

Giao diện cho phép chọn loại nguồn tự động hóa, cấu hình các tùy chọn giọng nói và đẩy yêu cầu xử lý lên hệ thống.

#### Phác thảo Giao diện

```
Tao Video Moi
Cung cap y tuong hoac file trinh chieu, Agent se tu dong xu ly.
-------------------------------------------------------------------------
Cai dat Pipeline Video
Thieth lap loai cong viec va tham so cho AI Worker

Loai Video
+---------------+ +---------------+ +---------------+ +---------------+
| [Icon: Wand2] | | [Icon: Globe] | | [Icon: Pres.] | | [Icon: Mon.]  |
|    Tu dong    | |      Web      | |  Trinh chieu  | |   May tinh    |
+---------------+ +---------------+ +---------------+ +---------------+
( ) Dang nhan dien: WEB (Neu chon Tu dong va dang nhap prompt)

+-----------------------------------------------------------------------+
| [ BIEN MAU PHU - Tuy thuoc vao Loai Video da chon ]                   |
|                                                                       |
| 1. Neu chon "Trinh chieu":                                            |
| Tai len PowerPoint (.pptx): [ Chon Tep ] Co the keo tha tep pptx.     |
|                                                                       |
| 2. Neu chon "May tinh" (OS Automation):                               |
| Chon ung dung Windows:                                                |
| [ Excel ] [ Word ] [ PPT ] [ Chrome ] [ Edge ] [ Firefox ]            |
| [ Notepad ] [ Calculator ] [ Paint ]                                  |
|                                                                       |
| * Neu chon App Office (Excel, Word, PPT):                             |
|   Upload file co san (Tuy chon): [ Chon Tep ] (De trong de tao moi)   |
| * Neu chon App Browser (Chrome, Edge, Firefox):                       |
|   URL trang web: [ https://example.com___________________________ ]   |
| * Neu chon App don gian (Notepad, Calculator, Paint):                 |
|   Thong bao: Ung dung se tu dong khoi dong tren Worker Windows.       |
+-----------------------------------------------------------------------+

Prompt / Y tuong kich ban
[ Vi du: Huong dan tao bang tinh luong nhan vien tren Excel...         ]
[_______________________________________________________________________]

TTS Engine                Giong doc                 Do tre (ms)
[ Edge TTS        (v) ]   [ Hoai My (Nu)    (v) ]   [ 500         ]

[x] Bat Voice (TTS)       [x] Tam dung de Review Kich Ban

                                                             [ Tao Job ]
```

### 3.5. Biểu mẫu Phê duyệt Kịch bản (Phase 2.5 Review Panel)

Xuất hiện khi người dùng thực hiện duyệt lời thoại thoại AI của tác vụ đang ở trạng thái `pending_review`.

#### Phác thảo Giao diện

```
+-----------------------------------------------------------------+
| [DUYET DONG Y KICH BAN] job_8f9a2c4e                            |
| --------------------------------------------------------------- |
| Cau hinh chung: Edge TTS | Giong doc: Hoai My | Do tre: 500 ms  |
| --------------------------------------------------------------- |
| DANH SACH CAC BUOC THUYET MINH (EDITABLE STEPS)                 |
|                                                                 |
| Slide 1: [ Anh chup trang chu ]                                |
| Loi thoi AI khoi tao:                                           |
| [ "Chào mừng bạn đến với hướng dẫn sử dụng WebReel."        ]   |
| Sua lai thong tin:                                              |
| [ Chào mừng bạn đến với hướng dẫn sử dụng WebReel hệ thống mới. ]   |
|                                                                 |
| Slide 2: [ Anh chup nut dang ky ]                               |
| Loi thoi AI khoi tao:                                           |
| [ "Nhấp chuột vào nút Đăng ký ở góc trên bên phải màn hình." ]   |
| Sua lai thong tin:                                              |
| [_____________________________________________________________] |
|                                                                 |
| Slide 3: [ Anh chup dien thong tin ]                             |
| Loi thoi AI khoi tao:                                           |
| [ "Điền các thông tin bắt buộc và nhấn gửi."                 ]   |
| Sua lai thong tin:                                              |
| [_____________________________________________________________] |
|                                                                 |
| --------------------------------------------------------------- |
| [ Huy Job ]                             [ Luu nhap ] [ Duyet ]  |
+-----------------------------------------------------------------+
```

---

## 4. NHÓM GIAO DIỆN QUẢN TRỊ VIÊN (ADMIN DASHBOARD)

Nhóm giao diện dành riêng cho tài khoản có quyền Quản trị viên (Admin). Giúp quản trị hệ thống, quản lý người dùng, công việc, và giám sát tài khoản dịch vụ qua noVNC.

### 4.1. Trang Tổng quan Hệ thống (Admin Dashboard Page)

Đường dẫn truy cập: `/admin`

#### Phác thảo Giao diện

```
System Overview
Tong quan he thong va thong ke
-------------------------------------------------------------------------
+-------------------+ +-------------------+ +-------------------+ +-------------------+
| Tong nguoi dung   | | Tong Jobs         | | Phan bo goi cuoc  | | Quan tri vien     |
| 120               | | 1450              | | Free: 80, Pro: 30 | | 5                 |
| 115 Active, 5 Ban | | Tat ca nguoi dung | | Enterprise: 10    | | 115 Nguoi dung    |
+-------------------+ +-------------------+ +-------------------+ +-------------------+

Job Status Distribution                     Quick Stats
+---------------------------------------+   +---------------------------------------+
| Status            | Count             |   | Metric            | Value             |
|-------------------+-------------------|   |-------------------+-------------------|
| Completed         | 1200              |   | Total Users       | 120               |
| Failed            | 150               |   | Total Jobs        | 1450              |
| Processing        | 10                |   | Active Rate       | 95.8%             |
| Pending Review    | 90                |   |                   |                   |
+---------------------------------------+   +---------------------------------------+
```

### 4.2. Trang Quản lý Người dùng (Admin Users Page)

Đường dẫn truy cập: `/admin/users`

#### Phác thảo Giao diện

```
Quan ly nguoi dung
Quan ly nguoi dung va phan quyen
-------------------------------------------------------------------------
Tat ca nguoi dung
+-----------------------------------------------------------------------+
| Email         | Ten       | Vai tro   | Goi     | T.Thai | H.Muc| H.Dong  |
|---------------+-----------+-----------+---------+--------+------+---------|
| admin@wr.vn   | SysAdmin  | Admin     | Enterp. | Active | 0/Inf| [DoiGoi]|
|---------------+-----------+-----------+---------+--------+------+---------|
| user1@gmail   | Nguyen A  | User      | Pro     | Active | 45/50| [DoiGoi]|
|               |           |           |         |        |      | [Khoa]  |
|---------------+-----------+-----------+---------+--------+------+---------|
| user2@gmail   | Tran B    | User      | Free    | Locked | 12/10| [DoiGoi]|
|               |           |           |         |        |      | [Mo]    |
+-----------------------------------------------------------------------+

* Dialog Doi goi dich vu:
+------------------------------------------------------------+
| Cap nhat goi dich vu                                [ X ]  |
| Chon goi moi cho user1@gmail.com                           |
|                                                            |
| Goi hien tai: Pro                                          |
| Giong moi:                                                 |
| [ Free (100 video/thang)                               (v) ]|
|                                                            |
|                                         [ Huy ] [ Cap nhat]|
+------------------------------------------------------------+

* Truong hop Bam Khoa Nguoi dung:
- He thong hien thi Popup prompt nhap Ly do khoa tai khoan truoc khi thuc hien.
```

### 4.3. Trang Quản lý Công việc Hệ thống (Admin Jobs Page)

Đường dẫn truy cập: `/admin/jobs`

#### Phác thảo Giao diện

```
Tat ca cong viec
Tat ca jobs cua moi nguoi dung
-------------------------------------------------------------------------
Danh sach cong viec (50 jobs gan nhat)
+-----------------------------------------------------------------------+
| Ma cong viec  | Tieu de                 | Ma nguoi dung | T.Thai| Date|
|---------------+-------------------------+---------------+-------+-----|
| job_8f9a2c4e  | Huong dan mua sam       | usr_7a1b3c    | Comp. |25/05|
|---------------+-------------------------+---------------+-------+-----|
| job_3f2b4c1d  | Bao cao tai chinh       | usr_19d2f3    | Review|25/05|
|---------------+-------------------------+---------------+-------+-----|
| job_9e2d3f4a  | Loi trinh chieu PPTX    | usr_4f2a1b    | Failed|25/05|
+-----------------------------------------------------------------------+
```

### 4.4. Trang Quản lý Trình duyệt từ xa (Admin Browser Page)

Đường dẫn truy cập: `/admin/browser`

Màn hình này cho phép quản trị viên đăng nhập vào các tài khoản trực tuyến (như OneDrive, Outlook) trên các worker chuyên biệt bằng cách phát luồng noVNC trực tiếp.

#### Phác thảo Giao diện

```
Quan ly trinh duyet
Dang nhap vao OneDrive/Outlook de duy tri phien lam viec cua worker
-------------------------------------------------------------------------
+---------------------------------------+ +---------------------------------------+
| [Icon: Monitor] Presentation Worker   | | [Icon: Monitor] Web Worker            |
| Lan dang nhap cuoi: 24/05/2026 15:00  | | Lan dang nhap cuoi: 10/05/2026 09:00  |
| [ 1 ngay truoc ] [ Trang thai: OK ]   | | [ 15 ngay truoc ] [ CANH BAO HET HAN ]|
|                                       | | [ CANH BAO: Can dang nhap lai ngay! ] |
| [ Dang xem ]                          | | [ Xem trinh duyet ]                   |
+---------------------------------------+ +---------------------------------------+

Trinh duyet tu xa - Presentation Worker                      [ Refresh ]
+-----------------------------------------------------------------------+
| noVNC is served through Nginx proxy /novnc/.                          |
|                                                                       |
| +-------------------------------------------------------------------+ |
| | [Khung hinh iFrame hien thi Chromium tu xa dang chay tren Worker] | |
| |                                                                   | |
| |  Microsoft OneDrive Login Page:                                   | |
| |  Email: [_______________________________________________________] | |
| |  Password: [____________________________________________________] | |
| |                                                                   | |
| +-------------------------------------------------------------------+ |
|                                                                       |
| Sau khi dang nhap xong tren trinh duyet, bam nut de luu trang thai:   |
|                                              [ Danh dau da dang nhap ]|
+-----------------------------------------------------------------------+
```

### 4.5. Trang Quản lý Phiên làm việc (Admin Session Manager Page)

Đường dẫn truy cập: `/admin/session`

Trang quản lý phiên Chrome chính (Master Profile), cung cấp các cảnh báo ngắt mạch (Circuit Breaker) khi tài khoản của Worker bị đăng xuất đột ngột và cho phép đóng băng (Freeze) dữ liệu phiên làm việc.

#### Phác thảo Giao diện

```
Session Manager
Log in to Microsoft/Google here, then save & freeze for Workers to use
-------------------------------------------------------------------------
[ PHAT HIEN CANH BAO - NGAT MACH HOAT DONG (CIRCUIT BREAKER)          ]
[ Kênh queue "presentation-queue" da bi TAM DUNG do phien het han.     ]
[ Hay dang nhap lai o trinh duyet duoi, bam Save & Freeze va Resume.    ]
[ Danh sach queue tam dung:                                           ]
| - Presentation (OneDrive) [Paused]  [Ly do: Session Expired]  [Resume]|
-------------------------------------------------------------------------

Thong so phien he thong
+-------------------+ +-------------------+ +-------------------+ +-------------------+
| Status            | | Last Frozen       | | Archive Size      | | Circuit Breaker   |
| [ Ready ]         | | 25/05/2026 10:00  | | 345.20 MB         | | 1 queue paused    |
+-------------------+ +-------------------+ +-------------------+ +-------------------+

Trang thai cac hang doi (Queue Status)                      [ Refresh ]
+-----------------------------------------------------------------------+
| [Icon: PauseCircle] Presentation (OneDrive)     - [Paused]   [Resume] |
| [Icon: Play]        Web Tutorial                - [Running]           |
| [Icon: Play]        Presentation (Google)       - [Running]           |
| [Icon: Play]        Office (Slide-to-Video)     - [Running]           |
+-----------------------------------------------------------------------+

Save & Freeze Session
+-----------------------------------------------------------------------+
| Hay dam bao ban da dang nhap vao cac dich vu Microsoft va Google      |
| o trinh duyet ben duoi truoc khi luu.                [ Save & Freeze] |
+-----------------------------------------------------------------------+

Remote Browser (Session Manager)                             [ Refresh ]
+-----------------------------------------------------------------------+
| noVNC ket noi toi Session Manager Master Chrome Profile.              |
|                                                                       |
| +-------------------------------------------------------------------+ |
| | [Khung hinh iFrame hien thi Chromium tu xa cua Session Manager]   | |
| |                                                                   | |
| |  Microsoft Accounts / Google Accounts Dashboard                   | |
| |                                                                   | |
| +-------------------------------------------------------------------+ |
+-----------------------------------------------------------------------+
```
