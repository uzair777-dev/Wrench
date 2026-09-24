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
   - Every potentially destructive action is protected by safety snapshots (`git stash create` commit objects + `.tar.gz` untracked files) before execution, providing single-click undo and reflog restoration.

---

## 2. High-Level Component Diagram

```mermaid
graph TD
    subgraph UI ["UI Layer (PySide6)"]
        MW[MainWindow]
        TC[TabContainer / TabButton]
        CT[ChangesTab]
        HT[HistoryTab - Commit Graph]
        PRL[PRListTab & IssueListTab]
        PRD[PRDetailTab & IssueDetailTab]
        BW[BranchSwitcherWidget]
        DV[DiffView]
        CG[CommitGraphWidget]
        MT[MergeDialog]
        RD[RemotesDialog]
        AD[AccountsDialog & EditAccountDialog]
        LD[LinkRepoDialog]
        BD[BusyOperationDialog]
        WKR[Worker Thread Pool & Dispatcher]
        THM[Theme Engine - theme.py]
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
        RCV[recovery / crash_handler.py]
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

    subgraph Forge ["Multi-Forge Subsystem (src/wrench/forge)"]
        FREG[forge.registry - Pluggable Discovery]
        FAD[forge.capability - ForgeAdapter Base]
        FGH[GitHubAdapter]
        FGL[GitLabAdapter]
        FFJ[ForgejoAdapter]
        FBB[BitbucketAdapter]
        FDF[github_device_flow.py - RFC 8628]
    end

    subgraph Credentials ["Credentials Layer (src/wrench/credentials)"]
        CRED[credentials.get_backend()]
        SS[SecretServiceBackend D-Bus]
        GCH[git-credential-wrench]
    end

    MW --> TC
    TC --> CT
    TC --> HT
    TC --> PRL
    TC --> PRD
    HT --> CG
    CT --> BW
    CT --> DV
    MW --> ENG
    MW --> RD
    MW --> AD
    MW --> LD
    MW --> BD
    MW --> THM
    THM -.->|Recursive Palette & Event Broadcast| TC
    THM -.->|Recursive Palette & Event Broadcast| CT
    THM -.->|Recursive Palette & Event Broadcast| HT
    THM -.->|Recursive Palette & Event Broadcast| DV
    THM -.->|Recursive Palette & Event Broadcast| BW
    THM -.->|Recursive Palette & Event Broadcast| CG
    PRL --> FREG
    PRD --> FREG
    AD --> FDF
    AD --> FREG
    LD --> FACC
    FREG --> FAD
    FAD --> FGH
    FAD --> FGL
    FAD --> FFJ
    FAD --> FBB
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
    ENG --> RCV
    INOT -->|Qt Signal| MW
    SNP --> DB
    REG --> DB
    SET --> DB
    FACC --> DB
    GCH --> FACC
    GCH --> CRED
    FAD --> CRED
    FDF --> CRED
    CRED --> SS
    WKR -.->|Main-Thread Queued Signal| MW
```

---

## 3. Component Breakdown

### 3.1 UI Layer (`src/wrench/ui/`)
- **`MainWindow` (`ui/main_window.py`)**: Root `QMainWindow` and lifecycle coordinator.
  - Native `QMenuBar` with **File**, **Edit**, **View**, **Repository**, and **Help** menus.
  - **Repository Menu**: Exposes `Fetch` (`Ctrl+Shift+F`), `Pull` (`Ctrl+Shift+L`), `Push` (`Ctrl+Shift+U`), and `Remotes…` actions wired through `run_in_background` with `BusyOperationDialog` tracking.
  - **Error Routing Engine**: Routes remote and git operation failures to actionable dialogs:
    - `AuthRequiredError`: Guides users when credentials are missing for a remote host.
    - `AuthFailedError`: Informs users when stored credentials were rejected by the remote.
    - `WorkflowScopeRequiredError`: Explains when pushes to `.github/workflows/` require the `workflow` OAuth scope, prompting re-authorization without confusing retry loops.
    - `PushRejectedError`: Offers actionable choices between "Fetch & Retry", "Force Push (with lease)", and "Cancel".
    - `MergeRequiredError`: Offers actionable choices between "Merge" and "Rebase" using Phase 2 tools.
    - `RemoteNotFoundError`: Prompts and opens the Remotes configuration dialog.
  - **Asynchronous Clone**: Routes repository cloning through `run_in_background` with cancellable `BusyOperationDialog` and atomic filesystem placement.
  - Hosts the central `TabContainer`.
  - **GUI Session Persistence Engine**: Runs a continuous 1000ms debounced auto-save timer (`_auto_save_timer`) coalescing window geometry, splitter ratios, tab list/order/pinning, active repo, and per-repo selections/drafts into `app_settings` key `ui.session_state`.
  - Synchronous flush on `closeEvent(event)` ensures state is never lost on shutdown or unexpected termination.
  - Startup restoration guard `_is_restoring` prevents initialization noise from wiping saved drafts and checkbox selections.
  - Enforces quit guards when unsaved commit message drafts exist or background workers are busy.
  - Owns the active `RepoHandle` and `RepoWatcher`.
- **`PRListTab` & `IssueListTab` (`ui/tabs/pr_list_tab.py`, `ui/tabs/issue_list_tab.py`)**:
  - Forge pull request and issue browser workspaces keyed by `(tab_type, repo_path)`.
  - Interactive search bar and state filters (`Open`, `Merged`, `Closed`, `All`) with 300ms debouncing.
  - SWR (Stale-While-Revalidate) cache with a 60-second TTL for instantaneous view loads.
  - Remote selector dropdown binding active repository remotes to configured forge accounts.
  - Generation-counted request invalidation preventing stale asynchronous responses from overwriting newer user selections.
  - "New Pull Request" creation dialog (`CreatePRDialog`) with branch selectors, title, and description editors.
  - Double-click item selection spawning dynamic entity detail tabs.
