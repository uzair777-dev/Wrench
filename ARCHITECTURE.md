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
   - Every potentially destructive action is protected by safety```mermaid
graph TD
    subgraph UI ["UI Layer (PySide6)"]
        MW[MainWindow]
        TC[TabContainer / TabButton]
        CT[ChangesTab]
        HT[HistoryTab - Commit Graph]
        BW[BranchSwitcherWidget]
        DV[DiffView]
        CG[CommitGraphWidget]
        MT[MergeDialog]
        RD[RemotesDialog - Phase 3]
        BD[BusyOperationDialog - Phase 3]
        FP[ForgePanel - Phase 4]
        WKR[Worker Thread Pool & Dispatcher]
    end

    subgraph Core ["Core Git Engine (src/wrench/core)"]
        ENG[engine.py Façade]
        READ[read_ops.py - pygit2]
        WRITE[write_ops.py - git subprocess]
        STREAM[run_git_streaming - pipe drainer]
        STG[Staging Patch Synthesizer]
        SNP[snapshots.py]
        LCK[lock_recovery.py]
        RFL[reflog.py]
        IDN[identity.py]
        SSH[ssh_agent.py - platform guard]
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
        FACC[forge_accounts.py]
    end

    subgraph Credentials ["Credentials & Forges"]
        CRED[credentials.get_backend()]
        SS[SecretServiceBackend D-Bus]
        GCH[git-credential-wrench]
        FORGE[forge.capability / adapters]
    end

    MW --> TC
    TC --> CT
    TC --> HT
    CT --> BW
    CT --> DV
    MW --> ENG
    MW --> RD
    MW --> BD
    CT --> ENG
    HT --> ENG
    BW --> ENG
    DV --> ENG
    CT --> REG
    MW --> SET
    ENG --> READ
    ENG --> WRITE
    WRITE --> STREAM
    WRITE --> SSH
    ENG --> STG
    ENG --> SNP
    ENG --> LCK
    ENG --> RFL
    ENG --> IDN
    INOT -->|Qt Signal| MW
    SNP --> DB
    REG --> DB
    SET --> DB
    FACC --> DB
    GCH --> FACC
    GCH --> CRED
    CRED --> SS
    WKR -.->|Main-Thread Queued Signal| MW
```

---

## 3. Component Breakdown

### 3.1 UI Layer (`src/wrench/ui/`)
- **`MainWindow` (`ui/main_window.py`)**: Root `QMainWindow` and lifecycle coordinator.
  - Native `QMenuBar` with **File**, **Edit**, **View**, **Repository**, and **Help** menus.
  - **Repository Menu (Phase 3)**: Exposes `Fetch` (`Ctrl+Shift+F`), `Pull` (`Ctrl+Shift+L`), `Push` (`Ctrl+Shift+U`), and `Remotes…` actions wired through `run_in_background` with `BusyOperationDialog` tracking.
  - **Error Routing Engine (Phase 3)**: Routes remote operation failures to actionable dialogs:
    - `AuthRequiredError`: Guides users when credentials are missing for a remote host.
    - `AuthFailedError`: Informs users when stored credentials were rejected by the remote.
    - `PushRejectedError`: Offers actionable choices between "Fetch & Retry", "Force Push (with lease)", and "Cancel".
    - `MergeRequiredError`: Offers actionable choices between "Merge" and "Rebase" using Phase 2 tools.
    - `RemoteNotFoundError`: Prompts and opens the Remotes configuration dialog.
  - **Asynchronous Clone (Phase 3)**: Routes repository cloning through `run_in_background` with cancellable `BusyOperationDialog` and atomic filesystem placement.
  - Hosts the central `TabContainer`.
  - **GUI Session Persistence Engine**: Runs a continuous 1000ms debounced auto-save timer (`_auto_save_timer`) coalescing window geometry, splitter ratios, tab list/order/pinning, active repo, and per-repo selections/drafts into `app_settings` key `ui.session_state`.
  - Synchronous flush on `closeEvent(event)` ensures state is never lost on shutdown or unexpected termination.
  - Startup restoration guard `_is_restoring` prevents initialization noise from wiping saved drafts and checkbox selections.
  - Enforces quit guards when unsaved commit message drafts exist or background workers are busy.
  - Owns the active `RepoHandle` and `RepoWatcher`.
