"""Main menu screen."""

import customtkinter as ctk
from .widgets import PADDING, show_message


class MainMenuFrame(ctk.CTkFrame):
    def __init__(self, parent, app):
        super().__init__(parent, fg_color="transparent")
        self.app = app

        ctk.CTkLabel(
            self,
            text="((explanation here))",
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
            case "Concatenate videos..." | "Censor video...":
                show_message(self, choice.rstrip("."), "Not implemented yet.")
            case "Exit":
                self.app.quit_app()
