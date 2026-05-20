"""OBSapp – OBS Studio recording appliance GUI.

Entry point: obsapp.main:main  (see pyproject.toml [project.scripts]).
"""

import os
import sys
from pathlib import Path

import customtkinter as ctk

from .api import Session, load_config, obs_config_dir_for
from .config import ConfigStore
from .gui.censor_dialog import CensorDialogFrame
from .gui.concat_dialog import ConcatDialogFrame
from .gui.main_menu import MainMenuFrame
from .gui.record_dialog import RecordDialogFrame, RecordingFrame
from .gui.widgets import PADDING, show_message


class App(ctk.CTk):
    def __init__(self, cfg: dict, obs_config_dir: Path) -> None:
        super().__init__()
        self.title("OBSapp")

        # Set our icon.  Two calls are needed on Windows:
        # 1. iconbitmap() sets CTk's _iconbitmap_method_called flag so CTk
        #    never overwrites the icon with its own logo.
        # 2. wm_iconphoto() supplies a high-resolution PNG so Windows can
        #    render a sharp icon on the taskbar and in task-switchers.
        #    Tk 8.6+ loads PNG natively; no Pillow required.
        #    The PhotoImage must be kept alive on self to prevent GC.
        _res = Path(__file__).parent / "resources"
        _ico = _res / "obsapp-icon.ico"
        _png = _res / "obsapp-icon.png"
        if _ico.exists():
            self.iconbitmap(str(_ico))
        if _png.exists():
            import tkinter as tk
            self._app_icon = tk.PhotoImage(file=str(_png))
            self.wm_iconphoto(True, self._app_icon)

        self.ffmpeg_executable: str = cfg["ffmpeg_executable"]

        # Programmatic appliance API.  GUI callbacks delegate to it; the
        # integration test driver uses the same Session directly.
        self.session = Session(cfg=cfg, obs_config_dir=obs_config_dir)
        # Backward-compat alias for existing GUI code that uses app.obs.*
        self.obs = self.session.obs
        self.config_store = ConfigStore(Path("obsapp_settings.json"))

        self._current_frame: ctk.CTkFrame | None = None

        self.protocol("WM_DELETE_WINDOW", self.quit_app)

        self.show_main_menu()

    # ── frame management ──────────────────────────────────────────────

    def _show_frame(self, frame: ctk.CTkFrame, title: str = "OBSapp") -> None:
        if self._current_frame is not None:
            self._current_frame.destroy()
        # Reset window size and minimum constraints so the incoming frame's
        # fit_window() callback measures only its own natural content height,
        # not the leftover geometry from the previous frame.
        self.minsize(1, 1)
        self.geometry("1x1")
        self._current_frame = frame
        self._current_frame.pack(fill="both", expand=True)
        self.title(title)

    def show_main_menu(self) -> None:
        self._show_frame(MainMenuFrame(self, app=self), title="OBSapp")

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
                show_message(self, "OBSapp: Error", f"Failed to start OBS:\n{exc}")
                self.show_main_menu()
                return
            loading.destroy()

        self._show_frame(RecordDialogFrame(self, app=self), title="OBSapp: Record video")

    def show_recording_controls(self, target_path: Path) -> None:
        self._show_frame(
            RecordingFrame(self, app=self, target_path=target_path),
            title="OBSapp: Record video",
        )

    def show_censor_dialog(self) -> None:
        self._show_frame(CensorDialogFrame(self, app=self), title="OBSapp: Censor a video")

    def show_concat_dialog(self) -> None:
        self._show_frame(
            ConcatDialogFrame(self, app=self),
            title="OBSapp: Concatenate several videos",
        )

    # ── shutdown ──────────────────────────────────────────────────────

    def quit_app(self) -> None:
        """Close the window; cleanup (stopping OBS) happens in main() after mainloop returns."""
        self.destroy()


def main() -> None:
    if len(sys.argv) < 2:
        sys.exit("Error: expected a .ini file as the first argument.")
    try:
        cfg = load_config(sys.argv[1])
    except (FileNotFoundError, ValueError) as exc:
        sys.exit(f"Error: {exc}")
    obs_config_dir = obs_config_dir_for(sys.argv[1])
    os.chdir(Path(sys.argv[1]).resolve().parent)

    # On Windows, decouple the process from python.exe so the taskbar shows
    # OBSapp as its own entry (not grouped under the Python launcher).
    if sys.platform == "win32":
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "obsapp.obsapp.1"
        )

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