- **`PRDetailTab` & `IssueDetailTab` (`ui/tabs/pr_detail_tab.py`, `ui/tabs/issue_detail_tab.py`)**:
  - Full-detail entity workspaces keyed by `(tab_type, repo_path, entity_id)`.
  - Direct non-paginated entity retrieval via `adapter.get_pull_request()` and `adapter.get_issue()`.
  - Inline CI/CD build status card (`CIIconWidget`) with external build log link button.
  - In-app review submission dialog (`SubmitReviewDialog`) supporting Approve, Request Changes, and Comment actions tailored to provider capability constraints.
  - Local branch checkout and tracking branch setup.
  - Stale repository warning banner informing users when the active main window repository has diverged from the open tab's repository.
- **`AccountsDialog`, `AddAccountDialog`, & `EditAccountDialog` (`ui/dialogs/accounts_dialog.py`)**:
  - Complete forge accounts management interface.
  - **Assisted Setup (Device Flow RFC 8628)**: Browser authorization for GitHub and GitHub Enterprise Server requesting `repo workflow` permissions, featuring live countdown timers, polling interval backoff, and clipboard copy helpers.
  - **In-Place Re-authorization**: 1-click re-authorization for existing GitHub accounts updating credentials in Secret Service while preserving all `repo_forge_links`.
  - **Manual Token Setup**: Guided PAT setup for GitHub, GitLab, Forgejo/Gitea, and Bitbucket with provider-specific permission documentation.
  - **Enterprise Security**: Custom CA bundle (PEM) file picker and explicit skip TLS verification option with security warning.
- **`LinkRepoDialog` (`ui/dialogs/link_dialog.py`)**:
  - Repository-to-forge account association dialog.
  - Auto-matches remotes to configured accounts by host URL.
  - Configures repository-level `git config credential.useHttpPath true` to ensure git CLI routes credentials path-specifically.
- **`RemotesDialog` (`ui/dialogs/remotes_dialog.py`)**: Repository remotes management interface.
  - Displays all configured remotes with columns: `Name`, `URL`, `Last Fetch`, and `Reachability`.
  - Color-coded reachability indicators: `● Reachable` (green), `● Unreachable` (red), `● Unknown` (gray).
  - Modal operations for `Add Remote` (with name regex & URL validation), `Edit Remote`, `Remove Remote` (with destructive confirmation), and `Refresh Status` (reachability probe).
- **`BusyOperationDialog` (`ui/recovery/busy_dialog.py`)**: Progress & cancellation modal dialog.
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
  - **Theme-Aware Tab Styling & Recursion Guards**:
    - `TabButton` binds `color: palette(window-text)` on active tabs and `color: palette(placeholder-text)` on inactive tabs (with hover transition to `palette(window-text)`), preventing stale white-on-light text artifacts after theme switches.
    - Handles `QEvent.PaletteChange` and `ApplicationPaletteChange` with an internal recursion guard (`_updating_style`) to eliminate stylesheet re-entry loops.
    - `TabContainer` provides `refresh_theme()` to synchronously trigger styling updates across all tab buttons when themes change.
- **`ChangesTab` (`ui/tabs/changes_tab.py`)**: Primary working tree changes workspace.
  - Flush borderless repository selector `QComboBox` with mode-isolated theme styling (`_update_repo_combo_theme()`): retains original stylesheet with `color: palette(window-text);` in dark mode, and applies explicit `#4c4f69` (charcoal slate) text on `#ffffff` card base in light mode to prevent invisible white text caused by static palette stylesheet binding.
  - Embedded `BranchSwitcherWidget` with theme-adaptive colors.
  - Visible 1px divider `QSplitter::handle` with interactive hover highlight.
  - Theme-adaptive merge conflict banner when merge conflicts are in progress.
  - Unified changed files list (staged + unstaged + untracked) with status badges (`M`, `A`, `D`, `R`, `?`, `⚠ C`) and path tooltips.
  - Tri-state select-all checkbox cycling `Unchecked ➔ All Checked ➔ All Unchecked`.
  - Right-click file context menu (`Stage`, `Unstage`, `Discard`, `Copy Relative/Absolute Path`).
  - Commit section with forge account avatar button, 72-character soft limit summary warning (using theme-aware warning ambers), description editor, amend toggle (pre-filled from last commit), and dynamic commit button (`commit_btn`) with mode-isolated theme styling (`_update_commit_btn_theme()`): preserves native unstyled Qt button rendering (`setStyleSheet("")`) in dark mode, and applies vibrant Catppuccin Sapphire (`#1e66f5`) with `#ffffff` text (disabled: `#e6e9ef` with `#7c7f93` text) in light mode to eliminate washed-out grey buttons.
  - Per-repo selections and draft text snapshotting (`get_current_repo_state()` / `restore_repo_state()`) during repository switches.
  - Right column embedded `DiffView` with clean state and programming quotes.
  - **Theme Lifecycle (`refresh_theme`)**: Propagates theme refreshes across `_update_repo_combo_theme()`, `_update_commit_btn_theme()`, `branch_switcher`, `files_list` item badges, `diff_view`, conflict banners, and secondary labels (`files_count_label`, `clean_title`, `clean_quote`, `clean_author` bound to `palette(placeholder-text)`), protected by recursion guards.
