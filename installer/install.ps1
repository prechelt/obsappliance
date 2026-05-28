#Requires -Version 5.1
<#
.SYNOPSIS
    Install OBSapp and its dependencies into a single self-contained directory.

.DESCRIPTION
    Downloads and installs:
      - OBS Studio (portable ZIP, no admin required)
      - Python (embeddable distribution, no admin required)
      - FFmpeg (standalone ZIP, no admin required)
      - OBSapp (from GitHub)

    On re-runs OBS, Python, and FFmpeg are left untouched; only OBSapp is
    reinstalled.  Use this to update OBSapp to a newer release.

.PARAMETER InstallDir
    The directory to install everything into.  Must be empty or not yet exist.
    On re-runs it must be the same directory used previously.

.PARAMETER Current
    Install from the main branch instead of the latest tagged release.

.EXAMPLE
    .\install.ps1 -InstallDir C:\Tools\obsapp
    .\install.ps1 -InstallDir C:\Tools\obsapp -Current
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory, Position = 0,
               HelpMessage = "Empty directory to install everything into")]
    [string] $InstallDir,

    [switch] $Current
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$ProgressPreference    = "SilentlyContinue"   # makes Invoke-WebRequest much faster

# ── Constants ─────────────────────────────────────────────────────────────────

$OBSAPP_REPO  = "prechelt/obsappliance"
$OBS_REPO     = "obsproject/obs-studio"
$OBS_MIN_VER  = [version]"28.0"

# Python: accepted minor version range for a system-wide install with tkinter.
$PYTHON_MIN_MINOR = 12   # 3.12
$PYTHON_MAX_MINOR = 30   # 3.30 (upper bound, adjust as needed)

# Pinned fallback version to download if no system Python is found.
# Bump when a newer stable release ships.
$PYTHON_FALLBACK_VER = "3.13.3"

# BtbN provides a stable "latest" permalink for FFmpeg GPL Windows builds.
$FFMPEG_URL   = "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip"

# ── Helpers ───────────────────────────────────────────────────────────────────

function Write-Step([string]$msg) {
    Write-Host "`n==> $msg" -ForegroundColor Cyan
}
function Write-OK([string]$msg) {
    Write-Host "    ok: $msg" -ForegroundColor Green
}
function Write-Skip([string]$msg) {
    Write-Host "    skip: $msg (already present)" -ForegroundColor Yellow
}
function Abort([string]$msg) {
    $script:_abortMessage = $msg
    throw "abort"
}

function Get-GitHubLatestTag([string]$repo) {
    $r = Get-GitHubLatestRelease $repo
    if ($r) { return $r.tag_name } else { return $null }
}

function Save-File([string]$url, [string]$dest) {
    Write-Host "    downloading $(Split-Path $url -Leaf) ..."
    Invoke-WebRequest -Uri $url -OutFile $dest -UseBasicParsing
}

# Extract a zip, handling the common case where the zip contains a single
# top-level directory (unwrap it) vs. extracting flat files directly.
function Expand-IntoDir([string]$zip, [string]$targetDir) {
    $tmp = Join-Path ([System.IO.Path]::GetTempPath()) ([System.IO.Path]::GetRandomFileName())
    Expand-Archive -Path $zip -DestinationPath $tmp -Force
    $children = @(Get-ChildItem $tmp)
    New-Item -ItemType Directory -Path $targetDir -Force | Out-Null
    if ($children.Count -eq 1 -and $children[0].PSIsContainer) {
        # Single wrapper directory — move its contents up
        Get-ChildItem $children[0].FullName | Move-Item -Destination $targetDir -Force
    } else {
        Get-ChildItem $tmp | Move-Item -Destination $targetDir -Force
    }
    Remove-Item $tmp -Recurse -Force
}

function Get-FileVersion([string]$path) {
    return [version](Get-Item $path).VersionInfo.ProductVersion.Split('-')[0]
}

