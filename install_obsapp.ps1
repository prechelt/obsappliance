#Requires -Version 5.1
<#
.SYNOPSIS
    OBSapp installer for Windows.
.DESCRIPTION
    Usage: powershell -ExecutionPolicy Bypass -File install_obsapp.ps1
       or: irm <raw-url> | iex
#>

$ErrorActionPreference = "Stop"

# ── Configuration ──────────────────────────────────────────────────────────
$OBSAPPDIR       = if ($env:OBSAPPDIR) { $env:OBSAPPDIR } else { Join-Path $HOME "obsapp" }
$MIN_OBS_VERSION = [version]"30.2"
$MIN_OBS_VERSION = [version]"32.0.3"  #  TODO: remove, it's for testing only
$MIN_PYTHON_VERSION = [version]"3.10"
$OBS_VERSION     = "32.1.0"
# OBS_ZIP_URL is built dynamically in Install-ObsPortable (needs arch)
$PYTHON_VERSION  = "3.12.8"
$REPO_URL        = "https://github.com/prechelt/obsappliance"

# ── Helpers ────────────────────────────────────────────────────────────────
function Info  ($msg) { Write-Host "[info]  $msg" -ForegroundColor Blue }
function Warn  ($msg) { Write-Host "[warn]  $msg" -ForegroundColor Yellow }
function Err   ($msg) { Write-Host "[error] $msg" -ForegroundColor Red }
function Die   ($msg) { Err $msg; exit 1 }

function Test-VersionGe([version]$actual, [version]$minimum) {
    return $actual -ge $minimum
}

function Download-File($url, $outFile) {
    # curl.exe (ships with Windows 10+) shows a progress bar natively
    $curl = Get-Command curl.exe -ErrorAction SilentlyContinue
    if ($curl) {
        & curl.exe -fSL --progress-bar -o $outFile $url
        if ($LASTEXITCODE -ne 0) { Die "Download failed: $url" }
    } else {
        Invoke-WebRequest -Uri $url -OutFile $outFile -UseBasicParsing
    }
}

function Get-Arch {
    $arch = $env:PROCESSOR_ARCHITECTURE
    switch ($arch) {
        "AMD64" { return "x86_64" }
        "ARM64" { return "aarch64" }
        default { Die "Unsupported architecture: $arch" }
    }
}

# ── Step 1: Check / install OBS Studio ─────────────────────────────────────
function Get-ObsVersion {
    # Check common install locations
    $candidates = @(
        (Join-Path $OBSAPPDIR "obsstudio\bin\64bit\obs64.exe"),
        "${env:ProgramFiles}\obs-studio\bin\64bit\obs64.exe",
        "${env:ProgramFiles(x86)}\obs-studio\bin\64bit\obs64.exe"
    )
    foreach ($path in $candidates) {
        if (Test-Path $path) {
            $verInfo = (Get-Item $path).VersionInfo.ProductVersion
            if ($verInfo -match '(\d+\.\d+(\.\d+)?)') {
                return [version]$Matches[1]
            }
        }
    }
    # Try PATH
    $obs = Get-Command obs64.exe -ErrorAction SilentlyContinue
    if ($obs) {
        $verInfo = (Get-Item $obs.Source).VersionInfo.ProductVersion
        if ($verInfo -match '(\d+\.\d+(\.\d+)?)') {
            return [version]$Matches[1]
        }
    }
    return $null
}

function Install-ObsPortable {
    $arch = Get-Arch
    $obsPlatform = switch ($arch) {
        "x86_64"  { "x64" }
        "aarch64" { "arm64" }
    }
    $OBS_ZIP_URL = "https://github.com/obsproject/obs-studio/releases/download/$OBS_VERSION/OBS-Studio-${OBS_VERSION}-Windows-${obsPlatform}.zip"
    Info "Downloading OBS Studio $OBS_VERSION portable..."
    Info "  URL: $OBS_ZIP_URL"

    $tmpZip = Join-Path $env:TEMP "obs-studio-portable.zip"
    $tmpDir = Join-Path $env:TEMP "obs-studio-extract"

    Download-File $OBS_ZIP_URL $tmpZip

    Info "Extracting OBS Studio to $OBSAPPDIR\obsstudio..."
    if (Test-Path $tmpDir) { Remove-Item $tmpDir -Recurse -Force }
    Expand-Archive -Path $tmpZip -DestinationPath $tmpDir -Force

    # The zip typically contains a top-level folder; move its contents
    $innerDirs = Get-ChildItem $tmpDir -Directory
    $sourceDir = if ($innerDirs.Count -eq 1) { $innerDirs[0].FullName } else { $tmpDir }

    $obsTarget = Join-Path $OBSAPPDIR "obsstudio"
    if (-not (Test-Path $obsTarget)) { New-Item -ItemType Directory -Path $obsTarget -Force | Out-Null }
    Copy-Item -Path "$sourceDir\*" -Destination $obsTarget -Recurse -Force

    Remove-Item $tmpZip -Force -ErrorAction SilentlyContinue
    Remove-Item $tmpDir -Recurse -Force -ErrorAction SilentlyContinue

    $obsExe = Join-Path $obsTarget "bin\64bit\obs64.exe"
    if (-not (Test-Path $obsExe)) {
        Die "OBS extraction failed - $obsExe not found."
    }
    Info "OBS Studio portable installed at $obsTarget"
}