- **`BranchSwitcherWidget` (`ui/widgets/branch_switcher.py`)**: Branch indicator and switcher.
  - Displays active branch (`🌿 main ▾`), detached HEAD (`🔗 HEAD detached at {sha}`), or unborn branch (`🌿 main (initial)`).
  - Searchable branch picker popup listing local and remote tracking branches.
  - Uncommitted changes prompt: `Stash & Switch`, `Switch Anyway`, or `Cancel`.
  - Right-click context actions: `Create New Branch…`, `Rename Branch…`, `Delete Branch…`.
  - **Theme Integration**: Employs `ACCENT_COLORS` for detached HEAD indicators (`#df8e1d` in Light, `#f9e2af` in Dark), `palette(placeholder-text)` for unborn branch states, and listens to `PaletteChange` with recursion protection.
- **`HistoryTab` (`ui/tabs/history_tab.py`)**: Git log and history visualization workspace.
  - Top search and filter bar (search input, dynamic author filter from active commits, path filter, clear button) with 300ms debouncing.
  - Hosts `CommitGraphWidget` with infinite scroll pagination, selection synchronization, and detail panel display.
  - Full UI state persistence: saves/restores table header column widths (`save_header_state()` / `restore_header_state()`) and vertical content splitter position (`save_splitter_state()` / `restore_splitter_state()`) in SQLite `ui.session_state`.
  - Unborn branch empty state (`"No history yet"`) styled with `palette(placeholder-text)`.
  - **Theme Lifecycle**: Propagates theme changes to `CommitDetailPanel`, graph viewport, and empty-state labels with recursion guards.
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
  - Renders diff lines with line-number metadata and theme-adaptive Catppuccin Velvet Pastel contrast.
  - Automatically re-renders loaded diffs on `PaletteChange`, `ApplicationPaletteChange`, or `ThemeChange` without requiring file re-selection.
  - Provides hunk dropdown controls and whole-file / hunk staging action buttons.
  - Binary file detection and exception safety.
- **`Theme Engine` (`ui/theme.py`)**: Centralized styling and color management.
  - Implements the **Catppuccin Velvet Pastel** design system:
    - **Latte Pastel (Light Mode)**: `#eff1f5` warm mist canvas, `#ffffff` card bases, `#4c4f69` soft charcoal slate text, `#1e66f5` sapphire accents, `#7c7f93` muted slate subtext.
    - **Mocha Velvet Pastel (Dark Mode)**: `#181825` deep midnight slate canvas, `#11111b` deep crust card bases, `#cdd6f4` frosted white text, `#89b4fa` pastel sky accents, `#9399b2` soft lavender-gray subtext.
  - **Luminance-Based Detection (`is_dark_theme`)**: Calculates average luminance of `QPalette.Window` and `QPalette.Base` to avoid desktop environment color scheme mismatches on KDE Plasma and GNOME.
  - **Recursive Descendant Palette Propagation (`apply_theme`)**: Sets the palette on `QApplication` and traverses all `topLevelWidgets()` and their child widgets recursively. This overcomes Qt container stylesheet isolation contexts (`QStyleSheetStyle` on `QSplitter`, `QGroupBox`, etc.) where child widgets otherwise retain stale palettes.
  - **Design Tokens**: Centralized maps for `DIFF_STYLES`, `BADGE_STYLES`, `CONFLICT_BANNER_STYLES`, `SECONDARY_TEXT`, `ACCENT_COLORS`, and `COMMIT_STAT_COLORS`.
- **`workers.py`**: Concurrency execution engine using Python daemon `WorkerThread` workers and a thread-safe `_Dispatcher(QObject)` singleton on the Qt main thread. Delivers non-blocking background operations, progress streaming (`progress_cb(pct, stage)`), cooperative cancellation (`threading.Event`), and error recovery without deadlocks between Python GIL and Qt's `signalSlotLock`.


### 3.2 Core Git Engine (`src/wrench/core/`)
- **`engine.py`**: Public façade exposing unified, typed functions. Converts internal errors into typed `WrenchGitError` derivatives.
  - Remote operations: `push(repo, remote, branch, force=False)` (enforces `--force-with-lease`), `pull(repo, remote, branch)` (enforces `--ff-only`), `fetch(repo, remote)` (with `--prune` and timestamp storage), and `clone_repo(url, dest)` (atomic staging via tempdir with automated rollback).
  - Remotes façade: `list_remotes(repo)`, `add_remote(repo, name, url)`, `remove_remote(repo, name)`, `set_remote_url(repo, name, url)`, and `_probe_reachability(repo_path, remote_name)`.
- **`read_ops.py`**: `pygit2`-backed status, diffs, log traversal, branch enumeration, and line-by-line blame.
- **`write_ops.py`**: Subprocess helpers managing Git CLI execution:
  - `run_git`: Standard synchronous runner with timeout and sanitized environment (`GIT_TERMINAL_PROMPT=0`).
  - `run_git_streaming`: Deadlock-free streaming execution using concurrent dual-pipe reader threads for `stdout` and `stderr`. Parses carriage-return `\r` and `\n` progress lines, routes live percentage and stage callbacks, and terminates gracefully on `cancel_event` (`SIGTERM` ➔ 3s grace ➔ `SIGKILL`). Deterministically classifies non-zero exits into typed exceptions:
    - `WorkflowScopeRequiredError`: Detects when pushes affecting `.github/workflows/` are rejected due to missing OAuth `workflow` scope.
    - `PushRejectedError`: Non-fast-forward push rejections.
    - `MergeRequiredError`: Fast-forward pull failures when branches diverge.
    - `AuthFailedError` & `AuthRequiredError`: Credential negotiation failures.
    - `CLITimeoutError`: Subprocess execution timeout.
