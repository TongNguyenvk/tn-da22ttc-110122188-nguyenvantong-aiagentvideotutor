"""
AI Video Tutor - Unified Desktop App (Flet UI)
Giao dien hop nhat: Web Browser + Desktop OS (Excel/Word/PowerPoint)
Entry point: chay tu thu muc goc webreel-ai-agent/
"""

import flet as ft
import asyncio
import logging
import threading
import shutil
from pathlib import Path
from dotenv import load_dotenv
import os
import subprocess
import platform
import sys
from datetime import datetime
import requests

# Setup paths - import from both desktop_app and os_recorder
ROOT_DIR = Path(__file__).parent
DESKTOP_APP_DIR = ROOT_DIR / "desktop_app"
OS_RECORDER_DIR = ROOT_DIR / "os_recorder"

sys.path.insert(0, str(DESKTOP_APP_DIR))
sys.path.insert(0, str(OS_RECORDER_DIR))

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Load env
env_path = DESKTOP_APP_DIR / ".env"
if env_path.exists():
    load_dotenv(env_path)
env_path2 = OS_RECORDER_DIR / ".env"
if env_path2.exists():
    load_dotenv(env_path2, override=False)


def check_chrome_running(port: int = 9222) -> bool:
    cdp_url = f"http://localhost:{port}"
    try:
        response = requests.get(f"{cdp_url}/json/version", timeout=1)
        return response.status_code == 200
    except Exception:
        return False


def launch_chrome_with_cdp(port: int = 9222) -> str:
    from browser_launcher import launch_chrome_with_cdp as _launch
    return _launch(port=port, kill_existing=False)