# Return the path to obs64.exe if a sufficient system-wide OBS installation is
# found in the standard Program Files locations, or $null otherwise.
function Find-SystemOBS {
    foreach ($base in @("$env:ProgramFiles\obs-studio",
                         "${env:ProgramFiles(x86)}\obs-studio")) {
        $exe = Join-Path $base "bin\64bit\obs64.exe"
        if (Test-Path $exe) { return $exe }
    }
    return $null
}

# Return the GitHub release API object for the latest release of $repo, or $null.
function Get-GitHubLatestRelease([string]$repo) {
    try {
        return Invoke-RestMethod "https://api.github.com/repos/$repo/releases/latest"
    } catch {
        return $null
    }
}

# Return the browser_download_url of the first release asset whose name matches
# $pattern (a wildcard string), or $null if none matches.
function Get-ReleaseAssetUrl($release, [string]$pattern) {
    $asset = $release.assets | Where-Object { $_.name -like $pattern } | Select-Object -First 1
    if ($asset) { return $asset.browser_download_url } else { return $null }
}

# Search HKLM and HKCU for Python 3.x (x in $PYTHON_MIN_MINOR..$PYTHON_MAX_MINOR).
# Returns the path to python.exe for the highest version found, or $null.
function Find-SystemPython {
    $best    = $null
    $bestVer = $null

    foreach ($hive in @("HKLM:\SOFTWARE\Python\PythonCore",
                         "HKCU:\SOFTWARE\Python\PythonCore",
                         "HKLM:\SOFTWARE\WOW6432Node\Python\PythonCore")) {
        if (-not (Test-Path $hive)) { continue }
        foreach ($minor in $PYTHON_MAX_MINOR..$PYTHON_MIN_MINOR) {
            $key = "$hive\3.$minor\InstallPath"
            if (-not (Test-Path $key)) { continue }
            # Prefer the ExecPath value; fall back to default (install dir).
            $exe = (Get-ItemProperty $key -ErrorAction SilentlyContinue).ExecutablePath
            if (-not $exe) {
                $dir = (Get-ItemProperty $key -ErrorAction SilentlyContinue).'(default)'
                if (-not $dir) {
                    $dir = (Get-ItemProperty $key -ErrorAction SilentlyContinue).''
                }
                if ($dir) { $exe = Join-Path $dir "python.exe" }
            }
            if ($exe -and (Test-Path $exe)) {
                # Reject embeddable distributions and any Python without tkinter,
                # since CustomTkinter requires it.
                & $exe -c "import tkinter" 2>$null
                if ($LASTEXITCODE -ne 0) { continue }
                $v = [version]"3.$minor"
                if (-not $bestVer -or $v -gt $bestVer) {
                    $bestVer = $v
                    $best    = $exe
                }
                break   # found this minor version; move to next hive
            }
        }
    }
    return $best
}