- **`git_credential_helper.py`**: Standalone executable (`git-credential-wrench`) implementing Git's standard credential helper protocol. Reads credentials from SQLite `wrench.db` in read-only WAL mode, resolving repo-specific bindings from `repo_forge_links` before falling back to unique host matches in `forge_accounts`. Strictly fails closed when multiple accounts share a host without explicit repository association.
- **`ssh_agent.py`**: Encapsulates platform `SSH_AUTH_SOCK` discovery and environment configuration behind the Platform-Abstraction Guard (FR-11.1–11.3).
- **`exceptions.py`**: Typed domain exceptions for Git errors, network operations, merge conflicts, and authentication failures.
- **`lock_recovery.py`**: Manages `.git/index.lock` detection with a 5-second grace window to differentiate active operations from stale crash locks.
- **`snapshots.py`**: Captures working directory states into dangling Git commit objects (`git stash create`) and compresses untracked files into `.tar.gz` archives without altering working directory status.
- **`reflog.py`**: Reflog inspection and branch restoration.
- **`identity.py`**: Validates user name and email configurations, providing repo-local configuration setters.
- **`paths.py`**: Standardized XDG data, config, and state directory resolution via `platformdirs`.
- **`crash_handler.py` & `core/recovery/`**: Local-first crash resilience framework:
  - `crash_handler.py`: Global unhandled exception hook capturing stack traces and auto-saving in-flight session drafts.
  - `process_guard.py`: Inspects `/proc` to verify whether process holding lock files is alive or defunct.
  - `sweeper.py`: Sweeps stale temporary staging files and orphan locks.
  - `transaction.py`: Transactional rollback guard for complex multi-step git operations.

### 3.3 Multi-Forge Subsystem (`src/wrench/forge/`)
- **`models.py`**: Normalized cross-provider data models:
  - `PullRequest`: Standardized entity with `state` normalized to `{"open", "merged", "closed"}`.
  - `Issue`: Standardized entity with `state` normalized to `{"open", "closed"}`.
  - `CIStatus`: Build status with state normalized to `{"success", "failure", "pending", "unknown"}`.
  - `ForgeAccount`: Runtime representation of configured accounts including TLS configuration and Secret Service references.
- **`capability.py`**:
  - `ForgeCapability`: Bitwise flags for granular feature gating (`PULL_REQUESTS`, `ISSUES`, `CI_STATUS`, `ISSUE_LINKING`, `REVIEWS`).
  - `ForgeAdapter(ABC)`: Abstract base class encapsulating `httpx.Client` with connection pooling, custom TLS CA bundle loading, self-signed skip-verification policies, automatic Secret Service token resolution, standard pagination (`_paged_get` with 500-item safeguard), and status-code-to-exception translation.
- **`registry.py`**: Pluggable adapter discovery using Python entry points (`[project.entry-points."wrench.forge_adapters"]`). Provides collision detection and the `get_adapter_for_account(account)` factory.
- **`adapters/`**: Provider-specific implementations:
  - `GitHubAdapter` (`github.py`): REST v3 API (`api.github.com` & GHES), Bearer authentication, `/issues` PR filtering, commit statuses + check-runs CI, and full review submissions (`APPROVE`, `REQUEST_CHANGES`, `COMMENT`).
  - `GitLabAdapter` (`gitlab.py`): REST v4 API (`gitlab.com` & self-hosted), Private-Token authentication, URL-encoded path slugs (`owner%2Frepo`), merge request state mapping, pipeline CI status, and self-approval trap translation.
  - `ForgejoAdapter` (`forgejo.py`): REST v1 API, token auth, commit status CI, and past-tense `APPROVED` review action mapping.
  - `BitbucketAdapter` (`bitbucket.py`): REST 2.0 API, HTTP Basic Auth (email + app password), `next` URL pagination, commit statuses, and multi-endpoint review actions.
- **`oauth/github_device_flow.py`**: Native OAuth Device Authorization Flow (RFC 8628):
  - Requests `repo workflow` scope enabling PR/issue management and workflow file updates.
  - Background polling with `slow_down` rate-limit backoff (+5s interval adjustments) and cooperative cancellation.
- **`exceptions.py`**: Typed 6-tier exception hierarchy:
  - `ForgeError`, `ForgeAuthenticationError`, `ForgeInsufficientScopeError` (with `scope_hint`), `ForgeRateLimitedError` (with `retry_after_seconds`), `ForgeUnreachableError`, and `ForgeNotFoundError`.

### 3.4 File Watcher (`src/wrench/watcher/`)
- **`inotify_watcher.py`**: Utilizes `watchdog.observers.Observer` to monitor repository directories.
  - Excludes internal `.git/` directory operations.
  - Subscribes to `on_modified` and `on_moved` / `IN_MOVED_TO` events (crucial for capturing atomic file saves from editors that write to temp files and rename).
  - Employs a 300ms single-shot `QTimer` debounce filter to collapse bursts of events into a single notification.
- **`polling_fallback.py`**: Fallback polling loop when inotify handle limits (`ENOSPC`) are reached.

### 3.5 Local Data Storage (`src/wrench/storage/`)
- **`db.py`**: Manages SQLite connection (`wrench.db`) located in `$XDG_DATA_HOME/wrench/`.
  - Configured with `check_same_thread=False`.
  - Serialized through a single process-wide `threading.Lock()` to prevent SQLite concurrency deadlocks.
  - Automated corrupt database quarantine and recovery.
