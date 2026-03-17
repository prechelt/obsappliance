"""Shared GUI helpers: message boxes, file choosers, validation display."""

import customtkinter as ctk
from tkinter import filedialog

PADDING = 20  # ~2 em


def show_message(parent, title: str, message: str) -> None:
    """Modal message window with a single OK button."""
    dialog = ctk.CTkToplevel(parent)
    dialog.title(title)
    dialog.transient(parent)
    dialog.grab_set()
    dialog.resizable(False, False)

    ctk.CTkLabel(
        dialog, text=message, wraplength=400, justify="left",
    ).pack(padx=PADDING, pady=(PADDING, 10))

    ctk.CTkButton(dialog, text="OK", command=dialog.destroy).pack(
        padx=PADDING, pady=(0, PADDING),
    )
    dialog.wait_window()


def ask_confirmation(parent, title: str, message: str) -> bool:
    """Modal confirmation dialog.  Returns True on OK, False on Cancel."""
    result: list[bool] = [False]

    dialog = ctk.CTkToplevel(parent)
    dialog.title(title)
    dialog.transient(parent)
    dialog.grab_set()
    dialog.resizable(False, False)

    ctk.CTkLabel(
        dialog, text=message, wraplength=400, justify="left",
    ).pack(padx=PADDING, pady=(PADDING, 10))

    btn_frame = ctk.CTkFrame(dialog, fg_color="transparent")
    btn_frame.pack(padx=PADDING, pady=(0, PADDING))

    def on_ok():
        result[0] = True
        dialog.destroy()

    ctk.CTkButton(btn_frame, text="OK", command=on_ok).pack(side="left", padx=5)
    ctk.CTkButton(btn_frame, text="Cancel", command=dialog.destroy).pack(
        side="left", padx=5,
    )
    dialog.wait_window()
    return result[0]


def choose_save_file(parent, title: str = "Save As") -> str | None:
    """File-save dialog for MP4 files.  Returns path or None."""
    path = filedialog.asksaveasfilename(
        parent=parent,
        title=title,
        filetypes=[("MP4 files", "*.mp4"), ("All files", "*.*")],
        defaultextension=".mp4",
    )
    return path or None
