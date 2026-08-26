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

# 1. Virtual Environment Setup
if [ ! -d ".venv" ]; then
    echo -e "${YELLOW}Creating Python virtual environment (.venv)...${RESET}"
    python3 -m venv .venv
fi

# 2. Activate virtual environment
if [ -f ".venv/bin/activate" ]; then
    # shellcheck source=/dev/null
    source .venv/bin/activate
    echo -e "${GREEN}✓ Virtual environment activated (${CYAN}.venv${GREEN})${RESET}"
fi

# 3. If executed directly (not sourced), ensure dependencies & pre-commit are installed
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    echo -e "\n${YELLOW}Checking and installing dependencies (editable dev mode)...${RESET}"
    pip install -e ".[dev]" --no-build-isolation 2>/dev/null || pip install -e ".[dev]"

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
alias wrench-run="python -m wrench.app"
alias wrench-test="pytest -v"
alias wrench-lint="ruff check . && black --check ."
alias wrench-format="ruff check --fix . && black ."
alias wrench-ci-check="ruff check . && black --check . && pytest -v"

echo -e "\n${BOLD}Available Developer Commands / Aliases:${RESET}"
echo -e "  ${CYAN}wrench-run${RESET}       : Launch Wrench application (${BOLD}python -m wrench.app${RESET})"
echo -e "  ${CYAN}wrench-test${RESET}      : Run all pytest suites (${BOLD}pytest -v${RESET})"
echo -e "  ${CYAN}wrench-lint${RESET}      : Check ruff linting & black formatting"
echo -e "  ${CYAN}wrench-format${RESET}    : Auto-format codebase with ruff & black"
echo -e "  ${CYAN}wrench-ci-check${RESET} : Run full lint, style, and unit test checks"
echo -e "  ${CYAN}wrench${RESET}           : Wrench CLI entry point"
echo ""
