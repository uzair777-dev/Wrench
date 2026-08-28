# Wrench Architecture

This document describes the design principles, component architecture, concurrency model, and data flow of **Wrench**.

---

## 1. Architectural Principles

Wrench is engineered around four non-negotiable architectural tenets:

1. **Hybrid Core Git Engine (Split Read/Write Responsibility)**:
   - **Read Operations** (`status`, `diff`, `log`, `blame`) are executed in-process using `pygit2` (libgit2 C bindings) for millisecond latency and structured in-memory traversal without process-spawning overhead.
   - **Write & Risky Operations** (`commit`, `branch`, `switch`, `merge`, `rebase`, `push`, `pull`, `fetch`, `credential negotiation`) are delegated to the system `git` CLI via subprocess. This guarantees 100% fidelity with git's battle-tested merge/rebase conflict handling, index updates, and credential protocols.
2. **Strict Layering & One-Directional Data Flow**:
   ```
   UI Layer (PySide6)
         │
         ▼
   Façade Layer (core.engine / forge.registry)
         │
   ┌─────┴───────────────────────┬────────────────────────┐
   ▼                             ▼                        ▼
   Read Engine (pygit2)     Write Engine (git CLI)   Forge Adapters (httpx)
   ```
   - **Rule**: UI code *never* directly imports `pygit2`, calls `subprocess`, or touches low-level database cursors. All interactions pass through the public `core.engine` and `forge.registry` façades.
3. **Thread Safety & Non-Blocking UI**:
   - Heavy write operations, network calls, and repository clones run in dedicated background threads (`ui.workers.run_in_background`).
   - Callback execution is marshalled back to the main GUI thread using Qt queued signals (`_Dispatcher`) to avoid thread race conditions and UI crashes.
4. **Local-First & Non-Destructive Safety**:
   - Every potentially destructive action is protected by safety systems (automatic pre-operation snapshots, stale lock recovery, and reflog recovery).

---

## 2. System Component Diagram

```mermaid
graph TD
    subgraph UI ["UI Layer (PySide6)"]
        MW[MainWindow]
        TC[TabContainer / TabButton]
        CT[ChangesTab]
        HT[HistoryTab - Skeleton]
        BW[BranchSwitcherWidget]
        DV[DiffView]
        CG[CommitGraph - Phase 2]
        MT[MergeTool - Phase 2]
        FP[ForgePanel - Phase 4]
        WKR[Worker Thread Pool & Dispatcher]
    end

    subgraph Core ["Core Git Engine (src/wrench/core)"]
        ENG[engine.py Façade]
        READ[read_ops.py - pygit2]
        WRITE[write_ops.py - git subprocess]
        STG[Staging Patch Synthesizer]
        SNP[snapshots.py]
        LCK[lock_recovery.py]
        RFL[reflog.py]
        IDN[identity.py]
    end

    subgraph Watcher ["Filesystem Watcher (src/wrench/watcher)"]
        INOT[inotify_watcher.py]
        POLL[polling_fallback.py]
    end

    subgraph Storage ["Storage Layer (src/wrench/storage)"]
        DB[(SQLite: wrench.db)]
        REG[repo_registry.py]
        SET[settings.py]
        SNPREG[snapshots.py]
    end

    subgraph Credentials ["Credentials & Forges"]
        CRED[credentials.backend]
        SS[Secret Service D-Bus]
        GCH[git-credential-wrench]
        FORGE[forge.capability / adapters]
    end

    MW --> TC
    TC --> CT
    TC --> HT
    CT --> BW
    CT --> DV
    MW --> ENG
    CT --> ENG
    HT --> ENG
    BW --> ENG
    DV --> ENG
    CT --> REG
    MW --> SET
    ENG --> READ
    ENG --> WRITE
    ENG --> STG
    ENG --> SNP
    ENG --> LCK
    ENG --> RFL
    ENG --> IDN
    INOT -->|Qt Signal| MW
    SNP --> DB
    REG --> DB
    SET --> DB
    WRITE --> GCH
    GCH --> CRED
    CRED --> SS
    WKR -.->|Main-Thread Queued Signal| MW
```

