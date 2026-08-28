# Wrench

**Wrench** is a fast, native Linux desktop Git client built with Python and Qt (PySide6). It pairs the blazing-fast read performance of `pygit2`/libgit2 with the rock-solid fidelity of the system `git` CLI, wrapped in an elegant, tabbed user interface.

[![License: AGPL v3](https://img.shields.io/badge/License-AGPL_v3-blue.svg)](LICENSE)
[![Python: 3.12+](https://img.shields.io/badge/Python-3.12+-green.svg)](https://www.python.org/)
[![GUI: PySide6](https://img.shields.io/badge/GUI-PySide6%20%2F%20Qt%206-informational.svg)](https://www.qt.io/)

---

## Key Features

- **Hybrid Git Core**: Fast in-memory status, diffs, and log traversal via `pygit2` (libgit2), combined with system `git` CLI execution for safe, conflict-aware write and staging operations.
- **Dynamic Tab Navigation**: Custom hybrid tab container supporting vertical (sidebar) and horizontal (top bar) modes, pinned non-closable Changes workspace, per-repo deduplication, and fast `Ctrl+1`..`Ctrl+9` keyboard switching.
- **Unified Changes Workspace**:
  - Borderless repository selector with auto-recovery for missing or relocated folders.
  - Interactive branch switcher (`🌿 main ▾` / `🔗 HEAD detached at {sha}`) with search filtering and uncommitted changes protection (`Stash & Switch`).
  - Unified changed files list with status badges (`M`, `A`, `D`, `R`, `?`, `⚠ C`), tri-state select-all checkbox, and context actions.
  - Commit box with forge account avatar, 72-character summary soft limit indicator, multi-line description, and one-click `--amend` pre-filling.
- **Granular Staging**: Whole-file staging, synthetic patch hunk-level staging, and line-level staging with syntax highlighting.
- **Local-First Safety & Recovery**:
  - Non-destructive rolling snapshots (`git stash create`) of dirty working trees.
  - Automated stale `.git/index.lock` detection and recovery with a 5-second grace period.
  - Reflog exploration and one-click branch restoration.
- **Real-Time File Monitoring**: Inotify-backed filesystem watcher with 300ms debouncing and atomic file-save detection (tempfile rename handling).

---

## Development Roadmap & Status

| Phase | Milestone | Status | Details |
|---|---|---|---|
| **Phase 1** | Core Git Engine & MVP Backend | **Completed** | [`phase-1.md`](dev/planning/phase-1.md) |
| **Phase 1.5** | UI Shell Overhaul & Hybrid Tabs | **Completed** | [`phase-1.5.md`](dev/planning/phase-1.5.md) |
| **Phase 2** | Visual Commit Graph & 3-Way Merge Tool | *Upcoming* | [`ui-planning.md §4, §6.6`](dev/planning/ui-planning.md) |
| **Phase 3** | Remotes, Push/Pull & Credential Helper | *Planned* | [`implementation-plan.md`](dev/planning/implementation-plan.md) |
| **Phase 4** | Multi-Forge Integration (GitHub, GitLab, Forgejo) | *Planned* | [`implementation-plan.md`](dev/planning/implementation-plan.md) |
| **Phase 5** | PR Centric Review, Polish & Packaging | *Planned* | Flatpak distribution |

---

## Quickstart & Development

### 1. Activate Environment & Aliases (Daily Development)

To initialize or activate the virtual environment with all development aliases:

```bash
source init-dev.sh
```

*(Note: Use `source` so the environment variables and aliases are loaded into your active shell).*

### 2. Clean Setup & Verification

To install dependencies in editable mode, set up git hooks, and run all tests:

```bash
./init-dev.sh
```

### 3. Available Developer Commands

| Command | Action | Direct Path Alternative |
|---|---|---|
| `wrench-run` | Launch the Wrench desktop application | `./bin/wrench-run` |
| `wrench-debug` | Launch with verbose `--debug` structured logging | `./bin/wrench-debug` |
| `wrench-test` | Run the complete pytest test suite | `./bin/wrench-test` |
| `wrench-lint` | Run Ruff linter and Black formatting checks | `./bin/wrench-lint` |
| `wrench-format` | Automatically fix and format code with Ruff/Black | `./bin/wrench-format` |
| `wrench-ci-check` | Run all linters, formatters, and unit tests in one step | `./bin/wrench-ci-check` |

---

## Architecture & Tech Stack

- **GUI Framework:** PySide6 (Qt 6.8+)
- **Git Engine:** `pygit2` (C libgit2 bindings) + System `git` CLI
- **Local Storage:** SQLite (`~/.local/share/wrench/wrench.db` via `platformdirs`)
- **Filesystem Watcher:** `watchdog` (Inotify) with Qt debounce event pipeline
- **Testing:** `pytest`, `pytest-qt`

For an in-depth exploration of data flows, concurrency models, and database schemas, see **[ARCHITECTURE.md](ARCHITECTURE.md)**.

---

## Documentation

- **[ARCHITECTURE.md](ARCHITECTURE.md)**: Architectural design principles, data flow, and directory structure.
- **[dev/planning/ui-planning.md](dev/planning/ui-planning.md)**: Comprehensive UI layout, wireframes, and secondary surface specifications.
- **[dev/planning/implementation-plan.md](dev/planning/implementation-plan.md)**: Phased master checklist and technical implementation plan.
- **[dev/planning/srs.md](dev/planning/srs.md)**: Software Requirements Specification (FR-1 through FR-11).
- **[dev/planning/phase-1.md](dev/planning/phase-1.md)**: Phase 1 completion summary.
- **[dev/planning/phase-1.5.md](dev/planning/phase-1.5.md)**: Phase 1.5 UI overhaul completion summary.

---

## License

GNU Affero General Public License v3.0 ([LICENSE](LICENSE)).
