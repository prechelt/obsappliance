"""FFmpeg-based video operations: censor, concatenate, text-frame generation.

All operations write to a sibling output file (e.g. "foo-censored.mp4" or
"foo-concat.mp4") and never touch the original.

FFmpeg is located in this order:
  1. OBS bundle  (<obsstudio_dir>/bin/ffmpeg or <obsstudio_dir>/bin/64bit/ffmpeg)
  2. System PATH
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path


# ---------------------------------------------------------------------------
# FFmpeg discovery
# ---------------------------------------------------------------------------

def find_ffmpeg(obsstudio_dir: Path | None = None) -> str:
    """Return path to an ffmpeg executable, raising FileNotFoundError if none found."""
    candidates: list[Path] = []

    if obsstudio_dir is not None:
        # OBS bundles ffmpeg inside its binary dirs on all platforms.
        if sys.platform == "win32":
            candidates += [
                obsstudio_dir / "bin" / "64bit" / "ffmpeg.exe",
                obsstudio_dir / "bin" / "ffmpeg.exe",
            ]
        elif sys.platform == "darwin":
            candidates += [
                obsstudio_dir / "Frameworks" / "ffmpeg",
                obsstudio_dir / "ffmpeg",
            ]
        else:
            candidates += [
                obsstudio_dir / "bin" / "ffmpeg",
                obsstudio_dir / "ffmpeg",
            ]

    for c in candidates:
        if c.exists():
            return str(c)

    # Fall back to PATH.
    import shutil
    exe = shutil.which("ffmpeg")
    if exe:
        return exe

    raise FileNotFoundError(
        "ffmpeg not found.  Install FFmpeg or place OBS Studio's bundled "
        "ffmpeg on PATH."
    )


# ---------------------------------------------------------------------------
# Video probing
# ---------------------------------------------------------------------------

def probe_video(ffmpeg_path: str, input_path: Path) -> dict:
    """Return a dict with keys: duration (float seconds), width, height, fps (float)."""
    ffprobe = _ffprobe_from_ffmpeg(ffmpeg_path)
    result = subprocess.run(
        [
            ffprobe,
            "-v", "quiet",
            "-print_format", "json",
            "-show_streams",
            "-show_format",
            str(input_path),
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe failed:\n{result.stderr}")
    data = json.loads(result.stdout)
    duration = float(data["format"]["duration"])
    video_stream = next(
        (s for s in data["streams"] if s["codec_type"] == "video"), None
    )
    if video_stream is None:
        raise RuntimeError(f"No video stream found in {input_path}")
    width = int(video_stream["width"])
    height = int(video_stream["height"])
    # fps from avg_frame_rate or r_frame_rate, e.g. "10/1"
    fps_raw = video_stream.get("avg_frame_rate") or video_stream.get("r_frame_rate", "10/1")
    num, den = fps_raw.split("/")
    fps = float(num) / float(den) if float(den) else 10.0
    return {"duration": duration, "width": width, "height": height, "fps": fps}


def _ffprobe_from_ffmpeg(ffmpeg_path: str) -> str:
    """Derive ffprobe path from ffmpeg path (same directory, sibling exe)."""
    p = Path(ffmpeg_path)
    if sys.platform == "win32":
        probe = p.parent / "ffprobe.exe"
    else:
        probe = p.parent / "ffprobe"
    if probe.exists():
        return str(probe)
    import shutil
    exe = shutil.which("ffprobe")
    if exe:
        return exe
    raise FileNotFoundError("ffprobe not found alongside ffmpeg or on PATH")


# ---------------------------------------------------------------------------
# Time parsing / formatting
# ---------------------------------------------------------------------------

_TIME_RE = re.compile(r"^(?:(\d+):)?(\d{1,2}):(\d{2})$")


def parse_time(s: str) -> float:
    """Parse "[[H:]M:]SS" → seconds as float.  Raises ValueError on bad format."""
    m = _TIME_RE.match(s.strip())
    if not m:
        raise ValueError(f"Invalid time format: {s!r}  (expected M:SS or H:MM:SS)")
    h = int(m.group(1)) if m.group(1) is not None else 0
    minutes = int(m.group(2))
    secs = int(m.group(3))
    return h * 3600 + minutes * 60 + secs


def format_time(seconds: float) -> str:
    """Format whole seconds as M:SS or H:MM:SS."""
    s = int(round(seconds))
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{sec:02d}"
    return f"{m}:{sec:02d}"


def parse_range(s: str) -> tuple[float, float]:
    """Parse "M:SS-M:SS" → (start, end) floats.  start < end required."""
    parts = s.strip().split("-")
    if len(parts) != 2:
        raise ValueError(f"Range must be two times separated by '-': {s!r}")
    start = parse_time(parts[0])
    end = parse_time(parts[1])
    if end <= start:
        raise ValueError(f"End time must be after start time: {s!r}")
    return start, end


# ---------------------------------------------------------------------------
# Censor operation  (use-case 2b)
# ---------------------------------------------------------------------------

def validate_censor_ranges(
    ranges_text: str, duration: float
) -> tuple[list[tuple[float, float, str]], list[str]]:
    """Parse and validate censor range text.

    Returns (ranges, errors) where ranges is a list of (start, end, original_str)
    sorted by start time, and errors is a list of human-readable error strings.
    """
    errors: list[str] = []
    ranges: list[tuple[float, float, str]] = []

    for lineno, raw_line in enumerate(ranges_text.splitlines(), 1):
        line = raw_line.strip()
        if not line:
            continue
        try:
            start, end = parse_range(line)
        except ValueError as exc:
            errors.append(f"Line {lineno}: {exc}")
            continue
        if start >= duration:
            errors.append(
                f"Line {lineno}: start {format_time(start)} is beyond video duration "
                f"({format_time(duration)})"
            )
            continue
        if end > duration:
            errors.append(
                f"Line {lineno}: end {format_time(end)} is beyond video duration "
                f"({format_time(duration)})"
            )
            continue
        ranges.append((start, end, line))

    if not errors:
        # Check for overlaps (after sorting by start).
        ranges.sort(key=lambda r: r[0])
        for i in range(1, len(ranges)):
            prev_end = ranges[i - 1][1]
            cur_start = ranges[i][0]
            if cur_start < prev_end:
                errors.append(
                    f"Ranges {ranges[i-1][2]!r} and {ranges[i][2]!r} overlap"
                )

    return ranges, errors


def censor(
    ffmpeg_path: str,
    input_path: Path,
    ranges: list[tuple[float, float, str]],
    output_path: Path,
    *,
    width: int,
    height: int,
    fps: float,
) -> None:
    """Remove ranges from the video, inserting a 1-second info frame for each.

    ranges must be sorted by start time and non-overlapping.
    Each censored range is replaced by a 1-second white frame with text
    "<range> deleted", then all pieces are concatenated.
    """
    info = probe_video(ffmpeg_path, input_path)
    total_duration = info["duration"]

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        segment_files: list[Path] = []
        seg_idx = 0

        # Walk through the timeline: keep → censor → keep → censor → … → keep
        cursor = 0.0
        for censor_start, censor_end, label in ranges:
            # Kept segment before this censored range (may be zero-length).
            if censor_start > cursor + 0.001:
                seg_path = tmp / f"seg_{seg_idx:04d}.mp4"
                _extract_segment(
                    ffmpeg_path, input_path, cursor, censor_start, seg_path,
                    width=width, height=height, fps=fps,
                )
                segment_files.append(seg_path)
                seg_idx += 1

            # Info frame replacing the censored range.
            frame_path = tmp / f"frame_{seg_idx:04d}.mp4"
            _make_text_frame(
                ffmpeg_path, f"{label} deleted",
                width=width, height=height, fps=fps,
                out_path=frame_path,
            )
            segment_files.append(frame_path)
            seg_idx += 1

            cursor = censor_end

        # Final kept segment after the last censored range.
        if total_duration > cursor + 0.001:
            seg_path = tmp / f"seg_{seg_idx:04d}.mp4"
            _extract_segment(
                ffmpeg_path, input_path, cursor, total_duration, seg_path,
                width=width, height=height, fps=fps,
            )
            segment_files.append(seg_path)

        # Concatenate all segments.
        _concat_segments(ffmpeg_path, segment_files, output_path)


def _extract_segment(
    ffmpeg_path: str,
    input_path: Path,
    start: float,
    end: float,
    out_path: Path,
    *,
    width: int,
    height: int,
    fps: float,
) -> None:
    duration = end - start
    cmd = [
        ffmpeg_path, "-y",
        "-ss", f"{start:.3f}",
        "-i", str(input_path),
        "-t", f"{duration:.3f}",
        "-vf", f"scale={width}:{height},fps={fps:.3f}",
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        "-c:a", "aac", "-b:a", "128k",
        "-movflags", "+faststart",
        str(out_path),
    ]
    _run(cmd)


def _make_text_frame(
    ffmpeg_path: str,
    text: str,
    *,
    width: int,
    height: int,
    fps: float,
    out_path: Path,
    duration: float = 1.0,
) -> None:
    """Generate a 1-second white frame with large black centred text."""
    # Escape text for FFmpeg drawtext filter.
    safe_text = text.replace("'", "\\'").replace(":", "\\:")
    fontsize = max(24, height // 12)
    cmd = [
        ffmpeg_path, "-y",
        "-f", "lavfi",
        "-i", f"color=white:size={width}x{height}:rate={fps:.3f}:duration={duration}",
        "-vf", (
            f"drawtext=text='{safe_text}':fontcolor=black:fontsize={fontsize}"
            f":x=(w-text_w)/2:y=(h-text_h)/2"
        ),
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        "-an",
        "-movflags", "+faststart",
        str(out_path),
    ]
    _run(cmd)


def _concat_segments(
    ffmpeg_path: str,
    segment_files: list[Path],
    output_path: Path,
) -> None:
    """Concatenate segment files using FFmpeg's concat demuxer."""
    if not segment_files:
        raise ValueError("No segments to concatenate")
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".txt", delete=False, encoding="utf-8"
    ) as flist:
        for seg in segment_files:
            # Paths in the concat list file must use forward slashes and be quoted.
            escaped = str(seg).replace("\\", "/").replace("'", "\\'")
            flist.write(f"file '{escaped}'\n")
        flist_path = flist.name
    try:
        cmd = [
            ffmpeg_path, "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", flist_path,
            "-c", "copy",
            "-movflags", "+faststart",
            str(output_path),
        ]
        _run(cmd)
    finally:
        Path(flist_path).unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Concatenate operation  (use-case 2c)
