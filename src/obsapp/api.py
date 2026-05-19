"""Programmatic entry points for OBSapp.

Wraps :class:`OBSController` and :mod:`video_ops` into use-case-level
operations that mirror the GUI flows (record, censor, concatenate) but
require no Tk display.

Used by:

* the GUI dialogs — so the orchestration logic is not tied to widget callbacks
* the integration test harness — drives the appliance without simulating clicks

The contract for every method here is plain Python:

* arguments are values (paths, names, strings) — no widget references
* failures raise ``ValueError`` / ``FileNotFoundError`` / ``RuntimeError`` with
  a human-readable message; no message-box side effects
* operations are synchronous; threading is the caller's concern
"""

from __future__ import annotations

import configparser
import time
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar

from .constants import (
    PIP_SCREEN_MARGIN,
    PIP_SIZE_SMALL,
    PIP_WEBCAM_ASPECT,
)
from .obs_control import OBSController
from .video_ops import (
    censor as _censor_op,
    concatenate as _concat_op,
    find_ffmpeg,
    probe_video,
    validate_censor_ranges,
    validate_concat_inputs,
)

# Subdirectory inside the obsapp directory where OBS profile/scene/websocket
# config is written.  Mirrors main._OBS_CONFIG_SUBDIR.
_OBS_CONFIG_SUBDIR = "obs-config"


# ── PiP configuration ─────────────────────────────────────────────────────

@dataclass
class PiPConfig:
    """Webcam picture-in-picture overlay settings for a recording session.

    ``position`` is one of the nine grid strings: ``"top-left"``,
    ``"top-center"``, ``"top-right"``, ``"middle-left"``, ``"middle-center"``,
    ``"middle-right"``, ``"bottom-left"``, ``"bottom-center"``,
    ``"bottom-right"``.

    ``size`` is one of ``"small"``, ``"medium"``, ``"large"``, mapping to the
    ``PIP_SIZE_*`` constants (recorded-resolution pixels).
    """

    position: str = "middle-right"
    size: int = PIP_SIZE_SMALL

    _VALID_POSITIONS: ClassVar[frozenset[str]] = frozenset({
        "top-left",    "top-center",    "top-right",
        "middle-left", "middle-center", "middle-right",
        "bottom-left", "bottom-center", "bottom-right",
    })

    def __post_init__(self) -> None:
        if self.position not in self._VALID_POSITIONS:
            raise ValueError(f"Invalid PiP position: {self.position!r}")
        if not isinstance(self.size, int) or self.size <= 0:
            raise ValueError(f"PiP size must be a positive integer, got {self.size!r}")


def _pip_webcam_transform(
    pip: PiPConfig,
    canvas_w: int,
    canvas_h: int,
) -> tuple[int, int, int, int]:
    """Return OBS canvas ``(x, y, w, h)`` for the webcam PiP overlay.

    ``canvas_w`` / ``canvas_h`` are the monitor's native pixel dimensions,
    which equal the OBS canvas size set via :meth:`Session.start_recording`.

    Width is forced to ``pip.size * PIP_WEBCAM_ASPECT`` (16:9) so the bounding
    box is always the right shape regardless of the physical webcam's AR.
    OBS ``OBS_BOUNDS_SCALE_INNER`` then fits the real webcam stream inside it.
    """
    pip_h = pip.size
    pip_w = round(pip_h * PIP_WEBCAM_ASPECT)

    row, col = pip.position.split("-")

    if col == "left":
        x = PIP_SCREEN_MARGIN
    elif col == "center":
        x = (canvas_w - pip_w) // 2
    else:  # right
        x = canvas_w - pip_w - PIP_SCREEN_MARGIN

    if row == "top":
        y = PIP_SCREEN_MARGIN
    elif row == "middle":
        y = (canvas_h - pip_h) // 2
    else:  # bottom
        y = canvas_h - pip_h - PIP_SCREEN_MARGIN

    return (x, y, pip_w, pip_h)


# ── configuration loading ─────────────────────────────────────────────────

def load_config(inifile: str | Path) -> dict[str, str]:
    """Parse an obsapp .ini file and return its entries as a flat dict.

    Raises FileNotFoundError if the file does not exist or is not an .ini.
    Raises ValueError if required keys are missing.
    """
    path = Path(inifile)
    if path.suffix != ".ini" or not path.exists():
        raise FileNotFoundError(f"{inifile!r} is not an existing .ini file.")
    parser = configparser.ConfigParser()
    parser.read(path)
    result: dict[str, str] = {}
    for section in parser.sections():
        for key, value in parser.items(section):
            result[key] = value
    missing = [k for k in ("obs_executable", "ffmpeg_executable") if k not in result]
    if missing:
        raise ValueError(
            "Missing entries in .ini file: " + ", ".join(missing)
        )
    return result


