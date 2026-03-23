"""Shared GUI helpers: message boxes, file choosers, validation display."""

import re
import tkinter as tk
from tkinter.font import Font

import customtkinter as ctk
from tkinter import filedialog

PADDING = 20  # ~2 em


# ---------------------------------------------------------------------------
# MarkupLabel
# ---------------------------------------------------------------------------

def _parse_markup(text: str) -> list[tuple[str, tuple[str, ...]]]:
    """Parse **bold** and _italic_ markers into a list of (run, tags) pairs.

    Markers may not nest.  An unmatched marker is emitted as literal text.
    Supported tags: "bold", "italic".
    """
    # Pattern matches **…** or _…_ (non-greedy, single-line spans only).
    TOKEN = re.compile(r'\*\*(.+?)\*\*|_(.+?)_', re.DOTALL)
    runs: list[tuple[str, tuple[str, ...]]] = []
    pos = 0
    for m in TOKEN.finditer(text):
        if m.start() > pos:
            runs.append((text[pos:m.start()], ()))
        if m.group(1) is not None:          # **bold**
            runs.append((m.group(1), ("bold",)))
        else:                               # _italic_
            runs.append((m.group(2), ("italic",)))
        pos = m.end()
    if pos < len(text):
        runs.append((text[pos:], ()))
    return runs


def _plain_text(text: str) -> str:
    """Strip markup markers, leaving only the displayable characters."""
    return re.sub(r'\*\*(.+?)\*\*|_(.+?)_', lambda m: m.group(1) or m.group(2),
                  text, flags=re.DOTALL)


class MarkupLabel(tk.Text):
    """A read-only text widget that renders **bold** and _italic_ inline markup.

    Visually equivalent to a plain label: no border, no cursor, not editable.
    Use like a normal widget — pack/grid it normally.  The *markup_text*
    argument accepts the raw string including ** and _ markers.
    """

    def __init__(self, parent: tk.Widget, markup_text: str, **kwargs):
        # Pull out any geometry kwargs; pass the rest to tk.Text.
        kwargs.setdefault("relief", "flat")
        kwargs.setdefault("borderwidth", 0)
        kwargs.setdefault("highlightthickness", 0)
        kwargs.setdefault("wrap", "none")
        kwargs.setdefault("cursor", "")
        # Use the same font family/size that CTkLabel and CTkButton use.
        # ctk.CTkFont() with no arguments resolves to CTk's configured default
        # (Roboto, scaled to the display), matching every other widget in the app.
        # Use cget("size") (the CTk logical size, e.g. 13) rather than
        # actual("size") (Tk's scaled points, e.g. 10) so the pixel size matches.
        _ctk_font = ctk.CTkFont()
        _family = _ctk_font.actual("family")
        _size   = _ctk_font.cget("size")
        kwargs.setdefault("font", Font(family=_family, size=_size))
        # We will set width/height after measuring; start at 1 to avoid
        # Tk allocating a huge default canvas.
        kwargs.setdefault("width", 1)
        kwargs.setdefault("height", 1)
        super().__init__(parent, **kwargs)

        self._markup_text = markup_text

        # Derive bold / italic fonts from the base font set above.
        self.tag_configure("bold",   font=Font(family=_family, size=_size, weight="bold"))
        self.tag_configure("italic", font=Font(family=_family, size=_size, slant="italic"))

        # Insert content.
        self._render(markup_text)

        # Measure and fix widget dimensions so it behaves like a label.
        self._fix_size()

        # Disable editing.
        self.configure(state="disabled")

        # Match parent background dynamically (handles theme changes).
        self.bind("<Configure>", self._sync_bg, add="+")
        self._sync_bg()

    # ── private ──────────────────────────────────────────────────────────

    def _render(self, markup_text: str) -> None:
        self.configure(state="normal")
        self.delete("1.0", "end")
        for run, tags in _parse_markup(markup_text):
            self.insert("end", run, tags)
        self.configure(state="disabled")

    def _fix_size(self) -> None:
        """Fix widget dimensions to exactly fit the content."""
        plain = _plain_text(self._markup_text)
        lines = plain.splitlines()
        # height in lines
        self.configure(height=len(lines))
        # width in characters: measure the longest line in pixels, convert to
        # average character widths so Tk allocates exactly that much horizontal
        # space.  This prevents the text widget from advertising a natural width
        # of zero (width=1) while wrap="none" — which makes Tk expand the window
        # to show the full unwrapped text regardless of any geometry() call.
        font = Font(font=self.cget("font"))
        longest_px = max((font.measure(l) for l in lines), default=0)
        avg_char_px = font.measure("0")
        if avg_char_px > 0:
            self.configure(width=max(1, longest_px // avg_char_px))

    def _sync_bg(self, _event=None) -> None:
        # The CTk top-level window holds the authoritative background color.
        # Walking up only one level (self.master) reaches a CTkFrame whose
        # underlying tk background is SystemButtonFace, not the window gray.
        try:
            bg = self.winfo_toplevel().cget("background")
        except Exception:
            return
        self.configure(background=bg, selectbackground=bg, inactiveselectbackground=bg)

    # ── public ───────────────────────────────────────────────────────────

    def longest_line_px(self) -> int:
        """Return the pixel width of the longest plain-text line."""
        font = Font(font=self.cget("font"))
        plain = _plain_text(self._markup_text)
        return max((font.measure(line) for line in plain.splitlines()), default=0)


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