# Attempt to install Python automatically.
# Tries winget first (fast, no download of our own), then falls back to the
# official silent installer downloaded from python.org.
# Returns the path to python.exe on success, aborts on failure.
function Install-Python([string]$tmpDir) {
    # ── winget ────────────────────────────────────────────────────────────────
    $winget = Get-Command winget -ErrorAction SilentlyContinue
    if ($winget) {
        $minor = $PYTHON_FALLBACK_VER.Split('.')[1]
        $wingetCmd = "winget install --id `"Python.Python.3.$minor`" --silent --scope user --accept-package-agreements --accept-source-agreements"
        Write-Host "    running: $wingetCmd"
        & winget install --id "Python.Python.3.$minor" --silent --scope user --accept-package-agreements --accept-source-agreements
        if ($LASTEXITCODE -ne 0) {
            Write-Host "    winget exited with code $LASTEXITCODE (may still have succeeded; checking ...)" -ForegroundColor Yellow
        }
        $found = Find-SystemPython
        if ($found) { return $found }
        Write-Host "    Python not found after winget; falling back to direct download ..." -ForegroundColor Yellow
    }

    # ── Official silent installer ──────────────────────────────────────────────
    Write-Host "    downloading Python $PYTHON_FALLBACK_VER installer ..."
    $pyExeUrl  = "https://www.python.org/ftp/python/$PYTHON_FALLBACK_VER/python-$PYTHON_FALLBACK_VER-amd64.exe"
    $pyInstaller = Join-Path $tmpDir "python-installer.exe"
    Save-File $pyExeUrl $pyInstaller

    Write-Host "    running Python installer silently (user-mode, no admin needed) ..."
    & $pyInstaller /quiet InstallAllUsers=0 PrependPath=0 Include_launcher=0 Include_tcltk=1
    if ($LASTEXITCODE -ne 0) {
        Write-Host "    Python installer exited with code $LASTEXITCODE (may still have succeeded; checking ...)" -ForegroundColor Yellow
    }

    $found = Find-SystemPython
    if (-not $found) {
        Abort "Python was not found after the silent installer (exit $LASTEXITCODE)."
    }
    return $found
}

# ── Directories ───────────────────────────────────────────────────────────────

# Resolve $InstallDir against PowerShell's $PWD before passing to .NET, because
# .NET resolves relative paths against [Environment]::CurrentDirectory which can
# differ from $PWD when the script runs as a scriptblock (e.g. piped from irm).
$InstallDir = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($InstallDir)

$tmp = $null   # initialised inside try so finally can safely remove it
$script:_abortMessage = $null   # set by Abort(); must exist before catch reads it
$script:_aborted      = $false  # set in catch; must exist before post-try check

try {

$root      = (Resolve-Path -LiteralPath (
                  [System.IO.Directory]::CreateDirectory($InstallDir).FullName
              )).Path
$obsDir    = Join-Path $root "obs-studio"
$ffmpegDir = Join-Path $root "ffmpeg"
$venvDir   = Join-Path $root "venv"
$iniFile   = Join-Path $root "obsapp-config.ini"
$batFile   = Join-Path $root "run-obsapp.bat"

$isUpdate  = Test-Path (Join-Path $venvDir "Scripts\python.exe")

if (-not $isUpdate) {
    # On a fresh install the directory must be empty.
    if ((Get-ChildItem $root -Force | Measure-Object).Count -gt 0) {
        Abort "InstallDir '$root' is not empty.  Choose an empty or non-existent directory."
    }
}

$tmp = Join-Path ([System.IO.Path]::GetTempPath()) "obsapp-install-$PID"
New-Item -ItemType Directory -Path $tmp -Force | Out-Null

# ── OBS Studio ────────────────────────────────────────────────────────────────

Write-Step "OBS Studio"

# $obsExe is set here (used again in the config-file step below).
if (Test-Path (Join-Path $obsDir "bin\64bit\obs64.exe")) {
    $obsExe = Join-Path $obsDir "bin\64bit\obs64.exe"
    $v = Get-FileVersion $obsExe
    if ($v -lt $OBS_MIN_VER) {
        Abort "Installed OBS ($v) is older than the required minimum ($OBS_MIN_VER).`nDelete '$obsDir' and re-run to download a fresh copy."
    }
    Write-Skip "OBS $v (portable in $obsDir)"
} else {
    $sysObs = Find-SystemOBS
    if ($sysObs) {
        $v = Get-FileVersion $sysObs
        if ($v -lt $OBS_MIN_VER) {
            Abort "System OBS ($v at $sysObs) is older than the required minimum ($OBS_MIN_VER).`nPlease update OBS Studio and re-run."
        }
        $obsExe = $sysObs
        Write-OK "Found system OBS $v at $sysObs"
    } else {
        $obsRelease = Get-GitHubLatestRelease $OBS_REPO
        if (-not $obsRelease) {
            Abort "Could not determine latest OBS release from GitHub. Exiting."
        }
        $obsTag = $obsRelease.tag_name
        $obsVer = $obsTag.TrimStart('v')
        $obsUrl = Get-ReleaseAssetUrl $obsRelease "OBS-Studio-*-Windows.zip"
        if (-not $obsUrl) {
            Abort "Could not find a Windows ZIP asset in OBS release $obsTag."
        }
        $obsZip = Join-Path $tmp "obs.zip"
        Save-File $obsUrl $obsZip
        Write-Host "    extracting ..."
        Expand-IntoDir $obsZip $obsDir
        $obsExe = Join-Path $obsDir "bin\64bit\obs64.exe"
        Write-OK "OBS $obsVer installed to $obsDir"
    }
}

