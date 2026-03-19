"""
Streamlit UI - AI Video Tutor v3.0
Web interface for the V3 Pipeline (6 phases, trace-driven).

Usage:
  cd webreel-ai-agent
  streamlit run src/app.py
"""
import asyncio
import os
import re
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

load_dotenv()

# Import V3 pipeline
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from run_pipeline import run_pipeline_v3, CDP_URL, set_stop_flag
from src.webreel_runner import OUTPUT_DIR


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
        "pipeline_thread": None,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


class PipelineProgress:
    """Thread-safe progress tracker."""
    def __init__(self):
        self.step = 0
        self.msg = ""
        self.logs = []
        self.last_phase = 0
        self.done = False
        self.error = None
        self.video_path = None
        self.stop_event = threading.Event()
        
    def update(self, step: int, msg: str):
        self.step = step
        self.msg = msg
        
    def add_log(self, log: str):
        self.logs.append(log)
        if len(self.logs) > 100:
            self.logs = self.logs[-100:]
    
    def request_stop(self):
        """Request pipeline to stop."""
        self.stop_event.set()
        self.done = True
        self.error = "Đã dừng bởi người dùng"
    
    def should_stop(self) -> bool:
        """Check if pipeline should stop."""
        return self.stop_event.is_set()


def _run_pipeline_thread(
    user_input: str,
    video_name: str,
    enable_tts: bool,
    tts_voice: str,
    tts_engine: str,
    padding_ms: int,
    cdp_url: str = CDP_URL,
    progress: PipelineProgress = None,
):
    """Run V3 pipeline in a background thread with progress tracking."""
    try:
        # Check if stopped before starting
        if progress and progress.done:
            logger.info("Pipeline stopped before starting")
            return
            
        # Add custom logging handler to capture phase changes
        import logging
        
        class ProgressLogHandler(logging.Handler):
            def __init__(self, progress_tracker):
                super().__init__()
                self.progress = progress_tracker
                
            def emit(self, record):
                try:
                    # Check if stopped
                    if self.progress and self.progress.should_stop():
                        return
                        
                    msg = self.format(record)
                    
                    # Detect phase changes from log messages
                    if "Phase 1: The Scout" in msg:
                        if self.progress.last_phase < 1:
                            self.progress.update(1, "The Scout - Đang thu thập dữ liệu từ web...")
                            self.progress.last_phase = 1
                    elif "Phase 2: The Parser" in msg:
                        if self.progress.last_phase < 2:
                            self.progress.update(2, "The Parser - Đang phân tích và tạo config...")
                            self.progress.last_phase = 2
                    elif "Phase 3: Ground-Truth TTS" in msg:
                        if self.progress.last_phase < 3:
                            self.progress.update(3, "Ground-Truth TTS - Đang tạo giọng nói...")
                            self.progress.last_phase = 3
                    elif "Phase 4: The Injector" in msg:
                        if self.progress.last_phase < 4:
                            self.progress.update(4, "The Injector - Đang chèn audio vào timeline...")
                            self.progress.last_phase = 4
                    elif "Phase 5: The Execution" in msg:
                        if self.progress.last_phase < 5:
                            self.progress.update(5, "The Execution - Đang quay video...")
                            self.progress.last_phase = 5
                    elif "Phase 6: The Composer" in msg:
                        if self.progress.last_phase < 6:
                            self.progress.update(6, "The Composer - Đang ghép video và audio...")
                            self.progress.last_phase = 6
                    elif "V3 PIPELINE COMPLETED" in msg:
                        self.progress.update(6, "Hoàn thành!")
                except Exception:
                    pass
        
        # Add handler to root logger
        handler = ProgressLogHandler(progress)
        root_logger = logging.getLogger()
        root_logger.addHandler(handler)

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        try:
            if progress:
                progress.update(1, "Đang khởi động pipeline...")
            
            # Check if stopped before running
            if progress and progress.should_stop():
                logger.info("Pipeline stopped before execution")
                return
            
            video_path = loop.run_until_complete(run_pipeline_v3(
                task=user_input,
                video_name=video_name,
                cdp_url=cdp_url,
                enable_tts=enable_tts,
                tts_voice=tts_voice,
                tts_engine=tts_engine,
                padding_ms=padding_ms,
                progress=progress,
            ))
        finally:
            root_logger.removeHandler(handler)

        # Check if stopped after completion
        if progress and progress.should_stop():
            logger.info("Pipeline was stopped, ignoring results")
            return

        # Store results in progress object
        if progress:
            progress.video_path = str(video_path) if video_path else None
            progress.error = None
            progress.done = True
            progress.history_item = {
                "script": user_input,
                "path": str(video_path) if video_path else None,
                "name": video_name,
                "created_at": datetime.now().strftime("%d/%m/%Y %H:%M"),
                "has_tts": enable_tts,
                "engine": tts_engine,
            }

    except Exception as exc:
        import traceback
        if progress:
            # Check if it's a stop-related error
            if progress.done and progress.error:
                logger.info("Pipeline stopped, ignoring exception")
                return
            progress.error = f"{exc}\n\n{traceback.format_exc()}"
            progress.video_path = None
            progress.done = True


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
    
    # Load videos directly from output directory
    video_files = []
    if OUTPUT_DIR.exists():
        for folder in sorted(OUTPUT_DIR.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
            if folder.is_dir() and folder.name != "browser_profile":
                # Look for video files with various naming patterns
                video_candidates = [
                    folder / f"{folder.name}_final.mp4",
                    folder / "final_video.mp4",
                ]
                
                # Also check for any .mp4 files in the folder
                mp4_files = list(folder.glob("*.mp4"))
                
                video_path = None
                if mp4_files:
                    # Prefer files with "final" in name
                    final_videos = [f for f in mp4_files if "final" in f.name.lower()]
                    video_path = final_videos[0] if final_videos else mp4_files[0]
                else:
                    # Check specific candidates
                    for candidate in video_candidates:
                        if candidate.exists():
                            video_path = candidate
                            break
                
                if video_path and video_path.exists():
                    video_files.append({
                        "name": folder.name,
                        "path": str(video_path),
                        "created_at": datetime.fromtimestamp(video_path.stat().st_mtime).strftime("%Y-%m-%d %H:%M"),
                    })
    
    if video_files:
        for i, item in enumerate(video_files[:8]):
            col_info, col_btn = st.columns([3, 1])
            with col_info:
                st.caption(item["created_at"])
                st.markdown(f"**{item['name']}**")
            with col_btn:
                if st.button("Play", key=f"hist_{i}", use_container_width=True):
                    st.session_state.video_path = item["path"]
                    st.rerun()
    else:
        st.caption("Chưa có video nào.")

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
        else:
            video_name = video_name_input.strip() or _slugify(script_input)
            
            # Create progress tracker
            progress = PipelineProgress()
            st.session_state.pipeline_progress = progress
            st.session_state.is_generating = True
            st.session_state.error_msg = None
            st.session_state.video_path = None
            st.session_state.stop_requested = False

            thread = threading.Thread(
                target=_run_pipeline_thread,
                args=(
                    script_input, video_name,
                    enable_tts, tts_voice, tts_engine, padding_ms, cdp_url,
                    progress,
                ),
                daemon=True,
            )
            st.session_state.pipeline_thread = thread
            thread.start()
            st.rerun()

    # --- Progress UI ---
    if st.session_state.is_generating:
        progress = st.session_state.get("pipeline_progress")
        
        # Check if pipeline is done
        if progress and progress.done:
            st.session_state.is_generating = False
            
            if progress.error:
                # Only show error if it's not a user-initiated stop
                if "dừng bởi người dùng" not in progress.error.lower():
                    st.session_state.error_msg = progress.error
                st.session_state.video_path = None
            else:
                st.session_state.video_path = progress.video_path
                if hasattr(progress, 'history_item'):
                    st.session_state.history.insert(0, progress.history_item)
                st.session_state.error_msg = None
            
            st.rerun()
        
        # Show progress with stop button
        col_info, col_stop = st.columns([4, 1])
        with col_info:
            st.info("Đang tạo video, vui lòng chờ...")
        with col_stop:
            if st.button("Dừng", type="secondary", use_container_width=True, key="stop_btn"):
                # Request stop via progress object
                if progress:
                    progress.request_stop()
                st.rerun()

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
