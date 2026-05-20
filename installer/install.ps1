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

# Python embeddable release.  Bump the patch version when a newer 3.12.x ships.
# The minor version (312) must match the ._pth filename inside the zip.
$PYTHON_VER   = "3.12.10"
$PYTHON_MINOR = "312"        # used to locate python312._pth inside the zip

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
    Write-Host "`nERROR: $msg" -ForegroundColor Red
    exit 1
}

function Get-GitHubLatestTag([string]$repo) {
    try {
        $r = Invoke-RestMethod "https://api.github.com/repos/$repo/releases/latest"
        return $r.tag_name
    } catch {
        return $null
    }
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

# ── Directories ───────────────────────────────────────────────────────────────

$root      = (Resolve-Path -LiteralPath (
                  [System.IO.Directory]::CreateDirectory($InstallDir).FullName
              )).Path
$obsDir    = Join-Path $root "obs-studio"
$pythonDir = Join-Path $root "python"
$ffmpegDir = Join-Path $root "ffmpeg"
$iniFile   = Join-Path $root "obsapp-config.ini"
$batFile   = Join-Path $root "run-obsapp.bat"

$isUpdate  = Test-Path (Join-Path $pythonDir "python.exe")

if (-not $isUpdate) {
    # On a fresh install the directory must be empty.
    if ((Get-ChildItem $root -Force | Measure-Object).Count -gt 0) {
        Abort "InstallDir '$root' is not empty.  Choose an empty or non-existent directory."
    }
}

$tmp = Join-Path ([System.IO.Path]::GetTempPath()) "obsapp-install-$PID"
New-Item -ItemType Directory -Path $tmp -Force | Out-Null

try {

# ── OBS Studio ────────────────────────────────────────────────────────────────

Write-Step "OBS Studio"

if (Test-Path (Join-Path $obsDir "bin\64bit\obs64.exe")) {
    $v = Get-FileVersion (Join-Path $obsDir "bin\64bit\obs64.exe")
    if ($v -lt $OBS_MIN_VER) {
        Abort "Installed OBS ($v) is older than the required minimum ($OBS_MIN_VER).`nDelete '$obsDir' and re-run to download a fresh copy."
    }
    Write-Skip "OBS $v"
} else {
    $obsTag = Get-GitHubLatestTag $OBS_REPO
    if (-not $obsTag) { Abort "Could not determine latest OBS release from GitHub." }
    $obsVer = $obsTag.TrimStart('v')
    $obsUrl = "https://github.com/$OBS_REPO/releases/download/$obsTag/OBS-Studio-$obsVer-Windows.zip"
    $obsZip = Join-Path $tmp "obs.zip"
    Save-File $obsUrl $obsZip
    Write-Host "    extracting ..."
    Expand-IntoDir $obsZip $obsDir
    Write-OK "OBS $obsVer installed to $obsDir"
}

# ── Python (embeddable) ───────────────────────────────────────────────────────

Write-Step "Python $PYTHON_VER (embeddable)"

if (Test-Path (Join-Path $pythonDir "python.exe")) {
    Write-Skip "Python (found at $pythonDir\python.exe)"
} else {
    $pyUrl = "https://www.python.org/ftp/python/$PYTHON_VER/python-$PYTHON_VER-embed-amd64.zip"
    $pyZip = Join-Path $tmp "python-embed.zip"
    Save-File $pyUrl $pyZip
    Write-Host "    extracting ..."
    New-Item -ItemType Directory -Path $pythonDir -Force | Out-Null
    Expand-Archive -Path $pyZip -DestinationPath $pythonDir -Force

    # The embeddable distribution disables site-packages by default.
    # Uncomment "import site" in the ._pth file to enable pip installs.
    $pthFile = Get-ChildItem $pythonDir -Filter "*._pth" | Select-Object -First 1
    if (-not $pthFile) { Abort "Could not find ._pth file in Python embeddable zip." }
    $pthContent = Get-Content $pthFile.FullName -Raw
    $pthContent = $pthContent -replace '#import site', 'import site'
    Set-Content $pthFile.FullName $pthContent -NoNewline

    # Bootstrap pip
    Write-Host "    installing pip ..."
    $getPip = Join-Path $tmp "get-pip.py"
    Save-File "https://bootstrap.pypa.io/get-pip.py" $getPip
    & "$pythonDir\python.exe" $getPip --quiet
    if ($LASTEXITCODE -ne 0) { Abort "pip bootstrap failed." }

    Write-OK "Python $PYTHON_VER installed to $pythonDir"
}

$pip    = Join-Path $pythonDir "Scripts\pip.exe"
$python = Join-Path $pythonDir "python.exe"

# ── FFmpeg ────────────────────────────────────────────────────────────────────

Write-Step "FFmpeg"

if (Test-Path (Join-Path $ffmpegDir "bin\ffmpeg.exe")) {
    Write-Skip "FFmpeg (found at $ffmpegDir\bin\ffmpeg.exe)"
} else {
    $ffmpegZip = Join-Path $tmp "ffmpeg.zip"
    Save-File $FFMPEG_URL $ffmpegZip
    Write-Host "    extracting ..."
    Expand-IntoDir $ffmpegZip $ffmpegDir
    Write-OK "FFmpeg installed to $ffmpegDir"
}

# ── OBSapp ────────────────────────────────────────────────────────────────────

Write-Step "OBSapp"

if ($Current) {
    $obsappUrl = "https://github.com/$OBSAPP_REPO/archive/refs/heads/main.zip"
    Write-Host "    installing from main branch ..."
} else {
    $tag = Get-GitHubLatestTag $OBSAPP_REPO
    if ($tag) {
        $obsappUrl = "https://github.com/$OBSAPP_REPO/archive/refs/tags/$tag.zip"
        Write-Host "    installing release $tag ..."
    } else {
        Write-Host "    no release found; falling back to main branch ..." -ForegroundColor Yellow
        $obsappUrl = "https://github.com/$OBSAPP_REPO/archive/refs/heads/main.zip"
    }
}

& $pip install $obsappUrl --quiet
if ($LASTEXITCODE -ne 0) { Abort "OBSapp installation via pip failed." }
Write-OK "OBSapp installed"

# ── Config file ───────────────────────────────────────────────────────────────

Write-Step "Configuration"

$obsExe    = Join-Path $obsDir    "bin\64bit\obs64.exe"
$ffmpegExe = Join-Path $ffmpegDir "bin\ffmpeg.exe"

if (-not (Test-Path $iniFile)) {
    @"
[obsappliance]
obs_executable     = $obsExe
ffmpeg_executable  = $ffmpegExe
"@ | Set-Content $iniFile
    Write-OK "Created $iniFile"
} else {
    Write-Skip "Config file (not overwritten on update)"
}

# ── Launcher ──────────────────────────────────────────────────────────────────

Write-Step "Launcher"

# pythonw.exe suppresses the console window for a GUI application.
@"
@echo off
start "" "%~dp0python\pythonw.exe" -m obsapp.main "%~dp0obsapp-config.ini" %*
"@ | Set-Content $batFile
Write-OK "Created $batFile"

# ── Desktop shortcut ──────────────────────────────────────────────────────────

Write-Step "Desktop shortcut"

# Find the installed icon; fall back to the OBS executable's icon.
$icoPath = Get-ChildItem "$pythonDir\Lib\site-packages\obsapp\resources" `
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

} finally {
    Remove-Item $tmp -Recurse -Force -ErrorAction SilentlyContinue
}

Write-Host @"

Done.  Installation layout:
  $root\
    obs-studio\        OBS Studio portable
    python\            Python $PYTHON_VER + OBSapp
    ffmpeg\            FFmpeg
    obsapp-config.ini  edit to adjust paths if needed
    run-obsapp.bat     launch from the command line

A desktop shortcut 'OBSapp' has been created.

To update OBSapp later, re-run this script with the same InstallDir.
"@ -ForegroundColor Green