# ── FFmpeg ────────────────────────────────────────────────────────────────────

Write-Step "FFmpeg"

# $ffmpegExe is set here (used again in the config-file step below).
if (Test-Path (Join-Path $ffmpegDir "bin\ffmpeg.exe")) {
    $ffmpegExe = Join-Path $ffmpegDir "bin\ffmpeg.exe"
    Write-Skip "FFmpeg (portable in $ffmpegDir)"
} else {
    $onPath = Get-Command ffmpeg -ErrorAction SilentlyContinue
    if ($onPath) {
        $ffmpegExe = $onPath.Source
        Write-OK "Found FFmpeg on PATH at $ffmpegExe"
    } else {
        $ffmpegZip = Join-Path $tmp "ffmpeg.zip"
        Save-File $FFMPEG_URL $ffmpegZip
        Write-Host "    extracting ..."
        Expand-IntoDir $ffmpegZip $ffmpegDir
        $ffmpegExe = Join-Path $ffmpegDir "bin\ffmpeg.exe"
        Write-OK "FFmpeg installed to $ffmpegDir"
    }
}

# ── Python ────────────────────────────────────────────────────────────────────

Write-Step "Python"

# Resolve the base python.exe we will use to create the venv.
# Must be a full Python install (not embeddable) with tkinter available.
$basePython = $null

if (Test-Path (Join-Path $venvDir "Scripts\python.exe")) {
    # Venv already exists — basePython is not needed; skip straight to venv step.
    Write-Skip "Python (there is even a venv already)"
    $basePython = "skip"
} else {
    $sysPython = Find-SystemPython
    if ($sysPython) {
        $v = & $sysPython -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')" 2>$null
        $basePython = $sysPython
        Write-OK "Found system Python $v at $sysPython"
    } else {
        Write-Host "    no suitable Python found; installing automatically ..."
        $basePython = Install-Python $tmp
        $v = & $basePython -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')" 2>$null
        Write-OK "Python $v installed and found at $basePython"
    }
}

# ── Venv ──────────────────────────────────────────────────────────────────────

Write-Step "Python venv"

if (Test-Path (Join-Path $venvDir "Scripts\python.exe")) {
    Write-Skip "venv (found at $venvDir)"
} else {
    Write-Host "    creating venv at $venvDir ..."
    & $basePython -m venv $venvDir
    if ($LASTEXITCODE -ne 0) { Abort "Failed to create venv at $venvDir." }
    Write-OK "venv created at $venvDir"
}

$python = Join-Path $venvDir "Scripts\python.exe"
$pip    = Join-Path $venvDir "Scripts\pip.exe"

# ── OBSapp ────────────────────────────────────────────────────────────────────

Write-Step "OBSapp"

