# WebReel Docker & Server Security Hardening PRD

## 1. Mục tiêu

Thiết lập cơ chế bảo mật cấp độ Hạ tầng (Docker & VPS Server) nhằm mục đích:

- Cô lập các thành phần hệ thống để giảm thiểu rủi ro khi một container bị xâm nhập (Lateral Movement).
- Ngăn chặn tấn công leo thang đặc quyền (Privilege Escalation) từ bên trong container ra máy chủ Host.
- Phòng chống cạn kiệt tài nguyên (CPU, RAM, Disk Space) do log phình to hoặc rò rỉ bộ nhớ từ tiến trình Chrome.
- Bắt buộc áp dụng cơ chế tự hủy/ngừng khởi động nếu phát hiện mật khẩu yếu (Fail-safe credentials).

---

## 1.1 Hiện trạng Hệ thống (Baseline)

**Tất cả container tự viết đều chạy dưới quyền root (UID 0).** Không có Dockerfile nào khai báo `USER` directive.

| Container                | User hiện tại | Dockerfile              | Ghi chú                              |
| ------------------------ | ------------- | ----------------------- | ------------------------------------ |
| `api`                    | root          | `Dockerfile.backend`    | Không có `USER` directive            |
| `web-worker`             | root          | `Dockerfile.worker`     | Chrome chạy `--no-sandbox` dưới root |
| `presentation-worker`    | root          | `Dockerfile.worker`     | Tương tự web-worker                  |
| `presentation-gg-worker` | root          | `Dockerfile.worker`     | Tương tự web-worker                  |
| `office-worker`          | root          | `Dockerfile.backend`    | Không cần Chrome                     |
| `autoscaler`             | root          | `Dockerfile.autoscaler` | Mount `docker.sock`, rủi ro cao nhất |
| `session-manager`        | root          | `Dockerfile.worker`     | Chrome + VNC dưới root               |
| `frontend`               | nginx         | Nginx image             | Image chính thức, tương đối an toàn  |
| `mongodb`                | mongodb       | `mongo:7`               | Image chính thức tự handle non-root  |
| `redis`                  | redis         | `redis:7-alpine`        | Image chính thức tự handle non-root  |

**Hệ quả của việc chạy root:** Root bypass toàn bộ kiểm tra quyền file. Mọi process ghi file ở bất kỳ đâu đều thành công. Khi chuyển sang non-root, bất kỳ thư mục nào không được `chown` đúng sẽ gây lỗi `Permission Denied`.

**Mạng hiện tại:** Tất cả container chạy chung 1 Docker default network. Bất kỳ container nào cũng có thể truy cập trực tiếp mọi container khác.

**Ports hiện tại đang expose ra ngoài:**

- `3000` (frontend/Nginx)
- `8000` (API, truy cập trực tiếp)
- `6080` (noVNC)
- `5900` (VNC raw)
- `8001` (session-manager internal API)

---

## 1.2 Khả năng Test Local (Windows/Docker Desktop)

> **Kết luận: Task 1-5 hoàn toàn áp dụng được trên local. Task 6 chỉ chạy được trên Linux VPS.**

- Frontend Nginx đã proxy API qua port `3000:80`, nên dồn cổng hoạt động bình thường trên local. Không cần port 80 (đang bị chiếm).
- Docker Desktop trên Windows hỗ trợ đầy đủ: non-root user, network isolation, `security_opt`, `cap_drop`, log rotation.
- Task 6 (iptables Cloudflare) dùng `iptables` + chain `DOCKER-USER`, chỉ tồn tại trên Linux kernel. Bỏ qua khi test local.
- Fail-safe credential check (Task 5): Local mặc định `ENVIRONMENT` không phải `production` nên sẽ chỉ log WARNING, không crash.

---

## 2. Threat Model

### 2.1 Container Escape (Thoát container)

- **Mối đe dọa:** Hacker khai báo payload tấn công thông qua mã nguồn Python hoặc Chrome sandbox để chiếm quyền root trên máy chủ Host.
- **Điểm yếu hiện tại:** Các container (`api`, `worker`) chạy bằng quyền `root` mặc định. Các Worker chạy Chromium yêu cầu cờ `--no-sandbox`.

