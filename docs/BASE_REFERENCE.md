# Base Reference - Tài liệu tham khảo nền tảng

## Giới thiệu dự án

AI Agent Video Tutor là hệ thống tự động hóa quay video hướng dẫn thực hành từ mô tả văn bản bằng tiếng Việt hoặc tiếng Anh. Hệ thống sử dụng AI Agent để điều khiển trình duyệt, ghi lại các thao tác và tạo video MP4 hoàn chỉnh kèm giọng thuyết minh.

**Sinh viên thực hiện:** Nguyễn Văn Tổng

**Năm học:** 2025-2026

**Loại đồ án:** Đồ án tốt nghiệp/cấp cơ sở

## Bài toán cần giải quyết

### Vấn đề hiện tại
- Tạo video hướng dẫn thực hành tốn nhiều thời gian và công sức
- Cần quay lại nhiều lần để có video chất lượng
- Khó đồng bộ giọng thuyết minh với hành động trên màn hình
- Quy trình thủ công, không thể tự động hóa

### Giải pháp đề xuất
Xây dựng hệ thống tự động:
1. Nhận mô tả tác vụ bằng ngôn ngữ tự nhiên
2. AI Agent tự động thực hiện tác vụ trong trình duyệt
3. Ghi lại toàn bộ thao tác thành video
4. Tạo giọng thuyết minh tiếng Việt tự nhiên
5. Đồng bộ audio và video thành sản phẩm hoàn chỉnh

### Đầu vào và đầu ra

**Đầu vào:**
- Mô tả tác vụ bằng ngôn ngữ tự nhiên (tiếng Việt hoặc tiếng Anh)
- Ví dụ: "Vào google.com và tìm kiếm Python programming"

**Đầu ra:**
- File video MP4 hoàn chỉnh
- Chuyển động chuột mượt mà với Bezier curves
- Giọng thuyết minh tiếng Việt tự nhiên (tùy chọn)
- Phụ đề đồng bộ (tùy chọn)

## Kiến trúc hệ thống

### Tổng quan kiến trúc

```
┌─────────────────────────────────────────────────────────────┐
│                    USER INPUT LAYER                         │
│  - Streamlit Web UI                                         │
│  - CLI Interface                                            │
│  - API Endpoint (future)                                    │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│                  AI AGENT LAYER                             │
│  - Google Gemini LLM                                        │
│  - browser-use Framework                                    │
│  - Playwright Browser Automation                            │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│                  PROCESSING LAYER                           │
│  - Parser: browser-use → webreel config                     │
│  - AI Reviewer: Optimize config + Generate TTS script       │
│  - Timeline Calculator                                      │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│                  RECORDING LAYER                            │
│  - webreel: Browser recording engine                        │
│  - Chrome headless-shell                                    │
│  - FFmpeg video encoding                                    │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│                  AUDIO LAYER                                │
│  - FPT.AI Text-to-Speech                                    │
│  - Multiple Vietnamese voices                               │
│  - MP3 audio segments                                       │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│                  COMPOSITION LAYER                          │
│  - MoviePy: Video + Audio merge                             │
│  - Timeline synchronization                                 │
│  - Subtitle generation (optional)                           │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│                    OUTPUT LAYER                             │
│  - Final MP4 video                                          │
│  - Thumbnail PNG                                            │
│  - Metadata JSON                                            │
└─────────────────────────────────────────────────────────────┘
```

### Luồng dữ liệu chi tiết

1. **User Input → AI Agent**
   - Input: Text prompt (tiếng Việt/Anh)
   - Process: Gemini LLM phân tích và lập kế hoạch
   - Output: Action plan

2. **AI Agent → Browser Automation**
   - Input: Action plan
   - Process: browser-use + Playwright thực hiện
   - Output: Action history với DOM elements

3. **Browser History → Parser**
   - Input: browser-use action history
   - Process: Extract selectors, coordinates, timing
   - Output: webreel config JSON

4. **Config → AI Reviewer**
   - Input: webreel config + original prompt
   - Process: Gemini review và tối ưu
   - Output: Enhanced config + TTS script

5. **Enhanced Config → Video Recording**
   - Input: webreel config
   - Process: Chrome headless-shell + FFmpeg
   - Output: Raw MP4 video

6. **TTS Script → Audio Generation**
   - Input: TTS script với timeline
   - Process: FPT.AI text-to-speech
   - Output: MP3 audio segments

7. **Video + Audio → Composition**
   - Input: MP4 video + MP3 audio + timeline
   - Process: MoviePy merge và sync
   - Output: Final MP4 với audio

## Các thành phần chính

### 1. AI Agent (browser-use)
- Framework tự động hóa trình duyệt bằng AI
- Sử dụng Accessibility Tree thay vì OCR
- Tự động trích xuất DOM elements
- Ghi lại đầy đủ action history

### 2. Parser (bu_to_webreel)
- Chuyển đổi browser-use actions sang webreel config
- Trích xuất CSS selectors theo thứ tự ưu tiên
- Tính toán timing chính xác
- Tuân thủ nghiêm ngặt webreel schema v1

