#!/usr/bin/env bash
#
# OBSapp installer for Linux and macOS.
# Usage: bash install_obsapp.sh
#        or: curl <raw-url> | bash
#
set -euo pipefail

# ── Configuration ──────────────────────────────────────────────────────────
OBSAPPDIR="${OBSAPPDIR:-$HOME/obsapp}"
MIN_OBS_VERSION="30.2"
MIN_PYTHON_VERSION="3.10"
PYTHON_STANDALONE_VERSION="3.12.8"
PYTHON_STANDALONE_TAG="20250106"
REPO_URL="https://github.com/prechelt/obsappliance"

# ── Helpers ────────────────────────────────────────────────────────────────
info()  { printf '\033[1;34m[info]\033[0m  %s\n' "$*"; }
warn()  { printf '\033[1;33m[warn]\033[0m  %s\n' "$*"; }
err()   { printf '\033[1;31m[error]\033[0m %s\n' "$*" >&2; }
die()   { err "$@"; exit 1; }

# Compare two dotted version strings: returns 0 if $1 >= $2
version_ge() {
    printf '%s\n%s\n' "$2" "$1" | sort -t. -k1,1n -k2,2n -k3,3n -C
}

detect_os() {
    case "$(uname -s)" in
        Linux*)  echo "linux" ;;
        Darwin*) echo "macos" ;;
        *)       die "Unsupported OS: $(uname -s)" ;;
    esac
}

detect_arch() {
    case "$(uname -m)" in
        x86_64|amd64)  echo "x86_64" ;;
        aarch64|arm64) echo "aarch64" ;;
        *)             die "Unsupported architecture: $(uname -m)" ;;
    esac
}

detect_linux_distro() {
    if [ -f /etc/os-release ]; then
        . /etc/os-release
        echo "$ID"
    else
        die "Cannot detect Linux distribution (no /etc/os-release)"
    fi
}

# ── Step 1: Check / install OBS Studio ─────────────────────────────────────
get_obs_version() {
    if command -v obs >/dev/null 2>&1; then
        obs --version 2>/dev/null | grep -oP '\d+\.\d+(\.\d+)?' | head -1
    else
        echo ""
    fi
}

install_obs_linux() {
    local distro
    distro="$(detect_linux_distro)"
    info "OBS Studio not found or too old. Offering to install via package manager."
    case "$distro" in
        debian|ubuntu|linuxmint|pop)
            echo "  Will run: sudo apt-get install -y obs-studio"
            ;;
        fedora)
            echo "  Will run: sudo dnf install -y obs-studio"
            ;;
        arch|manjaro|endeavouros)
            echo "  Will run: sudo pacman -S --noconfirm obs-studio"
            ;;
        *)
            die "Unsupported Linux distribution '$distro'. Please install OBS Studio >= $MIN_OBS_VERSION manually."
            ;;
    esac
    read -rp "Install OBS Studio system-wide? This requires sudo. [y/N] " answer
    case "$answer" in
        [yY]|[yY][eE][sS]) ;;
        *) die "OBS Studio >= $MIN_OBS_VERSION is required. Please install it manually and re-run." ;;
    esac
    case "$distro" in
        debian|ubuntu|linuxmint|pop)
            sudo apt-get update && sudo apt-get install -y obs-studio
            ;;
        fedora)
            sudo dnf install -y obs-studio
            ;;
        arch|manjaro|endeavouros)
            sudo pacman -S --noconfirm obs-studio
            ;;
    esac
}

install_obs_macos() {
    if command -v brew >/dev/null 2>&1; then
        info "OBS Studio not found or too old. Offering to install via Homebrew."
        echo "  Will run: brew install --cask obs"
        read -rp "Install OBS Studio via Homebrew? [y/N] " answer
        case "$answer" in
            [yY]|[yY][eE][sS]) brew install --cask obs ;;
            *) die "OBS Studio >= $MIN_OBS_VERSION is required. Please install it manually and re-run." ;;
        esac
    else
        die "OBS Studio >= $MIN_OBS_VERSION not found and Homebrew is not available.
Please install OBS Studio from https://obsproject.com/download and re-run."
    fi
}

