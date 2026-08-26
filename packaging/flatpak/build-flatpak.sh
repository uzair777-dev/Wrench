#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"

echo "Building Flatpak..."
flatpak-builder --user --install --force-clean "${ROOT_DIR}/build-dir" "${SCRIPT_DIR}/io.github.uzair.Wrench.yaml"
echo "Flatpak build complete."
