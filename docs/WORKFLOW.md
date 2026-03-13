# Workflow - Luồng làm việc & Quy trình

## Tổng quan

Tài liệu này mô tả chi tiết luồng làm việc của hệ thống AI Agent Video Tutor, từ input của user đến output video hoàn chỉnh.

## Pipeline Overview

```
┌─────────────────┐
│  User Input     │  Mô tả tác vụ bằng ngôn ngữ tự nhiên
└────────┬────────┘
         │
         ▼
┌─────────────────────────────────┐
│  Phase 1: Browser Automation    │  30-60s
│  - Gemini AI planning           │
│  - Playwright execution         │
│  - Action history collection    │
└────────┬────────────────────────┘
         │
         ▼
┌─────────────────────────────────┐
│  Phase 2: Config Generation     │  <1s
│  - Parse actions                │
│  - Extract selectors            │
│  - Calculate timing             │
└────────┬────────────────────────┘
         │
         ▼
┌─────────────────────────────────┐
│  Phase 3: AI Review             │  5-10s
│  - Validate config              │
│  - Fix errors                   │
│  - Generate TTS script          │
└────────┬────────────────────────┘
         │
         ▼
┌─────────────────────────────────┐
│  Phase 4: Video Recording       │  10-30s
│  - Chrome headless-shell        │
│  - Execute webreel config       │
│  - Output raw MP4               │
└────────┬────────────────────────┘
         │
         ▼
┌─────────────────────────────────┐
│  Phase 5: Audio Generation      │  2-5s/segment
│  - FPT.AI TTS                   │
│  - Download MP3 segments        │
└────────┬────────────────────────┘
         │
         ▼
┌─────────────────────────────────┐
│  Phase 6: Video Composition     │  5-10s
│  - Merge video + audio          │
│  - Sync timeline                │
│  - Add subtitles (optional)     │
└────────┬────────────────────────┘
         │
         ▼
┌─────────────────┐
│  Final Video    │  MP4 + thumbnail + metadata
└─────────────────┘
```

## Phase 1: Browser Automation

### Input
- Task description (string)
- Optional: Starting URL

### Process

1. **Initialize Agent**
```python
from browser_use import Agent
from langchain_google_genai import ChatGoogleGenerativeAI

llm = ChatGoogleGenerativeAI(
    model="gemini-2.0-flash-exp",
    temperature=0.3
)

agent = Agent(
    task="Vào google.com và tìm kiếm Python",
    llm=llm
)
```

2. **Execute Task**
```python
history = await agent.run()
```

3. **Collect Action History**
- Navigate actions với URLs
- Click actions với element info
- Input actions với text và selectors
- Scroll actions (sẽ bị skip sau này)
- Wait actions với duration

### Output
```json
{
  "task": "Vào google.com và tìm kiếm Python",
  "urls": ["https://google.com"],
  "model_actions": [
    {
      "navigate": {"url": "https://google.com"},
      "interacted_element": null
    },
    {
      "input": {"index": 2, "text": "Python"},
      "interacted_element": "DOMInteractedElement(...)"
    }
  ]
}
```

### Error Handling
- Retry on network errors (max 3 times)
- Fallback to simpler selectors
- Log all errors for debugging
- Continue pipeline even if some actions fail

---

## Phase 2: Config Generation (Parser)

### Input
- browser-use action history (JSON)
- Video name

### Process

1. **Initialize Config**
```python
config = {
    "$schema": "https://webreel.dev/schema/v1.json",
    "videos": {
        video_name: {
            "url": first_url,
            "steps": []
        }
    }
}
```

2. **Parse Each Action**
```python
for action in history["model_actions"]:
    if "navigate" in action:
        # Skip navigate (already in url field)
        continue
    
    elif "click" in action:
        selector = extract_selector(action["interacted_element"])
        steps.append({
            "action": "click",
            "selector": selector
        })
    
    elif "input" in action:
        selector = extract_selector(action["interacted_element"])
        text = action["input"]["text"]
        steps.append({
            "action": "type",
            "selector": selector,
            "text": text
        })
    
    elif "wait" in action:
        ms = action["wait"]["seconds"] * 1000
        steps.append({
            "action": "pause",
            "ms": ms
        })
```

