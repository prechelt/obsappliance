# OBS Appliance (OBSapp)

A few-click appliance to easily screen-record your desktop work locally with Open Broadcaster Software (OBS).
We use recent versions of OBS (V.30 or younger).

Still in early development and not ready for use.

## 1. Use cases


### 1.1 Overview

1. User activates OBSapp bootstrap for installation
2. User starts OBSapp
3. Config: User selects Monitor, Microphone (or none), Webcam (or none), target directory
4. OBSapp starts recording
5. User can pause/unpause the recording multiple times
6. User stops recording
7. OBSapp writes video file to target directory
8. OBSapp menu also offers censoring parts of the video or uploading the video

Next uses will start at step 2 and will offer the values of step 3 as defaults.


### 1.2 OBSapp bootstrap

1. User starts the OBSapp installer command
2. Installer checks if a current OBS Studio (at least V30.2) is present on the machine.
   If yes, places a starter script in the `$OBSAPPDIR/obsstudio` dir.
3. If not, downloads a portable version of OBS and places it (and a starter script) in `$OBSAPPDIR/obsstudio`.
4. Ditto for a suitable version of Python into `$OBSAPPDIR/python`. We require at least Python 3.10.
5. Installer places OBSapp code into `$OBSAPPDIR/obsapp`
6. Installer creates venv for OBSapp in `$OBSAPPDIR/venv` and installs the dependencies listed in `pyproject.toml`
7. Installer places OBSapp icon on desktop. Find a generic free red recording dot icon for that purpose.


### 1.3 OBSapp use

General GUI rules:
- All windows have ~2 em padding on all sides.
- OBS is started lazily (on first need) and shut down when OBSapp exits (or crashes).

1. OBSapp starts and presents the main GUI: an explanation text ("((explanation here))" for now)
   above a pulldown menu with entries:
   "Record...", "Concatenate videos...", "Censor video...", "Upload video...", "Exit".
   All subdialogs appear in the same window (which changes its size) and return to the main GUI when done.
2. User chooses an entry and gets sent to variant 2a, 2b, 2c, 2d, or 2e respectively.

Variants:

**2a. User chooses "Record...":**
2a1. OBSapp presents a dialog with four rows and buttons:
   - "Which screen to record:" pulldown of available screens
   - "Which microphone to record:" pulldown of available mics (or "\<no audio\>")
   - "Which webcam to record:" pulldown of available webcams (or "\<no webcam\>")
   - "Target MP4 file:" text field (initially empty) + file-selector button.
     If the chosen file already exists, warn; "OK" overwrites, "Cancel" returns to this dialog.
   - Buttons "Record", "Cancel"
2a2. User fills in dialog, then selects "Record".
2a3. OBSapp persists the dialog entries in a JSON file to offer them as defaults in the next run.
2a4. OBSapp starts OBS (if not already running), applies the config, starts recording,
   and shows the recording GUI: a small window with two buttons: "Pause" and "Stop".
2a5. "Pause" pauses recording; button label changes to "Resume". "Resume" resumes; label changes back.
2a6. "Stop" pauses, asks for confirmation.
   On confirm: stops recording, returns to main GUI.
   On cancel: unpauses recording, returns to recording GUI.

**2b. User chooses "Censor video...":**
2b1. OBSapp shows a dialog with:
     - Explanation text at top.
     - MP4 file name text field + file-chooser button.
     - A scrollable text area (initially ~5 lines tall) for time ranges, one per line.
       Format: `M:SS-M:SS` or `H:MM:SS-H:MM:SS` (whole seconds only).
       Example: "0:57-1:02" means seconds 57–62 will be cut and replaced by a short white frame
       with large black text "0:57-1:02 deleted". The output video is shorter than the input.
     - Buttons "OK", "Cancel".
     On "OK": validate ranges (no overlaps, within video duration, valid format).
     If invalid, show a message window listing the problems with an "OK" button; return to this dialog.
     (Perform replacements in reverse-sorted order back-to-front.)
2b2. OBSapp rewrites xyz.mp4 into xyz-censored.mp4 with each censored range removed
     and replaced by its info frame.
2b3. Returns to main GUI. ("Cancel" returns without rewriting.)

**2c. User chooses "Concatenate videos...":**
2c1. OBSapp presents a dialog with:
   - Explanation text at top.
   - A scrollable text area (initially ~5 lines tall) showing the file list, one path per line.
   - "Next input file:" text field + file-selector button.
   - "Output file:" text field + file-selector button.
   - Buttons "Add file", "DONE", "Cancel".
