# Audio/Video Sync Bất Đồng Bộ Trên Prod — Phân Tích & Fix

**Ngày**: 2026-05-27 (R1) → 2026-05-28 (R2A) → 2026-05-28 (Hotfix CDP) → 2026-05-28 (Hotfix narration) → 2026-05-28 (R2A2 — frame-leak)
**Phạm vi**: presentation-gg-worker (và web/presentation worker liên đới) khi chạy trên `docker-compose.prod.yml` với mô hình ephemeral worker (`docker compose run -d --rm`, single-job, auto-scaler).
**Trạng thái**:

- Round 1 (patch worker config): ĐÃ APPLY — không đủ.
- Round 2A (sửa Webreel core, bỏ frameSlots cap): ĐÃ APPLY — giảm drift nhưng chưa hết.
- Hotfix CDP short-circuit: ĐÃ APPLY.
- Hotfix duplicate narration: ĐÃ APPLY.
- **R2A2 (frame-leak fix — `lastFrameTime` set sau write)**: ĐÃ APPLY — chờ rebuild image + retest.
- Backend default `padding_ms` 300 → 1000 + worker env-priority: ĐÃ APPLY.
- Round 2B (frame_index trong trace): chưa làm.

---

## 1. Hiện tượng

- Local (Windows headed): audio + video sync chuẩn, không overlap.
- Prod (Docker ephemeral worker): audio các slide gối lên nhau, không bám timeline; thêm offset bằng tay cũng không cải thiện.
- Bắt đầu xảy ra **sau khi chuyển sang mô hình "phù du"** (mỗi job = 1 container `--rm` riêng, không dùng worker thường trực).

---

## 2. Kiến trúc sync hiện tại (tóm tắt)

Pipeline 6 phase tại `webreel-ai-agent/desktop_app/pipeline.py`, được `worker/presentation_gg_worker.py:242` gọi qua `run_pipeline_v3`:

| Phase       | Mục đích                                                                           | File chính                                                            |
| ----------- | ---------------------------------------------------------------------------------- | --------------------------------------------------------------------- |
| 1 Scout     | browser-use agent thao tác trên Google Slides                                      | `pipeline.py:phase1_scout`                                            |
| 2 Parser    | history → webreel config + tts_script                                              | `bu_to_webreel.py:convert_history_to_config_and_script`               |
| 3 TTS       | Sinh MP3 + đo duration bằng ffprobe                                                | `audio_injector.py:23`                                                |
| 4 Injector  | Thay `[NARRATION:idx]` pause placeholder bằng `duration + padding_ms`              | `audio_injector.py:83`                                                |
| 5 Execution | Webreel CLI (Node) phát lại + ghi video + xuất `.webreel/traces/<name>.trace.json` | `webreel_runner.py:158`, `packages/webreel/src/lib/runner.ts:320-578` |
| 6 Composer  | Đọc trace, đặt audio bằng `ffmpeg anullsrc + concat + amix`                        | `desktop_app/trace_composer.py`                                       |

Sync hoạt động trên **giả định cốt lõi**: `trace.start_time_ms` (wall-clock Node) ≈ thời điểm khung hình tương ứng trong file video.

---

## 3. Phân tích nguyên nhân (theo thứ tự nghiêm trọng)

### A. Trace là wall-clock, video không follow wall-clock một cách tuyến tính

`packages/webreel/src/lib/runner.ts:328,333,546` ghi:

```ts
const recordingStartTime = Date.now();
const stepStartMs = Date.now() - recordingStartTime;
```

Wall-clock thuần.

Trong khi `packages/@webreel/core/src/recorder.ts:163` ghi hình bằng vòng lặp `Page.captureScreenshot` (JPEG q=60) → push qua stdin của `ffmpeg -vsync cfr`. Khi capture chậm, code cố nhân đôi frame để bù:

```ts
const frameSlots = Math.min(600, Math.max(1, Math.round(elapsed / this.frameMs)));
```

Vấn đề: cơ chế bù **chỉ hoạt động khi loop còn quay đều**. Trong prod ephemeral worker:

- `TARGET_FPS = 60` (`packages/@webreel/core/src/types.ts:73`) → mỗi ~16.7ms phải có 1 capture.
- Có timeout 2000ms/screenshot, `consecutiveErrors >= 30` thì **abort recording** (`recorder.ts:222`).
- 2 vCPU + software-rendering Chrome trong Xvfb (`+extension GLX +render`, **không GPU**) khiến screenshot có lúc tốn 80–300ms.
- `await this.writeFrame(buffer)` chờ ffmpeg drain → khi libx264 chậm (ultrafast preset vẫn ngốn CPU lúc encode đoạn slide có animation), loop dừng → wall-clock vẫn chạy, video frames mất khoảng tương ứng.

⇒ Video thật ngắn hơn trace, và rút ngắn **không đồng đều** theo thời gian.

### B. `speed_factor` chỉ scale tuyến tính, không sửa được drift phi tuyến

`desktop_app/trace_composer.py:317-324`:

```python
speed_factor = video_duration_ms / trace_duration_ms
timestamps = [int(ts * speed_factor) for ts in timestamps]
```

Là "critical fix" cho Docker frame-drop, nhưng chỉ đúng nếu video bị compress **đều đặn**. Thực tế drift tập trung vào:

