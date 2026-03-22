"""OBSapp – OBS Studio recording appliance GUI.

Entry point: obsapp.main:main  (see pyproject.toml [project.scripts]).
"""

import atexit
import configparser
import os
import sys
from pathlib import Path

import customtkinter as ctk

from .config import ConfigStore
from .gui.main_menu import MainMenuFrame
from .gui.record_dialog import RecordDialogFrame, RecordingFrame
from .gui.widgets import PADDING, show_message
from .obs_control import OBSController


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
    def __init__(self, cfg: dict) -> None:
        super().__init__()
        self.title("OBSapp")
        self.obsstudio_dir = Path(cfg["obsstudio_dir"])

        self.obs = OBSController(self.obsstudio_dir)
        self.config_store = ConfigStore(Path("obsapp_settings.json"))

        self._current_frame: ctk.CTkFrame | None = None

        atexit.register(self._cleanup)
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

    # ── shutdown ──────────────────────────────────────────────────────

    def quit_app(self) -> None:
        self._cleanup()
        self.destroy()

    def _cleanup(self) -> None:
        self.obs.stop()


def main() -> None:
    if len(sys.argv) < 2:
        sys.exit("Error: expected a .ini file as the first argument.")
    cfg = _read_config(sys.argv[1])
    if "obsstudio_dir" not in cfg:
        sys.exit("Error: 'obsstudio_dir' entry missing from the .ini file.")
    os.chdir(Path(sys.argv[1]).resolve().parent)
    ctk.set_appearance_mode("system")
    ctk.set_default_color_theme("blue")
    app = App(cfg=cfg)
    app.mainloop()


if __name__ == "__main__":
    main()
