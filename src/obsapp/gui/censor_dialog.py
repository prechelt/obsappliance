"""Censor dialog – use-case 2b.

User picks an MP4, specifies time ranges to delete, and OBSapp rewrites the
file as <name>-censored.mp4 with each range replaced by a short info frame.
"""

from __future__ import annotations

from pathlib import Path
import threading
from typing import TYPE_CHECKING

import customtkinter as ctk
from tkinter import filedialog

from .widgets import PADDING, fix_textbox_tab, setup_keyboard_nav, show_message
from ..video_ops import (
    find_ffmpeg,
    probe_video,
    validate_censor_ranges,
    censor,
)

if TYPE_CHECKING:
    from ..main import App


_EXPLANATION = (
    "Enter the MP4 file to edit and the time ranges you want to remove.\n"
    "Format: M:SS-M:SS or H:MM:SS-H:MM:SS (whole seconds, one range per line).\n"
    "Example: 0:57-1:02\n"
    "Each removed range is replaced by a short info frame.\n"
    "Output is written to <filename>-censored.mp4."
)


class CensorDialogFrame(ctk.CTkFrame):
    """Dialog for use-case 2b (Censor video)."""

    def __init__(self, parent: ctk.CTk | ctk.CTkFrame, app: App) -> None:
        super().__init__(parent, fg_color="transparent")
        self.app = app

        # ── explanation ──
        ctk.CTkLabel(
            self,
            text=_EXPLANATION,
            wraplength=480,
            justify="left",
        ).pack(anchor="w", padx=PADDING, pady=(PADDING, 10))

        # ── input file row ──
        ctk.CTkLabel(self, text="MP4 file:").pack(
            anchor="w", padx=PADDING, pady=(0, 2),
        )
        file_row = ctk.CTkFrame(self, fg_color="transparent")
        file_row.pack(padx=PADDING, fill="x")
        self._file_var = ctk.StringVar()
        self._file_entry = ctk.CTkEntry(file_row, textvariable=self._file_var)
        self._file_entry.pack(side="left", fill="x", expand=True, padx=(0, 5))
        browse_btn = ctk.CTkButton(
            file_row, text="Browse…", width=80, command=self._browse,
        )
        browse_btn.pack(side="right")

        # ── ranges text area ──
        ctk.CTkLabel(self, text="Time ranges to remove (one per line):").pack(
            anchor="w", padx=PADDING, pady=(10, 2),
        )
        self._ranges_box = ctk.CTkTextbox(self, height=120)
        self._ranges_box.pack(padx=PADDING, fill="x")

        # ── progress label (hidden until operation starts) ──
        self._progress_label = ctk.CTkLabel(self, text="")
        self._progress_label.pack(padx=PADDING, pady=(6, 0))

        # ── buttons ──
        btn_row = ctk.CTkFrame(self, fg_color="transparent")
        btn_row.pack(padx=PADDING, pady=PADDING)
        self._ok_btn = ctk.CTkButton(btn_row, text="OK", command=self._on_ok)
        self._ok_btn.pack(side="left", padx=5)
        cancel_btn = ctk.CTkButton(
            btn_row, text="Cancel", command=self.app.show_main_menu,
        )
        cancel_btn.pack(side="left", padx=5)

        fix_textbox_tab(self._ranges_box)
        setup_keyboard_nav(browse_btn, self._ok_btn, cancel_btn)
        self.app.bind_all("<Escape>", lambda e: self.app.show_main_menu())
        self.after(0, self._file_entry.focus_set)

    # ── callbacks ─────────────────────────────────────────────────────

    def _browse(self) -> None:
        path = filedialog.askopenfilename(
            parent=self,
            title="Open MP4 file",
            filetypes=[("MP4 files", "*.mp4"), ("All files", "*.*")],
        )
        if path:
            self._file_var.set(path)

    def _on_ok(self) -> None:
        input_str = self._file_var.get().strip()
        if not input_str:
            show_message(self, "Error", "Please specify an MP4 file.")
            return

        input_path = Path(input_str)
        if not input_path.exists():
            show_message(self, "Error", f"File not found:\n{input_path}")
            return

        ranges_text = self._ranges_box.get("1.0", "end")

        # Probe video to get duration.
        try:
            ffmpeg = find_ffmpeg(self.app.ffmpeg_executable)
            info = probe_video(ffmpeg, input_path)
        except Exception as exc:
            show_message(self, "Error", f"Could not probe video:\n{exc}")
            return

        ranges, errors = validate_censor_ranges(ranges_text, info["duration"])
        if errors:
            show_message(self, "Validation errors", "\n".join(errors))
            return

        if not ranges:
            show_message(self, "Error", "No time ranges entered.")
            return

        output_path = input_path.with_stem(input_path.stem + "-censored")

        # Run in a background thread so the GUI stays responsive.
        self._ok_btn.configure(state="disabled")
        self._progress_label.configure(text="Processing… please wait.")
        self.update()

        def _worker():
            try:
                censor(
                    ffmpeg,
                    input_path,
                    ranges,
                    output_path,
                    width=info["width"],
                    height=info["height"],
                    fps=info["fps"],
                )
                self.after(0, lambda: self._on_done(output_path, error=None))
            except Exception as exc:
                msg = str(exc)
                self.after(0, lambda: self._on_done(output_path, error=msg))

        threading.Thread(target=_worker, daemon=True).start()

    def _on_done(self, output_path: Path, error: str | None) -> None:
        self._ok_btn.configure(state="normal")
        self._progress_label.configure(text="")
        if error:
            show_message(self, "Error", f"Censoring failed:\n{error}")
        else:
            show_message(
                self, "Done",
                f"Censored video written to:\n{output_path}",
            )
            self.app.show_main_menu()
