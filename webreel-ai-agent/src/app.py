"""
Streamlit UI - AI Video Tutor
Nguoi dung dan kich ban vao, nhan Generate, tai video ve.
"""
import os
import re
import threading
import time
from datetime import datetime
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

load_dotenv()

try:
    from .pipeline import run_pipeline, get_parsed_preview, MOCK_MODE
except ImportError:
    # When running as `streamlit run src/app.py` (not as a package)
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from src.pipeline import run_pipeline, get_parsed_preview, MOCK_MODE  # type: ignore

# --- Page config ---
st.set_page_config(
    page_title="AI Video Tutor",
    page_icon="assets/icon.png" if Path("assets/icon.png").exists() else None,
    layout="wide",
    initial_sidebar_state="expanded",
)

# --- Helpers ---
OUTPUT_DIR = Path(os.environ.get("OUTPUT_DIR", "videos"))
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

ACTION_ICONS = {
    "navigate": "navigate_next",
    "click": "ads_click",
    "type": "keyboard",
    "key": "keyboard_return",
    "scroll": "swap_vert",
    "pause": "pause_circle",
}

EXAMPLE_SCRIPTS = {
    "Tim kiem Google": "Mo google.com, go 'lap trinh Python cho nguoi moi', nhan Enter",
    "Vao VnExpress": "Mo vnexpress.net, click vao bai viet tin tuc dau tien, cuon xuong doc noi dung",
    "GitHub": "Mo github.com, click Sign in, nhap email demo@test.com vao o email",
    "YouTube": "Mo youtube.com, go 'hoc tieng Anh mien phi' vao o tim kiem, nhan Enter",
}


def _slugify(text: str) -> str:
    """Chuyen text thanh slug an toan cho ten file."""
    slug = re.sub(r"[^\w\s-]", "", text.lower())
    slug = re.sub(r"[\s_]+", "-", slug)
    return slug[:40].strip("-") or "demo"


