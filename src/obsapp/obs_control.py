"""OBS Studio process lifecycle and websocket control."""

import json
import logging
import os
import subprocess
import sys
import time
from pathlib import Path

import obsws_python as obsws

# obsws_python logs every error before raising it, which duplicates information
# already present in the raised exception.  Silence it globally.
logging.getLogger("obsws_python").setLevel(logging.CRITICAL)

from .os_specifics import (
    _enum_monitors_win32, _enum_mics_win32, _enum_webcams_win32,
    _enum_monitors_linux, _enum_mics_linux,
    _enum_monitors_darwin, _enum_mics_darwin,
)

# Platform-specific source types and the property name that lists available devices.
_SOURCE_TYPES = {
    "win32": {
        "monitor": ("monitor_capture", "monitor_id"),
        "mic": ("wasapi_input_capture", "device_id"),
        "webcam": ("dshow_input", "video_device_id"),
    },
    "linux": {
        "monitor": ("xshm_input", "screen"),
        "mic": ("pulse_input_capture", "device_id"),
        "webcam": ("v4l2_input", "device_id"),
    },
    "darwin": {
        "monitor": ("display_capture", "display"),
        "mic": ("coreaudio_input_capture", "device_id"),
        "webcam": ("av_capture_input", "device"),
    },
}

_SCENE_NAME = "OBSapp_Recording"
_WS_PORT = 4455


