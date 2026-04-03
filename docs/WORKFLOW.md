# Workflow - Luồng làm việc & Quy trình

## Tổng quan

Tài liệu này mô tả chi tiết luồng làm việc của hệ thống AI Agent Video Tutor, từ input của user đến output video hoàn chỉnh. Hệ thống có 2 pipeline riêng biệt:

1. **Web Browser Pipeline**: Dùng browser-use + webreel cho Chrome, Edge, Firefox
2. **Desktop OS Pipeline**: Dùng pywinauto + FFmpeg + Gemini Vision cho Excel, Word, PowerPoint, Desktop Apps

## Desktop OS Pipeline (os_recorder/)

Pipeline này là core của hệ thống, dùng cho Excel, Word, PowerPoint, Notepad và các desktop apps khác.

### Pipeline Overview

```
┌─────────────────┐
│  User Input     │  Task description + Target app (Excel/Word/PPT)
└────────┬────────┘
         │
         ▼
┌─────────────────────────────────┐
│  Phase 1: Planning (Silent)     │  30-60s
│  - Gemini Vision Agent          │
│  - Screenshot + UI tree          │
│  - Generate plan.json            │
│  - Generate narrations           │
│  - NO video recording            │
│  - NO mouse movement             │
└────────┬────────────────────────┘
         │
         ▼
┌─────────────────────────────────┐
│  Phase 2: TTS (Parallel)        │  5-10s total
│  - Edge TTS (Microsoft Azure)   │
│  - asyncio.gather for parallel  │
│  - Generate all MP3 segments    │
└────────┬────────────────────────┘
         │
         ▼
┌─────────────────────────────────┐
│  Phase 2.5: Review (Optional)   │  User interaction
│  - Show narration script in UI  │
│  - User can edit text            │
│  - Update plan.json              │
└────────┬────────────────────────┘
         │
         ▼
┌─────────────────────────────────┐
│  Phase 2.5: Inject Durations    │  <1s
│  - Measure exact TTS durations  │
│  - Inject into plan.json         │
│  - Update pause steps            │
└────────┬────────────────────────┘
         │
         ▼
┌─────────────────────────────────┐
│  Phase 3: Ready Confirmation    │  User interaction
│  - User resets app state         │
│  - (Undo changes from Phase 1)  │
│  - Click "Ready to Record"       │
└────────┬────────────────────────┘
         │
         ▼
┌─────────────────────────────────┐
│  Phase 3: Record-Replay          │  10-30s
│  - Read plan.json                │
│  - FFmpeg screen capture         │
│  - pywinauto silent execution    │
│  - Screenshot capture (parallel) │
│  - Generate trace.json           │
└────────┬────────────────────────┘
         │
         ▼
┌─────────────────────────────────┐
│  Phase 4: Audio Sync             │  5-10s
│  - Trace-driven composition      │
│  - FFmpeg adelay + amix          │
│  - Exact timestamp placement     │
└────────┬────────────────────────┘
         │
         ▼
┌─────────────────────────────────┐
│  Phase 5: Document Generation    │  5-10s (parallel)
│  - DOCX renderer                 │
│  - PDF renderer                  │
│  - Screenshots + narrations      │
└────────┬────────────────────────┘
         │
         ▼
┌─────────────────┐
│  Final Output   │  video_final.mp4 + tutorial.docx + tutorial.pdf
└─────────────────┘
```

---

## Phase 1: Planning (Silent Mode)

### Mục đích
Agent "dò đường" để hiểu task và lên kịch bản, KHÔNG quay video, KHÔNG chiếm chuột người dùng.

### Input
- Task description (tiếng Việt hoặc tiếng Anh)
- Target PID (Process ID của ứng dụng)
- Max steps (giới hạn số bước, mặc định 15)

### Quy trình

**1. Khởi tạo Agent**
- Connect tới ứng dụng qua PID bằng pywinauto
- Auto-detect app type (Excel, Word, PowerPoint, Browser, General)
- Load system prompt phù hợp với app type

**2. Agent Loop (Silent Exploration)**

Mỗi bước trong loop:

a. **Capture State**
   - Chụp screenshot cửa sổ ứng dụng
   - Lấy UI element tree (UIA - UI Automation)
   - Prune tree: chỉ giữ interactive elements (Button, Edit, MenuItem, etc.)
   - Index elements: gán số thứ tự + tọa độ cho mỗi element

