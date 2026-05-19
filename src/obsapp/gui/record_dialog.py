"""Record configuration dialog and recording controls (Pause/Resume, Stop)."""

from __future__ import annotations

import datetime
import time
import tkinter as tk
from pathlib import Path
from typing import TYPE_CHECKING

import customtkinter as ctk

from ..api import PiPConfig
from ..constants import (
    PIP_CELL_MARGIN,
    PIP_HEIGHT,
    PIP_SIZE_LARGE,
    PIP_SIZE_MEDIUM,
    PIP_SIZE_SMALL,
    PIP_WEBCAM_ASPECT,
)
from .widgets import PADDING, ask_confirmation, choose_save_file, fit_window, fix_textbox_tab, setup_keyboard_nav, show_message

if TYPE_CHECKING:
    from ..main import App

# ── PiP preview grid constants ────────────────────────────────────────────────

# Derived canvas dimensions (logical pixels) — all follow from the three
# tuneable constants in constants.py (PIP_HEIGHT, PIP_CELL_MARGIN, PIP_WEBCAM_ASPECT).
_PIP_CELL_H: float = (PIP_HEIGHT - 4 * PIP_CELL_MARGIN) / 3
_PIP_CELL_W: float = _PIP_CELL_H * PIP_WEBCAM_ASPECT
_PIP_CANVAS_W: int = round(3 * _PIP_CELL_W + 4 * PIP_CELL_MARGIN)

_PIP_COLOR_SELECTED = "#3b8ed0"
_PIP_COLOR_UNSELECTED = "#808080"

_PIP_ROWS = ("top", "middle", "bottom")
_PIP_COLS = ("left", "center", "right")

_PIP_SIZE_LEGACY = {"small": PIP_SIZE_SMALL, "medium": PIP_SIZE_MEDIUM, "large": PIP_SIZE_LARGE}


def _parse_pip_size(raw: object, default: int) -> int:
    """Return a valid pip size int from a stored config value.

    Accepts an int, a numeric string (``"240"``), or a legacy label
    (``"small"`` / ``"medium"`` / ``"large"``).  Falls back to *default*
    for any unrecognised value so stale config never crashes the dialog.
    """
    if isinstance(raw, int):
        return raw
    if isinstance(raw, str):
        if raw in _PIP_SIZE_LEGACY:
            return _PIP_SIZE_LEGACY[raw]
        try:
            return int(raw)
        except ValueError:
            pass
    return default


