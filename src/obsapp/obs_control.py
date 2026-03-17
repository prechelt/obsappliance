"""OBS Studio process lifecycle and websocket control."""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import obsws_python as obsws

# Platform-specific source types and the property name that lists available devices.
_SOURCE_TYPES = {
    "win32": {
        "monitor": ("monitor_capture", "monitor"),
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
        self.obs_dir = obsappdir / "obsstudio"
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
        self._ensure_obs_config()
        obs_exe = self._find_obs_executable()
        self.obs_dir.mkdir(parents=True, exist_ok=True)
        self._process = subprocess.Popen(
            [obs_exe, "--portable", "--minimize-to-tray",
             "--collection", "OBSapp", "--profile", "OBSapp"],
            cwd=str(self.obs_dir),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        # Wait for websocket to become available.
        for _ in range(30):
            try:
                self.ws = obsws.ReqClient(
                    host="localhost", port=_WS_PORT, password="", timeout=3,
                )
                return
            except Exception:
                time.sleep(1)
        raise ConnectionError("Could not connect to OBS websocket after 30 s")

    def stop(self) -> None:
        """Shut down OBS."""
        if self.ws is not None:
            try:
                self.ws = None          # closes on garbage collection
            except Exception:
                pass
        if self._process is not None:
            self._process.terminate()
            try:
                self._process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self._process.kill()
            self._process = None

    # ── device enumeration ────────────────────────────────────────────

    def get_monitors(self) -> list[tuple[str, str]]:
        return self._enumerate_devices("monitor")

    def get_microphones(self) -> list[tuple[str, str]]:
        return self._enumerate_devices("mic")

    def get_webcams(self) -> list[tuple[str, str]]:
        return self._enumerate_devices("webcam")

    # ── recording control ─────────────────────────────────────────────

    def setup_recording(
        self,
        monitor_value: str,
        mic_value: str | None,
        output_dir: str,
    ) -> None:
        """Configure OBS scene and sources for the upcoming recording."""
        assert self.ws is not None
        # Set output directory.
        self.ws.set_profile_parameter(
            parameter_category="SimpleOutput",
            parameter_name="FilePath",
            parameter_value=output_dir,
        )
        # Ensure our scene exists and is active.
        try:
            self.ws.create_scene(scene_name=_SCENE_NAME)
        except Exception:
            pass  # already exists
        self.ws.set_current_program_scene(scene_name=_SCENE_NAME)
        # Remove old sources so we start clean.
        for name in ("OBSapp_Monitor", "OBSapp_Mic"):
            try:
                self.ws.remove_input(input_name=name)
            except Exception:
                pass
        # Add monitor capture.
        types = _SOURCE_TYPES[self._platform]
        mon_kind, mon_prop = types["monitor"]
        self.ws.create_input(
            scene_name=_SCENE_NAME,
            input_name="OBSapp_Monitor",
            input_kind=mon_kind,
            input_settings={mon_prop: monitor_value},
            scene_item_enabled=True,
        )
        # Add microphone (if selected).
        if mic_value:
            mic_kind, mic_prop = types["mic"]
            self.ws.create_input(
                scene_name=_SCENE_NAME,
                input_name="OBSapp_Mic",
                input_kind=mic_kind,
                input_settings={mic_prop: mic_value},
                scene_item_enabled=True,
            )

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
        if self._platform == "win32":
            portable = self.obs_dir / "bin" / "64bit" / "obs64.exe"
            if portable.exists():
                return str(portable)
            progfiles = os.environ.get("ProgramFiles", r"C:\Program Files")
            system = Path(progfiles) / "obs-studio" / "bin" / "64bit" / "obs64.exe"
            if system.exists():
                return str(system)
            raise FileNotFoundError("OBS Studio not found")
        if self._platform == "darwin":
            app = Path("/Applications/OBS.app/Contents/MacOS/OBS")
            if app.exists():
                return str(app)
            raise FileNotFoundError("OBS Studio not found")
        # linux – assume 'obs' is in PATH
        return "obs"

    def _obs_config_path(self) -> Path:
        """Portable config directory (written before first OBS start)."""
        return self.obs_dir / "config" / "obs-studio"

    def _ensure_obs_config(self) -> None:
        """Create initial OBS config files if they do not exist yet."""
        cfg = self._obs_config_path()

        # ── websocket: enabled, no authentication ──
        ws_dir = cfg / "plugin_config" / "obs-websocket"
        ws_dir.mkdir(parents=True, exist_ok=True)
        ws_cfg = ws_dir / "config.json"
        if not ws_cfg.exists():
            ws_cfg.write_text(json.dumps({
                "server_enabled": True,
                "server_port": _WS_PORT,
                "server_password": "",
                "alerts_enabled": False,
            }, indent=2))

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

    def _enumerate_devices(self, device_type: str) -> list[tuple[str, str]]:
        """Create a temporary OBS source, query its device list, remove it."""
        assert self.ws is not None
        kind, prop = _SOURCE_TYPES[self._platform][device_type]
        temp_name = f"_obsapp_enum_{device_type}"
        try:
            # Ensure scene exists for the temporary source.
            try:
                self.ws.create_scene(scene_name=_SCENE_NAME)
            except Exception:
                pass
            self.ws.create_input(
                scene_name=_SCENE_NAME,
                input_name=temp_name,
                input_kind=kind,
                input_settings={},
                scene_item_enabled=False,
            )
            resp = self.ws.get_input_properties_list_property_items(
                input_name=temp_name, property_name=prop,
            )
            return [
                (item["itemName"], item["itemValue"])
                for item in resp.property_items
            ]
        except Exception as exc:
            print(f"Device enumeration for {device_type} failed: {exc}")
            return []
        finally:
            try:
                self.ws.remove_input(input_name=temp_name)
            except Exception:
                pass
