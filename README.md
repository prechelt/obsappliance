# OBS Appliance (OBSapp)

A few-click appliance to easily screen-record your desktop work locally with Open Broadcaster Software (OBS).

## 1. Use cases


### 1.1 Overview

1. User activates OBSapp bootstrap
2. User starts OBSapp
3. Config: User selects Monitor, Microphone (or none), Webcam (or none), target directory
4. OBSapp starts recording
5. User can pause/unpause the recording multiple times
6. User stops recording
7. OBSapp writes video file to target directory
8. OBSapp offers censoring parts of the video
9. OBSapp offers uploading the video

Next uses will start at step 2 and will offer the values of step 3 as defaults.


### 1.2 OBSapp bootstrap

1. User starts the OBSapp installer command
2. Installer checks if a current OBS Studio is present on the machine.
   If yes, places a starter script in the $OBSAPP_OBSDIR.
3. If not, downloads a portable version of OBS and places it (and a starter script) in $OBSAPP_OBSDIR.
4. Ditto for a suitable version of Python or Electron (depending on what we choose, see (3.) below)
   into $OBSAPP_PLATFORMDIR
5. Installer places OBSapp code into $OBSAPP_OBSAPPDIR
6. Installer places OBSapp icon on desktop 


### 1.3 OBSapp use

(to be added later)


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
  I imagine the tree to be something like this: 
  ~/obsapp/obsstudio/**, ~/obsapp/python/**, ~/obsapp/obsapp/**, ~/obsapp/config/*.   


## 3. Technology selection

Discuss these issues with me: Present options and considerations, then let me pick.
Replace the respective items in the list below with the outcomes.

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

1. ...
2. ...

Read Sections 1 and 2 for information only, then let us make the decisions for Section 3
and, once made, record them in the list just above.