- Vài giây đầu (Chrome warm-up, presentation mode load).
- Đoạn animation slide-transition của Google Slides.
- Đoạn cuối khi worker chuẩn bị shutdown.

Khi áp `speed_factor` toàn cục, các narration giữa/cuối bị đẩy về trước sai vị trí thực tế trong video → audio slide 3 vang lên khi vẫn đang show slide 2 → chồng nhau.

### C. Khi scale timestamp, audio KHÔNG được scale → tràn sang narration kế tiếp

`trace_composer.py:336-372` chỉ scale `timestamps` (vị trí đặt). File MP3 vẫn nguyên duration gốc. Nếu `speed_factor = 0.7`:

- Narration 0 đặt ở 0ms (dài 8000ms).
- Narration 1 đặt ở 8400ms (scaled từ 12000ms).
- `8000 + 800ms buffer = 8800 > 8400` → "prevent overlap" (line 251-256) đẩy narration 1 lên 8800ms.
- Nhưng video tại 8800ms có thể đã sang slide 4 → audio slide 2 vang trên slide 4.

Đây chính là **"audio gối lên nhau và không theo timeline"** user mô tả.

### D. `padding_ms = 300` trong worker quá nhỏ cho Docker

`presentation_gg_worker.py:249` (cũ) truyền `padding_ms=300`. Default `inject_exact_pauses` là 800ms (`audio_injector.py:87`). Trong môi trường drift, padding nhỏ = không có buffer hấp thụ jitter — ArrowRight bấm trước khi audio kết thúc.

Khi user "thêm offset" mà không đụng vào `padding_ms` này thì offset chỉ dịch toàn cục, **không** mở rộng cửa sổ im lặng trong webreel config.

### E. Ephemeral worker = không có warm-up giữa các job

Worker chạy `--rm` single-job (`presentation_gg_worker.py:381`). Mỗi job:

1. Container mới → Xvfb cold-start.
2. `tar -xzf master_profile.tar.gz` (entrypoint dòng 166) → I/O burst.
3. Chrome launch với 50+ flag disable.
4. Browser-use agent load model, mở Google Slides.
5. **Ngay sau đó** vào phase 5 recording.

Phase 5 bắt đầu khi container vẫn đang ấm hóa → JPEG capture loop chậm đúng vào những giây đầu của trace → drift lệch về đầu. Local thì Chrome đã chạy sẵn nhiều giờ → drift gần bằng 0.

### F. `cpus: "2.0"` + ffmpeg + node + Xvfb + x11vnc + Chrome cạnh tranh CPU

Trong cùng container worker đang chạy 5 process ngốn CPU:

- Xvfb (rasterize)
- x11vnc + websockify (poll liên tục dù không ai xem)
- Chrome (multi-process, software rendering)
- node Webreel (capture loop)
- ffmpeg libx264

Limit 2 vCPU không đủ. Local rộng rãi hơn nhiều.

### G. Trace mapping có 2 fallback có thể chọn nhầm step

`trace_composer.py:204-248` ưu tiên `[TTS:idx]` / `[NARRATION:idx]`, fallback sang `described_steps` (tất cả step có description). Nếu phase2_parser tạo description cho cả những step không phải narration (vd ArrowRight có `description="Advance to slide N"`), fallback sẽ map sai vị trí.

---

## 4. Tại sao local OK mà prod gãy

| Yếu tố                   | Local (Windows headed) | Prod (Docker ephemeral)                |
| ------------------------ | ---------------------- | -------------------------------------- |
| GPU Chrome               | Có (DirectX/Skia GPU)  | Không (`--disable-gpu`, Xvfb software) |
| CPU/RAM                  | Toàn máy               | 2 vCPU / 2GB hard limit                |
| Chrome warm-up           | Chạy sẵn, profile ấm   | Cold-start mỗi job                     |
| Frame jitter             | <5ms                   | 50-300ms khi GS animate                |
| ffmpeg encode            | Background, ổn định    | Cạnh tranh CPU với Chrome+Xvfb         |
| Drift video↔trace        | ≈0                     | 5-30%, không đều                       |
| `speed_factor` kích hoạt | Hầu như không          | Luôn kích hoạt, nhưng không đủ         |

---

## 5. Các fix đã apply (Round 1 — patch nhẹ, không sửa Webreel core)

### Fix 1: Tăng `padding_ms` default 300 → 1000, configurable qua env

**Files**:

- `webreel-ai-agent/worker/presentation_gg_worker.py:249`
- `webreel-ai-agent/worker/web_worker.py:197`
- `webreel-ai-agent/worker/presentation_worker.py:358`

**Trước**:

```python
padding_ms=config.get("padding_ms", 300),
```

**Sau**:

```python
padding_ms=config.get("padding_ms", int(os.getenv("PADDING_MS", "1000"))),
```

Tác dụng: mỗi narration được thêm 1000ms im lặng cuối, đủ buffer cho jitter Docker. Local không bị ảnh hưởng (PADDING_MS không set → fallback 1000 trong code worker nhưng user có thể override qua job config).

### Fix 2: FPS recording configurable qua env, prod hạ xuống 24

**File**: `webreel-ai-agent/desktop_app/bu_to_webreel.py:644`

**Trước**:

```python
"fps": 30,
```

**Sau**:

