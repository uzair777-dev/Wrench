#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"

echo "Building AppImage via Briefcase..."
cd "${ROOT_DIR}"
briefcase build linux appimage
briefcase package linux appimage
echo "AppImage build complete."
