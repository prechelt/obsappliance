#!/usr/bin/env bash
# install.sh — Install OBSapp on Linux or macOS.
#
# Usage:
#   bash install.sh [--current] [--no-sudo]
#
#   --current   Install from the main branch instead of the latest release.
#   --no-sudo   Do not run sudo.  Checks which system packages are missing;
#               if any, prints the required install command(s) and exits so
#               the user (or an admin) can run them before re-invoking this
#               script.  On macOS this flag has no effect (Homebrew does not
#               use sudo).
#
# What this script does:
#   1. Installs OBS Studio, FFmpeg, and Python 3.10+ via the system package
#      manager (Linux: apt/dnf/pacman/zypper; macOS: Homebrew).  If they are
#      already present in a sufficient version they are left untouched.
#   2. Creates a dedicated venv at ~/.local/share/obsapp/venv.
#   3. Installs OBSapp into that venv from GitHub.
#   4. Writes a config file to ~/.config/obsapp/obsapp-config.ini.
#   5. Writes a launcher script to ~/.local/bin/obsapp.
#   6. Places a desktop shortcut (Linux: .desktop file; macOS: .app bundle).
#
# Re-running this script only reinstalls OBSapp (step 3); system packages and
# the venv are left in place.  Use this to update OBSapp to a newer release.
#
# Requirements:
#   Linux : one of apt / dnf / pacman / zypper; internet access; a desktop
#           environment (OBS requires a display).
#   macOS : Homebrew (https://brew.sh); internet access.

set -euo pipefail

# ── Constants ─────────────────────────────────────────────────────────────────

OBSAPP_REPO="prechelt/obsappliance"
OBS_MIN_MAJOR=28       # OBS 28+ has obs-websocket 5.x built in
PYTHON_MIN="3.10"

VENV_DIR="$HOME/.local/share/obsapp/venv"
CONFIG_DIR="$HOME/.config/obsapp"
CONFIG_FILE="$CONFIG_DIR/obsapp-config.ini"
BIN_DIR="$HOME/.local/bin"
LAUNCHER="$BIN_DIR/obsapp"

# ── Argument parsing ──────────────────────────────────────────────────────────

USE_CURRENT=0
NO_SUDO=0
for arg in "$@"; do
    case "$arg" in
        --current) USE_CURRENT=1 ;;
        --no-sudo) NO_SUDO=1 ;;
        *) echo "Unknown argument: $arg" >&2; exit 1 ;;
    esac
done

_nosudo_pkgs=()    # package names to install (populated in --no-sudo mode)
_nosudo_precmds=() # commands to run before the main install (PPA/repo setup)

# ── Helpers ───────────────────────────────────────────────────────────────────

cyan()   { printf '\033[0;36m==> %s\033[0m\n' "$*"; }
green()  { printf '\033[0;32m    ok: %s\033[0m\n' "$*"; }
yellow() { printf '\033[0;33m    skip: %s (already present)\033[0m\n' "$*"; }
abort()  { printf '\033[0;31m\nERROR: %s\033[0m\n' "$*" >&2; exit 1; }

# version_gte A B — returns 0 (true) if version A >= B (dot-separated integers)
version_gte() {
    local a="$1" b="$2"
    IFS='.' read -ra av <<< "$a"
    IFS='.' read -ra bv <<< "$b"
    local i
    for (( i=0; i<${#bv[@]}; i++ )); do
        local va="${av[$i]:-0}" vb="${bv[$i]:-0}"
        (( va > vb )) && return 0
        (( va < vb )) && return 1
    done
    return 0
}

github_latest_tag() {
    curl -sf "https://api.github.com/repos/$1/releases/latest" \
        | grep '"tag_name"' | head -1 | cut -d'"' -f4
}

# ── Platform detection ────────────────────────────────────────────────────────

case "$(uname -s)" in
    Linux*)  PLATFORM=linux  ;;
    Darwin*) PLATFORM=macos  ;;
    *)       abort "Unsupported platform: $(uname -s)" ;;
esac

# Homebrew does not use sudo, so --no-sudo is a no-op on macOS.
if [[ "$PLATFORM" == "macos" && "$NO_SUDO" -eq 1 ]]; then
    echo "Note: --no-sudo has no effect on macOS (Homebrew does not use sudo); proceeding normally."
    NO_SUDO=0
fi

# ── Package manager (Linux only) ──────────────────────────────────────────────