- **`repo_registry.py`**: Repository CRUD operations, tracking last opened times, missing states, and relocated paths.
- **`settings.py`**: App-level and per-repository key-value configuration storage.
- **`forge_accounts.py`**: Forge account metadata storage and repository-to-account bindings (`repo_forge_links`):
  - Supports `tls_ca_bundle_path` and `tls_insecure` columns.
  - Atomic two-step insert-then-update with automatic rollback on Secret Service storage failure.
  - Fast-path path-based link resolution for `git-credential-wrench`.
- **`schema.sql`**: Normalized relational schema with foreign key cascading deletes.

### 3.6 Credentials & Platform Layer (`src/wrench/credentials/`)
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

### 4.7 Theme System & Instant Theme Switching Architecture
```
[Desktop Theme Change (KDE/GNOME/Windows)] OR [View -> Theme Menu Selection]
                            │
                            ▼
           [QGuiApplication.styleHints().colorSchemeChanged]
                                    OR
                     [MainWindow._set_theme(mode)]
                            │
                            ├── 1. Apply Qt QPalette (Latte Pastel / Mocha Pastel / Native System)
                            ├── 2. Recursive Palette Propagation to all topLevelWidgets() & children
                            ├── 3. Persist mode to SQLite app_settings ('theme')
                            │
                            ▼
             [Broadcast QEvent.PaletteChange & ApplicationPaletteChange]
                            │
          ┌─────────────────┼─────────────────┐
          ▼                 ▼                 ▼
   [TabContainer]    [ChangesTab]      [HistoryTab]
          │                 │                 │
          ├── Refresh tabs  ├── Refresh badges├── Refresh stats
          │   (active /     ├── Conflict theme├── Graph viewport
          │    inactive)    └── DiffWidget    └── Detail panel & DiffWidget
          │                 │                 │
          └─────────────────┼─────────────────┘
                            ▼
                 [DiffWidget.changeEvent]
                            │
                            ▼
              [_render_diff() with Catppuccin Velvet Pastel]
              - Light: Mint green (#dcefd8) & blush rose (#fcd7db)
              - Dark: Velvet mint (#1e3527) & flamingo rose (#3b1d28)
              - Seamless zero-latency instant re-render
```

#### 4.7.1 Palette Isolation & Recursive Descendant Propagation
In Qt's widget engine, applying an inline stylesheet (`setStyleSheet`) to a container widget (such as `QSplitter` in `ChangesTab` or `QGroupBox` in the commit section) assigns that widget a dedicated `QStyleSheetStyle` instance with a snapshot of the palette at construction time. Consequently, subsequent calls to `QApplication.setPalette()` do **not** automatically update the palette of already-instantiated child widgets inside that styled container (such as `QListWidget` or `QTextEdit`).

To ensure 100% theme fidelity when switching themes:
1. `apply_theme(app, mode)` applies the selected `QPalette` to `QApplication`.
2. It then traverses every top-level window via `QApplication.topLevelWidgets()` and sets the palette on each window and every descendant widget found via `top_widget.findChildren(QWidget)`.
3. `MainWindow._propagate_theme_refresh()` directly invokes `refresh_theme()` on child workspaces (`TabContainer`, `ChangesTab`, `HistoryTab`) to immediately recompute any dynamic CSS or color tokens without waiting for deferred event loop cycles.

#### 4.7.2 Event Recursion Protection
In Qt's style sheet architecture, calling `QWidget.setStyleSheet()` dispatches an internal `QEvent.PaletteChange` event to the widget. If a widget re-applies its stylesheet directly inside its `changeEvent(event)` handler when observing `PaletteChange`, an unbounded recursive loop (`maximum recursion depth exceeded`) occurs.

Wrench implements recursion guards across all theme-responsive components:
- `TabButton`: Guarded by `_updating_style` flag in both `changeEvent` and `_update_style()`.
- `ChangesTab`: Guarded by `_refreshing_theme` flag in `changeEvent`.
- `HistoryTab`: Guarded by `_refreshing_theme` flag in `changeEvent`.
- `BranchSwitcherWidget`: Guarded by `_updating_display_active` in `changeEvent`.

#### 4.7.3 Luminance-Based Theme Detection
`QGuiApplication.styleHints().colorScheme()` queries the host desktop environment (e.g., KDE Plasma or GNOME). On systems where the desktop runs in Dark Mode but the user selects "Pastel Light" in Wrench (or vice versa), `colorScheme()` returns the desktop setting rather than the application's active palette.

`is_dark_theme(widget)` resolves this by calculating the actual luminance of the palette:
$$\text{Luminance} = \frac{\text{lightnessF}(Window) + \text{lightnessF}(Base)}{2.0}$$
If $\text{Luminance} < 0.5$, the widget/app is dark; otherwise it is light. This guarantees flawless theme detection across all platforms and desktop environments.

