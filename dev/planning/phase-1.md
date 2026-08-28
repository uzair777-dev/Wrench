# Phase 1 Summary: Core Git Engine & MVP UI

**Status:** Completed  
**Associated SRS Requirements:** FR-1.1 – FR-1.10, FR-2.1, FR-10.1 – FR-10.5, FR-10.7, FR-11.2  
**Test Suite Coverage:** 48/48 unit, integration, and UI tests passing

---

## 1. Overview & Objectives

Phase 1 established the core foundations of Wrench:
1. **Hybrid Core Git Engine**: Fast, in-memory read operations via `pygit2`/libgit2 and robust subprocess write operations via the system `git` CLI.
2. **Local Metadata Storage**: Thread-safe SQLite persistence for repository registry, settings, and rolling local snapshots.
3. **Staging Engine**: Granular staging support including whole files, individual hunks via synthetic patch application, and line-level staging.
4. **Safety & Recovery Subsystems**: Automatic stale lock detection and recovery (`.git/index.lock`), non-destructive rolling snapshots, and reflog-based branch restoration.
5. **Real-time Filesystem Watching**: Inotify-backed filesystem observer with 300ms debounce handling atomic saves (tempfile-rename patterns).
6. **Thread-Safe PySide6 UI**: MVP desktop shell with a repository sidebar, staging list, syntax-highlighted diff viewer, and main-thread queued callback dispatching.
7. **Developer Tooling & Diagnostics**: Developer bootstrap scripts, CLI alias wrappers (`wrench-run`, `wrench-debug`, `wrench-test`, `wrench-lint`, `wrench-format`, `wrench-ci-check`), and non-intrusive debug logging.

---

## 2. Implemented Components

### 2.1 Core Read Engine (`src/wrench/core/read_ops.py`)
- **`get_status(repo)`**: Translates `pygit2` status bitmasks into `RepoStatus` / `FileChange` structures. Explicitly handles:
  - Unborn branches (fresh repositories with zero commits without throwing errors on `head.target`).
  - Detached HEAD states (populating `is_detached=True` and `detached_head_sha`).
  - Upstream tracking with ahead/behind commit calculations.
  - Conflict detection via index conflict state.
- **`get_diff(repo, path, staged)`**: Generates structured `Diff`, `Hunk`, and `DiffLine` models with line origins (`+`, `-`, ` `) and line number mappings. Detects binary files and avoids text rendering.
- **`get_log(repo, filter, limit, offset)`**: Topological + chronological commit history traversal.
- **`blame(repo, path)`**: Per-line commit attribution (`BlameLine`).

