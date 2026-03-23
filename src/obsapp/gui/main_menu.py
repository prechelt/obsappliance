"""Main menu screen."""

from __future__ import annotations

from typing import TYPE_CHECKING

import customtkinter as ctk

from .widgets import PADDING, MarkupLabel, show_message

if TYPE_CHECKING:
    from ..main import App

MAINMENU_EXPLANATION = """
This small Python app uses OBS Studio and FFMpeg internally.

**1.** It allows you to **record your desktop work** on one entire monitor.
You can add _microphone audio_ and/or a _small webcam video_ if you want.
You can _pause_ the recording at will.

**2.** Once done, you can **censor a recording** by excluding several time ranges.
If you _take notes_ during the recording of clock times where you might want to do that
and a clock is visible in your recording, you can do that easily later.

**3.** If you stopped your recording prematurely and add a second recording (or several) later,
you can **concatenate** these recordings into one. Just list the files in the right order.
"""

class MainMenuFrame(ctk.CTkFrame):
    def __init__(self, parent: ctk.CTkFrame, app: App) -> None:
        super().__init__(parent, fg_color="transparent")
        self.app = app

        self._explanation_label = MarkupLabel(
            self,
            markup_text=MAINMENU_EXPLANATION,
        )
        self._explanation_label.pack(padx=PADDING, pady=(PADDING, 10), fill="x")

        self._action_var = ctk.StringVar(value="Select action...")
        ctk.CTkOptionMenu(
            self,
            variable=self._action_var,
            values=[
                "Record...",
                "Concatenate videos...",
                "Censor video...",
                "Upload video...",
                "Exit",
            ],
            command=self._on_action,
        ).pack(padx=PADDING, pady=(0, PADDING))

        self.after(0, self._fit_width_to_explanation)

    def _fit_width_to_explanation(self) -> None:
        """Set window minsize so no line in the explanation wraps."""
        longest_screen_px = self._explanation_label.longest_line_px()
        # font.measure() returns screen pixels; CTk minsize() takes logical
        # pixels (it multiplies by the window scaling factor internally).
        scaling = self.app._get_window_scaling()
        min_w = int(longest_screen_px / scaling) + 2 * PADDING
        min_h = self.app.winfo_reqheight()
        self.app.minsize(min_w, min_h)

    def _on_action(self, choice: str) -> None:
        self._action_var.set("Select action...")  # reset for next time
        match choice:
            case "Record...":
                self.app.show_record_dialog()
            case "Censor video...":
                self.app.show_censor_dialog()
            case "Concatenate videos...":
                self.app.show_concat_dialog()
            case "Upload video...":
                show_message(self, "Upload video", "Not implemented yet.")
            case "Exit":
                self.app.quit_app()
