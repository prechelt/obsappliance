# AGENTS.md — OBSapp coding agent instructions

## Repository overview

OBSapp is a Python/CustomTkinter GUI appliance that drives OBS Studio via
obs-websocket to screen-record, censor, and concatenate videos.
Source lives under `src/obsapp/`; the package is installed via Poetry.

---

## Environment setup

```powershell
# Windows development (PowerShell)
cd C:\ws\gh\obsappliance
C:\venv\obsapp\Scripts\Activate.ps1
```

```bash
# Run the app (Git Bash / Linux / macOS)
PYTHONPATH=src python -m obsapp.main tmp_obsappdir/obsapp-config.ini
```

The `obsapp-config.ini` must contain at minimum:

```ini
[obsappliance]
obsstudio_dir=C:\Program Files\obs-studio
```

---

## Build and install

```bash
# Install in editable mode (Poetry)
pip install -e .

# Or with Poetry directly
poetry install
```

There is no compiled step; the package is pure Python.

---

## Lint and type-check

No linter or formatter is configured in `pyproject.toml` yet.
When adding tooling, prefer **ruff** for linting/formatting and **mypy** for
type-checking.  Proposed invocations (once configured):

```bash
ruff check src/
ruff format src/
mypy src/
```

Until tooling is configured, follow the style conventions below manually.

---

## Tests

There is no test suite yet.  When adding tests, place them under `tests/` and
use **pytest**:

```bash
# Run all tests
pytest

# Run a single test file
pytest tests/test_video_ops.py

# Run a single test function
pytest tests/test_video_ops.py::test_parse_time_valid
```

Modules that are safe to unit-test without a running OBS instance:
`video_ops.py`, `config.py`, `os_specifics.py`, `gui/widgets.py`.
`obs_control.py` and GUI frames require a running OBS / Tk display and are
better covered by integration/manual tests.

---

## Module structure

```
src/obsapp/
  main.py            — entry point, App (CTk) lifecycle, frame switching
  config.py          — JSON persistence of record dialog defaults
  obs_control.py     — OBS process lifecycle, websocket control, device enum
  os_specifics.py    — native OS device enumeration (monitors, mics, webcams)
  video_ops.py       — FFmpeg operations: censor, concatenate, text frames
  gui/
    main_menu.py     — MainMenuFrame: explanation label + action dropdown
    record_dialog.py — RecordDialogFrame (config) + RecordingFrame (controls)
    censor_dialog.py — CensorDialogFrame
    concat_dialog.py — ConcatDialogFrame
    widgets.py       — MarkupLabel, show_message, ask_confirmation, choose_save_file
```

Dependency rule: `obs_control`, `video_ops`, `config` must not import from
`gui` or from each other.  All cross-cutting imports flow downward from
`main.py` → `gui/*` → backend modules.

---

## Code style

### General

- **Python 3.10+**; use match/case, `X | Y` union syntax, `list[T]` / `dict[K,V]`
  built-in generics (no `from __future__ import annotations` needed except in
  `video_ops.py` where it is already present).
- Line length: soft limit ~88 characters (ruff default); never exceed 100.
- No trailing whitespace; Unix line endings.

### Imports

Standard order (PEP 8): stdlib → third-party → local.  One blank line between
groups.  Absolute imports only (`from obsapp.gui.widgets import …`).
Lazy imports inside functions are acceptable when they are platform-specific or
avoid circular imports (see `os_specifics.py` — `import ctypes` inside
each function).

```python
# Good
import json
import sys
from pathlib import Path

import customtkinter as ctk
import obsws_python as obsws

from .widgets import PADDING, show_message
```

### Type annotations

All public functions and methods must have full type annotations.
Private helpers (`_foo`) should be annotated when non-obvious.
Use `str | None` (not `Optional[str]`).  Prefer `Path` over `str` for
filesystem paths in function signatures.

