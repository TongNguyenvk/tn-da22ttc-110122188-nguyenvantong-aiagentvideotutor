# Plan - Kế hoạch thực hiện

## Tổng quan kế hoạch

Dự án được thực hiện trong 5 tuần với mục tiêu rõ ràng cho từng giai đoạn. Mỗi tuần tập trung vào một khía cạnh cụ thể của hệ thống, từ nghiên cứu cơ bản đến triển khai production.

**Thời gian:** 5 tuần (35 ngày)

**Phương pháp:** Agile, iterative development

**Deliverable cuối cùng:** Hệ thống hoàn chỉnh với 5 video demo

## Tuần 1: Browser Automation & Webreel Research

### Mục tiêu
Xây dựng nền tảng cho browser automation và hiểu rõ cơ chế hoạt động của webreel engine.

### Nhiệm vụ chi tiết

#### 1.1. Tích hợp browser-use
- [x] Cài đặt và cấu hình browser-use framework
- [x] Tích hợp Gemini LLM làm AI engine
- [x] Test basic automation: navigate, click, type
- [x] Xử lý stealth mode để tránh bot detection

**Output:**
```python
from browser_use import Agent
from langchain_google_genai import ChatGoogleGenerativeAI

llm = ChatGoogleGenerativeAI(model="gemini-2.0-flash-exp")
agent = Agent(task="Vào google.com", llm=llm)
history = await agent.run()
```

#### 1.2. Truy cập Accessibility Tree
- [x] Sử dụng Playwright để truy cập DOM
- [x] Parse Accessibility Tree thay vì OCR
- [x] Extract element attributes: id, class, name, text
- [x] Test với các loại element: button, input, link

**Lợi ích:**
- Chính xác hơn OCR
- Nhanh hơn (không cần image processing)
- Có thể extract selector chính xác

#### 1.3. Nghiên cứu Webreel Engine
- [x] Clone và build webreel từ source
- [x] Đọc hiểu schema v1: actions, selectors, timing
- [x] Test manual recording với config đơn giản
- [x] Phân tích output: MP4, timeline JSON, thumbnail

**Webreel Schema v1:**
```json
{
  "$schema": "https://webreel.dev/schema/v1.json",
  "videos": {
    "demo": {
      "url": "https://example.com",
      "steps": [
        {"action": "navigate", "url": "https://example.com"},
        {"action": "click", "selector": "#button"},
        {"action": "type", "selector": "input", "text": "Hello"},
        {"action": "pause", "ms": 1000}
      ]
    }
  }
}
```

#### 1.4. Proof of Concept
- [x] Chạy browser-use để thực hiện task đơn giản
- [x] Ghi lại action history
- [x] Manual convert sang webreel config
- [x] Record video thành công

### Deliverable Tuần 1
- ✅ browser-use Agent hoạt động ổn định
- ✅ Truy cập được DOM và Accessibility Tree
- ✅ Hiểu rõ cơ chế Webreel: schema, actions, output
- ✅ POC: Task → Actions → Video

### Thời gian
- Setup & Research: 2 ngày
- Implementation: 3 ngày
- Testing & Documentation: 2 ngày

---

## Tuần 2: Parser & AI Reviewer

### Mục tiêu
Tự động hóa việc chuyển đổi browser-use actions sang webreel config và tối ưu bằng AI.

### Nhiệm vụ chi tiết

#### 2.1. Xây dựng Parser (bu_to_webreel.py)
- [x] Parse browser-use action history
- [x] Map actions: navigate, click, input, wait
- [x] Extract CSS selectors từ DOM elements
- [x] Calculate timing cho mỗi step
- [x] Validate output theo schema v1

**Selector Priority:**
1. text content (chính xác nhất)
2. title attribute
3. id attribute
4. name attribute (cho forms)
5. class names
6. aria-label
7. XPath (fallback)

**Code Example:**
```python
def convert_to_webreel_config(history_data, video_name="demo"):
    """Convert browser-use history to webreel config"""
    config = {
        "$schema": "https://webreel.dev/schema/v1.json",
        "videos": {
            video_name: {
                "url": history_data["urls"][0],
                "steps": []
            }
        }
    }
    
    for action in history_data["model_actions"]:
        step = parse_action(action)
        if step:
            config["videos"][video_name]["steps"].append(step)
    
    return config
```

#### 2.2. Xử lý Edge Cases
- [x] URL decode cho href attributes
- [x] Handle dynamic selectors
- [x] Skip scroll actions (webreel tự động)
- [x] Skip done actions (chỉ là flag)
- [x] Fallback khi không extract được selector