if [[ "$PLATFORM" == "linux" ]]; then
    if   command -v apt-get &>/dev/null; then PKG_MGR=apt
    elif command -v dnf     &>/dev/null; then PKG_MGR=dnf
    elif command -v pacman  &>/dev/null; then PKG_MGR=pacman
    elif command -v zypper  &>/dev/null; then PKG_MGR=zypper
    else abort "No supported package manager found (apt/dnf/pacman/zypper)."
    fi
fi

# ── macOS: require Homebrew ───────────────────────────────────────────────────

if [[ "$PLATFORM" == "macos" ]]; then
    if ! command -v brew &>/dev/null; then
        abort "Homebrew is required but not installed.\nInstall it from https://brew.sh and re-run this script."
    fi
fi

# ── Install system package helper ─────────────────────────────────────────────

install_pkg() {
    # install_pkg <friendly-name> <apt-pkg> <dnf-pkg> <pacman-pkg> <zypper-pkg>
    local name="$1" apt_p="$2" dnf_p="$3" pac_p="$4" zpp_p="$5"
    if [[ "$NO_SUDO" -eq 1 ]]; then
        case "$PKG_MGR" in
            apt)    _nosudo_pkgs+=("$apt_p") ;;
            dnf)    _nosudo_pkgs+=("$dnf_p") ;;
            pacman) _nosudo_pkgs+=("$pac_p") ;;
            zypper) _nosudo_pkgs+=("$zpp_p") ;;
        esac
        return
    fi
    echo "    installing $name ..."
    case "$PKG_MGR" in
        apt)    sudo apt-get install -y "$apt_p" ;;
        dnf)    sudo dnf install -y "$dnf_p" ;;
        pacman) sudo pacman -S --noconfirm "$pac_p" ;;
        zypper) sudo zypper install -y "$zpp_p" ;;
    esac
}

# nosudo_flush — if any packages were collected in --no-sudo mode, print the
# install command(s) and exit; otherwise return silently (nothing to do).
nosudo_flush() {
    [[ ${#_nosudo_pkgs[@]} -eq 0 && ${#_nosudo_precmds[@]} -eq 0 ]] && return 0
    printf '\n\033[0;33mSome system packages need to be installed.\033[0m\n'
    printf 'Please run the following, then re-run:  bash install.sh --no-sudo\n\n'
    local cmd
    for cmd in "${_nosudo_precmds[@]}"; do
        printf '    %s\n' "$cmd"
    done
    if [[ ${#_nosudo_pkgs[@]} -gt 0 ]]; then
        case "$PKG_MGR" in
            apt)    printf '    sudo apt-get install -y %s\n' "${_nosudo_pkgs[*]}" ;;
            dnf)    printf '    sudo dnf install -y %s\n' "${_nosudo_pkgs[*]}" ;;
            pacman) printf '    sudo pacman -S --noconfirm %s\n' "${_nosudo_pkgs[*]}" ;;
            zypper) printf '    sudo zypper install -y %s\n' "${_nosudo_pkgs[*]}" ;;
        esac
    fi
    printf '\n'
    exit 0
}

# ── OBS Studio ────────────────────────────────────────────────────────────────

cyan "OBS Studio"

obs_exe=""
obs_ver=""

find_obs() {
    if [[ "$PLATFORM" == "macos" ]]; then
        if [[ -x "/Applications/OBS.app/Contents/MacOS/obs" ]]; then
            obs_exe="/Applications/OBS.app/Contents/MacOS/obs"
        fi
    else
        obs_exe=$(command -v obs 2>/dev/null || true)
    fi

    if [[ -n "$obs_exe" ]]; then
        obs_ver=$("$obs_exe" --version 2>&1 | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1 || true)
    fi
}

find_obs

if [[ -n "$obs_ver" ]] && version_gte "$obs_ver" "$OBS_MIN_MAJOR.0"; then
    yellow "OBS $obs_ver"
elif [[ -n "$obs_ver" ]]; then
    abort "OBS $obs_ver is installed but the minimum required version is $OBS_MIN_MAJOR.0.\nPlease update OBS via your package manager and re-run."
else
    if [[ "$PLATFORM" == "macos" ]]; then
        echo "    installing OBS via Homebrew Cask ..."
        brew install --cask obs
        obs_exe="/Applications/OBS.app/Contents/MacOS/obs"
    else
        case "$PKG_MGR" in
            apt)
                # OBS is not in the default Ubuntu/Debian repos; use the official PPA.
                if ! apt-cache show obs-studio &>/dev/null; then
                    if [[ "$NO_SUDO" -eq 1 ]]; then
                        command -v add-apt-repository &>/dev/null || \
                            _nosudo_precmds+=("sudo apt-get install -y software-properties-common")
                        _nosudo_precmds+=("sudo add-apt-repository -y ppa:obsproject/obs-studio")
                        _nosudo_precmds+=("sudo apt-get update")
                    else
                        echo "    adding OBS PPA ..."
                        command -v add-apt-repository &>/dev/null || \
                            sudo apt-get install -y software-properties-common
                        sudo add-apt-repository -y ppa:obsproject/obs-studio
                        sudo apt-get update -q
                    fi
                fi
                install_pkg "OBS Studio" obs-studio obs-studio obs-studio obs-studio
                ;;
            *)
                install_pkg "OBS Studio" obs-studio obs-studio obs-studio obs-studio
                ;;
        esac
        if [[ "$NO_SUDO" -eq 0 ]]; then
            obs_exe=$(command -v obs 2>/dev/null) || abort "OBS installation succeeded but 'obs' not found in PATH."
        fi
    fi
    if [[ "$NO_SUDO" -eq 0 ]]; then
        find_obs
        [[ -n "$obs_ver" ]] || abort "OBS was installed but its version could not be determined."
        version_gte "$obs_ver" "$OBS_MIN_MAJOR.0" || \
            abort "OBS $obs_ver was installed but version >= $OBS_MIN_MAJOR.0 is required.\nUpdate OBS via your package manager and re-run."
        green "OBS $obs_ver installed"
    fi
