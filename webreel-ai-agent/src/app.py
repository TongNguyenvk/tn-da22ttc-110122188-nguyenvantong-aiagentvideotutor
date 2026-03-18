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
from run_pipeline import run_pipeline_v3, CDP_URL
from src.webreel_runner import OUTPUT_DIR


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
EXAMPLE_SCRIPTS = {
    "E-Learning Slides": (
        "Vào http://127.0.0.1:5500/webreel-ai-agent/test-cases/"
        "microservices-elearning.html đọc nội dung trong trang "
        "sau đó ấn tiếp theo cho tới khi hoàn thành bài học kết thúc."
    ),
    "Tìm kiếm Google": (
        "Vào google.com tìm kiếm 'lập trình Python cho người mới' "
        "và dừng lại khi thấy kết quả"
    ),
    "YouTube": (
        "Vào youtube.com tìm kiếm 'Python programming' "
        "và ấn vào video đầu tiên"
    ),
    "VnExpress": "Mở vnexpress.net, click vào bài viết tin tức đầu tiên",
    "GitHub": "Mở github.com, tìm kiếm 'react' và click vào repo đầu tiên",
}

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
        "history": [],
        "video_path": None,
        "is_generating": False,
        "progress_step": 0,
        "progress_total": len(PIPELINE_STEPS),
        "progress_msg": "",
        "live_logs": [],
        "error_msg": None,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def _run_pipeline_thread(
    user_input: str,
    video_name: str,
    enable_tts: bool,
    tts_voice: str,
    tts_engine: str,
    padding_ms: int,
    cdp_url: str = CDP_URL,
):
    """Run V3 pipeline in a background thread."""
    try:
        # Intercept stdout/stderr to capture logs
        class LogCapturer:
            def __init__(self, original):
                self.original = original
            def write(self, message):
                self.original.write(message)
                if message.strip():
                    st.session_state.live_logs.append(message.strip())
                    if len(st.session_state.live_logs) > 100:
                        st.session_state.live_logs = st.session_state.live_logs[-100:]
            def flush(self):
                self.original.flush()

        old_stdout = sys.stdout
        old_stderr = sys.stderr
        sys.stdout = LogCapturer(old_stdout)
        sys.stderr = LogCapturer(old_stderr)

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        try:
            video_path = loop.run_until_complete(run_pipeline_v3(
                task=user_input,
                video_name=video_name,
                cdp_url=cdp_url,
                enable_tts=enable_tts,
                tts_voice=tts_voice,
                tts_engine=tts_engine,
                padding_ms=padding_ms,
            ))
        finally:
            sys.stdout = old_stdout
            sys.stderr = old_stderr

        st.session_state.video_path = str(video_path) if video_path else None
        st.session_state.history.insert(0, {
            "script": user_input,
            "path": str(video_path) if video_path else None,
            "name": video_name,
            "created_at": datetime.now().strftime("%d/%m/%Y %H:%M"),
            "has_tts": enable_tts,
            "engine": tts_engine,
        })
        st.session_state.error_msg = None

    except Exception as exc:
        import traceback
        st.session_state.error_msg = f"{exc}\n\n{traceback.format_exc()}"
        st.session_state.video_path = None

    finally:
        st.session_state.is_generating = False
        st.session_state.progress_step = 0
        st.session_state.progress_msg = ""


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

    .step-item {
        padding: 10px 16px;
        margin: 6px 0;
        border-radius: 6px;
        font-size: 14px;
        border-left: 3px solid transparent;
        transition: all 0.2s;
    }
    .step-done {
        background: rgba(16, 185, 129, 0.15);
        color: var(--success-green);
        border-left-color: var(--success-green);
    }
    .step-active {
        background: rgba(245, 158, 11, 0.15);
        color: var(--warning-orange);
        border-left-color: var(--warning-orange);
        font-weight: 500;
    }
    .step-pending {
        background: rgba(128, 128, 128, 0.1);
        color: rgba(128, 128, 128, 0.7);
        border-left-color: rgba(128, 128, 128, 0.3);
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
        ["CDP (Port 9222)", "Headless (Ẩn)"],
        index=0,
        help="Sử dụng CDP để kết nối vào Chrome đang mở sẵn (chống bot tốt hơn).",
    )
    st.session_state["browser_mode"] = browser_mode

    cdp_url = CDP_URL
    if browser_mode == "CDP (Port 9222)":
        cdp_url = st.text_input("CDP Endpoint:", value=CDP_URL)

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
    if st.session_state.history:
        for i, item in enumerate(st.session_state.history[:8]):
            col_info, col_btn = st.columns([3, 1])
            with col_info:
                st.caption(item["created_at"])
                tts_badge = f" [{item.get('engine', 'edge').upper()}]" if item.get("has_tts") else ""
                st.markdown(f"**{item['name']}**{tts_badge}")
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
    col_input, col_examples = st.columns([3, 2])

    with col_input:
        st.subheader("Kịch bản của bạn")

        script_input = st.text_area(
            label="Nhập kịch bản:",
            height=160,
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
                "Generate",
                type="primary",
                use_container_width=True,
                disabled=st.session_state.is_generating,
            )

    with col_examples:
        st.subheader("Ví dụ mẫu")
        for label, example in EXAMPLE_SCRIPTS.items():
            if st.button(label, use_container_width=True, key=f"ex_{label}"):
                st.session_state["_example_script"] = example
                st.rerun()

    # Set script from example click
    if "_example_script" in st.session_state:
        script_input = st.session_state.pop("_example_script")

    # --- Handle Generate ---
    if generate_btn:
        if not script_input.strip():
            st.error("Vui long nhap kich ban truoc khi tao video.")
        elif not os.environ.get("GEMINI_API_KEY") and not os.environ.get("GOOGLE_API_KEY"):
            st.error("Can GEMINI_API_KEY o thanh ben trai.")
        else:
            video_name = video_name_input.strip() or _slugify(script_input)
            st.session_state.is_generating = True
            st.session_state.error_msg = None
            st.session_state.video_path = None
            st.session_state.progress_step = 0
            st.session_state.progress_msg = "Dang khoi dong..."
            st.session_state.live_logs = []

            thread = threading.Thread(
                target=_run_pipeline_thread,
                args=(
                    script_input, video_name,
                    enable_tts, tts_voice, tts_engine, padding_ms, cdp_url,
                ),
                daemon=True,
            )
            thread.start()
            st.rerun()

    # --- Progress UI ---
    if st.session_state.is_generating:
        st.info("Video dang duoc tao, vui long cho...")

        step = st.session_state.progress_step
        total = st.session_state.progress_total
        msg = st.session_state.progress_msg

        progress_val = step / total if total > 0 else 0
        st.progress(progress_val, text=f"Buoc {step}/{total}: {msg}")

        for i, label in enumerate(PIPELINE_STEPS, 1):
            if i < step:
                st.markdown(
                    f'<div class="step-item step-done">[DONE] {label}</div>',
                    unsafe_allow_html=True,
                )
            elif i == step:
                st.markdown(
                    f'<div class="step-item step-active">[RUNNING] {label}</div>',
                    unsafe_allow_html=True,
                )
            else:
                st.markdown(
                    f'<div class="step-item step-pending">[PENDING] {label}</div>',
                    unsafe_allow_html=True,
                )

        # Show live logs
        with st.expander("Live Logs (Terminal)", expanded=True):
            log_text = "\\n".join(st.session_state.live_logs)
            st.code(log_text, language="bash")

        # Auto-refresh
        time.sleep(2)
        st.rerun()

    # --- Error UI ---
    if st.session_state.error_msg:
        error = st.session_state.error_msg
        st.error("Da xay ra loi!")
        with st.expander("Chi tiet loi"):
            st.code(error)

        with st.expander("Goi y khac phuc"):
            if "quota" in error.lower() or "rate" in error.lower():
                st.markdown("- API quota het, thu lai sau it phut hoac doi API key")
            elif "timeout" in error.lower():
                st.markdown("- Trang web load cham, thu lai sau")
            elif "webreel" in error.lower():
                st.markdown("- Kiem tra webreel da duoc build chua: `pnpm build`")
            elif "fpt" in error.lower() or "tts" in error.lower():
                st.markdown("- Kiem tra FPT_TTS_API_KEY trong file .env")
            elif "chrome" in error.lower() or "cdp" in error.lower():
                st.markdown("- Kiem tra Chrome dang chay voi debug port: `start_chrome_debug.bat`")
            else:
                st.markdown("- Thu kich ban don gian hon")
                st.markdown("- Kiem tra API key con hieu luc")

    # --- Success notification ---
    if (
        st.session_state.video_path
        and not st.session_state.is_generating
        and not st.session_state.error_msg
    ):
        st.success("Video tao thanh cong! Xem o tab Ket qua.")


# ---- Tab 2: Results ----
with tab_result:
    st.subheader("Video da tao")

    video_path = st.session_state.video_path
    if video_path and Path(video_path).exists():
        st.video(video_path)

        col_dl, col_info = st.columns([1, 2])
        with col_dl:
            with open(video_path, "rb") as f:
                st.download_button(
                    label="Tai video (MP4)",
                    data=f,
                    file_name=Path(video_path).name,
                    mime="video/mp4",
                    use_container_width=True,
                )
        with col_info:
            size_mb = Path(video_path).stat().st_size / 1024 / 1024
            st.metric("Kich thuoc", f"{size_mb:.1f} MB")
            st.metric("File", Path(video_path).name)

            # Check for other output files
            parent = Path(video_path).parent
            raw_videos = list(parent.glob("*.mp4"))
            if len(raw_videos) > 1:
                st.caption(f"Thu muc output: {parent}")

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
        st.warning(f"File video khong ton tai: {video_path}")
    else:
        st.info("Chua co video. Tao video o tab Tao video.")
