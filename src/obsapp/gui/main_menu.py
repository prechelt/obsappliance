"""Main menu screen."""

import customtkinter as ctk
from .widgets import PADDING, show_message

mainmenu_explanation="""
This small Python app uses OBS Studio and FFMpeg internally.

1. It allows you to record your desktop work on one entire monitor.
You can add microphone audio and/or a small webcam video of you want.
You can pause the recording at will.

2. Once done, you can "censor" a recording by excluding several time ranges.
If you take notes during the recording of clock times where you might want to do that
and a clock is visible in your recording, you can do that easily later.

3. If you stopped your recording prematurely and add a second recording (or several) later,
you can "concatenate" these recordings into one. Just list the files in the right order.
"""

class MainMenuFrame(ctk.CTkFrame):
    def __init__(self, parent, app):
        super().__init__(parent, fg_color="transparent")
        self.app = app

        ctk.CTkLabel(
            self,
            text=mainmenu_explanation,
            wraplength=400,
            justify="left",
        ).pack(padx=PADDING, pady=(PADDING, 10))

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

    def _on_action(self, choice: str) -> None:
        self._action_var.set("Select action...")  # reset for next time
        match choice:
            case "Record...":
                self.app.show_record_dialog()
            case "Upload video...":
                show_message(self, "Upload video", "Not implemented yet.")
            case "Exit":
                self.app.quit_app()