def main(page: ft.Page):
    page.title = "AI Video Tutor"
    page.window.width = 1280
    page.window.height = 720
    page.padding = 0
    page.scroll = None
    page.theme_mode = ft.ThemeMode.LIGHT
    page.bgcolor = ft.Colors.GREY_50

    # State
    running_jobs = {}
    job_counter = 0
    current_tab = 0

    # Phase 2.5 Review Queue
    review_queue = []
    current_reviewing_job = None

    # OS Pipeline state holders (per job_id)
    os_review_events = {}       # job_id -> threading.Event
    os_result_holders = {}      # job_id -> dict
    os_ready_events = {}        # job_id -> threading.Event (for "ready to record")

    # Helper: Get all video files from output directory
    def get_video_history():
        videos = []
        # Scan desktop_app/output
        output_base = DESKTOP_APP_DIR / "output"
        if output_base.exists():
            for project_dir in output_base.iterdir():
                if not project_dir.is_dir():
                    continue
                try:
                    for video_file in project_dir.glob("*_final.mp4"):
                        videos.append({
                            "name": project_dir.name,
                            "path": str(video_file),
                            "size": video_file.stat().st_size,
                            "created": video_file.stat().st_mtime,
                            "source": "web",
                        })
                    if not list(project_dir.glob("*_final.mp4")):
                        for video_file in project_dir.glob("*.mp4"):
                            if "_raw" not in video_file.stem:
                                videos.append({
                                    "name": project_dir.name,
                                    "path": str(video_file),
                                    "size": video_file.stat().st_size,
                                    "created": video_file.stat().st_mtime,
                                    "source": "web",
                                })
                except Exception as ex:
                    logger.warning(f"Error reading history for {project_dir}: {ex}")

        # Scan os_recorder/workspace/output (new structure)
        os_output = OS_RECORDER_DIR / "workspace" / "output"
        if os_output.exists():
            for project_dir in os_output.iterdir():
                if not project_dir.is_dir():
                    continue
                
                try:
                    # Look for final video
                    video_file = project_dir / f"{project_dir.name}_final.mp4"
                    if not video_file.exists():
                        # Fallback: any mp4 file
                        mp4_files = list(project_dir.glob("*.mp4"))
                        if mp4_files:
                            video_file = mp4_files[0]
                        else:
                            continue
                    
                    video_entry = {
                        "name": project_dir.name,
                        "path": str(video_file),
                        "size": video_file.stat().st_size,
                        "created": video_file.stat().st_mtime,
                        "source": "desktop",
                    }
                    
                    # Check for DOCX and PDF
                    docx_file = project_dir / f"{project_dir.name}.docx"
                    pdf_file = project_dir / f"{project_dir.name}.pdf"
                    
                    if docx_file.exists():
                        video_entry["docx_path"] = str(docx_file)
                    if pdf_file.exists():
                        video_entry["pdf_path"] = str(pdf_file)
                    
                    videos.append(video_entry)
                except Exception as ex:
                    logger.warning(f"Error reading history for desktop {project_dir}: {ex}")

        videos.sort(key=lambda x: x["created"], reverse=True)
        return videos

    def open_video_file(video_path: str):
        if not os.path.exists(video_path):
            page.snack_bar = ft.SnackBar(
                content=ft.Text(f"Lỗi: File hoặc thư mục {video_path} không tồn tại hoặc đã bị xóa.", color=ft.Colors.WHITE),
                bgcolor=ft.Colors.RED_600,
            )
            page.snack_bar.open = True
            page.update()
            return
            
        try:
            if platform.system() == "Windows":
                os.startfile(video_path)
            elif platform.system() == "Darwin":
                subprocess.run(["open", video_path])
            else:
                subprocess.run(["xdg-open", video_path])
        except Exception as e:
            logger.error(f"Failed to open video: {e}")

    # ================================================================
    # UI Components
    # ================================================================
    task_input = ft.TextField(
        label="Mô tả nhiệm vụ",
        hint_text="Nhập nhiệm vụ (VD: Vào google.com và tìm kiếm Python)",
        multiline=True,
        min_lines=3,
        max_lines=5,
        expand=True,
        bgcolor=ft.Colors.WHITE,
        border_color=ft.Colors.BLUE_200,
        focused_border_color=ft.Colors.BLUE_600,
        border_radius=8,
        text_size=13,
    )

    video_name_input = ft.TextField(
        label="Tên video",
        hint_text="demo",
        value="demo",
        expand=True,
        bgcolor=ft.Colors.WHITE,
        border_color=ft.Colors.BLUE_200,
        focused_border_color=ft.Colors.BLUE_600,
        border_radius=8,
        text_size=13,
    )

    # ---- Web-specific: CDP Port ----
    cdp_port_section_label = ft.Text("Cài đặt Chrome", size=13, weight=ft.FontWeight.BOLD, color=ft.Colors.BLUE_800)
    cdp_port_dropdown = ft.Dropdown(
        label="CDP Port",
        value="9222",
        width=140,
        bgcolor=ft.Colors.WHITE,
        border_color=ft.Colors.BLUE_200,
        focused_border_color=ft.Colors.BLUE_600,
        border_radius=8,
        text_size=13,
        options=[
            ft.dropdown.Option("9222", "9222"),
            ft.dropdown.Option("9223", "9223"),
            ft.dropdown.Option("9224", "9224"),
            ft.dropdown.Option("9225", "9225"),
        ],
    )
    web_section = ft.Container(
        content=ft.Column([cdp_port_section_label, cdp_port_dropdown], spacing=10),
        visible=True,
    )

    # ---- Desktop-specific: Target App ----
    target_app_section_label = ft.Text("Ung dung muc tieu", size=13, weight=ft.FontWeight.BOLD, color=ft.Colors.BLUE_800)

    # Custom process name input (visible only when "custom" is selected)
    custom_app_name_input = ft.TextField(
        label="Ten process (VD: photoshop.exe)",
        hint_text="ten_process.exe",
        visible=False,
        bgcolor=ft.Colors.WHITE,
        border_color=ft.Colors.BLUE_200,
        focused_border_color=ft.Colors.BLUE_600,
        border_radius=8,
        text_size=13,
    )

    def on_target_app_change(e):
        custom_app_name_input.visible = (target_app_dropdown.value == "custom")
        page.update()

    target_app_dropdown = ft.Dropdown(
        label="Ung dung",
        value="excel",
        expand=True,
        bgcolor=ft.Colors.WHITE,
        border_color=ft.Colors.BLUE_200,
        focused_border_color=ft.Colors.BLUE_600,
        border_radius=8,
        text_size=13,
        on_select=on_target_app_change,
        options=[
            ft.dropdown.Option("excel", "Microsoft Excel"),
            ft.dropdown.Option("word", "Microsoft Word"),
            ft.dropdown.Option("ppt", "Microsoft PowerPoint"),
            ft.dropdown.Option("notepad", "Notepad"),
            ft.dropdown.Option("chrome", "Google Chrome"),
            ft.dropdown.Option("edge", "Microsoft Edge"),
            ft.dropdown.Option("firefox", "Mozilla Firefox"),
            ft.dropdown.Option("custom", "Khac (nhap ten process)"),
        ],
    )

    # Dual output checkbox for Desktop mode
    enable_dual_output_checkbox = ft.Checkbox(
        label="Tao tai lieu DOCX + PDF",
        value=True,
        fill_color=ft.Colors.BLUE_600,
        tooltip="Tu dong tao tai lieu huong dan (DOCX) va PDF kem video",
    )

    desktop_section = ft.Container(
        content=ft.Column([
            target_app_section_label,
            target_app_dropdown,
            custom_app_name_input,
            enable_dual_output_checkbox,
        ], spacing=10),
        visible=False,
    )

    # ---- Environment selector ----
    def on_env_change(e):
        is_web = env_dropdown.value == "web"
        logger.info(f"Environment changed to: {env_dropdown.value} (is_web={is_web})")
        web_section.visible = is_web
        desktop_section.visible = not is_web
        page.update()

    env_dropdown = ft.Dropdown(
        label="Môi trường",
        value="web",
        expand=True,
        bgcolor=ft.Colors.WHITE,
        border_color=ft.Colors.BLUE_200,
        focused_border_color=ft.Colors.BLUE_600,
        border_radius=8,
        text_size=13,
        options=[
            ft.dropdown.Option("web", "Trình duyệt Web"),
            ft.dropdown.Option("desktop", "Phần mềm Desktop (OS)"),
        ],
    )
    env_dropdown.on_select = on_env_change

    # ---- TTS settings ----
    enable_tts_checkbox = ft.Checkbox(
        label="Bật TTS",
        value=True,
        fill_color=ft.Colors.BLUE_600,
    )

    tts_engine_dropdown = ft.Dropdown(
        label="TTS Engine",
        value="edge",
        expand=True,
        bgcolor=ft.Colors.WHITE,
        border_color=ft.Colors.BLUE_200,
        focused_border_color=ft.Colors.BLUE_600,
        border_radius=8,
        text_size=13,
        options=[
            ft.dropdown.Option("edge", "Edge TTS"),
            ft.dropdown.Option("fpt", "FPT AI"),
        ]
    )

    tts_voice_dropdown = ft.Dropdown(
        label="Giọng đọc",
        value="vi-VN-HoaiMyNeural",
        expand=True,
        bgcolor=ft.Colors.WHITE,
        border_color=ft.Colors.BLUE_200,
        focused_border_color=ft.Colors.BLUE_600,
        border_radius=8,
        text_size=13,
        options=[
            ft.dropdown.Option("vi-VN-HoaiMyNeural", "Hoài My (Nữ)"),
            ft.dropdown.Option("vi-VN-NamMinhNeural", "Nam Minh (Nam)"),
            ft.dropdown.Option("en-US-AriaNeural", "Aria (Female)"),
            ft.dropdown.Option("en-US-GuyNeural", "Guy (Male)"),
        ]
    )

    jobs_list = ft.Column(
        scroll=ft.ScrollMode.AUTO,
        expand=True,
        spacing=12,
    )

    history_list = ft.Column(
        scroll=ft.ScrollMode.AUTO,
        expand=True,
        spacing=12,
    )

    # ================================================================
    # Jobs display
    # ================================================================
    def update_jobs_display():
        jobs_list.controls.clear()

        if not running_jobs:
            jobs_list.controls.append(
                ft.Container(
                    content=ft.Column([
                        ft.Icon(ft.Icons.HOURGLASS_EMPTY, size=60, color=ft.Colors.GREY_400),
                        ft.Text("Chưa có job nào đang chạy", size=16, color=ft.Colors.GREY_600)
                    ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=16),
                    alignment=ft.alignment.Alignment(0, 0),
                    expand=True,
                )
            )
        else:
            for job_id, job_data in running_jobs.items():
                def make_stop_handler(jid):
                    return lambda e: stop_job(jid)

                progress_value = job_data.get("progress", 0)
                status_msg = job_data.get("status", "Đang chạy...")
                job_env = job_data.get("env", "web")

                # Status indicator
                if job_id in review_queue and job_id != current_reviewing_job:
                    queue_pos = review_queue.index(job_id) + 1
                    status_indicator = ft.Container(
                        content=ft.Text(f"Hàng đợi: {queue_pos}", size=11, color=ft.Colors.WHITE, weight=ft.FontWeight.BOLD),
                        bgcolor=ft.Colors.ORANGE_600,
                        padding=ft.Padding(left=8, right=8, top=4, bottom=4),
                        border_radius=12,
                    )
                elif job_id == current_reviewing_job:
                    status_indicator = ft.Container(
                        content=ft.Text("Đang review", size=11, color=ft.Colors.WHITE, weight=ft.FontWeight.BOLD),
                        bgcolor=ft.Colors.GREEN_600,
                        padding=ft.Padding(left=8, right=8, top=4, bottom=4),
                        border_radius=12,
                    )
                else:
                    status_indicator = None

                # Environment badge
                if job_env == "desktop":
                    target_app = job_data.get("target_app", "")
                    app_label_map = {
                        "excel": "Excel", "word": "Word", "ppt": "PowerPoint",
                        "notepad": "Notepad", "chrome": "Chrome",
                        "edge": "Edge", "firefox": "Firefox",
                    }
                    app_label = app_label_map.get(target_app, target_app)
                    is_browser = target_app in ("chrome", "edge", "firefox")
                    badge_bg = ft.Colors.ORANGE_700 if is_browser else ft.Colors.TEAL_700
                    env_indicator = ft.Container(
                        content=ft.Text(f"Desktop: {app_label}", size=10, color=ft.Colors.WHITE),
                        bgcolor=badge_bg,
                        padding=ft.Padding(left=6, right=6, top=3, bottom=3),
                        border_radius=10,
                    )
                else:
                    cdp_port = job_data.get("cdp_port")
                    env_indicator = ft.Container(
                        content=ft.Text(f"Web: Port {cdp_port}" if cdp_port else "Web", size=10, color=ft.Colors.WHITE),
                        bgcolor=ft.Colors.BLUE_700,
                        padding=ft.Padding(left=6, right=6, top=3, bottom=3),
                        border_radius=10,
                    )

                card_content = [
                    ft.Row([
                        ft.Column([
                            ft.Row([
                                ft.Text(f"Job #{job_id}: {job_data['video_name']}", size=16, weight=ft.FontWeight.BOLD, color=ft.Colors.BLUE_900),
                                status_indicator if status_indicator else ft.Container(),
                                env_indicator,
                            ], spacing=8),
                            ft.Text(job_data['task'][:60] + "..." if len(job_data['task']) > 60 else job_data['task'], size=12, color=ft.Colors.GREY_600),
                        ], spacing=4, expand=True),
                        ft.IconButton(
                            icon=ft.Icons.STOP_CIRCLE,
                            icon_size=32,
                            icon_color=ft.Colors.RED_600,
                            tooltip="Dừng job",
                            on_click=make_stop_handler(job_id)
                        ),
                    ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                    ft.ProgressBar(
                        value=progress_value,
                        color=ft.Colors.BLUE_600,
                        bgcolor=ft.Colors.BLUE_100,
                        height=6,
                        border_radius=3,
                    ),
                    ft.Text(status_msg, size=12, color=ft.Colors.BLUE_700),
                ]

                card = ft.Container(
                    content=ft.Column(card_content, spacing=8),
                    padding=20,
                    bgcolor=ft.Colors.WHITE,
                    border_radius=12,
                    border=ft.Border.all(1, ft.Colors.BLUE_300),
                )
                jobs_list.controls.append(card)

        page.update()

    def stop_job(job_id: int):
        """Stop a job immediately and forcefully."""
        nonlocal current_reviewing_job

        if job_id not in running_jobs:
            logger.warning(f"Job #{job_id} not found in running_jobs")
            return

        job_data = running_jobs[job_id]
        logger.info(f"Job #{job_id} stop requested - forcing immediate cancellation")

        # Step 1: Set cancel flag FIRST (highest priority)
        if "cancel_event" in job_data:
            job_data["cancel_event"].set()
            logger.info(f"  - Cancel event set for job #{job_id}")

        # Step 2: Cancel async task immediately
        if "task_handle" in job_data:
            try:
                job_data["task_handle"].cancel()
                logger.info(f"  - Async task cancelled for job #{job_id}")
            except Exception as e:
                logger.warning(f"  - Failed to cancel task: {e}")

        # Step 3: Close any open dialogs
        if current_reviewing_job == job_id:
            _restore_main_area()
            current_reviewing_job = None
            logger.info(f"  - Closed review dialog for job #{job_id}")

        if job_id in review_queue:
            review_queue.remove(job_id)
            logger.info(f"  - Removed from review queue: job #{job_id}")

        # Step 4: Unblock any waiting events (review, ready-to-record)
        if "review_event" in job_data:
            job_data["review_event"].set()
            logger.info(f"  - Review event unblocked for job #{job_id}")
        
        if job_id in os_review_events:
            os_review_events[job_id].set()
            logger.info(f"  - OS review event unblocked for job #{job_id}")
        
        if job_id in os_ready_events:
            os_ready_events[job_id].set()
            logger.info(f"  - OS ready event unblocked for job #{job_id}")

        # Step 5: Kill ALL child subprocess trees (FFmpeg, Webreel node, etc.)
        # Instead of relying on child_pids (never populated), we find and kill
        # all child processes of the current Python process using psutil.
        try:
            import psutil
            # Collect process names/executables to kill (spawned by pipeline)
            kill_targets = {"ffmpeg", "ffprobe", "node", "chrome-headless-shell"}
            current_process = psutil.Process(os.getpid())
            children = current_process.children(recursive=True)
            killed_count = 0
            for child in children:
                try:
                    child_name = child.name().lower()
                    # Kill FFmpeg, node (webreel), chrome-headless-shell
                    # Skip flet/python processes to keep the app running
                    if any(target in child_name for target in kill_targets):
                        child.kill()
                        killed_count += 1
                        logger.info(f"  - Killed subprocess PID={child.pid} ({child.name()})")
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            if killed_count > 0:
                logger.info(f"  - Total killed: {killed_count} child processes")
            else:
                logger.info(f"  - No killable child processes found (checked {len(children)} children)")
        except ImportError:
            # Fallback: use taskkill on Windows to kill known process names
            logger.warning("  - psutil not available, using taskkill fallback")
            if platform.system() == "Windows":
                for proc_name in ["ffmpeg.exe", "ffprobe.exe"]:
                    try:
                        subprocess.run(
                            f"taskkill /F /IM {proc_name}",
                            shell=True, capture_output=True, timeout=5,
                        )
                        logger.info(f"  - taskkill sent for {proc_name}")
                    except Exception:
                        pass

        # Step 6: Update UI immediately
        job_data["status"] = "Da huy"
        job_data["progress"] = 0
        job_data["cancelled"] = True
        update_jobs_display()

        logger.info(f"Job #{job_id} cancellation complete")

    def show_delete_confirmation_dialog(video_data):
        """Show confirmation dialog before deleting video folder."""
        try:
            logger.info(f"Showing delete confirmation for: {video_data.get('name', 'UNKNOWN')}")
            
            # Validate required keys
            if "name" not in video_data or "path" not in video_data:
                logger.error(f"Missing required keys in video_data: {video_data.keys()}")
                page.snack_bar = ft.SnackBar(
                    content=ft.Text("Lỗi: Dữ liệu video không hợp lệ", color=ft.Colors.WHITE),
                    bgcolor=ft.Colors.RED_600,
                )
                page.snack_bar.open = True
                page.update()
                return
            
            video_name = video_data["name"]
            video_path = Path(video_data["path"])
            folder_path = video_path.parent
            
            # Calculate folder size
            total_size = 0
            file_count = 0
            try:
                for file in folder_path.rglob("*"):
                    if file.is_file():
                        total_size += file.stat().st_size
                        file_count += 1
            except Exception as e:
                logger.error(f"Error calculating folder size: {e}")
            
            size_mb = total_size / (1024 * 1024)
            
            def on_confirm_delete(e):
                logger.info(f"Confirm delete clicked for: {video_name}")
                if hasattr(overlay_dialog, 'actions') and overlay_dialog.actions:
                    for action in overlay_dialog.actions:
                        action.disabled = True
                    page.update()
                    
                try:
                    # Delete entire folder
                    shutil.rmtree(folder_path)
                    logger.info(f"Deleted folder: {folder_path}")
                    
                    # Close dialog
                    if hasattr(page, 'close'):
                        page.close(overlay_dialog)
                    else:
                        overlay_dialog.open = False
                        page.update()
                    
                    # Refresh history
                    load_history_tab()
                    
                    # Show success message
                    page.snack_bar = ft.SnackBar(
                        content=ft.Text(f"Đã xóa '{video_name}' thành công!", color=ft.Colors.WHITE),
                        bgcolor=ft.Colors.GREEN_600,
                    )
                    page.snack_bar.open = True
                    page.update()
                    
                except Exception as ex:
                    logger.error(f"Failed to delete folder: {ex}")
                    import traceback
                    traceback.print_exc()
                    
                    # Close dialog on error
                    try:
                        if hasattr(page, 'close'):
                            page.close(overlay_dialog)
                        else:
                            overlay_dialog.open = False
                            page.update()
                    except:
                        pass
                    
                    # Show error message
                    page.snack_bar = ft.SnackBar(
                        content=ft.Text(f"Lỗi khi xóa: {str(ex)[:50]}", color=ft.Colors.WHITE),
                        bgcolor=ft.Colors.RED_600,
                    )
                    page.snack_bar.open = True
                    page.update()
            
            def on_cancel_delete(e):
                logger.info(f"Delete cancelled for: {video_name}")
                if hasattr(page, 'close'):
                    page.close(overlay_dialog)
                else:
                    overlay_dialog.open = False
                    page.update()
            
            # Build confirmation dialog using overlay
            overlay_dialog = ft.AlertDialog(
                modal=True,
                title=ft.Row([
                    ft.Icon(ft.Icons.WARNING_ROUNDED, size=28, color=ft.Colors.ORANGE_600),
                    ft.Text("Xác nhận xóa", size=20, weight=ft.FontWeight.BOLD),
                ], spacing=12),
                content=ft.Container(
                    content=ft.Column([
                        ft.Text(
                            f"Bạn có chắc chắn muốn xóa video '{video_name}' không?",
                            size=14,
                            color=ft.Colors.GREY_800,
                        ),
                        ft.Container(height=8),
                        ft.Container(
                            content=ft.Column([
                                ft.Text("Thông tin thư mục:", size=12, weight=ft.FontWeight.BOLD, color=ft.Colors.GREY_700),
                                ft.Text(f"Đường dẫn: {folder_path}", size=11, color=ft.Colors.GREY_600),
                                ft.Text(f"Số file: {file_count}", size=11, color=ft.Colors.GREY_600),
                                ft.Text(f"Kích thước: {size_mb:.1f} MB", size=11, color=ft.Colors.GREY_600),
                            ], spacing=4),
                            padding=12,
                            bgcolor=ft.Colors.ORANGE_50,
                            border_radius=8,
                            border=ft.Border.all(1, ft.Colors.ORANGE_200),
                        ),
                        ft.Container(height=8),
                        ft.Row([
                            ft.Icon(ft.Icons.INFO_OUTLINE, size=16, color=ft.Colors.RED_600),
                            ft.Text(
                                "Toàn bộ thư mục sẽ bị xóa vĩnh viễn!",
                                size=12,
                                color=ft.Colors.RED_600,
                                weight=ft.FontWeight.BOLD,
                            ),
                        ], spacing=8),
                    ], spacing=0, tight=True),
                    width=400,
                ),
                actions=[
                    ft.TextButton(
                        "Hủy",
                        on_click=on_cancel_delete,
                        style=ft.ButtonStyle(
                            color=ft.Colors.GREY_600,
                        ),
                    ),
                    ft.FilledButton(
                        "Xóa",
                        on_click=on_confirm_delete,
                        style=ft.ButtonStyle(
                            bgcolor=ft.Colors.RED_600,
                            color=ft.Colors.WHITE,
                        ),
                    ),
                ],
                actions_alignment=ft.MainAxisAlignment.END,
                open=True,
            )
            
            if hasattr(page, 'open'):
                page.open(overlay_dialog)
            else:
                page.overlay.append(overlay_dialog)
                page.update()
            
        except Exception as ex:
            logger.error(f"Error in show_delete_confirmation_dialog: {ex}")
            import traceback
            traceback.print_exc()

    def load_history_tab():
        history_list.controls.clear()
        videos = get_video_history()

        if not videos:
            history_list.controls.append(
                ft.Container(
                    content=ft.Column([
                        ft.Icon(ft.Icons.HISTORY, size=60, color=ft.Colors.GREY_400),
                        ft.Text("Chưa có video nào", size=16, color=ft.Colors.GREY_600)
                    ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=16),
                    alignment=ft.alignment.Alignment(0, 0),
                    expand=True,
                )
            )
        else:
            for video in videos:
                created_time = datetime.fromtimestamp(video["created"]).strftime("%Y-%m-%d %H:%M")
                size_mb = video["size"] / (1024 * 1024)
                source_label = "Desktop" if video.get("source") == "desktop" else "Web"

                def make_play_handler(path):
                    return lambda e: open_video_file(path)

                def make_folder_handler(path):
                    return lambda e: open_video_file(str(Path(path).parent))
                
                def make_delete_handler(vid_data):
                    def handler(e):
                        logger.info(f"Delete button clicked for: {vid_data.get('name', 'UNKNOWN')}")
                        try:
                            show_delete_confirmation_dialog(vid_data)
                        except Exception as ex:
                            logger.error(f"Error in delete handler: {ex}")
                            import traceback
                            traceback.print_exc()
                    return handler
                
                # Build action buttons
                action_buttons = [
                    ft.IconButton(
                        icon=ft.Icons.PLAY_CIRCLE_OUTLINE,
                        icon_size=32,
                        icon_color=ft.Colors.GREEN_600,
                        tooltip="Phát video",
                        on_click=make_play_handler(video["path"])
                    ),
                ]
                
                # Add DOCX button if available
                if video.get("docx_path"):
                    action_buttons.append(
                        ft.IconButton(
                            icon=ft.Icons.DESCRIPTION,
                            icon_size=28,
                            icon_color=ft.Colors.BLUE_700,
                            tooltip="Mở DOCX",
                            on_click=make_play_handler(video["docx_path"])
                        )
                    )
                
                # Add PDF button if available
                if video.get("pdf_path"):
                    action_buttons.append(
                        ft.IconButton(
                            icon=ft.Icons.PICTURE_AS_PDF,
                            icon_size=28,
                            icon_color=ft.Colors.RED_600,
                            tooltip="Mở PDF",
                            on_click=make_play_handler(video["pdf_path"])
                        )
                    )
                
                # Add folder button
                action_buttons.append(
                    ft.IconButton(
                        icon=ft.Icons.FOLDER_OPEN,
                        icon_size=28,
                        icon_color=ft.Colors.BLUE_600,
                        tooltip="Mở thư mục",
                        on_click=make_folder_handler(video["path"])
                    )
                )
                
                # Add delete button
                video_copy = dict(video)
                delete_button = ft.IconButton(
                    icon=ft.Icons.DELETE_OUTLINE,
                    icon_size=28,
                    icon_color=ft.Colors.RED_600,
                    tooltip="Xóa video",
                    on_click=make_delete_handler(video_copy),
                    disabled=False,
                )
                action_buttons.append(delete_button)

                card = ft.Container(
                    content=ft.Row([
                        ft.Icon(ft.Icons.VIDEO_FILE, size=40, color=ft.Colors.BLUE_600),
                        ft.Column([
                            ft.Row([
                                ft.Text(video["name"], size=16, weight=ft.FontWeight.BOLD, color=ft.Colors.BLUE_900),
                                ft.Container(
                                    content=ft.Text(source_label, size=10, color=ft.Colors.WHITE),
                                    bgcolor=ft.Colors.TEAL_600 if source_label == "Desktop" else ft.Colors.BLUE_600,
                                    padding=ft.Padding(left=6, right=6, top=2, bottom=2),
                                    border_radius=8,
                                ),
                            ], spacing=8),
                            ft.Text(f"{created_time}  {size_mb:.1f} MB", size=12, color=ft.Colors.GREY_600),
                        ], spacing=4, expand=True),
                        ft.Row(action_buttons, spacing=4),
                    ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                    padding=20,
                    bgcolor=ft.Colors.WHITE,
                    border_radius=12,
                    border=ft.Border.all(1, ft.Colors.GREY_300),
                )
                history_list.controls.append(card)

        page.update()

    def _restore_main_area():
        try:
            main_area.content = jobs_content
            update_jobs_display()
            logger.info("Review panel closed, jobs view restored")
        except Exception as ex:
            logger.error(f"Error restoring main area: {ex}")

    # ================================================================
    # Phase 2.5 Review Dialog (shared for both Web and Desktop)
    # ================================================================
    def show_review_dialog(job_id: int, tts_script: list, mode: str = "web"):
        """Show TTS script review as an inline panel.
        mode: 'web' (async review_event) or 'desktop' (threading.Event)
        """
        nonlocal current_reviewing_job

        logger.info(f"Job #{job_id}: show_review_dialog called with {len(tts_script) if tts_script else 0} segments (mode={mode})")

        if not tts_script:
            if mode == "web":
                if job_id in running_jobs and "review_event" in running_jobs[job_id]:
                    running_jobs[job_id]["reviewed_script"] = None
                    running_jobs[job_id]["review_event"].set()
            elif mode == "desktop":
                if job_id in os_result_holders:
                    os_result_holders[job_id]["reviewed_script"] = None
                if job_id in os_review_events:
                    os_review_events[job_id].set()
            return

        job_info = running_jobs.get(job_id, {})
        video_name = job_info.get("video_name", f"Job {job_id}")

        segment_controls = []
        segments_column = ft.Column(spacing=10, scroll=ft.ScrollMode.AUTO, expand=True)

        def _make_delete_handler(target_idx):
            def handler(e):
                to_remove = None
                for ctrl in segment_controls:
                    if ctrl["index"] == target_idx:
                        to_remove = ctrl
                        break
                if to_remove:
                    segment_controls.remove(to_remove)
                    if to_remove["container"] in segments_column.controls:
                        segments_column.controls.remove(to_remove["container"])
                for new_i, ctrl in enumerate(segment_controls):
                    ctrl["index"] = new_i
                    badge = ctrl["container"].content.controls[0]
                    badge.content.value = str(new_i + 1)
                page.update()
            return handler

        def _build_segment_card(idx, text):
            text_field = ft.TextField(
                value=text, multiline=True, min_lines=2, max_lines=5, expand=True,
                bgcolor=ft.Colors.WHITE,
                border_color=ft.Colors.with_opacity(0.35, ft.Colors.BLUE_400),
                focused_border_color=ft.Colors.BLUE_600,
                border_radius=10, text_size=13,
                content_padding=ft.Padding(left=14, right=14, top=12, bottom=12),
                cursor_color=ft.Colors.BLUE_700,
            )
            number_badge = ft.Container(
                content=ft.Text(str(idx + 1), size=12, weight=ft.FontWeight.BOLD, color=ft.Colors.WHITE, text_align=ft.TextAlign.CENTER),
                width=28, height=28, border_radius=14, bgcolor=ft.Colors.BLUE_600,
                alignment=ft.alignment.Alignment(0, 0),
            )
            delete_btn = ft.IconButton(
                icon=ft.Icons.CLOSE_ROUNDED, icon_size=18,
                icon_color=ft.Colors.RED_400, tooltip="Xóa segment",
                style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=8)),
                on_click=_make_delete_handler(idx),
            )
            card = ft.Container(
                content=ft.Row([number_badge, text_field, delete_btn], spacing=12, vertical_alignment=ft.CrossAxisAlignment.START),
                padding=ft.Padding(left=14, right=10, top=12, bottom=12),
                border_radius=12,
                bgcolor=ft.Colors.with_opacity(0.04, ft.Colors.BLUE_600),
                border=ft.Border.all(1, ft.Colors.with_opacity(0.12, ft.Colors.BLUE_400)),
            )
            segment_controls.append({"index": idx, "text_field": text_field, "container": card})
            return card

        for idx, segment in enumerate(tts_script):
            seg_text = segment.get("text", "") if isinstance(segment, dict) else str(segment)
            card = _build_segment_card(idx, seg_text)
            segments_column.controls.append(card)

        def on_add_segment(e):
            new_idx = len(segment_controls)
            card = _build_segment_card(new_idx, "")
            segments_column.controls.append(card)
            page.update()

        def on_ok_click(e):
            nonlocal current_reviewing_job
            edited_script = []
            for ctrl in segment_controls:
                text = ctrl["text_field"].value.strip()
                if text:
                    edited_script.append({"text": text, "narration_index": ctrl["index"], "index": ctrl["index"]})
                    
            if not edited_script:
                page.snack_bar = ft.SnackBar(
                    content=ft.Text("Kịch bản thuyết minh không được để trống! Vui lòng nhập nội dung hoặc bấm Hủy bỏ.", color=ft.Colors.WHITE),
                    bgcolor=ft.Colors.ORANGE_600,
                )
                page.snack_bar.open = True
                page.update()
                return

            if mode == "web":
                if job_id in running_jobs:
                    running_jobs[job_id]["reviewed_script"] = edited_script
                    running_jobs[job_id]["status"] = "Đang xử lý tiếp video, vui lòng đợi..."
            elif mode == "desktop":
                if job_id in os_result_holders:
                    os_result_holders[job_id]["reviewed_script"] = edited_script

            current_reviewing_job = None
            if job_id in review_queue:
                review_queue.remove(job_id)
            _restore_main_area()

            # Resume pipeline
            if mode == "web":
                if job_id in running_jobs and "review_event" in running_jobs[job_id]:
                    running_jobs[job_id]["review_event"].set()
            elif mode == "desktop":
                if job_id in os_review_events:
                    os_review_events[job_id].set()

            logger.info(f"Job #{job_id}: Review completed, {len(edited_script)} segments")

        def on_cancel_click(e):
            nonlocal current_reviewing_job
            if mode == "web":
                if job_id in running_jobs:
                    running_jobs[job_id]["reviewed_script"] = None
            elif mode == "desktop":
                if job_id in os_result_holders:
                    os_result_holders[job_id]["reviewed_script"] = None

            current_reviewing_job = None
            if job_id in review_queue:
                review_queue.remove(job_id)
            _restore_main_area()

            if mode == "web":
                if job_id in running_jobs and "review_event" in running_jobs[job_id]:
                    running_jobs[job_id]["review_event"].set()
            elif mode == "desktop":
                if job_id in os_review_events:
                    os_review_events[job_id].set()

            logger.info(f"Job #{job_id}: Review cancelled")

        # Build review panel
        header = ft.Container(
            content=ft.Row([
                ft.Container(
                    content=ft.Icon(ft.Icons.RECORD_VOICE_OVER_ROUNDED, size=22, color=ft.Colors.WHITE),
                    width=40, height=40, border_radius=12, bgcolor=ft.Colors.BLUE_600,
                    alignment=ft.alignment.Alignment(0, 0),
                ),
                ft.Column([
                    ft.Text("Xem lại lời thoại TTS", size=18, weight=ft.FontWeight.W_700, color=ft.Colors.BLUE_900),
                    ft.Text(f"Job #{job_id}  |  {video_name}  |  {len(tts_script)} đoạn", size=12, color=ft.Colors.GREY_600),
                ], spacing=2),
            ], spacing=14, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            padding=ft.Padding(left=24, right=24, top=20, bottom=16),
            bgcolor=ft.Colors.with_opacity(0.06, ft.Colors.BLUE_600),
            border_radius=ft.BorderRadius(top_left=16, top_right=16, bottom_left=0, bottom_right=0),
        )

        info_row = ft.Container(
            content=ft.Row([
                ft.Icon(ft.Icons.INFO_OUTLINE_ROUNDED, size=16, color=ft.Colors.BLUE_400),
                ft.Text("Chỉnh sửa nội dung thuyết minh, sau đó nhấn Xác nhận để tiếp tục.",
                        size=12, color=ft.Colors.GREY_600, italic=True),
            ], spacing=8),
            padding=ft.Padding(left=24, right=24, top=12, bottom=8),
        )

        action_bar = ft.Container(
            content=ft.Row([
                ft.TextButton("Thêm đoạn mới", icon=ft.Icons.ADD_CIRCLE_OUTLINE_ROUNDED,
                    style=ft.ButtonStyle(color=ft.Colors.BLUE_600, shape=ft.RoundedRectangleBorder(radius=10),
                        padding=ft.Padding(left=14, right=18, top=10, bottom=10)),
                    on_click=on_add_segment),
                ft.Container(expand=True),
                ft.TextButton("Hủy bỏ", icon=ft.Icons.UNDO_ROUNDED,
                    style=ft.ButtonStyle(color=ft.Colors.GREY_600, shape=ft.RoundedRectangleBorder(radius=10),
                        padding=ft.Padding(left=14, right=18, top=10, bottom=10)),
                    on_click=on_cancel_click),
                ft.FilledButton("Xác nhận", icon=ft.Icons.CHECK_CIRCLE_OUTLINE_ROUNDED,
                    style=ft.ButtonStyle(bgcolor=ft.Colors.BLUE_600, color=ft.Colors.WHITE,
                        shape=ft.RoundedRectangleBorder(radius=10),
                        padding=ft.Padding(left=18, right=22, top=12, bottom=12)),
                    on_click=on_ok_click),
            ], alignment=ft.MainAxisAlignment.END, spacing=10),
            padding=ft.Padding(left=24, right=24, top=12, bottom=18),
            bgcolor=ft.Colors.with_opacity(0.03, ft.Colors.GREY_600),
            border_radius=ft.BorderRadius(top_left=0, top_right=0, bottom_left=16, bottom_right=16),
            border=ft.Border(top=ft.BorderSide(1, ft.Colors.with_opacity(0.1, ft.Colors.GREY_500))),
        )

        review_panel = ft.Container(
            content=ft.Column([header, info_row, segments_column, action_bar], spacing=0, expand=True),
            bgcolor=ft.Colors.WHITE, border_radius=16,
            border=ft.Border.all(1, ft.Colors.BLUE_200), expand=True, padding=0,
        )

        main_area.content = ft.Column([review_panel], spacing=0, expand=True)
        current_reviewing_job = job_id
        page.update()

    # ================================================================
    # "Ready to Record" Dialog for Desktop OS
    # ================================================================
    def show_ready_to_record_dialog(job_id: int):
        nonlocal current_reviewing_job

        job_info = running_jobs.get(job_id, {})
        video_name = job_info.get("video_name", f"Job {job_id}")

        def on_confirm(e):
            nonlocal current_reviewing_job
            current_reviewing_job = None
            _restore_main_area()
            if job_id in os_ready_events:
                os_ready_events[job_id].set()
            logger.info(f"Job #{job_id}: User confirmed ready to record")

        panel = ft.Container(
            content=ft.Column([
                ft.Container(
                    content=ft.Row([
                        ft.Container(
                            content=ft.Icon(ft.Icons.VIDEOCAM_ROUNDED, size=22, color=ft.Colors.WHITE),
                            width=40, height=40, border_radius=12, bgcolor=ft.Colors.GREEN_600,
                            alignment=ft.alignment.Alignment(0, 0),
                        ),
                        ft.Column([
                            ft.Text("Sẵn sàng quay video", size=18, weight=ft.FontWeight.W_700, color=ft.Colors.BLUE_900),
                            ft.Text(f"Job #{job_id}  |  {video_name}", size=12, color=ft.Colors.GREY_600),
                        ], spacing=2),
                    ], spacing=14, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                    padding=ft.Padding(left=24, right=24, top=20, bottom=16),
                    bgcolor=ft.Colors.with_opacity(0.06, ft.Colors.GREEN_600),
                    border_radius=ft.BorderRadius(top_left=16, top_right=16, bottom_left=0, bottom_right=0),
                ),
                ft.Container(
                    content=ft.Column([
                        ft.Text("Agent đã lên kịch bản xong!", size=14, weight=ft.FontWeight.BOLD, color=ft.Colors.BLUE_900),
                        ft.Text("Hãy reset trạng thái ứng dụng (Ctrl+Z) về trạng thái ban đầu, sau đó bấm nút bên dưới để bắt đầu quay.", size=13, color=ft.Colors.GREY_700),
                    ], spacing=8),
                    padding=ft.Padding(left=24, right=24, top=16, bottom=16),
                ),
                ft.Container(
                    content=ft.Row([
                        ft.Container(expand=True),
                        ft.FilledButton(
                            "Bắt đầu quay",
                            icon=ft.Icons.PLAY_ARROW_ROUNDED,
                            style=ft.ButtonStyle(
                                bgcolor=ft.Colors.GREEN_600, color=ft.Colors.WHITE,
                                shape=ft.RoundedRectangleBorder(radius=10),
                                padding=ft.Padding(left=18, right=22, top=12, bottom=12),
                            ),
                            on_click=on_confirm,
                        ),
                    ], alignment=ft.MainAxisAlignment.END, spacing=10),
                    padding=ft.Padding(left=24, right=24, top=12, bottom=18),
                    bgcolor=ft.Colors.with_opacity(0.03, ft.Colors.GREY_600),
                    border_radius=ft.BorderRadius(top_left=0, top_right=0, bottom_left=16, bottom_right=16),
                ),
            ], spacing=0),
            bgcolor=ft.Colors.WHITE, border_radius=16,
            border=ft.Border.all(1, ft.Colors.GREEN_300), expand=True, padding=0,
        )

        main_area.content = ft.Column([panel], spacing=0, expand=True)
        current_reviewing_job = job_id
        page.update()

    # ================================================================
    # Completion Dialog - Show when job finishes
    # ================================================================
    def show_completion_dialog(job_id: int, video_name: str, video_path: str, document_path: str = None, pdf_path: str = None, mode: str = "web"):
        """Show completion dialog with options to view results or go to history."""
        
        def on_view_video(e):
            open_video_file(video_path)
            close_dialog(e)
        
        def on_view_docx(e):
            if document_path:
                open_video_file(document_path)
            close_dialog(e)
        
        def on_view_pdf(e):
            if pdf_path:
                open_video_file(pdf_path)
            close_dialog(e)
        
        def on_open_folder(e):
            open_video_file(str(Path(video_path).parent))
            close_dialog(e)
        
        def on_go_to_history(e):
            switch_tab(1)
            close_dialog(e)
        
        def close_dialog(e):
            # Remove job from running_jobs
            if job_id in running_jobs:
                del running_jobs[job_id]
            _restore_main_area()
        
        # Build action buttons
        action_buttons = [
            ft.FilledButton(
                "Xem video",
                icon=ft.Icons.PLAY_CIRCLE_OUTLINE,
                style=ft.ButtonStyle(
                    bgcolor=ft.Colors.GREEN_600,
                    color=ft.Colors.WHITE,
                    shape=ft.RoundedRectangleBorder(radius=10),
                    padding=ft.Padding(left=18, right=22, top=12, bottom=12),
                ),
                on_click=on_view_video,
            ),
        ]
        
        if document_path:
            action_buttons.append(
                ft.OutlinedButton(
                    "Xem DOCX",
                    icon=ft.Icons.DESCRIPTION,
                    style=ft.ButtonStyle(
                        color=ft.Colors.BLUE_700,
                        shape=ft.RoundedRectangleBorder(radius=10),
                        padding=ft.Padding(left=18, right=22, top=12, bottom=12),
                    ),
                    on_click=on_view_docx,
                )
            )
        
        if pdf_path:
            action_buttons.append(
                ft.OutlinedButton(
                    "Xem PDF",
                    icon=ft.Icons.PICTURE_AS_PDF,
                    style=ft.ButtonStyle(
                        color=ft.Colors.RED_600,
                        shape=ft.RoundedRectangleBorder(radius=10),
                        padding=ft.Padding(left=18, right=22, top=12, bottom=12),
                    ),
                    on_click=on_view_pdf,
                )
            )
        
        action_buttons.append(
            ft.OutlinedButton(
                "Mở thư mục",
                icon=ft.Icons.FOLDER_OPEN,
                style=ft.ButtonStyle(
                    color=ft.Colors.BLUE_600,
                    shape=ft.RoundedRectangleBorder(radius=10),
                    padding=ft.Padding(left=18, right=22, top=12, bottom=12),
                ),
                on_click=on_open_folder,
            )
        )
        
        # Build completion panel
        header = ft.Container(
            content=ft.Row([
                ft.Container(
                    content=ft.Icon(ft.Icons.CHECK_CIRCLE_ROUNDED, size=28, color=ft.Colors.WHITE),
                    width=50, height=50, border_radius=25, bgcolor=ft.Colors.GREEN_600,
                    alignment=ft.alignment.Alignment(0, 0),
                ),
                ft.Column([
                    ft.Text("Hoàn thành!", size=22, weight=ft.FontWeight.W_700, color=ft.Colors.GREEN_800),
                    ft.Text(f"Video '{video_name}' đã được tạo thành công", size=14, color=ft.Colors.GREY_700),
                ], spacing=4),
            ], spacing=16, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            padding=ft.Padding(left=24, right=24, top=24, bottom=20),
            bgcolor=ft.Colors.with_opacity(0.08, ft.Colors.GREEN_600),
            border_radius=ft.BorderRadius(top_left=16, top_right=16, bottom_left=0, bottom_right=0),
        )
        
        # File info
        file_size = Path(video_path).stat().st_size / (1024 * 1024)
        file_info_items = [
            ft.Row([
                ft.Icon(ft.Icons.VIDEO_FILE, size=20, color=ft.Colors.BLUE_600),
                ft.Text(f"Video: {file_size:.1f} MB", size=13, color=ft.Colors.GREY_700),
            ], spacing=8),
        ]
        
        if document_path and Path(document_path).exists():
            doc_size = Path(document_path).stat().st_size / 1024
            file_info_items.append(
                ft.Row([
                    ft.Icon(ft.Icons.DESCRIPTION, size=20, color=ft.Colors.BLUE_700),
                    ft.Text(f"DOCX: {doc_size:.1f} KB", size=13, color=ft.Colors.GREY_700),
                ], spacing=8)
            )
        
        if pdf_path and Path(pdf_path).exists():
            pdf_size = Path(pdf_path).stat().st_size / 1024
            file_info_items.append(
                ft.Row([
                    ft.Icon(ft.Icons.PICTURE_AS_PDF, size=20, color=ft.Colors.RED_600),
                    ft.Text(f"PDF: {pdf_size:.1f} KB", size=13, color=ft.Colors.GREY_700),
                ], spacing=8)
            )
        
        info_section = ft.Container(
            content=ft.Column([
                ft.Text("Các file đã tạo:", size=13, weight=ft.FontWeight.BOLD, color=ft.Colors.BLUE_900),
                ft.Column(file_info_items, spacing=8),
            ], spacing=12),
            padding=ft.Padding(left=24, right=24, top=16, bottom=16),
        )
        
        # Action buttons section
        action_section = ft.Container(
            content=ft.Column([
                ft.Row(action_buttons, spacing=10, wrap=True),
                ft.Divider(height=1, color=ft.Colors.GREY_300),
                ft.Row([
                    ft.TextButton(
                        "Đóng",
                        icon=ft.Icons.CLOSE,
                        style=ft.ButtonStyle(
                            color=ft.Colors.GREY_600,
                            shape=ft.RoundedRectangleBorder(radius=10),
                        ),
                        on_click=close_dialog,
                    ),
                    ft.Container(expand=True),
                    ft.FilledButton(
                        "Xem lịch sử",
                        icon=ft.Icons.HISTORY,
                        style=ft.ButtonStyle(
                            bgcolor=ft.Colors.BLUE_600,
                            color=ft.Colors.WHITE,
                            shape=ft.RoundedRectangleBorder(radius=10),
                            padding=ft.Padding(left=18, right=22, top=12, bottom=12),
                        ),
                        on_click=on_go_to_history,
                    ),
                ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
            ], spacing=16),
            padding=ft.Padding(left=24, right=24, top=16, bottom=20),
            bgcolor=ft.Colors.with_opacity(0.03, ft.Colors.GREY_600),
            border_radius=ft.BorderRadius(top_left=0, top_right=0, bottom_left=16, bottom_right=16),
        )
        
        completion_panel = ft.Container(
            content=ft.Column([header, info_section, action_section], spacing=0),
            bgcolor=ft.Colors.WHITE,
            border_radius=16,
            border=ft.Border.all(2, ft.Colors.GREEN_300),
            width=600,
        )
        
        # Center the panel
        completion_content = ft.Container(
            content=completion_panel,
            alignment=ft.alignment.Alignment(0, 0),
            expand=True,
        )
        
        main_area.content = completion_content
        page.update()

    # ================================================================
    # Web Job Runner (from desktop_app pipeline.py)
    # ================================================================
    async def run_web_job(job_id: int, task: str, video_name: str, cdp_port: int, enable_tts: bool, tts_voice: str, tts_engine: str):
        nonlocal current_reviewing_job

        cancel_event = threading.Event()
        review_event = asyncio.Event()

        running_jobs[job_id]["cancel_event"] = cancel_event
        running_jobs[job_id]["review_event"] = review_event

        # Check Chrome
        if not check_chrome_running(cdp_port):
            logger.info(f"Job #{job_id}: Starting Chrome on port {cdp_port}")
            try:
                launch_chrome_with_cdp(cdp_port)
                await asyncio.sleep(3)
                if not check_chrome_running(cdp_port):
                    raise Exception(f"Chrome not responding on port {cdp_port}")
            except Exception as e:
                logger.error(f"Job #{job_id}: Failed to start Chrome: {e}")
                raise
        else:
            logger.info(f"Job #{job_id}: Reusing Chrome on port {cdp_port}")

        job_cdp_url = f"http://localhost:{cdp_port}"
        running_jobs[job_id]["cdp_port"] = cdp_port
        running_jobs[job_id]["cdp_url"] = job_cdp_url

        try:
            from pipeline import run_pipeline_v3

            async def progress_callback(phase, message, data=None):
                # Check cancellation at every callback
                if cancel_event.is_set():
                    logger.info(f"Job #{job_id} cancelled at phase {phase}")
                    raise asyncio.CancelledError("Job cancelled by user")

                # Phase messages in Vietnamese
                phase_messages = {
                    1: "Giai đoạn 1: Trình duyệt đang thực hiện nhiệm vụ...",
                    2: "Giai đoạn 2: Đang phân tích và tạo kịch bản...",
                    2.5: "Giai đoạn 2.5: Chờ xem lại lời thoại...",
                    3: "Giai đoạn 3: Đang tạo giọng đọc TTS...",
                    4: "Giai đoạn 4: Đang điều chỉnh thời lượng âm thanh...",
                    5: "Giai đoạn 5: Đang quay video...",
                    6: "Giai đoạn 6: Đang ghép âm thanh vào video...",
                }

                if phase == 2.5 and data:
                    if job_id not in review_queue:
                        review_queue.append(job_id)
                    running_jobs[job_id]["tts_script"] = data
                    running_jobs[job_id]["status"] = "Đang chờ xem lại lời thoại..."
                    running_jobs[job_id]["progress"] = phase / 6
                    update_jobs_display()

                    # Wait for turn in queue with frequent cancel checks
                    while current_reviewing_job is not None and current_reviewing_job != job_id:
                        if cancel_event.is_set():
                            logger.info(f"Job #{job_id} cancelled while waiting for review")
                            raise asyncio.CancelledError("Job cancelled by user")
                        await asyncio.sleep(0.2)  # Check more frequently

                    # Check again before showing dialog
                    if cancel_event.is_set():
                        raise asyncio.CancelledError("Job cancelled before review dialog")

                    running_jobs[job_id]["status"] = "Đang xem lại lời thoại..."
                    update_jobs_display()
                    show_review_dialog(job_id, data, mode="web")
                    
                    # Wait for review with cancel checks
                    while not review_event.is_set():
                        if cancel_event.is_set():
                            logger.info(f"Job #{job_id} cancelled during review")
                            raise asyncio.CancelledError("Job cancelled during review")
                        try:
                            await asyncio.wait_for(review_event.wait(), timeout=0.2)
                            break
                        except asyncio.TimeoutError:
                            continue
                    
                    reviewed_script = running_jobs[job_id].get("reviewed_script")
                    review_event.clear()
                    return reviewed_script

                if job_id in running_jobs:
                    running_jobs[job_id]["progress"] = phase / 6
                    # Use Vietnamese message if available, otherwise use provided message
                    running_jobs[job_id]["status"] = phase_messages.get(phase, message)
                    update_jobs_display()
                return None

            video_path = await run_pipeline_v3(
                task=task, video_name=video_name, cdp_url=job_cdp_url,
                enable_tts=enable_tts, tts_voice=tts_voice, tts_engine=tts_engine,
                padding_ms=300, enable_review=False,
                progress_callback=progress_callback, cancel_event=cancel_event,
            )

            if job_id in running_jobs:
                if video_path and Path(video_path).exists():
                    running_jobs[job_id]["status"] = "Hoàn thành!"
                    running_jobs[job_id]["progress"] = 1.0
                    running_jobs[job_id]["video_path"] = str(video_path)
                    update_jobs_display()
                    
                    # Show completion dialog
                    await asyncio.sleep(0.5)
                    show_completion_dialog(
                        job_id=job_id,
                        video_name=video_name,
                        video_path=str(video_path),
                        mode="web"
                    )
                else:
                    running_jobs[job_id]["status"] = "Lỗi: Không tạo được video"
                    running_jobs[job_id]["progress"] = 0
                    update_jobs_display()
                    await asyncio.sleep(5)
                    if job_id in running_jobs:
                        del running_jobs[job_id]
                        update_jobs_display()

        except asyncio.CancelledError:
            logger.info(f"Job #{job_id} (Web) cancelled successfully")
            if job_id in running_jobs:
                running_jobs[job_id]["status"] = "Đã hủy"
                running_jobs[job_id]["progress"] = 0
                update_jobs_display()
                
                # Show cancelled status briefly
                await asyncio.sleep(1.5)
                
                # Remove job from list
                if job_id in running_jobs:
                    del running_jobs[job_id]
                    update_jobs_display()
                    logger.info(f"Job #{job_id} removed from running jobs")
        except Exception as ex:
            logger.exception(f"Job #{job_id} failed")
            if job_id in running_jobs:
                running_jobs[job_id]["status"] = f"Lỗi: {str(ex)[:50]}"
                running_jobs[job_id]["progress"] = 0
                update_jobs_display()
                await asyncio.sleep(5)
                if job_id in running_jobs:
                    del running_jobs[job_id]
                    update_jobs_display()

    # ================================================================
    # Desktop OS Job Runner (from os_recorder pipeline)
    # ================================================================
    async def run_os_job(job_id: int, task: str, video_name: str, target_app: str, enable_tts: bool, tts_voice: str):
        nonlocal current_reviewing_job

        cancel_event = threading.Event()
        running_jobs[job_id]["cancel_event"] = cancel_event

        # Setup threading events for OS pipeline
        review_evt = threading.Event()
        ready_evt = threading.Event()
        result_holder = {}
        os_review_events[job_id] = review_evt
        os_ready_events[job_id] = ready_evt
        os_result_holders[job_id] = result_holder

        try:
            # Find target application PID
            running_jobs[job_id]["status"] = "Đang tìm ứng dụng..."
            running_jobs[job_id]["progress"] = 0.05
            update_jobs_display()

            from core.window_manager import get_visible_windows
            windows = get_visible_windows()

            # IDE/editor exclusion filter
            _ide_excl = lambda t: not any(x in t for x in ["visual studio code", "cursor", "kiro", ".py"])

            app_map = {
                "excel": {
                    "filter": lambda t: ("excel" in t or "book" in t) and _ide_excl(t),
                    "exe": "excel.exe",
                    "start_cmd": "start excel",
                },
                "word": {
                    "filter": lambda t: ("word" in t or "document" in t) and _ide_excl(t),
                    "exe": "winword.exe",
                    "start_cmd": "start winword",
                },
                "ppt": {
                    "filter": lambda t: ("powerpoint" in t or "presentation" in t) and _ide_excl(t),
                    "exe": "powerpnt.exe",
                    "start_cmd": "start powerpnt",
                },
                "notepad": {
                    "filter": lambda t: "notepad" in t and _ide_excl(t),
                    "exe": "notepad.exe",
                    "start_cmd": "notepad",
                },
                "chrome": {
                    "filter": lambda t: "google chrome" in t or ("chrome" in t and "edge" not in t),
                    "exe": "chrome.exe",
                    "start_cmd": 'start chrome "about:blank"',
                },
                "edge": {
                    "filter": lambda t: "edge" in t or "msedge" in t,
                    "exe": "msedge.exe",
                    "start_cmd": 'start msedge "about:blank"',
                },
                "firefox": {
                    "filter": lambda t: "firefox" in t or "mozilla" in t,
                    "exe": "firefox.exe",
                    "start_cmd": 'start firefox "about:blank"',
                },
            }

            # Handle custom process name
            if target_app == "custom":
                custom_name = custom_app_name_input.value.strip() if custom_app_name_input.value else ""
                if not custom_name:
                    raise Exception("Vui long nhap ten process cho ung dung tuy chinh")
                # Normalize: add .exe if missing
                if not custom_name.lower().endswith(".exe"):
                    custom_name += ".exe"
                base_name = custom_name.replace(".exe", "").lower()
                app_info = {
                    "filter": lambda t, bn=base_name: bn in t,
                    "exe": custom_name,
                    "start_cmd": f"start {custom_name}",
                }
            else:
                app_info = app_map.get(target_app, app_map["notepad"])

            app_win = next(
                (w for w in windows if app_info["filter"](w["title"].lower())),
                None,
            )

            if not app_win:
                running_jobs[job_id]["status"] = f"Dang khoi dong {target_app}..."
                update_jobs_display()
                subprocess.Popen(app_info["start_cmd"], shell=True)
                await asyncio.sleep(4)
                windows = get_visible_windows()
                app_win = next(
                    (w for w in windows if app_info["filter"](w["title"].lower())),
                    None,
                )

            if not app_win:
                raise Exception(f"Khong tim thay cua so {target_app}")

            pid = app_win["pid"]
            logger.info(f"Job #{job_id}: Found {target_app} PID={pid}")

            running_jobs[job_id]["status"] = "Giai đoạn 1: AI đang lên kịch bản..."
            running_jobs[job_id]["progress"] = 0.1
            update_jobs_display()

            # Progress callback adapter (runs on background thread, schedules UI updates)
            phase_2_5_shown = False
            phase_3_shown = False

            def os_progress_callback(phase, message, narrations=None):
                nonlocal phase_2_5_shown, phase_3_shown

                # Check cancellation at every callback
                if cancel_event.is_set():
                    logger.info(f"Job #{job_id} cancelled at phase {phase}")
                    return  # Return immediately to stop pipeline

                # Phase messages in Vietnamese for Desktop mode
                phase_messages = {
                    1.0: "Giai đoạn 1: AI đang lên kịch bản...",
                    2.0: "Giai đoạn 2: Đang tạo giọng đọc TTS...",
                    2.5: "Giai đoạn 2.5: Chờ xem lại lời thoại...",
                    3.0: "Giai đoạn 3: Sẵn sàng quay video...",
                    4.0: "Giai đoạn 4: Đang ghép âm thanh vào video...",
                    5.0: "Giai đoạn 5: Đang tạo tài liệu DOCX và PDF...",
                }

                if phase == 2.5 and narrations and not phase_2_5_shown:
                    phase_2_5_shown = True
                    # Check cancel before showing dialog
                    if cancel_event.is_set():
                        logger.info(f"Job #{job_id} cancelled before review dialog")
                        return
                    
                    # Schedule UI review dialog on main thread
                    running_jobs[job_id]["status"] = "Giai đoạn 2.5: Chờ xem lại lời thoại..."
                    running_jobs[job_id]["progress"] = 0.3
                    # Must schedule on main event loop
                    page.run_thread(lambda: show_review_dialog(job_id, narrations, mode="desktop"))
                    return

                if phase == 3.0 and not phase_3_shown:
                    phase_3_shown = True
                    # Check cancel before showing dialog
                    if cancel_event.is_set():
                        logger.info(f"Job #{job_id} cancelled before ready dialog")
                        return
                    
                    running_jobs[job_id]["status"] = "Sẵn sàng quay video..."
                    running_jobs[job_id]["progress"] = 0.5
                    # Show ready-to-record dialog
                    page.run_thread(lambda: show_ready_to_record_dialog(job_id))
                    return

                # Generic progress update
                if job_id in running_jobs:
                    running_jobs[job_id]["progress"] = min(phase / 6.0, 0.95)
                    # Use Vietnamese message if available
                    running_jobs[job_id]["status"] = phase_messages.get(phase, message)
                    try:
                        page.update()
                    except Exception:
                        pass

            # Run OS pipeline in background thread
            from os_pipeline_main import run_os_pipeline_v3_dual
            
            # Get dual output setting
            enable_dual = enable_dual_output_checkbox.value

            pipeline_result = await asyncio.to_thread(
                run_os_pipeline_v3_dual,
                target_pid=pid,
                task_description=task,
                output_dir=str(OS_RECORDER_DIR / "workspace" / "output"),
                video_name=video_name,
                voice=tts_voice if tts_voice else "banmai",
                max_agent_steps=30,  # Tang tu 15 len 30 cho PowerPoint co nhieu slide
                dry_run=False,
                skip_tts=not enable_tts,
                app_executable=app_info["exe"],
                progress_callback=os_progress_callback,
                cancel_event=cancel_event,
                review_event=review_evt,
                review_result_holder=result_holder,
                ready_event=os_ready_events.get(job_id),
                enable_dual_output=enable_dual,
            )

            # Check if cancelled during pipeline execution
            # asyncio.to_thread does NOT raise CancelledError when the thread
            # finishes naturally, so we must check explicitly
            if cancel_event.is_set():
                logger.info(f"Job #{job_id} (Desktop) was cancelled during pipeline")
                if job_id in running_jobs:
                    running_jobs[job_id]["status"] = "Da huy"
                    running_jobs[job_id]["progress"] = 0
                    update_jobs_display()
                    await asyncio.sleep(1.5)
                    if job_id in running_jobs:
                        del running_jobs[job_id]
                        update_jobs_display()
                return

            # Check result
            video_path = pipeline_result.get("video_final_path") or pipeline_result.get("video_raw_path")
            document_path = pipeline_result.get("document_path")
            pdf_path = pipeline_result.get("pdf_path")

            if job_id in running_jobs:
                if video_path and Path(video_path).exists():
                    status_parts = ["Hoàn thành!"]
                    if document_path and Path(document_path).exists():
                        status_parts.append("DOCX")
                    if pdf_path and Path(pdf_path).exists():
                        status_parts.append("PDF")
                    
                    running_jobs[job_id]["status"] = " + ".join(status_parts)
                    running_jobs[job_id]["progress"] = 1.0
                    running_jobs[job_id]["video_path"] = str(video_path)
                    if document_path:
                        running_jobs[job_id]["document_path"] = str(document_path)
                    if pdf_path:
                        running_jobs[job_id]["pdf_path"] = str(pdf_path)
                    update_jobs_display()
                    
                    # Show completion dialog
                    await asyncio.sleep(0.5)
                    show_completion_dialog(
                        job_id=job_id,
                        video_name=video_name,
                        video_path=str(video_path),
                        document_path=str(document_path) if document_path else None,
                        pdf_path=str(pdf_path) if pdf_path else None,
                        mode="desktop"
                    )
                else:
                    error = pipeline_result.get("error", "Không tạo được video")
                    running_jobs[job_id]["status"] = f"Lỗi: {error[:50]}"
                    running_jobs[job_id]["progress"] = 0
                    update_jobs_display()
                    await asyncio.sleep(5)
                    if job_id in running_jobs:
                        del running_jobs[job_id]
                        update_jobs_display()

        except asyncio.CancelledError:
            logger.info(f"Job #{job_id} (Desktop) cancelled successfully")
            if job_id in running_jobs:
                running_jobs[job_id]["status"] = "Đã hủy"
                running_jobs[job_id]["progress"] = 0
                update_jobs_display()
                
                # Show cancelled status briefly
                await asyncio.sleep(1.5)
                
                # Remove job from list
                if job_id in running_jobs:
                    del running_jobs[job_id]
                    update_jobs_display()
                    logger.info(f"Job #{job_id} removed from running jobs")
        except Exception as ex:
            logger.exception(f"Job #{job_id} failed")
            if job_id in running_jobs:
                running_jobs[job_id]["status"] = f"Lỗi: {str(ex)[:50]}"
                running_jobs[job_id]["progress"] = 0
                update_jobs_display()
                await asyncio.sleep(5)
                if job_id in running_jobs:
                    del running_jobs[job_id]
                    update_jobs_display()
        finally:
            # Cleanup events
            os_review_events.pop(job_id, None)
            os_ready_events.pop(job_id, None)
            os_result_holders.pop(job_id, None)

    # ================================================================
    # Start Pipeline Click (Routing)
    # ================================================================
    async def start_pipeline_click(e):
        nonlocal job_counter

        task = task_input.value.strip() if task_input.value else ""
        video_name = video_name_input.value.strip() if video_name_input.value else ""
        env = env_dropdown.value

        if not task or not video_name:
            page.snack_bar = ft.SnackBar(
                content=ft.Text("Vui lòng điền đầy đủ thông tin!", color=ft.Colors.WHITE),
                bgcolor=ft.Colors.RED_600,
            )
            page.snack_bar.open = True
            page.update()
            return
            
        import re
        invalid_chars = r'[\\/:*?"<>|]'
        if re.search(invalid_chars, video_name):
            video_name = re.sub(invalid_chars, '_', video_name)
            video_name_input.value = video_name
            page.snack_bar = ft.SnackBar(
                content=ft.Text(f"Tên video đã chứa ký tự không hợp lệ và được tự động đổi thành: {video_name}", color=ft.Colors.WHITE),
                bgcolor=ft.Colors.ORANGE_600,
            )
            page.snack_bar.open = True
            page.update()

        run_button.disabled = True
        page.update()

        job_counter += 1
        job_id = job_counter

        running_jobs[job_id] = {
            "task": task,
            "video_name": video_name,
            "progress": 0,
            "status": "Đang khởi động...",
            "started": datetime.now(),
            "env": env,
        }

        if env == "web":
            cdp_port = int(cdp_port_dropdown.value)
            task_handle = asyncio.create_task(
                run_web_job(job_id, task, video_name, cdp_port,
                    enable_tts_checkbox.value, tts_voice_dropdown.value, tts_engine_dropdown.value)
            )
        else:
            target_app = target_app_dropdown.value
            running_jobs[job_id]["target_app"] = target_app
            task_handle = asyncio.create_task(
                run_os_job(job_id, task, video_name, target_app,
                    enable_tts_checkbox.value, tts_voice_dropdown.value)
            )

        running_jobs[job_id]["task_handle"] = task_handle
        update_jobs_display()

        page.snack_bar = ft.SnackBar(
            content=ft.Text(f"Job #{job_id} đã bắt đầu!", color=ft.Colors.WHITE),
            bgcolor=ft.Colors.GREEN_600,
        )
        page.snack_bar.open = True
        page.update()
        
        await asyncio.sleep(1)
        run_button.disabled = False
        page.update()

    run_button = ft.FilledButton(
        "Tạo video mới",
        icon=ft.Icons.ADD_CIRCLE,
        on_click=lambda e: asyncio.create_task(start_pipeline_click(e)),
        height=48,
        expand=True,
    )

    # ================================================================
    # Layout
    # ================================================================
    sidebar = ft.Container(
        content=ft.Container(
            content=ft.Column([
                ft.Text("Cấu hình video", size=16, weight=ft.FontWeight.BOLD, color=ft.Colors.BLUE_900),
                task_input,
                video_name_input,
                ft.Divider(height=1, color=ft.Colors.GREY_200),
                ft.Text("Môi trường", size=13, weight=ft.FontWeight.BOLD, color=ft.Colors.BLUE_800),
                env_dropdown,
                web_section,
                desktop_section,
                ft.Divider(height=1, color=ft.Colors.GREY_200),
                ft.Text("Cài đặt TTS", size=13, weight=ft.FontWeight.BOLD, color=ft.Colors.BLUE_800),
                enable_tts_checkbox,
                ft.Row([tts_engine_dropdown, tts_voice_dropdown], spacing=10),
                run_button,
            ], spacing=8, scroll=ft.ScrollMode.AUTO, expand=True),
            bgcolor=ft.Colors.WHITE,
            border_radius=14,
            padding=20,
            border=ft.Border.all(1, ft.Colors.GREY_200),
            expand=True,
        ),
        width=360,
        padding=ft.Padding(left=14, right=6, top=10, bottom=10),
        bgcolor=ft.Colors.GREY_50,
        expand=True,
    )

    main_area = ft.Container(
        content=ft.Container(
            content=ft.Column([
                ft.Container(
                    content=ft.Row([
                        ft.Icon(ft.Icons.WORK_OUTLINE, size=26, color=ft.Colors.BLUE_700),
                        ft.Text("Jobs đang chạy", size=18, weight=ft.FontWeight.BOLD, color=ft.Colors.BLUE_900),
                    ], spacing=10),
                    padding=ft.Padding.only(bottom=10),
                ),
                ft.Container(content=jobs_list, expand=True),
            ], spacing=0, expand=True),
            bgcolor=ft.Colors.WHITE,
            border_radius=14,
            padding=20,
            border=ft.Border.all(1, ft.Colors.GREY_200),
            expand=True,
        ),
        padding=ft.Padding(left=6, right=14, top=10, bottom=10),
        expand=True,
    )
    jobs_content = main_area.content

    create_tab_content = ft.Container(
        content=ft.Row([sidebar, main_area], spacing=0, expand=True,
            vertical_alignment=ft.CrossAxisAlignment.STRETCH),
        expand=True,
    )

    history_tab_content = ft.Container(
        content=ft.Column([
            ft.Container(
                content=ft.Row([
                    ft.Container(
                        content=ft.Icon(ft.Icons.HISTORY, size=28, color=ft.Colors.BLUE_600),
                        bgcolor=ft.Colors.BLUE_50, border_radius=50, padding=10,
                    ),
                    ft.Text("Lịch sử video", size=20, weight=ft.FontWeight.BOLD, color=ft.Colors.BLUE_900),
                    ft.Container(expand=True),
                    ft.IconButton(icon=ft.Icons.REFRESH, icon_size=24, icon_color=ft.Colors.BLUE_600,
                        tooltip="Làm mới", on_click=lambda e: load_history_tab(), bgcolor=ft.Colors.BLUE_50),
                ], spacing=12, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                padding=ft.Padding.only(bottom=20),
            ),
            ft.Container(content=history_list, expand=True),
        ], spacing=0, expand=True),
        padding=24,
        expand=True,
    )

    # Tab navigation
    tab_create_btn = ft.Container(
        content=ft.Row([
            ft.Icon(ft.Icons.ADD_CIRCLE_OUTLINE, size=20),
            ft.Text("Tạo video", size=14, weight=ft.FontWeight.BOLD),
        ], spacing=8),
        padding=ft.Padding(left=18, right=18, top=10, bottom=10),
        border_radius=10,
    )

    tab_history_btn = ft.Container(
        content=ft.Row([
            ft.Icon(ft.Icons.HISTORY, size=20),
            ft.Text("Lịch sử", size=14, weight=ft.FontWeight.BOLD),
        ], spacing=8),
        padding=ft.Padding(left=18, right=18, top=10, bottom=10),
        border_radius=10,
    )

    tab_bar = ft.Container(
        content=ft.Row([tab_create_btn, tab_history_btn], spacing=8),
        padding=ft.Padding(left=14, right=14, top=8, bottom=8),
        bgcolor=ft.Colors.WHITE,
    )

    content_container = ft.Container(content=create_tab_content, expand=True)

    def switch_tab(index):
        nonlocal current_tab
        current_tab = index

        if index == 0:
            tab_create_btn.bgcolor = ft.Colors.BLUE_600
            tab_create_btn.content.controls[0].color = ft.Colors.WHITE
            tab_create_btn.content.controls[1].color = ft.Colors.WHITE
            tab_history_btn.bgcolor = ft.Colors.TRANSPARENT
            tab_history_btn.content.controls[0].color = ft.Colors.GREY_600
            tab_history_btn.content.controls[1].color = ft.Colors.GREY_600
            content_container.content = create_tab_content
            update_jobs_display()
        else:
            tab_create_btn.bgcolor = ft.Colors.TRANSPARENT
            tab_create_btn.content.controls[0].color = ft.Colors.GREY_600
            tab_create_btn.content.controls[1].color = ft.Colors.GREY_600
            tab_history_btn.bgcolor = ft.Colors.BLUE_600
            tab_history_btn.content.controls[0].color = ft.Colors.WHITE
            tab_history_btn.content.controls[1].color = ft.Colors.WHITE
            content_container.content = history_tab_content
            load_history_tab()

        page.update()

    tab_create_btn.on_click = lambda e: switch_tab(0)
    tab_history_btn.on_click = lambda e: switch_tab(1)

    main_layout = ft.Column([tab_bar, content_container], spacing=0, expand=True)

    BASE_WIDTH = 1280
    BASE_HEIGHT = 680

    app_container = ft.Container(
        content=main_layout, width=BASE_WIDTH, height=BASE_HEIGHT, bgcolor=ft.Colors.GREY_50,
    )

    center_wrapper = ft.Container(
        content=app_container, alignment=ft.alignment.Alignment(0, 0),
        expand=True, bgcolor=ft.Colors.GREY_50,
    )

    def on_resize(e):
        current_width = page.width
        current_height = page.height
        if current_width == 0 or current_height == 0:
            return
        scale = min(current_width / BASE_WIDTH, current_height / BASE_HEIGHT)
        app_container.scale = scale
        app_container.update()

    page.on_resize = on_resize
    page.add(center_wrapper)
    on_resize(None)
    switch_tab(0)


if __name__ == "__main__":
    ft.run(main)