b. **Query Gemini Vision**
   - Gửi screenshot + indexed element list
   - Gemini phân tích và quyết định action tiếp theo
   - Response format: JSON với thought, action, narration, is_done

c. **Execute Action (Silent)**
   - Dùng pywinauto API (KHÔNG di chuyển chuột vật lý)
   - Supported actions:
     - click_element: Click by element index
     - type_text: Type vào element đang focus
     - press_key: Nhấn phím đơn (enter, tab, escape, arrow keys)
     - press_hotkey: Tổ hợp phím (Ctrl+B, Ctrl+C, F5, etc.)
     - drag_mouse: Drag từ element này sang element khác
     - scroll: Cuộn chuột
     - wait: Đợi (ms)
     - done: Hoàn thành task

d. **Record Step**
   - Lưu action vào history
   - Lưu narration (lời thoại tiếng Việt)
   - Lưu screenshot

e. **Check Completion**
   - Nếu is_done = true → dừng loop
   - Nếu đạt max_steps → dừng loop
   - Nếu phát hiện loop (5 action giống nhau liên tiếp) → dừng loop

**3. State Reset**
- Sau khi dò đường xong, agent tự động Undo (Ctrl+Z)
- Số lần Undo = số action đã thực hiện + 2 (cho chắc)
- Đưa ứng dụng về trạng thái ban đầu

**4. Generate plan.json**
- Convert action history thành replay plan
- Format: JSON array với step_index, action_type, parameters, description
- Mỗi description có format: "[NARRATION:idx] text..."

### Output

**plan.json** chứa danh sách actions để replay

**Screenshots:** step_000.png, step_001.png, ... (mỗi bước 1 ảnh)

**Narrations:** Extracted từ plan.json

### Đặc điểm quan trọng

**Silent Execution:**
- Dùng pywinauto UIA backend
- Không di chuyển chuột vật lý
- Người dùng vẫn dùng máy bình thường trong lúc agent chạy

**UI Element Pruning:**
- Giảm từ hàng trăm elements xuống vài chục
- Chỉ gửi interactive elements cho LLM
- Tiết kiệm token, tăng accuracy

**Loop Detection:**
- Phát hiện khi agent lặp lại action 5 lần liên tiếp
- Ngoại trừ navigation keys (space, right, pagedown) cho PowerPoint
- Tự động dừng để tránh infinite loop

**App-Specific Prompts:**
- PowerPoint: Lecturer mode, giải thích nội dung slide
- Browser: Coordinate grid overlay, mouse_click với (x,y)
- General: Standard OS automation

---

## Phase 2: TTS Generation (Parallel)

### Mục đích
Sinh audio cho tất cả narrations song song để tiết kiệm thời gian.

### Input
- Narrations từ Phase 1
- Voice selection (vi-VN-HoaiMyNeural, vi-VN-NamMinhNeural, etc.)
- TTS engine (Edge TTS hoặc FPT.AI)

### Quy trình

**1. Parallel Generation**
- Dùng asyncio.gather để gọi TTS API song song
- Mỗi narration → 1 async task
- Tất cả tasks chạy đồng thời

**2. Edge TTS (Default)**
- Microsoft Azure TTS
- Free, unlimited usage
- Giọng tự nhiên, hỗ trợ tiếng Việt tốt
- Output: MP3 files

**3. Measure Duration**
- Dùng ffprobe để đo chính xác duration (ms)
- Fallback: mutagen library
- Last resort: estimate từ file size

**4. Handle Failures**
- Nếu 1 segment fail → append None vào list
- Continue với các segments còn lại
- Log warning nhưng không dừng pipeline

### Output

Audio files: narration_000.mp3, narration_001.mp3, ...

Audio metadata: List of {"path": "...", "duration_ms": 2500}

### Timing
- Sequential: 2-5s per segment → 10-25s total cho 5 segments
- Parallel: 5-10s total cho tất cả segments (cải thiện 50-80%)

---

## Phase 2.5: Review & Duration Injection

### Part A: Review UI (Optional)

**Mục đích:**
Cho phép user review và edit narration script trước khi quay.

