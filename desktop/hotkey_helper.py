from __future__ import annotations

import base64
import array
import ctypes
import hashlib
import json
import logging
import math
import os
import queue
import struct
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
import wave
import winsound
from ctypes import wintypes
from io import BytesIO
from pathlib import Path
from typing import Any

import keyboard
import pyperclip
import pystray
import tkinter as tk
import tkinter.font as tkfont
from PIL import Image, ImageDraw, ImageFont, ImageGrab, ImageTk
import pyaudiowpatch as pyaudio

try:
    from .windows_hotkeys import WindowsHotkeys, modifiers_pressed, shortcut_pressed
    from .speech_output import AUDIO_API_LOCK, play_wav
except ImportError:
    from windows_hotkeys import WindowsHotkeys, modifiers_pressed, shortcut_pressed
    from speech_output import AUDIO_API_LOCK, play_wav


class _Rect(ctypes.Structure):
    _fields_ = [("left", wintypes.LONG), ("top", wintypes.LONG), ("right", wintypes.LONG), ("bottom", wintypes.LONG)]


class _Point(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


class _MonitorInfo(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", _Rect), ("rcWork", _Rect), ("dwFlags", wintypes.DWORD)]


class _GuiThreadInfo(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("hwndActive", wintypes.HWND),
        ("hwndFocus", wintypes.HWND),
        ("hwndCapture", wintypes.HWND),
        ("hwndMenuOwner", wintypes.HWND),
        ("hwndMoveSize", wintypes.HWND),
        ("hwndCaret", wintypes.HWND),
        ("rcCaret", _Rect),
    ]


PROJECT_ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
if getattr(sys, "frozen", False):
    executable_dir = Path(sys.executable).resolve().parent
    candidates = [executable_dir, *executable_dir.parents]
    PROJECT_ROOT = next(
        (candidate for candidate in candidates if (candidate / "start.ps1").is_file()),
        executable_dir,
    )
CONFIG_PATH = PROJECT_ROOT / "config" / "hotkey.local.json"
RUN_DIR = PROJECT_ROOT / ".run"
API_URL = "http://127.0.0.1:8765"
DEFAULTS: dict[str, Any] = {
    "hotkey": "ctrl+alt+space",
    "text_translate_hotkey": "f8",
    "text_source_language": "vi",
    "text_target_language": "en",
    "microphone": "__default__",
    "mode": "fast",
    "source_language": "vi",
    "target_language": "en",
    "translate": True,
    "screen_hotkey": "ctrl+alt+t",
    "screen_read_hotkey": "ctrl+alt+r",
    "screen_read_source_language": "auto",
    "screen_read_target_language": "vi",
    "screen_read_mode": "source",
    "screen_read_output_device": "__default__",
    "screen_read_voices": {"en": "am_adam", "zh": "zm_yunxi", "vi": "F1", "ja": "F1", "ko": "F1"},
    "screen_source_language": "zh",
    "screen_target_language": "vi",
    "screen_processor": "cpu",
    "screen_font_size": 14,
    "screen_text_color": "#ffffff",
    "screen_background_color": "#040806",
    "screen_continuous": True,
    "screen_exit_hotkey": "esc",
    "screen_refresh_seconds": 1.0,
    "screen_overlay_opacity": 0.92,
    "show_status_overlay": True,
}

RUN_DIR.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    filename=RUN_DIR / "hotkey.log",
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    encoding="utf-8",
)


class VoiceTypingHelper:
    def __init__(self) -> None:
        self.settings = self._load_settings()
        self.settings_mtime = self._mtime()
        self.hotkey_handles: list[Any] = []
        self.release_hook: Any | None = None
        self.release_keys: set[str] = set()
        self.native_hotkeys: WindowsHotkeys | None = None
        self.hotkey_results: dict[str, dict] = {}
        self.last_status = "Starting"
        self.state_lock = threading.Lock()
        self.hotkey_active = False
        self.starting = False
        self.stopping = False
        self.recording = False
        self.processing = False
        self.screen_selecting = False
        self.screen_processing = False
        self.screen_job_id = 0
        self.screen_action = "translate"
        self.screen_last_text = ""
        self.screen_empty_frames = 0
        self.screen_overlay_bbox: tuple[int, int, int, int] | None = None
        self.frames: list[bytes] = []
        self.audio: Any | None = None
        self.stream: Any | None = None
        self.sample_rate = 16_000
        self.channels = 1
        self.record_thread: threading.Thread | None = None
        self.stop_event = threading.Event()
        self.icon: pystray.Icon | None = None
        self.target_window: int | None = None
        self.target_control: int | None = None
        self.overlay: tk.Tk | None = None
        self.overlay_canvas: tk.Canvas | None = None
        self.overlay_status: int | None = None
        self.overlay_message: int | None = None
        self.status_queue: queue.SimpleQueue[tuple[str, str]] = queue.SimpleQueue()
        self.ui_queue: queue.SimpleQueue[tuple[str, Any]] = queue.SimpleQueue()
        self.screen_selector: tk.Toplevel | None = None
        self.screen_selection_image: Any | None = None
        self.screen_translation_overlay: tk.Toplevel | None = None
        self.screen_translation_labels: list[tk.Label] = []
        self.sound_dir = RUN_DIR / "sounds"
        self.engine_lock = threading.Lock()
        self._prepare_sounds()

    def _mtime(self) -> float:
        try:
            return CONFIG_PATH.stat().st_mtime
        except OSError:
            return 0.0

    def _load_settings(self) -> dict[str, Any]:
        settings = dict(DEFAULTS)
        try:
            payload = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            settings.update({key: payload[key] for key in DEFAULTS if key in payload})
        except (OSError, ValueError, TypeError):
            pass
        return settings

    def _register_hotkey(self) -> None:
        if self.native_hotkeys is not None:
            self.native_hotkeys.stop()
        callbacks = {"hotkey": self._native_start_recording,
                     "text_translate_hotkey": self.request_text_translation,
                     "screen_hotkey": self.request_screen_translation,
                     "screen_read_hotkey": self.request_screen_read}
        self.native_hotkeys = WindowsHotkeys({name: (str(self.settings[name]), callback) for name, callback in callbacks.items()})
        self.hotkey_results = self.native_hotkeys.start()
        self.applied_settings = dict(self.settings)
        self._write_runtime_status()

    def _native_start_recording(self) -> None:
        self.start_recording()
        # Poll physical key state so releasing any key also stops capture when
        # the keyboard hook is unavailable or a game intercepts key events.
        while not self.stop_event.wait(0.025):
            if not shortcut_pressed(str(self.settings["hotkey"])):
                self.stop_recording()
                return

    def _write_runtime_status(self) -> None:
        payload = {"pid": os.getpid(), "updated_at": time.time(), "status": self.last_status,
                   "hotkeys": self.hotkey_results, "settings": dict(self.applied_settings),
                   "listener_alive": bool(self.native_hotkeys and self.native_hotkeys.thread.is_alive())}
        temporary = RUN_DIR / "hotkey-status.tmp"
        temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        os.replace(temporary, RUN_DIR / "hotkey-status.json")

    def _on_key_release(self, event: keyboard.KeyboardEvent) -> None:
        name = (event.name or "").casefold()
        aliases = {name, name.replace("left ", ""), name.replace("right ", "")}
        if aliases & self.release_keys:
            self.stop_recording()

    def _watch_settings(self) -> None:
        while not self.stop_event.wait(2):
            current_mtime = self._mtime()
            if current_mtime != self.settings_mtime and not self.recording:
                self.settings_mtime = current_mtime
                self.settings = self._load_settings()
                try:
                    self._register_hotkey()
                    self.ui_queue.put(("status_visibility", None))
                    self._notify("Đã cập nhật phím tắt")
                except Exception:
                    logging.exception("Could not reload hotkey")
            try:
                self._write_runtime_status()
            except OSError:
                logging.exception("Could not write helper heartbeat")

    def _notify(self, message: str) -> None:
        logging.info(message)

    @staticmethod
    def _api_ready() -> bool:
        try:
            with urllib.request.urlopen(f"{API_URL}/health", timeout=1.2) as response:
                payload = json.loads(response.read().decode("utf-8"))
            return bool(payload.get("ok")) and payload.get("translator") == "hy-mt2"
        except Exception:
            return False

    def _ensure_engine(self) -> bool:
        if self._api_ready():
            return True
        if not self.engine_lock.acquire(blocking=False):
            return False
        try:
            if self._api_ready():
                return True
            start_script = PROJECT_ROOT / "start.ps1"
            if not start_script.is_file():
                self._set_status("error", "THIẾU START.PS1 · chạy bộ cài SpeakBridge")
                logging.error("Cannot auto-start engine; missing %s", start_script)
                return False
            self._set_status("processing", "ĐANG KHỞI ĐỘNG ENGINE · vui lòng chờ")
            logging.info("Starting SpeakBridge engine in the background")
            subprocess.Popen(
                [
                    "powershell.exe",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(start_script),
                    "-NoBrowser",
                ],
                cwd=str(PROJECT_ROOT),
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            for _ in range(180):
                if self.stop_event.wait(0.5):
                    return False
                if self._api_ready():
                    self._set_status("ready", f"Sẵn sàng · {self.settings['hotkey']}")
                    logging.info("SpeakBridge engine is ready")
                    return True
            self._set_status("error", "ENGINE KHÔNG KHỞI ĐỘNG · xem thư mục .run")
            logging.error("SpeakBridge engine did not become ready within 90 seconds")
            return False
        except Exception:
            logging.exception("Could not auto-start SpeakBridge engine")
            self._set_status("error", "KHÔNG KHỞI ĐỘNG ĐƯỢC ENGINE")
            return False
        finally:
            self.engine_lock.release()

    def _set_status(self, state: str, message: str, notify: bool = False) -> None:
        del notify  # Status is shown by the quiet overlay, never by Windows toast.
        colors = {
            "ready": "#c9ff5d",
            "selecting": "#68f0b8",
            "recording": "#ff685f",
            "processing": "#ffba72",
            "done": "#68f0b8",
            "error": "#ff685f",
        }
        logging.info("%s: %s", state.upper(), message)
        self.last_status = message
        self.status_queue.put((state, message))
        if self.icon:
            self.icon.icon = self._icon_image(colors.get(state, "#c9ff5d"))
            self.icon.title = f"SpeakBridge · {message}"

    def _prepare_sounds(self) -> None:
        """Create low-volume, soft sine chimes instead of harsh PC speaker beeps."""
        self.sound_dir.mkdir(parents=True, exist_ok=True)
        patterns = {
            "start": [(620, 55), (820, 75)],
            "processing": [(540, 55), (690, 65)],
            "done": [(720, 65), (960, 75), (1240, 85)],
            "error": [(360, 85), (260, 110)],
        }
        sample_rate = 24_000
        for name, notes in patterns.items():
            path = self.sound_dir / f"{name}.wav"
            if path.exists():
                continue
            samples: list[int] = []
            for frequency, duration_ms in notes:
                count = int(sample_rate * duration_ms / 1000)
                fade = max(1, int(count * 0.20))
                for index in range(count):
                    envelope = min(1.0, index / fade, (count - index - 1) / fade)
                    # A quiet fundamental plus a small upper harmonic gives a clean tech chime.
                    value = (math.sin(2 * math.pi * frequency * index / sample_rate) * 0.10)
                    value += (math.sin(2 * math.pi * frequency * 2 * index / sample_rate) * 0.018)
                    samples.append(int(32767 * envelope * value))
                samples.extend([0] * int(sample_rate * 0.012))
            with wave.open(str(path), "wb") as output:
                output.setnchannels(1)
                output.setsampwidth(2)
                output.setframerate(sample_rate)
                output.writeframes(struct.pack(f"<{len(samples)}h", *samples))

    def _play_sound(self, name: str) -> None:
        path = self.sound_dir / f"{name}.wav"
        try:
            winsound.PlaySound(
                str(path), winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT
            )
        except Exception:
            logging.exception("Could not play status sound %s", name)

    def _create_overlay(self) -> None:
        root = tk.Tk()
        self.overlay = root
        root.title("SpeakBridge Status")
        root.overrideredirect(True)
        root.configure(bg="#0b100d")
        root.attributes("-topmost", True)
        root.attributes("-alpha", 0.94)
        width, height = 430, 64
        x = max(12, (root.winfo_screenwidth() - width) // 2)
        root.geometry(f"{width}x{height}+{x}+18")
        canvas = tk.Canvas(root, width=width, height=height, bg="#0b100d", highlightthickness=1, highlightbackground="#263229")
        canvas.pack(fill="both", expand=True)
        self.overlay_canvas = canvas
        canvas.create_oval(18, 22, 38, 42, fill="#c9ff5d", outline="", tags="dot")
        self.overlay_status = canvas.create_text(52, 20, anchor="nw", fill="#c9ff5d", font=("Segoe UI Semibold", 10), text="SPEAKBRIDGE · SẴN SÀNG")
        self.overlay_message = canvas.create_text(52, 39, anchor="nw", fill="#b8c0b9", font=("Segoe UI", 9), text=f"Giữ {self.settings['hotkey']} để nói")
        root.update_idletasks()
        hwnd = int(root.winfo_id())
        user32 = ctypes.windll.user32
        parent = int(user32.GetParent(hwnd))
        if parent:
            hwnd = parent
        GWL_EXSTYLE = -20
        WS_EX_TOOLWINDOW = 0x00000080
        WS_EX_NOACTIVATE = 0x08000000
        style = int(user32.GetWindowLongW(hwnd, GWL_EXSTYLE))
        user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE)
        self._exclude_window_from_capture(root)
        if not bool(self.settings.get("show_status_overlay", True)):
            root.withdraw()
        root.after(40, self._poll_overlay)

    def _poll_overlay(self) -> None:
        # Observe the exit chord only while a screen action is open. Reserving
        # Escape globally would prevent other apps from receiving it.
        if (self.screen_selecting or self.screen_processing or self.screen_translation_overlay is not None) and shortcut_pressed(str(self.settings.get("screen_exit_hotkey", "esc"))):
            self._on_screen_exit()
        colors = {
            "ready": "#c9ff5d",
            "selecting": "#68f0b8",
            "recording": "#ff685f",
            "processing": "#ffba72",
            "done": "#68f0b8",
            "error": "#ff685f",
        }
        labels = {
            "ready": "SPEAKBRIDGE · SẴN SÀNG",
            "selecting": "SPEAKBRIDGE · CHỌN VÙNG DỊCH",
            "recording": "SPEAKBRIDGE · ĐANG NGHE",
            "processing": "SPEAKBRIDGE · ĐANG DỊCH",
            "done": "SPEAKBRIDGE · HOÀN THÀNH",
            "error": "SPEAKBRIDGE · CẦN THỬ LẠI",
        }
        if self.screen_action == "read":
            labels["selecting"] = "SPEAKBRIDGE · CHỌN VÙNG ĐỌC"
            labels["processing"] = "SPEAKBRIDGE · ĐANG TẠO GIỌNG ĐỌC"
        latest: tuple[str, str] | None = None
        while True:
            try:
                command, payload = self.ui_queue.get_nowait()
            except queue.Empty:
                break
            if command == "select_screen":
                try:
                    self._begin_screen_selection()
                except Exception as exc:
                    logging.exception("Could not open desktop screen selector")
                    with self.state_lock:
                        self.screen_selecting = False
                        self.screen_processing = False
                    self._set_status("error", f"KHÔNG MỞ ĐƯỢC VÙNG CHỌN · {exc}")
            elif command == "screen_result":
                job_id, bbox, result = payload
                if job_id == self.screen_job_id:
                    self._handle_screen_result(bbox, job_id, result)
            elif command == "screen_read_result":
                job_id, result = payload
                if job_id == self.screen_job_id:
                    try:
                        audio_data = base64.b64decode(result["audio_base64"], validate=True)
                        if not audio_data.startswith(b"RIFF"):
                            raise ValueError("Audio WAV không hợp lệ")
                        self._set_status("processing", "ĐANG ĐỌC CHỮ ĐÃ BÔI ĐEN")
                        threading.Thread(target=self._play_screen_read_audio, args=(job_id, audio_data), daemon=True).start()
                    except (KeyError, ValueError, TypeError) as exc:
                        self.ui_queue.put(("screen_error", (job_id, f"KHÔNG ĐỌC ĐƯỢC ÂM THANH · {exc}")))
            elif command == "screen_read_done":
                job_id = payload
                if job_id == self.screen_job_id:
                    with self.state_lock:
                        self.screen_selecting = False
                        self.screen_processing = False
                    self._set_status("done", "ĐÃ ĐỌC XONG CHỮ ĐÃ CHỌN")
            elif command == "screen_error":
                job_id, message = payload
                if job_id == self.screen_job_id:
                    with self.state_lock:
                        self.screen_selecting = False
                        self.screen_processing = False
                    self._set_status("error", str(message))
                    self._play_sound("error")
            elif command == "clear_screen_overlay":
                self._clear_screen_translation()
            elif command == "dismiss_screen":
                self._dismiss_screen_ui()
            elif command == "status_visibility":
                self._apply_status_visibility()
        while True:
            try:
                latest = self.status_queue.get_nowait()
            except queue.Empty:
                break
        if latest and self.overlay_canvas is not None:
            state, message = latest
            color = colors.get(state, "#c9ff5d")
            self.overlay_canvas.itemconfigure("dot", fill=color)
            if self.overlay_status is not None:
                self.overlay_canvas.itemconfigure(self.overlay_status, fill=color, text=labels.get(state, labels["ready"]))
            if self.overlay_message is not None:
                self.overlay_canvas.itemconfigure(self.overlay_message, text=message)
        if self.overlay is not None and not self.stop_event.is_set():
            self.overlay.after(40, self._poll_overlay)

    def request_screen_translation(self) -> None:
        """Queue desktop selection without blocking the global keyboard hook."""
        with self.state_lock:
            if self.screen_selecting or self.screen_processing or self.recording or self.processing:
                return
            self.screen_selecting = True
            self.screen_action = "translate"
        self.ui_queue.put(("select_screen", None))

    def request_screen_read(self) -> None:
        """Read text already highlighted in the foreground app; never capture the screen."""
        logging.info("Selected-text read hotkey triggered")
        with self.state_lock:
            if self.screen_selecting or self.screen_processing or self.recording or self.processing:
                logging.info("Selected-text read ignored because another action is active")
                return
            self.screen_processing = True
            self.screen_action = "read"
            self.screen_job_id += 1
            job_id = self.screen_job_id
        target_window, target_control = self._focused_target()
        threading.Thread(
            target=self._read_selected_text,
            args=(target_window, target_control, job_id),
            daemon=True,
        ).start()

    def _capture_selected_text(self, target_window: int | None, target_control: int | None) -> str:
        """Copy only a mouse/keyboard selection, preserving plain-text clipboard content."""
        del target_window, target_control  # Keep the current browser selection and focus untouched.
        self._wait_for_modifiers_released()
        if modifiers_pressed():
            raise RuntimeError("Hãy thả phím tắt trước khi app sao chép đoạn chữ bôi đen.")
        original_clipboard = pyperclip.paste()
        marker = f"__SPEAKBRIDGE_NO_SELECTION_{time.time_ns()}__"
        try:
            pyperclip.copy(marker)
            keyboard.press_and_release("ctrl+c")
            time.sleep(0.3)
            selected = pyperclip.paste()
        finally:
            pyperclip.copy(original_clipboard)
        if selected == marker or not selected.strip():
            raise RuntimeError("Chưa lấy được chữ bôi đen. Hãy kéo chọn chữ có thể sao chép rồi bấm phím tắt.")
        if len(selected) > 1500:
            raise RuntimeError("Đoạn bôi đen quá dài; vui lòng chọn tối đa 1.500 ký tự.")
        return selected

    def _read_selected_text(self, target_window: int | None, target_control: int | None, job_id: int) -> None:
        try:
            self._set_status("processing", "ĐANG LẤY CHỮ ĐÃ BÔI ĐEN")
            selected = self._capture_selected_text(target_window, target_control)
            if job_id != self.screen_job_id:
                return
            self._set_status("processing", "ĐANG TẠO GIỌNG ĐỌC")
            if not self._api_ready() and not self._ensure_engine():
                raise RuntimeError("Engine chưa sẵn sàng")
            payload = {
                "text": selected,
                "source_language": self.settings["screen_read_source_language"],
                "target_language": self.settings["screen_read_target_language"],
                "read_mode": self.settings["screen_read_mode"],
                "voices": self.settings.get("screen_read_voices", DEFAULTS["screen_read_voices"]),
            }
            request = urllib.request.Request(
                f"{API_URL}/text/read",
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=180) as response:
                result = json.loads(response.read().decode("utf-8"))
            self.ui_queue.put(("screen_read_result", (job_id, result)))
        except urllib.error.HTTPError as exc:
            try:
                detail = json.loads(exc.read().decode("utf-8")).get("detail", str(exc))
            except Exception:
                detail = str(exc)
            self.ui_queue.put(("screen_error", (job_id, f"ĐỌC CHỮ LỖI · {detail}")))
        except Exception as exc:
            logging.exception("Selected text read failed")
            self.ui_queue.put(("screen_error", (job_id, f"ĐỌC CHỮ LỖI · {exc}")))

    def request_text_translation(self) -> None:
        """Translate selected text, or all text in the focused input when nothing is selected."""
        with self.state_lock:
            if self.recording or self.processing or self.screen_selecting or self.screen_processing:
                return
            self.processing = True
        target_window, target_control = self._focused_target()
        threading.Thread(
            target=self._translate_focused_text,
            args=(target_window, target_control),
            daemon=True,
        ).start()

    @staticmethod
    def _wait_for_modifiers_released(timeout: float = 2.0) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if not modifiers_pressed():
                return
            time.sleep(0.03)

    @staticmethod
    def _focus_target(target_window: int | None, target_control: int | None) -> None:
        if not target_window:
            return
        user32 = ctypes.windll.user32
        target_thread = user32.GetWindowThreadProcessId(target_window, None)
        current_thread = ctypes.windll.kernel32.GetCurrentThreadId()
        attached = bool(target_thread and target_thread != current_thread and user32.AttachThreadInput(current_thread, target_thread, True))
        try:
            user32.ShowWindow(target_window, 5)
            user32.BringWindowToTop(target_window)
            user32.SetForegroundWindow(target_window)
            if target_control:
                user32.SetFocus(target_control)
        finally:
            if attached:
                user32.AttachThreadInput(current_thread, target_thread, False)
        time.sleep(0.12)

    def _capture_focused_text(self, target_window: int | None, target_control: int | None) -> str:
        self._wait_for_modifiers_released()
        self._focus_target(target_window, target_control)
        original_clipboard = pyperclip.paste()
        marker = f"__SPEAKBRIDGE_EMPTY_{time.time_ns()}__"
        pyperclip.copy(marker)
        keyboard.press_and_release("ctrl+c")
        time.sleep(0.25)
        text = pyperclip.paste()
        if text == marker:
            keyboard.press_and_release("ctrl+a")
            time.sleep(0.12)
            keyboard.press_and_release("ctrl+c")
            time.sleep(0.25)
            text = pyperclip.paste()
        if text == marker or not text.strip():
            pyperclip.copy(original_clipboard)
            raise RuntimeError("Không lấy được chữ. Hãy đặt con trỏ trong ô chat hoặc bôi đen đoạn cần dịch.")
        if len(text) > 6000:
            pyperclip.copy(original_clipboard)
            raise RuntimeError("Đoạn chữ quá dài; giới hạn là 6.000 ký tự.")
        return text

    def _translate_focused_text(self, target_window: int | None, target_control: int | None) -> None:
        restart_engine = False
        try:
            self._set_status("processing", "ĐANG LẤY CHỮ TRONG Ô CHAT")
            source = self._capture_focused_text(target_window, target_control)
            target_language = str(self.settings.get("text_target_language", "en"))
            self._set_status("processing", f"ĐANG DỊCH CHỮ → {target_language.upper()}")
            if not self._ensure_engine():
                raise RuntimeError("Không khởi động được engine dịch")
            source_language = str(self.settings.get("text_source_language", "vi"))
            payload = {
                "text": source,
                "source_language": source_language,
                "target_language": target_language,
                "mode": str(self.settings.get("mode", "fast")),
            }
            request = urllib.request.Request(
                f"{API_URL}/text/translate",
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=180) as response:
                result = json.loads(response.read().decode("utf-8"))
            translated = str(result.get("text", "")).strip()
            if not translated:
                raise RuntimeError("Bản dịch trống")
            self._paste_text(translated, target_window, target_control)
            self._set_status("done", "ĐÃ DỊCH VÀ THAY CHỮ", notify=True)
            self._play_sound("done")
            self._notify(f"Đã dịch chữ: {source[:60]!r} -> {translated[:60]!r}")
        except urllib.error.HTTPError as exc:
            try:
                detail = json.loads(exc.read().decode("utf-8")).get("detail", str(exc))
            except Exception:
                detail = str(exc)
            self._set_status("error", "DỊCH CHỮ LỖI", notify=True)
            self._play_sound("error")
            self._notify(f"Dịch chữ lỗi: {detail}")
        except urllib.error.URLError as exc:
            restart_engine = True
            logging.exception("Typed text translation engine connection failed")
            self._set_status("error", "MẤT KẾT NỐI ENGINE", notify=True)
            self._play_sound("error")
            self._notify(f"Dịch chữ mất kết nối engine: {exc}")
        except Exception as exc:
            logging.exception("Typed text translation failed")
            self._set_status("error", "DỊCH CHỮ LỖI", notify=True)
            self._play_sound("error")
            self._notify(f"Dịch chữ lỗi: {exc}")
        finally:
            self.processing = False
            if restart_engine:
                threading.Thread(target=self._ensure_engine, daemon=True).start()
            else:
                time.sleep(0.8)
                self._set_status("ready", f"Dịch chữ · {self.settings['text_translate_hotkey']}")

    def _on_screen_exit(self) -> None:
        if self.screen_selecting or self.screen_processing or self.screen_translation_overlay is not None:
            self.ui_queue.put(("dismiss_screen", None))

    def clear_screen_translation(self, icon: Any = None, item: Any = None) -> None:
        del icon, item
        self.ui_queue.put(("dismiss_screen", None))

    def _apply_status_visibility(self) -> None:
        if self.overlay is None:
            return
        if bool(self.settings.get("show_status_overlay", True)):
            self.overlay.deiconify()
            self.overlay.lift()
        else:
            self.overlay.withdraw()
        if self.screen_translation_overlay is not None:
            opacity = max(0.2, min(1.0, float(self.settings.get("screen_overlay_opacity", 0.92))))
            try:
                self.screen_translation_overlay.attributes("-alpha", opacity)
            except tk.TclError:
                pass

    @staticmethod
    def _virtual_screen_bounds() -> tuple[int, int, int, int]:
        user32 = ctypes.windll.user32
        left = int(user32.GetSystemMetrics(76))
        top = int(user32.GetSystemMetrics(77))
        width = int(user32.GetSystemMetrics(78))
        height = int(user32.GetSystemMetrics(79))
        return left, top, max(1, width), max(1, height)

    @classmethod
    def _cursor_monitor_bounds(cls) -> tuple[int, int, int, int]:
        user32 = ctypes.windll.user32
        user32.GetCursorPos.argtypes = [ctypes.POINTER(_Point)]
        user32.GetCursorPos.restype = wintypes.BOOL
        point = _Point()
        if not user32.GetCursorPos(ctypes.byref(point)):
            return cls._virtual_screen_bounds()
        user32.MonitorFromPoint.argtypes = [_Point, wintypes.DWORD]
        user32.MonitorFromPoint.restype = ctypes.c_void_p
        monitor = user32.MonitorFromPoint(point, 2)  # MONITOR_DEFAULTTONEAREST
        user32.GetMonitorInfoW.argtypes = [ctypes.c_void_p, ctypes.POINTER(_MonitorInfo)]
        user32.GetMonitorInfoW.restype = wintypes.BOOL
        info = _MonitorInfo(cbSize=ctypes.sizeof(_MonitorInfo))
        if not monitor or not user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
            return cls._virtual_screen_bounds()
        rect = info.rcMonitor
        return rect.left, rect.top, max(1, rect.right - rect.left), max(1, rect.bottom - rect.top)

    def _clear_screen_translation(self) -> None:
        if self.screen_translation_overlay is not None:
            try:
                self.screen_translation_overlay.destroy()
            except tk.TclError:
                pass
        self.screen_translation_overlay = None
        self.screen_translation_labels = []
        self.screen_overlay_bbox = None

    def _clear_screen_translation_text(self) -> None:
        for label in self.screen_translation_labels:
            try:
                label.place_forget()
            except tk.TclError:
                pass

    def _dismiss_screen_ui(self) -> None:
        self.screen_job_id += 1
        if self.screen_action == "read":
            winsound.PlaySound(None, 0)
        if self.screen_selector is not None:
            try:
                self.screen_selector.grab_release()
                self.screen_selector.destroy()
            except tk.TclError:
                pass
        self.screen_selector = None
        self.screen_selection_image = None
        self._clear_screen_translation()
        self.screen_last_text = ""
        self.screen_empty_frames = 0
        with self.state_lock:
            self.screen_selecting = False
            self.screen_processing = False
        self._set_status("ready", f"Dịch vùng {self.settings['screen_hotkey']} · đọc chữ {self.settings['screen_read_hotkey']}")
        self.screen_action = "translate"

    def _cancel_screen_selection(self) -> None:
        self._dismiss_screen_ui()

    def _begin_screen_selection(self) -> None:
        if self.overlay is None:
            self._cancel_screen_selection()
            return
        self._clear_screen_translation()
        left, top, width, height = self._cursor_monitor_bounds()
        screenshot = ImageGrab.grab(bbox=(left, top, left + width, top + height), all_screens=True).convert("RGB")
        if screenshot.size != (width, height):
            logging.warning("Virtual screen %sx%s differs from screenshot %sx%s; resizing selector preview", width, height, *screenshot.size)
            screenshot = screenshot.resize((width, height), Image.Resampling.LANCZOS)
        selector = tk.Toplevel(self.overlay)
        self.screen_selector = selector
        selector.overrideredirect(True)
        selector.attributes("-topmost", True)
        selector.attributes("-alpha", 1.0)
        selector.configure(bg="#050806")
        selector.geometry(f"{width}x{height}{left:+d}{top:+d}")
        canvas = tk.Canvas(selector, bg="#050806", cursor="crosshair", highlightthickness=0)
        canvas.pack(fill="both", expand=True)
        self.screen_selection_image = ImageTk.PhotoImage(screenshot)
        canvas.create_image(0, 0, anchor="nw", image=self.screen_selection_image)
        canvas.create_rectangle(0, 0, width, height, fill="#050806", stipple="gray50", outline="")
        canvas.create_rectangle(max(0, width // 2 - 290), 8, min(width, width // 2 + 290), 58, fill="#050806", outline="#68f0b8", width=1)
        exit_shortcut = str(self.settings.get("screen_exit_hotkey", "esc")).upper()
        canvas.create_text(
            width // 2,
            33,
            text=f"SPEAKBRIDGE · KÉO CHỌN VÙNG CẦN DỊCH · {exit_shortcut} ĐỂ HỦY",
            fill="#c9ff5d",
            font=("Segoe UI Semibold", 12),
        )
        drag: dict[str, int | None] = {"x": None, "y": None, "rect": None}

        def pointer_down(event: tk.Event) -> None:
            logging.info("Screen selection pointer down at %s,%s", event.x, event.y)
            drag["x"], drag["y"] = int(event.x), int(event.y)
            if drag["rect"] is not None:
                canvas.delete(int(drag["rect"]))
            drag["rect"] = canvas.create_rectangle(event.x, event.y, event.x, event.y, outline="#c9ff5d", fill="#c9ff5d", stipple="gray75", width=3)

        def pointer_move(event: tk.Event) -> None:
            if drag["x"] is not None and drag["y"] is not None and drag["rect"] is not None:
                canvas.coords(int(drag["rect"]), int(drag["x"]), int(drag["y"]), event.x, event.y)

        def pointer_up(event: tk.Event) -> None:
            if drag["x"] is None or drag["y"] is None:
                return
            x1, x2 = sorted((int(drag["x"]), int(event.x)))
            y1, y2 = sorted((int(drag["y"]), int(event.y)))
            if x2 - x1 < 12 or y2 - y1 < 12:
                self._cancel_screen_selection()
                return
            bbox = (left + x1, top + y1, left + x2, top + y2)
            logging.info("Screen selection completed: %s", bbox)
            try:
                selector.grab_release()
                selector.destroy()
            except tk.TclError:
                pass
            self.screen_selector = None
            self.screen_selection_image = None
            with self.state_lock:
                self.screen_processing = True
                self.screen_job_id += 1
                job_id = self.screen_job_id
            self.screen_last_text = ""
            self.screen_empty_frames = 0
            self._set_status("processing", "ĐANG OCR VÀ DỊCH VÙNG MÀN HÌNH")
            self._play_sound("processing")
            if self.overlay is not None:
                self.overlay.after(120, lambda: self._start_screen_capture(bbox, job_id))

        canvas.bind("<ButtonPress-1>", pointer_down)
        canvas.bind("<B1-Motion>", pointer_move)
        canvas.bind("<ButtonRelease-1>", pointer_up)
        selector.bind("<Escape>", lambda _event: self._cancel_screen_selection())
        selector.update_idletasks()
        selector.deiconify()
        selector.lift()
        selector.grab_set()
        selector.focus_force()
        canvas.focus_set()
        logging.info("Screen selector visible at %s,%s size %sx%s", left, top, width, height)
        self._set_status("selecting", f"KÉO CHỌN VÙNG CẦN DỊCH · {exit_shortcut} để hủy")

    def _start_screen_capture(self, bbox: tuple[int, int, int, int], job_id: int) -> None:
        if job_id != self.screen_job_id or not self.screen_processing:
            return
        threading.Thread(
            target=self._process_screen_region,
            args=(bbox, job_id, self.screen_last_text),
            daemon=True,
        ).start()

    def _play_screen_read_audio(self, job_id: int, audio_data: bytes) -> None:
        try:
            if job_id == self.screen_job_id:
                play_wav(audio_data, str(self.settings.get("screen_read_output_device", "__default__")),
                         cancelled=lambda: job_id != self.screen_job_id or self.stop_event.is_set())
            self.ui_queue.put(("screen_read_done", job_id))
        except Exception as exc:
            logging.exception("Could not play selected-text speech")
            self.ui_queue.put(("screen_error", (job_id, f"PHÁT GIỌNG ĐỌC LỖI · {exc}")))

    def _schedule_screen_capture(self, bbox: tuple[int, int, int, int], job_id: int) -> None:
        if self.overlay is None or job_id != self.screen_job_id or not self.screen_processing:
            return
        if not bool(self.settings.get("screen_continuous", True)):
            with self.state_lock:
                self.screen_processing = False
            return
        refresh_seconds = max(0.25, min(10.0, float(self.settings.get("screen_refresh_seconds", 1.0))))
        self.overlay.after(round(refresh_seconds * 1000), lambda: self._start_screen_capture(bbox, job_id))

    def _process_screen_region(self, bbox: tuple[int, int, int, int], job_id: int, previous_text: str) -> None:
        try:
            if not self._api_ready() and not self._ensure_engine():
                raise RuntimeError("Engine dịch chưa sẵn sàng")
            image = ImageGrab.grab(bbox=bbox, all_screens=True)
            encoded = BytesIO()
            image.convert("RGB").save(encoded, format="JPEG", quality=90)
            payload = {
                "image_base64": base64.b64encode(encoded.getvalue()).decode("ascii"),
                "source_language": self.settings["screen_source_language"],
                "target_language": self.settings["screen_target_language"],
                "processor": self.settings["screen_processor"],
                "mode": self.settings["mode"],
                "previous_text": previous_text,
            }
            request = urllib.request.Request(
                f"{API_URL}/ocr/translate",
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=180) as response:
                result = json.loads(response.read().decode("utf-8"))
            self.ui_queue.put(("screen_result", (job_id, bbox, result)))
        except urllib.error.HTTPError as exc:
            try:
                detail = json.loads(exc.read().decode("utf-8")).get("detail", str(exc))
            except Exception:
                detail = str(exc)
            self.ui_queue.put(("screen_error", (job_id, f"DỊCH MÀN HÌNH LỖI · {detail}")))
        except Exception as exc:
            logging.exception("Desktop screen translation failed")
            self.ui_queue.put(("screen_error", (job_id, f"DỊCH MÀN HÌNH LỖI · {exc}")))

    def _handle_screen_result(
        self,
        bbox: tuple[int, int, int, int],
        job_id: int,
        result: dict[str, Any],
    ) -> None:
        source = " ".join(str(result.get("source", "")).split())
        self.screen_selecting = False
        if not source:
            self.screen_empty_frames += 1
            if self.screen_empty_frames >= 2:
                self._clear_screen_translation_text()
                self.screen_last_text = ""
            if not bool(self.settings.get("screen_continuous", True)):
                self._set_status("error", "KHÔNG TÌM THẤY CHỮ TRONG VÙNG ĐÃ CHỌN")
        else:
            self.screen_empty_frames = 0
            if not bool(result.get("unchanged")) and result.get("regions"):
                self.screen_last_text = source
                self._show_screen_translation(bbox, result)
        self._schedule_screen_capture(bbox, job_id)

    @staticmethod
    def _make_click_through(window: tk.Toplevel) -> None:
        window.update_idletasks()
        user32 = ctypes.windll.user32
        hwnd = int(window.winfo_id())
        parent = int(user32.GetParent(hwnd))
        if parent:
            hwnd = parent
        GWL_EXSTYLE = -20
        WS_EX_TOOLWINDOW = 0x00000080
        WS_EX_TRANSPARENT = 0x00000020
        WS_EX_NOACTIVATE = 0x08000000
        style = int(user32.GetWindowLongW(hwnd, GWL_EXSTYLE))
        user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style | WS_EX_TOOLWINDOW | WS_EX_TRANSPARENT | WS_EX_NOACTIVATE)

    @staticmethod
    def _exclude_window_from_capture(window: tk.Misc) -> None:
        """Keep an overlay visible locally while omitting it from screenshots."""
        window.update_idletasks()
        user32 = ctypes.windll.user32
        hwnd = int(window.winfo_id())
        parent = int(user32.GetParent(hwnd))
        if parent:
            hwnd = parent
        user32.SetWindowDisplayAffinity.argtypes = [wintypes.HWND, wintypes.DWORD]
        user32.SetWindowDisplayAffinity.restype = wintypes.BOOL
        WDA_EXCLUDEFROMCAPTURE = 0x00000011
        if not user32.SetWindowDisplayAffinity(hwnd, WDA_EXCLUDEFROMCAPTURE):
            logging.warning("Windows could not exclude overlay hwnd=%s from screen capture", hwnd)

    def _show_screen_translation(self, bbox: tuple[int, int, int, int], result: dict[str, Any]) -> None:
        if self.overlay is None:
            return
        left, top, right, bottom = bbox
        width, height = max(1, right - left), max(1, bottom - top)
        overlay_background = str(self.settings.get("screen_background_color", "#040806"))
        overlay_foreground = str(self.settings.get("screen_text_color", "#ffffff"))
        window = self.screen_translation_overlay
        if window is None or self.screen_overlay_bbox != bbox:
            self._clear_screen_translation()
            window = tk.Toplevel(self.overlay)
            self.screen_translation_overlay = window
            self.screen_overlay_bbox = bbox
            window.overrideredirect(True)
            window.attributes("-topmost", True)
            window.configure(bg=overlay_background)
            window.geometry(f"{width}x{height}{left:+d}{top:+d}")
            opacity = max(0.2, min(1.0, float(self.settings.get("screen_overlay_opacity", 0.92))))
            window.attributes("-alpha", opacity)
            self._make_click_through(window)
            self._exclude_window_from_capture(window)

        window.configure(bg=overlay_background)

        visible_labels = 0
        for region in result.get("regions", []):
            translation = " ".join(str(region.get("translation", "")).split())
            if not translation:
                continue
            x = max(0, min(width - 1, round(float(region.get("x", 0)) * width)))
            y = max(0, min(height - 1, round(float(region.get("y", 0)) * height)))
            box_width = max(4, min(width - x, round(float(region.get("width", 0)) * width)))
            box_height = max(4, min(height - y, round(float(region.get("height", 0)) * height)))
            font_size = max(8, min(48, int(self.settings.get("screen_font_size", 14))))
            font = tkfont.Font(family="Segoe UI", size=-font_size, weight="bold")
            expanded_width = max(box_width, font.measure(translation) + 6)
            expanded_height = max(box_height, int(font.metrics("linespace")) + 2)
            expanded_width = max(4, min(width - x, expanded_width))
            expanded_height = max(4, min(height - y, expanded_height))
            if visible_labels < len(self.screen_translation_labels):
                label = self.screen_translation_labels[visible_labels]
                label.configure(text=translation, font=font, bg=overlay_background, fg=overlay_foreground)
            else:
                label = tk.Label(
                    window,
                    text=translation,
                    bg=overlay_background,
                    fg=overlay_foreground,
                    font=font,
                    anchor="w",
                    padx=2,
                    pady=0,
                )
                self.screen_translation_labels.append(label)
            label.place(x=x, y=y, width=expanded_width, height=expanded_height)
            visible_labels += 1

        for label in self.screen_translation_labels[visible_labels:]:
            label.place_forget()

        self.screen_selecting = False
        continuous = bool(self.settings.get("screen_continuous", True))
        state_text = "ĐANG DỊCH LIÊN TỤC" if continuous else "ĐÃ DỊCH VÙNG"
        self._set_status("done", f"{state_text} · {result.get('processor', 'cpu').upper()}")
        if not continuous:
            self._play_sound("done")

    def _find_microphone(self) -> dict[str, Any]:
        assert self.audio is not None
        requested = str(self.settings.get("microphone", "__default__"))
        wasapi_index: int | None = None
        for index in range(self.audio.get_host_api_count()):
            host = self.audio.get_host_api_info_by_index(index)
            if "WASAPI" in str(host["name"]):
                wasapi_index = int(host["index"])
                if requested == "__default__":
                    return self.audio.get_device_info_by_index(int(host["defaultInputDevice"]))
                break
        if requested == "__default__":
            return self.audio.get_default_input_device_info()
        candidates: list[dict[str, Any]] = []
        for index in range(self.audio.get_device_count()):
            device = self.audio.get_device_info_by_index(index)
            if device.get("maxInputChannels", 0) <= 0 or device.get("isLoopbackDevice", False):
                continue
            if requested.casefold() == str(device["name"]).casefold():
                candidates.append(device)
        if candidates:
            return next(
                (device for device in candidates if int(device["hostApi"]) == wasapi_index),
                candidates[0],
            )
        raise RuntimeError(f"Không tìm thấy microphone đã chọn: {requested}")

    def start_recording(self) -> None:
        # Keyboard hooks must return immediately. Opening PyAudio or checking the
        # engine in this callback can stall delivery of Ctrl/Shift to Windows.
        with self.state_lock:
            if self.hotkey_active or self.starting or self.stopping or self.recording or self.processing:
                return
            self.hotkey_active = True
            self.starting = True
        threading.Thread(target=self._start_recording, daemon=True).start()

    def _start_recording(self) -> None:
        if not self._api_ready():
            self._set_status("processing", "ENGINE ĐANG TẮT · tự khởi động lại")
            threading.Thread(target=self._ensure_engine, daemon=True).start()
            with self.state_lock:
                self.starting = False
            return
        try:
            self.target_window, self.target_control = self._focused_target()
            with AUDIO_API_LOCK:
                self.audio = pyaudio.PyAudio()
            device = self._find_microphone()
            self.sample_rate = int(device.get("defaultSampleRate", 48_000))
            self.channels = max(1, min(2, int(device.get("maxInputChannels", 1))))
            self.stream = self.audio.open(
                format=pyaudio.paInt16,
                channels=self.channels,
                rate=self.sample_rate,
                input=True,
                input_device_index=int(device["index"]),
                frames_per_buffer=1024,
            )
            self.frames = []
            with self.state_lock:
                self.starting = False
                if not self.hotkey_active or self.stop_event.is_set():
                    self._close_audio()
                    return
                self.recording = True
            self.record_thread = threading.Thread(target=self._record_loop, daemon=True)
            self.record_thread.start()
            logging.info("Recording device: %s (%s Hz, %s channel(s))", device.get("name"), self.sample_rate, self.channels)
            self._set_status("recording", "ĐANG NGHE · thả phím để dịch", notify=True)
            self._play_sound("start")
        except Exception as exc:
            logging.exception("Cannot start microphone")
            self._close_audio()
            with self.state_lock:
                self.starting = False
                self.hotkey_active = False
            self._set_status("error", "Không mở được microphone", notify=True)
            self._notify(f"Không mở được microphone: {exc}")

    def _record_loop(self) -> None:
        while self.recording and self.stream is not None:
            try:
                self.frames.append(self.stream.read(1024, exception_on_overflow=False))
            except Exception:
                logging.exception("Microphone read failed")
                break

    def stop_recording(self) -> None:
        # Mark the key as released synchronously, then perform audio shutdown and
        # sample analysis away from the global keyboard hook thread.
        with self.state_lock:
            self.hotkey_active = False
            if not self.recording or self.stopping:
                return
            self.recording = False
            self.stopping = True
        threading.Thread(target=self._finish_recording, daemon=True).start()

    def _finish_recording(self) -> None:
        self._set_status("processing", "ĐANG NHẬN DẠNG VÀ DỊCH", notify=True)
        self._play_sound("processing")
        if self.record_thread:
            self.record_thread.join(timeout=1)
        audio_bytes = b"".join(self.frames)
        logging.info(
            "Recorded %.2f seconds (%s bytes)",
            len(audio_bytes) / max(1, self.sample_rate * self.channels * 2),
            len(audio_bytes),
        )
        samples = array.array("h")
        samples.frombytes(audio_bytes)
        if samples:
            sums = [0.0] * self.channels
            peaks = [0] * self.channels
            counts = [0] * self.channels
            for index, sample in enumerate(samples):
                channel = index % self.channels
                sums[channel] += float(sample) * float(sample)
                peaks[channel] = max(peaks[channel], abs(sample))
                counts[channel] += 1
            rms = [round(math.sqrt(sums[i] / max(1, counts[i])) / 32768.0, 5) for i in range(self.channels)]
            peak = [round(peaks[i] / 32768.0, 5) for i in range(self.channels)]
            logging.info("Audio levels RMS=%s peak=%s", rms, peak)
        self._close_audio()
        if len(audio_bytes) < self.sample_rate * self.channels // 2:
            with self.state_lock:
                self.stopping = False
            self._set_status("error", "Đoạn nói quá ngắn", notify=True)
            self._notify("Đoạn nói quá ngắn")
            return
        self.processing = True
        with self.state_lock:
            self.stopping = False
        threading.Thread(
            target=self._process_recording, args=(audio_bytes,), daemon=True
        ).start()

    def _close_audio(self) -> None:
        if self.stream is not None:
            try:
                self.stream.stop_stream()
                self.stream.close()
            except Exception:
                pass
        if self.audio is not None:
            try:
                with AUDIO_API_LOCK:
                    self.audio.terminate()
            except Exception:
                pass
        self.stream = None
        self.audio = None

    def _process_recording(self, audio_bytes: bytes) -> None:
        restart_engine = False
        try:
            logging.info("Submitting %.2f seconds to %s/dictate", len(audio_bytes) / max(1, self.sample_rate * self.channels * 2), API_URL)
            payload = {
                "pcm16_base64": base64.b64encode(audio_bytes).decode("ascii"),
                "sample_rate": self.sample_rate,
                "channels": self.channels,
                "mode": self.settings["mode"],
                "source_language": self.settings["source_language"],
                "target_language": self.settings["target_language"],
                "translate": bool(self.settings["translate"]),
            }
            request = urllib.request.Request(
                f"{API_URL}/dictate",
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=180) as response:
                result = json.loads(response.read().decode("utf-8"))
            logging.info(
                "Dictation response: source=%s target=%s transcript=%r text=%r",
                result.get("source_language"),
                result.get("target_language"),
                str(result.get("transcript", ""))[:200],
                str(result.get("text", ""))[:200],
            )
            text = str(result.get("text", "")).strip()
            if not text:
                raise RuntimeError("Không nhận ra nội dung")
            self._paste_text(text, self.target_window, self.target_control)
            self._set_status("done", "ĐÃ NHẬP XONG", notify=True)
            self._play_sound("done")
            self._notify(f"Đã nhập: {text[:80]}")
        except urllib.error.HTTPError as exc:
            try:
                detail = json.loads(exc.read().decode("utf-8")).get("detail", str(exc))
            except Exception:
                detail = str(exc)
            self._set_status("error", "NHẬN DẠNG LỖI", notify=True)
            self._play_sound("error")
            self._notify(f"Nhận dạng lỗi: {detail}")
        except urllib.error.URLError as exc:
            restart_engine = True
            logging.exception("Voice typing engine connection failed")
            self._set_status("error", "MẤT KẾT NỐI ENGINE · đang khởi động lại")
            self._play_sound("error")
            self._notify(f"Voice typing mất kết nối engine: {exc}")
        except Exception as exc:
            logging.exception("Voice typing failed")
            self._set_status("error", "VOICE TYPING LỖI", notify=True)
            self._play_sound("error")
            self._notify(f"Voice typing lỗi: {exc}")
        finally:
            self.processing = False
            if restart_engine:
                threading.Thread(target=self._ensure_engine, daemon=True).start()
            else:
                time.sleep(0.8)
                self._set_status("ready", f"Sẵn sàng · {self.settings['hotkey']}")

    @staticmethod
    def _focused_target() -> tuple[int | None, int | None]:
        user32 = ctypes.windll.user32
        foreground = int(user32.GetForegroundWindow())
        if not foreground:
            return None, None
        process_id = wintypes.DWORD()
        thread_id = user32.GetWindowThreadProcessId(foreground, ctypes.byref(process_id))
        info = _GuiThreadInfo(cbSize=ctypes.sizeof(_GuiThreadInfo))
        focus = int(info.hwndFocus) if user32.GetGUIThreadInfo(thread_id, ctypes.byref(info)) and info.hwndFocus else None
        return foreground, focus

    @staticmethod
    def _paste_text(text: str, target_window: int | None, target_control: int | None = None) -> None:
        # Keep the generated text in the clipboard. This provides a reliable
        # manual Ctrl+V fallback when a protected/elevated application rejects
        # injected input.
        pyperclip.copy(text)
        logging.info("Clipboard updated with %s characters", len(text))
        user32 = ctypes.windll.user32
        if target_window:
            target_thread = user32.GetWindowThreadProcessId(target_window, None)
            current_thread = ctypes.windll.kernel32.GetCurrentThreadId()
            attached = bool(target_thread and target_thread != current_thread and user32.AttachThreadInput(current_thread, target_thread, True))
            try:
                user32.ShowWindow(target_window, 5)
                user32.BringWindowToTop(target_window)
                user32.SetForegroundWindow(target_window)
                if target_control:
                    user32.SetFocus(target_control)
            finally:
                if attached:
                    user32.AttachThreadInput(current_thread, target_thread, False)
            time.sleep(0.18)

        class_name = ctypes.create_unicode_buffer(256)
        if target_control:
            user32.GetClassNameW(target_control, class_name, len(class_name))
        if target_control and "edit" in class_name.value.casefold():
            user32.SendMessageW(target_control, 0x0302, 0, 0)  # WM_PASTE
            logging.info("Text injection: WM_PASTE to %s", class_name.value)
        else:
            user32.keybd_event(0x11, 0, 0, 0)  # Ctrl down
            user32.keybd_event(0x56, 0, 0, 0)  # V down
            user32.keybd_event(0x56, 0, 2, 0)  # V up
            user32.keybd_event(0x11, 0, 2, 0)  # Ctrl up
            logging.info("Text injection: Win32 Ctrl+V to %s", class_name.value or "focused window")
        time.sleep(0.65)

    @staticmethod
    def _icon_image(color: str = "#c9ff5d") -> Image.Image:
        image = Image.new("RGB", (64, 64), "#10150f")
        draw = ImageDraw.Draw(image)
        draw.ellipse((8, 8, 56, 56), fill=color)
        try:
            font = ImageFont.truetype("C:/Windows/Fonts/arialbd.ttf", 42)
        except OSError:
            font = ImageFont.load_default(size=42)
        draw.text((32, 31), "S", anchor="mm", font=font, fill="#10150f")
        return image

    @staticmethod
    def _show_tray_icon(icon: pystray.Icon) -> None:
        try:
            icon.visible = True
            logging.info("SpeakBridge tray icon visible")
        except Exception:
            logging.exception("SpeakBridge tray icon could not become visible")

    def quit(self, icon: pystray.Icon | None = None, item: Any = None) -> None:
        del item
        self.stop_event.set()
        if self.native_hotkeys is not None:
            self.native_hotkeys.stop()
        self.recording = False
        self._close_audio()
        keyboard.unhook_all()
        if icon:
            icon.stop()
        if self.overlay is not None:
            try:
                self._clear_screen_translation()
                if self.screen_selector is not None:
                    self.screen_selector.destroy()
                self.overlay.after(0, self.overlay.destroy)
            except Exception:
                pass

    def run(self) -> None:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
        kernel32.CreateMutexW.restype = wintypes.HANDLE
        mutex_name = "Local\\SpeakBridge.Hotkeys." + hashlib.sha256(str(PROJECT_ROOT).lower().encode()).hexdigest()[:16]
        self._instance_mutex = kernel32.CreateMutexW(None, False, mutex_name)
        if not self._instance_mutex:
            raise ctypes.WinError(ctypes.get_last_error())
        if ctypes.get_last_error() == 183:
            logging.info("SpeakBridge helper already running; ignoring duplicate launch")
            kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
            kernel32.CloseHandle(self._instance_mutex)
            return
        try:
            # Per-monitor DPI awareness keeps Tk selection coordinates aligned
            # with ImageGrab pixels on mixed-scale multi-monitor desktops.
            ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        except Exception:
            try:
                ctypes.windll.shcore.SetProcessDpiAwareness(2)
            except Exception:
                pass
        (RUN_DIR / "hotkey.pid").write_text(str(os.getpid()), encoding="ascii")
        self._register_hotkey()
        threading.Thread(target=self._watch_settings, daemon=True).start()
        menu = pystray.Menu(
            pystray.MenuItem("Mở SpeakBridge", lambda: webbrowser.open("http://localhost:3000/")),
            pystray.MenuItem("Dịch chữ trong ô chat", lambda: self.request_text_translation()),
            pystray.MenuItem("Dịch vùng màn hình", lambda: self.request_screen_translation()),
            pystray.MenuItem("Đọc chữ đã bôi đen", lambda: self.request_screen_read()),
            pystray.MenuItem("Xóa lớp dịch màn hình", self.clear_screen_translation),
            pystray.MenuItem("Thoát Voice Typing", self.quit),
        )
        self.icon = pystray.Icon(
            "SpeakBridgeVoiceTyping", self._icon_image(), f"SpeakBridge · {self.settings['screen_read_hotkey']} đọc chữ", menu
        )
        self._notify(f"Giữ {self.settings['hotkey']} để nói · {self.settings['text_translate_hotkey']} dịch chữ · {self.settings['screen_hotkey']} dịch vùng")
        self._set_status("ready", f"Nói {self.settings['hotkey']} · dịch chữ {self.settings['text_translate_hotkey']}")
        # Tk owns the main loop; pystray's documented integration is run_detached.
        self.icon.run_detached(setup=self._show_tray_icon)
        self._create_overlay()
        threading.Thread(target=self._ensure_engine, daemon=True).start()
        assert self.overlay is not None
        self.overlay.mainloop()


if __name__ == "__main__":
    try:
        VoiceTypingHelper().run()
    except Exception:
        logging.exception("SpeakBridge helper startup failed")
        raise
