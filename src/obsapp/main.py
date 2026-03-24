"""OBSapp – OBS Studio recording appliance GUI.

Entry point: obsapp.main:main  (see pyproject.toml [project.scripts]).
"""

import configparser
import os
import sys
from pathlib import Path

import customtkinter as ctk

from .config import ConfigStore
from .gui.censor_dialog import CensorDialogFrame
from .gui.concat_dialog import ConcatDialogFrame
from .gui.main_menu import MainMenuFrame
from .gui.record_dialog import RecordDialogFrame, RecordingFrame
from .gui.widgets import PADDING, show_message
from .obs_control import OBSController

# Name of the OBS config subdirectory inside the obsapp directory.
_OBS_CONFIG_SUBDIR = "obs-config"


def _read_config(inifile: str) -> dict:
    """Parse the given .ini file and return its entries as a flat dict."""
    path = Path(inifile)
    if not path.suffix == ".ini" or not path.exists():
        sys.exit(f"Error: '{inifile}' is not an existing .ini file.")
    parser = configparser.ConfigParser()
    parser.read(path)
    result = {}
    for section in parser.sections():
        for key, value in parser.items(section):
            result[key] = value
    return result


class App(ctk.CTk):
    def __init__(self, cfg: dict, obs_config_dir: Path) -> None:
        super().__init__()
        self.title("OBSapp")
        self.ffmpeg_executable: str = cfg["ffmpeg_executable"]

        self.obs = OBSController(
            obs_executable=cfg["obs_executable"],
            obs_config_dir=obs_config_dir,
        )
        self.config_store = ConfigStore(Path("obsapp_settings.json"))

        self._current_frame: ctk.CTkFrame | None = None

        self.protocol("WM_DELETE_WINDOW", self.quit_app)

        self.show_main_menu()

    # ── frame management ──────────────────────────────────────────────

    def _show_frame(self, frame: ctk.CTkFrame) -> None:
        if self._current_frame is not None:
            self._current_frame.destroy()
        self._current_frame = frame
        self._current_frame.pack(fill="both", expand=True)

    def show_main_menu(self) -> None:
        self._show_frame(MainMenuFrame(self, app=self))

    def show_record_dialog(self) -> None:
        """Lazy-start OBS, then show the record configuration dialog."""
        if not self.obs.is_running:
            # Show a temporary loading label while OBS starts.
            if self._current_frame is not None:
                self._current_frame.destroy()
                self._current_frame = None
            loading = ctk.CTkLabel(
                self, text="Starting OBS Studio…",
                font=ctk.CTkFont(size=14),
            )
            loading.pack(padx=PADDING, pady=PADDING)
            self.update()
            try:
                self.obs.start()
            except Exception as exc:
                loading.destroy()
                show_message(self, "Error", f"Failed to start OBS:\n{exc}")
                self.show_main_menu()
                return
            loading.destroy()

        self._show_frame(RecordDialogFrame(self, app=self))

    def show_recording_controls(self, target_path: Path) -> None:
        self._show_frame(RecordingFrame(self, app=self, target_path=target_path))

    def show_censor_dialog(self) -> None:
        self._show_frame(CensorDialogFrame(self, app=self))

    def show_concat_dialog(self) -> None:
        self._show_frame(ConcatDialogFrame(self, app=self))

    # ── shutdown ──────────────────────────────────────────────────────

    def quit_app(self) -> None:
        """Close the window; cleanup (stopping OBS) happens in main() after mainloop returns."""
        self.destroy()


def main() -> None:
    if len(sys.argv) < 2:
        sys.exit("Error: expected a .ini file as the first argument.")
    cfg = _read_config(sys.argv[1])
    missing = [k for k in ("obs_executable", "ffmpeg_executable") if k not in cfg]
    if missing:
        sys.exit(
            "Error: the following entries are missing from the .ini file: "
            + ", ".join(missing)
        )
    obs_config_dir = Path(sys.argv[1]).resolve().parent / _OBS_CONFIG_SUBDIR
    os.chdir(Path(sys.argv[1]).resolve().parent)
    ctk.set_appearance_mode("system")
    ctk.set_default_color_theme("blue")
    app = App(cfg=cfg, obs_config_dir=obs_config_dir)
    try:
        app.mainloop()
    finally:
        # Runs on normal exit, exceptions, and KeyboardInterrupt.
        # Not guaranteed on hard crashes (SIGKILL/power loss), but covers all
        # normal termination paths including unhandled exceptions.
        app.obs.stop()


if __name__ == "__main__":
    main()