3. **Extract Selectors (Priority Order)**
```python
def extract_selector(element):
    # 1. Text content (most reliable)
    if element.text:
        return f'text="{element.text}"'
    
    # 2. Title attribute
    if element.title:
        return f'[title="{element.title}"]'
    
    # 3. ID
    if element.id:
        return f'#{element.id}'
    
    # 4. Name (for forms)
    if element.name:
        return f'[name="{element.name}"]'
    
    # 5. Class
    if element.class_name:
        return f'.{element.class_name}'
    
    # 6. Aria-label
    if element.aria_label:
        return f'[aria-label="{element.aria_label}"]'
    
    # 7. XPath fallback
    return element.xpath
```

### Output
```json
{
  "$schema": "https://webreel.dev/schema/v1.json",
  "videos": {
    "demo": {
      "url": "https://google.com",
      "steps": [
        {
          "action": "type",
          "selector": "#APjFqb",
          "text": "Python"
        },
        {
          "action": "click",
          "selector": "input[name=\"btnK\"]"
        }
      ]
    }
  }
}
```

### Validation
- Check schema compliance
- Verify all required fields
- Validate selector syntax
- Test config với dry-run (optional)

---

## Phase 3: AI Review & Enhancement

### Input
- Webreel config (JSON)
- Original task description
- Action history

### Process

1. **Calculate Timeline**
```python
def calculate_timeline(steps):
    timeline = []
    current_time = 0.0
    
    for step in steps:
        if step["action"] == "pause":
            duration = step["ms"] / 1000
        elif step["action"] == "navigate":
            duration = 2.0
        elif step["action"] == "click":
            duration = 0.5
        elif step["action"] == "type":
            duration = len(step["text"]) * 0.1
        else:
            duration = 1.0
        
        timeline.append({
            "action": step["action"],
            "start_time": current_time,
            "end_time": current_time + duration
        })
        
        current_time += duration + 0.5  # defaultDelay
    
    return timeline
```

2. **AI Review Prompt**
```python
prompt = f"""
Bạn là chuyên gia review cấu hình webreel.

Task gốc: {task}
Config hiện tại: {json.dumps(config)}
Timeline: {json.dumps(timeline)}

Nhiệm vụ:
1. Kiểm tra config có hợp lệ không
2. Sửa lỗi selector nếu có (ưu tiên text selector)
3. Điều chỉnh timing cho mượt mà
4. Tạo script thuyết minh tiếng Việt tự nhiên

Output JSON:
{{
  "enhanced_config": {{...}},
  "tts_script": [
    {{"text": "...", "start_time": 0.0, "end_time": 3.0}}
  ],
  "review_notes": "..."
}}
"""
```

3. **Call Gemini API**
```python
from google import genai

client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
response = client.models.generate_content(
    model="gemini-2.0-flash-exp",
    contents=prompt,
    config={
        "temperature": 0.3,
        "response_mime_type": "application/json"
    }
)

result = json.loads(response.text)
```

### Output
```json
{
  "enhanced_config": {
    "$schema": "https://webreel.dev/schema/v1.json",
    "videos": {
      "demo": {
        "url": "https://google.com",
        "steps": [
          {"action": "pause", "ms": 1000},
          {"action": "type", "selector": "textarea[name=\"q\"]", "text": "Python"},
          {"action": "pause", "ms": 500},
          {"action": "click", "selector": "text=\"Google Search\""}
        ]
      }
    }
  },
  "tts_script": [
    {
      "text": "Chúng ta bắt đầu bằng cách truy cập Google",
      "start_time": 0.0,
      "end_time": 2.5
    },
    {
      "text": "Tiếp theo, nhập từ khóa Python vào ô tìm kiếm",
      "start_time": 3.0,
      "end_time": 6.0
    },
    {
      "text": "Cuối cùng, nhấp vào nút Google Search để tìm kiếm",
      "start_time": 6.5,
      "end_time": 9.5
    }
  ],
  "review_notes": "Đã thêm pause để trang load, sửa selector thành text-based"
}
```

### Fallback
Nếu AI review fail:
- Sử dụng config gốc từ parser
- TTS script rỗng (skip audio)
- Log warning và continue

---

## Phase 4: Video Recording

### Input
- Enhanced webreel config
- Video name

### Process

1. **Save Config**
```python
config_path = output_dir / "webreel_pipeline.config.json"
with open(config_path, "w") as f:
    json.dump(enhanced_config, f, indent=2)
```