#### 4.7.4 Design Tokens & Contrast System
| Component | Catppuccin Latte Pastel (Light) | Catppuccin Mocha Velvet Pastel (Dark) |
|---|---|---|
| **Window Canvas** | `#eff1f5` (Warm pastel mist) | `#181825` (Velvety midnight slate) |
| **Card / Editor Base** | `#ffffff` (Crisp card white) | `#11111b` (Deep crust base) |
| **Primary Text** | `#4c4f69` (Charcoal slate) | `#cdd6f4` (Frosted mist white) |
| **Secondary Subtext** | `#7c7f93` (Muted slate) | `#9399b2` (Soft lavender-gray) |
| **Highlight Accent** | `#1e66f5` (Sapphire blue) | `#89b4fa` (Pastel sky blue) |
| **Diff Addition** | `#dcefd8` bg / `#216e39` text / `#40a02b` bar | `#1e3527` bg / `#a6e3a1` text / `#a6e3a1` bar |
| **Diff Deletion** | `#fcd7db` bg / `#a8233e` text / `#d20f39` bar | `#3b1d28` bg / `#f38ba8` text / `#f38ba8` bar |
| **Diff Hunk Header** | `#e6e9f8` bg / `#1e66f5` text / `#ccd0da` border | `#1e2640` bg / `#89b4fa` text / `#313244` border |
| **Status Badge: Modified (M)** | `#1e66f5` fg / `#e0e7ff` bg | `#89b4fa` fg / `#1e2942` bg |
| **Status Badge: Added (A)** | `#40a02b` fg / `#dcfce7` bg | `#a6e3a1` fg / `#1b3526` bg |
| **Status Badge: Deleted (D)** | `#d20f39` fg / `#fee2e2` bg | `#f38ba8` fg / `#3b1c28` bg |
| **Status Badge: Untracked (?)** | `#7c7f93` fg / `#e6e9ef` bg | `#9399b2` fg / `#282a3a` bg |
| **Warning / Detached HEAD** | `#df8e1d` (Amber Latte) | `#f9e2af` (Amber Mocha) |
| **Primary Commit Button** | `#1e66f5` (Sapphire) bg / `#ffffff` text (disabled: `#e6e9ef` bg / `#7c7f93` text) | Native Qt button (`setStyleSheet("")`, untouched) |
| **Repo Dropdown Text** | `#4c4f69` (Charcoal slate) on transparent / `#ffffff` popup | `palette(window-text)` (untouched) |

### 4.8 Commit Graph Rendering & Synchronized Pixel Scrolling Architecture
```
[Main Horizontal Scroll Event / Mouse Drag / Trackpad Pan]
                             │
                             ▼
     [CommitGraphWidget.setHorizontalScrollMode(ScrollPerPixel)]
                             │
                             ├── Fluid per-pixel horizontal movement across all columns
                             │   (eliminates default QTableView column-snapping stutter)
                             │
                             ▼
             [scrollContentsBy(dx, dy) Override]
                             │
                             ├── 1. Trigger base table viewport repainting
                             │
                             └── 2. Invoke _update_graph_scrollbar_geometry()
                                     │
                                     ├── Calculate Column 0 Viewport Coordinate:
                                     │   x_col0 = viewport().x() + header.sectionViewportPosition(0)
                                     │
                                     ├── Translate DAG Scrollbar to x_col0:
                                     │   - Translates left in lockstep as main table scrolls right
                                     │   - Clips left boundary to max(viewport().x(), x_col0)
                                     │   - Clips right boundary to prevent overlapping vertical scrollbar
                                     │
                                     └── Visibility Rules:
                                         - Visible when DAG width > Column 0 width AND Column 0 is in viewport
                                         - Hidden when Column 0 scrolls completely off-screen to the left
                                         - Hidden when all DAG lanes fit within Column 0 without scrolling
```

#### 4.8.1 Two-Tier Horizontal Scrolling Coordination
The `CommitGraphWidget` visualizes Git commit histories with an interactive topological DAG rendered in Column 0 (`"Graph"`) alongside standard textual metadata columns (`"SHA"`, `"Author"`, `"Date"`, `"Message"`). Because the number of concurrent branches can expand the DAG lane width beyond Column 0's allocated width, the DAG column requires independent horizontal panning (`_graph_scroll_x`).

To prevent UI conflicts between table-level scrolling and column-level scrolling:
1. **Fluid Pixel Scrolling**: The table is configured with `setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)` and `setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)`, eliminating stepped column snapping and providing fluid scrolling across high-resolution displays and touchpads.
2. **Synchronized Overlay Scrollbar**: A dedicated `QScrollBar` is placed as an overlay pinned to the bottom of the table viewport. Instead of remaining static at $x=0$, its horizontal geometry is dynamically bound to Column 0's position:
$$x_{\text{scrollbar}} = \text{viewport}().x() + \text{header}.\text{sectionViewportPosition}(0)$$
$$w_{\text{scrollbar}} = \min(\text{header}.\text{sectionSize}(0), \text{viewport}().width() - (x_{\text{scrollbar}} - \text{viewport}().x()))$$
3. **Synchronous Viewport Updates**: Overriding `scrollContentsBy(dx, dy)` guarantees that the overlay scrollbar updates synchronously with the table's native scrolling pipeline, eliminating visual latency or detachment during continuous scrolling.

