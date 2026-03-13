# Tech Stack - Công nghệ sử dụng

## Tổng quan

Dự án sử dụng stack công nghệ hiện đại, kết hợp AI, browser automation, và video processing để tạo ra hệ thống tự động hóa quay video hướng dẫn.

## AI & Machine Learning

### Google Gemini
**Version:** gemini-3.1-flash-lite-review

**Vai trò:**
- LLM chính điều khiển AI Agent
- Review và tối ưu webreel config
- Generate TTS script tự nhiên


**Đặc điểm:**
- Temperature: 0.3 (balance giữa creativity và accuracy)
- Output format: JSON
- Context window: 1M tokens
- Fast response time (~2-5s)

**Use cases:**
1. Browser automation planning
2. Config validation và optimization
3. TTS script generation với timeline
4. Error detection và fixing

### FPT.AI Text-to-Speech
**Version:** API v5

**Vai trò:**
- Chuyển text thành giọng nói tiếng Việt tự nhiên
- Hỗ trợ nhiều giọng đọc

**API Endpoint:**
```
https://api.fpt.ai/hmi/tts/v5
```

**Giọng đọc hỗ trợ:**
- banmai (nữ, miền Bắc)
- leminh (nam, miền Bắc)
- thuminh (nữ, miền Nam)
- myan (nữ, miền Trung)
- lannhi (nữ, miền Bắc)


**Đặc điểm:**
- Output: MP3 format
- Speed control: -3 to +3
- Async download
- Giới hạn: ~5000 ký tự/request

## Browser Automation

### browser-use
**Version:** 0.12.0+

**Vai trò:**
- Framework tự động hóa trình duyệt bằng AI
- Truy cập Accessibility Tree
- Ghi lại action history

**Installation:**
```bash
pip install browser-use>=0.12.0
```

**Key Features:**
- AI-powered element detection
- Accessibility Tree parsing (không dùng OCR)
- Action history với DOM elements
- Stealth mode để tránh bot detection

**Usage:**
```python
from browser_use import Agent
from langchain_google_genai import ChatGoogleGenerativeAI

llm = ChatGoogleGenerativeAI(model="gemini-2.0-flash-exp")
agent = Agent(task="Your task here", llm=llm)
history = await agent.run()
```

**Supported Actions:**
- navigate: Điều hướng URL
- click: Click element
- input: Nhập text
- scroll: Cuộn trang
- wait: Đợi
- extract: Trích xuất dữ liệu

### Playwright
**Version:** 1.40.0+

**Vai trò:**
- Engine điều khiển trình duyệt
- Được browser-use sử dụng bên dưới


**Đặc điểm:**
- Cross-browser support (Chromium, Firefox, WebKit)
- Headless và headed mode
- Network interception
- Screenshot và video recording

## Video Recording & Processing

### webreel
**Version:** Custom build từ monorepo

**Vai trò:**
- Engine ghi hình trình duyệt chuyên nghiệp
- Render video với cursor overlay và HUD

**Supported Actions:**
- navigate: Điều hướng URL
- click: Click element
- type: Nhập text
- pause: Đợi (ms)
- keypress: Nhấn phím
- scroll: Cuộn (tự động)

**Output:**
- MP4 video (CRF 18, 60fps)
- PNG thumbnail
- Timeline JSON

### FFmpeg
**Version:** Latest stable

**Vai trò:**
- Video encoding
- Audio processing
- Format conversion


**Usage trong webreel:**
- Encode raw frames thành MP4
- CRF 18 (high quality)
- 60fps smooth playback
- H.264 codec

### MoviePy
**Version:** Latest from master branch

**Vai trò:**
- Merge video và audio
- Timeline synchronization
- Subtitle generation

**Usage:**
```python
from moviepy.editor import VideoFileClip, AudioFileClip, CompositeAudioClip

video = VideoFileClip("video.mp4")
audio = AudioFileClip("audio.mp3")
final = video.set_audio(audio)
final.write_videofile("output.mp4")
```

**Đặc điểm:**
- Python-based video editing
- Support nhiều format
- Audio/video sync
- Subtitle overlay

## Backend & Core

### Python
**Version:** 3.12+

**Vai trò:**
- Ngôn ngữ chính của backend
- Orchestration pipeline



**Project Structure:**
```
webreel-ai-agent/
├── src/
│   ├── bu_to_webreel.py    # Parser
│   ├── ai_reviewer.py      # AI Reviewer
│   ├── tts.py              # TTS client
│   └── video_composer.py   # Video composition
├── run_pipeline.py         # Main orchestrator
└── requirements.txt
```

### Node.js
**Version:** 20+

**Vai trò:**
- Runtime cho webreel
- Package management với pnpm


## Frontend & UI

### Streamlit
**Version:** 1.55.0+

**Vai trò:**
- Web interface cho user
- Real-time progress tracking
- Video preview


**Features:**
- Task input form
- Voice selection
- Progress bar
- Video player
- Download button


## Deployment & Infrastructure

### Docker
**Version:** Latest stable

**Vai trò:**
- Containerization
- Consistent environment
- Easy deployment


### Chrome Headless Shell
**Version:** Latest stable

**Vai trò:**
- Browser engine cho headless recording
- Lightweight alternative to full Chrome