2. **Execute Webreel**
```bash
cd output_dir
npx webreel record
```

3. **Webreel Internal Process**
- Launch Chrome headless-shell
- Navigate to URL
- Execute each step sequentially
- Record frames with FFmpeg
- Overlay cursor và HUD
- Generate thumbnail
- Save timeline JSON

### Output Structure
```
output/demo/
├── .webreel/
│   ├── raw/
│   │   └── demo.mp4          # Raw recording
│   └── timelines/
│       └── demo.timeline.json
├── videos/
│   ├── demo.mp4              # Final video (before audio)
│   └── demo.png              # Thumbnail
└── webreel_pipeline.config.json
```

### Error Handling
- Timeout after 60s per step
- Retry failed steps (max 2 times)
- Screenshot on error
- Detailed error logs

---

## Phase 5: Audio Generation

### Input
- TTS script với timeline
- Voice selection

### Process

1. **Generate Audio Segments**
```python
async def generate_tts_segments(tts_script, voice="banmai"):
    segments = []
    
    for i, item in enumerate(tts_script):
        output_path = f"tts/segment_{i}.mp3"
        
        # Call FPT.AI API
        url = "https://api.fpt.ai/hmi/tts/v5"
        headers = {
            "api-key": os.getenv("FPT_API_KEY"),
            "voice": voice,
            "speed": "0"
        }
        
        response = requests.post(
            url,
            headers=headers,
            data=item["text"].encode('utf-8')
        )
        
        # Download MP3
        audio_url = response.json()["async"]
        audio_data = requests.get(audio_url).content
        
        with open(output_path, "wb") as f:
            f.write(audio_data)
        
        segments.append({
            "path": output_path,
            "start_time": item["start_time"],
            "end_time": item["end_time"],
            "text": item["text"]
        })
    
    return segments
```

2. **Validate Audio Duration**
```python
from pydub import AudioSegment

for segment in segments:
    audio = AudioSegment.from_mp3(segment["path"])
    actual_duration = len(audio) / 1000.0
    expected_duration = segment["end_time"] - segment["start_time"]
    
    if actual_duration > expected_duration:
        # Speed up audio
        audio = audio.speedup(playback_speed=actual_duration/expected_duration)
        audio.export(segment["path"], format="mp3")
```

### Output
```
output/demo/tts/
├── segment_0.mp3
├── segment_1.mp3
└── segment_2.mp3
```

### Error Handling
- Retry API calls (max 3 times)
- Skip segment on persistent failure
- Log warnings
- Continue with available segments

---

## Phase 6: Video Composition

### Input
- Video file (MP4)
- Audio segments (MP3)
- TTS script với timeline
- Subtitle flag (optional)

### Process

1. **Load Video**
```python
from moviepy.editor import VideoFileClip

video = VideoFileClip("videos/demo.mp4")
video_duration = video.duration
```

2. **Create Audio Track**
```python
from moviepy.editor import AudioFileClip, CompositeAudioClip

audio_clips = []

for segment in audio_segments:
    audio = AudioFileClip(segment["path"])
    audio = audio.set_start(segment["start_time"])
    audio_clips.append(audio)

final_audio = CompositeAudioClip(audio_clips)
```

3. **Merge Video + Audio**
```python
final_video = video.set_audio(final_audio)
```

4. **Add Subtitles (Optional)**
```python
from moviepy.video.tools.subtitles import SubtitlesClip

# Generate SRT
srt_content = generate_srt(tts_script)
with open("subtitles.srt", "w") as f:
    f.write(srt_content)

# Add to video
subtitles = SubtitlesClip("subtitles.srt", make_textclip)
final_video = CompositeVideoClip([final_video, subtitles])
```

5. **Export Final Video**
```python
final_video.write_videofile(
    "output/demo/final_demo.mp4",
    codec='libx264',
    audio_codec='aac',
    fps=60,
    bitrate='5000k'
)
```

### Output
```
output/demo/
├── final_demo.mp4           # Final video với audio
├── subtitles.srt            # Subtitle file (if enabled)
└── metadata.json            # Video metadata
```

### Quality Settings
- Video codec: H.264 (libx264)
- Audio codec: AAC
- FPS: 60
- Bitrate: 5000k
- Resolution: 1920x1080

---

## Complete Workflow Example

