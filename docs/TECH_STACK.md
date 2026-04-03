# Tech Stack - Công nghệ sử dụng

## Tổng quan

Dự án sử dụng stack công nghệ hiện đại, kết hợp AI, OS automation, và video processing để tạo ra hệ thống tự động hóa quay video hướng dẫn cho cả Web Browser và Desktop Applications.

## Kiến trúc 2 Pipeline

### 1. Web Browser Pipeline (desktop_app/)
- Automation: browser-use + Playwright
- Recording: webreel (Node.js)
- Target: Chrome, Edge, Firefox

### 2. Desktop OS Pipeline (os_recorder/)
- Automation: pywinauto + Gemini Vision
- Recording: FFmpeg direct capture
- Target: Excel, Word, PowerPoint, Notepad, Desktop Apps

## AI & Machine Learning

### Google Gemini
**Model:** gemini-3.1-flash-lite-preview

**Vai trò:**
- LLM chính điều khiển OS Planning Agent
- Vision model phân tích screenshot + UI element tree
- Generate narration script tự nhiên

**Đặc điểm:**
- Temperature: 0.3 (balance giữa creativity và accuracy)
- Output format: JSON
- Context window: 1M tokens
- Vision capabilities: Screenshot analysis
- Fast response time (~2-5s)

**Use cases trong OS Pipeline:**
1. Screenshot + UI tree analysis
2. Action planning (click, type, hotkey)
3. Narration generation (Vietnamese with diacritics)
4. Loop detection và error recovery

**System Prompts:**
- General: OS automation với UI element indexing
- PowerPoint: Lecturer mode với slide navigation
- Browser: Coordinate grid-based clicking

### Edge TTS (Microsoft Azure)
**Library:** edge-tts (Python)

**Vai trò:**
- Text-to-Speech engine chính (thay thế FPT.AI)
- Parallel audio generation với asyncio

**Giọng đọc hỗ trợ:**
- vi-VN-HoaiMyNeural (nữ, miền Bắc) - default
- vi-VN-NamMinhNeural (nam, miền Bắc)
- en-US-AriaNeural (female)
- en-US-GuyNeural (male)

**Đặc điểm:**
- Output: MP3 format
- Async generation với asyncio.gather
- Rate control: +/-20%
- Free, unlimited usage
- Exact duration measurement

**Usage:**
```python
from core.tts_edge import _generate_speech_async

async def generate_all():
    tasks = [_generate_speech_async(text, path, voice) for ...]
    results = await asyncio.gather(*tasks)
```

## OS Automation

### pywinauto
**Version:** Latest

**Vai trò:**
- Windows UI Automation framework
- Silent execution (không chiếm chuột)
- Element tree inspection

**Backend:** UIA (UI Automation)

**Key Features:**
- Connect to process by PID
- Element tree traversal
- Silent click/type (không di chuyển chuột vật lý)
- Window focus management

**Usage:**
```python
from pywinauto import Application

app = Application(backend="uia").connect(process=pid)
window = app.top_window()
window.set_focus()
```

**Supported Actions:**
- click_element: Click by element index
- type_text: Type into focused element
- press_key: Single key press
- press_hotkey: Key combinations (Ctrl+B, etc.)
- drag_mouse: Drag selection
- scroll: Mouse wheel scroll

### UI Element Tree Pruning
**Module:** core/ui_inspector.py

**Vai trò:**
- Giảm DOM explosion (hàng trăm elements → vài chục)
- Chỉ gửi interactive elements cho LLM

**Interactive Types:**
- Button, Edit, Document, MenuItem
- Hyperlink, ListItem, TreeItem
- CheckBox, RadioButton, ComboBox
- DataGrid, Table

**Indexed Element Format:**
```
[0] Button "Bold" #BoldButton (450,120) 32x24
[1] Edit "Document1" (640,300) 800x600
```

## Browser Automation (Web Pipeline)

### browser-use
**Version:** 0.12.0+

**Vai trò:**
- AI-powered browser automation
- Accessibility Tree parsing
- Action history collection

**Usage:**
```python
from browser_use import Agent
from langchain_google_genai import ChatGoogleGenerativeAI

llm = ChatGoogleGenerativeAI(model="gemini-2.0-flash-exp")
agent = Agent(task="Your task", llm=llm)
history = await agent.run()
```

### Playwright
**Version:** 1.40.0+

**Vai trò:**
- Browser engine cho browser-use
- CDP (Chrome DevTools Protocol) connection

## Video Recording & Processing

### FFmpeg
**Version:** Latest stable

**Vai trò:**
- Screen capture (OS Pipeline)
- Audio mixing (trace-driven composition)
- Video encoding

**OS Recording:**
```bash
ffmpeg -f gdigrab -framerate 60 -i title="Window Title" \
  -c:v libx264 -crf 18 -preset ultrafast output.mp4
```