---

## 3. Component Breakdown

### 3.1 UI Layer (`src/wrench/ui/`)
- **`MainWindow` (`ui/main_window.py`)**: Root `QMainWindow` and lifecycle coordinator.
  - Native `QMenuBar` with **File**, **Edit**, **View**, and **Help** menus.
  - Hosts the central `TabContainer`.
  - Persists window geometry and tab orientation into `app_settings` across sessions.
  - Enforces quit guards when unsaved commit message drafts exist.
  - Owns the active `RepoHandle` and `RepoWatcher`.
- **`TabContainer` & `TabButton` (`ui/tabs/tab_bar.py`)**: Custom hybrid tab system.
  - Supports dynamic switching between **Vertical** (left sidebar) and **Horizontal** (top bar) orientations.
  - Pinned non-closable `Changes` tab (index 0) and closable category / dynamic detail tabs.
  - Trailing `+` button with category tabs dropdown menu.
  - Per-repo deduplication rule: `(tab_type, repo_path, entity_id)` avoids duplicate tabs.
  - Keyboard tab switching (`Ctrl+1` .. `Ctrl+9`).
- **`ChangesTab` (`ui/tabs/changes_tab.py`)**: Primary working tree changes workspace.
  - Flush borderless repository selector `QComboBox` with missing repository auto-locate prompts.
  - Embedded `BranchSwitcherWidget`.
  - Merge conflict banner when merge conflicts are in progress.
  - Unified changed files list (staged + unstaged + untracked) with status badges (`M`, `A`, `D`, `R`, `?`, `⚠ C`) and path tooltips.
  - Tri-state select-all checkbox cycling `Unchecked ➔ All Checked ➔ All Unchecked`.
  - Right-click file context menu (`Stage`, `Unstage`, `Discard`, `Copy Relative/Absolute Path`).
  - Commit section with forge account avatar button, 72-character soft limit summary warning, description editor, amend toggle (pre-filled from last commit), and dynamic commit button.
  - Right column embedded `DiffView` with clean state and programming quotes.
- **`BranchSwitcherWidget` (`ui/widgets/branch_switcher.py`)**: Branch indicator and switcher.
  - Displays active branch (`🌿 main ▾`), detached HEAD (`🔗 HEAD detached at {sha}`), or unborn branch (`🌿 main (initial)`).
  - Searchable branch picker popup listing local and remote tracking branches.
  - Uncommitted changes prompt: `Stash & Switch`, `Switch Anyway`, or `Cancel`.
  - Right-click context actions: `Create New Branch…`, `Rename Branch…`, `Delete Branch…`.
- **`HistoryTab` (`ui/tabs/history_tab.py`)**: Git log and history visualization skeleton.
  - Top search and filter bar (search input, author filter, path filter, clear button) with 300ms debouncing.
  - Swappable graph placeholder container (wired to `CommitGraphWidget` in Phase 2).
  - Unborn branch empty state (`"No history yet"`).
  - Hidden detail panel slot.
- **`DiffView` (`ui/diff_view/diff_widget.py`)**: Syntax-highlighted diff viewer.
  - Renders diff lines with line-number metadata.
  - Provides hunk dropdown controls and whole-file / hunk staging action buttons.
  - Binary file detection and exception safety.
- **`workers.py`**: Background thread runner using `QThread` and a thread-safe `_Dispatcher` `QObject` via `Qt.ConnectionType.QueuedConnection` to ensure callbacks execute strictly on the main GUI thread.

