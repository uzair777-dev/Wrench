# Wrench

**Wrench** is a fast, native Linux desktop Git client built with Python and Qt (PySide6). It pairs the blazing-fast read performance of `pygit2`/libgit2 with the rock-solid fidelity of the system `git` CLI, wrapped in an elegant, tabbed user interface.

[![License: AGPL v3](https://img.shields.io/badge/License-AGPL_v3-blue.svg)](LICENSE)
![GitHub Repo stars](https://img.shields.io/github/stars/uzair777-dev/Wrench)
[![Python: 3.15 Primary (3.12+ Compatible)](https://img.shields.io/badge/Python-3.15%20Primary%20(3.12+%20Compatible)-blue.svg)](https://www.python.org/)
[![GUI: PySide6](https://img.shields.io/badge/GUI-PySide6%20%2F%20Qt%206-informational.svg)](https://www.qt.io/)
[![Tests: 534 passed](https://img.shields.io/badge/Tests-534%20passed-brightgreen.svg)](tests/)
![GitHub Actions Workflow Status](https://img.shields.io/github/actions/workflow/status/uzair777-dev/Wrench/ci.yml)

---

> [!WARNING]
> 1. Its only for linux as of now, but its foundation for cross-platform compatibility is being laid and is scheduled for v3, as i want to make it stable on one platform first rather than doing all at once.
> 2. I do not recommend this for production use yet, but it can be used for personal use until full v2 spec and stability lands. 



---

## Key Features

- **Hybrid Git Core**: Fast in-memory status, diffs, and log traversal via `pygit2` (libgit2), combined with system `git` CLI execution for safe, conflict-aware write and staging operations.
- **Dynamic Tab Navigation**: Custom hybrid tab container supporting vertical (sidebar) and horizontal (top bar) modes, pinned non-closable Changes workspace, per-repo deduplication, and fast `Ctrl+1`..`Ctrl+9` keyboard switching.
- **Multi-Repository Directory Discovery (FR-1.12)**:
  - Bounded (depth $\le 3$) non-blocking background scanner (`discover_repos`) with cooperative cancellation and live progress counters.
  - Automatic branching from `_on_open_repo` when a picked folder is not a Git repo.
  - Interactive `DiscoverReposDialog` with Select All / Deselect All, tri-state selection, worktree `.git`-file detection, symlink cycle protection, and atomic batch registry import with missing-status recovery (`clear_missing`).
- **Python 3.15 Engine & Native Explicit Lazy Imports (PEP 810)**:
  - Primary development runtime powered by Python 3.15 with backwards-compatible support for Python 3.12+.
  - Native `lazy import <mod>` syntax deferring heavyweight startup modules (`secretstorage`, `platformdirs`, `httpx`, `watchdog`), eliminating cold-start latency.
  - Fully integrated with high-speed `uv` and `uvx` package management, offline test runners, and automated C-extension compilation.
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
  - **Granular Push Error Protection & Recovery**: Distinguishes non-fast-forward diverged branches, missing Actions scopes (`WorkflowScopeRequiredError`), Secret Scanning blocks (`GH007` with direct unblock URLs), Protected Branch rulesets (`GH006` with guided new-branch creation and checkout), Large File quota rejections (`GH001`), Signed Commit requirements (`GH008`), and 403 Permission Denied.
- **Native Git Credential Helper**:
  - Standalone executable `git-credential-wrench` implementing the Git credential helper protocol.
  - Seamless FreeDesktop Secret Service D-Bus integration (`secretstorage` / `keyring` abstraction) without storing plaintext passwords or tokens on disk.
  - Strict host disambiguation preventing credential leakage across multiple accounts on the same forge.
- **Multi-Forge Integration (GitHub, GitLab, Forgejo/Gitea, Bitbucket Cloud)**:
  - **Assisted GitHub OAuth Setup (RFC 8628)**: Device Authorization Flow with in-browser authorization, customizable advanced scopes (`repo`, `workflow`, `user:email`, `read:org`), countdown timers, and in-place re-authorization.
  - **Auto-Aligned Local Identity**: Automatically synchronizes repository-local `user.name` and verified `user.email` from the linked forge account.
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
| **Phase 1** | Core Local Git Engine & MVP UI | **Completed** | [`phase-1.md`](dev/planning/phase-1.md) |
| **Phase 1.5** | UI Shell Overhaul & Hybrid Tabs | **Completed** | [`phase-1.5.md`](dev/planning/phase-1.5.md) |
| **Phase 2** | Visual Commit Graph & 3-Way Merge Tool | **Completed** | [`phase-2.md`](dev/planning/phase-2.md) |
| **Phase 3** | Remote Operations, Push/Pull & Credential Helper | **Completed** | [`phase-3.md`](dev/planning/phase-3.md) |
| **Phase 4** | Multi-Forge Integration (GitHub, GitLab, Forgejo, Bitbucket) | **Completed** | [`phase-4.md`](dev/planning/phase-4.md) |
| **Phase 4.5** | Multi-Repository Directory Discovery & `uv` Tooling | **Completed** | [`phase-4.5.md`](dev/planning/phase-4.5.md) |
| **Phase 4.6** | Operation Feedback & Delight (Progress, Activity Log, Humor) | *Next in line* | [`implementation-plan.md`](dev/planning/implementation-plan.md) |
| **Phase 5** | Git LFS & Submodules | *Planned* | [`implementation-plan.md`](dev/planning/implementation-plan.md) |
| **Phase 6** | Packaging Hardening & Flathub Submission | *Planned* | [`implementation-plan.md`](dev/planning/implementation-plan.md) |
| **Phase 7** | v1 Polish & Final Release | *Planned* | [`implementation-plan.md`](dev/planning/implementation-plan.md) |
| **Phase 8** | v2 Backlog (Interactive Rebase, GPG Signing, SourceForge) | *Planned (v2)* | [`v2-implementation-plan.md`](dev/planning/v2-implementation-plan.md) |

---

## Quickstart & Development

### 1. Modern Package Management (`uv` & `uvx`) & Python 3.15

Wrench utilizes `uv` and `uvx` for fast, reproducible dependency resolution, sub-second virtual environment management, and ephemeral tool execution under Python 3.15:

```bash
# Clone the repository
git clone https://github.com/uzair777-dev/Wrench.git
cd Wrench

# All-in-one bootstrap script (handles Python 3.15, uv, and C-extension compilation):
./init-dev.sh

# Or activate into your terminal:
source init-dev.sh
```

#### Manual Virtual Environment Creation (Python 3.15):
```bash
# Provision Python 3.15 virtual environment with uv
uv venv .venv --python 3.15
source .venv/bin/activate

# Install dependencies (C_INCLUDE_PATH / LIBRARY_PATH are automatically configured by init-dev.sh)
uv pip install -e ".[dev]"
```

For complete details on building native C extensions (`pygit2`, `cffi`) and dynamic linker configuration, see **[dev/planning/python-315-migration.md](dev/planning/python-315-migration.md)**.

### 2. Available Developer Commands

All developer binaries in `bin/` leverage `uv run --no-sync` for fast, offline execution:

| Command | Action | Direct Path Alternative |
|---|---|---|
| `wrench-run` | Launch the Wrench desktop application | `./bin/wrench-run` |
| `wrench-debug` | Launch with verbose `--debug` structured logging | `./bin/wrench-debug` |
| `wrench-test` | Run the complete pytest test suite via `uv run` | `./bin/wrench-test` |
| `wrench-lint` | Run Ruff linter and Black formatting checks via `uv run` | `./bin/wrench-lint` |
| `wrench-format` | Automatically fix and format code with Ruff/Black via `uv run` | `./bin/wrench-format` |
| `wrench-ci-check` | Run all linters, formatters, and unit tests in one step | `./bin/wrench-ci-check` |

---

## Architecture & Tech Stack

- **GUI Framework:** PySide6 (Qt 6.8+ / Qt 6.12 via Python Stable ABI `abi3`)
- **Git Engine:** `pygit2` (C libgit2 bindings) + System `git` CLI
- **Tooling & Package Management:** `uv` & `uvx` 0.13+ (sub-second dependency resolution)
- **Runtime & Optimization:** Python 3.15.0 primary runtime (PEP 810 native `lazy import` support & `LazyProxyModule` fallback, `requires-python = ">=3.12"`)
- **HTTP Client:** `httpx` (HTTP/1.1 & HTTP/2 with custom TLS trust anchors, lazily imported)
- **Credential Storage:** `secretstorage` (FreeDesktop Secret Service D-Bus specification, lazily imported)
- **Local Storage:** SQLite (`~/.local/share/wrench/wrench.db` via `platformdirs`, lazily imported)
- **Filesystem Watcher:** `watchdog` (Inotify) with Qt debounce event pipeline
- **Testing:** `pytest`, `pytest-qt` (534 passed tests across unit, integration, and UI suites)

For an in-depth exploration of data flows, concurrency models, and database schemas, see **[ARCHITECTURE.md](ARCHITECTURE.md)**.

---

## Documentation

- **[ARCHITECTURE.md](ARCHITECTURE.md)**: Architectural design principles, data flow, and directory structure.
- **[dev/planning/python-315-migration.md](dev/planning/python-315-migration.md)**: Python 3.15 migration guide, PEP 810 lazy imports, and C-extension compilation.
- **[dev/planning/ui-planning.md](dev/planning/ui-planning.md)**: Comprehensive UI layout, wireframes, and secondary surface specifications.
- **[dev/planning/implementation-plan.md](dev/planning/implementation-plan.md)**: Phased master checklist and technical implementation plan.
- **[dev/planning/srs.md](dev/planning/srs.md)**: Software Requirements Specification (FR-1 through FR-11).
- **[dev/planning/phase-1.md](dev/planning/phase-1.md)**: Phase 1 completion summary (Core engine & MVP).
- **[dev/planning/phase-1.5.md](dev/planning/phase-1.5.md)**: Phase 1.5 UI overhaul completion summary (Shell & tabs).
- **[dev/planning/phase-2.md](dev/planning/phase-2.md)**: Phase 2 completion summary (DAG commit graph & 3-way merge tool).
- **[dev/planning/phase-3.md](dev/planning/phase-3.md)**: Phase 3 completion summary (Remotes, sync & credential helper).
- **[dev/planning/phase-4.md](dev/planning/phase-4.md)**: Phase 4 completion summary (Multi-forge integration layer).
- **[dev/planning/phase-4.5.md](dev/planning/phase-4.5.md)**: Phase 4.5 completion summary (Multi-repository directory discovery, uv tooling & Python 3.15 migration).
- **[dev/planning/v2-implementation-plan.md](dev/planning/v2-implementation-plan.md)**: v2 deferred roadmap and backlog specifications.

---

## License

GNU Affero General Public License v3.0 ([LICENSE](LICENSE)).
