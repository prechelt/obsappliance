"""Record configuration dialog and recording controls (Pause/Resume, Stop)."""

import time
from pathlib import Path

import customtkinter as ctk

from .widgets import PADDING, ask_confirmation, choose_save_file, show_message


class RecordDialogFrame(ctk.CTkFrame):
    """Config dialog shown before recording starts (use-case 2a1)."""

    def __init__(self, parent, app):
        super().__init__(parent, fg_color="transparent")
        self.app = app

        defaults = app.config_store.load()

        # ── Monitor ──
        ctk.CTkLabel(self, text="Which screen to record:").pack(
            anchor="w", padx=PADDING, pady=(PADDING, 2),
        )
        self._monitor_var = ctk.StringVar()
        monitors = app.obs.get_monitors()
        monitor_names = [n for n, _ in monitors] or ["(no monitors found)"]
        self._monitor_map = dict(monitors)
        ctk.CTkOptionMenu(
            self, variable=self._monitor_var, values=monitor_names,
        ).pack(padx=PADDING, fill="x")
        if defaults.get("monitor") in monitor_names:
            self._monitor_var.set(defaults["monitor"])

        # ── Microphone ──
        ctk.CTkLabel(self, text="Which microphone to record:").pack(
            anchor="w", padx=PADDING, pady=(10, 2),
        )
        self._mic_var = ctk.StringVar(value="<no audio>")
        mics = [("<no audio>", "")] + app.obs.get_microphones()
        mic_names = [n for n, _ in mics]
        self._mic_map = dict(mics)
        ctk.CTkOptionMenu(
            self, variable=self._mic_var, values=mic_names,
        ).pack(padx=PADDING, fill="x")
        if defaults.get("mic") in mic_names:
            self._mic_var.set(defaults["mic"])

        # ── Webcam ──
        ctk.CTkLabel(self, text="Which webcam to record:").pack(
            anchor="w", padx=PADDING, pady=(10, 2),
        )
        self._webcam_var = ctk.StringVar(value="<no webcam>")
        webcams = [("<no webcam>", "")] + app.obs.get_webcams()
        webcam_names = [n for n, _ in webcams]
        self._webcam_map = dict(webcams)
        ctk.CTkOptionMenu(
            self, variable=self._webcam_var, values=webcam_names,
        ).pack(padx=PADDING, fill="x")
        if defaults.get("webcam") in webcam_names:
            self._webcam_var.set(defaults["webcam"])

        # ── Target file ──
        ctk.CTkLabel(self, text="Target MP4 file:").pack(
            anchor="w", padx=PADDING, pady=(10, 2),
        )
        file_row = ctk.CTkFrame(self, fg_color="transparent")
        file_row.pack(padx=PADDING, fill="x")

        self._file_var = ctk.StringVar(value=defaults.get("target_file", ""))
        ctk.CTkEntry(file_row, textvariable=self._file_var).pack(
            side="left", fill="x", expand=True, padx=(0, 5),
        )
        ctk.CTkButton(
            file_row, text="Browse…", width=80, command=self._browse,
        ).pack(side="right")

        # ── Buttons ──
        btn_row = ctk.CTkFrame(self, fg_color="transparent")
        btn_row.pack(padx=PADDING, pady=PADDING)
        ctk.CTkButton(btn_row, text="Record", command=self._on_record).pack(
            side="left", padx=5,
        )
        ctk.CTkButton(
            btn_row, text="Cancel", command=self.app.show_main_menu,
        ).pack(side="left", padx=5)

    # ── callbacks ─────────────────────────────────────────────────────

    def _browse(self) -> None:
        path = choose_save_file(self)
        if path:
            self._file_var.set(path)

    def _on_record(self) -> None:
        target = self._file_var.get().strip()
        if not target:
            show_message(self, "Error", "Please specify a target MP4 file.")
            return

        target_path = Path(target)
        if not target_path.suffix:
            target_path = target_path.with_suffix(".mp4")

        if target_path.exists():
            if not ask_confirmation(
                self, "File exists",
                f"{target_path.name} already exists.\nOverwrite?",
            ):
                return

        # Persist defaults (2a3).
        self.app.config_store.save({
            "monitor": self._monitor_var.get(),
            "mic": self._mic_var.get(),
            "webcam": self._webcam_var.get(),
            "target_file": str(target_path),
        })

        monitor_val = self._monitor_map.get(self._monitor_var.get(), "")
        mic_name = self._mic_var.get()
        mic_val = self._mic_map.get(mic_name) if mic_name != "<no audio>" else None
        webcam_name = self._webcam_var.get()
        webcam_val = self._webcam_map.get(webcam_name) if webcam_name != "<no webcam>" else None

        try:
            self.app.obs.setup_recording(
                monitor_value=monitor_val,
                mic_value=mic_val,
                webcam_value=webcam_val,
                output_dir=str(target_path.parent),
            )
            self.app.obs.start_recording()
            self.app.show_recording_controls(target_path)
        except Exception as exc:
            show_message(self, "Error", f"Failed to start recording:\n{exc}")