class OBSController:
    def __init__(self, obsappdir: Path):
        self.obsappdir = obsappdir
        self.obs_dir = obsappdir  # kept for callers; obsappdir IS the obs dir
        self._obs_exe: str | None = None
        self._process: subprocess.Popen | None = None
        self.ws: obsws.ReqClient | None = None
        self._platform = "linux" if sys.platform.startswith("linux") else sys.platform

    # ── public helpers ────────────────────────────────────────────────

    @property
    def is_running(self) -> bool:
        return self.ws is not None

    # ── OBS lifecycle ─────────────────────────────────────────────────

    def start(self) -> None:
        """Start OBS (if needed) and connect the websocket."""
        if self.ws is not None:
            return
        obs_exe = self._find_obs_executable()
        self._ensure_obs_config()
        self._process = subprocess.Popen(
            [obs_exe, "--minimize-to-tray",
             "--collection", "OBSapp", "--profile", "OBSapp"],
            cwd=str(Path(obs_exe).parent),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        for _ in range(30):
            if self._process.poll() is not None:
                raise ConnectionError(
                    f"OBS process exited unexpectedly (code {self._process.returncode})"
                )
            try:
                self.ws = obsws.ReqClient(
                    host="localhost", port=_WS_PORT, password="", timeout=3,
                )
                return
            except Exception:
                time.sleep(1)
        raise ConnectionError("Could not connect to OBS websocket after 30 s")

    def stop(self) -> None:
        """Shut down OBS cleanly, falling back to terminate() if needed."""
        # Close the websocket first.
        if self.ws is not None:
            try:
                self.ws.disconnect()
            except Exception:
                pass
            self.ws = None

        if self._process is None:
            return

        # Ask OBS to exit gracefully via WM_CLOSE so it writes its clean-exit
        # flag and doesn't show the crash-recovery dialog on next launch.
        if self._platform == "win32":
            self._close_windows_gracefully()
        else:
            self._process.terminate()

        try:
            self._process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self._process.kill()
            self._process.wait()
        self._process = None

    def _close_windows_gracefully(self) -> None:
        """Send WM_CLOSE to the main OBS window to trigger a clean shutdown.

        Only the primary OBS window (title starts with "OBS") is targeted.
        Sending WM_CLOSE to auxiliary windows (DirectShow, IME, tray helpers,
        etc.) can interrupt OBS's shutdown sequence before it removes its
        sentinel file, which causes the crash-recovery dialog on next launch.
        """
        import ctypes
        import ctypes.wintypes as wt

        WM_CLOSE = 0x0010
        WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)
        GetWindowThreadProcessId = ctypes.windll.user32.GetWindowThreadProcessId
        GetWindowTextW = ctypes.windll.user32.GetWindowTextW
        PostMessage = ctypes.windll.user32.PostMessageW

        pid = self._process.pid
        main_windows = []

        def callback(hwnd, _):
            proc_id = wt.DWORD()
            GetWindowThreadProcessId(hwnd, ctypes.byref(proc_id))
            if proc_id.value == pid:
                buf = ctypes.create_unicode_buffer(256)
                GetWindowTextW(hwnd, buf, 256)
                if buf.value.startswith("OBS"):
                    main_windows.append(hwnd)
            return True

        ctypes.windll.user32.EnumWindows(WNDENUMPROC(callback), 0)
        for hwnd in main_windows:
            PostMessage(hwnd, WM_CLOSE, 0, 0)

    # ── device enumeration (native OS, no OBS involvement) ───────────

    def get_monitors(self) -> list[tuple[str, str]]:
        """Return [(display_name, value), ...] using native OS APIs."""
        try:
            if self._platform == "win32":
                return _enum_monitors_win32()
            if self._platform == "darwin":
                return _enum_monitors_darwin()
            return _enum_monitors_linux()
        except Exception as exc:
            print(f"Monitor enumeration failed: {exc}")
            return []

    def get_microphones(self) -> list[tuple[str, str]]:
        """Return [(friendly_name, device_id), ...] using native OS APIs."""
        try:
            if self._platform == "win32":
                return _enum_mics_win32()
            if self._platform == "darwin":
                return _enum_mics_darwin()
            return _enum_mics_linux()
        except Exception as exc:
            print(f"Microphone enumeration failed: {exc}")
            return []

    def get_webcams(self) -> list[tuple[str, str]]:
        """Return [(friendly_name, device_id), ...] using native OS APIs."""
        try:
            if self._platform == "win32":
                return _enum_webcams_win32()
            # Linux and macOS webcam enumeration not yet implemented.
            return []
        except Exception as exc:
            print(f"Webcam enumeration failed: {exc}")
            return []

    # ── recording control ─────────────────────────────────────────────

    def setup_recording(
        self,
        monitor_value: str,
        mic_value: str | None,
        webcam_value: str | None,
        output_dir: str,
    ) -> None:
        """Configure OBS scene and sources for the upcoming recording."""
        assert self.ws is not None
        # Set output directory.
        self.ws.set_profile_parameter(
            category="SimpleOutput",
            name="FilePath",
            value=output_dir,
        )
        # Ensure our scene exists and is active.
        self._create_scene_if_missing(_SCENE_NAME)
        self.ws.set_current_program_scene(_SCENE_NAME)
        # Remove old sources so we start clean.
        removed_any = False
        for name in ("OBSapp_Monitor", "OBSapp_Mic", "OBSapp_Webcam"):
            try:
                self.ws.remove_input(name)
                removed_any = True
            except Exception:
                pass
        # OBS processes source removal asynchronously.  If any source existed
        # and was just removed, wait briefly so OBS fully disposes of the
        # capture device before we try to re-create a source with the same name.
        # Without this delay, create_input can race and return code 601
        # ("source already exists") even though the remove succeeded.
        if removed_any:
            time.sleep(0.5)
        # Add monitor capture.
        types = _SOURCE_TYPES[self._platform]
        mon_kind, mon_prop = types["monitor"]
        self.ws.create_input(
            _SCENE_NAME, "OBSapp_Monitor", mon_kind,
            {mon_prop: monitor_value}, True,
        )
        # Add microphone (if selected).
        if mic_value:
            mic_kind, mic_prop = types["mic"]
            self.ws.create_input(
                _SCENE_NAME, "OBSapp_Mic", mic_kind,
                {mic_prop: mic_value}, True,
            )
        # Add webcam (if selected).
        if webcam_value:
            cam_kind, cam_prop = types["webcam"]
            self.ws.create_input(
                _SCENE_NAME, "OBSapp_Webcam", cam_kind,
                {cam_prop: webcam_value}, True,
            )
        # Give OBS a moment to open the capture devices before recording starts.
        # Without this, the monitor source may produce a black frame and webcam
        # hardware may not finish initialising in time.
        time.sleep(2)

    def start_recording(self) -> None:
        assert self.ws is not None
        self.ws.start_record()

    def stop_recording(self) -> str:
        """Stop recording.  Returns the path of the recorded file."""
        assert self.ws is not None
        resp = self.ws.stop_record()
        return resp.output_path

    def pause_recording(self) -> None:
        assert self.ws is not None
        self.ws.pause_record()

    def resume_recording(self) -> None:
        assert self.ws is not None
        self.ws.resume_record()

    # ── private helpers ───────────────────────────────────────────────

    def _find_obs_executable(self) -> str:
        if self._obs_exe is not None:
            return self._obs_exe
        if self._platform == "win32":
            progfiles = os.environ.get("ProgramFiles", r"C:\Program Files")
            system = Path(progfiles) / "obs-studio" / "bin" / "64bit" / "obs64.exe"
            if system.exists():
                self._obs_exe = str(system)
                return self._obs_exe
            raise FileNotFoundError("OBS Studio not found")
        if self._platform == "darwin":
            app = Path("/Applications/OBS.app/Contents/MacOS/OBS")
            if app.exists():
                self._obs_exe = str(app)
                return self._obs_exe
            raise FileNotFoundError("OBS Studio not found")
        # linux – assume 'obs' is in PATH
        self._obs_exe = "obs"
        return self._obs_exe

    def _obs_config_path(self) -> Path:
        """Standard per-user OBS config directory (no --portable flag used)."""
        if self._platform == "win32":
            appdata = os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming"))
            return Path(appdata) / "obs-studio"
        elif self._platform == "darwin":
            return Path.home() / "Library" / "Application Support" / "obs-studio"
        else:
            return Path.home() / ".config" / "obs-studio"

    def _ensure_obs_config(self) -> None:
        """Create/update OBS config files before launching OBS."""
        cfg = self._obs_config_path()

        # ── websocket: enabled, no authentication ──
        # Always overwrite these fields so a pre-existing user config with
        # server_enabled=false or a password does not prevent connection.
        ws_dir = cfg / "plugin_config" / "obs-websocket"
        ws_dir.mkdir(parents=True, exist_ok=True)
        ws_cfg = ws_dir / "config.json"
        existing = {}
        if ws_cfg.exists():
            try:
                existing = json.loads(ws_cfg.read_text())
            except Exception:
                pass
        existing.update({
            "server_enabled": True,
            "server_port": _WS_PORT,
            "server_password": "",
            "auth_required": False,
        })
        ws_cfg.write_text(json.dumps(existing, indent=2))

        # ── profile: low-CPU recording preset ──
        prof = cfg / "basic" / "profiles" / "OBSapp"
        prof.mkdir(parents=True, exist_ok=True)
        ini = prof / "basic.ini"
        if not ini.exists():
            ini.write_text(
                "[General]\n"
                "Name=OBSapp\n"
                "\n"
                "[Video]\n"
                "FPSType=2\n"
                "FPSNum=10\n"
                "FPSDen=1\n"
                "\n"
                "[Output]\n"
                "Mode=Simple\n"
                "\n"
                "[SimpleOutput]\n"
                "RecQuality=Small\n"
                "RecFormat=mp4\n"
                "RecEncoder=x264\n"
            )

        # ── minimal scene collection ──
        scenes_dir = cfg / "basic" / "scenes"
        scenes_dir.mkdir(parents=True, exist_ok=True)
        sc = scenes_dir / "OBSapp.json"
        if not sc.exists():
            sc.write_text(json.dumps({
                "name": "OBSapp",
                "current_scene": _SCENE_NAME,
                "scenes": [{"name": _SCENE_NAME, "sources": []}],
            }, indent=2))

        # ── global.ini: websocket settings ──
        gi = cfg / "global.ini"
        if not gi.exists():
            gi.write_text(
                "[General]\n"
                "FirstRun=true\n"
                "\n"
                "[OBSWebSocket]\n"
                f"ServerPort={_WS_PORT}\n"
                "ServerEnabled=true\n"
                "ServerPassword=\n"
                "AlertsEnabled=false\n"
            )

    def _create_scene_if_missing(self, name: str) -> None:
        """Create an OBS scene, silently ignoring 'already exists' (code 601)."""
        try:
            self.ws.create_scene(name)
        except Exception:
            pass  # code 601 = already exists; any other error is also non-fatal here