function Setup-Obs {
    $obsVersion = Get-ObsVersion
    if ($obsVersion -and (Test-VersionGe $obsVersion $MIN_OBS_VERSION)) {
        Info "Found OBS Studio $obsVersion (>= $MIN_OBS_VERSION). Good."
    } else {
        if ($obsVersion) {
            Warn "Found OBS Studio $obsVersion, but need >= $MIN_OBS_VERSION."
        } else {
            Warn "OBS Studio not found."
        }
        Info "Will download OBS Studio $OBS_VERSION portable (no admin rights needed)."
        $answer = Read-Host "Download and install OBS Studio portable? [y/N]"
        if ($answer -notmatch '^[yY]') {
            Die "OBS Studio `>= $MIN_OBS_VERSION is required. Please install it manually and re-run."
        }
        Install-ObsPortable
    }
    New-Item -ItemType Directory -Path (Join-Path $OBSAPPDIR "obsstudio") -Force | Out-Null
}

# ── Step 2: Check / install Python ─────────────────────────────────────────
function Get-PythonCmd {
    # Check system Python
    foreach ($cmd in @("python3", "python")) {
        $pyCmd = Get-Command $cmd -ErrorAction SilentlyContinue
        if ($pyCmd) {
            try {
                $ver = & $pyCmd.Source -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>$null
                if ($ver -and (Test-VersionGe ([version]$ver) $MIN_PYTHON_VERSION)) {
                    return $pyCmd.Source
                }
            } catch { }
        }
    }
    # Check previously installed standalone
    $standalone = Join-Path $OBSAPPDIR "python\python.exe"
    if (Test-Path $standalone) {
        return $standalone
    }
    return $null
}

function Install-Python {
    $arch = Get-Arch
    $suffix = switch ($arch) {
        "x86_64"  { "amd64" }
        "aarch64" { "arm64" }
        default   { Die "No Python installer available for Windows/$arch" }
    }
    $url = "https://www.python.org/ftp/python/$PYTHON_VERSION/python-$PYTHON_VERSION-$suffix.exe"

    Info "Downloading Python $PYTHON_VERSION from python.org..."
    Info "  URL: $url"

    $tmpInstaller = Join-Path $env:TEMP "python-$PYTHON_VERSION-installer.exe"
    Download-File $url $tmpInstaller

    $pythonTarget = Join-Path $OBSAPPDIR "python"
    Info "Installing Python to $pythonTarget (silent, no admin required)..."
    Start-Process -FilePath $tmpInstaller -ArgumentList `
        "/quiet InstallAllUsers=0 TargetDir=$pythonTarget Include_launcher=0 Include_test=0 Include_doc=0 AssociateFiles=0 Shortcuts=0 Include_tcltk=0" `
        -Wait -NoNewWindow

    Remove-Item $tmpInstaller -Force -ErrorAction SilentlyContinue

    $pyExe = Join-Path $pythonTarget "python.exe"
    if (-not (Test-Path $pyExe)) {
        Die "Python installation failed - $pyExe not found."
    }
    Info "Python installed at $pythonTarget"
}

function Setup-Python {
    $script:PythonCmd = Get-PythonCmd
    if ($script:PythonCmd) {
        $ver = & $script:PythonCmd -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')"
        Info "Found Python $ver at $($script:PythonCmd). Good."
    } else {
        Info "No suitable Python >= $MIN_PYTHON_VERSION found on system."
        Install-Python
        $script:PythonCmd = Join-Path $OBSAPPDIR "python\python.exe"
    }
}