# ---------------------------------------------------------------------------

def validate_concat_inputs(
    input_paths: list[Path],
) -> list[str]:
    """Return a list of error strings (empty = all OK).

    Checks: all files exist.  (Resolution/codec/fps compatibility is checked
    later in concatenate() by probing; we normalise to a common format anyway,
    so we only validate existence here.)
    """
    errors = []
    for p in input_paths:
        if not p.exists():
            errors.append(f"File not found: {p}")
    return errors


def concatenate(
    ffmpeg_path: str,
    input_paths: list[Path],
    output_path: Path,
) -> None:
    """Concatenate videos, inserting a 1-second title frame before each part.

    The title frame shows the filename (not the full path) of the upcoming part.
    All inputs are re-encoded to a common resolution/fps (the first file's settings).
    """
    if not input_paths:
        raise ValueError("No input files provided")

    # Probe the first file to get target resolution and fps.
    info = probe_video(ffmpeg_path, input_paths[0])
    width, height, fps = info["width"], info["height"], info["fps"]

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        segment_files: list[Path] = []

        for idx, inp in enumerate(input_paths):
            # Title frame.
            title_text = inp.name
            frame_path = tmp / f"title_{idx:04d}.mp4"
            _make_text_frame(
                ffmpeg_path, title_text,
                width=width, height=height, fps=fps,
                out_path=frame_path,
            )
            segment_files.append(frame_path)

            # Re-encode the input to a normalised format.
            seg_path = tmp / f"part_{idx:04d}.mp4"
            _extract_segment(
                ffmpeg_path, inp, 0.0,
                probe_video(ffmpeg_path, inp)["duration"],
                seg_path,
                width=width, height=height, fps=fps,
            )
            segment_files.append(seg_path)

        _concat_segments(ffmpeg_path, segment_files, output_path)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _run(cmd: list[str]) -> None:
    """Run an FFmpeg command, raising RuntimeError on failure."""
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(
            f"FFmpeg command failed (exit {result.returncode}):\n"
            f"Command: {' '.join(cmd)}\n"
            f"Stderr: {result.stderr[-2000:]}"
        )
