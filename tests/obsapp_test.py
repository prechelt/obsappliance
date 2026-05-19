"""System-level integration test for obsapp.

Drives :class:`obsapp.api.Session` through a full Record → Censor flow on a
real OBS Studio installation and validates the timing of the resulting MP4.

A small Tk **Timer window** is spawned as a *subprocess* (so the driver and
the Timer never share a Tk main loop) and placed in the upper-left of the
captured monitor.  It displays:

* a magenta sentinel border (for auto-localization in extracted frames),
* a 16-bit barcode of centiseconds since a shared ``anchor`` epoch
  (white = 0, black = 1, MSB on the left),
* the same value as human-readable ``M:SS.S`` digits (visual debugging only;
  the test relies on the barcode).

After recording, the test extracts every frame with one ffmpeg invocation,
decodes the barcode at sampled video times, and reports start delay, pause
jump, and overall duration deltas.

Usage (driver)::

    PYTHONPATH=src python tests/obsapp_test.py tmp_obsappdir/obsapp-config.ini

Usage (timer subprocess; spawned automatically, do not call directly)::

    python tests/obsapp_test.py --timer-window X Y W H ANCHOR_EPOCH

Designed for **manual developer use**, not CI: requires a live OBS Studio,
visible screen (not locked), and at least one monitor.  Microphone and webcam
are optional and are skipped if absent.
"""

import argparse
import json
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

# Make the obsapp package importable when running from a source checkout.
_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC_DIR = _REPO_ROOT / "src"
if _SRC_DIR.exists() and str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))


# ── Barcode geometry (encoder and decoder must agree) ─────────────────────

BARCODE_BITS = 16            # 65 535 cs ≈ 655 s, plenty for a 10-s test
BORDER_PX = 12               # magenta sentinel border thickness
BARCODE_HEIGHT = 80          # px, inner barcode strip
DIGIT_HEIGHT = 60            # px, inner digit strip
TIMER_INNER_W = 640
TIMER_W = TIMER_INNER_W + 2 * BORDER_PX
TIMER_H = BARCODE_HEIGHT + DIGIT_HEIGHT + 2 * BORDER_PX
MAGENTA = "#FF00FF"


# ── Timer subprocess ──────────────────────────────────────────────────────

