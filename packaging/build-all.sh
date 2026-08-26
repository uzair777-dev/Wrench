#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "=== 1/2 Building Flatpak ==="
"${SCRIPT_DIR}/flatpak/build-flatpak.sh"

echo "=== 2/2 Building AppImage ==="
"${SCRIPT_DIR}/appimage/build-appimage.sh"

echo "=== All builds complete ==="
