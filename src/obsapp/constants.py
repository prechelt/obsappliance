"""Shared constants for OBSapp."""

# Recording frame rate (frames per second) used both for the OBS recording
# profile and as a fallback when ffprobe cannot report a stream's fps.
FPS_DEFAULT = 8

# Duration (seconds) of the white info frame inserted in place of each
# censored range by `censor()`.
CENSORING_REPLACEMENTSLIDE_DURATION_SECS = 1

# Duration (seconds) of the title slide showing each input file's name,
# inserted before its content by `concatenate()`.
CONCATENATE_FILENAMESLIDE_DURATION_SECS = 1