### 2.2 Lateral Movement (Tấn công leo thang mạng nội bộ)

- **Mối đe dọa:** Hacker chiếm quyền kiểm soát Container Frontend (web server tĩnh) rồi từ đó trực tiếp tấn công/quét cổng Database (MongoDB) hoặc hàng đợi (Redis).
- **Điểm yếu hiện tại:** Toàn bộ container cùng chạy chung một Docker network mặc định và không có lớp chặn tường lửa nội bộ.

### 2.3 Host Takeover via Docker Socket

- **Mối đe dọa:** Container `autoscaler` nắm giữ file socket `/var/run/docker.sock` của Host. Nếu container này bị chiếm quyền, Hacker có thể tạo ra các container root khác để ghi đè file hệ thống của VPS.
- **Điểm yếu hiện tại:** `autoscaler` chạy bằng quyền root mặc định trong container.

### 2.4 Credential Exposure & Weak Passwords

- **Mối đe dọa:** Khi deploy lên môi trường Production, quản trị viên quên đổi mật khẩu MongoDB/Redis, sử dụng lại các mật khẩu mặc định của file template.

---

## 3. Yêu cầu Thiết kế & Triển khai

### 3.1 Cấu hình Người dùng Non-root

- Tạo user hệ thống `webreel` (UID/GID = 1000) trong tất cả Dockerfiles.
- Thay đổi quyền sở hữu (ownership) các thư mục ứng dụng `/app` và `/app/output` thành `webreel:webreel`.
- Tiến trình khởi động trong entrypoint chạy các tác vụ cài đặt ban đầu (như VNC, Xvfb) dưới quyền root, sau đó bắt buộc hạ quyền xuống user `webreel` để vận hành Worker/API.

### 3.2 Cô lập Mạng nội bộ (Docker Networks)

Tách hệ thống thành 3 mạng độc lập trong `docker-compose.prod.yml`:

1. **`frontend-net`**: Kết nối giữa `frontend` và `api`.
2. **`backend-net`**: Kết nối giữa `api`, `autoscaler`, `workers` (web, presentation, office) và `redis`.
3. **`db-net`**: Kết nối giữa `api`, `workers` với `mongodb` và `redis`.

- _Lưu ý:_ `frontend` tuyệt đối không được cấu hình tham gia vào mạng `db-net`.
- Các Worker do Autoscaler tạo ra sẽ tự động thừa hưởng cấu hình mạng được định nghĩa sẵn trong Compose dịch vụ tương ứng.

### 3.3 Giới hạn Đặc quyền & Tài nguyên Container

- Áp dụng chỉ thị `security_opt: [no-new-privileges:true]` cho toàn bộ dịch vụ.
- Đối với Chromium Worker: Tước bỏ toàn bộ đặc quyền Linux thông qua chỉ thị `cap_drop: [ALL]`. Vận hành Chromium với cờ `--no-sandbox` dưới quyền user `webreel` thay vì cấp quyền `SYS_ADMIN`.
- Cấu hình Log Rotation toàn cục trong `docker-compose.prod.yml`:
  ```yaml
  logging:
    driver: "json-file"
    options:
      max-size: "10m"
      max-file: "3"
  ```
- Cấu hình giới hạn CPU cho các Worker (`cpus: "2.0"`) và giới hạn bộ nhớ RAM để tránh tình trạng chiếm dụng tài nguyên máy chủ.

### 3.4 Bảo mật Autoscaler (Docker Socket Protection)

- **Autoscaler chạy non-root** (user `webreel`, UID 1000) và **không mount trực tiếp** `/var/run/docker.sock`.
- Thay vào đó, sử dụng **Docker Socket Proxy** (`tecnativa/docker-socket-proxy`) làm lớp trung gian, chỉ cho phép các Docker API endpoint cần thiết:
  - `CONTAINERS: 1` - Liệt kê, tạo, khởi động, dừng, xóa container (cần cho autoscaler)
  - `INFO: 1` - Thông tin Docker engine (docker compose cần)
  - `IMAGES: 1` - Kiểm tra image tồn tại (docker compose cần)
  - `POST: 1` - Cho phép request POST (tạo/dừng container)
  - Tất cả quyền nguy hiểm bị tắt: `EXEC=0`, `VOLUMES=0`, `BUILD=0`, `NETWORKS=0`, `SYSTEM=0`