```python
def find_ffmpeg(obsstudio_dir: Path | None = None) -> str: ...
def parse_range(s: str) -> tuple[float, float]: ...
```

### Naming

| Entity | Convention | Example |
|---|---|---|
| Module-level constant | `UPPER_SNAKE` | `_SCENE_NAME`, `PADDING` |
| Private module symbol | `_lower_snake` | `_SOURCE_TYPES`, `_run()` |
| Class | `PascalCase` | `OBSController`, `MarkupLabel` |
| Method / function | `lower_snake` | `setup_recording()`, `_sync_bg()` |
| GUI callback | `_on_<event>` | `_on_record()`, `_on_action()` |
| tk/CTk internal widget | `self._foo` | `self._file_entry`, `self._monitor_var` |

### Docstrings

Module docstring: one-line summary on the first line.  Mention key public API
or non-obvious constraints.  No reStructuredText or Google-style sections
unless the function is genuinely complex.

```python
"""JSON persistence of user settings (record dialog defaults)."""
```

Function/method docstrings: single line is fine for simple functions.
Multi-line: blank line after summary, then prose.  No `:param:` tags.

### Error handling

- Raise specific built-in exceptions (`ValueError`, `FileNotFoundError`,
  `RuntimeError`, `ConnectionError`) with a human-readable message.
- Swallow exceptions silently only when the failure is genuinely non-fatal and
  explained by an inline comment (e.g. `remove_input` returning 600 when the
  source doesn't exist yet).
- GUI callbacks catch `Exception` broadly and surface errors via
  `show_message(self, "Error", str(exc))` — never let an unhandled exception
  silently swallow user-visible failures.

```python
# Good — non-fatal, explained
try:
    self.ws.remove_input(name)
except Exception:
    pass  # code 600 = not found; safe to ignore on first run

# Good — fatal, descriptive
raise FileNotFoundError("OBS Studio not found in Program Files")
```

### GUI conventions

- All frames inherit from `ctk.CTkFrame` with `fg_color="transparent"`.
- Use `PADDING = 20` (from `widgets.py`) as the standard window margin.
- All frames are swapped via `App._show_frame()`; they must not manage their
  own window lifecycle.
- Use `self.after(0, callback)` to defer any measurement that requires a
  realized widget (font metrics, `winfo_reqheight`, etc.).
- When calling `app.minsize(w, h)` always pass **both** arguments; CTk's
  override crashes on `None` comparisons if one is omitted.
- `font.measure()` returns **screen pixels** (DPI-scaled).  CTk `minsize()`
  takes **logical pixels**.  Divide by `app._get_window_scaling()` before
  passing to `minsize`.
- `tk.Text` used as a label: set `font="TkDefaultFont"` explicitly (avoids
  the `TkFixedFont`/Courier default), derive background from
  `self.winfo_toplevel().cget("background")` (not `self.master`).

### Section separators

Use `# ── section name ──────` (em-dash style) for logical sections within a
module, matching the existing codebase style:

```python
# ── recording control ─────────────────────────────────────────────
```

Use `# ---------------------------------------------------------------------------`
(75 dashes) for top-level sections inside larger modules (`video_ops.py`).

---

## OBS / websocket notes

- OBS websocket runs on `localhost:4455`, no password (`auth_required=false`).
- Error code 600 = source not found (safe to ignore in cleanup).
- Error code 601 = already exists (safe to ignore for scene creation).
- `monitor_capture` on Windows uses property key `monitor_id` with a GDI
  device name value (e.g. `\\.\DISPLAY1`).
- `dshow_input` on Windows uses property key `video_device_id` with the
  DirectShow `DevicePath` string.
- Always sleep ~2 s after `create_input` calls before `start_record()` to
  allow capture devices to initialise.
- Send `WM_CLOSE` only to windows whose title starts with `"OBS"` —
  not to all process windows — to allow OBS's clean-shutdown path to run and
  remove its sentinel directory.
