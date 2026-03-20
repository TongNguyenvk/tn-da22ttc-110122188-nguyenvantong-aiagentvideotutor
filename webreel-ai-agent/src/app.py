"""
Streamlit UI - AI Video Tutor v3.0
Web interface for the V3 Pipeline (6 phases, trace-driven).

Usage:
  cd webreel-ai-agent
  streamlit run src/app.py
"""
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

load_dotenv()

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Import API client and WebSocket client
from frontend.api_client import (
    submit_job, get_job_status, list_jobs, check_backend_health,
    APIClientError, ConnectionFailedError, TimeoutError as APITimeoutError
)
from frontend.websocket_client import track_progress
from src.webreel_runner import OUTPUT_DIR

# Default CDP URL
CDP_URL = "http://localhost:9222"


# ==============================================================================
# Constants & Paths
# ==============================================================================
HISTORY_FILE = OUTPUT_DIR / "video_history.json"


# ==============================================================================
# Helper Functions
# ==============================================================================
def _load_history() -> list:
    """Load video history from JSON file."""
    if HISTORY_FILE.exists():
        try:
            import json
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []
    return []


def _save_history(history: list):
    """Save video history to JSON file."""
    try:
        import json
        HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(history, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"Failed to save history: {e}")


# ==============================================================================
# Page Config
# ==============================================================================
st.set_page_config(
    page_title="AI Video Tutor v3",
    page_icon="V",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ==============================================================================
# Constants
# ==============================================================================
TTS_VOICES_EDGE = {
    "vi-VN-HoaiMyNeural": "Nữ Hoài My (Edge)",
    "vi-VN-NamMinhNeural": "Nam Nam Minh (Edge)",
}

TTS_VOICES_FPT = {
    "banmai": "Nữ miền Bắc (Ban Mai)",
    "leminh": "Nam miền Bắc (Lê Minh)",
    "myan": "Nữ miền Nam (My An)",
    "lannhi": "Nữ miền Nam trẻ (Lan Nhi)",
    "linhsan": "Nữ miền Trung (Linh San)",
}

PIPELINE_STEPS = [
    "Phase 1: The Scout (browser-use + narration)",
    "Phase 2: The Parser (config + tts_script)",
    "Phase 3: Ground-Truth TTS (Edge/FPT)",
    "Phase 4: The Injector (exact pauses)",
    "Phase 5: The Execution (Webreel record)",
    "Phase 6: The Composer (ffmpeg trace-sync)",
]


# ==============================================================================
# Helpers
# ==============================================================================
def _slugify(text: str) -> str:
    """Convert text to a safe filename slug."""
    slug = re.sub(r"[^\w\s-]", "", text.lower())
    slug = re.sub(r"[\s_]+", "-", slug)
    return slug[:40].strip("-") or "demo"


def _init_session():
    """Initialize session state defaults."""
    defaults = {
        "history": _load_history(),
        "video_path": None,
        "is_generating": False,
        "progress_step": 0,
        "progress_total": len(PIPELINE_STEPS),
        "progress_msg": "",
        "error_msg": None,
        "current_job_id": None,
        "progress_tracker": None,
        "backend_healthy": check_backend_health(),
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


class JobProgress:
    """Progress tracker for API-based job execution."""
    def __init__(self):
        self.step = 0
        self.msg = ""
        self.status = "pending"
        self.job_id = None
        self.done = False
        self.error = None
        self.video_url = None
        
    def update_from_api(self, job_data: dict):
        """Update progress from API response."""
        self.status = job_data.get("status", "pending")
        
        # Map status to done flag
        if self.status in ["completed", "failed", "interrupted"]:
            self.done = True
        
        # Extract progress information
        if "progress" in job_data and job_data["progress"]:
            progress = job_data["progress"]
            self.step = progress.get("current_phase", 0)
            self.msg = progress.get("message", "")
        
        # Extract error if failed
        if self.status == "failed" and "error" in job_data:
            self.error = job_data["error"]
        
        # Extract video URL if completed
        if self.status == "completed" and "result" in job_data:
            result = job_data["result"]
            self.video_url = result.get("video_url", "")


def _handle_progress_update(job_data: dict):
    """Handle progress update from WebSocket or polling."""
    if "pipeline_progress" not in st.session_state:
        return
    
    progress = st.session_state.pipeline_progress
    progress.update_from_api(job_data)
    
    # Check if job is complete
    if progress.done:
        # Stop the tracker
        if st.session_state.progress_tracker:
            st.session_state.progress_tracker.stop()
            st.session_state.progress_tracker = None
        
        st.session_state.is_generating = False
        
        if progress.status == "completed":
            # Get the full job details to extract video path
            try:
                job_details = get_job_status(progress.job_id)
                if "result" in job_details and job_details["result"]:
                    result = job_details["result"]
                    video_path = result.get("video_path", "")
                    st.session_state.video_path = video_path
                    
                    # Add to history
                    history_item = {
                        "script": job_details.get("task", ""),
                        "path": video_path,
                        "name": job_details.get("video_name", ""),
                        "created_at": datetime.now().strftime("%d/%m/%Y %H:%M"),
                        "job_id": progress.job_id,
                    }
                    st.session_state.history.insert(0, history_item)
                    _save_history(st.session_state.history)
            except Exception as e:
                print(f"Error fetching job details: {e}")
        
        elif progress.status == "failed":
            st.session_state.error_msg = progress.error or "Job failed"
            st.session_state.video_path = None


# ==============================================================================
# CSS
# ==============================================================================
st.markdown("""
<style>
    :root {
        --primary-blue: #2563eb;
        --success-green: #10b981;
        --warning-orange: #f59e0b;
    }

    .stTabs [data-baseweb="tab-list"] {
        gap: 8px;
        border-bottom: 2px solid rgba(128, 128, 128, 0.2);
    }
    .stTabs [data-baseweb="tab"] {
        padding: 12px 24px;
        font-size: 15px;
        font-weight: 500;
        border-radius: 8px 8px 0 0;
        background: transparent;
        transition: all 0.2s;
    }
    .stTabs [data-baseweb="tab"]:hover {
        background: rgba(37, 99, 235, 0.1);
    }
    .stTabs [aria-selected="true"] {
        background: var(--primary-blue) !important;
        color: white !important;
    }

    /* Light mode styles */
    .step-item {
        padding: 12px 18px;
        margin: 8px 0;
        border-radius: 8px;
        font-size: 15px;
        font-weight: 500;
        border-left: 4px solid transparent;
        transition: all 0.3s;
        display: flex;
        align-items: center;
        gap: 12px;
    }
    
    .step-item::before {
        font-size: 20px;
        min-width: 24px;
        text-align: center;
    }
    
    .step-done {
        background: linear-gradient(135deg, rgba(16, 185, 129, 0.15), rgba(16, 185, 129, 0.05));
        color: #059669;
        border-left-color: #10b981;
    }
    .step-done::before {
        content: "✓";
        color: #10b981;
    }
    
    .step-active {
        background: linear-gradient(135deg, rgba(59, 130, 246, 0.2), rgba(59, 130, 246, 0.1));
        color: #2563eb;
        border-left-color: #3b82f6;
        animation: pulse 2s ease-in-out infinite;
    }
    .step-active::before {
        content: "▶";
        color: #3b82f6;
    }
    
    .step-pending {
        background: rgba(156, 163, 175, 0.08);
        color: #6b7280;
        border-left-color: rgba(156, 163, 175, 0.3);
    }
    .step-pending::before {
        content: "○";
        color: #9ca3af;
    }
    
    /* Dark mode styles */
    @media (prefers-color-scheme: dark) {
        .step-done {
            background: linear-gradient(135deg, rgba(52, 211, 153, 0.25), rgba(52, 211, 153, 0.1));
            color: #34d399;
            border-left-color: #34d399;
        }
        .step-done::before {
            color: #34d399;
        }
        
        .step-active {
            background: linear-gradient(135deg, rgba(96, 165, 250, 0.3), rgba(96, 165, 250, 0.15));
            color: #60a5fa;
            border-left-color: #60a5fa;
        }
        .step-active::before {
            color: #60a5fa;
        }
        
        .step-pending {
            background: rgba(209, 213, 219, 0.12);
            color: #d1d5db;
            border-left-color: rgba(209, 213, 219, 0.4);
        }
        .step-pending::before {
            color: #d1d5db;
        }
    }
    
    @keyframes pulse {
        0%, 100% {
            opacity: 1;
        }
        50% {
            opacity: 0.7;
        }
    }

    .stButton > button {
        border-radius: 6px;
        font-weight: 500;
        transition: all 0.2s;
    }
    .stButton > button:hover {
        transform: translateY(-1px);
        box-shadow: 0 4px 6px rgba(0,0,0,0.15);
    }

    .stTextInput > div > div > input,
    .stTextArea > div > div > textarea {
        border-radius: 6px;
        transition: all 0.2s;
    }
    .stTextInput > div > div > input:focus,
    .stTextArea > div > div > textarea:focus {
        border-color: var(--primary-blue);
        box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.15);
    }

    .streamlit-expanderHeader {
        border-radius: 6px;
        transition: all 0.2s;
    }
    .streamlit-expanderHeader:hover {
        background: rgba(37, 99, 235, 0.05);
    }

    [data-testid="stMetricValue"] {
        font-size: 1.5rem;
        font-weight: 600;
    }

    .stProgress > div > div > div {
        background-color: var(--primary-blue);
    }
</style>
""", unsafe_allow_html=True)


# ==============================================================================
# MAIN UI
# ==============================================================================
_init_session()


# ---- Sidebar ----
with st.sidebar:
    st.title("Cấu hình")
    
    # Backend health check
    backend_status = check_backend_health()
    if backend_status:
        st.success("Backend: Hoạt động")
    else:
        st.error("Backend: Không hoạt động")
        st.caption("Khởi động: uvicorn main:app --reload")
    
    st.session_state.backend_healthy = backend_status

    # --- LLM Provider ---
    st.subheader("LLM Provider")
    gemini_key = st.text_input(
        "GEMINI_API_KEY",
        value=os.environ.get("GEMINI_API_KEY", ""),
        type="password",
        help="Lấy tại https://aistudio.google.com/app/apikey",
    )
    if gemini_key:
        os.environ["GEMINI_API_KEY"] = gemini_key
        os.environ["GOOGLE_API_KEY"] = gemini_key

    st.divider()

    # --- Browser Mode ---
    st.subheader("Browser Mode")
    browser_mode = st.radio(
        "Chế độ trình duyệt:",
        ["CDP (Port 9222)", "CDP (Port 9223)", "Headless (Ẩn)"],
        index=0,
        help="Sử dụng CDP để kết nối vào Chrome đang mở sẵn. Port 9223 dùng cho nested execution.",
    )
    st.session_state["browser_mode"] = browser_mode

    if "CDP (Port 9222)" in browser_mode:
        cdp_url = "http://localhost:9222"
    elif "CDP (Port 9223)" in browser_mode:
        cdp_url = "http://localhost:9223"
    else:
        cdp_url = CDP_URL

    st.divider()

    # --- TTS Config ---
    st.subheader("Thuyết minh (TTS)")
    enable_tts = st.toggle("Bật thuyết minh giọng nói", value=True)

    tts_engine = "edge"
    tts_voice = "vi-VN-HoaiMyNeural"
    padding_ms = 300

    if enable_tts:
        tts_engine = st.selectbox(
            "TTS Engine:",
            options=["edge", "fpt"],
            format_func=lambda e: "Edge TTS (miễn phí)" if e == "edge" else "FPT.AI (cần API key)",
            index=0,
        )

        if tts_engine == "edge":
            tts_voice = st.selectbox(
                "Chọn giọng:",
                options=list(TTS_VOICES_EDGE.keys()),
                format_func=lambda v: TTS_VOICES_EDGE[v],
                index=0,
            )
        else:
            tts_voice = st.selectbox(
                "Chọn giọng:",
                options=list(TTS_VOICES_FPT.keys()),
                format_func=lambda v: TTS_VOICES_FPT[v],
                index=0,
            )

        padding_ms = st.slider(
            "Padding (ms):",
            min_value=0,
            max_value=2000,
            value=300,
            step=100,
            help="Thời gian đệm thêm vào cuối mỗi đoạn thuyết minh.",
        )

    st.divider()

    # --- History ---
    st.subheader("Lịch sử video")
    
    # Fetch completed jobs from backend API
    try:
        completed_jobs = list_jobs(status="completed", limit=10)
        
        if completed_jobs:
            for i, job in enumerate(completed_jobs[:8]):
                col_info, col_btn = st.columns([3, 1])
                with col_info:
                    created_at = job.get("created_at", "")
                    if created_at:
                        # Format timestamp
                        try:
                            from datetime import datetime
                            dt = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                            formatted_date = dt.strftime("%Y-%m-%d %H:%M")
                        except:
                            formatted_date = created_at
                    else:
                        formatted_date = "Unknown"
                    
                    st.caption(formatted_date)
                    video_name = job.get("video_name", job.get("job_id", ""))
                    st.markdown(f"**{video_name}**")
                with col_btn:
                    if st.button("Play", key=f"hist_{i}", use_container_width=True):
                        # Get video path from job result
                        if "result" in job and job["result"]:
                            video_path = job["result"].get("video_path", "")
                            if video_path:
                                st.session_state.video_path = video_path
                                st.rerun()
        else:
            st.caption("Chưa có video nào.")
    
    except ConnectionFailedError:
        st.caption("Không thể kết nối tới backend")
    except Exception as e:
        st.caption(f"Lỗi: {str(e)}")

    st.divider()
    st.caption("AI Video Tutor v3.0 | V3 Pipeline")


# ---- Main Content ----
st.title("AI Video Tutor v3")
st.markdown(
    "Nhập kịch bản bằng ngôn ngữ tự nhiên, AI sẽ tự động mở trình duyệt, "
    "quay video thực hành, và thêm thuyết minh giọng nói cho bạn. "
    "Hỗ trợ mọi loại web: slides, tutorials, trang tin tức, ứng dụng web."
)

tab_create, tab_result = st.tabs(["Tạo video", "Kết quả"])


# ---- Tab 1: Create Video ----
with tab_create:
    st.subheader("Kịch bản của bạn")

    script_input = st.text_area(
        label="Nhập kịch bản:",
        height=200,
        placeholder=(
            "Ví dụ: Vào google.com tìm kiếm 'lập trình Python' và dừng lại khi thấy kết quả\n\n"
            "Hoặc: Mở youtube.com, tìm kiếm 'Python programming' và ấn vào video đầu tiên"
        ),
        label_visibility="collapsed",
    )

    col_name, col_btn = st.columns([2, 1])
    with col_name:
        video_name_input = st.text_input(
            "Tên video:",
            value=_slugify(script_input) if script_input else "demo",
            help="Tên file và key trong config",
        )

    with col_btn:
        st.markdown("<br>", unsafe_allow_html=True)
        generate_btn = st.button(
            "Tạo Video",
            type="primary",
            use_container_width=True,
            disabled=st.session_state.is_generating,
        )

    # --- Handle Generate ---
    if generate_btn:
        if not script_input.strip():
            st.error("Vui lòng nhập kịch bản trước khi tạo video.")
        elif not os.environ.get("GEMINI_API_KEY") and not os.environ.get("GOOGLE_API_KEY"):
            st.error("Cần GEMINI_API_KEY ở thanh bên trái.")
        elif not st.session_state.backend_healthy:
            st.error("Backend không hoạt động. Vui lòng khởi động FastAPI backend trước.")
            st.info("Chạy lệnh: cd webreel-ai-agent/backend && uvicorn main:app --reload")
        else:
            video_name = video_name_input.strip() or _slugify(script_input)
            
            # Prepare job configuration
            job_config = {
                "enable_tts": enable_tts,
                "tts_voice": tts_voice,
                "tts_engine": tts_engine,
                "cdp_url": cdp_url,
                "padding_ms": padding_ms,
            }
            
            try:
                # Submit job to backend
                response = submit_job(
                    task=script_input,
                    video_name=video_name,
                    config=job_config
                )
                
                job_id = response["job_id"]
                
                # Create progress tracker
                progress = JobProgress()
                progress.job_id = job_id
                st.session_state.pipeline_progress = progress
                st.session_state.current_job_id = job_id
                st.session_state.is_generating = True
                st.session_state.error_msg = None
                st.session_state.video_path = None
                
                # Start WebSocket progress tracking
                tracker = track_progress(job_id, _handle_progress_update, use_fallback=True)
                st.session_state.progress_tracker = tracker
                
                st.rerun()
                
            except ConnectionFailedError as e:
                st.error(f"Không thể kết nối tới backend: {str(e)}")
                st.info("Vui lòng khởi động FastAPI backend: cd webreel-ai-agent/backend && uvicorn main:app --reload")
            except APITimeoutError as e:
                st.error(f"Timeout: {str(e)}")
            except APIClientError as e:
                st.error(f"Lỗi API: {str(e)}")

    # --- Progress UI ---
    if st.session_state.is_generating:
        progress = st.session_state.get("pipeline_progress")
        
        # Check if pipeline is done
        if progress and progress.done:
            st.session_state.is_generating = False
            
            if progress.error:
                st.session_state.error_msg = progress.error
                st.session_state.video_path = None
            
            st.rerun()
        
        # Show progress info
        st.info(f"Đang tạo video... Job ID: {st.session_state.current_job_id}")

        step = progress.step if progress else 0
        total = st.session_state.progress_total
        msg = progress.msg if progress else "Đang khởi động..."

        # Show progress bar
        progress_val = step / total if total > 0 else 0
        st.progress(progress_val, text=f"Bước {step}/{total}: {msg}")

        # Show detailed steps
        st.markdown("### Tiến trình:")
        for i, label in enumerate(PIPELINE_STEPS, 1):
            if i < step:
                st.markdown(
                    f'<div class="step-item step-done">{label}</div>',
                    unsafe_allow_html=True,
                )
            elif i == step:
                st.markdown(
                    f'<div class="step-item step-active">{label}</div>',
                    unsafe_allow_html=True,
                )
            else:
                st.markdown(
                    f'<div class="step-item step-pending">{label}</div>',
                    unsafe_allow_html=True,
                )

        # Force refresh every 1 second
        time.sleep(1)
        st.rerun()

    # --- Error UI ---
    if st.session_state.error_msg:
        error = st.session_state.error_msg
        st.error("Đã xảy ra lỗi!")
        with st.expander("Chi tiết lỗi"):
            st.code(error)

    # --- Success notification ---
    if (
        st.session_state.video_path
        and not st.session_state.is_generating
        and not st.session_state.error_msg
    ):
        st.success("Video tạo thành công! Xem ở tab Kết quả.")


# ---- Tab 2: Results ----
with tab_result:
    st.subheader("Video đã tạo")

    video_path = st.session_state.video_path
    if video_path and Path(video_path).exists():
        st.video(video_path)

        col_dl, col_info = st.columns([1, 2])
        with col_dl:
            with open(video_path, "rb") as f:
                st.download_button(
                    label="Tải video (MP4)",
                    data=f,
                    file_name=Path(video_path).name,
                    mime="video/mp4",
                    use_container_width=True,
                )
        with col_info:
            size_mb = Path(video_path).stat().st_size / 1024 / 1024
            st.metric("Kích thước", f"{size_mb:.1f} MB")
            st.metric("File", Path(video_path).name)

            # Check for other output files
            parent = Path(video_path).parent
            raw_videos = list(parent.glob("*.mp4"))
            if len(raw_videos) > 1:
                st.caption(f"Thư mục output: {parent}")

            # Show TTS script if available
            tts_script_path = parent / "tts_script.json"
            if tts_script_path.exists():
                with st.expander("TTS Script (narrations)"):
                    import json
                    with open(tts_script_path, "r", encoding="utf-8") as f:
                        script_data = json.load(f)
                    for i, item in enumerate(script_data):
                        st.markdown(f"**Narration {i}:** {item.get('text', '')}")

    elif video_path:
        st.warning(f"File video không tồn tại: {video_path}")
    else:
        st.info("Chưa có video")