- Autoscaler áp dụng thêm:
  - `read_only: true` + `tmpfs: [/tmp]` - Filesystem chỉ đọc, kẻ tấn công không thể sửa code
  - `cap_drop: [ALL]` - Tước bỏ toàn bộ Linux capabilities
  - `no-new-privileges: true` - Ngăn leo thang đặc quyền
- Docker Socket Proxy nằm trong mạng riêng `docker-proxy-net` (internal, không có internet), chỉ autoscaler mới truy cập được.
- Không khai báo bất kỳ cổng mạng `ports` nào cho container `autoscaler` hay `docker-socket-proxy`.
- **Kết quả:** Kể cả khi autoscaler bị chiếm quyền hoàn toàn, kẻ tấn công không thể tạo container privileged, mount filesystem host, exec vào container khác, hay sửa đổi code autoscaler.

### 3.5 Ràng buộc mật khẩu Production (Fail-safe)

- Bổ sung đoạn mã kiểm tra (Startup validation) tại `backend/main.py`:
  - Khi biến môi trường `ENVIRONMENT=production`, hệ thống sẽ kiểm tra xem `MONGO_PASSWORD` và `REDIS_PASSWORD` có trùng với các giá trị mặc định của hệ thống hay không (ví dụ: `webreel_mongo_2026`, `webreel_secret_2026`).
  - Nếu trùng, ghi log mức cảnh báo khẩn cấp `CRITICAL` và thoát chương trình lập tức (`sys.exit(1)`).

### 3.6 Cấu hình dồn cổng và Reverse Proxy Nginx

- Gỡ bỏ toàn bộ ports của backend API (8000), session-manager (6080, 5900, 8001) khỏi `docker-compose.prod.yml`.
- Giữ nguyên mapping `3000:80` cho container frontend (Nginx). Port 80 trên host không bắt buộc vì local có thể đang bị chiếm.
- Cấu hình Nginx proxy các yêu cầu `/novnc/` đến `session-manager:6080` bao gồm nâng cấp kết nối WebSocket.
- Khôi phục IP thực tế của client từ header `CF-Connecting-IP` của Cloudflare bằng module `real_ip` trong Nginx.
- Cập nhật `/admin/novnc-url` trong `backend/admin_routes.py` trả về relative path để chạy trực tiếp trên cổng Nginx.

### 3.7 Script Tường lửa iptables Cloudflare trên Host

- Viết script `scripts/setup-cloudflare-firewall.sh` chạy trên host để kiểm soát truy cập vào cổng expose của Docker thông qua chain `DOCKER-USER`.
- Hỗ trợ cơ chế bật/tắt:
  - `enable`: Tự động tải dải IP của Cloudflare (IPv4 & IPv6), thiết lập luật cho phép dải IP này và## 5. Kế hoạch Triển khai (Vertical Slices Tasks)

### Task 1: Cấu hình dồn cổng và Reverse Proxy Nginx cho noVNC & Cloudflare Real IP [HOAN THANH - 2026-05-22]

- **Mô tả:** Gỡ bỏ các cấu hình `ports` của backend API và session-manager trong `docker-compose.prod.yml`. Thêm cấu hình proxy đường dẫn `/novnc/` và WebSocket upgrade vào `frontend/nginx.conf`. Đồng thời cấu hình module `real_ip` trong Nginx để nhận diện IP thực của client từ header `CF-Connecting-IP`.
- **Kiểm thử:** Khởi động docker-compose ở local, kiểm tra xem có thể truy cập frontend, backend, và giao diện noVNC trực tiếp qua cổng duy nhất của Nginx (`localhost:3000`). Các cổng 8000, 6080, 5900 phải được đóng hoàn toàn từ bên ngoài.
- **Lưu ý Local:** Port `3000:80` giữ nguyên, không cần port 80 trên host. `session-manager` phải tham gia `frontend-net` để Nginx resolve được hostname `session-manager`.