- **`RemotesDialog` (`ui/dialogs/remotes_dialog.py`)**: Repository remotes management interface (Phase 3).
  - Displays all configured remotes with columns: `Name`, `URL`, `Last Fetch`, and `Reachability`.
  - Color-coded reachability indicators: `● Reachable` (green), `● Unreachable` (red), `● Unknown` (gray).
  - Modal operations for `Add Remote` (with name regex & URL validation), `Edit Remote`, `Remove Remote` (with destructive confirmation), and `Refresh Status` (reachability probe).
- **`BusyOperationDialog` (`ui/recovery/busy_dialog.py`)**: Progress & cancellation modal dialog (Phase 3).
  - Real-time percentage progress bar or animated indeterminate spinner.
  - Interactive "Cancel" button setting a `threading.Event` to abort in-flight git operations.
- **`TabContainer`, `TabStripWidget`, & `TabButton` (`ui/tabs/tab_bar.py`)**: Custom hybrid tab system.
  - Supports dynamic switching between **Vertical** (left sidebar, default) and **Horizontal** (top bar) orientations.
  - **Dynamic Tab Model & Pinning**: All tabs are dynamic. Right-click context menu provides `Pin Tab` / `Unpin Tab`, `Close Tab`, `Close Other Tabs`, and `Close Tabs to the Right/Below`. Pinned tabs show a `📌` badge prefix and hide the `×` close button.
  - **Drag-and-Drop Tab Reordering**:
    - `TabButton` captures mouse drag motions via `installEventFilter` and initiates `QDrag` with visual pixmap snapshots.
    - `TabStripWidget` implements drag target tracking (`dragEnterEvent`, `dragMoveEvent`, `dragLeaveEvent`, `dropEvent`) and renders a 2px visual insertion line in `paintEvent`.
    - `move_tab(from_index, to_index)` enforces the pinned grouping constraint (pinned tabs reorder among pinned tabs; unpinned tabs reorder among unpinned tabs).
    - Active tab focus is retained during reordering and triggers `tabs_mutated` for debounced auto-save persistence.
  - **Section Dividers**: 1px subtle divider line between the tab strip and main content area (`border-right` in vertical mode, `border-bottom` in horizontal mode).
  - Trailing `+` button with category tabs dropdown menu.
  - Per-repo deduplication rule: `(tab_type, repo_path, entity_id)` avoids duplicate tabs.
  - Keyboard tab switching (`Ctrl+1` .. `Ctrl+9`).
- **`ChangesTab` (`ui/tabs/changes_tab.py`)**: Primary working tree changes workspace.
  - Flush borderless repository selector `QComboBox` with missing repository auto-locate prompts.
  - Embedded `BranchSwitcherWidget`.
  - Visible 1px divider `QSplitter::handle` with interactive hover highlight.
  - Merge conflict banner when merge conflicts are in progress.
  - Unified changed files list (staged + unstaged + untracked) with status badges (`M`, `A`, `D`, `R`, `?`, `⚠ C`) and path tooltips.
  - Tri-state select-all checkbox cycling `Unchecked ➔ All Checked ➔ All Unchecked`.
  - Right-click file context menu (`Stage`, `Unstage`, `Discard`, `Copy Relative/Absolute Path`).
  - Commit section with forge account avatar button, 72-character soft limit summary warning, description editor, amend toggle (pre-filled from last commit), and dynamic commit button.
  - Per-repo selections and draft text snapshotting (`get_current_repo_state()` / `restore_repo_state()`) during repository switches.
  - Right column embedded `DiffView` with clean state and programming quotes.
- **`BranchSwitcherWidget` (`ui/widgets/branch_switcher.py`)**: Branch indicator and switcher.
  - Displays active branch (`🌿 main ▾`), detached HEAD (`🔗 HEAD detached at {sha}`), or unborn branch (`🌿 main (initial)`).
  - Searchable branch picker popup listing local and remote tracking branches.
  - Uncommitted changes prompt: `Stash & Switch`, `Switch Anyway`, or `Cancel`.
  - Right-click context actions: `Create New Branch…`, `Rename Branch…`, `Delete Branch…`.
- **`HistoryTab` (`ui/tabs/history_tab.py`)**: Git log and history visualization workspace.
  - Top search and filter bar (search input, dynamic author filter from active commits, path filter, clear button) with 300ms debouncing.
  - Hosts `CommitGraphWidget` with infinite scroll pagination, selection synchronization, and detail panel display.
  - Full UI state persistence: saves/restores table header column widths (`save_header_state()` / `restore_header_state()`) and vertical content splitter position (`save_splitter_state()` / `restore_splitter_state()`) in SQLite `ui.session_state`.
  - Unborn branch empty state (`"No history yet"`).