```python
"fps": int(os.getenv("WEBREEL_FPS", "30")),
```

Thêm `import os` ở đầu file.

`docker-compose.prod.yml` set `WEBREEL_FPS=24` cho cả 3 worker (web/presentation/presentation-gg).

Tác dụng: capture loop chỉ cần kéo ~24 screenshot/giây thay vì 30/60 → đỡ áp lực CDP + ffmpeg → drift giảm. Local không set env → vẫn 30fps.

### Fix 3: Tắt x11vnc + noVNC mặc định, gate sau `ENABLE_VNC=1`

**File**: `webreel-ai-agent/scripts/docker-entrypoint.sh:108-156`

Bọc Step 3 (x11vnc) + Step 4 (websockify) trong:

```bash
if [ "${ENABLE_VNC:-0}" = "1" ]; then
    # ... start x11vnc + websockify ...
else
    echo "[entrypoint] ENABLE_VNC=0 (default) -> bo qua x11vnc + noVNC"
fi
```

`docker-compose.prod.yml` set `ENABLE_VNC=${ENABLE_VNC:-0}` cho cả 3 worker.

Tác dụng:

- Tiết kiệm 2 process polling liên tục → free CPU/RAM cho capture loop + ffmpeg.
- Xvfb vẫn chạy → Chrome vẫn có màn ảo cho anti-bot.
- Khi cần debug: `ENABLE_VNC=1 docker compose -f docker-compose.prod.yml up presentation-gg-worker`.

### Fix 4: Thêm env vars vào docker-compose.prod.yml

**File**: `webreel-ai-agent/docker-compose.prod.yml`

Mỗi worker (web/presentation/presentation-gg) thêm:

```yaml
# Audio-sync tuning cho moi truong Docker (xem trace_composer):
# - WEBREEL_FPS thap hon -> capture loop de keep up, drift video<->trace giam
# - PADDING_MS lon hon -> buffer giua narration va action ke tiep, tranh overlap
- WEBREEL_FPS=${WEBREEL_FPS:-24}
- PADDING_MS=${PADDING_MS:-1000}
# Tat VNC mac dinh de tiet kiem CPU/RAM (chi can Xvfb cho Chrome anti-bot)
- ENABLE_VNC=${ENABLE_VNC:-0}
```

Comment ở web-worker (dòng 192) cập nhật: `"Xvfb (+ VNC/noVNC neu ENABLE_VNC=1)"`.

---

## 5.5. Kết quả Round 1 trên job test (2026-05-28)

User build prod với patch Round 1, chạy 1 job presentation-gg ID `2e6f0816-8eb6-4da0-9bbe-a5b66a3991ee`.

**Hiện tượng**: vẫn lệch — audio các slide đầu nói sớm hơn hành động trong video (sau khi nói xong N0, dừng ~2s rồi sang N1, trong khi hành động ArrowRight thực sự dừng 5-7s mới chạy theo). Slide cuối và thoại cuối lại gần như đồng bộ.

**Số liệu trích từ container (volume `webreel-ai-agent_output_data`, job dir `slide_gg_phan_6-_du_doan_rui_ro_2e6f0816`)**:

| Chỉ số                              | Giá trị                                                                                          |
| ----------------------------------- | ------------------------------------------------------------------------------------------------ |
| Trace wall-clock (Webreel ghi nhận) | **164.2s**                                                                                       |
| Video duration thực tế (ffprobe)    | **98.13s**                                                                                       |
| Drift                               | **66s mất ~40%**                                                                                 |
| `speed_factor` composer tính ra     | **0.5977**                                                                                       |
| FPS                                 | 24 ✓ (Fix 2 đã có hiệu lực)                                                                      |
| Padding trong config                | 800ms (chứ không phải 1000ms — chú ý: là 800 vì khi đó job submit chưa pickup env `PADDING_MS`?) |

Trace timing (wall-clock) đối chiếu với vị trí audio thực sự trong video sau scale × 0.5977:

| Narration | Audio dur | Trace anchor | Vị trí trong video sau scale | ArrowRight trong trace | ArrowRight trong video |
| --------- | --------- | ------------ | ---------------------------- | ---------------------- | ---------------------- |
| N0        | 10.7s     | 3.30s        | **1.97s**                    | 14.88s                 | 8.90s                  |
| N1        | 14.1s     | 22.39s       | **13.38s**                   | 37.38s                 | 22.34s                 |
| N2        | 17.0s     | 44.70s       | **26.71s**                   | 62.58s                 | 37.40s                 |
| N3        | 18.7s     | 70.18s       | **41.94s**                   | 89.70s                 | 53.61s                 |
| N4        | 15.3s     | 97.38s       | **58.19s**                   | 113.48s                | 67.81s                 |
| N5        | 13.2s     | 121.18s      | **72.41s**                   | 135.18s                | 80.78s                 |
| N6        | 15.7s     | 142.38s      | **85.09s**                   | (cuối)                 | (cuối)                 |

⇒ Audio N1 đặt @13.4s nhưng ArrowRight slide 1→2 fire @8.9s trong video. Khán giả thấy: slide 2 hiện ra → 4.5s im lặng → mới bắt đầu N1 (vì N0 vẫn còn leftover). Đúng triệu chứng "**audio chạy trước, hành động lẹt đẹt theo sau, đến giữa slide thì audio đã nói được nửa**".