**UI Flow:**
1. Pipeline pause sau Phase 2
2. Show review dialog với editable text fields
3. User có thể:
   - Edit narration text
   - Keep original
   - Cancel job
4. Click "Confirm" → continue pipeline

**Update plan.json:**
- Replace narration text trong description
- Keep action parameters unchanged
- Regenerate TTS nếu text thay đổi (future feature)

### Part B: Duration Injection (Automatic)

**Mục đích:**
Inject exact TTS durations vào plan.json để audio sync chính xác.

**Quy trình:**
1. Đọc plan.json
2. Tìm các step có [NARRATION:idx] trong description
3. Match với audio file tương ứng
4. Inject duration_ms vào step
5. Thêm padding 300ms cho natural pacing
6. Save updated plan.json

---

## Phase 3: Ready-to-Record Confirmation

### Mục đích
Đảm bảo ứng dụng ở trạng thái ban đầu trước khi quay video thật.

### Lý do cần thiết
- Phase 1 đã thay đổi state của ứng dụng (dù có Undo)
- Một số thay đổi không thể Undo hoàn toàn (file save, network request)
- User cần manually verify state

### UI Flow

**Desktop App (Flet):**
1. Show dialog: "Sẵn sàng quay. Hãy reset trạng thái ứng dụng rồi bấm Xác nhận."
2. User actions:
   - Kiểm tra ứng dụng
   - Undo thủ công nếu cần (Ctrl+Z)
   - Đóng/mở lại file nếu cần
   - Click "Xác nhận" khi ready
3. Pipeline continues

**CLI Mode:**
- Print message: "BẤM PHÍM [ENTER] ĐỂ TIẾN HÀNH QUAY..."
- Wait for Enter key
- Continue

### Best Practices
- Đóng tất cả dialogs/popups
- Đưa cursor về vị trí ban đầu
- Đảm bảo không có unsaved changes
- Đảm bảo window ở foreground

---

## Phase 3: Record-Replay

### Mục đích
Quay video thật với FFmpeg + execute actions từ plan.json.

### Input
- plan.json (đã inject durations)
- Target PID
- Video name
- Enable dual output flag

### Quy trình

**1. Start FFmpeg Capture**
- Capture window by title (gdigrab trên Windows)
- 60 FPS, CRF 18 (high quality)
- H.264 codec
- Output: video_raw.mp4

**2. Replay Actions**

Đọc plan.json và execute từng step:

a. **Execute Action**
   - Dùng pywinauto API (giống Phase 1)
   - Nhưng lần này có FFmpeg đang quay
   - Timing chính xác theo duration_ms trong plan

b. **Screenshot Callback (Dual Output)**
   - Nếu enable_dual_output = True
   - Sau mỗi action → chụp screenshot
   - Highlight element đang tương tác
   - Save: screenshots/step_000.png, step_001.png, ...
   - Retry logic: max 3 retries nếu fail
   - Fallback: placeholder image

c. **Generate Trace**
   - Record exact timestamp của mỗi action
   - Format: start_time_ms, end_time_ms
   - Save: trace.json

**3. Stop FFmpeg**
- Send stop signal
- Wait for encoding to finish
- Verify video file exists

### Output

**Video:** video_raw.mp4 (video thuần, chưa có audio)

**Trace:** trace.json với exact timestamps

**Screenshots (if dual output enabled):** step_000.png, step_001.png, ...

### Error Handling
- Timeout: 60s per step
- Retry: max 2 times per step
- Cancel support: check cancel_event mỗi step
- Graceful degradation: continue nếu screenshot fail

---

## Phase 4: Audio Sync (Trace-Driven)

### Mục đích
Ghép audio vào video với timing chính xác dựa trên execution trace.

### Tại sao dùng Trace?
- Không estimation, không guessing
- Exact timestamp từ thực tế execution
- Audio placement chính xác tuyệt đối

### Input
- video_raw.mp4
- trace.json
- Audio files (MP3)

### Quy trình

**1. Parse Trace**
- Đọc trace.json
- Tìm các step có [TTS:idx] hoặc [NARRATION:idx] tag
- Build mapping: narration_index → trace_step

**2. Compute Timestamps**

Strategy:
- Narration i → place tại start_time của step i
- Prevent overlap: ensure narration i starts after narration i-1 ends
- Buffer: 800ms giữa các narrations cho natural pacing