class RecordDialogFrame(ctk.CTkFrame):
    """Config dialog shown before recording starts (use-case 2a1)."""

    def __init__(self, parent: ctk.CTk | ctk.CTkFrame, app: App) -> None:
        super().__init__(parent, fg_color="transparent")
        self.app = app

        defaults = app.config_store.load()

        # ── Monitor ──
        ctk.CTkLabel(self, text="Which screen to record:").pack(
            anchor="w", padx=PADDING, pady=(PADDING, 2),
        )
        self._monitor_var = ctk.StringVar()
        monitors = app.obs.get_monitors()
        monitor_names = [n for n, *_ in monitors] or ["(no monitors found)"]
        self._monitor_map = {n: v for n, v, *_ in monitors}
        self._monitor_res_map: dict[str, tuple[int, int]] = {
            n: (w, h) for n, _v, w, h in monitors
        }
        self._monitor_menu = ctk.CTkOptionMenu(
            self, variable=self._monitor_var, values=monitor_names,
        )
        self._monitor_menu.pack(padx=PADDING, fill="x")
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
        self._mic_menu = ctk.CTkOptionMenu(
            self, variable=self._mic_var, values=mic_names,
        )
        self._mic_menu.pack(padx=PADDING, fill="x")
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
        self._webcam_menu = ctk.CTkOptionMenu(
            self, variable=self._webcam_var, values=webcam_names,
            command=self._on_webcam_changed,
        )
        self._webcam_menu.pack(padx=PADDING, fill="x")
        if defaults.get("webcam") in webcam_names:
            self._webcam_var.set(defaults["webcam"])

        # ── PiP position picker (hidden when no webcam selected) ──────
        self._pip_pos_var = ctk.StringVar(
            value=defaults.get("pip_position", "middle-right")
        )
        self._pip_size_var = ctk.IntVar(
            value=_parse_pip_size(defaults.get("pip_size"), PIP_SIZE_SMALL)
        )
        self._pip_frame = ctk.CTkFrame(self, fg_color="transparent")
        ctk.CTkLabel(self._pip_frame, text="Webcam position:").pack(
            anchor="w", pady=(0, 2),
        )
        bg = self.winfo_toplevel().cget("background") if self.winfo_toplevel() else "white"
        self._pip_canvas = tk.Canvas(
            self._pip_frame,
            width=_PIP_CANVAS_W,
            height=PIP_HEIGHT,
            bg=bg,
            highlightthickness=1,
            highlightbackground="#555555",
            cursor="hand2",
        )
        self._pip_canvas.pack(anchor="w")
        self._pip_canvas.bind("<Button-1>", self._on_pip_click)
        size_row = ctk.CTkFrame(self._pip_frame, fg_color="transparent")
        size_row.pack(anchor="w", pady=(4, 0))
        ctk.CTkLabel(size_row, text="PiP insert height:").pack(side="left", padx=(0, 8))
        for px in (PIP_SIZE_SMALL, PIP_SIZE_MEDIUM, PIP_SIZE_LARGE):
            ctk.CTkRadioButton(
                size_row, text=f"{px} pixel",
                variable=self._pip_size_var, value=px,
                command=self._pip_draw,
            ).pack(side="left", padx=(0, 10))
        # Show or hide pip_frame based on the current (defaulted) webcam choice.
        if self._webcam_var.get() != "<no webcam>":
            self._pip_frame.pack(after=self._webcam_menu, padx=PADDING, fill="x", pady=(8, 0))
            self._pip_draw()

        # ── Target file ──
        ctk.CTkLabel(self, text="Target MP4 file:").pack(
            anchor="w", padx=PADDING, pady=(10, 2),
        )
        file_row = ctk.CTkFrame(self, fg_color="transparent")
        file_row.pack(padx=PADDING, fill="x")

        stored = defaults.get("target_file", "")
        if stored:
            stored_path = Path(stored)
            if stored_path.exists():
                stamp = datetime.datetime.now().strftime("%Y-%m-%d_%H%M")
                stored = str(stored_path.with_stem(stamp))
        self._file_var = ctk.StringVar(value=stored)
        self._file_entry = ctk.CTkEntry(file_row, textvariable=self._file_var)
        self._file_entry.pack(side="left", fill="x", expand=True, padx=(0, 5))
        self._file_entry.bind("<Return>", lambda e: self._on_record())
        browse_btn = ctk.CTkButton(
            file_row, text="Browse…", width=80, command=self._browse,
        )
        browse_btn.pack(side="right")

        # Set the window wide enough for the entry to show 60 characters.
        # We defer by one event-loop tick so the entry widget is fully realised
        # and its internal Tk Entry is accessible for font measurement.
        self.after(0, self._set_min_width_for_entry)

        # ── Buttons ──
        btn_row = ctk.CTkFrame(self, fg_color="transparent")
        btn_row.pack(padx=PADDING, pady=PADDING)
        record_btn = ctk.CTkButton(btn_row, text="Record", command=self._on_record)
        record_btn.pack(side="left", padx=5)
        cancel_btn = ctk.CTkButton(
            btn_row, text="Cancel", command=self.app.show_main_menu,
        )
        cancel_btn.pack(side="left", padx=5)

        setup_keyboard_nav(self._monitor_menu, self._mic_menu, self._webcam_menu,
                           browse_btn, record_btn, cancel_btn)
        self.app.bind_all("<Escape>", lambda e: self.app.show_main_menu())
        self.after(0, lambda: self._monitor_menu._canvas.focus_set())

    # ── callbacks ─────────────────────────────────────────────────────

    def _on_webcam_changed(self, value: str) -> None:
        """Show or hide the PiP selector based on whether a webcam is chosen."""
        if value == "<no webcam>":
            self._pip_frame.pack_forget()
        else:
            self._pip_frame.pack(after=self._webcam_menu, padx=PADDING, fill="x", pady=(8, 0))
            self._pip_draw()

    def _pip_draw(self) -> None:
        """Redraw the 3×3 position-picker grid on the PiP canvas."""
        c = self._pip_canvas
        c.delete("all")
        sel = self._pip_pos_var.get()
        for ri, row in enumerate(_PIP_ROWS):
            for ci, col in enumerate(_PIP_COLS):
                x0 = PIP_CELL_MARGIN + ci * (_PIP_CELL_W + PIP_CELL_MARGIN)
                y0 = PIP_CELL_MARGIN + ri * (_PIP_CELL_H + PIP_CELL_MARGIN)
                x1 = x0 + _PIP_CELL_W
                y1 = y0 + _PIP_CELL_H
                fill = _PIP_COLOR_SELECTED if f"{row}-{col}" == sel else _PIP_COLOR_UNSELECTED
                c.create_rectangle(x0, y0, x1, y1, fill=fill, outline="")

    def _on_pip_click(self, event: tk.Event) -> None:  # type: ignore[type-arg]
        """Select the grid cell that was clicked."""
        for ri, row in enumerate(_PIP_ROWS):
            for ci, col in enumerate(_PIP_COLS):
                x0 = PIP_CELL_MARGIN + ci * (_PIP_CELL_W + PIP_CELL_MARGIN)
                y0 = PIP_CELL_MARGIN + ri * (_PIP_CELL_H + PIP_CELL_MARGIN)
                if x0 <= event.x <= x0 + _PIP_CELL_W and y0 <= event.y <= y0 + _PIP_CELL_H:
                    self._pip_pos_var.set(f"{row}-{col}")
                    self._pip_draw()
                    return

    def _set_min_width_for_entry(self) -> None:
        """Resize window so the target-file entry displays 60 characters."""
        from tkinter.font import Font
        # Derive the entry font from CTk's configured default (same family/size
        # as every CTk widget) without touching any private CTk internals.
        _ctk_font = ctk.CTkFont()
        font = Font(family=_ctk_font.actual("family"), size=_ctk_font.cget("size"))
        # font.measure() returns screen pixels; fit_window() takes logical pixels.
        scaling = self.app._get_window_scaling()
        char_w = font.measure("0")
        entry_target_w = int(char_w * 60 / scaling)
        # Total width = entry + Browse button + padx on both sides
        browse_w = 80
        browse_padx = 5
        min_w = entry_target_w + browse_w + browse_padx + 2 * PADDING
        fit_window(self.app, self, min_w)

    def _browse(self) -> None:
        path = choose_save_file(self)
        if path:
            self._file_var.set(path)

    def _on_record(self) -> None:
        target = self._file_var.get().strip()
        if not target:
            show_message(self, "OBSapp: Error", "Please specify a target MP4 file.")
            return

        target_path = Path(target)
        if not target_path.suffix:
            target_path = target_path.with_suffix(".mp4")

        if target_path.exists():
            if not ask_confirmation(
                self, "OBSapp: File exists",
                f"{target_path.name} already exists.\nOverwrite?",
            ):
                return

        # Persist defaults (2a3).
        self.app.config_store.save({
            "monitor": self._monitor_var.get(),
            "mic": self._mic_var.get(),
            "webcam": self._webcam_var.get(),
            "pip_position": self._pip_pos_var.get(),
            "pip_size": self._pip_size_var.get(),
            "target_file": str(target_path),
        })

        mic_name = self._mic_var.get()
        webcam_name = self._webcam_var.get()

        pip_cfg: PiPConfig | None = None
        if webcam_name != "<no webcam>":
            try:
                pip_cfg = PiPConfig(
                    position=self._pip_pos_var.get(),
                    size=self._pip_size_var.get(),
                )
            except ValueError as exc:
                show_message(self, "OBSapp: Error", f"Invalid PiP config:\n{exc}")
                return

        try:
            self.app.session.start_recording(
                monitor_name=self._monitor_var.get(),
                mic_name=mic_name if mic_name != "<no audio>" else None,
                webcam_name=webcam_name if webcam_name != "<no webcam>" else None,
                target_path=target_path,
                pip=pip_cfg,
            )
            self.app.show_recording_controls(target_path)
        except Exception as exc:
            show_message(self, "OBSapp: Error", f"Failed to start recording:\n{exc}")