#### 2.3. Xây dựng AI Reviewer
- [x] Tích hợp Gemini API
- [x] Design prompt để review config
- [x] Sửa lỗi selector tự động
- [x] Điều chỉnh timing cho mượt mà
- [x] Generate TTS script với timeline

**AI Reviewer Flow:**
```
Original Config
    ↓
Calculate Timeline (duration của mỗi step)
    ↓
Gemini Review (sửa lỗi, tối ưu)
    ↓
Enhanced Config + TTS Script
```

**TTS Script Format:**
```json
[
  {
    "text": "Chúng ta bắt đầu bằng cách truy cập trang web",
    "start_time": 0.0,
    "end_time": 3.0
  },
  {
    "text": "Tiếp theo, nhấp vào nút đăng nhập",
    "start_time": 3.5,
    "end_time": 6.0
  }
]
```

#### 2.4. Testing & Validation
- [x] Unit tests cho parser
- [x] Test với nhiều loại tasks
- [x] Validate schema compliance
- [x] Test AI reviewer với edge cases

### Deliverable Tuần 2
- ✅ Parser hoàn chỉnh: browser-use → webreel config
- ✅ AI Reviewer: tối ưu config + tạo TTS script
- ✅ Test suite đầy đủ
- ✅ Documentation: BU_TO_WEBREEL.md, AI_REVIEWER.md

### Thời gian
- Parser implementation: 3 ngày
- AI Reviewer: 2 ngày
- Testing: 2 ngày

---

## Tuần 3: Streamlit UI & TTS Integration

### Mục tiêu
Xây dựng giao diện web thân thiện và tích hợp text-to-speech tiếng Việt.

### Nhiệm vụ chi tiết

#### 3.1. Xây dựng Streamlit UI
- [x] Design layout: input form, progress, output
- [x] Task input với text area
- [x] Voice selection dropdown
- [x] Enable/disable TTS và subtitle
- [x] Progress tracking real-time
- [x] Video preview và download

**UI Components:**
```python
import streamlit as st

st.title("🎬 AI Agent Video Tutor")

# Input section
task = st.text_area("Mô tả tác vụ", height=100)
video_name = st.text_input("Tên video", "demo")

# Options
col1, col2 = st.columns(2)
with col1:
    voice = st.selectbox("Giọng đọc", ["banmai", "leminh", "thuminh"])
with col2:
    enable_subtitle = st.checkbox("Thêm phụ đề")

# Generate button
if st.button("Tạo video"):
    with st.spinner("Đang xử lý..."):
        video_path = run_pipeline(task, video_name, voice)
        st.success("Hoàn thành!")
        st.video(video_path)
```

#### 3.2. Tích hợp FPT.AI TTS
- [x] Setup FPT.AI API client
- [x] Implement async download MP3
- [x] Support multiple voices
- [x] Handle API errors gracefully
- [x] Cache audio segments

**TTS Client:**
```python
import requests
import asyncio

async def generate_tts(text, voice="banmai", output_path="audio.mp3"):
    url = "https://api.fpt.ai/hmi/tts/v5"
    headers = {
        "api-key": os.getenv("FPT_API_KEY"),
        "voice": voice,
        "speed": "0"
    }
    
    response = requests.post(url, headers=headers, data=text.encode('utf-8'))
    audio_url = response.json()["async"]
    
    # Download MP3
    audio_response = requests.get(audio_url)
    with open(output_path, "wb") as f:
        f.write(audio_response.content)
```

#### 3.3. Timeline Synchronization
- [x] Calculate video duration từ webreel timeline
- [x] Map TTS segments với video timeline
- [x] Ensure audio không dài hơn video
- [x] Add padding nếu cần

**Timeline Calculation:**
```python
def calculate_timeline(steps):
    timeline = []
    current_time = 0.0
    
    for step in steps:
        duration = get_step_duration(step)
        timeline.append({
            "action": step["action"],
            "start_time": current_time,
            "end_time": current_time + duration
        })
        current_time += duration
    
    return timeline
```

#### 3.4. Progress Tracking
- [x] Real-time progress bar
- [x] Status messages cho mỗi phase
- [x] Error handling và display
- [x] Estimated time remaining

### Deliverable Tuần 3
- ✅ Streamlit UI hoạt động đầy đủ
- ✅ TTS tích hợp với nhiều giọng Việt
- ✅ Timeline sync chính xác
- ✅ User experience mượt mà