**3. FFmpeg Composition**

Dùng filter_complex với anullsrc, concat, amix, apad để place audio tại exact timestamps.

**4. Cancel Support**
- Use Popen + poll loop
- Check cancel_event mỗi 300ms
- Kill FFmpeg process nếu cancelled

### Output
video_final.mp4 (video + audio synced)

### Accuracy
- Placement accuracy: ±50ms (limited by FFmpeg precision)
- No drift: mỗi narration independent
- No overlap: guaranteed by buffer logic

---

## Phase 5: Document Generation (Dual Output)

### Mục đích
Tạo tài liệu hướng dẫn (DOCX + PDF) từ screenshots và narrations.

### Điều kiện
- enable_dual_output = True
- Screenshots captured trong Phase 3

### Input
- Screenshots (step_000.png, step_001.png, ...)
- plan.json hoặc trace.json (để lấy narrations)
- Video name, task description

### Quy trình

**1. Build Render Plan**

a. **Map Screenshots**
   - Parse filename: step_(\d+).png → step_index
   - Build dict: {step_index: screenshot_path}

b. **Extract Narrations**
   - Parse trace.json
   - Find steps với [NARRATION:idx] tag
   - Build dict: {step_index: narration_text}

c. **Match Narration → Screenshot**
   - Strategy: narration tại step i → screenshot tại step i+1
   - Lý do: narration mô tả action, screenshot show kết quả
   - Prevent reuse: mỗi screenshot chỉ dùng 1 lần

**2. Parallel Rendering**

Dùng asyncio.gather để render DOCX và PDF song song:

a. **DOCX Renderer**
   - python-docx library
   - Title page với video name
   - Mỗi step: narration text + screenshot
   - Professional formatting
   - Output: video_name.docx

b. **PDF Renderer**
   - ReportLab library
   - Same content as DOCX
   - Better for sharing/printing
   - Output: video_name.pdf

**3. Handle Missing Screenshots**
- Nếu screenshot không tồn tại → skip step
- Log warning
- Continue với steps còn lại

### Output Structure

```
output/video_name/
├── video_name_final.mp4
├── video_name.docx
├── video_name.pdf
└── screenshots/
    ├── step_000.png
    ├── step_001.png
    └── ...
```

### Document Format

**Title Page:**
- Video name (large, bold)
- Task description
- Creation date

**Step Pages:**
- Step number
- Narration text (2-3 sentences)
- Screenshot (centered, scaled to fit)
- Action type badge (optional)

### Timing
- DOCX: 2-3s
- PDF: 3-5s
- Parallel: 5-7s total (vs 5-8s sequential)

---

## Web Browser Pipeline (desktop_app/)

Pipeline này dùng cho Chrome, Edge, Firefox và các web-based tasks.

### Pipeline Overview

```
┌─────────────────┐
│  User Input     │  Task description + CDP Port
└────────┬────────┘
         │
         ▼
┌─────────────────────────────────┐
│  Phase 1: Browser Automation    │  30-60s
│  - browser-use + Playwright     │
│  - Gemini AI planning            │
│  - Action history collection     │
└────────┬────────────────────────┘
         │
         ▼
┌─────────────────────────────────┐
│  Phase 2: Config Generation     │  <1s
│  - Parse browser-use history    │
│  - Extract selectors             │
│  - Generate webreel config       │
└────────┬────────────────────────┘
         │
         ▼
┌─────────────────────────────────┐
│  Phase 3: AI Review             │  5-10s
│  - Validate config               │
│  - Fix selectors                 │
│  - Generate TTS script           │
└────────┬────────────────────────┘
         │
         ▼
┌─────────────────────────────────┐
│  Phase 4: Video Recording       │  10-30s
│  - webreel (Node.js)             │
│  - Chrome headless-shell         │
│  - Output MP4 + timeline         │
└────────┬────────────────────────┘
         │
         ▼
┌─────────────────────────────────┐
│  Phase 5: TTS Generation        │  5-10s
│  - Edge TTS (parallel)           │
│  - Generate MP3 segments         │
└────────┬────────────────────────┘
         │
         ▼
┌─────────────────────────────────┐
│  Phase 6: Video Composition     │  5-10s
│  - MoviePy                       │
│  - Merge video + audio           │
│  - Timeline sync                 │
└────────┬────────────────────────┘
         │
         ▼
┌─────────────────┐
│  Final Output   │  video_final.mp4
└─────────────────┘
```