### 4.9 Multi-Forge API Execution & SWR Caching Workflow
```
[User Selects PRs/Issues Tab OR Triggers Refresh]
                    │
                    ▼
[PRListTab / IssueListTab.reload_links_and_data()]
                    │
                    ├── 1. Query SQLite: repos & repo_forge_links
                    │      └── Resolves linked forge_account_id, owner_slug, repo_slug
                    │
                    ├── 2. Query SQLite: forge_accounts
                    │      └── Resolves instance_url, provider, credentials key, TLS config
                    │
                    ▼
[forge.registry.get_adapter_for_account(acc)]
                    │
                    ├── Instantiates provider adapter (GitHub, GitLab, Forgejo, Bitbucket)
                    ├── Configures httpx.Client (TLS verify bundle / insecure override)
                    └── Lazily retrieves token from D-Bus Secret Service
                    │
                    ▼
[Check SWR (Stale-While-Revalidate) In-Memory Cache]
                    │
         ┌──────────┴────────────────────────────────┐
         ▼                                           ▼
[Cache Hit (< 60s & not bypass)]             [Cache Miss / Stale (>= 60s)]
         │                                           │
         ├── Render immediately from cache           ├── 1. If stale cache exists, render immediately
         └── Done (0 network latency)                │
                                                     ├── 2. Increment _load_generation counter (race guard)
                                                     ├── 3. ui.workers.run_in_background(adapter.list_...)
                                                     │
                                                     ▼
                                      [Background Thread Execution]
                                                     │
                                                     ├── Executes REST/GraphQL via httpx
                                                     │
                                      ┌──────────────┴──────────────┐
                                      ▼                             ▼
                              [Success (HTTP 200)]          [Error (4xx / 5xx / Net)]
                                      │                             │
                                      ├── Verify gen_id == _gen     ├── Verify gen_id == _gen
                                      ├── Store in _cache[(path,)]  ├── Map typed exception:
                                      ├── Update TableModel         │     ForgeAuthenticationError,
                                      └── Toggle Empty State View   │     ForgeInsufficientScopeError,
                                                                    │     ForgeRateLimitedError,
                                                                    │     ForgeUnreachableError
                                                                    └── ForgeErrorBanner.show_error(exc)
```

#### 4.9.1 Out-of-Order Request Race Protection
When switching between repositories, remotes, or filters in rapid succession, background worker threads may complete out of order (e.g., an older slow request resolves after a newer fast request).
To prevent UI desynchronization, `PRListTab` and `IssueListTab` maintain an integer monotonic `_load_generation` counter:
1. Every new fetch request increments `_load_generation` and captures the current generation ID `gen_id`.
2. When the background worker emits `on_finished` or `on_failed` back to the main GUI thread, the handler compares `gen_id == self._load_generation`.
3. If the IDs do not match, the response is discarded immediately as stale.

### 4.10 GitHub Device Authorization Flow (OAuth RFC 8628) & Re-authorization Workflow
```
[User clicks "Sign in with GitHub" in AccountsDialog OR "Re-authenticate" on ErrorBanner]
                                      │
                                      ▼
[GitHubDeviceFlowClient.request_device_code(client_id, scope="repo workflow")]
                                      │
                                      ├── POST https://github.com/login/device/code
                                      │   Request scopes: "repo", "workflow"
                                      │
                                      ▼
                      [Response: RFC 8628 Device Payload]
                      - device_code: Secret token for polling
                      - user_code: Human verification code (e.g. ABCD-1234)
                      - verification_uri: https://github.com/login/device
                      - interval: 5 seconds
                                      │
                                      ▼
                   [AccountsDialog Displays Modal Device Code UI]
                                      │
                                      ├── Copies user_code to system clipboard
                                      ├── Displays user_code in large monospace font
                                      ├── Automatically launches default browser to verification_uri
                                      │
                                      ▼
               [ui.workers.run_in_background: Polling Loop]
                                      │
                                      ├── Every (interval) seconds:
                                      │   POST https://github.com/login/oauth/access_token
                                      │
                   ┌──────────────────┼─────────────────────────┐
                   ▼                  ▼                         ▼
         [authorization_pending]   [slow_down]           [Success: access_token]
                   │                  │                         │
                   ├── Wait interval  └── interval += 5         ├── GET https://api.github.com/user
                   └── Poll again         Poll again            │   (Resolves authenticated username)
                                                                │
                                                                ▼
                                              [In-Place Re-auth vs. New Account]
                                                                │
                                       ┌────────────────────────┴────────────────────────┐
                                       ▼                                                 ▼
                          [Re-authorizing Existing Account]                     [New Forge Account]
                                       │                                                 │
                                       ├── Preserve account ID & link bindings           ├── Insert into forge_accounts
                                       ├── Update D-Bus Secret Service token in-place    ├── Store token in D-Bus Secret Service
                                       └── Refresh AccountsDialog list                   └── Refresh AccountsDialog list
```

### 4.11 Workflow Scope Error Classification & Push Protection Workflow
```
[User triggers Push in ChangesTab / MainWindow]
                      │
                      ▼
[core.write_ops.run_git_streaming: git push <remote> <branch>]
                      │
                      ├── Drains stderr stream concurrently
                      │
                      ▼
        [Non-Zero Exit & stderr Stream Inspection]
                      │
   ┌──────────────────┴─────────────────────────────────────────┐
   ▼                                                            ▼
["refusing to allow an OAuth App to create or update workflow"] [Generic Non-Zero Exit]
   │                                                            │
   ▼                                                            ▼
[Raise WorkflowScopeRequiredError]                             [Classify PushRejectedError /
   │                                                            MergeRequiredError / AuthFailedError]
   ▼                                                            │
[MainWindow.on_failed(exc)]                                    ▼
   │                                                            [Generic Push Conflict Dialog:
   ├── Inspects isinstance(exc, WorkflowScopeRequiredError)      Prompt: "Fetch & Retry" / "Force Push"]
   │
   ▼
[Dedicated GitHub Workflow Scope Recovery Dialog]
   - Informs user: Commits modify .github/workflows/ without OAuth "workflow" scope
   - Prevents destructive Force Push loops or redundant Fetch & Retry attempts
   - Action Button: "Open Accounts & Re-authenticate"
        └── Launches AccountsDialog with pre-configured "repo workflow" OAuth scopes
```

