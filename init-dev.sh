#!/usr/bin/env bash
# ==============================================================================
# Wrench — Developer Environment Initialization & Shell Helper
#
# Usage:
#   1. Initial Setup:
#        ./init-dev.sh
#
#   2. Daily Development (Activate venv + aliases in current shell):
#        source init-dev.sh
# ==============================================================================

# Determine project root directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}"

# Color formatting helpers
BOLD="\033[1m"
GREEN="\033[32m"
BLUE="\033[34m"
YELLOW="\033[33m"
CYAN="\033[36m"
RESET="\033[0m"

echo -e "${BOLD}${BLUE}🔧 Wrench Developer Environment${RESET}"
echo -e "Project root: ${CYAN}${SCRIPT_DIR}${RESET}\n"

# Configure libgit2 and libffi search paths if vendored/local build exists
if [ -d "${SCRIPT_DIR}/.build/libgit2/usr/lib64" ]; then
    export LD_LIBRARY_PATH="${SCRIPT_DIR}/.build/libgit2/usr/lib64:${LD_LIBRARY_PATH}"
    export C_INCLUDE_PATH="${SCRIPT_DIR}/.build/libgit2/usr/include:${SCRIPT_DIR}/.build/libffi/usr/include:${C_INCLUDE_PATH}"
    export LIBRARY_PATH="${SCRIPT_DIR}/.build/libgit2/usr/lib64:${SCRIPT_DIR}/.build/libffi/usr/lib64:${LIBRARY_PATH}"
    export PKG_CONFIG_PATH="${SCRIPT_DIR}/.build/libgit2/usr/lib64/pkgconfig:${SCRIPT_DIR}/.build/libffi/usr/lib64/pkgconfig:${PKG_CONFIG_PATH}"
    export LIBGIT2="${SCRIPT_DIR}/.build/libgit2/usr"
fi

# 1. Virtual Environment Setup
if [ ! -d ".venv" ]; then
    echo -e "${YELLOW}Creating Python virtual environment (.venv)...${RESET}"
    PYTHON_315_BIN=""
    if [ -x "${SCRIPT_DIR}/.uv_python/cpython-3.15.0-linux-x86_64-gnu/bin/python3.15" ]; then
        PYTHON_315_BIN="${SCRIPT_DIR}/.uv_python/cpython-3.15.0-linux-x86_64-gnu/bin/python3.15"
    elif command -v python3.15 &>/dev/null; then
        PYTHON_315_BIN="$(command -v python3.15)"
    fi

    UV_BIN=""
    if command -v uv &>/dev/null; then
        UV_BIN="$(command -v uv)"
    elif [ -x "${SCRIPT_DIR}/.build/bin/uv" ]; then
        UV_BIN="${SCRIPT_DIR}/.build/bin/uv"
    fi

    if [ -n "${UV_BIN}" ] && [ -n "${PYTHON_315_BIN}" ]; then
        "${UV_BIN}" venv .venv --python "${PYTHON_315_BIN}"
        cp "${UV_BIN%/*}/uv"* .venv/bin/ 2>/dev/null || true
    elif [ -n "${PYTHON_315_BIN}" ]; then
        "${PYTHON_315_BIN}" -m venv .venv
    else
        python3 -m venv .venv
    fi
fi

# 2. Activate virtual environment
if [ -f ".venv/bin/activate" ]; then
    # shellcheck source=/dev/null
    source .venv/bin/activate
    echo -e "${GREEN}✓ Virtual environment activated (${CYAN}.venv${GREEN})${RESET}"
fi

# 3. If executed directly (not sourced), ensure dependencies & pre-commit are installed
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    if [ -f ".venv/bin/uv" ]; then
        .venv/bin/uv pip install -e ".[dev]"
    elif command -v uv &>/dev/null; then
        uv pip install -e ".[dev]"
    else
        pip install -e ".[dev]" --no-build-isolation 2>/dev/null || pip install -e ".[dev]"
    fi

    echo -e "\n${YELLOW}Setting up bin/ CLI helpers in .venv/bin/...${RESET}"
    chmod +x bin/*
    ln -sf "${SCRIPT_DIR}/bin/"* "${SCRIPT_DIR}/.venv/bin/"

    echo -e "\n${YELLOW}Setting up pre-commit hooks...${RESET}"
    pre-commit install

    echo -e "\n${YELLOW}Running test suite verification...${RESET}"
    pytest -v

    echo -e "\n${BOLD}${GREEN}======================================================${RESET}"
    echo -e "${BOLD}${GREEN}✓ Setup complete!${RESET}"
    echo -e "To activate the environment and aliases in your terminal, run:"
    echo -e "  ${BOLD}${CYAN}source init-dev.sh${RESET}"
    echo -e "${BOLD}${GREEN}======================================================${RESET}\n"
fi

# 4. Developer Aliases (Active when sourced into the interactive shell)
alias wrench-run="${SCRIPT_DIR}/bin/wrench-run"
alias wrench-debug="${SCRIPT_DIR}/bin/wrench-debug"
alias wrench-test="${SCRIPT_DIR}/bin/wrench-test"
alias wrench-lint="${SCRIPT_DIR}/bin/wrench-lint"
alias wrench-format="${SCRIPT_DIR}/bin/wrench-format"
alias wrench-ci-check="${SCRIPT_DIR}/bin/wrench-ci-check"

echo -e "\n${BOLD}Available Developer Commands / Aliases:${RESET}"
echo -e "  ${CYAN}wrench-run${RESET}       : Launch Wrench application (${BOLD}python -m wrench.app${RESET})"
echo -e "  ${CYAN}wrench-debug${RESET}     : Launch Wrench with verbose debug logging (${BOLD}--debug${RESET})"
echo -e "  ${CYAN}wrench-test${RESET}      : Run all pytest suites (${BOLD}pytest -v${RESET})"
echo -e "  ${CYAN}wrench-lint${RESET}      : Check ruff linting & black formatting"
echo -e "  ${CYAN}wrench-format${RESET}    : Auto-format codebase with ruff & black"
echo -e "  ${CYAN}wrench-ci-check${RESET} : Run full lint, style, and unit test checks"
echo -e "  ${CYAN}wrench${RESET}           : Wrench CLI entry point"
echo ""