### Thời gian
- Streamlit UI: 3 ngày
- TTS integration: 2 ngày
- Timeline sync: 2 ngày

---

## Tuần 4: Video Composition & Audio Sync

### Mục tiêu
Merge video và audio thành sản phẩm hoàn chỉnh với đồng bộ chính xác.

### Nhiệm vụ chi tiết

#### 4.1. Tích hợp MoviePy
- [x] Setup MoviePy từ master branch
- [x] Load video và audio clips
- [x] Merge với timeline chính xác
- [x] Export final MP4

**Video Composer:**
```python
from moviepy.editor import VideoFileClip, AudioFileClip, CompositeAudioClip

def compose_video(video_path, audio_segments, output_path):
    video = VideoFileClip(video_path)
    
    # Create audio clips with timing
    audio_clips = []
    for segment in audio_segments:
        audio = AudioFileClip(segment["path"])
        audio = audio.set_start(segment["start_time"])
        audio_clips.append(audio)
    
    # Composite audio
    final_audio = CompositeAudioClip(audio_clips)
    
    # Set audio to video
    final_video = video.set_audio(final_audio)
    
    # Export
    final_video.write_videofile(
        output_path,
        codec='libx264',
        audio_codec='aac',
        fps=60
    )
```

#### 4.2. Bezier Curves cho Cursor
- [x] Webreel đã hỗ trợ smooth cursor movement
- [x] Test với các loại click: single, double, drag
- [x] Verify cursor overlay hiển thị đúng

#### 4.3. Subtitle Generation (Optional)
- [x] Generate SRT file từ TTS script
- [x] Overlay subtitle lên video
- [x] Styling: font, size, position, color

**SRT Format:**
```
1
00:00:00,000 --> 00:00:03,000
Chúng ta bắt đầu bằng cách truy cập trang web

2
00:00:03,500 --> 00:00:06,000
Tiếp theo, nhấp vào nút đăng nhập
```

#### 4.4. Quality Optimization
- [x] Video encoding: CRF 18, 60fps
- [x] Audio quality: 128kbps AAC
- [x] File size optimization
- [x] Thumbnail generation

### Deliverable Tuần 4
- ✅ Video Composer hoàn chỉnh
- ✅ Audio/video sync chính xác
- ✅ Subtitle generation (optional)
- ✅ Output MP4 chất lượng cao

### Thời gian
- MoviePy integration: 2 ngày
- Audio sync: 2 ngày
- Subtitle: 1 ngày
- Testing & optimization: 2 ngày

---

## Tuần 5: Docker & Production Deployment

### Mục tiêu
Container hóa hệ thống và chuẩn bị cho production deployment.

### Nhiệm vụ chi tiết

#### 5.1. Docker Setup
- [x] Multi-stage Dockerfile
- [x] Optimize layer caching
- [x] Install system dependencies
- [x] Setup Chrome headless-shell

**Dockerfile:**
```dockerfile
# Stage 1: Node.js build
FROM node:20-slim AS node-builder
WORKDIR /app
COPY package.json pnpm-lock.yaml ./
RUN npm install -g pnpm && pnpm install
COPY . .
RUN pnpm build

# Stage 2: Python runtime
FROM node:20-slim
RUN apt-get update && apt-get install -y \
    python3.12 \
    python3-pip \
    ffmpeg \
    chromium \
    fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY --from=node-builder /app /app
COPY webreel-ai-agent/requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt

EXPOSE 8501
CMD ["streamlit", "run", "webreel-ai-agent/app.py"]
```

#### 5.2. Docker Compose
- [x] Service definition
- [x] Volume mounts cho output
- [x] Environment variables
- [x] Health check
- [x] Resource limits

**docker-compose.yml:**
```yaml
version: '3.8'
services:
  app:
    build: .
    ports:
      - "8501:8501"
    volumes:
      - ./output:/app/output
    environment:
      - GEMINI_API_KEY=${GEMINI_API_KEY}
      - FPT_API_KEY=${FPT_API_KEY}
    shm_size: '2gb'
    mem_limit: 4g
    cpus: 2
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8501"]
      interval: 30s
      timeout: 10s
      retries: 3
```

#### 5.3. Optimization
- [x] Layer caching cho faster builds
- [x] Multi-stage build cho smaller image
- [x] .dockerignore để exclude unnecessary files
- [x] Cleanup apt cache

#### 5.4. Sinh Video Demo
- [x] Demo 1: Google Search
- [x] Demo 2: Wikipedia Research
- [x] Demo 3: GitHub Navigation
- [x] Demo 4: Form Filling
- [x] Demo 5: Complex Multi-step Task