### Task 2: Cập nhật API /admin/novnc-url và tích hợp Iframe Dashboard [HOAN THANH - 2026-05-22]

- **Mô tả:** Cập nhật API `/admin/novnc-url` trong `backend/admin_routes.py` để trả về relative path `/novnc/vnc.html...` thay vì localhost cố định.
- **Kiểm thử:** Truy cập Admin Dashboard từ trình duyệt (`localhost:3000`), bấm vào nút mở cửa sổ điều khiển và xác nhận iframe tải noVNC thành công, kết nối mượt mà qua cổng Nginx mà không cần SSH tunnel.

### Task 3: Cấu hình User Non-root, phân quyền và giới hạn đặc quyền (Capabilities) cho Worker/API [HOAN THANH - 2026-05-23]

- **Mô tả:** Cập nhật `Dockerfile.backend` và `Dockerfile.worker` để tạo và chạy dưới user `webreel` (UID/GID 1000). Cấu hình `scripts/docker-entrypoint.sh` khởi chạy VNC/Xvfb bằng `gosu webreel` sau khi dọn dẹp file rác dưới quyền root. Cập nhật `docker-compose.prod.yml` bổ sung `security_opt: [no-new-privileges:true]`, `cap_drop: [ALL]` cho các Chromium Workers và giới hạn CPU/RAM/Log Rotation.
- **Kiểm thử:** Chạy lệnh `docker exec -it <container_id> whoami` trả về `webreel` và xác nhận các tiến trình VNC/Chrome hoạt động ổn định dưới user non-root.
- **Giải quyết đường dẫn Chrome:** Cập nhật `scripts/session-manager-start.sh` tự động phát hiện đường dẫn Chrome (hỗ trợ `chromium-1223` hoặc các phiên bản khác trong `/opt/pw-browsers/chromium-*/chrome-linux64/chrome`) để đảm bảo không bị lỗi hardcode đường dẫn khi nâng cấp Playwright.
- **Kết quả kiểm thử:**
  - API và Autoscaler chạy dưới user `webreel` (UID 1000).
  - Chrome trong `session-manager` chạy dưới user `webreel` thông qua `gosu`.
  - Cấu hình Log rotation và `no-new-privileges` được áp dụng thành công.
  - Tất cả API endpoint, noVNC proxy hoạt động hoàn hảo.

#### Tiến độ thực hiện (2026-05-22 ~ 2026-05-23)

**Các file đã sửa:**

1. **`Dockerfile.backend`** - HOÀN THÀNH
2. **`Dockerfile.worker`** - HOÀN THÀNH
3. **`scripts/docker-entrypoint.sh`** - HOÀN THÀNH
4. **`scripts/session-manager-start.sh`** - HOÀN THÀNH (Đã sửa tìm kiếm Chrome binary tự động và bọc bảo vệ)
5. **`docker-compose.prod.yml`** - HOÀN THÀNH (Đã fix YAML + socket proxy)
6. **`Dockerfile.autoscaler`** - HOÀN THÀNH

**Kết quả test thực tế:**

| Container                 | `whoami`                          | PID 1 user | Trạng thái                                    |
| ------------------------- | --------------------------------- | ---------- | --------------------------------------------- |
| `webreel-api`             | `webreel`                         | `webreel`  | PASS - API hoạt động bình thường              |
| `webreel-session-manager` | root (VNC) / webreel (Chrome/API) | `webreel`  | PASS - Xvfb/VNC/noVNC + Chrome + API chạy tốt |
| `webreel-autoscaler`      | `webreel`                         | `webreel`  | PASS - Kết nối qua Docker socket proxy        |

#### Vấn đề kỹ thuật gặp phải (Đã giải quyết)

