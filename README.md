# AI AGENT VIDEO TUTOR - TỰ ĐỘNG HÓA QUAY VIDEO HƯỚNG DẪN

Sinh viên thực hiện: Nguyễn Văn Tổng

## 1. Tổng quan bài toán (Project Overview)

Dự án xây dựng hệ thống tự động tạo video hướng dẫn thực hành từ mô tả văn bản bằng cách sử dụng AI Agent để điều khiển trình duyệt và ghi lại thành video MP4 hoàn chỉnh.

**Đầu vào (Input):** Mô tả tác vụ bằng ngôn ngữ tự nhiên (tiếng Việt hoặc tiếng Anh)

**Mục tiêu (Goal):** Tự động hóa quy trình quay video thực hành, giảm thời gian và công sức tạo nội dung giáo dục

**Đầu ra (Output):** File video MP4 hoàn chỉnh với chuyển động chuột, thao tác và có thể kèm theo giải thích bằng giọng nói

## 2. Công nghệ sử dụng (Tech Stack)

**AI Engine & Xử lý lõi:**
- Google Gemini (gemini-3.1-flash-lite-preview): LLM điều khiển AI Agent
- browser-use: Framework tự động hóa trình duyệt bằng AI
- FPT.AI TTS: Text-to-speech tiếng Việt

**Backend / Điều phối:**
- Python 3.12+
- Playwright: Điều khiển trình duyệt
- webreel: Công cụ ghi hình trình duyệt

**Triển khai & Môi trường:**
- Docker & Docker Compose
- Chrome headless-shell

## 3. Luồng xử lý hệ thống (System Pipeline)

```
User Prompt (Văn bản mô tả)
    |
    v
browser-use Agent (Thực hiện tác vụ trong trình duyệt)
    |
    v
Parser (Chuyển đổi action history sang webreel config)
    |
    v
AI Reviewer (Review và tối ưu config, tạo TTS script)
    |
    v
webreel (Quay video từ config)
    |
    v
Video Composer (Merge audio + video)
    |
    v
Output: Video MP4 hoàn chỉnh
```

## 4. Kế hoạch & Tiến độ triển khai

<table>
<tr>
<th>Tuần</th>
<th>Nhiệm vụ trọng tâm</th>
<th>Kết quả đầu ra (Deliverable)</th>
</tr>
<tr>
<td>Tuần 1</td>
<td>Tích hợp browser-use và Playwright để truy cập Cây trợ năng (Accessibility Tree), tự động bóc tách DOM thay vì dùng OCR. Nghiên cứu engine kết xuất Webreel.</td>
<td>browser-use Agent hoạt động, truy cập được DOM và Accessibility Tree, hiểu cơ chế Webreel</td>
</tr>
<tr>
<td>Tuần 2</td>
<td>Sử dụng LLM phân rã kịch bản tiếng Việt. Viết Trình biên dịch (JSON Parser) bằng Python để ánh xạ log hành động thành file cấu hình chuẩn của Webreel.</td>
<td>Parser hoàn chỉnh, chuyển đổi action history sang webreel config, AI Reviewer tối ưu config</td>
</tr>
<tr>
<td>Tuần 3</td>
<td>Xây dựng giao diện Streamlit. Tích hợp Text-to-Speech (FPT.AI Neural TTS) để sinh giọng đọc tự nhiên.</td>
<td>Streamlit UI hoạt động, TTS tích hợp, tạo được audio narration tiếng Việt</td>
</tr>
<tr>
<td>Tuần 4</td>
<td>Tích hợp MoviePy để đồng bộ hóa âm thanh với hành động chuột (Bezier curves). Render tự động ra file video .mp4.</td>
<td>Video Composer hoàn chỉnh, merge audio + video, output MP4 với audio sync</td>
</tr>
<tr>
<td>Tuần 5</td>
<td>Container hóa toàn bộ hệ thống bằng Docker (tối ưu Layer Caching cho Node.js và Python). Sinh 5 video thực hành mẫu.</td>
<td>Docker image production-ready, 5 video demo hoàn chỉnh, tài liệu đầy đủ</td>
</tr>
</table>

## 5. Hướng dẫn cài đặt & Khởi chạy (Setup & Run)

### Yêu cầu hệ thống (Prerequisites)

- Đã cài đặt Python 3.12+
- Đã cài đặt Node.js 18+
- Đã cài đặt Docker (khuyến nghị)
- Các API Keys cần thiết: Gemini API Key, FPT.AI API Key (cho TTS)

### Các bước cài đặt

**Bước 1:** Clone kho lưu trữ và chuyển sang branch của dự án này

```bash
git clone git@github.com:AI-RDI/pre-ai-edtech.git
cd pre-ai-edtech
git checkout ai-agent-video-tutor
```

**Bước 2:** Cài đặt thư viện phụ thuộc (Dependencies)

```bash
# Cài đặt webreel (từ thư mục gốc)
pnpm install
pnpm build

# Chuyển vào thư mục dự án
cd webreel-ai-agent

# Tạo virtual environment
python -m venv venv
source venv/bin/activate  # Linux/Mac
.\venv\Scripts\activate   # Windows

# Cài đặt dependencies
pip install -r requirements.txt
```

**Bước 3:** Thiết lập biến môi trường

Tạo file .env từ file .env.example và điền các thông tin bảo mật:

```bash
cp .env.example .env
```

Nội dung file .env:

```
GEMINI_API_KEY=your_gemini_api_key_here
FPT_API_KEY=your_fpt_api_key_here
```

**Bước 4:** Khởi chạy dự án

Chạy bằng Docker (khuyến nghị):

```bash
docker-compose up --build
```

Hoặc chạy trực tiếp:

```bash
python run_pipeline.py "Vào google.com và tìm kiếm Python" --name demo
```

Output:
- Config: output/demo/webreel_pipeline.config.json
- Video: output/demo/videos/demo.mp4

---

Ghi chú: Mã nguồn và tài liệu thuộc khuôn khổ đồ án tốt nghiệp/cấp cơ sở năm học 2025-2026.