class RecordingFrame(ctk.CTkFrame):
    """Small recording-control window: Pause/Resume + Stop (2a4–2a6)."""

    def __init__(self, parent, app, target_path: Path):
        super().__init__(parent, fg_color="transparent")
        self.app = app
        self.target_path = target_path
        self._paused = False

        ctk.CTkLabel(
            self,
            text="Recording…",
            font=ctk.CTkFont(size=16, weight="bold"),
        ).pack(padx=PADDING, pady=(PADDING, 10))

        btn_row = ctk.CTkFrame(self, fg_color="transparent")
        btn_row.pack(padx=PADDING, pady=(0, PADDING))

        self._pause_btn = ctk.CTkButton(
            btn_row, text="Pause", command=self._on_pause,
        )
        self._pause_btn.pack(side="left", padx=5)

        ctk.CTkButton(btn_row, text="Stop", command=self._on_stop).pack(
            side="left", padx=5,
        )

    def _on_pause(self) -> None:
        if self._paused:
            self.app.obs.resume_recording()
            self._pause_btn.configure(text="Pause")
            self._paused = False
        else:
            self.app.obs.pause_recording()
            self._pause_btn.configure(text="Resume")
            self._paused = True

    def _on_stop(self) -> None:
        # Pause first so the user can review (2a6).
        if not self._paused:
            self.app.obs.pause_recording()
            self._paused = True
            self._pause_btn.configure(text="Resume")

        if ask_confirmation(self, "Stop Recording", "Stop recording?"):
            try:
                actual_path_str = self.app.obs.stop_recording()
                # Rename OBS's auto-named file to the user's chosen target.
                # OBS may still hold the file handle briefly after stop_record()
                # returns (it flushes on a background thread), so retry with
                # backoff until the rename succeeds or a timeout is reached.
                if actual_path_str:
                    actual = Path(actual_path_str)
                    if actual.exists() and actual != self.target_path:
                        self.target_path.parent.mkdir(parents=True, exist_ok=True)
                        if self.target_path.exists():
                            self.target_path.unlink()
                        _rename_with_retry(actual, self.target_path)
            except Exception as exc:
                show_message(self, "Error", f"Error stopping recording:\n{exc}")
            self.app.show_main_menu()
        else:
            # Cancel → unpause (2a6).
            self.app.obs.resume_recording()
            self._pause_btn.configure(text="Pause")
            self._paused = False


def _rename_with_retry(
    src: Path,
    dst: Path,
    timeout: float = 10.0,
    interval: float = 0.5,
) -> None:
    """Rename *src* to *dst*, retrying on PermissionError for up to *timeout* seconds.

    OBS finalises MP4 files on a background thread after stop_record() returns,
    so the file handle may still be open for a short time.  On Windows this
    manifests as [WinError 32] (file in use).
    """
    deadline = time.monotonic() + timeout
    while True:
        try:
            src.rename(dst)
            return
        except PermissionError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(interval)