Slide cuối: N6 đặt @85.1s trên video 98.13s. Drift ở đoạn cuối gần converge vì cap không bị hit ở đây → "**slide cuối gần như fix**".

---

## 5.6. Root cause THỰC SỰ (chỉ phát hiện sau khi có log)

Trong file `packages/@webreel/core/src/recorder.ts:196` (trước khi patch):

```ts
const frameSlots = Math.min(600, Math.max(1, Math.round(elapsed / this.frameMs)));
```

**Cap cứng 600 frame slots = 25s.**

Khi Google Slides animate slide transition (heavy paint), `Page.captureScreenshot` timeout (2s — `recorder.ts:187`), throw error, catch block chỉ chờ `frameMs` (~42ms) rồi retry. Nếu Chrome freeze nhiều giây liên tiếp, suốt thời gian đó **không có frame nào được write**. Khi cuối cùng screenshot success, `elapsed` lớn → frameSlots cap về 600 → **video time "ăn cắp" cho mỗi cụm freeze >25s**.

⇒ Drift **không đều**, tập trung vào những đoạn transition slide (giữa job), không phải drift đều khắp video.

⇒ `speed_factor` toàn cục (trace_composer.py:317-324) áp tỉ lệ 0.6 cho TẤT CẢ narration, kể cả những narration nằm ở đoạn KHÔNG hề bị freeze — đẩy chúng về trước nhiều giây so với vị trí thực sự cần.

### Tại sao Round 1 không giải quyết được

- `padding_ms` tăng → chỉ thêm im lặng vào config (pause trong trace dài hơn). Không cứu composer khỏi giả định "compression đều".
- `fps=24` → giảm áp lực capture loop, đỡ freeze. Nhưng không xóa được 600-cap. Drift 40% test này quá lớn để fps có thể bù.
- Tắt VNC → tương tự, chỉ đỡ jitter, không sửa logic cap.

Round 1 đúng nhưng chưa đủ; drift quá nghiêm trọng để workaround xử lý.

---

## 5.7. Round 2A — Sửa tận gốc trong Webreel core (ĐÃ APPLY)

**File**: `packages/@webreel/core/src/recorder.ts`

### Thay đổi 1: Bỏ cap 600 frameSlots

**Trước** (line 196):

```ts
const frameSlots = Math.min(600, Math.max(1, Math.round(elapsed / this.frameMs)));
```

**Sau**:

```ts
// No upper cap: when capture freezes for several seconds (heavy
// page paint, e.g. Google Slides transitions), we must duplicate
// enough frames to keep the video timeline aligned with wall-clock,
// otherwise downstream trace-based audio composition gets a video
// that is much shorter than the trace and audio drifts.
const frameSlots = Math.max(1, Math.round(elapsed / this.frameMs));
```

Tác dụng: khi freeze 30s, frame duplication điền đủ 30s × 24fps = 720 frames thay vì cap ở 600. Video sẽ dài đúng bằng trace → `speed_factor ≈ 1.0` → composer hoạt động đúng. Drift gần như biến mất.

Risk: video to hơn (nhiều frame duplicate trong cụm freeze), nhưng `libx264 -crf 18` compress duplicate cực tốt — IDR + P-frames trùng → bitrate gần như 0 cho đoạn đó.

### Thay đổi 2: Tăng captureScreenshot timeout 2000 → 5000

**Trước** (line 187):

```ts
setTimeout(() => reject(new Error("captureScreenshot timeout")), 2000);
```

**Sau**:

```ts
setTimeout(() => reject(new Error("captureScreenshot timeout")), 5000);
```

Tác dụng: Chrome software-rendering trong Docker thi thoảng cần 2-3s cho 1 captureScreenshot ở thời điểm rasterize nặng. Timeout 2s sinh false-positive → throw vào catch → consecutiveErrors tăng → tới 30 thì abort recording. Nâng lên 5s cho thực tế Docker.

### Rebuild

```bash
# Buoc 1: rebuild TS -> dist (chay tren may dev local)
cd packages/@webreel/core
npx tsc        # output dist/recorder.js da verify

# Buoc 2: rebuild Docker image (BAT BUOC sau khi sua core)
# Dockerfile.worker COPY packages/@webreel/core/dist san vao image, nen image
# CU se KHONG co patch. Workers ephemeral spawn tu image -> phai rebuild.
cd webreel-ai-agent
docker compose -f docker-compose.prod.yml build --no-cache web-worker

# Buoc 3 (verify): chec recorder.js trong image moi
docker run --rm webreel-worker:latest sh -c \
  "grep -nE 'frameSlots|captureScreenshot timeout' /app/packages/@webreel/core/dist/recorder.js"
# Output ky vong:
#   ... new Error("captureScreenshot timeout")), 5000)
#   ... const frameSlots = Math.max(1, Math.round(elapsed / this.frameMs));
```

Đã verify `dist/recorder.js` line 160/172 chứa `5000` và `Math.max(1, ...)` (không còn `600`).

`packages/webreel` (CLI) import `Recorder` từ `@webreel/core` qua workspace symlink → không cần rebuild CLI thêm.