### Key Differences vs OS Pipeline

**Phase 1: browser-use**
- Dùng Playwright để control browser
- Accessibility Tree parsing (không phải UIA)
- Action history format khác

**Phase 2: Config Parser**
- Convert browser-use actions → webreel config
- Selector extraction: text, ID, class, aria-label, XPath
- Priority order: text > ID > class

**Phase 4: webreel Recording**
- Node.js tool (không phải FFmpeg)
- CDP (Chrome DevTools Protocol)
- Cursor overlay + HUD built-in

**No Dual Output:**
- Web pipeline chưa hỗ trợ DOCX/PDF generation
- Chỉ output video

---

## Desktop App UI (Flet)

### Main Features

**1. Environment Selector**
- Dropdown: Web / Desktop
- Dynamic UI: show/hide relevant controls

**2. Web Mode Controls**
- CDP Port selector (9222, 9223, 9224, 9225)
- Auto-detect Chrome running
- Launch Chrome with CDP if needed

**3. Desktop Mode Controls**
- Target app dropdown:
  - Excel, Word, PowerPoint
  - Notepad
  - Chrome, Edge, Firefox (OS-level control)
  - Custom (nhập tên process)
- Dual output checkbox (DOCX + PDF)

**4. TTS Settings**
- Enable/disable TTS
- Engine selector (Edge TTS / FPT.AI)
- Voice selector (Hoài My, Nam Minh, Aria, Guy)

**5. Job Management**
- Jobs list với progress bars
- Status indicators:
  - Running
  - Review queue position
  - Currently reviewing
- Stop button (force kill)
- Environment badges (Web/Desktop)

**6. Phase 2.5 Review UI**
- Show narration script
- Editable text fields
- Confirm/Cancel buttons
- Queue management (multiple jobs)

**7. Phase 3 Ready Confirmation**
- Show dialog: "Sẵn sàng quay..."
- User confirms when ready
- Continue pipeline

**8. History Tab**
- Video cards với thumbnail
- Metadata: name, size, date, source
- Actions:
  - Play video
  - Open folder
  - Delete (with confirmation)
- Dual output indicators (DOCX/PDF icons)

### Job Lifecycle

**1. Submit Job**
- Validate inputs
- Assign job_id
- Create cancel_event, review_event, ready_event
- Add to running_jobs dict
- Start async task

**2. Progress Updates**
- Phase 1: 0.0 → 1.0
- Phase 2: 1.0 → 2.0
- Phase 2.5 Review: 2.5 (pause)
- Phase 3 Ready: 3.0 (pause)
- Phase 3 Record: 3.0 → 4.0
- Phase 4 Audio: 4.0 → 5.0
- Phase 5 Document: 5.0 → 6.0

**3. Review Queue**
- Multiple jobs can wait for review
- Show queue position
- Process one at a time
- Restore main area after review

**4. Cancel Job**
- Set cancel_event
- Cancel async task
- Kill child processes (FFmpeg, node)
- Unblock waiting events
- Update UI immediately

**5. Complete Job**
- Remove from running_jobs
- Refresh history tab
- Show success notification

---

## Error Handling & Recovery

### Gemini API Errors

**Retry Logic:**
- Max 3 retries với exponential backoff
- Delay: 2s, 4s, 8s
- Nếu fail hết → raise RuntimeError → stop pipeline

**Common Errors:**
- Rate limit: wait and retry
- Invalid JSON: parse error, retry
- Network timeout: retry
- API key invalid: fail immediately

### TTS Errors

**Graceful Degradation:**
- Nếu 1 segment fail → append None
- Continue với segments còn lại
- Final video có audio cho segments thành công
- Log warning cho segments failed

**Retry:**
- Max 3 retries per segment
- Exponential backoff
- Skip segment nếu fail hết

### FFmpeg Errors

**Recording Errors:**
- Window not found: fail immediately
- Encoding error: retry 1 time
- Disk full: fail with clear message

**Composition Errors:**
- Invalid audio file: skip segment
- Filter error: fallback to simpler filter
- Timeout: kill process, return raw video

### Screenshot Errors