**Audio Mixing (Trace-Driven):**
```bash
ffmpeg -i video.mp4 -i audio1.mp3 -i audio2.mp3 \
  -filter_complex "[1]adelay=2000|2000[a1];[2]adelay=5000|5000[a2];[a1][a2]amix=2[aout]" \
  -map 0:v -map "[aout]" -c:v copy -c:a aac output.mp4
```

### webreel
**Version:** Custom build từ monorepo

**Vai trò:**
- Browser recording engine (Web Pipeline only)
- Cursor overlay + HUD
- Timeline JSON generation

**Output:**
- MP4 video (CRF 18, 60fps)
- PNG thumbnail
- Execution trace JSON

### Trace-Driven Composition
**Module:** core/trace_composer.py

**Vai trò:**
- Sync audio với video dựa trên execution trace
- Exact timestamp placement (không estimation)

**Strategy:**
1. Parse trace để lấy timestamp thực tế của mỗi action
2. Map narration index → trace step với [TTS:idx] tag
3. Place audio tại start_time của step tương ứng
4. Prevent overlap với buffer 800ms

**Trace Format:**
```json
[
  {
    "step_index": 0,
    "action_type": "click_element",
    "description": "[TTS:0] Click vào nút Bold",
    "start_time_ms": 2000,
    "end_time_ms": 2500
  }
]
```

## Backend & Core

### Python
**Version:** 3.12+

**Vai trò:**
- Ngôn ngữ chính của cả 2 pipeline
- Orchestration và coordination

**Project Structure:**
```
webreel-ai-agent/
├── desktop_app/              # Web Browser Pipeline
│   ├── pipeline_runner.py    # Main orchestrator
│   ├── browser_launcher.py   # CDP launcher
│   └── output/               # Video projects
├── os_recorder/              # Desktop OS Pipeline
│   ├── os_pipeline_main.py   # Main orchestrator
│   ├── core/
│   │   ├── os_planning_agent_v2.py  # Gemini Vision Agent
│   │   ├── os_executor_v2.py        # pywinauto executor
│   │   ├── trace_composer.py        # Audio sync
│   │   └── tts_edge.py              # Edge TTS
│   └── workspace/output/     # Video projects
├── dual_output_pipeline/     # Document generation
│   ├── core/
│   │   └── screenshot_capture.py
│   └── renderers/
│       ├── document_renderer.py  # DOCX
│       └── pdf_renderer.py       # PDF
└── app_flet_unified.py       # Desktop UI (Flet)
```

### Node.js
**Version:** 20+

**Vai trò:**
- Runtime cho webreel (Web Pipeline only)
- Package management với pnpm

## Frontend & UI

### Flet
**Version:** Latest

**Vai trò:**
- Cross-platform desktop UI
- Unified interface cho cả 2 pipeline
- Real-time progress tracking

**Features:**
- Environment selector (Web/Desktop)
- Target app dropdown (Excel, Word, PowerPoint, etc.)
- TTS settings (voice, engine)
- Job queue management
- Phase 2.5 Review UI (edit narration script)
- Phase 3 Ready-to-Record confirmation
- Video history với dual output support
- Delete video confirmation dialog

**UI Components:**
- Task input (multiline TextField)
- Video name input
- CDP port selector (Web mode)
- Target app selector (Desktop mode)
- Dual output checkbox (DOCX + PDF)
- Jobs list với progress bars
- History list với video cards

## Dual Output System

### Screenshot Capture
**Module:** dual_output_pipeline/core/screenshot_capture.py

**Vai trò:**
- Chụp screenshot sau mỗi action step
- Highlight element đang tương tác
- Placeholder generation khi fail

**Strategy:**
- Callback-based: gọi sau mỗi action trong replay
- Retry logic: max 3 retries với delay
- Fallback: placeholder image với error message

### Document Renderer
**Module:** dual_output_pipeline/renderers/document_renderer.py

**Vai trò:**
- Generate DOCX tutorial từ screenshots + narrations
- Professional formatting với python-docx

**Output:**
- Title page
- Step-by-step instructions
- Screenshots với captions
- Narration text

### PDF Renderer
**Module:** dual_output_pipeline/renderers/pdf_renderer.py

**Vai trò:**
- Generate PDF tutorial từ screenshots + narrations
- Professional layout với ReportLab

**Output:**
- Same content as DOCX
- PDF format for easy sharing

## Deployment & Infrastructure

### Windows-only
**Platform:** Windows 10/11

**Lý do:**
- pywinauto chỉ hỗ trợ Windows
- gdigrab (FFmpeg) cho screen capture
- UIA (UI Automation) API

### Python Virtual Environment
**Tool:** venv hoặc conda

**Setup:**
```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

### Environment Variables
**File:** .env

**Required:**
```
GEMINI_API_KEY=your_key_here
```

**Optional:**
```
FFMPEG_PATH=C:\path\to\ffmpeg.exe
```