#### 4.11.1 Prevention of Infinite Fetch-Retry Loops
GitHub returns HTTP 403 with `refusing to allow an OAuth App to create or update workflow... without \`workflow\` scope` whenever a commit modifies files in `.github/workflows/` and the pushing credential helper or OAuth token lacks the `workflow` scope.
If treated as a generic `PushRejectedError`, GUI clients mistakenly suggest "Fetch and Retry" or "Force Push". Neither action succeeds because the rejection is authorization-based rather than reference non-fast-forward.
By raising `WorkflowScopeRequiredError` before generic rejection classification, Wrench intercepts the failure at the core engine level and directs the user straight to in-place OAuth token re-authorization with the required `"repo workflow"` scopes.

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
                                 │ tls_ca_bundle_path                 │
                                 │ tls_insecure                       │
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
│       ├── phase-3.md
│       └── phase-4.md
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
│   │   ├── paths.py              # XDG / platformdirs path resolution
│   │   └── recovery/             # Automatic corruption & lock recovery subsystem
│   │       ├── actions.py        # Remediation actions (unlock, fsck, quarantine)
│   │       ├── classifier.py     # Health diagnostics & error classification
│   │       ├── process_guard.py  # Lock file ownership & PID inspection
│   │       ├── sweeper.py        # Background garbage collection & cleanup
│   │       └── transaction.py    # Atomic rollback & snapshot journals
│   ├── credentials/              # Secret Service & credential backends
│   │   ├── backend.py            # CredentialBackend abstract interface
│   │   └── secret_service.py     # D-Bus Secret Service platform backend
│   ├── forge/                    # Forge provider capability system
│   │   ├── capability.py         # ForgeCapability flags & ForgeAdapter ABC
│   │   ├── exceptions.py         # Typed forge error hierarchy
│   │   ├── models.py             # Dataclasses: PullRequest, Issue, CIStatus
│   │   ├── registry.py           # Dynamic entry point & provider adapter registry
│   │   ├── adapters/             # Forge provider implementations
│   │   │   ├── github.py         # GitHub REST/GraphQL adapter
│   │   │   ├── gitlab.py         # GitLab REST adapter
│   │   │   ├── forgejo.py        # Forgejo / Gitea REST adapter
│   │   │   └── bitbucket.py      # Bitbucket Cloud REST adapter
│   │   └── oauth/                # OAuth flows
│   │       └── github_device_flow.py # RFC 8628 Device Authorization Flow client
│   ├── storage/                  # SQLite storage & repository registry
│   │   ├── db.py                 # SQLite connection management & locks
│   │   ├── repo_registry.py      # Repository tracking CRUD
│   │   ├── settings.py           # App & repo key-value settings
│   │   ├── forge_accounts.py     # Forge accounts, repo links & TLS settings
│   │   └── schema.sql            # Normalized relational schema
│   ├── ui/                       # PySide6 desktop UI
│   │   ├── main_window.py        # Main application window & repository menu
│   │   ├── theme.py              # Catppuccin Velvet Pastel palettes & theme management
│   │   ├── workers.py            # Thread-safe background worker marshaller
│   │   ├── commit_graph/         # Topological DAG layout & custom table view
│   │   │   ├── layout.py         # S-curve calculation & slot recycling
│   │   │   └── graph_widget.py   # CommitGraphWidget & custom delegate
│   │   ├── dialogs/              # Interactive dialogs & account managers
│   │   │   ├── accounts_dialog.py# Forge accounts manager & OAuth Device Flow
│   │   │   ├── link_dialog.py    # Remote-to-forge account association dialog
│   │   │   └── remotes_dialog.py # Repository remotes manager & reachability
│   │   ├── diff_view/            # Syntax-highlighted diff viewer & staging
│   │   ├── forge_panel/          # Forge UI integration components
│   │   │   ├── badges.py         # Catppuccin Velvet Pastel pill painter
│   │   │   ├── create_pr_dialog.py # New Pull Request modal dialog
│   │   │   ├── error_banner.py   # Inline forge error notifications
│   │   │   ├── info_popover.py   # Hover inspection popovers
│   │   │   └── review_dialog.py  # PR review & approval dialog
│   │   ├── merge_tool/           # 3-Way visual merge conflict resolution tool
│   │   │   └── merge_dialog.py   # Conflict side-by-side editor & resolution
│   │   ├── recovery/             # Recovery & progress modals
│   │   │   ├── busy_dialog.py    # Modal progress tracker & cancel button
│   │   │   └── recovery_dialog.py# Busy operation tracking & repo diagnostics
│   │   ├── snapshots_panel/      # Rolling snapshots browser & restore panel
│   │   │   └── snapshots_panel.py# Snapshot timeline & restore triggers
│   │   ├── tabs/                 # Hybrid tab navigation system
│   │   │   ├── tab_bar.py        # TabContainer & TabButton widgets
│   │   │   ├── changes_tab.py    # Primary Changes workspace
│   │   │   ├── history_tab.py    # History / Commit graph workspace
│   │   │   ├── pr_list_tab.py    # Pull Requests virtualized list & filters
│   │   │   ├── pr_detail_tab.py  # Pull Request discussion & diff inspector
│   │   │   ├── issue_list_tab.py # Issues virtualized list & filters
│   │   │   └── issue_detail_tab.py # Issue discussion & state toggles
│   │   └── widgets/              # Reusable UI widgets
│   │       └── branch_switcher.py# Interactive branch selector & popup
│   └── watcher/                  # Inotify filesystem watching & debouncing
└── tests/                        # Comprehensive test suite (unit, integration, UI)
```