setup_obs() {
    local os="$1"
    local obs_version
    obs_version="$(get_obs_version)"

    if [ -n "$obs_version" ] && version_ge "$obs_version" "$MIN_OBS_VERSION"; then
        info "Found OBS Studio $obs_version (>= $MIN_OBS_VERSION). Good."
    else
        if [ -n "$obs_version" ]; then
            warn "Found OBS Studio $obs_version, but need >= $MIN_OBS_VERSION."
        else
            warn "OBS Studio not found."
        fi
        case "$os" in
            linux) install_obs_linux ;;
            macos) install_obs_macos ;;
        esac
        obs_version="$(get_obs_version)"
        if [ -z "$obs_version" ] || ! version_ge "$obs_version" "$MIN_OBS_VERSION"; then
            die "OBS Studio installation failed or version is still too old ($obs_version)."
        fi
        info "OBS Studio $obs_version installed successfully."
    fi

    # Place starter script (copied in install_obsapp_code)
    mkdir -p "$OBSAPPDIR/obsstudio"
}

# ── Step 2: Check / install Python ─────────────────────────────────────────
get_python_cmd() {
    # Try python3 first, then python
    for cmd in python3 python; do
        if command -v "$cmd" >/dev/null 2>&1; then
            local ver
            ver="$("$cmd" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null)" || continue
            if version_ge "$ver" "$MIN_PYTHON_VERSION"; then
                echo "$cmd"
                return 0
            fi
        fi
    done
    # Check if we already installed standalone Python
    if [ -x "$OBSAPPDIR/python/bin/python3" ]; then
        echo "$OBSAPPDIR/python/bin/python3"
        return 0
    fi
    return 1
}

download_python_standalone() {
    # Will be used rarely, because even old-ish distros will have a suitable Python installed already
    local os="$1" arch="$2"
    local platform_triple
    case "${os}_${arch}" in
        linux_x86_64)   platform_triple="x86_64-unknown-linux-gnu" ;;
        linux_aarch64)  platform_triple="aarch64-unknown-linux-gnu" ;;
        macos_x86_64)   platform_triple="x86_64-apple-darwin" ;;
        macos_aarch64)  platform_triple="aarch64-apple-darwin" ;;
        *) die "No standalone Python build available for ${os}/${arch}" ;;
    esac

    local url="https://github.com/indygreg/python-build-standalone/releases/download/${PYTHON_STANDALONE_TAG}/cpython-${PYTHON_STANDALONE_VERSION}+${PYTHON_STANDALONE_TAG}-${platform_triple}-install_only.tar.gz"

    info "Downloading standalone Python ${PYTHON_STANDALONE_VERSION}..."
    info "  URL: $url"
    mkdir -p "$OBSAPPDIR/python"

    local tmpfile
    tmpfile="$(mktemp)"
    if command -v curl >/dev/null 2>&1; then
        curl -fSL --progress-bar -o "$tmpfile" "$url"
    elif command -v wget >/dev/null 2>&1; then
        wget -q --show-progress -O "$tmpfile" "$url"
    else
        die "Neither curl nor wget found. Cannot download Python."
    fi

    info "Extracting Python to $OBSAPPDIR/python..."
    tar -xzf "$tmpfile" -C "$OBSAPPDIR/python" --strip-components=1
    rm -f "$tmpfile"

    if [ ! -x "$OBSAPPDIR/python/bin/python3" ]; then
        die "Python extraction failed — $OBSAPPDIR/python/bin/python3 not found."
    fi
    info "Standalone Python installed at $OBSAPPDIR/python/"
}

setup_python() {
    local os="$1" arch="$2"
    local python_cmd
    if python_cmd="$(get_python_cmd)"; then
        local ver
        ver="$("$python_cmd" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}")')"
        info "Found Python $ver at $python_cmd. Good."
    else
        info "No suitable Python >= $MIN_PYTHON_VERSION found on system."
        download_python_standalone "$os" "$arch"
        python_cmd="$OBSAPPDIR/python/bin/python3"
    fi
    # Export for later use (the Python we'll use will eventually be the one in the venv)
    PYTHON_CMD="$python_cmd"
}