**Lưu ý quan trọng**: Sửa code TS local + rebuild `dist/` **CHƯA ĐỦ**. Image Docker được build từ trước sẽ copy snapshot của `dist/` tại thời điểm build → patch không có trong image. Mỗi job mới do autoscaler spawn từ image cũ → patch không có hiệu lực. **Phải rebuild Docker image** (`docker compose build --no-cache web-worker`) sau khi sửa core.

---

## 5.8. Hotfix duplicate narration trên cùng slide (2026-05-28, job 819a89a3)

**Hiện tượng** (sau khi R2A + hotfix CDP hoạt động trơn tru):

- Sync timeline gần như chuẩn.
- Nhưng 1 slide không có audio + slide thứ 2 nghe 2 đoạn audio chồng lên nhau (nội dung khác nhau, cùng chủ đề "kiểm thử/nghiệm thu").

**Phân tích `browser_use_history.json`** của job `819a89a3-6e45-434c-b278-7f7511be563b`:

Chuỗi `model_actions`:

```
1. navigate
2. save_narration  -> "Chào các em..." (slide 1)
3. send_keys ArrowRight
4. wait
5. save_narration  -> "Tiếp theo, kiểm thử và nghiệm thu..." (slide 2 LẦN 1)
6. save_narration  -> "Tiếp theo, quy trình kiểm thử..." (slide 2 LẦN 2) ⚠️
7. send_keys ArrowRight
8. wait
9. save_narration  -> "đánh giá kết quả..." (đáng lẽ slide 3, nhưng index lệch)
...
```

Agent đã gọi `save_narration` **2 lần liên tiếp cho slide 2** mà không có ArrowRight ở giữa (có thể agent tự sửa lại nội dung). Hệ quả:

1. 7 narration cho 6 slide → audio thừa 1 segment.
2. 2 audio "slide 2" đặt trên cùng vị trí timeline → user nghe 2 đoạn chồng.
3. Index `[TTS:idx]` shift 1: TTS:2 (thực ra là "slide 2 lần 2") rơi vào pause sau ArrowRight thứ 1 → slide 6 (TÓM TẮT) mất narration.

### Root cause

`webreel-ai-agent/desktop_app/bu_to_webreel.py:182-190` cũ có dedupe theo similarity > 80%:

```python
overlap = len(set(clean_text.split()) & set(last_narration_text.split()))
similarity = overlap / max(len(set(clean_text.split())), 1)
if similarity > 0.8:
    continue
```

Hai narration trên cùng chủ đề nhưng câu chữ khác hẳn → similarity ~30-40% → dedup không bắt.

Dấu hiệu chắc chắn 2 narration thuộc cùng slide: **chưa có ArrowRight giữa chúng**. Dedup theo dấu hiệu này chính xác hơn similarity.

### Fix

**File**: `webreel-ai-agent/desktop_app/bu_to_webreel.py`

Thêm flag `narration_advanced_since_last`:

- Khởi tạo `= True` (slide 1 luôn được narrate).
- Reset `= False` mỗi khi parser thêm narration mới.
- Set `= True` ở mỗi vị trí tạo step ArrowRight (2 vị trí: line 334 — branch click presentation button, line 581 — branch send_keys).

Trong nhánh `save_narration`:

- Nếu `not narration_advanced_since_last` và đã có narration trước → **GHI ĐÈ** narration cuối (giữ narration sau, vì agent thường tự sửa nội dung chi tiết hơn) thay vì append narration mới.
- Cập nhật cả `tts_script[-1]["text"]` và `steps[...]["description"]` (tag `[NARRATION:prev_idx]`).
- Giữ lại logic similarity-based dedup làm fallback cho trường hợp khác (agent retry sau ArrowRight).

Tác dụng:

- 2 narration cùng slide → chỉ giữ 1 (narration sau, chi tiết hơn).
- `narration_counter` không tăng → audio count khớp slide count → mapping `[TTS:idx]` không lệch → slide cuối không bị mất narration.

### Hành động

Chỉ cần rebuild Docker image (không cần đụng dist Webreel core):

```bash
cd webreel-ai-agent
docker compose -f docker-compose.prod.yml build --no-cache web-worker
```

---

## 5.9. Hotfix CDP short-circuit regression (2026-05-28, job 157ef435)

**Hiện tượng**: sau khi rebuild Docker image với R2A, chạy job `157ef435-efa1-420a-ba99-98a03f581733` không tạo được video → R2 trả về not found.

Log `webreel_run_*.log` chỉ có 4 dòng:

```
Recording: slide_gg_phan_5-_giai_doan_ket_thuc_da_157ef435
[DEBUG] launchChrome: headless = true
Downloading chrome-headless-shell... (one-time setup)
spawnSync unzip ENOENT
```

Khác hoàn toàn job cũ (2e6f0816) — job cũ có `[DEBUG] launchChrome: Using existing CDP URL = http://localhost:9222`.

### Root cause

`packages/@webreel/core/src/chrome.ts` đã bị **revert mất 3 đoạn** trước khi mình bắt đầu task này (mtime 2026-05-27 18:38, trước phiên làm việc):

1. Field `cdpUrl` và `profile` trong `LaunchChromeOptions` interface.
2. **CDP short-circuit** ở đầu `launchChrome`: nếu `options.cdpUrl` được truyền → return mock instance, không spawn chrome mới, không download chrome-headless-shell.
3. Logic `isTempProfile` để Chrome dùng profile bền vững khi có `options.profile`.