- **Vấn đề 1: `docker exec whoami` trả về `root` dù process chạy `webreel`** -> Đã giải quyết bằng cách dùng `user: "1000:1000"`.
- **Vấn đề 2: `cap_drop: ALL` khiến entrypoint root không thể thực hiện cleanup** -> Đã giải quyết bằng cách dùng `cap_drop: ALL` + `cap_add` (SETUID, SETGID, CHOWN, FOWNER, KILL, DAC_OVERRIDE).
- **Vấn đề 3: File `docker-compose.prod.yml` bị hỏng cấu trúc YAML** -> Đã giải quyết (tách `logging:` ra khỏi `cap_add:` ở đúng level).
- **Vấn đề 4: Đường dẫn Chrome bị hardcode trong `session-manager-start.sh`** -> Đã giải quyết bằng cách dò tìm dynamic qua glob pattern `chromium-*/chrome-linux64/chrome`.

#### 5.1 Hardening Autoscaler bằng Docker Socket Proxy [HOÀN THÀNH - 2026-05-23]

- Đã tách autoscaler khỏi file socket vật lý, chạy non-root qua cổng proxy 2375.
- Đã test và xác nhận các API nguy hiểm (`/volumes`, `/networks`) đều trả về **403 Forbidden** như thiết kế.

### Task 4: Thiết lập cô lập mạng nội bộ (Docker Networks) và cấu hình Autoscaler [HOÀN THÀNH - 2026-05-23]

- **Mô tả:** Khai báo 3 mạng `frontend-net`, `backend-net`, và `db-net` trong `docker-compose.prod.yml` và gắn các container vào đúng mạng như thiết kế. Cho phép container `autoscaler` chạy quyền root trong mạng `backend-net` để quản lý `docker.sock` ổn định. Cho phép `session-manager` tham gia cả `frontend-net` và `backend-net`.
- **Kiểm thử:** Đứng từ container `frontend` ping sang `mongodb` hoặc `redis` báo lỗi không tìm thấy host hoặc kết nối bị từ chối do khác mạng.
- **Lưu ý quan trọng - Ma tran mang can thiet:**
  - `frontend`: `frontend-net` (KHONG duoc vao `db-net` hay `backend-net`)
  - `api`: `frontend-net` + `backend-net` + `db-net` (cau noi giua frontend va backend)
  - `workers` (web, presentation, office, presentation-gg): `backend-net` + `db-net`
  - `autoscaler`: `backend-net` (chi can Redis, KHONG can MongoDB)
  - `session-manager`: `frontend-net` + `backend-net` (Nginx proxy can resolve hostname)
  - `redis`: `backend-net` + `db-net`
  - `mongodb`: `db-net`
- **Kết quả kiểm thử thực tế:**
  - `webreel-frontend` ping `mongodb` / `redis` thất bại do không tìm thấy host -> ✅ Thành công cô lập.
  - `webreel-frontend` ping `api` / `session-manager` thành công -> ✅ Hoạt động bình thường.
  - `webreel-autoscaler` phân giải DNS `mongodb` thất bại, kết nối `redis` và `docker-socket-proxy` thành công.
  - `webreel-presentation-worker` tự động tạo động bởi autoscaler tham gia đúng mạng và thực thi job thành công.

### Task 5: Ràng buộc kiểm tra mật khẩu Production (Fail-safe credentials) [HOAN THANH - 2026-05-23]

- **Mô tả:** Thêm đoạn mã kiểm tra trong sự kiện lifespan tại `backend/main.py`. Nếu `ENVIRONMENT=production` và các mật khẩu `MONGO_PASSWORD` hoặc `REDIS_PASSWORD` trùng với giá trị mặc định, ghi log mức `CRITICAL` và dừng chương trình (`sys.exit(1)`).
- **Kiểm thử:** Đặt `ENVIRONMENT=production`, giữ nguyên mật khẩu mặc định, khởi động API và xác nhận container tự crash kèm theo thông báo lỗi rõ ràng.

### Task 6: Script Tường lửa iptables Cloudflare trên Host