# ── Step 3: Install OBSapp code ────────────────────────────────────────────
install_obsapp_code() {
    local script_dir
    # Determine source: are we running from the repo or from a curl pipe?
    if [ -f "$(dirname "${BASH_SOURCE[0]:-$0}")/pyproject.toml" ]; then
        script_dir="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
        info "Installing OBSapp from local repo at $script_dir"
    else
        info "Downloading OBSapp from $REPO_URL..."
        local tmpdir
        tmpdir="$(mktemp -d)"
        if command -v git >/dev/null 2>&1; then
            git clone --depth 1 "$REPO_URL.git" "$tmpdir/obsappliance"
        else
            curl -fSL -o "$tmpdir/repo.tar.gz" "$REPO_URL/archive/refs/heads/main.tar.gz"
            tar -xzf "$tmpdir/repo.tar.gz" -C "$tmpdir"
            mv "$tmpdir"/obsappliance-main "$tmpdir/obsappliance"
        fi
        script_dir="$tmpdir/obsappliance"
    fi

    mkdir -p "$OBSAPPDIR/obsapp"
    cp -r "$script_dir/src/obsapp/"* "$OBSAPPDIR/obsapp/"
    cp "$script_dir/pyproject.toml" "$OBSAPPDIR/"
    cp "$script_dir/src/start_obs.sh" "$OBSAPPDIR/obsstudio/start_obs.sh"
    chmod +x "$OBSAPPDIR/obsstudio/start_obs.sh"
    cp "$script_dir/src/obsapp.desktop" "$OBSAPPDIR/obsapp/"
    cp "$script_dir/src/OBSapp.command" "$OBSAPPDIR/obsapp/"
    info "OBSapp code installed to $OBSAPPDIR/obsapp/"
}

# ── Step 4: Create venv and install dependencies ───────────────────────────
setup_venv() {
    info "Creating virtual environment at $OBSAPPDIR/venv..."
    "$PYTHON_CMD" -m venv "$OBSAPPDIR/venv"

    info "Installing dependencies from pyproject.toml..."
    "$OBSAPPDIR/venv/bin/pip" install --upgrade pip --quiet
    "$OBSAPPDIR/venv/bin/pip" install "$OBSAPPDIR" --quiet

    info "Dependencies installed."
}

# ── Step 5: Desktop icon ──────────────────────────────────────────────────
create_desktop_icon() {
    local os="$1"

    # Template files use __OBSAPPDIR__ as placeholder, substituted here.

    if [ "$os" = "linux" ]; then
        mkdir -p "$HOME/.local/share/applications"
        sed "s|__OBSAPPDIR__|$OBSAPPDIR|g" "$OBSAPPDIR/obsapp/obsapp.desktop" \
            > "$HOME/.local/share/applications/obsapp.desktop"
        # Also copy to Desktop if it exists
        if [ -d "$HOME/Desktop" ]; then
            cp "$HOME/.local/share/applications/obsapp.desktop" "$HOME/Desktop/obsapp.desktop"
            chmod +x "$HOME/Desktop/obsapp.desktop"
        fi
        info "Desktop icon created."

    elif [ "$os" = "macos" ]; then
        if [ -d "$HOME/Desktop" ]; then
            sed "s|__OBSAPPDIR__|$OBSAPPDIR|g" "$OBSAPPDIR/obsapp/OBSapp.command" \
                > "$HOME/Desktop/OBSapp.command"
            chmod +x "$HOME/Desktop/OBSapp.command"
            info "Desktop launcher created at ~/Desktop/OBSapp.command"
        else
            warn "~/Desktop not found. Skipping desktop icon."
        fi
    fi
}

# ── Main ───────────────────────────────────────────────────────────────────
main() {
    info "OBSapp installer"
    info "Install directory: $OBSAPPDIR"
    echo

    local os arch
    os="$(detect_os)"
    arch="$(detect_arch)"
    info "Detected: $os / $arch"
    echo

    setup_obs "$os"
    echo

    setup_python "$os" "$arch"
    echo

    install_obsapp_code
    echo

    setup_venv
    echo

    create_desktop_icon "$os"
    echo

    info "Installation complete!"
    info "Run OBSapp with: $OBSAPPDIR/venv/bin/obsapp"
}

main "$@"