def obs_config_dir_for(inifile: str | Path) -> Path:
    """Return the OBS config directory associated with the given .ini file."""
    return Path(inifile).resolve().parent / _OBS_CONFIG_SUBDIR


# ── Session: the high-level appliance API ─────────────────────────────────

class Session:
    """High-level OBSapp operations: device discovery, recording, video editing.

    Typical use::

        cfg = load_config("obsapp-config.ini")
        with Session(cfg, obs_config_dir_for("obsapp-config.ini")) as s:
            s.start_obs()
            mons = s.list_monitors()
            s.start_recording(
                monitor_name=mons[0][0], mic_name=None, webcam_name=None,
                target_path=Path("recording1.mp4"),
            )
            time.sleep(5)
            s.pause_recording(); time.sleep(2); s.resume_recording()
            time.sleep(3)
            out = s.stop_recording()
            s.censor_video(out, "0:03-0:04")

    The session owns an :class:`OBSController`; ``__exit__`` stops OBS so a
    failing test never leaves OBS running.
    """

    def __init__(self, cfg: dict[str, str], obs_config_dir: Path) -> None:
        self.cfg = cfg
        self.ffmpeg_executable: str = cfg["ffmpeg_executable"]
        self.obs = OBSController(
            obs_executable=cfg["obs_executable"],
            obs_config_dir=obs_config_dir,
        )
        # Set by start_recording(); consumed by stop_recording() to rename
        # OBS's auto-named output file to the caller's chosen target.
        self._target_path: Path | None = None

    # ── lifecycle / context manager ───────────────────────────────────

    def start_obs(self) -> None:
        """Start OBS Studio (idempotent)."""
        self.obs.start()

    def stop_obs(self) -> None:
        """Stop OBS Studio cleanly (idempotent)."""
        self.obs.stop()

    def __enter__(self) -> "Session":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.stop_obs()

    # ── device discovery ──────────────────────────────────────────────

    def list_monitors(self) -> list[tuple[str, str, int, int]]:
        """Return [(display_name, device_value, width, height), ...]."""
        return self.obs.get_monitors()

    def list_microphones(self) -> list[tuple[str, str]]:
        """Return [(friendly_name, device_id), ...]."""
        return self.obs.get_microphones()

    def list_webcams(self) -> list[tuple[str, str]]:
        """Return [(friendly_name, device_id), ...]."""
        return self.obs.get_webcams()

    # ── recording (use-case 2a) ───────────────────────────────────────

    def start_recording(
        self,
        *,
        monitor_name: str,
        mic_name: str | None,
        webcam_name: str | None,
        target_path: Path,
        pip: PiPConfig | None = None,
    ) -> None:
        """Configure OBS sources for the named devices and start recording.

        ``monitor_name`` must match a name returned by :meth:`list_monitors`.
        ``mic_name`` / ``webcam_name`` may be ``None`` to omit that input.
        ``pip`` configures the webcam overlay position and size; ignored when
        ``webcam_name`` is ``None``.

        OBS writes the recording into ``target_path.parent`` with an
        auto-generated filename; :meth:`stop_recording` renames it to
        ``target_path``.
        """
        # Resolve monitor name → device value + native resolution.
        monitors = {n: (v, w, h) for n, v, w, h in self.list_monitors()}
        if monitor_name not in monitors:
            raise ValueError(
                f"Unknown monitor: {monitor_name!r}.  "
                f"Available: {sorted(monitors)}"
            )
        mon_val, mon_w, mon_h = monitors[monitor_name]

        # Resolve microphone name → device id (None = no audio).
        mic_val: str | None = None
        if mic_name is not None:
            mic_map = dict(self.list_microphones())
            if mic_name not in mic_map:
                raise ValueError(
                    f"Unknown microphone: {mic_name!r}.  "
                    f"Available: {sorted(mic_map)}"
                )
            mic_val = mic_map[mic_name] or None  # empty string → no audio

        # Resolve webcam name → device id (None = no webcam).
        webcam_val: str | None = None
        if webcam_name is not None:
            cam_map = dict(self.list_webcams())
            if webcam_name not in cam_map:
                raise ValueError(
                    f"Unknown webcam: {webcam_name!r}.  "
                    f"Available: {sorted(cam_map)}"
                )
            webcam_val = cam_map[webcam_name] or None

        # Compute webcam transform if pip config provided.
        webcam_transform: tuple[int, int, int, int] | None = None
        if webcam_val is not None and pip is not None:
            webcam_transform = _pip_webcam_transform(pip, mon_w, mon_h)

        target_path = Path(target_path)
        target_path.parent.mkdir(parents=True, exist_ok=True)

        # OBS resolves relative recording paths against its own CWD (the OBS
        # binary directory), which is typically not writable and triggers
        # "the configured recording path could not be opened".  Always pass an
        # absolute path so OBS opens the directory the caller intended.
        output_dir = str(target_path.parent.resolve())

        self.obs.setup_recording(
            monitor_value=mon_val,
            monitor_resolution=(mon_w, mon_h),
            mic_value=mic_val,
            webcam_value=webcam_val,
            webcam_transform=webcam_transform,
            output_dir=output_dir,
        )
        self.obs.start_recording()
        self._target_path = target_path

    def pause_recording(self) -> None:
        self.obs.pause_recording()

    def resume_recording(self) -> None:
        self.obs.resume_recording()

    def stop_recording(self) -> Path:
        """Stop the active recording and return the final file path.

        If the caller specified a target path in :meth:`start_recording`,
        OBS's auto-named output is renamed to it (with retry while OBS still
        holds the file handle).  Otherwise the OBS-auto-named path is returned.
        """
        actual_str = self.obs.stop_recording()
        target = self._target_path
        self._target_path = None

        if not actual_str:
            if target is None:
                raise RuntimeError(
                    "Recording stopped but OBS returned no output path "
                    "and no target was set."
                )
            return target

        actual = Path(actual_str)
        if target is None or actual == target:
            return actual

        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            target.unlink()
        _rename_with_retry(actual, target)
        return target

    # ── censor (use-case 2b) ──────────────────────────────────────────

    def censor_video(
        self,
        input_path: Path,
        ranges_text: str,
        output_path: Path | None = None,
    ) -> Path:
        """Censor an MP4 file.

        ``ranges_text`` is one ``M:SS-M:SS`` (or ``H:MM:SS-H:MM:SS``) range
        per line.  The output is written to ``<stem>-censored.mp4`` next to
        the input by default.

        Returns the path of the produced file.  Raises ValueError if any
        range is invalid or empty.
        """
        input_path = Path(input_path)
        if not input_path.exists():
            raise FileNotFoundError(input_path)
        ffmpeg = find_ffmpeg(self.ffmpeg_executable)
        info = probe_video(ffmpeg, input_path)
        ranges, errors = validate_censor_ranges(ranges_text, info["duration"])
        if errors:
            raise ValueError("Invalid censor ranges:\n" + "\n".join(errors))
        if not ranges:
            raise ValueError("No censor ranges given.")
        if output_path is None:
            output_path = input_path.with_stem(input_path.stem + "-censored")
        _censor_op(
            ffmpeg, input_path, ranges, output_path,
            width=info["width"], height=info["height"], fps=info["fps"],
        )
        return output_path

    # ── concatenate (use-case 2c) ─────────────────────────────────────

    def concatenate_videos(
        self,
        input_paths: list[Path],
        output_path: Path,
    ) -> Path:
        """Concatenate MP4 files into ``output_path``.

        Each part is preceded by a short title frame showing its filename.
        Returns ``output_path``.
        """
        paths = [Path(p) for p in input_paths]
        errors = validate_concat_inputs(paths)
        if errors:
            raise ValueError("Invalid concat inputs:\n" + "\n".join(errors))
        ffmpeg = find_ffmpeg(self.ffmpeg_executable)
        _concat_op(ffmpeg, paths, Path(output_path))
        return Path(output_path)

    # ── miscellaneous ─────────────────────────────────────────────────

    def probe(self, video_path: Path) -> dict:
        """Return ffprobe info: ``{duration, width, height, fps}``."""
        return probe_video(find_ffmpeg(self.ffmpeg_executable), Path(video_path))


# ── private helpers ───────────────────────────────────────────────────────

def _rename_with_retry(
    src: Path,
    dst: Path,
    timeout: float = 10.0,
    interval: float = 0.5,
) -> None:
    """Rename ``src`` to ``dst``, retrying on PermissionError up to ``timeout`` s.

    OBS finalises MP4 files on a background thread after stop_record() returns,
    so the file handle may still be open briefly.  On Windows this manifests
    as ``[WinError 32]`` (file in use).
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