**Capture Errors:**
- Retry: max 3 times với delay 100ms
- Fallback: placeholder image
- Continue pipeline (không fail)

**Placeholder:**
- Gray background
- Text: "Screenshot failed at step X"
- Same size as normal screenshots

### Cancel Handling

**Graceful Cancellation:**
- Check cancel_event mỗi phase
- Kill child processes (FFmpeg, node)
- Cleanup temp files
- Update UI immediately
- Return partial results

**Process Killing:**
- Use psutil to find all children
- Kill: ffmpeg, ffprobe, node, chrome-headless-shell
- Skip: python, flet (keep app running)

---

## Performance Optimization

### Parallel Processing

**TTS Generation:**
- Sequential: 2-5s × 5 = 10-25s
- Parallel (asyncio.gather): 5-10s
- Improvement: 50-80%

**Document Rendering:**
- Sequential: 2-3s + 3-5s = 5-8s
- Parallel (asyncio.gather): 5-7s
- Improvement: ~15%

**Screenshot Capture:**
- Parallel với video recording
- No additional time cost
- Callback-based, non-blocking

### Resource Management

**Memory:**
- Close pywinauto connections after use
- Clear screenshot buffers
- Garbage collect after each phase

**Disk:**
- Delete temp files after composition
- Keep only final outputs
- Compress screenshots (PNG)

**CPU:**
- FFmpeg: use ultrafast preset for recording
- Use slower preset for final encode (if needed)
- Limit concurrent jobs (1-2 max)

### Caching

**UI Element Tree:**
- Cache pruned tree trong 1 step
- Reuse nếu window không thay đổi

**Gemini Responses:**
- No caching (mỗi screenshot unique)

**Audio Files:**
- Cache by text hash (future feature)
- Reuse nếu text giống nhau

---

## Best Practices

### For Users

**1. Task Description:**
- Rõ ràng, cụ thể
- Chia nhỏ task phức tạp
- Tránh task quá dài (>15 steps)

**2. App State:**
- Đảm bảo app ở trạng thái sạch
- Đóng dialogs/popups
- Không có unsaved changes

**3. Review Narrations:**
- Đọc kỹ script
- Sửa lỗi chính tả
- Đảm bảo ngữ nghĩa đúng

**4. Ready Confirmation:**
- Kiểm tra app state
- Undo thủ công nếu cần
- Đảm bảo window foreground

### For Developers

**1. Error Handling:**
- Always use try-except
- Log errors với context
- Graceful degradation
- Clear error messages

**2. Testing:**
- Unit test cho mỗi module
- Integration test cho pipeline
- Test với nhiều app types
- Test cancel functionality

**3. Logging:**
- Log mỗi phase start/end
- Log timing metrics
- Log errors với stack trace
- Use structured logging

**4. Code Organization:**
- Separate concerns (planning, recording, composition)
- Reusable modules
- Clear interfaces
- Type hints

---

## Monitoring & Metrics

### Performance Metrics

**Per Phase:**
- Duration (seconds)
- Success rate (%)
- Error count
- Retry count

**Overall:**
- Total duration
- Success rate
- Most common errors
- Average steps per video

### Quality Metrics

**Video:**
- Resolution
- FPS
- File size
- Encoding time

**Audio:**
- Sync accuracy (ms)
- Volume levels
- Segment count
- Failed segments

**Documents:**
- Page count
- Screenshot count
- File size
- Generation time

### User Metrics

**Usage:**
- Videos created per day
- Most used app types
- Average task length
- Cancel rate

**Satisfaction:**
- Review edit rate
- Retry rate
- Delete rate
- Feedback scores

---

## Kết luận

Workflow được thiết kế để:

1. **Tự động hóa tối đa**: Agent tự dò đường, không cần user can thiệp
2. **Chính xác cao**: Trace-driven audio sync, exact timestamps
3. **Linh hoạt**: Hỗ trợ nhiều app types, graceful degradation
4. **User-friendly**: Review UI, ready confirmation, cancel support
5. **Hiệu quả**: Parallel processing, resource optimization
6. **Mở rộng dễ**: Modular design, clear interfaces

Mỗi phase độc lập, có thể test riêng và thay thế nếu cần. Pipeline có thể chạy CLI hoặc Desktop UI, phù hợp với nhiều use cases.