# ── Step 3: Install OBSapp code ────────────────────────────────────────────
function Install-ObsappCode {
    # Determine source: running from repo or downloaded?
    $scriptDir = if ($PSScriptRoot) { $PSScriptRoot } else { Split-Path -Parent $MyInvocation.ScriptName }
    $pyprojectLocal = Join-Path $scriptDir "pyproject.toml"

    if ($scriptDir -and (Test-Path $pyprojectLocal)) {
        Info "Installing OBSapp from local repo at $scriptDir"
    } else {
        Info "Downloading OBSapp from $REPO_URL..."
        $tmpDir = Join-Path $env:TEMP "obsappliance-download"
        if (Test-Path $tmpDir) { Remove-Item $tmpDir -Recurse -Force }

        $zipUrl = "$REPO_URL/archive/refs/heads/main.zip"
        $tmpZip = Join-Path $env:TEMP "obsappliance.zip"
        Download-File $zipUrl $tmpZip
        Expand-Archive -Path $tmpZip -DestinationPath $tmpDir -Force
        Remove-Item $tmpZip -Force -ErrorAction SilentlyContinue
        $scriptDir = Join-Path $tmpDir "obsappliance-main"
    }

    $obsappTarget = Join-Path $OBSAPPDIR "obsapp"
    New-Item -ItemType Directory -Path $obsappTarget -Force | Out-Null
    Copy-Item -Path (Join-Path $scriptDir "src\obsapp\*") -Destination $obsappTarget -Recurse -Force
    Copy-Item -Path (Join-Path $scriptDir "pyproject.toml") -Destination $OBSAPPDIR -Force
    Copy-Item -Path (Join-Path $scriptDir "src\start_obs.bat") -Destination (Join-Path $OBSAPPDIR "obsstudio\start_obs.bat") -Force
    Info "OBSapp code installed to $obsappTarget"
}

# ── Step 4: Create venv and install dependencies ───────────────────────────
function Setup-Venv {
    $venvDir = Join-Path $OBSAPPDIR "venv"
    $venvPython = Join-Path $venvDir "Scripts\python.exe"

    Info "Creating virtual environment at $venvDir..."
    & $script:PythonCmd -m venv $venvDir
    if ($LASTEXITCODE -ne 0) { Die "Failed to create virtual environment." }

    Info "Upgrading pip..."
    & $venvPython -m pip install --upgrade pip --quiet
    if ($LASTEXITCODE -ne 0) { Die "Failed to upgrade pip." }

    Info "Installing dependencies from pyproject.toml..."
    & $venvPython -m pip install $OBSAPPDIR --quiet
    if ($LASTEXITCODE -ne 0) { Die "Failed to install dependencies." }

    Info "Dependencies installed."
}

# ── Step 5: Desktop shortcut ──────────────────────────────────────────────
function Create-DesktopIcon {
    # Icon is already copied as part of src\obsapp\resources\ in Install-ObsappCode

    # Create desktop shortcut via COM
    $desktopPath = [Environment]::GetFolderPath("Desktop")
    if ($desktopPath -and (Test-Path $desktopPath)) {
        $shortcutPath = Join-Path $desktopPath "OBSapp.lnk"
        $obsappExe = Join-Path $OBSAPPDIR "venv\Scripts\obsapp.exe"
        $shell = New-Object -ComObject WScript.Shell
        $shortcut = $shell.CreateShortcut($shortcutPath)
        $shortcut.TargetPath = $obsappExe
        $shortcut.WorkingDirectory = $OBSAPPDIR
        $shortcut.Description = "OBSapp - Screen recording appliance"
        $shortcut.Save()
        Info "Desktop shortcut created at $shortcutPath"
    } else {
        Warn "Desktop folder not found. Skipping shortcut."
    }
}

# ── Main ───────────────────────────────────────────────────────────────────
function Main {
    Info "OBSapp installer (Windows)"
    Info "Install directory: $OBSAPPDIR"
    Write-Host ""

    $arch = Get-Arch
    Info "Detected: Windows / $arch"
    Write-Host ""

    Setup-Obs
    Write-Host ""

    Setup-Python
    Write-Host ""

    Install-ObsappCode
    Write-Host ""

    Setup-Venv
    Write-Host ""

    Create-DesktopIcon
    Write-Host ""

    $obsappExe = Join-Path $OBSAPPDIR "venv\Scripts\obsapp.exe"
    Info "Installation complete!"
    Info "Run OBSapp with: $obsappExe"
}

Main
