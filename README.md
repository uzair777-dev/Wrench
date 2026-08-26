# Wrench

Wrench is a free and open-source, native Linux desktop Git client built with Qt/PySide6, targeting simplicity, PR-centric workflows, and rich visual history management. It is designed for seamless local repository management and forge collaboration across GitHub, GitLab, Forgejo/Gitea, and Bitbucket.

**Status:** Alpha — Core Local Git Engine & MVP UI complete (Phase 1).

---

## Quickstart & Development Environment

### 1. Daily Development (Activate venv & Shell Aliases)

To initialize or activate the development environment with all CLI shortcuts in your active terminal, run:

```bash
source init-dev.sh
```

*(Note: Use `source` so the aliases and `.venv` are loaded into your active shell).*

### 2. Full Setup / CI Verification

To perform a clean setup (installing dependencies in editable mode, configuring pre-commit hooks, and running the full test suite):

```bash
./init-dev.sh
```

---

## Available Developer Commands & Aliases

Once `source init-dev.sh` is executed (or by running scripts directly from `bin/`), the following commands are available:

| Command | Action | Direct Path Alternative |
|---|---|---|
| `wrench-run` | Launch Wrench desktop application (`python -m wrench.app`) | `./bin/wrench-run` |
| `wrench-test` | Run all pytest suites with verbose output | `./bin/wrench-test` |
| `wrench-lint` | Check Ruff linting & Black formatting | `./bin/wrench-lint` |
| `wrench-format` | Auto-format codebase with Ruff and Black | `./bin/wrench-format` |
| `wrench-ci-check` | Run the full verification pipeline (lint + format check + test suite) | `./bin/wrench-ci-check` |
| `wrench` | Wrench CLI entry point | `.venv/bin/wrench` |

---

## Architecture & Tech Stack

- **GUI Framework:** PySide6 (Qt 6.11+)
- **Git Operations:**
  - Fast read-only queries (status, log, diff, blame): `pygit2` (libgit2 C bindings)
  - Write operations & staging (commit, branch, stash, apply): Subprocess Git CLI
- **Local Storage:** SQLite (`~/.local/share/wrench/wrench.db` via `platformdirs`)
- **File System Monitoring:** `watchdog` (Inotify) with Qt-debounced event pipeline
- **Testing:** `pytest`, `pytest-qt`

---

## Documentation

- **[dev/planning/implementation-plan.md](dev/planning/implementation-plan.md)**: Phased technical architecture and implementation roadmap.
- **[dev/planning/srs.md](dev/planning/srs.md)**: Software Requirements Specification.

---

## License

GNU Affero General Public License v3.0 ([LICENSE](LICENSE)).

test