fi

# ── FFmpeg ────────────────────────────────────────────────────────────────────

cyan "FFmpeg"

if command -v ffmpeg &>/dev/null; then
    ffmpeg_ver=$(ffmpeg -version 2>&1 | head -n 1 | awk '{print $3}' || true)
    yellow "FFmpeg $ffmpeg_ver"
else
    if [[ "$PLATFORM" == "macos" ]]; then
        echo "    installing FFmpeg via Homebrew ..."
        brew install ffmpeg
    else
        case "$PKG_MGR" in
            dnf)
                # FFmpeg is in RPM Fusion free repo; enable it if needed.
                if ! dnf list installed ffmpeg &>/dev/null; then
                    if grep -q '^ID=fedora$' /etc/os-release 2>/dev/null; then
                        rpmfusion_url="https://mirrors.rpmfusion.org/free/fedora/rpmfusion-free-release-$(rpm -E %fedora).noarch.rpm"
                    else
                        rpmfusion_url="https://mirrors.rpmfusion.org/free/el/rpmfusion-free-release-$(rpm -E %rhel).noarch.rpm"
                    fi
                    if [[ "$NO_SUDO" -eq 1 ]]; then
                        _nosudo_precmds+=("sudo dnf install -y $rpmfusion_url")
                    else
                        echo "    enabling RPM Fusion free repo for FFmpeg ..."
                        sudo dnf install -y "$rpmfusion_url"
                    fi
                fi
                install_pkg "FFmpeg" ffmpeg ffmpeg ffmpeg ffmpeg
                ;;
            *)
                install_pkg "FFmpeg" ffmpeg ffmpeg ffmpeg ffmpeg
                ;;
        esac
    fi
    [[ "$NO_SUDO" -eq 0 ]] && green "FFmpeg installed"
fi

# ── Python 3.10+ ──────────────────────────────────────────────────────────────

cyan "Python >= $PYTHON_MIN"

python_exe=""

find_python() {
    for candidate in python3.13 python3.12 python3.11 python3.10 python3; do
        local exe
        exe=$(command -v "$candidate" 2>/dev/null || true)
        if [[ -n "$exe" ]]; then
            local ver
            ver=$("$exe" --version 2>&1 | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1)
            if [[ -n "$ver" ]] && version_gte "$ver" "$PYTHON_MIN"; then
                python_exe="$exe"
                return 0
            fi
        fi
    done
    return 1
}

if find_python; then
    py_ver=$("$python_exe" --version 2>&1 | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1)
    yellow "Python $py_ver ($python_exe)"
