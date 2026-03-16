@echo off
REM Starter script for OBS Studio in OBSapp portable mode (Windows).
set "SCRIPT_DIR=%~dp0"
set "OBSAPPDIR=%SCRIPT_DIR%.."

REM Try portable OBS first, then system-installed OBS
if exist "%OBSAPPDIR%\obsstudio\bin\64bit\obs64.exe" (
    set "OBS_EXE=%OBSAPPDIR%\obsstudio\bin\64bit\obs64.exe"
) else (
    where obs64.exe >nul 2>&1
    if %ERRORLEVEL% equ 0 (
        set "OBS_EXE=obs64.exe"
    ) else (
        echo ERROR: OBS Studio not found.
        exit /b 1
    )
)

start "" "%OBS_EXE%" --portable --minimize-to-tray --startrecording --collection "OBSapp" --profile "OBSapp" %*