### 3.2 Core Git Engine (`src/wrench/core/`)
- **`engine.py`**: Public façade exposing unified, typed functions. Converts all internal exceptions into typed `WrenchGitError` derivatives (`WrenchRepoNotFoundError`, `GitCommandError`, `StagingError`, etc.).
- **`read_ops.py`**: `pygit2`-backed status, diffs, log traversal, and line-by-line blame.
- **`write_ops.py`**: Subprocess helper `run_git` managing process execution, environment sanitation (`GIT_TERMINAL_PROMPT=0`), timeouts, and command logging.
- **`lock_recovery.py`**: Manages `.git/index.lock` detection with a 5-second grace window to differentiate active operations from stale crash locks.
- **`snapshots.py`**: Captures working directory states into dangling Git commit objects (`git stash create`) and compresses untracked files into `.tar.gz` archives without altering working directory status.
- **`reflog.py`**: Reflog inspection and branch restoration.
- **`identity.py`**: Validates user name and email configurations, providing repo-local configuration setters.
- **`paths.py`**: Standardized XDG data, config, and state directory resolution via `platformdirs`.

### 3.3 File Watcher (`src/wrench/watcher/`)
- **`inotify_watcher.py`**: Utilizes `watchdog.observers.Observer` to monitor repository directories.
  - Excludes internal `.git/` directory operations.
  - Subscribes to `on_modified` and `on_moved` / `IN_MOVED_TO` events (crucial for capturing atomic file saves from editors that write to temp files and rename).
  - Employs a 300ms single-shot `QTimer` debounce filter to collapse bursts of events into a single notification.
- **`polling_fallback.py`**: Fallback polling loop when inotify handle limits (`ENOSPC`) are reached.

### 3.4 Local Data Storage (`src/wrench/storage/`)
- **`db.py`**: Manages SQLite connection (`wrench.db`) located in `$XDG_DATA_HOME/wrench/`.
  - Configured with `check_same_thread=False`.
  - Serialized through a single process-wide `threading.Lock()` to prevent SQLite concurrency deadlocks.
  - Automated corrupt database quarantine and recovery.
- **`repo_registry.py`**: Repository CRUD operations, tracking last opened times, missing states, and relocated paths.
- **`settings.py`**: App-level and per-repository key-value configuration storage.
- **`schema.sql`**: Normalized relational schema with foreign key cascading deletes.

---

## 4. Key Workflows & Data Flows

### 4.1 Granular Staging Workflow
```
[User clicks 'Stage Hunk']
        │
        ▼
[ui.diff_view] calls core.engine.stage_hunk(repo, path, hunk_id)
        │
        ▼
[core.read_ops] retrieves structured Diff for path via pygit2
        │
        ▼
[core.engine] extracts target Hunk and formats unified diff patch:
        --- a/path
        +++ b/path
        @@ -old_start,old_count +new_start,new_count @@
        ...
        │
        ▼
[core.write_ops] writes patch to temp file and executes:
        git apply --cached <temp_patch>
        │
        ▼
[core.write_ops] cleans up temp file
        │
        ▼
[inotify_watcher] detects index change -> 300ms debounce -> triggers UI refresh
```

### 4.2 Safe Branch Switching Workflow
```
[User selects branch in BranchSwitcherWidget]
        │
        ▼
[BranchSwitcherWidget] checks repo status
        │
   ┌────┴────────────────────────┐
   ▼                             ▼
[Worktree is Clean]        [Uncommitted Changes Exist]
   │                             │
   │                             ▼
   │                       [Prompt Dialog: Stash & Switch / Switch Anyway / Cancel]
   │                             │
   │              ┌──────────────┴──────────────┐
   │              ▼                             ▼
   │        [Stash & Switch]              [Switch Anyway]
   │              │                             │
   │        1. engine.stash_create()            │
   │        2. engine.switch_branch()           │
   │        3. engine.stash_pop()               │
   │              │                             │
   └──────────────┬─────────────────────────────┘
                  │
                  ▼
          [engine.switch_branch()]
                  │
                  ▼
          [inotify_watcher] -> triggers ChangesTab & HistoryTab refresh
```

### 4.3 Non-Blocking Background Operations
```
[UI Trigger: Clone / Push / Fetch]
        │
        ▼
ui.workers.run_in_background(fn, *args, on_finished=cb, on_failed=err_cb)
        │
        ├── Spawns QThread & GitOperationWorker
        ├── Executes blocking git subprocess on background thread
        │
        ▼
[Background Thread Completes]
        │
        ├── Emits finished(result) or failed(error) Signal
        │
        ▼
[_Dispatcher QObject (Main Thread)]
        │
        └── Receives signal via Qt.QueuedConnection
        └── Executes on_finished / on_failed directly on Main GUI Thread
```