### 3. AI Reviewer
- Review và tối ưu webreel config
- Sửa lỗi selector tự động
- Tạo TTS script tự nhiên với timeline
- Đảm bảo đồng bộ audio/video

### 4. Webreel Engine
- Công cụ ghi hình trình duyệt chuyên nghiệp
- Hỗ trợ cursor overlay và HUD
- FFmpeg encoding với CRF 18, 60fps
- Output MP4 chất lượng cao

### 5. TTS Engine (FPT.AI)
- Text-to-speech tiếng Việt tự nhiên
- Nhiều giọng đọc: banmai, leminh, thuminh, etc.
- API async cho performance tốt
- Output MP3 segments

### 6. Video Composer (MoviePy)
- Merge video và audio
- Sync timeline chính xác
- Tạo phụ đề (optional)
- Export final MP4

## Tài liệu tham khảo

### Công nghệ sử dụng

1. **browser-use**
   - GitHub: https://github.com/browser-use/browser-use
   - Docs: https://docs.browser-use.com
   - Version: 0.12.0+

2. **webreel**
   - Website: https://webreel.dev
   - Schema: https://webreel.dev/schema/v1.json
   - GitHub: https://github.com/AI-RDI/pre-ai-edtech

3. **Google Gemini**
   - Docs: https://ai.google.dev/gemini-api/docs
   - Model: gemini-2.0-flash-exp
   - SDK: google-genai

4. **FPT.AI TTS**
   - Docs: https://fpt.ai/vi/tts
   - API: https://api.fpt.ai/hmi/tts/v5
   - Voices: banmai, leminh, thuminh, etc.

5. **Playwright**
   - Docs: https://playwright.dev/python
   - Version: 1.40.0+

6. **MoviePy**
   - GitHub: https://github.com/Zulko/moviepy
   - Docs: https://zulko.github.io/moviepy

### Chuẩn và quy ước

1. **Webreel Schema v1**
   - Tuân thủ nghiêm ngặt schema
   - Không thêm key không hợp lệ
   - Validate trước khi record

2. **CSS Selector Priority**
   - text > title > id > name > class > aria-label > XPath
   - URL decode cho href attributes
   - Fallback gracefully

3. **Timeline Calculation**
   - Pause: ms / 1000
   - Navigate: ~2s
   - Click: ~0.5s
   - Type: len(text) * charDelay
   - Scroll: ~1s

4. **Docker Best Practices**
   - Multi-stage build
   - Layer caching optimization
   - Volume mount cho output
   - Health check

## Giới hạn và ràng buộc

### Giới hạn kỹ thuật

1. **Browser Automation**
   - Chỉ hỗ trợ Chromium-based browsers
   - Một số trang web có bot detection
   - Cần xử lý CAPTCHA thủ công

2. **AI Agent**
   - Phụ thuộc vào Gemini API quota
   - Có thể fail với task phức tạp
   - Cần prompt engineering tốt

3. **Video Recording**
   - Headless mode có thể khác headed
   - Một số element không render đúng
   - Cần điều chỉnh timing

4. **TTS**
   - Chỉ hỗ trợ tiếng Việt (FPT.AI)
   - Giới hạn ký tự mỗi request
   - Chi phí API

### Ràng buộc hệ thống

1. **Resource Requirements**
   - RAM: 2-4GB minimum
   - CPU: 2-4 cores recommended
   - Disk: ~100MB per video
   - Network: Stable internet cho API calls

2. **Dependencies**
   - Python 3.12+
   - Node.js 20+
   - FFmpeg
   - Chrome headless-shell

3. **API Keys Required**
   - GEMINI_API_KEY (bắt buộc)
   - FPT_API_KEY (cho TTS)

## Roadmap phát triển

### Phase 1: Core Features (Tuần 1-2)
- ✅ Browser automation với browser-use
- ✅ Parser chuyển đổi actions
- ✅ Webreel integration
- ✅ Basic video recording

### Phase 2: AI Enhancement (Tuần 2-3)
- ✅ AI Reviewer module
- ✅ TTS integration
- ✅ Timeline synchronization
- ✅ Config optimization

### Phase 3: UI & UX (Tuần 3-4)
- ✅ Streamlit web interface
- ✅ Video composer
- ✅ Subtitle generation
- ✅ Progress tracking

### Phase 4: Production (Tuần 4-5)
- ✅ Docker containerization
- ✅ Error handling
- ✅ Documentation
- ✅ Demo videos

### Future Enhancements
- Multi-language TTS support
- Cloud storage integration
- Batch processing
- Custom themes
- Live preview
- Quality presets
- Caching layer
- Web dashboard

## Kết luận

Hệ thống AI Agent Video Tutor là giải pháp tự động hóa hoàn chỉnh cho việc tạo video hướng dẫn thực hành. Bằng cách kết hợp AI, browser automation, và video processing, hệ thống giúp giảm đáng kể thời gian và công sức tạo nội dung giáo dục chất lượng cao.
