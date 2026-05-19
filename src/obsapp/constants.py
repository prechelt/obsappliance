"""Shared constants for OBSapp."""

# Recording frame rate (frames per second) used both for the OBS recording
# profile and as a fallback when ffprobe cannot report a stream's fps.
FPS_DEFAULT = 8

# ── Picture-in-Picture (webcam overlay) ──────────────────────────────────────

# Height of the PiP position-picker canvas in the Record dialog (logical px).
PIP_HEIGHT = 120

# Gap between each grid cell and its neighbours / the canvas border (logical px).
# Increase to make the grid more open; decrease for a denser look.
PIP_CELL_MARGIN = 2

# Assumed webcam aspect ratio used to draw the preview grid cells.
# 16:9 is correct for virtually all modern webcams.
PIP_WEBCAM_ASPECT: float = 16.0 / 9.0

# Webcam overlay sizes in OBS *canvas* pixels (recorded resolution).
PIP_SIZE_SMALL = 180
PIP_SIZE_MEDIUM = 240
PIP_SIZE_LARGE = 300

# Gap from the nearest screen edge in OBS canvas pixels.
PIP_SCREEN_MARGIN = 20

# Duration (seconds) of the white info frame inserted in place of each
# censored range by `censor()`.
CENSORING_REPLACEMENTSLIDE_DURATION_SECS = 1

# Duration (seconds) of the title slide showing each input file's name,
# inserted before its content by `concatenate()`.
CONCATENATE_FILENAMESLIDE_DURATION_SECS = 1