else
    if [[ "$PLATFORM" == "macos" ]]; then
        echo "    installing Python via Homebrew ..."
        brew install python@3.12
        find_python || abort "Python 3.12 was installed but cannot be found."
    else
        case "$PKG_MGR" in
            apt)    install_pkg "Python 3.12" python3.12 python3.12 python python3.12
                    install_pkg "python3-venv" python3.12-venv python3-venv python python3.12-venv ;;
            dnf)    install_pkg "Python 3.12" python3.12 python3.12 python python3.12 ;;
            pacman) install_pkg "Python"      python     python     python python ;;
            zypper) install_pkg "Python 3.12" python312  python3.12 python python3.12 ;;
        esac
        if [[ "$NO_SUDO" -eq 0 ]]; then
            find_python || abort "Python >= $PYTHON_MIN was installed but cannot be found."
        fi
    fi
    if [[ "$NO_SUDO" -eq 0 ]]; then
        py_ver=$("$python_exe" --version 2>&1 | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1)
        green "Python $py_ver installed"
    fi
fi

# Ensure python3-venv is available (needed to create the venv on Debian/Ubuntu).
# Skip when python_exe is empty: Python itself was just recorded as needed and
# the apt branch of install_pkg already included python3.12-venv.
if [[ "$PLATFORM" == "linux" ]] && [[ "$PKG_MGR" == "apt" ]] && [[ -n "$python_exe" ]]; then
    if ! "$python_exe" -m venv --help &>/dev/null; then
        py_venv_pkg="python$("$python_exe" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')-venv"
        if [[ "$NO_SUDO" -eq 1 ]]; then
            _nosudo_pkgs+=("$py_venv_pkg")
        else
            echo "    installing $py_venv_pkg ..."
            sudo apt-get install -y "$py_venv_pkg"
        fi
    fi
fi

# In --no-sudo mode: if any packages are needed, print install instructions and exit.
[[ "$NO_SUDO" -eq 1 ]] && nosudo_flush

# ── Venv ──────────────────────────────────────────────────────────────────────

cyan "Python venv ($VENV_DIR)"

if [[ ! -d "$VENV_DIR" ]]; then
    "$python_exe" -m venv "$VENV_DIR"
    green "venv created"
else
    yellow "venv"
fi

PIP="$VENV_DIR/bin/pip"
PYTHON_VENV="$VENV_DIR/bin/python"

# ── OBSapp ────────────────────────────────────────────────────────────────────

cyan "OBSapp"

if [[ "$USE_CURRENT" -eq 1 ]]; then
    obsapp_url="https://github.com/$OBSAPP_REPO/archive/refs/heads/main.tar.gz"
    echo "    installing from main branch ..."
else
    tag=$(github_latest_tag "$OBSAPP_REPO" || true)
    if [[ -n "$tag" ]]; then
        obsapp_url="https://github.com/$OBSAPP_REPO/archive/refs/tags/$tag.tar.gz"
        echo "    installing release $tag ..."
    else
        echo "    no release found; falling back to main branch ..."
        obsapp_url="https://github.com/$OBSAPP_REPO/archive/refs/heads/main.tar.gz"
    fi
fi

"$PIP" install --quiet "$obsapp_url"
green "OBSapp installed"

# ── Config file ───────────────────────────────────────────────────────────────

cyan "Configuration"

mkdir -p "$CONFIG_DIR"

if [[ ! -f "$CONFIG_FILE" ]]; then
    cat > "$CONFIG_FILE" <<EOF
[obsappliance]
obs_executable    = $obs_exe
ffmpeg_executable = ffmpeg
EOF
    green "Created $CONFIG_FILE"
else
    yellow "Config file (not overwritten on update)"
fi

# ── Launcher ──────────────────────────────────────────────────────────────────

cyan "Launcher ($LAUNCHER)"

mkdir -p "$BIN_DIR"

cat > "$LAUNCHER" <<EOF
#!/usr/bin/env bash
exec "$PYTHON_VENV" -m obsapp.main "$CONFIG_FILE" "\$@"
EOF
chmod +x "$LAUNCHER"
green "Created $LAUNCHER"

# Remind the user if ~/.local/bin is not yet on PATH.
if [[ ":$PATH:" != *":$BIN_DIR:"* ]]; then
    echo "    NOTE: Add $BIN_DIR to your PATH to run 'obsapp' from anywhere."
    echo "          e.g. add this to ~/.bashrc or ~/.zshrc:"
    echo "          export PATH=\"\$HOME/.local/bin:\$PATH\""