### CLI Usage
```bash
python run_pipeline.py \
  "Vào google.com và tìm kiếm Python programming" \
  --name google-search \
  --voice banmai \
  --subtitle
```

### Programmatic Usage
```python
import asyncio
from run_pipeline import run_pipeline

async def main():
    video_path = await run_pipeline(
        task="Vào google.com và tìm kiếm Python programming",
        video_name="google-search",
        enable_tts=True,
        tts_voice="banmai",
        enable_subtitle=True
    )
    
    print(f"✅ Video created: {video_path}")

asyncio.run(main())
```

### Streamlit UI
```python
import streamlit as st
from run_pipeline import run_pipeline

st.title("🎬 AI Agent Video Tutor")

task = st.text_area("Mô tả tác vụ")
video_name = st.text_input("Tên video", "demo")
voice = st.selectbox("Giọng đọc", ["banmai", "leminh", "thuminh"])
enable_subtitle = st.checkbox("Thêm phụ đề")

if st.button("Tạo video"):
    with st.spinner("Đang xử lý..."):
        progress_bar = st.progress(0)
        
        # Phase 1: Browser automation
        st.info("Phase 1: Browser automation...")
        progress_bar.progress(20)
        
        # Phase 2-6: Continue...
        video_path = await run_pipeline(
            task=task,
            video_name=video_name,
            enable_tts=True,
            tts_voice=voice,
            enable_subtitle=enable_subtitle
        )
        
        progress_bar.progress(100)
        st.success("✅ Hoàn thành!")
        st.video(video_path)
```

---

## Error Handling Strategy

### Retry Logic
```python
async def with_retry(func, max_retries=3):
    for attempt in range(max_retries):
        try:
            return await func()
        except Exception as e:
            if attempt == max_retries - 1:
                raise
            await asyncio.sleep(2 ** attempt)
```

### Graceful Degradation
1. AI review fails → Use original config
2. TTS fails → Silent video
3. Subtitle fails → Video without subtitles
4. Composition fails → Keep raw video

### Logging
```python
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('pipeline.log'),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)
logger.info("Phase 1: Starting browser automation")
```

---

## Performance Optimization

### Parallel Processing
```python
import asyncio

# Run TTS segments in parallel
tasks = [
    generate_tts(segment["text"], voice, f"segment_{i}.mp3")
    for i, segment in enumerate(tts_script)
]
audio_segments = await asyncio.gather(*tasks)
```

### Caching
```python
from functools import lru_cache

@lru_cache(maxsize=100)
def get_selector(element_hash):
    # Cache selector extraction
    return extract_selector(element)
```

### Resource Management
```python
# Cleanup after each phase
def cleanup():
    # Close browser
    await browser.close()
    
    # Clear temp files
    shutil.rmtree("temp/", ignore_errors=True)
    
    # Free memory
    gc.collect()
```

---

## Monitoring & Metrics

### Track Performance
```python
import time

metrics = {
    "phase1_duration": 0,
    "phase2_duration": 0,
    "phase3_duration": 0,
    "phase4_duration": 0,
    "phase5_duration": 0,
    "phase6_duration": 0,
    "total_duration": 0
}

start = time.time()
# Execute phase
metrics["phase1_duration"] = time.time() - start
```

### Success Rate
```python
stats = {
    "total_videos": 0,
    "successful": 0,
    "failed": 0,
    "success_rate": 0.0
}

# Update after each run
stats["total_videos"] += 1
if success:
    stats["successful"] += 1
else:
    stats["failed"] += 1

stats["success_rate"] = stats["successful"] / stats["total_videos"]
```

---

## Best Practices

### 1. Input Validation
- Validate task description (not empty, reasonable length)
- Check API keys before starting
- Verify output directory exists

### 2. Progress Tracking
- Update progress bar after each phase
- Show meaningful status messages
- Estimate time remaining

### 3. Error Messages
- User-friendly error messages
- Technical details in logs
- Suggest solutions when possible

### 4. Resource Cleanup
- Close browser after use
- Delete temp files
- Free memory

### 5. Testing
- Unit tests for each module
- Integration tests for pipeline
- End-to-end tests with real tasks

---

## Kết luận

Workflow được thiết kế để:
- Tự động hóa tối đa
- Xử lý lỗi gracefully
- Tối ưu performance
- Dễ maintain và extend

Mỗi phase độc lập, có thể test riêng và thay thế nếu cần.