**Demo Scripts:**
```python
demos = [
    "Vào google.com và tìm kiếm 'Python programming'",
    "Vào wikipedia.org và tìm bài viết về Artificial Intelligence",
    "Vào github.com và tìm repository 'tensorflow'",
    "Vào example.com/form và điền thông tin đăng ký",
    "Vào amazon.com, tìm sách Python, và thêm vào giỏ hàng"
]

for i, task in enumerate(demos, 1):
    video_path = await run_pipeline(
        task=task,
        video_name=f"demo-{i}",
        enable_tts=True,
        tts_voice="banmai"
    )
    print(f"✅ Demo {i} completed: {video_path}")
```

#### 5.5. Documentation
- [x] README.md với setup instructions
- [x] DOCKER_SETUP.md
- [x] API documentation
- [x] Troubleshooting guide
- [x] Architecture diagrams

### Deliverable Tuần 5
- ✅ Docker image production-ready
- ✅ 5 video demo hoàn chỉnh
- ✅ Documentation đầy đủ
- ✅ Deployment guide

### Thời gian
- Docker setup: 2 ngày
- Optimization: 1 ngày
- Demo videos: 1 ngày
- Documentation: 3 ngày

---

## Metrics & KPIs

### Performance Targets
- Browser automation: < 60s per task
- Parser conversion: < 1s
- AI review: < 10s
- Video recording: < 30s
- TTS generation: < 5s per segment
- Video composition: < 10s
- Total pipeline: < 2 minutes

### Quality Targets
- Video quality: 1080p, 60fps, CRF 18
- Audio quality: 128kbps AAC
- Selector accuracy: > 95%
- Timeline sync: < 100ms drift
- Success rate: > 90%

### Resource Targets
- Memory usage: < 4GB
- CPU usage: < 80% (2 cores)
- Disk per video: < 100MB
- Docker image size: < 2GB

---

## Risk Management

### Identified Risks

1. **Browser automation fails**
   - Mitigation: Stealth mode, retry logic, fallback selectors

2. **API quota exceeded**
   - Mitigation: Rate limiting, caching, fallback to local models

3. **Video recording errors**
   - Mitigation: Validate config before recording, increase timeouts

4. **Audio/video desync**
   - Mitigation: Precise timeline calculation, validation checks

5. **Docker build fails**
   - Mitigation: Multi-stage build, dependency pinning

### Contingency Plans

- **Plan A:** Full pipeline với TTS
- **Plan B:** Pipeline without TTS (silent video)
- **Plan C:** Manual config creation (skip parser)

---

## Success Criteria

### Must Have
- ✅ Browser automation hoạt động
- ✅ Parser chuyển đổi chính xác
- ✅ Video recording thành công
- ✅ Docker deployment

### Should Have
- ✅ AI Reviewer tối ưu config
- ✅ TTS integration
- ✅ Streamlit UI
- ✅ Audio/video sync

### Nice to Have
- ✅ Subtitle generation
- ⏳ Multi-language support
- ⏳ Cloud storage integration
- ⏳ Batch processing

---

## Timeline Summary

| Tuần | Focus | Deliverable | Status |
|------|-------|-------------|--------|
| 1 | Browser Automation & Research | POC working | ✅ |
| 2 | Parser & AI Reviewer | Automated conversion | ✅ |
| 3 | UI & TTS | User interface + audio | ✅ |
| 4 | Video Composition | Final video output | ✅ |
| 5 | Docker & Deployment | Production ready | ✅ |

**Total:** 35 ngày (5 tuần)

**Status:** ✅ Hoàn thành đúng tiến độ

---

## Lessons Learned

### Technical Insights
1. Accessibility Tree chính xác hơn OCR
2. AI review giúp giảm lỗi đáng kể
3. Timeline sync cần tính toán cẩn thận
4. Docker multi-stage build giảm image size

### Process Improvements
1. Test sớm, test thường xuyên
2. Documentation đồng bộ với code
3. Incremental development hiệu quả
4. User feedback quan trọng

### Future Recommendations
1. Implement caching layer
2. Add quality presets
3. Support more languages
4. Build web dashboard
5. Cloud deployment

---

## Kết luận

Kế hoạch 5 tuần được thực hiện thành công với tất cả deliverables hoàn thành đúng hạn. Hệ thống đã sẵn sàng cho production deployment và có thể mở rộng thêm nhiều tính năng trong tương lai.
