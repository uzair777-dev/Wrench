# Wrench

**Wrench** is a fast, native Linux desktop Git client built with Python and Qt (PySide6). It pairs the blazing-fast read performance of `pygit2`/libgit2 with the rock-solid fidelity of the system `git` CLI, wrapped in an elegant, tabbed user interface.

[![License: AGPL v3](https://img.shields.io/badge/License-AGPL_v3-blue.svg)](LICENSE)
[![Python: 3.12+](https://img.shields.io/badge/Python-3.12+-green.svg)](https://www.python.org/)
[![GUI: PySide6](https://img.shields.io/badge/GUI-PySide6%20%2F%20Qt%206-informational.svg)](https://www.qt.io/)
[![Tests: 376 passed](https://img.shields.io/badge/Tests-376%20passed-brightgreen.svg)](tests/)

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
- **Visual Topological Commit Graph**:
  - Interactive Git DAG rendering branching, merging, and octopus merge topologies with smooth cubic Bézier curves.
  - Deterministic 10-color lane persistence with slot recycling algorithm preventing lane explosion.
  - Infinite scrolling pagination with smooth per-pixel horizontal scrolling (`ScrollPerPixel`) and synchronized graph column scrollbar.
  - Integrated search, author filtering, and path filtering bar with 300ms debouncing.
- **Interactive 3-Way Merge Tool**:
  - Side-by-side "Ours" (Current Branch), "Base" (Common Ancestor), and "Theirs" (Incoming Branch) conflict resolution panes.
  - Block-level conflict acceptance (Take Ours, Take Theirs, Take Both, Manual Edit) with live merged output preview and automatic index staging.
- **Remotes & Synchronization**:
  - Background asynchronous `Fetch` (`Ctrl+Shift+F`), `Pull` (`Ctrl+Shift+L` with `--ff-only`), and `Push` (`Ctrl+Shift+U` with `--force-with-lease`).
  - Modal `BusyOperationDialog` with real-time percentage progress and cooperative cancellation (`threading.Event`).
  - Remotes manager dialog with reachability probing, add, edit, and deletion workflows.
  - Smart push error routing: distinguishes between non-fast-forward diverged branches and missing OAuth permissions (`WorkflowScopeRequiredError`).
- **Native Git Credential Helper**:
  - Standalone executable `git-credential-wrench` implementing the Git credential helper protocol.
  - Seamless FreeDesktop Secret Service D-Bus integration (`secretstorage` / `keyring` abstraction) without storing plaintext passwords or tokens on disk.
  - Strict host disambiguation preventing credential leakage across multiple accounts on the same forge.
- **Multi-Forge Integration (GitHub, GitLab, Forgejo/Gitea, Bitbucket Cloud)**:
  - **Assisted GitHub OAuth Setup (RFC 8628)**: Device Authorization Flow with in-browser authorization requesting `repo workflow` permissions, countdown timers, and in-place re-authorization.
  - **Pull Requests Tab & Issues Tab**: Searchable and filterable table views with Stale-While-Revalidate (SWR 60s) caching, live active repository switching, and new PR creation.
  - **PR & Issue Detail Views**: Single-entity retrieval, inline CI/CD status cards, in-app review submissions (`Approve`, `Request Changes`, `Comment`), local branch checkout, and external browser navigation.
  - **Enterprise & Self-Hosted Support**: Custom CA bundle (PEM) file picker and explicit skip-TLS verification options.
- **Local-First Safety & Recovery**:
  - Non-destructive rolling snapshots (`git stash create` commit objects + `.tar.gz` untracked archives) before risky operations.
  - Automated stale `.git/index.lock` detection and recovery with a 5-second grace window.
  - Reflog exploration and one-click branch restoration.
  - Wrench Crash Handler & Session Preserver ensuring drafts and uncommitted work are never lost.
- **Real-Time File Monitoring**: Inotify-backed filesystem watcher with 300ms debouncing and atomic file-save detection (tempfile rename handling).
- **Catppuccin Velvet Pastel Design System**: Native Latte (Light) and Mocha (Dark) pastel themes with luminance-based desktop detection and recursion-guarded palette propagation.

---

## Development Roadmap & Status

| Phase | Milestone | Status | Details |
|---|---|---|---|
| **Phase 1** | Core Git Engine & MVP Backend | **Completed** | [`phase-1.md`](dev/planning/phase-1.md) |
| **Phase 1.5** | UI Shell Overhaul & Hybrid Tabs | **Completed** | [`phase-1.5.md`](dev/planning/phase-1.5.md) |
| **Phase 2** | Visual Commit Graph & 3-Way Merge Tool | **Completed** | [`phase-2.md`](dev/planning/phase-2.md) |
| **Phase 3** | Remotes, Push/Pull & Credential Helper | **Completed** | [`phase-3.md`](dev/planning/phase-3.md) |
| **Phase 4** | Multi-Forge Integration (GitHub, GitLab, Forgejo, Bitbucket) | **Completed** | [`phase-4.md`](dev/planning/phase-4.md) |
| **Phase 5** | Flatpak Packaging, Native Integrations & Release Polish | *In Progress* | [`implementation-plan.md`](dev/planning/implementation-plan.md) |

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
| `wrench-test` | Run the complete pytest test suite (373 tests) | `./bin/wrench-test` |
| `wrench-lint` | Run Ruff linter and Black formatting checks | `./bin/wrench-lint` |
| `wrench-format` | Automatically fix and format code with Ruff/Black | `./bin/wrench-format` |
| `wrench-ci-check` | Run all linters, formatters, and unit tests in one step | `./bin/wrench-ci-check` |

---

## Architecture & Tech Stack

- **GUI Framework:** PySide6 (Qt 6.8+)
- **Git Engine:** `pygit2` (C libgit2 bindings) + System `git` CLI
- **HTTP Client:** `httpx` (HTTP/1.1 & HTTP/2 with custom TLS trust anchors)
- **Credential Storage:** `secretstorage` (FreeDesktop Secret Service D-Bus specification)
- **Local Storage:** SQLite (`~/.local/share/wrench/wrench.db` via `platformdirs`)
- **Filesystem Watcher:** `watchdog` (Inotify) with Qt debounce event pipeline
- **Testing:** `pytest`, `pytest-qt` (373 tests across unit, integration, and UI suites)

For an in-depth exploration of data flows, concurrency models, and database schemas, see **[ARCHITECTURE.md](ARCHITECTURE.md)**.

---

## Documentation

- **[ARCHITECTURE.md](ARCHITECTURE.md)**: Architectural design principles, data flow, and directory structure.
- **[dev/planning/ui-planning.md](dev/planning/ui-planning.md)**: Comprehensive UI layout, wireframes, and secondary surface specifications.
- **[dev/planning/implementation-plan.md](dev/planning/implementation-plan.md)**: Phased master checklist and technical implementation plan.
- **[dev/planning/srs.md](dev/planning/srs.md)**: Software Requirements Specification (FR-1 through FR-11).
- **[dev/planning/phase-1.md](dev/planning/phase-1.md)**: Phase 1 completion summary (Core engine & MVP).
- **[dev/planning/phase-1.5.md](dev/planning/phase-1.5.md)**: Phase 1.5 UI overhaul completion summary (Shell & tabs).
- **[dev/planning/phase-2.md](dev/planning/phase-2.md)**: Phase 2 completion summary (DAG commit graph & 3-way merge tool).
- **[dev/planning/phase-3.md](dev/planning/phase-3.md)**: Phase 3 completion summary (Remotes, sync & credential helper).
- **[dev/planning/phase-4.md](dev/planning/phase-4.md)**: Phase 4 completion summary (Multi-forge integration layer).

---

## License

GNU Affero General Public License v3.0 ([LICENSE](LICENSE)).