def run_timer(x: int, y: int, w: int, h: int, anchor: float) -> None:
    """Run the Tk Timer window. Blocks until the parent kills the process."""
    import tkinter as tk

    # The driver enumerates monitors with Per-Monitor DPI Aware v2, so the
    # (x, y, w, h) we receive are *physical* pixels.  Tk's ``geometry`` takes
    # logical pixels by default, which on a DPI-scaled multi-monitor desktop
    # places the window in the wrong spot (sometimes off-screen).  Mark this
    # process Per-Monitor DPI Aware v2 *before* creating the Tk root so Tk's
    # geometry coordinates are also physical pixels.
    if sys.platform == "win32":
        try:
            import ctypes
            user32 = ctypes.windll.user32
            set_ctx = getattr(user32, "SetProcessDpiAwarenessContext", None)
            if set_ctx is not None:
                set_ctx.restype = ctypes.c_bool
                set_ctx.argtypes = [ctypes.c_void_p]
                # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = -4
                if not set_ctx(ctypes.c_void_p(-4)):
                    # Fall back to Per-Monitor v1 on older Windows 10 builds.
                    set_ctx(ctypes.c_void_p(-3))
            else:
                # Pre-1607 fallback: process-wide System DPI Aware.
                shcore = getattr(ctypes.windll, "shcore", None)
                if shcore is not None:
                    shcore.SetProcessDpiAwareness(2)  # PROCESS_PER_MONITOR_DPI_AWARE
                else:
                    user32.SetProcessDPIAware()
        except Exception:
            pass

    root = tk.Tk()
    root.overrideredirect(True)
    root.geometry(f"{w}x{h}+{x}+{y}")
    root.configure(bg=MAGENTA)
    root.attributes("-topmost", True)

    inner_w = w - 2 * BORDER_PX
    inner_h = h - 2 * BORDER_PX
    cell_w = inner_w / BARCODE_BITS

    canvas = tk.Canvas(
        root, width=inner_w, height=inner_h, bg="white", highlightthickness=0,
    )
    canvas.place(x=BORDER_PX, y=BORDER_PX)

    cells = []
    for i in range(BARCODE_BITS):
        cx0 = i * cell_w
        cx1 = (i + 1) * cell_w
        rect = canvas.create_rectangle(
            cx0, 0, cx1, BARCODE_HEIGHT,
            fill="white", outline="",
        )
        cells.append(rect)

    digit_id = canvas.create_text(
        inner_w / 2,
        BARCODE_HEIGHT + DIGIT_HEIGHT / 2,
        text="0:00.0",
        font=("Courier New", 36, "bold"),
        fill="black",
    )

    def update() -> None:
        elapsed_cs = max(0, int(round((time.time() - anchor) * 100)))
        # Wrap into the bit field if the test runs longer than expected.
        v = elapsed_cs & ((1 << BARCODE_BITS) - 1)
        for i in range(BARCODE_BITS):
            bit = (v >> (BARCODE_BITS - 1 - i)) & 1
            canvas.itemconfig(cells[i], fill="black" if bit else "white")
        secs = elapsed_cs / 100.0
        m = int(secs // 60)
        s = secs - 60 * m
        canvas.itemconfig(digit_id, text=f"{m}:{s:04.1f}")
        root.after(50, update)

    update()
    # Force initial paint before announcing readiness.
    root.update_idletasks()
    root.update()
    print("TIMER_READY", flush=True)
    root.mainloop()


# ── Barcode decoding (pure PIL, no numpy) ─────────────────────────────────

def decode_barcode(image_path: Path) -> int | None:
    """
    Decoded centisecond value, or None if the sentinel was not found.
    16-bit barcode: will wrap around after 655 seconds!
    """
    from PIL import Image, ImageChops, ImageFilter

    img = Image.open(image_path).convert("RGB")
    r, g, b = img.split()
    # Magenta = high R, low G, high B.  Tolerances are generous enough to
    # survive low-bitrate libx264 at 8 fps.
    r_mask = r.point(lambda v: 255 if v > 180 else 0)
    g_mask = g.point(lambda v: 255 if v < 100 else 0)
    b_mask = b.point(lambda v: 255 if v > 180 else 0)
    mask = ImageChops.multiply(ImageChops.multiply(r_mask, g_mask), b_mask)
    # Other UI elements on the captured desktop (icons, syntax highlighting,
    # cursor sprites) can include stray magenta pixels that, if left alone,
    # blow up the bounding box of the timer's sentinel.  The timer's border
    # is BORDER_PX (=12) pixels thick, so a 5-pixel binary erosion (MinFilter
    # with kernel 5) removes anything thinner than ~5 px while leaving the
    # border largely intact.  We then take the bbox of the eroded mask.
    eroded = mask.filter(ImageFilter.MinFilter(5))
    bbox = eroded.getbbox()
    if bbox is None:
        return None
    x0, y0, x1, y1 = bbox
    bw, bh = x1 - x0, y1 - y0
    # Reject obviously-too-small candidates (noise / stray magenta).
    if bw < 100 or bh < 50:
        return None
    # The eroded bbox is inset by ~2 px on each side relative to the true
    # outer border.  Expand it by one MinFilter radius so subsequent inner
    # padding reasoning matches the original (un-eroded) sentinel geometry.
    x0 = max(0, x0 - 2)
    y0 = max(0, y0 - 2)
    x1 = min(img.size[0], x1 + 2)
    y1 = min(img.size[1], y1 + 2)
    bw, bh = x1 - x0, y1 - y0

    # Step inside the magenta border by ~3 % of the bbox to land on the
    # white interior reliably even with a few pixels of compression bleed.
    pad_x = max(2, int(bw * 0.03))
    pad_y = max(2, int(bh * 0.03))
    ix0, iy0 = x0 + pad_x, y0 + pad_y
    ix1, iy1 = x1 - pad_x, y1 - pad_y
    inner_w = ix1 - ix0
    inner_h = iy1 - iy0
    if inner_w < BARCODE_BITS * 4 or inner_h < 10:
        return None

    # Barcode strip occupies the top BARCODE_HEIGHT/(BARCODE_HEIGHT+DIGIT_HEIGHT)
    # of the inner area.
    bar_frac = BARCODE_HEIGHT / (BARCODE_HEIGHT + DIGIT_HEIGHT)
    bar_y_center = iy0 + (inner_h * bar_frac) / 2
    cell_w_px = inner_w / BARCODE_BITS

    pixels = img.load()
    bits = 0
    W, H = img.size
    for i in range(BARCODE_BITS):
        cx = int(ix0 + (i + 0.5) * cell_w_px)
        cy = int(bar_y_center)
        # Average a 5×5 patch around the cell centre.
        total = 0
        n = 0
        for dy in (-4, -2, 0, 2, 4):
            for dx in (-4, -2, 0, 2, 4):
                px_x = min(W - 1, max(0, cx + dx))
                px_y = min(H - 1, max(0, cy + dy))
                px = pixels[px_x, px_y]
                total += (px[0] + px[1] + px[2]) / 3.0
                n += 1
        avg = total / n
        bit = 1 if avg < 128 else 0
        bits = (bits << 1) | bit
    return bits


# ── Frame extraction ──────────────────────────────────────────────────────

def extract_all_frames(ffmpeg: str, video: Path, out_dir: Path) -> list[Path]:
    """Dump every frame of *video* to *out_dir/frame_NNNNN.png* (1-based)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        ffmpeg, "-y",
        "-i", str(video),
        "-vsync", "passthrough",
        str(out_dir / "frame_%05d.png"),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(
            f"ffmpeg frame extraction failed:\n{result.stderr[-2000:]}"
        )
    return sorted(out_dir.glob("frame_*.png"))


# ── Pre-flight ────────────────────────────────────────────────────────────

def preflight(cfg: dict) -> str:
    """Validate dependencies and return the resolved ffmpeg path."""
    print("[preflight] checking dependencies...")
    from obsapp.video_ops import find_ffmpeg
    ffmpeg = find_ffmpeg(cfg["ffmpeg_executable"])
    print(f"[preflight]   ffmpeg = {ffmpeg}")
    obs_exe = Path(cfg.get("obs_executable", "Missing config entry 'obs_executable'"))
    if not obs_exe.exists():
        raise FileNotFoundError(f"OBS not found: {obs_exe}")
    print(f"[preflight]   obs    = {obs_exe}")
    try:
        from PIL import Image, ImageChops  # noqa: F401
    except ImportError as exc:
        raise RuntimeError(
            "Pillow is required for barcode decoding.  "
            "Install with: pip install Pillow"
        ) from exc
    print("[preflight]   PIL    ok")
    return ffmpeg


# ── Subprocess plumbing for the Timer window ──────────────────────────────

def _spawn_timer(x: int, y: int, w: int, h: int, anchor: float
                 ) -> subprocess.Popen:
    """Spawn the Timer subprocess, wait until it prints TIMER_READY."""
    proc = subprocess.Popen(
        [sys.executable, str(Path(__file__).resolve()),
         "--timer-window", str(x), str(y), str(w), str(h), f"{anchor:.6f}"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    ready = threading.Event()

    def _drain() -> None:
        assert proc.stdout is not None
        for line in iter(proc.stdout.readline, ""):
            if "TIMER_READY" in line:
                ready.set()
            # else: discard, but keep draining so the pipe never fills.

    threading.Thread(target=_drain, daemon=True).start()
    if not ready.wait(timeout=15.0):
        proc.terminate()
        raise RuntimeError("Timer subprocess did not become ready in 15 s")
    return proc


def _kill_timer(proc: subprocess.Popen | None) -> None:
    if proc is None or proc.poll() is not None:
        return
    try:
        proc.terminate()
        proc.wait(timeout=5)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


# ── Main test driver ──────────────────────────────────────────────────────

def main_driver(inifile: Path) -> int:
    from obsapp.api import Session, load_config, obs_config_dir_for
    from obsapp.video_ops import probe_video

    cfg = load_config(inifile)
    ffmpeg = preflight(cfg)

    workdir = inifile.parent / "test_run"
    workdir.mkdir(parents=True, exist_ok=True)
    rec1 = workdir / "recording1.mp4"
    rec1_censored = workdir / "recording1-censored.mp4"
    frames_dir = workdir / "frames"
    frames_dir2 = workdir / "frames-censored"
    for d in (frames_dir, frames_dir2):
        if d.exists():
            shutil.rmtree(d)
    for f in (rec1, rec1_censored):
        if f.exists():
            f.unlink()

    timer_proc: subprocess.Popen | None = None
    summary: dict = {}

    try:
        with Session(cfg, obs_config_dir_for(inifile)) as session:
            print("[step 1] starting OBS...")
            session.start_obs()

            print("[step 2] selecting devices...")
            monitors = session.list_monitors()
            mics = session.list_microphones()
            cams = session.list_webcams()
            if not monitors:
                raise RuntimeError("No monitors found.")
            mon_label, _, mon_w, mon_h = monitors[0]
            mic_label = mics[0][0] if mics else None
            cam_label = cams[0][0] if cams else None
            print(f"          monitor: {mon_label}  ({mon_w}×{mon_h})")
            print(f"          mic:     {mic_label or '(none)'}")
            print(f"          webcam:  {cam_label or '(none)'}")

            # Parse "@ x,y" out of the Windows-style monitor label.  On
            # Linux/macOS the label has no offset, so default to (0,0) — the
            # primary screen origin in those backends.
            mo = re.search(r"@\s*(-?\d+),(-?\d+)", mon_label)
            mon_x = int(mo.group(1)) if mo else 0
            mon_y = int(mo.group(2)) if mo else 0

            print("[step 3] launching Timer window...")
            anchor = time.time()
            timer_x = mon_x + 40
            timer_y = mon_y + 40
            timer_proc = _spawn_timer(
                timer_x, timer_y, TIMER_W, TIMER_H, anchor,
            )
            print(f"          timer at screen ({timer_x},{timer_y}) "
                  f"size {TIMER_W}×{TIMER_H}, anchor={anchor:.3f}")
            time.sleep(0.5)  # let the always-on-top window settle

            print("[step 4] start recording...")
            session.start_recording(
                monitor_name=mon_label,
                mic_name=mic_label,
                webcam_name=cam_label,
                target_path=rec1,
            )
            t_start = time.time()
            print(f"          recording started "
                  f"(t-anchor={t_start - anchor:.2f}s)")
            time.sleep(5.0)

            print("[step 5] pause recording for 2 s...")
            session.pause_recording()
            t_pause = time.time()
            time.sleep(2.0)

            print("[step 6] resume recording...")
            session.resume_recording()
            t_resume = time.time()
            time.sleep(3.0)

            print("[step 7] stop recording...")
            t_stop = time.time()  # before the call: excludes OBS finalize/rename time
            out_path = session.stop_recording()
            print(f"          saved: {out_path}")
            assert out_path == rec1, f"path mismatch: {out_path} != {rec1}"

            # ── analyze recording1 ──
            print("[step 8] analyzing recording1.mp4...")
            info1 = probe_video(ffmpeg, rec1)
            fps = info1["fps"]
            tol = max(0.5, 3.0 / fps)
            print(f"          observed: fps={fps:.3f}, "
                  f"duration={info1['duration']:.2f}s, "
                  f"{info1['width']}×{info1['height']}")
            print(f"          tolerance = {tol:.2f}s "
                  f"(max of 0.5s and 3 frames at {fps:.2f} fps)")

            ext_pause_dur = t_resume - t_pause
            ext_active_dur = (t_pause - t_start) + (t_stop - t_resume)
            print(f"          external clock: "
                  f"active={ext_active_dur:.2f}s, "
                  f"pause={ext_pause_dur:.2f}s")
            delta_dur = info1["duration"] - ext_active_dur
            print(f"          file duration vs external active: "
                  f"Δ={delta_dur:+.2f}s "
                  f"({'OK' if abs(delta_dur) < tol + 1.0 else 'CHECK'})")

            all_frames = extract_all_frames(ffmpeg, rec1, frames_dir)
            print(f"          extracted {len(all_frames)} frames to "
                  f"{frames_dir}")

            step = max(1, int(round(0.8 * fps)))
            sample_idxs = list(range(0, len(all_frames), step))

            decoded_samples: list[tuple[int, float, int | None]] = []
            print("          frame decode results:")
            for i in sample_idxs:
                video_t = i / fps
                cs = decode_barcode(all_frames[i])
                decoded_samples.append((i, video_t, cs))
                if cs is None:
                    print(f"            video t={video_t:5.2f}s "
                          f"frame {i:4d}: SENTINEL NOT FOUND")
                else:
                    wall = anchor + cs / 100.0
                    print(f"            video t={video_t:5.2f}s "
                          f"frame {i:4d}: timer={cs/100.0:6.2f}s "
                          f"(wall-start={wall - t_start:+.2f}s)")

            # Start delay = wall-clock at video t=0 minus t_start.
            start_delay: float | None = None
            if decoded_samples and decoded_samples[0][2] is not None:
                first_wall = anchor + decoded_samples[0][2] / 100.0
                start_delay = first_wall - t_start
                ok = abs(start_delay) < tol + 1.0
                print(f"          start delay: {start_delay:+.3f}s "
                      f"({'OK' if ok else 'CHECK'})")

            # Find the pause jump as the largest excess Δtimer between
            # consecutive samples beyond the expected step duration.
            pause_jump: float | None = None
            prev_cs = prev_t = None
            anomalies: list[str] = []
            expected_step = step / fps
            for (_, vt, cs) in decoded_samples:
                if cs is None:
                    prev_cs = prev_t = None
                    continue
                if prev_cs is not None:
                    d_video = vt - prev_t
                    d_timer = (cs - prev_cs) / 100.0
                    excess = d_timer - d_video
                    if excess > tol:
                        if pause_jump is None or excess > pause_jump:
                            pause_jump = excess
                    elif abs(d_timer - d_video) > tol:
                        anomalies.append(
                            f"video Δ={d_video:.2f}s but "
                            f"timer Δ={d_timer:.2f}s at video t={vt:.2f}s"
                        )
                prev_cs, prev_t = cs, vt
            if pause_jump is not None:
                ok_pause = abs(pause_jump - ext_pause_dur) < tol + 1.0
                print(f"          observed pause jump: {pause_jump:.2f}s "
                      f"(external: {ext_pause_dur:.2f}s) "
                      f"{'OK' if ok_pause else 'CHECK'}")
            else:
                print("          observed pause jump: NOT DETECTED")
            for a in anomalies:
                print(f"          anomaly: {a}")

            # ── censor (step 9) ──
            print("[step 9] censoring 0:03-0:05...")
            session.censor_video(rec1, "0:03-0:05", rec1_censored)
            print(f"          wrote: {rec1_censored}")

            info2 = probe_video(ffmpeg, rec1_censored)
            print(f"          censored: fps={info2['fps']:.3f}, "
                  f"duration={info2['duration']:.2f}s")

            # ── analyze censored (step 10) ──
            print("[step 10] analyzing censored video...")
            all_frames2 = extract_all_frames(ffmpeg, rec1_censored, frames_dir2)
            print(f"          extracted {len(all_frames2)} frames")

            step2 = max(1, int(round(0.8 * info2["fps"])))
            print("          frame decode results (placeholder = no sentinel):")
            for i in range(0, len(all_frames2), step2):
                video_t = i / info2["fps"]
                cs = decode_barcode(all_frames2[i])
                if cs is None:
                    print(f"            video t={video_t:5.2f}s "
                          f"frame {i:4d}: (no sentinel — placeholder?)")
                else:
                    print(f"            video t={video_t:5.2f}s "
                          f"frame {i:4d}: timer={cs/100.0:6.2f}s")

            # ── duration delta (step 11) ──
            print("[step 11] verifying censored duration delta...")
            delta = info1["duration"] - info2["duration"]
            expected = 1.0   # 2 s removed, 1 s placeholder inserted
            ok_delta = abs(delta - expected) < tol
            print(f"          Δduration = {delta:.2f}s "
                  f"(expected ≈ {expected:.2f}s, tol={tol:.2f}s) "
                  f"{'OK' if ok_delta else 'OUT OF TOLERANCE'}")

            summary = {
                "fps": fps,
                "tolerance_s": tol,
                "recording1_duration_s": info1["duration"],
                "recording1_censored_duration_s": info2["duration"],
                "duration_delta_s": delta,
                "duration_delta_expected_s": expected,
                "duration_delta_ok": ok_delta,
                "external_active_duration_s": ext_active_dur,
                "external_pause_duration_s": ext_pause_dur,
                "start_delay_s": start_delay,
                "observed_pause_jump_s": pause_jump,
                "n_frames_recording1": len(all_frames),
                "n_frames_censored": len(all_frames2),
            }
            print("[summary] " + json.dumps(summary, default=lambda o: None))

            # ── final checks ──────────────────────────────────────────────
            print("[checks]")
            failures: list[str] = []

            # 1. recording1 duration is close to the external active duration.
            if abs(delta_dur) >= tol + 1.0:
                failures.append(
                    f"recording1 duration {info1['duration']:.2f}s differs from "
                    f"external active time {ext_active_dur:.2f}s by "
                    f"{delta_dur:+.2f}s (tol={tol + 1.0:.2f}s)"
                )

            # 2. sentinel was found in at least half of the sampled frames.
            n_decoded = sum(1 for _, _, cs in decoded_samples if cs is not None)
            n_sampled = len(decoded_samples)
            if n_sampled > 0 and n_decoded < n_sampled // 2:
                failures.append(
                    f"sentinel found in only {n_decoded}/{n_sampled} sampled "
                    f"frames of recording1 — timer may have been off-screen or "
                    f"occluded"
                )

            # 3. start delay is reasonable (OBS should begin within tol + 1 s).
            if start_delay is None:
                failures.append(
                    "could not determine start delay: sentinel not found in "
                    "first sampled frame"
                )
            elif abs(start_delay) >= tol + 1.0:
                failures.append(
                    f"start delay {start_delay:+.3f}s exceeds tolerance "
                    f"{tol + 1.0:.2f}s"
                )

            # 4. pause jump detected and close to the external pause duration.
            if pause_jump is None:
                failures.append(
                    "pause jump not detected in recording1 — pause/resume may "
                    "not have been recorded, or too few decoded frames"
                )
            elif abs(pause_jump - ext_pause_dur) >= tol + 1.0:
                failures.append(
                    f"observed pause jump {pause_jump:.2f}s differs from "
                    f"external pause {ext_pause_dur:.2f}s by "
                    f"{pause_jump - ext_pause_dur:+.2f}s (tol={tol + 1.0:.2f}s)"
                )

            # 5. no timing anomalies in recording1.
            for a in anomalies:
                failures.append(f"timing anomaly in recording1: {a}")

            # 6. censored video duration delta is as expected (step 11).
            if not ok_delta:
                failures.append(
                    f"censored duration delta {delta:.2f}s differs from "
                    f"expected {expected:.2f}s by {delta - expected:+.2f}s "
                    f"(tol={tol:.2f}s)"
                )

            # 7. placeholder frame present in censored video (sentinel absent
            #    for at least one sampled frame in the censored region ~0-3 s).
            fps2 = info2["fps"]
            censor_region_end_frame = int(3.5 * fps2)
            placeholder_found = any(
                decode_barcode(all_frames2[i]) is None
                for i in range(0, min(censor_region_end_frame, len(all_frames2)))
            )
            if not placeholder_found:
                failures.append(
                    "no placeholder (sentinel-free) frame found in the first "
                    "3.5 s of recording1-censored.mp4 — censor may have failed"
                )

            # 8. censored video has fewer frames than recording1.
            if len(all_frames2) >= len(all_frames):
                failures.append(
                    f"censored video has {len(all_frames2)} frames, "
                    f"not fewer than recording1 ({len(all_frames)} frames)"
                )

            if failures:
                print(f"  FAILED ({len(failures)} issue(s)):")
                for msg in failures:
                    print(f"    - {msg}")
            else:
                print("  All looking good!")

            return 0 if not failures else 1

    finally:
        _kill_timer(timer_proc)
        for d in (frames_dir, frames_dir2):
            if d.exists():
                shutil.rmtree(d, ignore_errors=True)


# ── Entry point ───────────────────────────────────────────────────────────

def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--timer-window", nargs=5,
        metavar=("X", "Y", "W", "H", "ANCHOR"),
        help="Internal: run as the Timer subprocess.",
    )
    p.add_argument(
        "inifile", nargs="?",
        help="Path to obsapp-config.ini",
    )
    args = p.parse_args()

    if args.timer_window:
        x, y, w, h, anchor = args.timer_window
        run_timer(int(x), int(y), int(w), int(h), float(anchor))
        return 0

    if not args.inifile:
        p.error("inifile is required (or pass --timer-window for the subprocess)")

    return main_driver(Path(args.inifile))


if __name__ == "__main__":
    sys.exit(main())