class RecordingFrame(ctk.CTkFrame):
    """Small recording-control window: Pause/Resume + Stop (2a4–2a6)."""

    def __init__(self, parent: ctk.CTkFrame, app: App, target_path: Path) -> None:
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

        stop_btn = ctk.CTkButton(btn_row, text="Stop", command=self._on_stop)
        stop_btn.pack(side="left", padx=5)

        setup_keyboard_nav(self._pause_btn, stop_btn)
        self.after(0, self._pause_btn.focus_set)
        self.after(0, self._fit_to_content)

    def _fit_to_content(self) -> None:
        """Resize window to the natural size of the recording controls."""
        fit_window(self.app, self, self.winfo_reqwidth())

    def _on_pause(self) -> None:
        if self._paused:
            self.app.session.resume_recording()
            self._pause_btn.configure(text="Pause")
            self._paused = False
        else:
            self.app.session.pause_recording()
            self._pause_btn.configure(text="Resume")
            self._paused = True

    def _on_stop(self) -> None:
        # Pause first so the user can review (2a6).
        if not self._paused:
            self.app.session.pause_recording()
            self._paused = True
            self._pause_btn.configure(text="Resume")

        if ask_confirmation(self, "OBSapp: Stop recording", "Stop recording?"):
            try:
                # Session.stop_recording() handles the OBS-auto-name → target rename.
                self.app.session.stop_recording()
            except Exception as exc:
                show_message(self, "OBSapp: Error", f"Error stopping recording:\n{exc}")
            self.app.show_main_menu()
        else:
            # Cancel → unpause (2a6).
            self.app.session.resume_recording()
            self._pause_btn.configure(text="Pause")
            self._paused = False


def _rename_with_retry(
    src: Path,
    dst: Path,
    timeout: float = 10.0,
    interval: float = 0.5,
) -> None:
    """Deprecated; kept for backward compatibility.

    The rename-on-stop logic now lives in :meth:`obsapp.api.Session.stop_recording`.
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
