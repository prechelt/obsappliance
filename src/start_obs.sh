#!/usr/bin/env bash
# Starter script for OBS Studio in OBSapp portable mode.
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
OBSAPPDIR="$(cd "$SCRIPT_DIR/.." && pwd)"
exec obs --portable --minimize-to-tray \
    --startrecording \
    --collection "OBSapp" \
    --profile "OBSapp" \
    "$@"
