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

# ── Microphone audio filters ──────────────────────────────────────────────────
#
# A noise gate followed by a compressor is applied to every microphone source.
# The gate eliminates background noise during silence; the compressor evens out
# speech dynamics so intelligibility stays consistent.
#
# All threshold/gain values are in dBFS (negative = below full-scale).
# All time values are in milliseconds.

# Noise gate — mutes the mic while the level stays below close_threshold;
# opens once the level rises above open_threshold.
MIC_GATE_OPEN_DB: float = -26.0    # dBFS — typical peak level of distant/quiet speech
MIC_GATE_CLOSE_DB: float = -32.0   # dBFS — 6 dB hysteresis prevents chatter
MIC_GATE_ATTACK_MS: int = 25       # ms — fast enough to catch consonant onsets
MIC_GATE_HOLD_MS: int = 200        # ms — stay open through brief inter-word pauses
MIC_GATE_RELEASE_MS: int = 150     # ms — smooth fade-out when gate closes

# Compressor — reduces the dynamic range of speech so that both quiet and loud
# passages land at a similar perceived level.
MIC_COMP_RATIO: float = 4.0        # 4:1 — audible but natural-sounding compression
MIC_COMP_THRESHOLD_DB: float = -18.0  # dBFS — kick in once speech is clearly present
MIC_COMP_ATTACK_MS: int = 6        # ms — fast enough to control plosives
MIC_COMP_RELEASE_MS: int = 60      # ms — short enough not to pump between syllables
MIC_COMP_OUTPUT_GAIN_DB: float = 0.0  # dB makeup gain — increase if overall level is low
CENSORING_REPLACEMENTSLIDE_DURATION_SECS = 1

# Duration (seconds) of the title slide showing each input file's name,
# inserted before its content by `concatenate()`.
CONCATENATE_FILENAMESLIDE_DURATION_SECS = 1