- **`CommitGraphWidget` (`ui/commit_graph/graph_widget.py`)**: Custom table view for Git DAG commit graph.
  - Custom `CommitTableModel` supporting `Qt.DisplayRole`, `Qt.UserRole` (`GraphRow`), and rich `Qt.ToolTipRole` across all columns.
  - **Smooth Per-Pixel Horizontal Scrolling**: Configured with `setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)` to eliminate column snapping and deliver fluid pixel-continuous horizontal scrolling across all table columns.
  - **Synchronized Column 0 Scrollbar (`_graph_scrollbar`)**: Dedicated pinned horizontal scrollbar styled identically to the main scrollbar with dynamic height matching and off-screen viewport panning (`_graph_scroll_x`). Dynamically tracks Column 0's viewport coordinate (`self.viewport().x() + header.sectionViewportPosition(0)`), translating smoothly to the left in exact sync with Column 0 as the main scrollbar scrolls right, with width bounded by viewport boundaries to prevent overlapping the vertical scrollbar. Automatically hides when Column 0 scrolls off-screen or when lane count fits without scrolling.
  - **Synchronous Viewport Scroll Updates**: Overrides `scrollContentsBy(dx, dy)` and connects to `valueChanged`, `rangeChanged`, and `header.geometriesChanged` to ensure instant, zero-lag scrollbar positioning during mouse drags, trackpad pans, and window resizes.
  - Interactive column resizing across all header sections with boundary clipping and auto-save triggering on resize.
  - Auto-scrolling to selected commit nodes with glowing halo accent rings (`NODE_RADIUS + 3.0`).
- **`Topological Layout Calculator` (`ui/commit_graph/layout.py`)**:
  - Computes `(col, row)` coordinates and directional `Connector` segments (`PASS_THROUGH`, `FORK_DOWN`, `MERGE_UP`, `JOIN_TOP`).
  - 10-color deterministic color persistence and slot recycling algorithm preventing lane explosion.
- **`MergeDialog` (`ui/dialogs/merge_dialog.py`)**: 3-Way visual merge conflict resolution tool.
  - Side-by-side Ours, Base, and Theirs diff viewers with block-level conflict acceptance and index staging.
- **`RecoveryDialog` (`ui/dialogs/recovery_dialog.py`)**:
  - Actionable diagnostics and recovery workflows for stale locks, interrupted rebases, detached HEADs, and reflogs.
- **`DiffView` (`ui/diff_view/diff_widget.py`)**: Syntax-highlighted diff viewer.
  - Renders diff lines with line-number metadata and theme-adaptive light/dark mode contrast.
  - Provides hunk dropdown controls and whole-file / hunk staging action buttons.
  - Binary file detection and exception safety.
- **`workers.py`**: Background thread runner using `QThread` and a thread-safe `_Dispatcher` `QObject` via `Qt.ConnectionType.QueuedConnection` to ensure callbacks execute strictly on the main GUI thread. Adapted in Phase 3 to support multi-parameter `progress_cb(pct, stage)` and cooperative cancellation via `threading.Event`.


### 3.2 Core Git Engine (`src/wrench/core/`)
- **`engine.py`**: Public façade exposing unified, typed functions. Converts internal errors into typed `WrenchGitError` derivatives.
  - Remote operations (Phase 3): `push(repo, remote, branch, force=False)` (enforces `--force-with-lease`), `pull(repo, remote, branch)` (enforces `--ff-only`), `fetch(repo, remote)` (with `--prune` and timestamp storage), and `clone_repo(url, dest)` (atomic staging via tempdir with automated rollback).
  - Remotes façade (Phase 3): `list_remotes(repo)`, `add_remote(repo, name, url)`, `remove_remote(repo, name)`, `set_remote_url(repo, name, url)`, and `_probe_reachability(repo_path, remote_name)`.
- **`read_ops.py`**: `pygit2`-backed status, diffs, log traversal, branch enumeration, and line-by-line blame.
- **`write_ops.py`**: Subprocess helpers managing Git CLI execution:
  - `run_git`: Standard synchronous runner with timeout and sanitized environment (`GIT_TERMINAL_PROMPT=0`).
  - `run_git_streaming`: Deadlock-free streaming execution using concurrent dual-pipe reader threads for `stdout` and `stderr`. Parses carriage-return `\r` and `\n` progress lines, routes live percentage and stage callbacks, and terminates gracefully on `cancel_event` (`SIGTERM` ➔ 3s grace ➔ `SIGKILL`). Deterministically classifies non-zero exits into typed exceptions (`PushRejectedError`, `MergeRequiredError`, `AuthFailedError`, `AuthRequiredError`, `CLITimeoutError`).