Khi mình chạy `npx tsc` cho R2A, TypeScript compile **toàn bộ src** → ghi đè `dist/chrome.js` cũ (vốn còn short-circuit) → image build mới mất luôn 3 đoạn này.

`dist/` bị gitignore → không track được trong git → bản dist hoạt động trước đây chỉ tồn tại trong image cũ.

### Hậu quả dây chuyền

1. `runner.ts:193` luôn gọi `launchChrome({ headless: shouldRecord, cdpUrl: config.cdpUrl })`.
2. Source mới (post-revert) bỏ qua `cdpUrl` → đi nhánh headless → `await ensureHeadlessShell()`.
3. `ensureHeadlessShell()` download Chrome from Google → cần `unzip` binary để giải nén → image **không cài `unzip`** (`Dockerfile.worker` chỉ có ffmpeg, libreoffice, node, xvfb, x11vnc, novnc, gosu) → `spawnSync unzip ENOENT` → crash.
4. Webreel exit non-zero → video không tạo → upload to R2 thất bại → R2 trả `404 not found`.

### Fix

```bash
# Khoi phuc chrome.ts tu HEAD (3 doan da bi revert)
cd /f/==HK1-2526==/ThucTap/webreel
git checkout HEAD -- packages/@webreel/core/src/chrome.ts

# Rebuild dist (kèm theo R2A patch trong recorder.ts đã apply)
cd packages/@webreel/core
rm -rf dist && npx tsc

# Verify both patches in dist:
grep -nE "Using existing CDP|frameSlots = Math|captureScreenshot timeout" dist/chrome.js dist/recorder.js
# Ky vong:
#   dist/chrome.js:    Using existing CDP URL = ...
#   dist/recorder.js:  captureScreenshot timeout)), 5000)
#   dist/recorder.js:  frameSlots = Math.max(1, ...)

# Rebuild Docker image:
cd webreel-ai-agent
docker compose -f docker-compose.prod.yml build --no-cache web-worker
```

### Bài học

- `dist/` artifacts không track git → mỗi lần `npx tsc` rebuild có thể overwrite các patch local-only.
- Tiêu chuẩn từ giờ: **trước khi rebuild dist**, luôn `git diff packages/@webreel/core/src/` để biết src có lệch HEAD không. Nếu lệch, đảm bảo lệch là CHỦ Ý (như R2A) trước khi build.
- Cân nhắc: thêm `dist/` vào git để có baseline so sánh, hoặc cài pre-commit hook tự rebuild dist mỗi khi src thay đổi.

---

## 5.10. R2A2 — Fix frame-leak trong capture loop (2026-05-28, job b039f1c6)

**Hiện tượng** (sau R2A + hotfix CDP + hotfix narration):

- Sync đã tốt hơn kha khá.
- Nhưng đoạn đầu N0 chưa đọc xong đã sang N1.
- Càng về sau hình ảnh và âm thanh càng lệch.
- Các đoạn thoại nối tiếp nhau, đôi chỗ gối lên nhau ~1s.

**Số liệu trích từ container** (`slide_gg_phan_6-_du_doan_rui_ro_b039f1c6`):

| Chỉ số                  | Giá trị                                     |
| ----------------------- | ------------------------------------------- |
| Trace duration          | 185.13s                                     |
| Video raw duration      | **113.29s** (chỉ 2719 frame, mong đợi 4440) |
| `speed_factor` composer | **0.612** (vẫn lệch 39% như job cũ!)        |
| FPS                     | 24 ✓                                        |
| Padding ms thực tế      | **~500ms** (không phải 1000ms như đã tune)  |

R2A bỏ cap 600 nhưng video vẫn ngắn hơn trace 39%. Frame count thực tế thiếu **1721 frame**.

### Root cause: frame-leak do `lastFrameTime` không bao gồm thời gian write

`packages/@webreel/core/src/recorder.ts:194` (cũ):

```ts
const buffer = Buffer.from(screenshotResult.data, "base64");
const now = Date.now(); // <-- timestamp TRUOC khi write
const elapsed = now - lastFrameTime;
const frameSlots = Math.max(1, Math.round(elapsed / this.frameMs));

// ... loop write frameSlots-1 frames ...
await this.writeFrame(buffer); // <-- write thuc te (co the block)

// ...
lastFrameTime = now; // <-- set lai bang `now` cu (truoc write)
```

Khi `writeFrame()` block (ffmpeg pipe full → `drainResolve` chờ), thời gian X ms này **wall-clock chạy mà KHÔNG được bù bằng frame duplicate ở vòng tiếp**:

- Vòng N: `now = T0`, write tốn X ms, `lastFrameTime = T0`.
- Vòng N+1: `now = T0 + X + dt`, `elapsed = X + dt`, `frameSlots = round((X+dt)/41.66)`.
- Nhưng X ms đó đã bị nuốt vào write của vòng N → wall-clock thực tế từ frame N tới frame N+1 là `X + dt` chứ không phải `dt` → frame slots phải bù cả X + dt.
- Code có vẻ đã làm đúng (`elapsed = now - lastFrameTime`), NHƯNG vì `lastFrameTime = now` (chứ không phải post-write timestamp), nên **vòng N+1 lại tiếp tục lặp lại lỗi**: thời gian write của vòng N+1 bị ăn tiếp.