def _init_session():
    """Khoi tao session state lan dau."""
    defaults = {
        "history": [],
        "video_path": None,
        "is_generating": False,
        "progress_step": 0,
        "progress_total": 4,
        "progress_msg": "",
        "error_msg": None,
        "preview_actions": None,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def _make_progress_callback(step_placeholder, progress_bar, msg_placeholder):
    """Tao callback cap nhat progress UI tu background thread."""
    def callback(step: int, total: int, message: str):
        st.session_state.progress_step = step
        st.session_state.progress_total = total
        st.session_state.progress_msg = message
        # Streamlit khong cho update widget tu thread khac truc tiep,
        # nen luu vao session_state va dung st.rerun() o main thread.
    return callback


def _run_pipeline_thread(user_input: str, video_name: str):
    """Chay pipeline trong background thread."""
    try:
        def on_progress(step, total, msg):
            st.session_state.progress_step = step
            st.session_state.progress_total = total
            st.session_state.progress_msg = msg

        video_path = run_pipeline(
            user_input=user_input,
            video_name=video_name,
            output_dir=str(OUTPUT_DIR),
            on_progress=on_progress,
        )

        st.session_state.video_path = str(video_path)
        st.session_state.history.insert(0, {
            "script": user_input,
            "path": str(video_path),
            "name": video_name,
            "created_at": datetime.now().strftime("%d/%m/%Y %H:%M"),
        })
        st.session_state.error_msg = None

    except Exception as exc:
        st.session_state.error_msg = str(exc)
        st.session_state.video_path = None

    finally:
        st.session_state.is_generating = False
        st.session_state.progress_step = 0
        st.session_state.progress_msg = ""


# ==================== MAIN UI ====================

_init_session()

# --- Sidebar ---
with st.sidebar:
    st.title("Cau hinh")

    st.subheader("Gemini API")
    gemini_key = st.text_input(
        "GEMINI_API_KEY",
        value=os.environ.get("GEMINI_API_KEY", ""),
        type="password",
        help="Lay tai https://aistudio.google.com/app/apikey",
    )
    if gemini_key:
        os.environ["GEMINI_API_KEY"] = gemini_key
        try:
            from google import genai
            genai.Client(api_key=gemini_key)  # validate key format
        except ImportError:
            pass

    st.divider()

    st.subheader("Lich su video")
    if st.session_state.history:
        for i, item in enumerate(st.session_state.history[:8]):
            col_info, col_btn = st.columns([3, 1])
            with col_info:
                st.caption(f"{item['created_at']}")
                st.markdown(f"**{item['name']}**")
            with col_btn:
                if st.button("Xem", key=f"hist_{i}", use_container_width=True):
                    st.session_state.video_path = item["path"]
                    st.rerun()
    else:
        st.caption("Chua co video nao.")

    st.divider()
    if MOCK_MODE:
        st.warning("DEMO MODE - khong goi API thuc")

    st.caption("AI Video Tutor v1.0  |  Powered by Gemini + webreel")


# --- Main content ---
st.title("AI Video Tutor")
if MOCK_MODE:
    st.info("DEMO MODE (MOCK_MODE=1): Pipeline dang mo phong, khong can API key hay trinh duyet.")
st.markdown(
    "Nhap kich ban bang ngon ngu tu nhien, AI se tu dong mo trinh duyet "
    "va quay video thuc hanh cho ban."
)

tab_create, tab_preview, tab_result = st.tabs(["Tao video", "Xem truoc buoc", "Ket qua"])

# ---- Tab 1: Tao video ----
with tab_create:
    col_input, col_examples = st.columns([3, 2])

    with col_input:
        st.subheader("Kich ban cua ban")

        script_input = st.text_area(
            label="Nhap kich ban:",
            height=160,
            placeholder=(
                "Vi du: Mo Google, go 'hoc lap trinh Python', nhan Enter\n\n"
                "Hoac: Mo vnexpress.net, click bai viet dau tien, cuon xuong"
            ),
            label_visibility="collapsed",
        )

        col_name, col_btn = st.columns([2, 1])
        with col_name:
            video_name_input = st.text_input(
                "Ten video:",
                value=_slugify(script_input) if script_input else "demo",
                help="Ten file va key trong config",
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
        st.subheader("Vi du kich ban")
        for label, example in EXAMPLE_SCRIPTS.items():
            if st.button(label, use_container_width=True, key=f"ex_{label}"):
                st.session_state["_example_script"] = example
                st.rerun()

    # Set script from example click
    if "_example_script" in st.session_state:
        script_input = st.session_state.pop("_example_script")

    # --- Xu ly Generate ---
    if generate_btn:
        if not script_input.strip():
            st.error("Vui long nhap kich ban truoc khi tao video.")
        elif not MOCK_MODE and not os.environ.get("GEMINI_API_KEY") and not os.environ.get("GITHUB_TOKEN"):
            st.error("Can GEMINI_API_KEY hoac GITHUB_TOKEN (Azure fallback) o thanh ben trai.")
        else:
            video_name = video_name_input.strip() or _slugify(script_input)
            st.session_state.is_generating = True
            st.session_state.error_msg = None
            st.session_state.video_path = None
            st.session_state.progress_step = 0
            st.session_state.progress_msg = "Dang khoi dong..."

            thread = threading.Thread(
                target=_run_pipeline_thread,
                args=(script_input, video_name),
                daemon=True,
            )
            thread.start()  # noqa: E501
            st.rerun()

    # --- Progress UI ---
    if st.session_state.is_generating:
        st.info("Video dang duoc tao, vui long cho...")
        step = st.session_state.progress_step
        total = st.session_state.progress_total
        msg = st.session_state.progress_msg

        progress_val = step / total if total > 0 else 0
        st.progress(progress_val, text=f"Buoc {step}/{total}: {msg}")

        step_labels = [
            "Phan tich kich ban",
            "Tim kiem elements tren trang web",
            "Tao cau hinh webreel",
            "Quay video",
        ]
        for i, label in enumerate(step_labels, 1):
            icon = "check_circle" if i < step else ("hourglass_top" if i == step else "radio_button_unchecked")
            color = "green" if i < step else ("orange" if i == step else "gray")
            st.markdown(
                f'<span style="color:{color}">{"[x]" if i < step else ("[>]" if i == step else "[ ]")} '
                f'Buoc {i}: {label}</span>',
                unsafe_allow_html=True,
            )

        # Tu dong refresh de cap nhat progress
        time.sleep(2)
        st.rerun()

    # --- Error UI ---
    if st.session_state.error_msg:
        error = st.session_state.error_msg
        st.error(f"Da xay ra loi: {error}")

        with st.expander("Goi y khac phuc"):
            if "url" in error.lower() or "navigate" in error.lower():
                st.markdown("- Kich ban can co URL (vi du: 'Mo google.com')")
            elif "quota" in error.lower() or "rate" in error.lower():
                st.markdown("- API quota het, thu lai sau it phut hoac doi API key")
            elif "timeout" in error.lower():
                st.markdown("- Trang web load cham, thu lai sau")
                st.markdown("- Kiem tra ket noi mang")
            elif "webreel" in error.lower():
                st.markdown("- Kiem tra webreel da duoc build chua: `pnpm build`")
                st.markdown("- Kiem tra bien WEBREEL_BIN trong .env")
            else:
                st.markdown("- Thu kich ban don gian hon")
                st.markdown("- Kiem tra API key con hieu luc")

    # --- Success notification ---
    if (
        st.session_state.video_path
        and not st.session_state.is_generating
        and not st.session_state.error_msg
    ):
        st.success("Video tao thanh cong! Xem o tab 'Ket qua'.")


# ---- Tab 2: Preview actions ----
with tab_preview:
    st.subheader("Xem truoc cac buoc")
    st.markdown("Kiem tra AI se lam gi truoc khi chay may tinh.")

    preview_input = st.text_area(
        "Nhap kich ban de phan tich:",
        height=100,
        key="preview_input",
        placeholder="Mo google.com, go 'hello world', nhan Enter",
    )

    if st.button("Phan tich", key="btn_preview"):
        if not preview_input.strip():
            st.warning("Nhap kich ban truoc.")
        elif not MOCK_MODE and not os.environ.get("GEMINI_API_KEY") and not os.environ.get("GITHUB_TOKEN"):
            st.error("Can GEMINI_API_KEY hoac GITHUB_TOKEN.")
        else:
            with st.spinner("Dang phan tich..."):
                try:
                    actions = get_parsed_preview(preview_input)
                    st.session_state.preview_actions = actions
                except Exception as e:
                    st.error(f"Loi phan tich: {e}")

    if st.session_state.preview_actions:
        actions = st.session_state.preview_actions
        st.success(f"Tim thay {len(actions)} buoc:")

        for i, action in enumerate(actions, 1):
            action_type = action.action.value if hasattr(action.action, "value") else action.action

            with st.container(border=True):
                col_num, col_detail = st.columns([1, 6])
                with col_num:
                    st.markdown(f"### {i}")
                with col_detail:
                    st.markdown(f"**`{action_type.upper()}`**")
                    if action.url:
                        st.markdown(f"URL: `{action.url}`")
                    if action.target:
                        st.markdown(f"Element: *{action.target}*")
                    if action.text:
                        st.markdown(f"Text: `{action.text}`")
                    if action.key:
                        st.markdown(f"Key: `{action.key}`")
                    if action.direction:
                        st.markdown(f"Huong: {action.direction}")


# ---- Tab 3: Ket qua ----
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
            st.metric("Duong dan", Path(video_path).name)

    elif video_path:
        st.warning(f"File video khong ton tai: {video_path}")
    else:
        st.info("Chua co video. Tao video o tab 'Tao video'.")