- **`git_credential_helper.py`**: Standalone executable (`git-credential-wrench`) implementing Git's standard credential helper protocol. Reads credentials from SQLite `wrench.db` in read-only WAL mode, resolving repo-specific bindings from `repo_forge_links` before falling back to unique host matches in `forge_accounts`. Strictly fails closed when multiple accounts share a host without explicit repository association.
- **`ssh_agent.py`**: Encapsulates platform `SSH_AUTH_SOCK` discovery and environment configuration behind the Platform-Abstraction Guard (FR-11.1–11.3).
- **`exceptions.py`**: Typed domain exceptions for Git errors, network operations, merge conflicts, and authentication failures.
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
- **`forge_accounts.py`**: Forge account metadata storage and repository-to-account bindings (`repo_forge_links`).
- **`schema.sql`**: Normalized relational schema with foreign key cascading deletes.

### 3.5 Credentials & Platform Layer (`src/wrench/credentials/`)
- **`backend.py`**: Abstract base class `CredentialBackend` defining `get_secret(key)`, `store_secret(key, secret)`, and `delete_secret(key)`.
- **`secret_service.py`**: `SecretServiceBackend` implementing the Freedesktop Secret Service D-Bus specification via `secretstorage`.
  - Automatically handles collection unlocking via `collection.unlock()`.
  - Formats user-actionable diagnostics tailored to runtime environments: Flatpak sandboxes, desktop keyrings (GNOME Keyring / KWallet), and headless systems.
  - Strict compliance with Platform-Abstraction Guard (FR-11.1–11.3): all Secret Service imports are strictly encapsulated here.
- **`__init__.py`**: Caching factory function `get_backend()` and packaging context detection `detect_packaging_context()` (`flatpak`, `snap`, `appimage`, `system`).

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

### 4.4 Continuous Session State & Draft Persistence Workflow
```
[UI Events: Typing Draft, Checking Files, Reordering Tabs, Switching Repos, Resizing Splitter]
        │
        ▼
[MainWindow._trigger_auto_save()]
        │
        ▼
[QTimer: 1000ms Debounce Delay] ───(Rapid bursts coalesce into a single timer restart)───┐
        │                                                                                │
        ▼ (Timer fires after 1s quiet)                                                   │
[MainWindow._save_session_state()]                                                       │
        │                                                                                │
        ├── Serializes Window Geometry + Window State (Hex)                              │
        ├── Serializes Tab Order + Types + Labels + Pinning State                        │
        ├── Serializes Active Tab Index + Active Repo Path                               │
        ├── Serializes Per-Repo Draft State (Message, Description, Amend, Checkboxes)   │
        │                                                                                │
        ▼                                                                                │
[storage.settings.set_setting("ui.session_state", json_blob)]                            │
        │                                                                                │
        ▼                                                                                │
[SQLite: app_settings] ◄─────────────────────────────────────────────────────────────────┘
        │
        ├── On Startup: MainWindow._restore_settings() re-hydrates full UI state
        └── On Close: MainWindow.closeEvent() executes immediate synchronous flush
```

### 4.5 Deadlock-Free Streaming & Remote Operations Workflow
```
[User triggers Fetch / Pull / Push / Clone]
        │
        ▼
[MainWindow] runs operation in background via ui.workers.run_in_background
        │
        ├── Instantiates BusyOperationDialog (modal progress & cancellation)
        ├── Passes cancel_event (threading.Event) and progress_cb(pct, stage)
        │
        ▼
[core.engine: push / pull / fetch / clone_repo]
        │
        ▼
[core.write_ops.run_git_streaming]
        │
        ├── Injects SSH_AUTH_SOCK via core.ssh_agent.configure_ssh_env
        ├── Sets GIT_TERMINAL_PROMPT=0 and LC_ALL=C
        ├── Spawns subprocess.Popen(stdout=PIPE, stderr=PIPE)
        │
        ├── Thread 1: Drains stdout line-by-line concurrently
        ├── Thread 2: Drains stderr line-by-line concurrently
        │       ├── Parses \r and \n progress lines: "Counting objects: 45% (9/20)"
        │       └── Invokes progress_cb(pct, stage) -> Worker -> Main Thread GUI Dialog
        │
        ├── Monitors cancel_event:
        │       └── If set: SIGTERM -> 3s grace period -> SIGKILL
        │
        ├── Joins stdout and stderr reader threads (0 OS pipe buffer deadlocks)
        └── Classifies non-zero exits into typed WrenchGitError subclasses:
                PushRejectedError, MergeRequiredError, AuthFailedError, AuthRequiredError
```