Lũy kế: mỗi vòng "nuốt" trung bình một phần thời gian. Sau 925 vòng → tích lũy 72s thiếu hụt → video chỉ dài 113s thay vì 185s.

### Fix

`packages/@webreel/core/src/recorder.ts`:

```ts
// Thay vi `lastFrameTime = now` (truoc write):
lastFrameTime = Date.now(); // <-- timestamp SAU khi tat ca write/drain xong
```

Đảm bảo elapsed của vòng tiếp bao gồm cả thời gian write của vòng hiện tại → frame slots bù đủ → video duration ≈ wall-clock.

### Fix kèm theo: backend `padding_ms` default 300 → 1000

`webreel-ai-agent/backend/job_models.py:19`:

```python
# Truoc:
padding_ms: int = 300
# Sau:
padding_ms: int = 1000
```

Khi job được submit qua API mà không truyền `padding_ms` → Pydantic auto-fill 300 → `config.get("padding_ms", ...)` ưu tiên giá trị này → env `PADDING_MS=1000` của container không có hiệu lực.

### Fix kèm theo: worker priority env > config

3 worker file: `worker/web_worker.py`, `worker/presentation_worker.py`, `worker/presentation_gg_worker.py`.

```python
# Truoc:
padding_ms=config.get("padding_ms", int(os.getenv("PADDING_MS", "1000")))
# Sau:
padding_ms=int(os.getenv("PADDING_MS") or config.get("padding_ms") or 1000)
```

Đảo thứ tự ưu tiên: `PADDING_MS` env (set trong docker-compose.prod.yml) thắng config từ backend. Cho phép tune từ ngoài qua env mà không cần rebuild backend khi muốn thử nghiệm.

---

## 6. Cách verify sau khi deploy round 2A

Cần rebuild image worker để Dockerfile pick up `packages/@webreel/core/dist` mới:

```bash
cd webreel-ai-agent
docker compose -f docker-compose.prod.yml build --no-cache web-worker
# (web-worker, presentation-worker, presentation-gg-worker đều dùng image webreel-worker:latest)
```

Chạy lại 1 job presentation-gg và kiểm tra log:

1. **Phase 4 Injector** — đúng padding:

   ```
   [Injector] NARRATION:0 -> 5234ms + 1000ms padding = 6234ms
   ```

   (Padding phải là 1000ms — nếu job test ID `2e6f0816` ra 800ms, kiểm tra lại env `PADDING_MS=1000` đã set chưa.)

2. **Phase 6 Composer** — drift video↔trace (chỉ số QUAN TRỌNG NHẤT):

   ```
   [TraceComposer] Trace: Xms | Video: Yms
   [TraceComposer] -> Video is compressed. Scaling timestamps by factor: 0.XX
   ```

   - **Kỳ vọng sau R2A**: `Y/X >= 0.97` (drift < 3%), `speed_factor` gần 1.0.
   - Nếu vẫn `< 0.90` → frame duplication chưa kịp (capture screenshot vẫn timeout chuỗi dài) → cần R2B.

3. **Webreel recorder** — frame drop:

   ```
   Warning: N frame(s) dropped during recording
   ```

   - `N = 0`: capture loop khỏe.
   - `N > 0`: FPS vẫn cao so với năng lực container → hạ `WEBREEL_FPS=20`.

4. **Quan sát mắt** — mở `output/<video>/<video>_final.mp4`:
   - Audio slide 1 phải kết thúc TRƯỚC khi animation slide 2 bắt đầu.
   - Nếu vẫn overlap → tăng `PADDING_MS=1500`.

---

## 7. Việc tiếp theo (Round 2B — nếu R2A vẫn không đủ)

### 7.1. Sửa tận gốc: ghi `frame_index` vào trace thay vì `start_time_ms`

**File**: `packages/webreel/src/lib/runner.ts`

Thay đổi cấu trúc `executionTrace`:

```ts
const executionTrace: Array<{
  step_index: number;
  action_type: string;
  description?: string;
  start_time_ms: number; // giữ lại cho backward compat
  end_time_ms: number;
  start_frame: number; // MỚI: frame_count khi step bắt đầu
  end_frame: number; // MỚI: frame_count khi step kết thúc
}> = [];
```

Cần expose `recorder.frameCount` ra ngoài (hiện đang private). Khi bắt đầu mỗi step:

```ts
const stepStartFrame = recorder?.getFrameCount() ?? 0;
```

Cập nhật `desktop_app/trace_composer.py` để ưu tiên `start_frame / fps * 1000` thay vì `start_time_ms`, không cần `speed_factor` nữa.

Phải rebuild `packages/webreel` và `packages/@webreel/core`. Risk: nhiều, vì runner.ts đụng vào logic core.

### 7.2. Piecewise-linear scaling thay vì global speed_factor

Trong `trace_composer.py`, thay vì 1 speed_factor toàn cục, tính tỉ lệ riêng cho mỗi đoạn giữa các trace step:

- Đoạn `[step_i.start_time_ms, step_{i+1}.start_time_ms]` → video duration tương ứng = ffprobe của frame range.
- Cần thêm metadata trong trace (frame index per step) — quay về 7.1.

### 7.3. Auto-truncate / fade-out audio khi overlap