- **Mô tả:** Tạo file shell script `scripts/setup-cloudflare-firewall.sh` hỗ trợ hai tham số `enable` và `disable`. Tải tự động danh sách IP của Cloudflare và áp dụng luật lọc vào chain `DOCKER-USER` cấp host để bảo vệ cổng expose của Nginx.
- **Kiểm thử:** Chạy script với `enable`/`disable` và kiểm tra bảng rules iptables trên VPS để đảm bảo chỉ cho phép IP Cloudflare/Local truy cập vào cổng Docker expose.
- **CHI AP DUNG TREN LINUX VPS.** `iptables` va chain `DOCKER-USER` khong ton tai tren Windows/Docker Desktop. Bo qua task nay khi test local.

---

## 6. Nguyên tắc Đảm bảo Không Ảnh hưởng Ứng dụng (Zero Regression Principles)

Để đảm bảo quá trình gia cố bảo mật không làm gián đoạn hay phát sinh lỗi cho các tính năng hiện tại của WebReel, quá trình phát triển và cấu hình phải tuân thủ các nguyên tắc sau:

1. **Bảo toàn quyền hạn Hệ thống tập tin (File Permissions):**
   - Khi chuyển sang chạy dưới user non-root `webreel`, toàn bộ các lệnh ghi file của Chrome profile (`/tmp/worker_profile`), các file locks của VNC, và đặc biệt là thư mục chứa video đầu ra (`/app/output`) phải được cấp quyền đọc/ghi chính xác cho user `webreel`.
   - Kiểm thử thực tế bằng cách chạy thử một job render video hoàn chỉnh và kiểm tra file đầu ra được tạo ra thành công mà không gặp lỗi Permission Denied.
   - **Checklist `chown` bat buoc trong Dockerfile:**
     ```dockerfile
     RUN groupadd -g 1000 webreel && useradd -u 1000 -g webreel -m webreel
     RUN chown -R webreel:webreel /app /app/output
     RUN mkdir -p /tmp/worker_profile && chown webreel:webreel /tmp/worker_profile
     ```
   - **Checklist `chown` bat buoc trong entrypoint (runtime):**
     ```bash
     # Chay duoi root truoc khi ha quyen
     mkdir -p /tmp/.X11-unix && chmod 1777 /tmp/.X11-unix
     mkdir -p /tmp/worker_profile && chown webreel:webreel /tmp/worker_profile
     # Ha quyen
     exec gosu webreel "$@"
     ```
2. **Duy trì độ ổn định của noVNC (WebSocket Connection):**
   - Đảm bảo cấu hình proxy `/novnc/` trên Nginx xử lý chính xác giao thức nâng cấp WebSocket (`Upgrade`, `Connection`). Kết nối WebSocket từ trình duyệt của Admin đến websockify trong container không được bị gián đoạn hay timeout bất thường.
   - **Cau hinh Nginx toi thieu:**
     ```nginx
     location /novnc/ {
         proxy_pass http://session-manager:6080/;
         proxy_http_version 1.1;
         proxy_set_header Upgrade $http_upgrade;
         proxy_set_header Connection "upgrade";
         proxy_read_timeout 86400s;
     }
     ```
3. **Đồng bộ hóa kết nối mạng nội bộ (Network Reachability):**
   - Mặc dù tách biệt các container vào các mạng Docker khác nhau để cô lập, các container cần thiết (như `api`, `workers`) vẫn phải được khai báo tham gia đồng thời vào các mạng cần thiết (ví dụ `backend-net`, `db-net`) để không làm mất kết nối tới `redis` hay `mongodb`.
4. **Cô lập logic Fail-safe trong môi trường Development:**
   - Cơ chế tự dừng chương trình (`sys.exit(1)`) khi phát hiện mật khẩu mặc định chỉ được phép kích hoạt khi biến môi trường `ENVIRONMENT=production`. Trong môi trường local development, hệ thống chỉ ghi log cảnh báo mức `WARNING` mà không làm crash chương trình, đảm bảo nhà phát triển vẫn có thể chạy thử local một cách thuận tiện.
5. **Khong anh huong Disk I/O cua Docker Volume:**
   - Volume `output_data` duoc mount vao `/app/output`. Khi chuyen non-root, volume nay van giu nguyen data cu. Can dam bao user `webreel` (UID 1000) co quyen ghi vao volume nay. Neu volume da co data cu tao boi root, can chay `chown -R 1000:1000` trong entrypoint mot lan.