### 4.6 Git Credential Helper Protocol & Disambiguation Workflow
```
[git CLI triggers remote transport (e.g., https://github.com/...)]
        │
        ▼
[git CLI executes helper]: git-credential-wrench get
        │
        ├── Inputs via stdin (key=value pairs): protocol=https, host=github.com, path=...
        │
        ▼
[core.git_credential_helper.handle_get]
        │
        ├── Opens SQLite wrench.db in read-only URI mode (file:...mode=ro) with retry loop
        │
        ├── Step 1: Query repo_forge_links for exact (repo_id, remote_name) binding
        │       └── Found? Retrieve associated forge_accounts row.
        │
        ├── Step 2 (Fallback): Query forge_accounts WHERE instance_url / host matches
        │       ├── Exactly 1 matching account? Select it.
        │       └── >1 matching accounts? Fail closed (do not guess) -> Exit 0 with empty stdout.
        │
        ├── Step 3: Fetch secret from credentials.get_backend() via secret_service_key
        │       └── D-Bus Secret Service unlocks collection if necessary.
        │
        └── Emits to stdout:
                username=<username>
                password=<password>
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
│       ├── phase-1.5.md
│       ├── phase-2.md
│       └── phase-3.md
├── packaging/
│   └── flatpak/                  # Flatpak packaging manifests
├── src/wrench/
│   ├── app.py                    # Application bootstrap & logging configuration
│   ├── core/                     # Core Git engine & platform primitives
│   │   ├── engine.py             # Public unified façade
│   │   ├── read_ops.py           # pygit2 read operations
│   │   ├── write_ops.py          # subprocess CLI write & streaming operations
│   │   ├── git_credential_helper.py # Standalone git-credential-wrench executable
│   │   ├── ssh_agent.py          # SSH_AUTH_SOCK platform encapsulation
│   │   ├── exceptions.py         # Domain and CLI typed exceptions
│   │   ├── lock_recovery.py      # Stale index.lock detection
│   │   ├── snapshots.py          # Rolling safety snapshots
│   │   ├── reflog.py             # Reflog operations
│   │   ├── identity.py           # Git author configuration
│   │   └── paths.py              # XDG / platformdirs path resolution
│   ├── credentials/              # Secret Service & credential backends
│   │   ├── backend.py            # CredentialBackend abstract interface
│   │   └── secret_service.py     # D-Bus Secret Service platform backend
│   ├── forge/                    # Forge provider capability system
│   ├── storage/                  # SQLite storage & repository registry
│   │   ├── db.py                 # SQLite connection management & locks
│   │   ├── repo_registry.py      # Repository tracking CRUD
│   │   ├── settings.py           # App & repo key-value settings
│   │   ├── forge_accounts.py     # Forge accounts & repository links
│   │   └── schema.sql            # Normalized relational schema
│   ├── ui/                       # PySide6 desktop UI
│   │   ├── main_window.py        # Main application window & repository menu
│   │   ├── workers.py            # Thread-safe background worker marshaller
│   │   ├── tabs/                 # Hybrid tab navigation system
│   │   │   ├── tab_bar.py        # TabContainer & TabButton widgets
│   │   │   ├── changes_tab.py    # Primary Changes workspace
│   │   │   └── history_tab.py    # History / Commit graph workspace
│   │   ├── commit_graph/         # Topological DAG layout & custom table view
│   │   │   ├── layout.py         # S-curve calculation & slot recycling
│   │   │   └── graph_widget.py   # CommitGraphWidget & custom delegate
│   │   ├── dialogs/              # Interactive dialogs & recovery panels
│   │   │   ├── merge_dialog.py   # 3-Way visual merge conflict resolution tool
│   │   │   └── remotes_dialog.py # Repository remotes manager & reachability
│   │   ├── recovery/             # Recovery & progress modals
│   │   │   ├── busy_dialog.py    # Modal progress tracker & cancel button
│   │   │   └── recovery_dialog.py# Busy operation tracking & repo diagnostics
│   │   ├── widgets/              # Reusable UI widgets
│   │   │   └── branch_switcher.py# Interactive branch selector & popup
│   │   └── diff_view/            # Syntax-highlighted diff viewer & staging
│   └── watcher/                  # Inotify filesystem watching & debouncing
└── tests/                        # Comprehensive test suite (unit, integration, UI)
```