### 2.2 Core Write Engine (`src/wrench/core/write_ops.py`)
- **`run_git(repo_path, args, timeout)`**: Unified subprocess runner enforcing `GIT_TERMINAL_PROMPT=0` to prevent hanging, debug logging of commands and execution timings, and error conversion to typed `GitCommandError` with detailed stderr.
- **Branch Management**: `create_branch`, `switch_branch` (using git's modern `switch`), `delete_branch` (safe `-d` with force `-D` escalation), `rename_branch`.
- **Commits & Stash**: `commit` (with message validation and `--amend` support), `stash_create`, `stash_apply`, `stash_drop`.

### 2.3 Staging Granularity (`src/wrench/core/engine.py`)
- **Whole-File Staging**: Direct `pygit2` index manipulation (`index.add`, `index.remove`, `index.write`).
- **Hunk-Level Staging (`stage_hunk`)**: Generates unified diff patch chunks with normalized headers (`--- a/...`, `+++ b/...`, `@@ -o,c +n,c @@`) and applies them atomically via `git apply --cached`.
- **Line-Level Staging (`stage_lines`)**: Synthesizes custom patch hunks converting unselected diff lines into context lines.
- **Edge-Case Handlings**:
  - Rejects binary file staging with `BinaryFileStagingError`.
  - Proper patch headers for pure additions (`0,0` old lines) and pure deletions (`0,0` new lines).
  - Explicit trailing `\ No newline at end of file` marker preservation.

### 2.4 Safety & Recovery Systems
- **Stale Lock Recovery (`src/wrench/core/lock_recovery.py`)**:
  - Detects `.git/index.lock` across registered repositories.
  - Grace period (5 seconds) distinguishes active terminal processes from orphaned crash locks.
  - User-confirmed lock deletion dialog during app startup or before write operations.
- **Reflog Restoration (`src/wrench/core/reflog.py`)**:
  - Queries `pygit2` reflog history.
  - `restore_to_ref` allows resetting current branch state to a historical reflog point.
- **Rolling Local Snapshots (`src/wrench/core/snapshots.py` & `src/wrench/storage/snapshots.py`)**:
  - Non-destructive `git stash create` captures working tree and index state as floating git commit objects without disturbing working directory files.
  - Untracked files stored as compressed tarballs in `$XDG_DATA_HOME/wrench/snapshots/`.
  - Configurable retention pruning.

### 2.5 Real-Time Filesystem Watcher (`src/wrench/watcher/inotify_watcher.py`)
- Inotify observer ignoring `.git/` internal directory churn.
- Listens to both `on_modified` and `on_moved` / `IN_MOVED_TO` events to capture atomic editor saves (e.g. JetBrains, Vim, VS Code writing to temp files and renaming).
- Single-shot `QTimer` with 300ms debouncing collapses rapid bursts of filesystem events into a single `status_changed` signal.
- Polling fallback (`src/wrench/watcher/polling_fallback.py`) for environments reaching inotify limits.

### 2.6 Thread-Safe UI Shell (`src/wrench/ui/`)
- **`MainWindow` (`ui/main_window.py`)**: QSplitter holding sidebar and main workspace. Coordinates active repository lifecycle and status watcher.
- **`RepoSidebar` (`ui/sidebar/repo_sidebar.py`)**: Lists registered repositories with active branch and missing status markers.
- **`DiffWidget` (`ui/diff_view/diff_widget.py`)**:
  - Staged and unstaged file lists with checkboxes.
  - High-performance, read-only syntax-highlighted `QTextEdit` displaying diff lines.
  - Per-hunk selector dropdown and whole-file / hunk staging action buttons.
  - Thread-safe UI updates preventing Qt repaint recursion.
- **Thread Marshaller (`ui/workers.py`)**:
  - `_Dispatcher` `QObject` with Qt `QueuedConnection` ensuring all background worker callbacks (`on_finished`, `on_failed`, `on_progress`) execute strictly on the main GUI thread.

### 2.7 Developer Environment & Diagnostic Tooling
- **`init-dev.sh`**: Automatic `.venv` setup, dependency verification, pre-commit hook installer, and terminal alias configuration.
- **`bin/` Executables**:
  - `wrench-run`: Run the application.
  - `wrench-debug`: Run the application with verbose `--debug` logging.
  - `wrench-test`: Run the full pytest test suite.
  - `wrench-lint`: Run Ruff and Black checks.
  - `wrench-format`: Run Ruff auto-fixes and Black formatting.
  - `wrench-ci-check`: Run all lint, formatting, and unit tests in one command.
- **Diagnostic Logging (`src/wrench/app.py`)**: Structured logs with timestamps and component filters. Silences high-volume third-party inotify buffer logging while exposing full internal Wrench debug messages.

---

## 3. Verification & Test Suite

All 48 automated test cases pass:
- **`tests/unit/core/test_read_ops.py`**: Validates unborn branch guards, detached HEAD, commit log limits/pagination, text/binary diff parsing, and blame.
- **`tests/unit/core/test_write_ops.py`**: Validates commit creation, amend, empty commit rejection, branch creation/switching/renaming/force-deletion, and stash cycles.
- **`tests/unit/core/test_engine_staging.py`**: Validates whole-file staging, synthetic hunk patch staging, and binary file exception safety.
- **`tests/unit/core/test_lock_recovery.py`**: Tests active vs. stale lock mtime calculations and cleanup.
- **`tests/unit/core/test_reflog.py`**: Tests reflog listing and branch recovery.
- **`tests/unit/core/test_snapshots.py`**: Validates non-destructive snapshots, dirty worktree captures, and retention pruning.
- **`tests/unit/core/test_watcher.py`**: Validates watcher event filtering and atomic rename handling.
- **`tests/unit/core/test_workers.py`**: Tests background thread execution and exception propagation.
- **`tests/unit/storage/test_repo_registry.py`**: Validates CRUD operations, missing flags, relocation, and settings storage.
- **`tests/ui/test_ui_components.py`**: Qt-based UI tests verifying sidebar rendering, diff view hunk presentation, and main window lifecycle.

---

## 4. Next Phase Transition

Phase 1 acceptance criteria are fully met. The codebase is ready for **Phase 2: Forge Authentication & Token Storage (FR-8.1, FR-8.2, FR-8.3, FR-8.4, FR-8.5, FR-8.7)**.