---

## 5. Relational Database Schema

```
┌──────────────────────────────┐       ┌────────────────────────────────────┐
│            repos             │       │      repo_identity_overrides       │
├──────────────────────────────┤       ├────────────────────────────────────┤
│ id (PK)                      │◄──────┤ repo_id (FK, PK)                   │
│ path (UNIQUE)                │       │ user_name                          │
│ display_name                 │       │ user_email                         │
│ last_opened_at               │       └────────────────────────────────────┘
│ is_missing                   │
└──────────────┬───────────────┘
               │
               ├───────────────────────┐
               ▼                       ▼
┌──────────────────────────────┐ ┌────────────────────────────────────┐
│          snapshots           │ │         repo_forge_links           │
├──────────────────────────────┤ ├────────────────────────────────────┤
│ id (PK)                      │ │ repo_id (FK, PK)                   │
│ repo_id (FK)                 │ │ remote_name (PK)                   │
│ trigger                      │ │ forge_account_id (FK)              │
│ label                        │ └─────────────────┬──────────────────┘
│ commit_sha                   │                   │
│ untracked_archive_path       │                   ▼
│ created_at                   │ ┌────────────────────────────────────┐
└──────────────────────────────┘ │           forge_accounts           │
                                 ├────────────────────────────────────┤
                                 │ id (PK)                            │
                                 │ provider                           │
                                 │ instance_url                       │
                                 │ label                              │
                                 │ username                           │
                                 │ secret_service_key                 │
                                 └────────────────────────────────────┘
```

---

## 6. Directory Structure

```
wrench/
├── bin/                          # Development helper binaries (symlinked to .venv/bin)
│   ├── wrench-run
│   ├── wrench-debug
│   ├── wrench-test
│   ├── wrench-lint
│   ├── wrench-format
│   └── wrench-ci-check
├── dev/
│   └── planning/                 # Architectural specifications, SRS & phase logs
│       ├── srs.md
│       ├── implementation-plan.md
│       ├── ui-planning.md
│       ├── phase-1.md
│       └── phase-1.5.md
├── packaging/
│   └── flatpak/                  # Flatpak packaging manifests
├── src/wrench/
│   ├── app.py                    # Application bootstrap & logging configuration
│   ├── core/                     # Core Git engine & platform primitives
│   │   ├── engine.py             # Public unified façade
│   │   ├── read_ops.py           # pygit2 read operations
│   │   ├── write_ops.py          # subprocess CLI write operations
│   │   ├── lock_recovery.py      # Stale index.lock detection
│   │   ├── snapshots.py          # Rolling safety snapshots
│   │   ├── reflog.py             # Reflog operations
│   │   ├── identity.py           # Git author configuration
│   │   └── paths.py              # XDG / platformdirs path resolution
│   ├── forge/                    # Forge provider capability system
│   ├── storage/                  # SQLite storage & repository registry
│   │   ├── db.py                 # SQLite connection management & locks
│   │   ├── repo_registry.py      # Repository tracking CRUD
│   │   ├── settings.py           # App & repo key-value settings
│   │   └── schema.sql            # Normalized relational schema
│   ├── ui/                       # PySide6 desktop UI
│   │   ├── main_window.py        # Main application window
│   │   ├── workers.py            # Thread-safe background worker marshaller
│   │   ├── tabs/                 # Hybrid tab navigation system
│   │   │   ├── tab_bar.py        # TabContainer & TabButton widgets
│   │   │   ├── changes_tab.py    # Primary Changes workspace
│   │   │   └── history_tab.py    # History / Commit graph skeleton
│   │   ├── widgets/              # Reusable UI widgets
│   │   │   └── branch_switcher.py# Interactive branch selector & popup
│   │   └── diff_view/            # Syntax-highlighted diff viewer & staging
│   └── watcher/                  # Inotify filesystem watching & debouncing
└── tests/                        # Comprehensive test suite (unit, integration, UI)
```