Trong `compute_narration_timestamps`, nếu prev_end > next_start, không push next mà **truncate prev** bằng `aformat=... ,atrim=duration=...`. Audio chấp nhận bị cắt cụt còn hơn lệch lung tung.

### 7.4. Atempo speed-match audio với video

Khi `speed_factor < 1`, áp `atempo=1/speed_factor` (clamp ≤ 1.15) cho từng audio segment. Tăng tốc audio nhẹ để khớp video bị nén.

### 7.5. Pre-warm Chrome trước phase 5

Trong `pipeline.py` giữa phase 4 và phase 5, thêm 2-3s "warm capture" giả (dummy CDP screenshot) để ổn định pipeline trước khi recording thật bắt đầu.

### 7.6. Validate trace mapping chặt hơn

`trace_composer.py:236-248`: nếu mapping bằng `tts_index` không tìm thấy đủ cho tất cả narration → raise ERROR thay vì fallback sang `described_steps`. Tránh map sai im lặng.

### 7.7. Cân nhắc dùng SwiftShader cho Chrome

Thử `--use-gl=swiftshader` thay vì `--disable-gpu`. Rasterization vẫn software nhưng nhanh hơn. Test kỹ với Google Slides vì animation có thể đổi.

### 7.8. Tăng resource limit container

`cpus: "2.0"` → `cpus: "3.0"`, `memory: 2G` → `memory: 3G`. Trade-off: ít worker chạy song song hơn nhưng mỗi worker stable hơn.

---

## 8. Các file đã thay đổi (changelog)

```
# Round 1 (worker config)
webreel-ai-agent/worker/presentation_gg_worker.py        # padding_ms default 1000 via env
webreel-ai-agent/worker/web_worker.py                    # padding_ms default 1000 via env
webreel-ai-agent/worker/presentation_worker.py           # padding_ms default 1000 via env
webreel-ai-agent/desktop_app/bu_to_webreel.py            # fps via WEBREEL_FPS env
webreel-ai-agent/scripts/docker-entrypoint.sh            # x11vnc + noVNC gated by ENABLE_VNC
webreel-ai-agent/docker-compose.prod.yml                 # env vars cho 3 worker + comment update

# Round 2A (Webreel core)
packages/@webreel/core/src/recorder.ts                   # bo cap 600 frameSlots + timeout 2000->5000
packages/@webreel/core/dist/recorder.js                  # rebuilt via `npx tsc`

# Hotfix CDP regression (sau job 157ef435)
packages/@webreel/core/src/chrome.ts                     # khoi phuc CDP short-circuit tu HEAD
packages/@webreel/core/dist/chrome.js                    # rebuilt

# Hotfix duplicate narration (sau job 819a89a3)
webreel-ai-agent/desktop_app/bu_to_webreel.py            # narration_advanced_since_last flag

# R2A2 + padding fix (sau job b039f1c6)
packages/@webreel/core/src/recorder.ts                   # lastFrameTime = Date.now() sau write (frame-leak fix)
packages/@webreel/core/dist/recorder.js                  # rebuilt
webreel-ai-agent/backend/job_models.py                   # padding_ms default 300 -> 1000
webreel-ai-agent/worker/web_worker.py                    # padding_ms env-priority over config
webreel-ai-agent/worker/presentation_worker.py           # padding_ms env-priority over config
webreel-ai-agent/worker/presentation_gg_worker.py        # padding_ms env-priority over config
```

Không sửa:

- `packages/webreel/` CLI (import từ core qua workspace, không cần rebuild).
- `desktop_app/trace_composer.py` (logic compose — để Round 2B nếu cần).
- `worker/office_worker.py` (không recording video, không liên quan).

---

## 9. Rollback nếu cần

```bash
git diff HEAD -- webreel-ai-agent/worker/presentation_gg_worker.py \
                 webreel-ai-agent/worker/web_worker.py \
                 webreel-ai-agent/worker/presentation_worker.py \
                 webreel-ai-agent/desktop_app/bu_to_webreel.py \
                 webreel-ai-agent/scripts/docker-entrypoint.sh \
                 webreel-ai-agent/docker-compose.prod.yml \
                 packages/@webreel/core/src/recorder.ts \
                 packages/@webreel/core/dist/recorder.js
git checkout HEAD -- <file>
# Nho rebuild lai core sau khi rollback:
#   cd packages/@webreel/core && npx tsc
# Roi rebuild Docker image:
#   docker compose -f docker-compose.prod.yml build --no-cache web-worker
```

Hoặc override env trong job submission để revert Round 1 behavior:

```
PADDING_MS=300 WEBREEL_FPS=30 ENABLE_VNC=1
```

---

## 10. Câu hỏi mở để thảo luận

1. Có nên hạ `WEBREEL_FPS` xuống 20 hoặc 18 không? Trade-off: smoothness vs sync. Test trên video thực để quyết.
2. Webreel core dùng `Page.captureScreenshot` (poll) thay vì `Page.startScreencast` (push). Có nên migrate sang screencast để ổn định hơn không? (Big change.)
3. Có nên cho mỗi worker container có pre-pulled Chrome profile thay vì extract từ tar mỗi lần? (Tốn disk, nhanh hơn cold start.)
4. Auto-scaler launch `docker compose run -d --rm` có thể thêm `--cpu-shares=2048` để worker được ưu tiên CPU không? Hoặc dùng `cgroups` riêng.