fi

# ── Desktop shortcut ──────────────────────────────────────────────────────────

cyan "Desktop shortcut"

# Locate the installed icon (glob through venv lib tree).
icon_png=$(ls "$VENV_DIR"/lib/python*/site-packages/obsapp/resources/obsapp-icon.png 2>/dev/null | head -1 || true)

if [[ "$PLATFORM" == "linux" ]]; then

    desktop_entry() {
        local dest="$1"
        mkdir -p "$(dirname "$dest")"
        cat > "$dest" <<EOF
[Desktop Entry]
Version=1.0
Type=Application
Name=OBSapp
Comment=OBS Studio Recording Appliance
Exec=$LAUNCHER
Icon=${icon_png:-utilities-terminal}
Terminal=false
Categories=AudioVideo;Video;
EOF
    }

    # Application menu entry
    desktop_entry "$HOME/.local/share/applications/obsapp.desktop"
    green "Application menu entry: ~/.local/share/applications/obsapp.desktop"

    # Desktop icon (if Desktop directory exists)
    if [[ -d "$HOME/Desktop" ]]; then
        desktop_entry "$HOME/Desktop/obsapp.desktop"
        chmod +x "$HOME/Desktop/obsapp.desktop"
        # Mark as trusted on GNOME (silently ignore if gio is absent).
        gio set "$HOME/Desktop/obsapp.desktop" metadata::trusted true 2>/dev/null || true
        green "Desktop shortcut: ~/Desktop/obsapp.desktop"
    fi

elif [[ "$PLATFORM" == "macos" ]]; then

    # Build a minimal .app bundle so macOS shows the correct icon and name.
    app_dir="$HOME/Desktop/OBSapp.app"
    macos_dir="$app_dir/Contents/MacOS"
    res_dir="$app_dir/Contents/Resources"
    mkdir -p "$macos_dir" "$res_dir"

    # Launcher executable inside the bundle
    cat > "$macos_dir/obsapp" <<EOF
#!/usr/bin/env bash
exec "$PYTHON_VENV" -m obsapp.main "$CONFIG_FILE" "\$@"
EOF
    chmod +x "$macos_dir/obsapp"

    # Convert PNG icon to ICNS using macOS built-in tools (sips + iconutil).
    if [[ -n "$icon_png" ]]; then
        iconset=$(mktemp -d).iconset
        mkdir -p "$iconset"
        for size in 16 32 64 128 256 512; do
            sips -z $size $size "$icon_png" --out "$iconset/icon_${size}x${size}.png" >/dev/null
        done
        sips -z 32   32   "$icon_png" --out "$iconset/icon_16x16@2x.png"   >/dev/null
        sips -z 64   64   "$icon_png" --out "$iconset/icon_32x32@2x.png"   >/dev/null
        sips -z 256  256  "$icon_png" --out "$iconset/icon_128x128@2x.png" >/dev/null
        sips -z 512  512  "$icon_png" --out "$iconset/icon_256x256@2x.png" >/dev/null
        sips -z 1024 1024 "$icon_png" --out "$iconset/icon_512x512@2x.png" >/dev/null
        iconutil -c icns "$iconset" -o "$res_dir/obsapp-icon.icns"
        rm -rf "$iconset"
        icon_key="<key>CFBundleIconFile</key><string>obsapp-icon</string>"
    else
        icon_key=""
    fi

    # Minimal Info.plist
    cat > "$app_dir/Contents/Info.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
    "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleExecutable</key>  <string>obsapp</string>
    <key>CFBundleIdentifier</key>  <string>de.prechelt.obsapp</string>
    <key>CFBundleName</key>        <string>OBSapp</string>
    <key>CFBundleVersion</key>     <string>1.0</string>
    <key>LSUIElement</key>         <false/>
    $icon_key
</dict>
</plist>
EOF

    green "Desktop app bundle: ~/Desktop/OBSapp.app"

fi

# ── Done ──────────────────────────────────────────────────────────────────────

printf '\n\033[0;32mDone.\033[0m\n'
cat <<EOF

  Config : $CONFIG_FILE
  Venv   : $VENV_DIR
  Launch : obsapp          (or double-click the desktop shortcut)

To update OBSapp later, re-run this script (use --current for the main branch).
EOF
