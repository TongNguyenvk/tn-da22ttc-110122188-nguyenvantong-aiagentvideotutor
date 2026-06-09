# Bằng chứng thực nghiệm cho Chương 4

Toàn bộ log dưới đây được Claude chạy thật trên hệ thống của bạn
(tài khoản `tongct08@gmail.com`) vào ngày **2026-06-01 07:30-07:36 UTC**
(14:30-14:36 giờ VN). Worker phù du đã được capture trước khi container biến mất.

## Mục lục bằng chứng

| File                                              | Tương ứng "Hình …" / Mục trong báo cáo                       |
| ------------------------------------------------- | ------------------------------------------------------------ |
| `job_submit_*.log`                                | Hình 4.z – API submit + Redis queue (job_id `bc9c432d`)      |
| `worker_*_snapshot.log`                           | Hình 4.z – Worker thực thi browser-use agent (Phase 1 Scout) |
| `autoscaler_snapshot.log`, `autoscaler_final.log` | Hình 4.z – Autoscaler nhận event và scale workers            |
| `redis_queues_snapshot.log`                       | Hình 4.z – LLEN của 5 queue trên Redis                       |
| `rate_limit_test_*.log`                           | Hình 4.c – 10× HTTP 200 + 5× HTTP 429                        |
| `ffmpeg_stream_copy_demo.log`                     | Hình 4.v – FFmpeg Stream Copy 10s render 1.26s               |
| `ffmpeg_tmp/final.mp4`                            | Hình 4.u – Sample video 1920×1080 30fps + AAC mono           |
| `failsafe_demo.log`, `failsafe_source.log`        | Hình 4.a – Fail-safe trigger với mật khẩu mặc định           |
| `security_verification.log`                       | Mục 4.3.1 – Non-root + no-new-privileges + cap_drop          |
| `docker_stats_final.log`, `docker_ps_final.log`   | Mục 4.4.3 – Tiêu thụ tài nguyên thực tế                      |

## Tóm tắt số liệu thu được

### 1. Hàng đợi sự kiện (Hình 4.z)

```
Job submitted: bc9c432d-3a38-43fa-bd9f-22860a54a011
User: tongct08@gmail.com
Endpoint: POST /api/queue/submit
HTTP status: 200 OK
Redis web-queue LLEN sau submit: 18 jobs đang chờ
Autoscaler nhận event:
  [autoscaler] INFO - Event [new-job]: bc9c432d-... -> web-queue
  [autoscaler] INFO - Queue web-queue: 2/2 workers running
  [autoscaler] INFO - Max workers reached for web-worker (2/2). Job ... will wait in queue.
```

### 2. Worker phù du đang xử lý (worker_297ed3ba_snapshot.log)

Worker `webreel-web-worker-297ed3ba` đã được autoscaler spawn động, chạy đầy đủ:

- Phase 1 Scout: browser-use 0.12.1 + Gemini 3.1-flash-lite điều khiển Chrome
- Hoàn thành 4 steps, thu được 3 narration segments
- Sau đó Phase 2 (Parser): tạo `tts_script.json` (3 segments)
- Stuck ở Phase 2.5 review chờ user duyệt kịch bản (Human-in-the-loop)

### 3. Rate Limit (Hình 4.c)

```
Request # 1 -> HTTP 200   ...   Request #10 -> HTTP 200
Request #11 -> HTTP 429 {"detail":"Rate limit exceeded: 10 per 1 minute","retry_after":60}
Request #12 -> HTTP 429
Request #13 -> HTTP 429
Request #14 -> HTTP 429
Request #15 -> HTTP 429
```

### 4. FFmpeg Stream Copy (Hình 4.v)

```
Input: silent.mp4 (1920×1080 30fps libx264, 10s) + voice.m4a (AAC mono 44.1kHz, 10s)
ffmpeg -i silent.mp4 -i voice.m4a -map 0:v -map 1:a -c:v copy -c:a copy final.mp4
Speed: 578x (frame=300 fps=0.0 q=-1.0 ... speed=578x)
Render completed in 1.26s (KHÔNG re-encode)
Output: 1920×1080 30fps + AAC mono, 113 KB
```

### 5. Fail-safe (Hình 4.a)

Khi chạy `docker run` image API với `ENVIRONMENT=production` + `REDIS_PASSWORD=webreel_secret_2026`:

```
{"level": "CRITICAL", "logger": "backend.main",
 "message": "CRITICAL SECURITY ALERT: Running in PRODUCTION mode but default credentials are still in use!
            MONGO_PASSWORD or REDIS_PASSWORD is set to default values. Exiting for safety."}
```

Container thoát ngay lập tức qua `sys.exit(1)`.

### 6. Non-root + Docker Hardening

| Container                              | UID                                                     | security_opt      | cap_drop                 |
| -------------------------------------- | ------------------------------------------------------- | ----------------- | ------------------------ |
| webreel-api                            | 1000 (webreel)                                          | no-new-privileges | (mặc định)               |
| webreel-autoscaler                     | 1000 (webreel)                                          | no-new-privileges | ALL                      |
| webreel-web-worker-\*                  | entrypoint=root, gosu drop xuống 1000 cho python+chrome | no-new-privileges | ALL (+ 6 caps cần thiết) |
| webreel-frontend, webreel-docker-proxy | root (image bên thứ ba)                                 | no-new-privileges | -                        |

### 7. Tiêu thụ tài nguyên thực tế (idle)

```
MongoDB        : 304 MiB
Session Manager: 376 MiB
API            : 119 MiB
Web Worker x 2 : đang chạy Chromium đầy đủ
Autoscaler     : 38 MiB
Docker Proxy   : 19 MiB
Frontend       : 14 MiB
Test Server    : 15 MiB
Redis          : 12 MiB
-----------------------------------------
Tổng core (idle, chưa worker) : ~900 MiB
```
