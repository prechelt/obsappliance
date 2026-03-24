"""Concatenate dialog – use-case 2c.

User builds an ordered list of MP4 files; OBSapp concatenates them into a
single output file, inserting a 1-second title frame (showing the filename)
before each part.
"""

from __future__ import annotations

from pathlib import Path
import threading
from typing import TYPE_CHECKING

import customtkinter as ctk
from tkinter import filedialog

from .widgets import PADDING, show_message
from ..video_ops import find_ffmpeg, validate_concat_inputs, concatenate

if TYPE_CHECKING:
    from ..main import App


_EXPLANATION = (
    "Build an ordered list of MP4 files to join.\n"
    "A 1-second title frame (showing each file's name) is inserted before each part.\n"
    "All parts are re-encoded to match the resolution and frame rate of the first file."
)


class ConcatDialogFrame(ctk.CTkFrame):
    """Dialog for use-case 2c (Concatenate videos)."""

    def __init__(self, parent: ctk.CTk | ctk.CTkFrame, app: App) -> None:
        super().__init__(parent, fg_color="transparent")
        self.app = app

        defaults = app.config_store.load()

        # ── explanation ──
        ctk.CTkLabel(
            self,
            text=_EXPLANATION,
            wraplength=480,
            justify="left",
        ).pack(anchor="w", padx=PADDING, pady=(PADDING, 10))

        # ── file list (editable, scrollable, one path per line) ──
        ctk.CTkLabel(self, text="Files to concatenate (one path per line):").pack(
            anchor="w", padx=PADDING, pady=(0, 2),
        )
        self._list_box = ctk.CTkTextbox(self, height=120, wrap="none")
        self._list_box.pack(padx=PADDING, fill="x")

        # ── add input files (Browse opens a multi-select picker) ──
        ctk.CTkButton(
            self,
            text="Add input file(s)…",
            command=self._browse_input,
        ).pack(anchor="w", padx=PADDING, pady=(6, 0))

        # ── output file row ──
        ctk.CTkLabel(self, text="Output file:").pack(
            anchor="w", padx=PADDING, pady=(10, 2),
        )
        out_row = ctk.CTkFrame(self, fg_color="transparent")
        out_row.pack(padx=PADDING, fill="x")
        self._output_var = ctk.StringVar(value=defaults.get("concat_output_file", ""))
        ctk.CTkEntry(out_row, textvariable=self._output_var).pack(
            side="left", fill="x", expand=True, padx=(0, 5),
        )
        ctk.CTkButton(
            out_row, text="Browse…", width=80, command=self._browse_output,
        ).pack(side="right")

        # ── progress label ──
        self._progress_label = ctk.CTkLabel(self, text="")
        self._progress_label.pack(padx=PADDING, pady=(6, 0))

        # ── buttons ──
        btn_row = ctk.CTkFrame(self, fg_color="transparent")
        btn_row.pack(padx=PADDING, pady=PADDING)
        self._done_btn = ctk.CTkButton(
            btn_row, text="Concatenate now", command=self._on_done,
        )
        self._done_btn.pack(side="left", padx=5)
        ctk.CTkButton(
            btn_row, text="Cancel", command=self.app.show_main_menu,
        ).pack(side="left", padx=5)

    # ── callbacks ─────────────────────────────────────────────────────

    def _browse_input(self) -> None:
        """Open a multi-select file picker and append chosen paths to the list."""
        paths = filedialog.askopenfilenames(
            parent=self,
            title="Select input MP4 file(s)",
            filetypes=[("MP4 files", "*.mp4"), ("All files", "*.*")],
        )
        # askopenfilenames returns a tuple of strings (empty tuple if cancelled).
        for p in paths:
            if not p:
                continue
            # Avoid duplicates: check existing lines in the textbox.
            existing = self._get_paths()
            if p not in existing:
                # Ensure the box ends with a newline before appending.
                current = self._list_box.get("1.0", "end")
                if current.strip():
                    self._list_box.insert("end", "\n" + p)
                else:
                    self._list_box.insert("end", p)

    def _browse_output(self) -> None:
        path = filedialog.asksaveasfilename(
            parent=self,
            title="Save concatenated video as",
            filetypes=[("MP4 files", "*.mp4"), ("All files", "*.*")],
            defaultextension=".mp4",
        )
        if path:
            self._output_var.set(path)

    def _get_paths(self) -> list[str]:
        """Return non-blank lines from the file list textbox."""
        raw = self._list_box.get("1.0", "end")
        return [line.strip() for line in raw.splitlines() if line.strip()]

    def _on_done(self) -> None:
        input_strs = self._get_paths()
        if not input_strs:
            show_message(self, "Error", "Add at least one input file.")
            return

        output_str = self._output_var.get().strip()
        if not output_str:
            show_message(self, "Error", "Please specify an output file.")
            return

        input_paths = [Path(p) for p in input_strs]
        output_path = Path(output_str)
        if not output_path.suffix:
            output_path = output_path.with_suffix(".mp4")

        errors = validate_concat_inputs(input_paths)
        if errors:
            show_message(self, "Validation errors", "\n".join(errors))
            return

        try:
            ffmpeg = find_ffmpeg(self.app.obsstudio_dir)
        except Exception as exc:
            show_message(self, "Error", str(exc))
            return

        # Persist the output path for next time.
        self.app.config_store.save({"concat_output_file": str(output_path)})

        self._done_btn.configure(state="disabled")
        self._progress_label.configure(text="Processing… please wait.")
        self.update()

        def _worker():
            try:
                concatenate(ffmpeg, input_paths, output_path)
                self.after(0, lambda: self._on_finished(output_path, error=None))
            except Exception as exc:
                self.after(0, lambda: self._on_finished(output_path, error=str(exc)))

        threading.Thread(target=_worker, daemon=True).start()

    def _on_finished(self, output_path: Path, error: str | None) -> None:
        self._done_btn.configure(state="normal")
        self._progress_label.configure(text="")
        if error:
            show_message(self, "Error", f"Concatenation failed:\n{error}")
        else:
            show_message(
                self, "Done",
                f"Concatenated video written to:\n{output_path}",
            )
            self.app.show_main_menu()