2c2. User enters a filepath and clicks "Add file"; OBSapp appends it to the list. Repeat ad libitum.
2c3. User clicks "DONE".
2c4. OBSapp validates that all input files exist and are compatible (same resolution, codec, frame rate).
   If not, show a message window listing the problems with an "OK" button; return to this dialog.
2c5. OBSapp writes the concatenated video to the output file.
     Before each part (including the first), it inserts a short white frame with large black text
     stating the file name (not path) of the upcoming part.
2c6. Returns to main GUI. ("Cancel" discards the list and returns without concatenating.)

**2d. User chooses "Upload video...":**
Shows a message window saying "Not implemented yet" with an "OK" button. Returns to main GUI.

**2e. User chooses "Exit":**
OBSapp shuts down OBS (if running) and terminates.



## 2. Non-functional properties

- Works on Windows 11, macOS, Linux (those distros that SW developers tend to have)
- Nothing ever requires superuser rights
- Recording consumes only modest amounts of CPU and memory so as not to disturb the human's work.
  In particular, the frame rate is 5 to 10 fps because smooth movement is unimportant.
- The entire installation is a single file tree in $HOME and is readily movable
  (i.e. uses only relative paths internally).


## 3. Architecture and Base Technology

- **Installation** — bootstrap scripts (`install.sh` for Linux/macOS, `install.ps1` for Windows)
  download a portable OBS Studio (if needed), FFmpeg (if needed), Python (if needed), 
  and the OBSapp package (always)
  into a single directory tree in the user's home directory. No superuser rights required.
- **obsappliance** is a small Python application with a desktop GUI that glues together the
  powerful capabilities of OBS Studio (video recording) and FFmpeg (video file handling).
- **OBS Studio** — used as the recording engine (screen capture, mic/webcam input,
  hardware encoder detection, pause/resume). Requires OBS V30 or newer.
- **FFmpeg** — used for video editing (censor, concatenate, text-frame generation).
- **CustomTkinter** — Python GUI toolkit providing a modern look on all platforms.
- **obs-websocket** — built into OBS 28+, used for all runtime control
  (`StartRecord`, `StopRecord`, `PauseRecord`, `ResumeRecord`, `GetInputList`, etc.)
  via the `obsws-python` library. Runs on `localhost:4455` with no password.


## 4. Configuration

`main.py` is called with a single argument, an `.ini` config file.
Its directory is the obsapp directory.
The OBS config files that obsapp creates dynamically will live in it.
Python, the Python venv, and OBS Studio may live in that directory or elsewhere.
Here is an example how it may look in an installed version of obsapp:
```ini
[obsappliance]
obs_executable=./obsstudio/bin/64bit/obs64.exe
ffmpeg_executable=C:\sw\ffmpeg20260323\bin\ffmpeg.exe
venv_dir=./venv
# The obs_config_dir will be the 'obs-config' subdirectory of the present file's location.
```
When obsapp starts, it immediately changes into the obsapp directory, so that the config file
can use relative paths, so that the obsapp directory can be relocated easily.

Here is a variant for a development setup on Windows where all parts are in a standard place:
```ini
[obsappliance]
obs_executable=c:/Program Files/obs-studio/bin/64bit/obs64.exe
ffmpeg_executable=C:/sw/ffmpeg20260323/bin/ffmpeg.exe
venv_dir=c:/venvs/obsapp
# The obs_config_dir will be the 'obs-config' subdirectory of the present file's location.
```


## 5. Remaining future development steps

Initialize development from a `pwsh` by
```
cd c:/ws/gh/obsappliance
c:\venv\obsapp\Scripts\Activate.ps1
```
and then either `\sw\opencode\opencode` for agentic work or the following for testing
```
& 'C:\Program Files\Git\bin\bash.exe'
PYTHONPATH=src python -m obsapp.main tmp_obsappdir/obsapp-config.ini
```

Steps to do:
- Get "concatenate" functionality to work
- Determine window sizes in the natural manner: based on content sizes.
- _make_text_frame(): make the font scaling work, it currently does not scale down long filenames.
- Get "censor" functionality to work
- Revise the installer to use obsapp-config.ini rather than the current fixed directory-shape convention.
- Test on Linux
- Test on macOS


### 6. Next development steps

...

