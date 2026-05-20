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
# An expander followed by a compressor is applied to every microphone source.
# The expander attenuates audio below the threshold rather than hard-muting it,
# which tolerates quiet microphones better than a noise gate would.
# The compressor evens out speech dynamics for consistent intelligibility.
#
# All threshold/gain values are in dBFS (negative = below full-scale).
# All time values are in milliseconds.

# Expander — attenuates audio that falls below the threshold by `ratio`:1.
# Unlike a hard gate, a ratio of 4:1 reduces level by 3 dB per 4 dB below
# the threshold, so quiet speech is turned down rather than silenced.
# Setting the threshold low (−40 dBFS) means even quiet microphones whose
# speech peaks only reach around −35 dBFS are unaffected above the threshold,
# while background noise at −60 dBFS is reduced by roughly 15 dB.
MIC_EXPANDER_RATIO: float = 4.0       # 4:1 — noticeable but not abrupt attenuation
MIC_EXPANDER_THRESHOLD_DB: float = -40.0  # dBFS — low enough for quiet microphones
MIC_EXPANDER_ATTACK_MS: int = 10      # ms — fast enough not to clip consonant onsets
MIC_EXPANDER_RELEASE_MS: int = 50     # ms — short enough not to pump
MIC_EXPANDER_DETECTOR: str = "rms"    # "rms" is smoother than "peak" for speech
MIC_EXPANDER_KNEE_DB: float = 2.0     # dB soft-knee width — gentler transition

# Compressor — reduces the dynamic range of speech so that both quiet and loud
# passages land at a similar perceived level.
MIC_COMP_RATIO: float = 4.0        # 4:1 — audible but natural-sounding compression
MIC_COMP_THRESHOLD_DB: float = -18.0  # dBFS — kick in once speech is clearly present
MIC_COMP_ATTACK_MS: int = 6        # ms — fast enough to control plosives
MIC_COMP_RELEASE_MS: int = 60      # ms — short enough not to pump between syllables
MIC_COMP_OUTPUT_GAIN_DB: float = 0.0  # dB makeup gain — increase if overall level is low

# ── Duration of the inserted announcement slides ──────────────────────────────

CENSORING_REPLACEMENTSLIDE_DURATION_SECS = 1
CONCATENATE_FILENAMESLIDE_DURATION_SECS = 1