$pipFlags = "--upgrade"
if ($Current) {
    $obsappUrl = "https://github.com/$OBSAPP_REPO/archive/refs/heads/main.zip"
    Write-Host "    installing from main branch ..."
    # --force-reinstall ensures the latest commit is installed even when the
    # version number in pyproject.toml has not been bumped.
    $pipFlags = "--upgrade --force-reinstall"
} else {
    $tag = Get-GitHubLatestTag $OBSAPP_REPO
    if ($tag) {
        $obsappUrl = "https://github.com/$OBSAPP_REPO/archive/refs/tags/$tag.zip"
        Write-Host "    installing release $tag ..."
    } else {
        Write-Host "    no release found; falling back to main branch ..." -ForegroundColor Yellow
        $obsappUrl = "https://github.com/$OBSAPP_REPO/archive/refs/heads/main.zip"
        $pipFlags = "--upgrade --force-reinstall"
    }
}

& $pip install $pipFlags.Split() $obsappUrl --quiet
if ($LASTEXITCODE -ne 0) { Abort "OBSapp installation via pip failed." }
Write-OK "OBSapp installed"

# ── Config file ───────────────────────────────────────────────────────────────

Write-Step "Configuration"

if (-not (Test-Path $iniFile)) {
    # Write UTF-8 without BOM so Python's configparser reads it correctly on
    # every locale, even when the install path contains non-ASCII characters.
    # Set-Content's default encoding differs between PS5 (ANSI) and PS7 (UTF-8),
    # so we use WriteAllText with an explicit no-BOM UTF-8 encoder.
    $iniContent = @"
[obsappliance]
obs_executable     = $obsExe
ffmpeg_executable  = $ffmpegExe
venv_dir           = $venvDir
"@
    [System.IO.File]::WriteAllText($iniFile, $iniContent, [System.Text.UTF8Encoding]::new($false))
    Write-OK "Created $iniFile"
} else {
    Write-Skip "Config file (not overwritten on update)"
}

# ── Launcher ──────────────────────────────────────────────────────────────────

Write-Step "Launcher"

# pythonw.exe suppresses the console window for a GUI application.
@"
@echo off
start "" "%~dp0venv\Scripts\pythonw.exe" -m obsapp.main "%~dp0obsapp-config.ini" %*
"@ | Set-Content $batFile
Write-OK "Created $batFile"

# ── Desktop shortcut ──────────────────────────────────────────────────────────

Write-Step "Desktop shortcut"

# Find the installed icon; fall back to the OBS executable's icon.
$icoPath = Get-ChildItem "$venvDir\Lib\site-packages\obsapp\resources" `
               -Filter "obsapp-icon.ico" -ErrorAction SilentlyContinue |
           Select-Object -First 1 -ExpandProperty FullName
if (-not $icoPath) { $icoPath = "$obsExe,0" }

$lnkPath = Join-Path ([Environment]::GetFolderPath("Desktop")) "OBSapp.lnk"
$shell    = New-Object -ComObject WScript.Shell
$lnk      = $shell.CreateShortcut($lnkPath)
$lnk.TargetPath       = $batFile
$lnk.WorkingDirectory = $root
$lnk.Description      = "OBS Studio Recording Appliance"
$lnk.IconLocation     = $icoPath
$lnk.Save()
Write-OK "Shortcut created at $lnkPath"

# ── Done ──────────────────────────────────────────────────────────────────────

} catch {
    if ($script:_abortMessage) {
        Write-Host "`nERROR: $script:_abortMessage" -ForegroundColor Red
    } else {
        Write-Host "`nUnexpected error: $_" -ForegroundColor Red
    }
    $script:_aborted = $true
} finally {
    if ($tmp) { Remove-Item $tmp -Recurse -Force -ErrorAction SilentlyContinue }
}

if ($script:_aborted) { return }

Write-Host @"

Done.  Installation layout:
  $root\
    obs-studio\        OBS Studio portable (if no system OBS was found)
    ffmpeg\            FFmpeg (if no system FFmpeg was found on PATH)
    venv\              Python venv with OBSapp and its dependencies
    obsapp-config.ini  edit to adjust paths if needed
    run-obsapp.bat     launch from the command line

A desktop shortcut 'OBSapp' has been created.

To update OBSapp later, re-run this script with the same InstallDir.
"@ -ForegroundColor Green
