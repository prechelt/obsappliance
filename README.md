# OBS Appliance (OBSapp)

A few-click appliance to easily screen-record your desktop work locally with Open Broadcaster Software (OBS).

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
       Example: "0:57-1:02" means seconds 57–62 will be cut and replaced by a 1-second white frame
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
     Before each part (including the first), it inserts a 1-second white frame with large black text
     stating the file name (not path) of the upcoming part.
2c6. Returns to main GUI. ("Cancel" discards the list and returns without concatenating.)

**2d. User chooses "Upload video...":**
Shows a message window saying "Not implemented yet" with an "OK" button. Returns to main GUI.

**2e. User chooses "Exit":**
OBSapp shuts down OBS (if running) and terminates.



## 2. Non-functional requirements

- Must work on Windows 11, macOS, Linux (those distros that SW developers tend to have)
- Nothing ever requires superuser rights
- Installation is into the user's home directory
- Must present a desktop GUI for config and for pause/unpause/stop
- Recording should consume only modest amounts of CPU and memory so as not to disturb the human's work;
  15% CPU is OK, 30% is too much.
- Text in the recording must be legible even if it is visible only shortly (0.4 sec)
- Smooth movement is unimportant. A frame rate of 5 to 10 fps is sufficient.
- Distribution is via the GitHub repo or perhaps a GitHub release
- The entire installation should be a single file tree in $HOME and should be readily movable
  (i.e. use only relative paths internally).


## 3. Technology selection

1. Consider if there is a sensible alternative to OBS Studio 
2. Installation ("bootstrap") on Linux and macOS could be in the `curl someurl | bash` style.
   Is there a better way?
3. Installation on Windows: Can it be done by a similar single command in PowerShell?
   If not, should we go for an executable or a PowerShell script for the installer? Why?
4. Any ideas for minimizing the amount of redundancy between the Windows and the macOS/Linux install script?
5. On Windows, can we avoid requiring WSL easily?
6. For the GUI I can think of Python/tkinter or Electron.
   Any other sensible possibility that is lightweight and uses mainstream building blocks?
   Which of the two might we prefer and why?
   My JS skills are minimal, my Python skills good, so I might lean towards Python.
   However, a tkinter GUI will look very oldfashioned, right? Is that avoidable?
   On the other hand, Electron is going to be very heavyweight, correct? Is that a problem?
7. Is OBS Studio's Python scripting useful for building the GUI? 
   Or for simplifying building it (e.g. accessing the device lists)?
   Then we might face a Python download in any case -- unless we use Lua instead.
   Can we use Lua? Should we? Again, present arguments and tradeoffs.
8. How will the actual OBS control be realized? I guess the config (device selection) can be written
   into a file? How will start/stop/pause/unpause be transmitted to OBS Studio?

Decisions:

1. **OBS Studio** — FFmpeg-only would save download size but adds substantial complexity
   (pause/resume, hardware encoder detection, platform-specific screen enumeration).
   OBS provides all of that out of the box. Webcam overlay is dropped from requirements.
2. **`curl <url> | bash`** for Linux/macOS bootstrap. Standard approach for developer tools.
3. **`irm <url> | iex`** (PowerShell) for Windows bootstrap. Same pattern, no need for an .exe installer.
4. **Two parallel scripts** (`install.sh` + `install.ps1`) with the same logical structure.
   Shared configuration (URLs, versions) in a small JSON file that both scripts read.
5. **No WSL required.** OBS, Python, and PowerShell all run natively on Windows.
6. **Python + CustomTkinter** for the GUI. Modern look, lightweight (~1 MB on top of Python),
   matches developer's Python skills. Electron rejected as too heavyweight (~150 MB+).
7. **No OBS scripting for the GUI.** OBS scripts run inside OBS and can't build standalone windows.
   Use **obs-websocket** (built into OBS 28+) for all communication between GUI and OBS.
   A small Lua script inside OBS may help with device enumeration if the websocket API falls short.
8. **obs-websocket** for runtime control (`StartRecord`, `StopRecord`, `PauseRecord`, `ResumeRecord`,
   `GetInputList`, etc.) via the `obsws-python` library. Device/scene configuration is written
   as OBS scene collection JSON files placed in OBS's portable config directory before launch.


## 4. Architecture

### 4.1 Video processing

OBS is a recording/streaming engine, not a video editor.
Concatenation and censoring (cutting segments, generating text frames, reassembling)
require **FFmpeg**. OBS bundles an FFmpeg binary on all platforms;
we use that and fall back to a separate FFmpeg download if needed.

### 4.2 Module structure

```
obsapp/
  main.py                — entry point, app lifecycle
  gui/
    __init__.py
    main_menu.py         — main menu screen
    record_dialog.py     — record config dialog + recording controls (Pause/Resume, Stop)
    censor_dialog.py     — censor dialog
    concat_dialog.py     — concatenate dialog
    widgets.py           — shared GUI helpers (message boxes, file choosers, validation display)
  obs_control.py         — OBS process lifecycle, websocket connection, record/pause/stop commands
  video_ops.py           — FFmpeg operations: censor, concatenate, text-frame generation
  config.py              — JSON persistence of user settings (defaults for record dialog)
```

### 4.3 Dependencies between modules

```
main.py → gui/*          (drives the GUI)
gui/*   → obs_control    (record_dialog calls start/pause/stop)
gui/*   → video_ops      (censor_dialog, concat_dialog call FFmpeg operations)
gui/*   → config         (record_dialog reads/writes defaults)
gui/*   → widgets        (all dialogs use shared helpers)
```

`obs_control`, `video_ops`, and `config` do not depend on each other or on `gui`.

### 4.4 Configuration

`main.py` is called with a single argument, an `.ini` config file.
Its directory is the obsapp directory.
The OBS config file that obsapp creates dynamically will live in it.
Python, the Python venv, and OBS Studio may live in that directory or elsewhere.
Here is an example how it may look in an installed version of obsapp:
```ini
[obsappliance]
obsstudio_dir=./obsstudio
venv_dir=./venv
```
When obsapp starts, it immediately changes into the obsapp directory, so that the config file
can use relative paths, so that the obsapp directory can be relocated easily.

Here is a variant for a development setup on Windows where both parts are in a standard place:
```ini
[obsappliance]
obsstudio_dir=C:\Program Files\obs-studio
venv_dir=c:\venv\obsapp
```


## 5. Next development step

Functionality 2a ("Record") is implemented.
Use the OBS indicated in the .ini file.
Test recording on a desktop system (Linux, Windows, or macOS) with OBS Studio installed.
Then implement 2b ("Censor video") and 2c ("Concatenate videos").
