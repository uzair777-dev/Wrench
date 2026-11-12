# Wrench Architecture

This document describes the design principles, component architecture, concurrency model, and data flow of **Wrench**.

---

## 1. Architectural Principles

Wrench is engineered around six non-negotiable architectural tenets:

1. **Hybrid Core Git Engine (Split Read/Write Responsibility)**:
   - **Read Operations** (`status`, `diff`, `log`, `blame`, `lfs_status`, `list_submodules`, `list_reflog`) are executed in-process using `pygit2` (libgit2 C bindings) for millisecond latency and structured in-memory traversal without process-spawning overhead.
   - **Write & Risky Operations** (`commit`, `branch`, `switch`, `merge`, `rebase`, `push`, `pull`, `fetch`, `credential negotiation`, `lfs_track`, `submodule_update`, `bundle`) are delegated to the system `git` CLI via subprocess. This guarantees 100% fidelity with git's battle-tested merge/rebase conflict handling, index updates, and credential protocols.
2. **Strict Layering & One-Directional Data Flow**:
   ```
   UI Layer (PySide6)
         │
         ▼
   Façade Layer (core.engine / forge.registry / storage.settings_registry)
         │
   ┌─────┴───────────────────────┬────────────────────────┬────────────────────────┐
   ▼                             ▼                        ▼                        ▼
   Read Engine (pygit2)     Write Engine (git CLI)   Forge Adapters (httpx)   Storage Engine (SQLite WAL)
   ```
   - **Rule**: UI code *never* directly imports `pygit2`, calls `subprocess`, invokes `httpx`, or touches raw storage database connections. All interactions pass through the public `core.engine`, `forge.registry`, and `storage.settings_registry` façades.
3. **Thread Safety & Non-Blocking UI**:
   - Heavy write operations, network calls, and repository clones run in dedicated background threads (`ui.workers.run_in_background`).
   - Callback execution is marshalled back to the main GUI thread using Qt queued signals (`_Dispatcher`) to avoid thread race conditions and UI crashes.
4. **Local-First & Non-Destructive Safety**:
   - Every potentially destructive action is protected by safety snapshots (`git stash create` commit objects + `.tar.gz` untracked files) before execution, providing single-click undo and reflog restoration.
5. **Universal Configurability & Zero-Overhead Feature Gating (`VP-0`)**:
   - Every single subsystem, feature, background timer, and network operation is governed by the **13-category Universal Settings Registry** (`storage/settings_registry.py`, 83 registered `DEFAULT_SETTING_SPECS`).
   - Settings expose a progressive two-tier UI via `SettingTier` (`Normal` for 17 everyday preferences including `ui.settings_view_mode`, `Advanced` for all 83 settings including per-repo overrides) and propagate live via `SettingsRegistry.setting_changed`.
   - Disabled features/forges short-circuit in `< 0.05 ms` without spawning background threads, timers, or network requests (`OPT-1`).
   - Settings support hierarchical scoping (`repo_settings_overrides` > `global_settings` > default specs), instant pre-indexed search (`OPT-2`), a 100-entry SQLite-persisted delta-only undo log (`settings_undo_log`, `OPT-3`), and 1-click presets (e.g. Minimalist Local-Only Mode).
6. **Automated AST Security & Anti-Hallucination Integrity Guard**:
   - Enforced by `tests/unit/test_no_shortcuts_guard.py` across the entire codebase.
   - Verifies AST structural invariants: UI layer never imports backend modules directly (`pygit2`, `subprocess`, `sqlite3`, `httpx`, `storage.db`, `read_ops`, `write_ops`); zero `shell=True` or `raise NotImplementedError` stubs (`FLASH-1`); zero truncation markers; zero unhandled `except Exception: pass` swallows (`FLASH-5`); and zero f-string/dynamic string interpolation in SQL executions (`SEC-7`).
7. **Intent-Preserving Staging Consistency & Pre-Commit Hook Lifecycle**:
   - **Partial Staging Integrity (`MM`/`AM`)**: Tracks dual-status files (staged index hunks vs unstaged working-tree modifications). When committing checked files with unstaged edits, `PartialStagingDialog` eliminates stale-index desynchronization.
   - **Pre-Commit Formatter Auto-Remediation**: Detects non-zero hook aborts caused by auto-formatters (`black`, `ruff --fix`, `prettier`, `cargo fmt` modifying working tree files) and provides 1-click `[Stage Formatted Changes & Retry Commit]` execution.
   - **Virtualenv-Aware Tool Discovery**: Formatter and hook diagnostics discover local project binaries (`.venv/bin/`, `venv/bin/`, `node_modules/.bin/`) before querying system `PATH`.
8. **Monorepo Scalability, Partial Clone & Transport Hardening (`VP-16`)**:
   - **Cursor-Paginated Commit Graph & Viewport Virtualization**: Walks commit history incrementally via `_ACTIVE_WALKER_CACHE` and `get_log_page` sized by `performance.graph_page_size`, paired with `QThreadPool` workers, viewport-clipped painting, and DPR-scaled `QPixmapCache` caching.
   - **Cone-Mode Sparse-Checkout & Partial Clone**: Supports `--filter=blob:none`/`tree:0` and `--sparse` cloning alongside `SparseCheckoutDialog` cone directory management, guarded by `security_sanitizer.py` (`SEC-2`/`SEC-3`).
   - **Adaptive 3-Tier Watcher & Diff Protection**: Automatically steps down from full worktree `inotify` -> `.git`-only metadata `inotify` -> Qt-thread polling on watch-limit errors, runs background `git commit-graph write --reachable`, and enforces a default 5,000-line / KB cap on `DiffView` with 1-click full-diff loading.

---

## 2. High-Level Component Diagram

```text
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                               UI LAYER (PySide6 / Qt 6)                                │
│                                                                                        │
│  ┌──────────────────────────────────────────────────────────────────────────────────┐  │
│  │ MainWindow (ui/main_window.py)                                                   │  │
│  │   • MenuBar: File | Edit | View | Repository | Help                              │  │
│  │   • Central Lifecycle Coordinator, Live Settings Sync & Actionable Error Routing │  │
│  │   • Dialogs: CloneDialog | SparseCheckoutDialog | PartialStagingDialog | Merge | │  │
│  │              InteractiveRebaseDialog | Remotes | Accounts | LinkRepo |           │  │
│  │              DiscoverRepos | Submodule | SettingsDialog (13 Cats) | AboutDialog  │  │
│  │              PushRecovery | BusyDialog                                           │  │
│  │   • Docks:   ActivityLogBar (Ctrl+`) & CliCommandPreviewBar                     │  │
│  │   • Theme Engine (theme.py): Recursive Palette & Event Broadcast to all widgets  │  │
│  └───────┬──────────────────────────────────────────────────────────────────▲───────┘  │
│          │                                                                  │          │
│          ▼                                                                  │          │
│  ┌──────────────────────────────────────────────────────────────────────┐   │          │
│  │ TabContainer (ui/tabs/tab_bar.py) - Dynamic Hybrid Tab Shell         │   │ Queued   │
│  │  ┌─────────────────────────────────┐ ┌─────────────────────────────┐ │   │ Signals  │
│  │  │ ChangesTab (Pinned Workspace)   │ │ HistoryTab                  │ │   │          │
│  │  │  • BranchSwitcherWidget         │ │  • CommitGraphWidget(100k+) │ │   │          │
│  │  │  • Unified File List & MM/AM    │ │  • Search/Filter Bar (300ms)│ │   │          │
│  │  │  • DiffView (5k Cap) & Staging  │ │  • CommitDetailPanel(Avatar)│ │   │          │
│  │  │  • Commit & Amend Box (Avatar)  │ │  • Branch & Ref Badges      │ │   │          │
│  │  └─────────────────────────────────┘ └─────────────────────────────┘ │   │          │
│  │  ┌─────────────────────────────────────────────────────────────────┐ │   │          │
│  │  │ Multi-Forge Tabs (ui/tabs/ & ui/forge_panel/)                   │ │   │          │
│  │  │  • PRListTab & IssueListTab (SWR 60s Cache, Table Avatars)      │ │   │          │
│  │  │  • PRDetailTab & IssueDetailTab (40px Header Avatar, CI Status) │ │   │          │
│  │  └─────────────────────────────────────────────────────────────────┘ │   │          │
│  │  ┌─────────────────────────────────────────────────────────────────┐ │   │          │
│  │  │ Avatar Subsystem (ui/widgets/avatar.py)                         │ │   │          │
│  │  │  • AvatarLoader Singleton (2-tier mem + 7d SHA-256 disk cache)  │ │   │          │
│  │  │  • AvatarWidget (smooth circle, initial badge fallback, themes) │ │   │          │
│  │  │  • Gravatar Privacy Gate (default-OFF opt-in in Settings)       │ │   │          │
│  │  └─────────────────────────────────────────────────────────────────┘ │   │          │
│  │  ┌─────────────────────────────────────────────────────────────────┐ │   │          │
│  │  │ Preferences Subsystem (ui/dialogs/settings_dialog.py)           │ │   │          │
│  │  │  • 13-Category Nav, Normal (17) / Advanced (83) Tier Switcher   │ │   │          │
│  │  │  • Lazy Page Loading (OPT-1) & Instant Search (< 5ms, OPT-2)    │ │   │          │
│  │  │  • Scope Selector: Global Defaults vs Per-Repo Overrides        │ │   │          │
│  │  │  • Minimalist Preset, 150ms Debounce & 100-Entry SQLite Undo    │ │   │          │
│  │  └─────────────────────────────────────────────────────────────────┘ │   │          │
│  └────────────────────────────────────────┬─────────────────────────────┘   │          │
│                                           │                                 │          │
│  ┌────────────────────────────────────────▼─────────────────────────────┐   │          │
│  │ Worker Thread Pool & Dispatchers (ui/workers.py & QThreadPool)       ├───┘          │
│  │  • Daemon WorkerThreads & QRunnables with queued main-thread dispatch│              │
│  └──────────────────────────────────────────────────────────────────────┘              │
└──────────────▲────────────────────┬─────────────────────────────┬──────────────────────┘
               │                    │                             │                       
    Qt Signals │   Git Operations   │                             │ Forge REST APIs       
   (3-Tier Fs) │  (Façade Pipeline) │                             │ (SWR 60s Cache)       
               │                    ▼                             ▼                       
┌──────────────┴───────┐  ┌─────────┬──────────────────────┐  ┌───┬──────────────────────┐
│  FILESYSTEM WATCHER  │  │   CORE GIT ENGINE (core/)      │  │  MULTI-FORGE (forge/)    │
│ (src/wrench/watcher) │  │                                │  │                          │
│                      │  │ • engine.py (Façade API)       │  │ • forge.registry         │
│ • inotify_watcher.py │  │ • read_ops.py (pygit2 reads)   │  │   - Entry-point plugins  │
│   (RepoWatcher)      │  │   - status, diff, paged log    │  │   - Zero-overhead gating │
│   - T1: full_inotify │  │ • write_ops.py (git CLI writes)│  │ • forge.capability       │
│   - T2: git_dir_only │  │   - commit, branch, clone, cg  │  │   - ForgeAdapter Base    │
│   - T3: Qt polling   │  │ • rebase_sequencer.py (VP-2)   │  │   - get_avatar_url()     │
│   - suspend()/resume │  │   - rebase_editor_helper.py    │  │ • Concrete Adapters:     │
│   - 300ms debounce   │  │ • sparse_checkout.py (Cone)    │  │   - GitHubAdapter        │
│ • polling_fallback.py│  │ • security_sanitizer.py        │  │   - GitLabAdapter        │
│ • Signals Emitted:   │  │   - SEC-2 URL / SEC-3 Redact   │  │   - ForgejoAdapter       │
│   - status_changed   │  │ • discovery.py (FR-1.12 scan)  │  │   - BitbucketAdapter     │
│   - adaptive_fallback│  │ • paths.py / ssh_agent.py      │  │ • author_avatar_url maps │
│     _activated       │  │ • snapshots.py / lock_recovery │  │ • github_device_flow.py  │
│                      │  │ • identity.py / crash_handler  │  │   - RFC 8628 Device Flow │
│                      │  │ • lazy_loader.py (PEP 810)     │  │ • TLS Custom CA / Verify │
└──────────────────────┘  └────────────────┬───────────────┘  └────────────┬─────────────┘
                                           │                               │              
                    Snapshot / Config      │              Token Storage    │              
                          Persistence      ▼               & Resolution    ▼              
┌────────────────────────────────────────┬─┐  ┌────────────────────────────┬─────────────┐
│   STORAGE LAYER (src/wrench/storage)   │ │  │  CREDENTIALS (src/wrench/credentials)    │
│                                        │ │  │                                          │
│ • SQLite Database (wrench.db, Schema v3│ │  │ • credentials.py: Backend factory        │
│   - Single coarse mutex + WAL mode     │ │  │ • SecretServiceBackend (D-Bus Secret API)│
│ • settings_registry.py (Universal Reg) │ │  │   - KDE KWallet & GNOME Keyring          │
│   - 13 Cats, 83 Specs, Normal/Advanced │ │  │   - Zero plaintext tokens on disk        │
│   - 100-Entry SQLite Delta Undo (OPT-3)│ │  │ • OAuth RFC 8628 tokens resolution       │
│ • repo_registry.py: MRU, clear_missing │ │  │ • Disambiguated accounts per remote host │
│ • settings.py: Session & alias bridge  │ │  │                                          │
│ • snapshots.py: Recovery records & OIDs│ │  │                                          │
│ • forge_accounts.py: Accounts & links  │ │  │                                          │
│ • health.py: Integrity checks & repair │ │  │                                          │
│ • Schema migrations & backup handling  │ │  │                                          │
└────────────────────────────────────────┴─┘  └────────────────────────────┴─────────────┘
                                         │                                 │              
                                         │ Query Account Link              │ D-Bus Secret 
                                         └────────────────┬────────────────┘ Handshake    
                                                          ▼                               
                                           ┌──────────────┬──────────────┐                
                                           │    git-credential-wrench    │                
                                           │   (CLI Credential Helper)   │                
                                           │ • Git credential protocol   │                
                                           │ • Disambiguated link lookup │                
                                           └─────────────────────────────┘                
```

### 2.1 Subsystem Dataflow & Interaction Summary

1. **User Interface (`src/wrench/ui`)**:
   - `MainWindow` coordinates top-level application actions, modal dialogs (`CloneDialog`, `SparseCheckoutDialog`, `PartialStagingDialog`, `MergeDialog`, `InteractiveRebaseDialog`, `RemotesDialog`, `AccountsDialog`, `LinkRepoDialog`, `DiscoverReposDialog`, `SubmoduleDialog`, `SettingsDialog`, `AboutDialog`, `BusyOperationDialog`, `PushRecoveryDialogs`), live setting propagation (`_on_registry_setting_changed`), background `commit-graph` maintenance, coalesced `DeferredDelete` heap reclamation (`_heap_trim_timer`), and actionable error routing.
   - `TabContainer` manages dynamic tab lifecycles (`ChangesTab`, `HistoryTab`, `PRListTab`, `IssueListTab`, `PRDetailTab`, `IssueDetailTab`), disposing closed hidden tab widgets and pooled HTTP clients cleanly.
   - Theme changes in `theme.py` trigger recursive palette recalculation and broadcast across all child widgets, status pills, and open dialogs without application restarts.
   - Heavy background tasks run through `run_in_background` (`ui/workers.py`) and `QThreadPool` workers (`_GraphPageWorker`, `_GraphSearchWorker`, `_TreeExpandWorker`, `_ApplySparseWorker`, `_CommitGraphWorker`), posting results via thread-safe Qt queued `_Dispatcher` signals back to the main thread.
   - **Avatar Subsystem (`ui/widgets/avatar.py`)**: `AvatarLoader` singleton resolves user avatars via a 2-tier cache (memory + 7-day disk cache with SHA-256 keying) and non-blocking background downloads. `AvatarWidget` renders anti-aliased circular avatars with deterministic initials badges. Commit author Gravatars are strictly gated behind the default-OFF `ui.avatars_gravatar` privacy setting on `SettingsDialog`.
   - **Universal Preferences Center (`ui/dialogs/settings_dialog.py`)**: Two-row header (`top_row_1`, `top_row_2`) interface displaying 83 `DEFAULT_SETTING_SPECS` across 13 categories (`General & UI`, `Staging & Commits`, `Commit Graph`, `Diff & Merge`, `Branches & Stacks`, `Worktrees & Submodules`, `Remotes & LFS`, `Forges & CI`, `Hooks & Signing`, `Blame & Search`, `Watcher & Performance`, `Safety & Backups`, `Custom Actions & Shortcuts`). Supports `SettingTier` (`Normal` = 17 basic preferences including `ui.settings_view_mode`, `Advanced` = all 83 preferences with scope toggle, Modified filter, Reset Category, and Minimalist Preset), `< 5 ms` instant search filtering (`OPT-2`), lazy page construction (`OPT-1`), `150ms` debounced auto-save with `flush_pending()` on close, and a 100-entry SQLite-persisted delta-only undo log (`OPT-3`).
   - **Submodules & Monorepo Dialogs (`ui/dialogs/submodule_dialog.py`, `clone_dialog.py`, `sparse_checkout_dialog.py`)**: Non-blocking dialogs for submodule workflows, partial/sparse clones (`--filter=blob:none` / `tree:0`, `--sparse`), and Cone-mode sparse-checkout tree management with live secret-redacted `CliCommandPreviewBar` footers.

2. **Core Git Operations (`src/wrench/core`)**:
   - Strict read/write separation: read operations (status, diffs, paginated log traversal via `_ACTIVE_WALKER_CACHE`, blame, submodule listing, reflog listing) execute in-memory via `pygit2`/libgit2 (`read_ops.py`, `submodules.py`, `reflog_ops.py`) with a bounded 32 MB `libgit2` LRU cache cap (`configure_libgit2_memory_limits`); write operations (commit, branch creation/switching/renaming, push, pull, fetch, merge, interactive/standard rebase, submodule update/sync, sparse-checkout, partial clone, `commit-graph write`, bundles) invoke the system `git` CLI (`write_ops.py`, `rebase_sequencer.py`, `rebase_editor_helper.py`, `sparse_checkout.py`, `lfs_ops.py`, `bundles.py`).
   - All write executions funnel through `run_git_streaming` with pipe draining and cooperative `threading.Event` cancellation, while `security_sanitizer.py` enforces clone URL scheme/option safety (`SEC-2`), git ref validation, and UI/log secret redaction (`SEC-3`).
   - Destructive operations are guarded by automatic pre-operation safety snapshots (`snapshots.py`, conditionally enabled by `safety.pre_op_snapshot.enabled`) and lock recovery (`lock_recovery.py`).
   - **Git LFS Ops (`lfs_ops.py`)**: Automatic Git LFS detection, `.gitattributes` filter inspection, pointer file parsing without shelling out, and safe `lfs track`, `lfs untrack`, and `lfs pull` routines.
   - **Git Submodules (`submodules.py`)**: In-memory inspection of `.gitmodules` via `pygit2`, combined with safe CLI operations (`git submodule update`, `git submodule sync`, `git submodule init`, `git submodule add`).
   - **Git Bundles (`bundles.py`)**: Complete repository bundling (`git bundle create`), validation (`git bundle verify`), and restoration (`restore_backup`).
   - **Git Reflog Ops (`reflog_ops.py`)**: Structured reflog enumeration (`list_reflog`), branch recovery from reflog entries (`create_branch_from_reflog`), and safe commit reset (`reset_to_reflog_entry`).
   - **Directory Discovery (`discovery.py`)**: Performs bounded, non-blocking scans (max depth 3) for Git repositories and worktrees, pruning at `.git` boundaries, ignoring dot-directories, refusing symlinks, and tolerating permission errors.
   - **Lazy Loading (`lazy_loader.py`)**: Implements explicit lazy module loading supporting Python 3.15 PEP 810 native `lazy import` alongside backward-compatible `LazyProxyModule` to defer heavy dependencies until first access.

3. **Filesystem Watcher (`src/wrench/watcher`)**:
   - `RepoWatcher` monitors the active repository using a 3-tier monorepo fallback: Tier 1 `full_inotify` (`_WatchdogHandler` excluding `.git/`, with configurable `watcher.debounce_ms` defaulting to 300ms and atomic rename handling) -> Tier 2 `git_dir_inotify` (`_GitDirMetadataHandler` watching `<gitdir>/{HEAD,index,packed-refs,config,config.worktree}`, `info/sparse-checkout`, and `refs/` on `ENOSPC`/`EMFILE`, gated by `watcher.monorepo_adaptive_fallback.enabled`) -> Tier 3 Qt-thread `PollingFallback` (`polling` mode).
   - Supports `suspend()`/`resume(grace_ms=150)` around bulk checkouts, dynamic updates via `setting_changed`, and exposes `adaptive_fallback_activated(mode, reason)` + `status_info` (`WatcherStatusInfo`) to update `MainWindow` status pills and refresh `ChangesTab` / `CommitGraphWidget`.

4. **Multi-Forge Subsystem (`src/wrench/forge`)**:
   - Pluggable architecture based on Python entry points (`wrench.forge_adapters`) and the `ForgeAdapter` abstract base class.
   - Built-in adapters for GitHub, GitLab, Forgejo/Gitea, and Bitbucket Cloud normalize PRs, issues, CI checks, and review submissions.
   - Maps `author_avatar_url` across all 4 providers and defines the `get_avatar_url()` capability contract.
   - **Zero-Overhead Feature Gating**: Wired directly to `SettingsRegistry`. When a forge provider or forge integration as a whole is disabled (`forge.enabled = False` or `forge.{provider}.enabled = False`), network adapters short-circuit in `< 0.05 ms` without initializing HTTP clients or spawning background sync timers.
   - Assisted GitHub setup uses RFC 8628 Device Authorization Flow (`github_device_flow.py`) requesting necessary OAuth scopes (`repo`, `workflow`, `user:email`, `read:org`).

5. **Storage Layer (`src/wrench/storage`)**:
   - Local SQLite database (`wrench.db`) managed via a dedicated coarse-grained thread lock under SQLite WAL mode with Schema Version 3 (`user_version = 3`).
   - **Universal Settings Registry (`settings_registry.py`)**: $O(1)$ in-memory cached configuration management (`_effective_cache`) governing all 13 categories (83 `DEFAULT_SETTING_SPECS`, `SettingTier` `NORMAL`/`ADVANCED`). Hierarchical scoping allows overriding global settings per repository (`repo_settings_overrides`). Persists delta history in SQLite `settings_undo_log` (capped to the latest 100 entries), handles `_LEGACY_KEY_ALIASES` cleanup via `_delete_stale_legacy_app_settings`, performs one-time migration from legacy v1 settings tables, and supports JSON export/import.
   - **Legacy Settings Bridge (`settings.py`)**: Seamless backward-compatibility facade keeping `_SESSION_BLOB_KEYS` (`ui.session_state`, `ui.window_geometry`) in `app_settings` while delegating known aliased keys (`"theme"`, `"repo.auto_fetch_on_open"`) to `SettingsRegistry`.
   - Persists tracked repository registry (`repo_registry.py` with `clear_missing()` for rediscovered repos), safety snapshot metadata (`snapshots.py`), and forge account credentials / remote link associations (`forge_accounts.py`).
   - Health diagnostics and integrity verification via `health.py`.

6. **Credentials Layer (`src/wrench/credentials`)**:
   - Uses `SecretServiceBackend` to store and retrieve authentication tokens securely over D-Bus via the FreeDesktop Secret Service specification (KDE KWallet / GNOME Keyring) with zero plaintext disk exposure.
   - The standalone `git-credential-wrench` helper integrates with git CLI commands, consulting `storage/forge_accounts.py` and `credentials` to provide host- and path-specific credentials without leaking credentials between multiple accounts on the same forge host.

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
    - `SecretScanningRejectedError` (`GH007`): Spawns `SecretScanningDialog` displaying detected secrets, affected files, and direct unblock link.
    - `ProtectedBranchRejectedError` (`GH006`): Spawns `ProtectedBranchDialog` providing guided branch creation, automatic checkout, and re-push.
    - `FileTooLargeRejectedError` (`GH001`): Spawns `FileTooLargeDialog` showing quota limits and Git LFS / index-cache removal guidance.
    - `SignedCommitsRequiredError` (`GH008`): Guides users through GPG/SSH commit signing (`git commit -S`).
    - `RepoPermissionDeniedError` (`403`): Alerts user to repository write permission barriers.
    - `PushRejectedError`: Offers actionable choices between "Fetch & Retry", "Force Push (with lease)", and "Cancel".
    - `MergeRequiredError`: Offers actionable choices between "Merge" and "Rebase" using Phase 2 tools.
    - `RemoteNotFoundError`: Prompts and opens the Remotes configuration dialog.
  - **Asynchronous Clone & Sparse-Checkout**: Routes repository cloning (including partial filter `--filter=blob:none`/`tree:0` and `--sparse`) through `CloneDialog` + `run_in_background` with cancellable `BusyOperationDialog` and atomic filesystem placement; exposes `Repository -> Sparse-Checkout Directories…` (`_run_sparse_checkout_dialog`) wrapped with `watcher.suspend()`/`resume(grace_ms=150)` and bottom-right status pills (`sparse_status_btn`, `watcher_mode_label`).
  - **Live Registry Propagation, Repo-Switch Hygiene & Background Maintenance**: `_on_registry_setting_changed` live-applies changes to `ui.theme_mode`, `ui.font_size_pt` (`_apply_font_size_pt`), `ui.avatars_gravatar`, `ui.humor_lines`, `ui.activity_dock.max_lines`, `remote.auto_fetch.enabled`, `monorepo.sparse_checkout_ui.enabled`, `rebase.interactive_ui.enabled`, and `maintenance.auto_commit_graph.enabled` (using `_CommitGraphDispatcher`, `_CommitGraphWorker`, and `_maybe_write_commit_graph` with generation cancellation). `_propagate_theme_refresh()` refreshes status bar pills (`_apply_status_bar_theme()`) and open `QDialog`s (`_active_settings_dialog`, `_sparse_dialog`, `_interactive_rebase_dialog`, and child dialogs). `QSignalBlocker` prevents duplicate repo-open events on programmatic combo updates, `request_restart()` restarts Wrench cleanly for restart-flagged settings (`ui.theme_mode`), and `_reclaim_heap_after_switch()` + coalesced 150ms single-shot `_heap_trim_timer` (`_on_delayed_heap_trim`) run `gc.collect()` and `malloc_trim(0)` after `DeferredDelete` cycles with closing/validity guards.
  - **Interactive Rebase Coordinator (`_on_history_interactive_rebase` / `_run_interactive_rebase_dialog`)**: Launches non-modal `InteractiveRebaseDialog` from `HistoryTab.interactive_rebase_requested`, suspends `RepoWatcher` during `rebase_started` and resumes on `rebase_completed`/`rebase_failed`, routes paused/conflicted outcomes back to `ChangesTab`, and enforces single-instance activation.
  - Hosts the central `TabContainer`.
  - **GUI Session Persistence Engine**: Runs a continuous 1000ms debounced auto-save timer (`_auto_save_timer`) coalescing window geometry, splitter ratios, tab list/order/pinning, active repo, and per-repo selections/drafts into `app_settings` key `ui.session_state`.
  - Synchronous flush on `closeEvent(event)` ensures state is never lost on shutdown or unexpected termination.
  - Startup restoration guard `_is_restoring` prevents initialization noise from wiping saved drafts and checkbox selections.
  - Enforces quit guards when unsaved commit message drafts exist or background workers are busy.
  - Owns the active `RepoHandle` and `RepoWatcher`.
- **`PRListTab` & `IssueListTab` (`ui/tabs/pr_list_tab.py`, `ui/tabs/issue_list_tab.py`)**:
  - Forge pull request and issue browser workspaces keyed by `(tab_type, repo_path)`.
  - Author column displays 24px `AvatarWidget` circular avatar or deterministic colored initials badge fallback.
  - Interactive search bar and state filters (`Open`, `Merged`, `Closed`, `All`) with 300ms debouncing.
  - SWR (Stale-While-Revalidate) cache with a 60-second TTL for instantaneous view loads.
  - Remote selector dropdown binding active repository remotes to configured forge accounts.
  - Generation-counted request invalidation preventing stale asynchronous responses from overwriting newer user selections.
  - "New Pull Request" creation dialog (`CreatePRDialog`) with branch selectors, title, and description editors.
  - Double-click item selection spawning dynamic entity detail tabs.
- **`PRDetailTab` & `IssueDetailTab` (`ui/tabs/pr_detail_tab.py`, `ui/tabs/issue_detail_tab.py`)**:
  - Full-detail entity workspaces keyed by `(tab_type, repo_path, entity_id)`.
  - Header view displays 40px `AvatarWidget` circular author avatar beside author name and title.
  - Direct non-paginated entity retrieval via `adapter.get_pull_request()` and `adapter.get_issue()`.
  - Inline CI/CD build status card (`CIIconWidget`) with external build log link button.
  - In-app review submission dialog (`SubmitReviewDialog`) supporting Approve, Request Changes, and Comment actions tailored to provider capability constraints.
  - Local branch checkout and tracking branch setup.
  - Stale repository warning banner informing users when the active main window repository has diverged from the open tab's repository.
- **`AccountsDialog`, `AddAccountDialog`, & `EditAccountDialog` (`ui/dialogs/accounts_dialog.py`)**:
  - Complete forge accounts management interface.
  - **Assisted Setup (Device Flow RFC 8628)**: Browser authorization for GitHub and GitHub Enterprise Server requesting `repo workflow user:email read:org` permissions, featuring live countdown timers, polling interval backoff, and clipboard copy helpers.
  - **Scope Picker UI**: Preset radio buttons ("Full Access" vs. "Public Repositories Only") and collapsible "Advanced Scopes" toggle (`QToolButton` + `advanced_scopes_widget`) exposing checkboxes for `workflow`, `user:email`, and `read:org`.
  - **In-Place Re-authorization**: 1-click re-authorization for existing GitHub accounts updating credentials in Secret Service while preserving all `repo_forge_links`.
  - **Manual Token Setup**: Guided PAT setup for GitHub, GitLab, Forgejo/Gitea, and Bitbucket with provider-specific permission documentation.
  - **Enterprise Security**: Custom CA bundle (PEM) file picker and explicit skip TLS verification option with security warning.
- **Push Recovery Dialogs (`ui/dialogs/push_recovery_dialogs.py`)**:
  - **`SecretScanningDialog`**: Actionable recovery dialog for GitHub Secret Scanning (`GH007`) displaying detected secret type, file location, and direct 1-click external unblock URL button.
  - **`ProtectedBranchDialog`**: Guided recovery dialog for GitHub Protected Branch (`GH006`) push rejections, offering automated new branch creation (`patch-1` / `patch-{branch}`), branch checkout, and re-push.
  - **`FileTooLargeDialog`**: Recovery dialog for GitHub File Size Quota (`GH001`) displaying offending filename, file size, quota limit, and remediation guidance for `git rm --cached` and Git LFS.
- **`LinkRepoDialog` (`ui/dialogs/link_dialog.py`)**:
  - Repository-to-forge account association dialog.
  - Auto-matches remotes to configured accounts by host URL.
  - Asynchronously aligns local git author identity (`user.name` and verified `user.email`) with the authenticated forge user via `adapter.get_primary_email()`.
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
  - Resets `_selected_file = None` and `_current_status = None` at the start of `set_repo()` and validates persisted `selected_file` keys against populated `files_list` rows inside `restore_repo_state()`, preventing stale cross-repo `get_diff` subprocess fallbacks on repository switches.
  - Flush borderless repository selector `QComboBox` with mode-isolated theme styling (`_update_repo_combo_theme()`): retains original stylesheet with `color: palette(window-text);` in dark mode, and applies explicit `#4c4f69` (charcoal slate) text on `#ffffff` card base in light mode to prevent invisible white text caused by static palette stylesheet binding.
  - Embedded `BranchSwitcherWidget` with theme-adaptive colors.
  - Visible 1px divider `QSplitter::handle` with interactive hover highlight.
  - Theme-adaptive merge conflict banner when merge conflicts are in progress.
  - Unified changed files list (staged + unstaged + untracked) with status badges (`M`, `A`, `D`, `R`, `?`, `⚠ C`) and path tooltips.
  - Tri-state select-all checkbox cycling `Unchecked ➔ All Checked ➔ All Unchecked`.
  - Right-click file context menu (`Stage`, `Unstage`, `Discard`, `Copy Relative/Absolute Path`).
  - Commit section with forge account avatar button, 72-character soft limit summary warning (using theme-aware warning ambers), description editor, amend toggle (pre-filled from last commit), and dynamic commit button (`commit_btn`) with mode-isolated theme styling (`_update_commit_btn_theme()`): preserves native unstyled Qt button rendering (`setStyleSheet("")`) in dark mode, and applies vibrant Catppuccin Sapphire (`#1e66f5`) with `#ffffff` text (disabled: `#e6e9ef` with `#7c7f93` text) in light mode to eliminate washed-out grey buttons.
  - Per-repo selections and draft text snapshotting (`get_current_repo_state()` / `restore_repo_state()`) during repository switches.
  - Right column embedded `DiffView` with clean state, programming quotes (`refresh_humor_setting()` synced with `ui.humor_lines`), and `PartialStagingDialog` (`MM`/`AM` conflict resolver on commit returning `PartialStagingChoice`).
  - **Theme Lifecycle (`refresh_theme`)**: Propagates theme refreshes across `_update_repo_combo_theme()`, `_update_commit_btn_theme()`, `branch_switcher`, `files_list` item badges, `diff_view`, conflict banners, and secondary labels (`files_count_label`, `clean_title`, `clean_quote`, `clean_author` bound to `palette(placeholder-text)`), protected by recursion guards.
- **`BranchSwitcherWidget` (`ui/widgets/branch_switcher.py`)**: Branch indicator and switcher.
  - Displays active branch (`🌿 main ▾`), detached HEAD (`🔗 HEAD detached at {sha}`), or unborn branch (`🌿 main (initial)`).
  - Searchable branch picker popup listing local and remote tracking branches.
  - Uncommitted changes prompt: `Stash & Switch`, `Switch Anyway`, or `Cancel`.
  - Right-click context actions: `Create New Branch…`, `Rename Branch…`, `Delete Branch…`.
  - **Theme Integration**: Employs `ACCENT_COLORS` for detached HEAD indicators (`#df8e1d` in Light, `#f9e2af` in Dark), `palette(placeholder-text)` for unborn branch states, and listens to `PaletteChange` with recursion protection.
- **`HistoryTab` (`ui/tabs/history_tab.py`)**: Git log and history visualization workspace.
  - Exposes `interactive_rebase_requested` forwarded from `CommitGraphWidget` and uses `QSignalBlocker` when refreshing author filters.
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
  - **100k+ Cursor Pagination & Virtualized Painting (`VP-16`)**: Fetches pages off the UI thread via `_GraphWorkerDispatcher`, `_GraphPageWorker`, and `_GraphSearchWorker` on `QThreadPool` using `engine.get_log_page` sized by `performance.graph_page_size` when vertical scroll crosses 80% (`CommitTableModel.append_rows`), clips `paintEvent` strictly to visible viewport rows (`_last_painted_row_range`), and caches DPR-scaled ref pills and 18px avatars in `QPixmapCache` (invalidated via `invalidate_paint_caches()`).
  - Interactive column resizing across all header sections with boundary clipping and auto-save triggering on resize.
  - Auto-scrolling to selected commit nodes with glowing halo accent rings (`NODE_RADIUS + 3.0`).
  - Commit context menu exposes `"Interactive Rebase from Here..."` (`interactive_rebase_requested` Signal) gated by `rebase.interactive_ui.enabled`.
- **`CommitDetailPanel` (`ui/commit_graph/detail_panel.py`)**: Detailed commit inspection panel.
  - Cleans up embedded table `cellWidget` items cleanly via `deleteLater()` in `_clear_files_table()` prior to row reset.
  - Displays selected commit metadata: full commit message, author name, committer, SHA-1 with 1-click clipboard copy, parent SHAs, commit timestamp, and stat badges.
  - Embeds a 24px `AvatarWidget` for the commit author, resolving avatars via Gravatar hashing (MD5/SHA-256 of author email) when the `ui.avatars_gravatar` setting is enabled, or gracefully falling back to deterministic initials badges when disabled.
- **`Topological Layout Calculator` (`ui/commit_graph/layout.py`)**:
  - Computes `(col, row)` coordinates and directional `Connector` segments (`PASS_THROUGH`, `FORK_DOWN`, `MERGE_UP`, `JOIN_TOP`).
  - 10-color deterministic color persistence and slot recycling algorithm preventing lane explosion.
- **`MergeDialog` (`ui/dialogs/merge_dialog.py`)**: 3-Way visual merge conflict resolution tool.
  - Side-by-side Ours, Base, and Theirs diff viewers with block-level conflict acceptance and index staging.
- **`InteractiveRebaseDialog` (`ui/dialogs/interactive_rebase_dialog.py`, `VP-2`, `FR-3.5`)**: Visual interactive rebase planner and executor.
  - Loads commits in `base_oid..HEAD` asynchronously in oldest-first `git rebase -i` order via `_LoadCommitsWorker` and queued `_RebaseDialogDispatcher` signals (`OPT-6` generation tokens), enforcing a 1,000-commit safety cap.
  - Renders `_RebaseTodoTableWidget` (`InternalMove` drag-and-drop row reordering emitting `row_move_requested`), per-row action selectors (`pick`, `reword`, `edit`, `squash`, `fixup`, `drop`) styled with `REBASE_ACTION_COLORS`, inline message editor for `reword`/`squash`, and validation blocking top-row `squash`/`fixup`.
  - Hosts `--autostash` / `--autosquash` toggles, Preferences gear button (`⚙`), live secret-redacted `CliCommandPreviewBar` footer, and async execution via `_RunInteractiveRebaseWorker` (`rebase_started`, `rebase_completed`, `rebase_failed` signals).
- **`DiscoverReposDialog` (`ui/dialogs/discover_repos_dialog.py`)**:
  - Multi-repository discovery review and import dialog (FR-1.12).
  - Displays discovered local Git repositories and worktrees in a checkable list with Select All / Deselect All controls, path canonicalization, and Catppuccin theme token styling.
  - On accept, registers newly found repositories in SQLite `repos` table and invokes `repo_registry.clear_missing()` to re-activate previously missing repository entries.
- **`SettingsDialog` (`ui/dialogs/settings_dialog.py`)**:
  - Centralized application preferences dialog (minimum 920x640, default 960x680) driven by `storage.settings_registry.SettingsRegistry`.
  - **Two-Row Header & Progressive Disclosure (`SettingTier`)**: Cleanly splits discovery (`top_row_1`: live search `QLineEdit` + `Normal`/`Advanced` view-mode `QComboBox` backed by `ui.settings_view_mode`) from power controls (`top_row_2`: `scope_combo`, `Modified` filter, Undo `Ctrl+Z`, Redo `Ctrl+Y`, and `↺ Reset`). `Normal` mode displays only the 17 essential user settings (`SettingTier.NORMAL`) and hides advanced categories/chrome; `Advanced` mode reveals all 83 specs, repo-override scoping, `Modified` filtering, category reset, and `⚡ Apply Minimalist Preset…`.
  - **13 Navigation Categories**: `General & UI`, `Staging & Commits`, `Commit Graph`, `Diff & Merge`, `Branches & Stacks`, `Worktrees & Submodules`, `Remotes & LFS`, `Forges & CI`, `Hooks & Signing`, `Blame & Search`, `Watcher & Performance`, `Safety & Backups`, and `Custom Actions & Shortcuts`.
  - **Lazy Page Loading (`OPT-1`)**: Pages are constructed on-demand upon first category selection or active search, reducing initial dialog opening latency to $< 15\text{ ms}$.
  - **Instant Search & Tier Filtering (`OPT-2`)**: `SettingRowWidget.matches_query()` + `CategorySettingsPage.filter_rows()` toggle row and navigation item visibility in $< 5\text{ ms}$ across key, label, description, and category without recreating widgets.
  - **Hierarchical Scope Switcher**: Toggles between `🌐 Global Defaults` and `📁 Repo Override: <name>` in `Advanced` mode.
  - **Zero-Overhead Debounced Auto-Save & Close Flush (`OPT-2`)**: Boolean/choice toggles save immediately while `QSpinBox`/`QLineEdit` inputs use a 150ms single-shot debounce timer plus immediate `editingFinished` and `flush_pending()` execution inside `done()`/`closeEvent()`, preventing lost edits on quick close.
  - **Bottom-Right `Apply Changes` / `Apply Changes & Restart` Staging Bar (`btn_apply`)**: Supports explicit staged preference mutations (`stage_change`, `apply_pending_changes`, `pending_requires_restart`), switching the button label to `Apply Changes & Restart` when a `SettingSpec.requires_restart` preference (such as `ui.theme_mode`) is modified and invoking `MainWindow.request_restart()` on apply.
  - **Lifecycle Sync (`showEvent` / `reload_key` / `select_category`)**: Reconnects `registry.setting_changed` cleanly on re-open, refreshes row values on show (`showEvent`), skips in-flight debounced rows in `reload_key`, and auto-switches from `Normal` to `Advanced` when `select_category(..., highlight_key)` targets an advanced preference.
  - **Preset Engine**: 1-click `[⚡ Apply Minimalist Preset…]` button disables background fetching, forge polling, telemetry, and external avatar lookups.
  - **100-Entry SQLite Delta Undo/Redo (`OPT-3`)**: `[↶]` / `Ctrl+Z` and `[↷]` / `Ctrl+Y` buttons driven by `SettingsRegistry.undo_last_change()` and `redo_last_change()` backed by SQLite `settings_undo_log` (pruned to 100 entries).
  - **Dual-Mode Backward Compatibility**: When instantiated with `v1_compat=True` (or legacy suites expecting `nav_list.count() == 6`), renders the classic 6-page interface while defaulting to the 13-category registry in production.
- **`CloneDialog` (`ui/dialogs/clone_dialog.py`)**:
  - Partial & sparse clone dialog supporting `none`, `blob:none` (blobless), and `tree:0` (treeless) filters initialized from `clone.default_filter_mode`, optional `--sparse` checkout toggle, destination path picker using single-line middle-eliding `_SingleLinePathLabel`, forge account selector, and a live secret-redacted `CliCommandPreviewBar` footer (`SEC-2`/`SEC-3`).
- **`SparseCheckoutDialog` (`ui/dialogs/sparse_checkout_dialog.py`)**:
  - Cone-mode sparse-checkout directory tree manager (`Repository -> Sparse-Checkout Directories...`) with lazy `QThreadPool` subdirectory expansion (`_TreeExpandWorker` + `_SparseDialogDispatcher`), generation-token race protection (`OPT-6`), async apply/disable via `_ApplySparseWorker`, and `CliCommandPreviewBar` preview.
- **`PartialStagingDialog` (`ui/dialogs/partial_staging_dialog.py`)**:
  - Modal commit conflict-of-intent resolver displayed when checked files have both staged index edits and unstaged working-tree edits (`MM`/`AM`), offering `Stage All & Commit`, `Commit Staged Hunks Only`, `Cancel`, and per-repo remember-choice persistence.
- **`CliCommandPreviewBar` (`ui/widgets/cli_preview_bar.py`)**:
  - Reusable monospace footer widget showing the live equivalent Git CLI invocation after passing through `engine.redact_secrets()` (`SEC-3`), with one-click clipboard copy and live show/hide binding to `ui.show_cli_preview_in_dialogs`.
- **`SubmoduleDialog` (`ui/dialogs/submodule_dialog.py`)**:
  - Git submodules management and inspection dialog.
  - Lists all configured submodules parsed from `.gitmodules` via `core.submodules.list_submodules` with columns: `Name`, `Path`, `URL`, `Commit SHA`, and `Branch`.
  - Non-blocking asynchronous operations wired through `run_in_background`: `Add Submodule` (modal wizard prompting URL, path, and optional branch), `Update Submodules` (recursive update and init), `Sync Submodules` (synchronizes remote URLs from `.gitmodules` to `.git/config`), and `Initialize Submodule`.
  - Strict compliance with Catppuccin Velvet Pastel theme tokens and zero hardcoded hex colors.
- **`AvatarWidget` & `AvatarLoader` (`ui/widgets/avatar.py`)**:
  - **`AvatarLoader` Singleton**: Application-wide thread-safe manager for asynchronous avatar downloads and caching.
    - **Dual-Tier Cache**: Bounded in-memory LRU cache (`maxsize=128` `QPixmap` entries) paired with `QPixmapCache.setCacheLimit(16384)` (16 MB), plus on-disk SHA-256 hashed cache files stored in `$XDG_CACHE_HOME/wrench/avatars` (`paths.cache_dir() / "avatars"`) with a 7-day TTL.
    - **In-Flight Request Coalescing**: Collapses duplicate concurrent requests for identical URLs into a single network operation.
    - **Non-Blocking Architecture**: Disk reads and network downloads execute on background worker threads using a shared pooled `httpx.Client` (no cookie storage, bounded timeout). Pixmap decoding and widget repainting are marshalled safely back to the Qt main thread via the `avatar_loaded` Qt signal.
    - **Silent Failure Fallback**: Network errors, HTTP 404s, offline airplane mode, or corrupt cache files fail silently without popups, cleanly falling back to initials.
  - **`AvatarWidget`**: Circular, anti-aliased avatar widget supporting standard size buckets (24px, 40px, 64px).
    - Renders fallback colored badges containing two-letter initials derived from username/author.
    - Initial badge background colors are selected deterministically using hash-based lookup against `AVATAR_BG_COLORS` semantic tokens in `theme.py`, guaranteeing 100% WCAG 2.1 AAA/AA contrast compliance ($\ge 4.5:1$ against white text).
    - Automatically swaps to loaded pixmaps smoothly upon background completion.
- **`ActivityLogBar` & `ActivityLogModel` (`ui/widgets/activity_log.py`)**:
  - Live activity dock mounted immediately above the status bar displaying latest operation status with level indicators (`info`, `ok`, `warn`, `error`).
  - Thread-safe in-memory ring buffer using `collections.deque(maxlen=200)` with queued signal dispatching.
  - Expandable ~8-line monospace history scrollback pane toggled via chevron click or `Ctrl+`` keyboard shortcut without stealing focus from active editors.
  - Automatic instrumentation via `workers.py`: `run_in_background` auto-posts start, finish (with elapsed time), and failure events when `op_name` is provided.
- **`AboutDialog` (`ui/dialogs/about_dialog.py`)**:
  - Native About dialog displaying package version dynamically resolved from `importlib.metadata.version("wrench")`.
  - Rotating wisdom lines drawn from `ABOUT_WISDOM` in `ui/quotes.py`.
  - External links to GitHub repository and issue tracker via `QDesktopServices`.
  - Bundled AGPL-3.0 license and third-party notices pane (Qt/PySide6, pygit2/libgit2, httpx, watchdog, secretstorage, platformdirs) with About Qt integration.
- **`Quotes & Personality Banks` (`ui/quotes.py`)**:
  - Centralized, translatable flavor text module providing `CLEAN_STATE_QUOTES`, `WAITING_LINES`, `SUCCESS_LINES`, `EMPTY_REPO_LINES`, `EMPTY_PR_LINES`, `EMPTY_ISSUES_LINES`, `IDLE_LINES`, `MILESTONE_LINES`, and `ABOUT_WISDOM`.
  - Gated by the `ui.humor_lines` configuration setting (persisted in `app_settings` with View menu toggle).
- **`LoadingOverlay` (`ui/widgets/loading_overlay.py`)**:
  - Semi-transparent modal overlay with animated spinner and custom status text, providing responsive feedback during heavy repository or forge operations without locking the GUI event loop.
- **`RecoveryDialog` (`ui/dialogs/recovery_dialog.py`)**:
  - Actionable diagnostics and recovery workflows for stale locks, interrupted rebases, detached HEADs, and reflogs.
- **`DiffView` (`ui/diff_view/diff_widget.py`)**: Syntax-highlighted diff viewer.
  - `set_repo(repo)` unconditionally clears `_current_path = None`, `_diff = None`, `_read_only = False`, `_force_full_diff = False`, and resets action/truncation controls before displaying the next repository's selection.
  - Renders diff lines with line-number metadata and theme-adaptive Catppuccin Velvet Pastel contrast (using compact CSS rendering above 5,000 lines).
  - Enforces a default truncation cap (`DEFAULT_MAX_DIFF_LINES = 5000` and `performance.max_diff_file_size_kb`) with a non-modal warning `truncation_banner` and 1-click `[Load Full Diff]` (`load_full_diff_btn`) override.
  - Automatically re-renders loaded diffs on `PaletteChange`, `ApplicationPaletteChange`, or `ThemeChange` without requiring file re-selection.
  - Provides hunk dropdown controls and whole-file / hunk staging action buttons.
  - Binary file detection and exception safety.
- **`Theme Engine` (`ui/theme.py`)**: Centralized styling and color management.
  - Implements the **Catppuccin Velvet Pastel** design system:
    - **Latte Pastel (Light Mode)**: `#eff1f5` warm mist canvas, `#ffffff` card bases, `#4c4f69` soft charcoal slate text, `#1e66f5` sapphire accents, `#5c5f77` high-contrast muted slate subtext (`SECONDARY_TEXT`).
    - **Mocha Velvet Pastel (Dark Mode)**: `#181825` deep midnight slate canvas, `#11111b` deep crust card bases, `#cdd6f4` frosted white text, `#89b4fa` pastel sky accents, `#a6adc8` lavender-gray subtext (`SECONDARY_TEXT`).
  - **Luminance-Based Detection (`is_dark_theme`)**: Calculates average luminance of `QPalette.Window` and `QPalette.Base` to avoid desktop environment color scheme mismatches on KDE Plasma and GNOME.
  - **Recursive Descendant Palette Propagation (`apply_theme` & `_repolish_widget`)**: Sets the palette on `QApplication`, traverses all `topLevelWidgets()` and their child widgets recursively (overcoming Qt `QStyleSheetStyle` isolation on `QSplitter`/`QGroupBox`), and unpolishes/re-polishes dynamic dialogs and labels immediately.
  - **Design Tokens & Normalization**: Centralized maps and helpers including `normalize_theme_mode`, `DIFF_STYLES`, `BADGE_STYLES`, `CONFLICT_BANNER_STYLES`, `SECONDARY_TEXT`, `ACCENT_COLORS`, `COMMIT_STAT_COLORS`, `STATUS_PILL_STYLES`/`get_status_pill_style`, `TREE_WIDGET_STYLES`/`get_tree_widget_qss`, `SETTINGS_BADGE_STYLES`/`get_settings_badge_qss`, `TOAST_TEXT_COLOR`, `CLI_PREVIEW_STYLES`, and `READONLY_FIELD_STYLES`/`get_readonly_field_qss`.
- **`workers.py`**: Concurrency execution engine using Python daemon `WorkerThread` workers and a thread-safe `_Dispatcher(QObject)` singleton on the Qt main thread. Delivers non-blocking background operations, progress streaming (`progress_cb(pct, stage)`), cooperative cancellation (`threading.Event`), and error recovery without deadlocks between Python GIL and Qt's `signalSlotLock`.


### 3.2 Core Git Engine (`src/wrench/core/`)
- **`engine.py`**: Public façade exposing unified, typed functions. Converts internal errors into typed `WrenchGitError` derivatives.
  - Remote & Clone operations: `push(repo, remote, branch, force=False)` (enforces `--force-with-lease`), `pull(repo, remote, branch)` (enforces `--ff-only`), `fetch(repo, remote)` (with `--prune` and timestamp storage), and `clone_repo` / `clone_repository` (atomic staging via tempdir with automated rollback, `--filter=blob:none`/`tree:0`, `--sparse`).
  - Remotes façade: `list_remotes(repo)`, `add_remote(repo, name, url)`, `remove_remote(repo, name)`, `set_remote_url(repo, name, url)`, and `_probe_reachability(repo_path, remote_name)`.
  - Monorepo, Graph & Maintenance façade: `get_log_page`, `get_repo_refs_signature`, `is_unborn_repo`, `refresh_repo_handle`, `is_sparse_checkout_enabled`, `get_sparse_checkout_state`, `init_sparse_checkout`, `list_sparse_directories`, `set_sparse_directories`, `disable_sparse_checkout`, `list_head_top_directories`, `list_tree_subdirectories`, `write_commit_graph`, `maybe_write_commit_graph`, `validate_clone_url`, `validate_git_ref`, `redact_secrets`, and `resolve_git_dir`.
  - Feature gating facade: `is_feature_enabled(feature_key, repo_path)` and `get_settings(repo_path)` providing zero-overhead short-circuits (`OPT-1`).
  - Interactive Rebase façade (`VP-2`): `build_interactive_rebase_cli_args`, `get_interactive_rebase_target_label`, `list_commits_for_interactive_rebase`, `list_commits_for_interactive_rebase_checked`, and `interactive_rebase` (creating pre-operation safety snapshots and honoring `rebase.autostash`/`rebase.autosquash`).
  - LFS façade: `is_lfs_installed()`, `repo_uses_lfs(repo)`, `is_lfs_pointer_file(repo, path)`, `lfs_track(repo, pattern)`, `lfs_untrack(repo, pattern)`, `lfs_pull(repo)`, and `lfs_status(repo)`.
  - Submodules façade: `list_submodules(repo)`, `init_submodule(repo, name)`, `update_submodules(repo, recursive, init)`, `sync_submodules(repo)`, and `add_submodule(repo, url, path, branch)`.
  - Bundles façade: `create_bundle(repo, output_path, rev_range)`, `verify_bundle(repo, bundle_path)`, and `unbundle(repo, bundle_path)`.
  - Reflog façade: `list_reflog(repo, ref, limit)`, `reset_to_reflog_entry(repo, sha, mode)`, and `create_branch_from_reflog(repo, branch_name, sha)`.
- **`models.py`**: Typed dataclass models for Git primitives and core extensions:
  - `LfsFileStatus`: Represents LFS pointer status, OID, size in bytes, and local cache availability.
  - `SubmoduleInfo`: Represents submodule metadata (name, path, url, commit_sha, branch, initialized).
  - `ReflogEntry`: Represents parsed reflog entries (index, commit_sha, old_sha, committer, timestamp, message).
  - `BundleVerificationResult`: Holds bundle validity flag, header metadata, prerequisite commit SHAs, and contained reference heads.
  - `CloneResult`: Outcome metadata for atomic clone operations (success, repo_path, duration_seconds, error_message).
  - `LogPage`, `CommitGraphStats`, `SparseCheckoutState`, `TreeDirectoryEntry`, and `WatcherStatusInfo`: Monorepo pagination, commit-graph maintenance, cone-mode sparse-checkout, and adaptive watcher telemetry models (`VP-16`).
  - `RebaseTodoEntry`: Immutable interactive rebase plan row (`action`, `oid`, `short_oid`, `summary`, `author`, `new_message`, `VP-2`).
- **`rebase_sequencer.py` (`VP-2`, `FR-3.5`, `FR-10.1`)**: Core engine for graphical interactive rebase:
  - `list_commits_for_interactive_rebase_checked` / `list_commits_for_interactive_rebase`: Enumerates `base_oid..HEAD` in oldest-first `git rebase -i` order via `pygit2` (`GIT_SORT_TOPOLOGICAL | GIT_SORT_REVERSE`, capped at `MAX_INTERACTIVE_REBASE_COMMITS = 1000`) without subprocesses.
  - `run_interactive_rebase`: Validates `RebaseTodoEntry` sequences (blocking leading `squash`/`fixup` and invalid OIDs), writes the plan JSON inside a `0o700` temporary directory with `0o600` file permissions (`SEC-4`), and executes `git rebase -i` (`shell=False`, `--` separator `SEC-1`) with `GIT_SEQUENCE_EDITOR` and `GIT_EDITOR` bound to `python -m wrench.core.rebase_editor_helper <plan_json>`.
- **`rebase_editor_helper.py` (`VP-2`)**: Standalone CLI editor entrypoint invoked by Git during interactive rebase (`apply_sequence_plan` for `git-rebase-todo`; `apply_commit_message` for `COMMIT_EDITMSG` matching `rebase-merge/done` OIDs or ordered fallback message slots with `0o600` atomic writes).
- **`lfs_ops.py`**: Git Large File Storage (LFS) operations and detection:
  - Detection: `is_lfs_installed()` decorated with `@functools.lru_cache(maxsize=1)` checks `shutil.which("git-lfs")` before creating directories or invoking `git lfs version`; parses `.gitattributes` for `filter=lfs` bindings.
  - In-Memory Pointer Inspection: Inspects blob headers via `pygit2.Blob` in-process (`version https://git-lfs...`, `oid sha256:...`, `size ...`), eliminating subprocess overhead.
  - Operations: Enforces safety checks via `require_lfs()` before executing `git lfs track`, `git lfs untrack`, or `git lfs pull` with argument sanitization and `--` separators (`SEC-1`).
- **`submodules.py`**: Git submodule management:
  - In-memory inspection: Parses `.gitmodules` directly via `pygit2` into `SubmoduleInfo` models without spawning child processes.
  - Submodule operations: Synchronous and streaming execution of `git submodule update --init --recursive`, `git submodule sync --recursive`, `git submodule init`, and `git submodule add` with path and ref protections.
- **`bundles.py`**: Git bundle archiving and validation:
  - `create_bundle(repo, output_path, rev_range="--all")`: Packages repository history into portable, self-contained single-file archives.
  - `verify_bundle(repo, bundle_path)`: Parses `git bundle verify` output into structured `BundleVerificationResult` containing required prerequisites and head references.
  - `unbundle(repo, bundle_path)`: Re-imports bundle commit references into the active repository index.
- **`reflog_ops.py`**: Git reference log inspection and recovery:
  - Traversal: Iterates reference log entries via `pygit2.Repository.references[ref].log()` or git CLI fallback.
  - Restoration: Resets working branch to historical states (`git reset --hard <sha>`) or creates named recovery branches directly from reflog points without modifying active checkouts.
- **`read_ops.py`**: `pygit2`-backed status, diffs, paginated log traversal (`get_log_page` returning `LogPage` backed by a thread-safe `_ACTIVE_WALKER_CACHE` LRU of size 8 validated via `_repo_refs_digest`), branch enumeration, line-by-line blame, and `configure_libgit2_memory_limits()` (32 MB global `libgit2` LRU cache cap + 48 MB `mwindow_mapped_limit` initialized once by `GitEngine`).
- **`write_ops.py`**: Subprocess helpers managing Git CLI execution:
  - `ensure_credential_config`: Checks `repo.config` via `pygit2` under a per-repo lock before spawning `git config --local` subprocesses for `credential.helper` / `credential.useHttpPath`.
  - `clone_repository` / `clone_repo`: Atomic clone with partial-clone `filter_spec` (`blob:none`, `tree:0`) and `sparse` flags, validated via `security_sanitizer.validate_clone_url`.
  - `write_commit_graph`: Lock- and unborn-repo-safe `git commit-graph write --reachable --changed-paths --no-progress` returning `CommitGraphStats`.
  - `run_git`: Standard synchronous runner with timeout and sanitized environment (`GIT_TERMINAL_PROMPT=0`).
  - `run_git_streaming`: Deadlock-free streaming execution using concurrent dual-pipe reader threads for `stdout` and `stderr`. Parses carriage-return `\r` and `\n` progress lines, routes live percentage and stage callbacks, and terminates gracefully on `cancel_event` (`SIGTERM` ➔ 3s grace ➔ `SIGKILL`). Deterministically classifies non-zero exits into typed exceptions:
    - `WorkflowScopeRequiredError`: Detects when pushes affecting `.github/workflows/` are rejected due to missing OAuth `workflow` scope.
    - `SecretScanningRejectedError` (`GH007`): Detects secrets caught by GitHub Secret Scanning, parsing secret type, file location, and unblock URLs.
    - `ProtectedBranchRejectedError` (`GH006`): Detects branch protection rejections, parsing branch name and protection rules reason.
    - `FileTooLargeRejectedError` (`GH001`): Detects 100MB file size quota rejections, parsing filename, file size MB, and quota limit MB.
    - `SignedCommitsRequiredError` (`GH008`): Detects remote requirements for GPG/SSH commit signatures.
    - `RepoPermissionDeniedError` (`403`): Detects remote write permission barriers.
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
- **`identity.py`**: Validates user name and email configurations (`check_identity()`), provides repo-local configuration setters (`set_identity()`), and supports automatic background synchronization from authenticated forge accounts on link creation.
- **`security_sanitizer.py`**: Enforces clone URL transport/option validation (`validate_clone_url`), git ref safety (`validate_git_ref`), and token/Bearer/credential scrubbing (`redact_secrets`) for UI previews and logs (`SEC-2`, `SEC-3`).
- **`sparse_checkout.py`**: Implements validated Cone-mode sparse-checkout management (`is_sparse_checkout_enabled`, `get_sparse_checkout_state`, `init_sparse_checkout`, `list_sparse_directories`, `set_sparse_directories` via `--stdin`, `disable_sparse_checkout`) and non-checkout HEAD tree traversal (`list_tree_subdirectories` via `pygit2` with `git ls-tree` partial-clone fallback, `list_head_top_directories`).
- **`paths.py`**: Standardized XDG data, config, state, cache directory (`cache_dir()`), and Git metadata directory resolution (`resolve_git_dir` supporting standard repos, linked `.git` pointer files, and bare repos).
- **`remote_urls.py`**: Git remote URL parsing and normalization (supporting SCP-like `git@host:...`, SSH `ssh://...`, HTTPS, and git protocols), extracting canonical forge hostnames and owner/repository path slugs.
- **`backup.py`**: Safety backup and recovery utilities for repository configurations and runtime states.
- **`discovery.py`**: Multi-repository directory discovery (`discover_repos`). Performs a bounded, non-blocking scan up to depth 3, immediately pruning at repository roots (handling both standard directories and `.git`-file linked worktrees), skipping dot-directories, refusing to follow symlinks to prevent cycles, and catching permission errors without aborting. Re-exported via `core.engine.discover_repos`.
- **`lazy_loader.py`**: Explicit lazy module loading system supporting Python 3.15 PEP 810 native `lazy import` syntax alongside backward-compatible `LazyProxyModule` and module-level `__lazy_modules__` declarations to defer heavy dependencies until first access.
- **`lazy_demo.py`**: Demonstrates native Python 3.15 PEP 810 explicit lazy imports syntax and deferred symbol resolution.
- **`crash_handler.py` & `core/recovery/`**: Local-first crash resilience & error recovery framework:
  - `crash_handler.py`: Global unhandled exception hook capturing stack traces and auto-saving in-flight session drafts.
  - `classifier.py`: Structured error classification (`diagnose_error`) mapping raw CLI/libgit2 errors into 11 discrete categories (locks, pre-commit hook failures, hook reformatting exits, dirty working tree clashes, corrupt index) with tailored `DiagnosticReport` objects.
  - `actions.py`: Typed `RecoveryAction` instances executing safe self-healing workflows, including `StageHookModificationsAndRetryAction`, `RunPreCommitFixAction`, virtualenv-aware `AutoFormatAndRetryAction` (`find_project_binary`), `ReleaseStaleLockAction`, and `CommitNoVerifyAction`.
  - `process_guard.py`: Inspects `/proc` to verify whether process holding lock files is alive or defunct.
  - `sweeper.py`: Sweeps stale temporary staging files and orphan locks.
  - `transaction.py`: Transactional rollback guard for complex multi-step git operations.

### 3.3 Multi-Forge Subsystem (`src/wrench/forge/`)
- **`models.py`**: Normalized cross-provider data models:
  - `PullRequest`: Standardized entity with `state` normalized to `{"open", "merged", "closed"}` and trailing `author_avatar_url: str | None = None` preserving constructor backward compatibility.
  - `Issue`: Standardized entity with `state` normalized to `{"open", "closed"}` and trailing `author_avatar_url: str | None = None` preserving constructor backward compatibility.
  - `CIStatus`: Build status with state normalized to `{"success", "failure", "pending", "unknown"}`.
  - `ForgeAccount`: Runtime representation of configured accounts including TLS configuration and Secret Service references.
- **`capability.py`**:
  - `ForgeCapability`: Bitwise flags for granular feature gating (`PULL_REQUESTS`, `ISSUES`, `CI_STATUS`, `ISSUE_LINKING`, `REVIEWS`).
  - `ForgeAdapter(ABC)`: Abstract base class encapsulating `httpx.Client` with connection pooling, custom TLS CA bundle loading, self-signed skip-verification policies, automatic Secret Service token resolution, standard pagination (`_paged_get` with 500-item safeguard), status-code-to-exception translation, `get_primary_email()` contract, and `get_avatar_url(account, token)` capability method.
- **`registry.py`**: Pluggable adapter discovery using Python entry points (`[project.entry-points."wrench.forge_adapters"]`). Provides collision detection and the `get_adapter_for_account(account)` factory.
- **`adapters/`**: Provider-specific implementations:
  - `GitHubAdapter` (`github.py`): REST v3 API (`api.github.com` & GHES), Bearer authentication, `/issues` PR filtering, commit statuses + check-runs CI, full review submissions (`APPROVE`, `REQUEST_CHANGES`, `COMMENT`), `/user/emails` verified email resolution, and author avatar URL extraction via `user.avatar_url`.
  - `GitLabAdapter` (`gitlab.py`): REST v4 API (`gitlab.com` & self-hosted), Private-Token authentication, URL-encoded path slugs (`owner%2Frepo`), merge request state mapping, pipeline CI status, self-approval trap translation, and author avatar URL extraction via `author.avatar_url`.
  - `ForgejoAdapter` (`forgejo.py`): REST v1 API, token auth, commit status CI, past-tense `APPROVED` review action mapping, and author avatar URL extraction via `user.avatar_url`.
  - `BitbucketAdapter` (`bitbucket.py`): REST 2.0 API, HTTP Basic Auth (email + app password), `next` URL pagination, commit statuses, multi-endpoint review actions, and author avatar URL extraction via `author.links.avatar.href`.
- **`oauth/github_device_flow.py`**: Native OAuth Device Authorization Flow (RFC 8628):
  - Requests `repo workflow user:email read:org` scopes, with customizable preset and advanced scope configurations.
  - Background polling with `slow_down` rate-limit backoff (+5s interval adjustments) and cooperative cancellation.
- **`exceptions.py`**: Typed 6-tier exception hierarchy:
  - `ForgeError`, `ForgeAuthenticationError`, `ForgeInsufficientScopeError` (with `scope_hint`), `ForgeRateLimitedError` (with `retry_after_seconds`), `ForgeUnreachableError`, and `ForgeNotFoundError`.

### 3.4 File Watcher (`src/wrench/watcher/`)
- **`inotify_watcher.py` (`RepoWatcher`)**:
  - **Tier 1 (`full_inotify`)**: Uses `watchdog.observers.Observer` + `_WatchdogHandler` excluding internal `.git/` paths, capturing `on_modified`, `on_created`, `on_deleted`, and `on_moved` / `IN_MOVED_TO` events (including atomic tempfile renames) behind a configurable single-shot `QTimer` (`watcher.debounce_ms`, default 300ms). Both `_WatchdogHandler` and `_GitDirMetadataHandler` filter out internal `objects/info/commit-graph*` and `commit-graph.lock` writes so background commit-graph maintenance never triggers redundant self-reloads.
  - **Tier 2 (`git_dir_inotify` adaptive fallback)**: When `ENOSPC` / `EMFILE` watch limits are hit and `watcher.monorepo_adaptive_fallback.enabled` is active, switches to `_GitDirMetadataHandler` watching only `<gitdir>/{HEAD,index,packed-refs,config,config.worktree}`, `info/sparse-checkout`, and `refs/` via `core.paths.resolve_git_dir`.
  - **Tier 3 (`polling`)**: Falls back to Qt-thread `PollingFallback` when `inotify` is unavailable or disabled.
  - Exposes `suspend()` / `resume(grace_ms=150)`, dynamic `setting_changed` updates (`_on_setting_changed`), `adaptive_fallback_activated(mode, reason)` signal, and `status_info` (`WatcherStatusInfo`).
- **`polling_fallback.py`**: Qt-thread polling fallback loop emitting status refreshes when inotify handles are exhausted or disabled.

### 3.5 Local Data Storage (`src/wrench/storage/`)
- **`db.py`**: Manages SQLite connection (`wrench.db`) located in `$XDG_DATA_HOME/wrench/`.
  - Configured with `check_same_thread=False` and SQLite WAL mode (`PRAGMA journal_mode = WAL`).
  - Serialized through a single process-wide `threading.Lock()` to prevent SQLite concurrency deadlocks.
  - Automated corrupt database quarantine and recovery.
  - Schema migrations from v1 through v2 to v3 (`user_version = 3`).
- **`settings_registry.py`**: Universal Settings Registry engine (`VP-0`):
  - Manages all **83** `DEFAULT_SETTING_SPECS` across **13** `CATEGORIES_ORDER` (`General & UI`, `Staging & Commits`, `Commit Graph`, `Diff & Merge`, `Branches & Stacks`, `Worktrees & Submodules`, `Remotes & LFS`, `Forges & CI`, `Hooks & Signing`, `Blame & Search`, `Watcher & Performance`, `Safety & Backups`, `Custom Actions & Shortcuts`).
  - **Tiered Progressive Disclosure (`SettingTier`)**: Partitions preferences into `NORMAL` (17 core settings including `ui.settings_view_mode`) and `ADVANCED` (66 power-user settings).
  - **O(1) Effective Cache**: In-memory `_effective_cache` keyed by `(repo_path, key)` delivering `< 0.05 ms` lookups.
  - **Hierarchical Scoping**: Evaluates configuration with precedence: `repo_settings_overrides` > `global_settings` > `DEFAULT_SETTING_SPECS`.
  - **Delta-Only Undo Log (`OPT-3`)**: Persists inverse deltas (`SettingDelta`) directly in SQLite `settings_undo_log` (automatically pruned beyond the latest 100 entries) and cleans shadowed legacy rows via `_delete_stale_legacy_app_settings`.
  - **Preset Engine**: Provides built-in presets such as `apply_minimalist_local_only_preset()` to strip background network activity, forge polling, and heavy animations.
  - **JSON Portability**: Full configuration import and export (`export_json()` / `import_json()`) with validation and delta recording.
- **`settings.py`**: Seamless backward-compatibility bridge:
  - Retains `_SESSION_BLOB_KEYS` (`ui.session_state`, `ui.window_geometry`) directly in `app_settings` and routes `_LEGACY_KEY_ALIASES` (`"theme" -> "ui.theme_mode"`, `"repo.auto_fetch_on_open" -> "remote.auto_fetch.enabled"`) to `SettingsRegistry`.
- **`repo_registry.py`**: Repository CRUD operations, tracking last opened times, missing states (`is_missing`), and relocated paths. Provides `clear_missing(conn, path_or_id)` to restore missing repository records during multi-repo directory discovery.
- **`forge_accounts.py`**: Forge account metadata storage and repository-to-account bindings (`repo_forge_links`):
  - Supports `tls_ca_bundle_path` and `tls_insecure` columns.
  - Atomic two-step insert-then-update with automatic rollback on Secret Service storage failure.
  - Fast-path path-based link resolution for `git-credential-wrench`.
- **`health.py`**: SQLite database health checks, pragma integrity validation, and automated repair/vacuum routines.
- **`snapshots.py`**: Safety snapshot metadata records, dangling commit OIDs, and untracked archive paths.
- **`schema.sql`**: Normalized relational schema (Schema Version 3) defining `global_settings`, `repo_settings_overrides`, `settings_undo_log`, `repos`, `repo_identity_overrides`, `snapshots`, `repo_forge_links`, and `forge_accounts`.

### 3.6 Credentials & Platform Layer (`src/wrench/credentials/`)
- **`backend.py`**: Abstract base class `CredentialBackend` defining `get_secret(key)`, `store_secret(key, secret)`, and `delete_secret(key)`.
- **`secret_service.py`**: `SecretServiceBackend` implementing the Freedesktop Secret Service D-Bus specification via `secretstorage`.
  - Automatically handles collection unlocking via `collection.unlock()`.
  - Formats user-actionable diagnostics tailored to runtime environments: Flatpak sandboxes, desktop keyrings (GNOME Keyring / KWallet), and headless systems.
  - Strict compliance with Platform-Abstraction Guard (FR-11.1–11.3): all Secret Service imports are strictly encapsulated here.
- **`__init__.py`**: Caching factory function `get_backend()` and packaging context detection `detect_packaging_context()` (`flatpak`, `snap`, `appimage`, `system`).

### 3.7 Automated AST Security & Anti-Hallucination Guard (`tests/unit/test_no_shortcuts_guard.py`)
- **Continuous Architectural Integrity Assurance**:
  - Automatically scans every Python source file in `src/wrench/` using Python's native `ast` module before test execution or CI completion.
- **Enforced Security & Cleanliness Gates**:
  1. **Strict Layer Boundary Purity (`test_ui_layer_never_imports_backends_directly`)**:
     - Asserts that no file in `src/wrench/ui/` directly imports `pygit2`, `subprocess`, `sqlite3`, `httpx`, `wrench.core.read_ops`, `wrench.core.write_ops`, or `wrench.storage.db`. All access MUST route through `core.engine`, `forge.registry`, or `storage.settings_registry`.
  2. **Subprocess Argument Safety (`test_no_shell_true_or_not_implemented_stubs`)**:
     - Verifies that zero subprocess calls set `shell=True` (`SEC-1`). All git commands MUST execute as argument lists with `--` before filenames or user-supplied references.
     - Detects and rejects any `raise NotImplementedError` stubbing across production source code (`FLASH-1`).
  3. **SQL Injection Prevention (`test_no_fstring_sql_queries_in_storage` / `SEC-7`)**:
     - Verifies that all `cursor.execute(...)` calls in `src/wrench/storage/` use parameterized query tuples (`?`) rather than formatted strings (`f"..."`), `%`-formatting, or `str.format()`.
  4. **Zero Truncation Markers & Anti-Hallucination (`test_no_flash_api_hallucinations_or_truncation_markers`)**:
     - Scans for LLM truncation markers (e.g. `# ... existing code ...`, `# ... rest of class ...`, `TODO: implement`, `pass # placeholder`).
     - Flags hallucinations of deprecated GitPython APIs (e.g. `iter_commits`, `active_branch`) or PyQt5/PyQt6 imports.
  5. **Zero Silent Error Swallowing (`test_no_silent_exception_pass_in_src` / `FLASH-5`)**:
     - Detects `try ... except Exception: pass` anti-patterns across `src/wrench/`. All caught exceptions must be logged or handled with explicit recovery actions.

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
[Desktop Theme Change] OR [View -> Theme Menu] OR [SettingsDialog: ui.theme_mode]
                            │
                            ▼
           [QGuiApplication.styleHints().colorSchemeChanged]
                                    OR
                     [MainWindow._set_theme(mode)]
                            │
                            ├── 1. Normalize mode ("auto"/"system") & apply Qt QPalette
                            ├── 2. Recursive Palette Propagation + _repolish_widget
                            ├── 3. Persist via settings/SettingsRegistry ('ui.theme_mode')
                            │
                            ▼
             [Broadcast QEvent.PaletteChange & ApplicationPaletteChange]
                            │
          ┌─────────────────┼─────────────────┬──────────────────────┐
          ▼                 ▼                 ▼                      ▼
   [TabContainer]    [ChangesTab]      [HistoryTab]     [Status Pills & Dialogs]
          │                 │                 │                      │
          ├── Refresh tabs  ├── Refresh badges├── Refresh stats      └── _apply_status_bar_theme()
          │   (active /     ├── Conflict theme├── Graph viewport         _active_settings_dialog /
          │    inactive)    └── DiffWidget    └── Detail panel         _sparse_dialog / QDialogs
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
1. `apply_theme(app, mode)` normalizes modes (`normalize_theme_mode`) and applies the selected `QPalette` to `QApplication`.
2. It traverses every top-level window via `QApplication.topLevelWidgets()` and sets the palette on each window and every descendant widget found via `top_widget.findChildren(QWidget)`.
3. `MainWindow._propagate_theme_refresh()` directly invokes `refresh_theme()` on child workspaces (`TabContainer`, `ChangesTab`, `HistoryTab`), refreshes status bar pills (`_apply_status_bar_theme()`), and calls `_apply_theme()` + `_repolish_widget()` on open dialogs (`_active_settings_dialog`, `_sparse_dialog`, and child `QDialog`s) so open Preferences and modal sheets repaint immediately.

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
| **Secondary Subtext** | `#5c5f77` (High-contrast slate `SECONDARY_TEXT`) | `#a6adc8` (Soft lavender-gray `SECONDARY_TEXT`) |
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
| **Avatar Backgrounds** | 6 accessible Latte tones (`#1e66f5`, `#8839ef`, `#40a02b`, `#d20f39`, `#179299`, `#7287fd`) | 6 accessible Mocha tones (`#89b4fa`, `#cba6f7`, `#a6e3a1`, `#fab387`, `#94e2d5`, `#b4befe`) |

#### 4.7.5 Accessible Deterministic Avatar Color Generation
Avatar fallback badges derive their background colors using `get_avatar_bg_color(username: str, mode: str = "dark")`:
1. **Deterministic Hashing**: The username string is hashed (`abs(hash(username)) % len(tokens)`) ensuring persistent color assignment across sessions.
2. **WCAG 2.1 AA/AAA Contrast**: White text (`#ffffff`) against all 12 `AVATAR_BG_COLORS` tokens achieves $\ge 4.5:1$ contrast ratio, verified by automated CI gates (`tests/unit/ui/test_theme_contrast.py`).
3. **Zero Hardcoded Colors**: Strictly centralized in `ui/theme.py`; hardcoded color checks forbid raw hex codes outside the theme engine.

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

### 4.12 Multi-Repository Directory Discovery Workflow (FR-1.12)
```text
[User clicks "Open Repository" (Ctrl+O) in MainWindow]
                          │
                          ▼
             [QFileDialog.getExistingDirectory]
                          │
         ┌────────────────┴────────────────┐
         ▼                                 ▼
[Path is Git Repository]        [Path is Directory Container]
(engine.open_repo succeeds)     (engine.open_repo raises WrenchRepoNotFoundError)
         │                                 │
         ├── Add to repo_registry          ▼
         ├── Load in ChangesTab        [MainWindow._start_directory_discovery(root_path)]
         └── Done                          │
                                           ├── Show non-modal status bar scan notification
                                           ├── Instantiate cancel_event = threading.Event()
                                           ├── ui.workers.run_in_background(
                                           │       core.discovery.discover_repos,
                                           │       root_path, max_depth=3, cancel_event, on_progress
                                           │   )
                                           │
                                           ▼
                             [Background Worker Thread]
                                           │
                                           ├── os.walk(root_path, followlinks=False)
                                           ├── Cycle guard: refuses symlinks to prevent infinite loops
                                           ├── Prunes dot-directories (.cache, .local, etc.)
                                           ├── Depth guard: stops descent when depth >= 3
                                           │
                                  ┌────────┴───────────────────────────┐
                                  ▼                                    ▼
                         [.git Directory or File]             [Non-Repo Directory]
                                  │                                    │
                                  ├── Add resolved path                └── Descend if depth < 3
                                  ├── Prune dirnames (no submodules)
                                  └── Emit on_progress(count)
                                           │
                                           ▼
                             [Scan Completes / Results Returned]
                                           │
                                  ┌────────┴───────────────────────────┐
                                  ▼                                    ▼
                             [0 Repos Found]                    [>= 1 Repos Found]
                                  │                                    │
                                  └── QMessageBox.information          ▼
                                      ("No Repositories Found")  [Launch DiscoverReposDialog]
                                                                       │
                                                                       ├── Displays checkable list
                                                                       ├── Select All / Deselect All
                                                                       │
                                                              ┌────────┴────────┐
                                                              ▼                 ▼
                                                         [User Confirms]   [User Cancels]
                                                              │                 │
                                                              ├── Loop paths    └── Abort
                                                              │   ├── Known & is_missing:
                                                              │   │     repo_registry.clear_missing()
                                                              │   └── New repo:
                                                              │         repo_registry.add_repo()
                                                              │
                                                              ▼
                                               [ChangesTab.load_repos()]
                                               [Status bar: "Added X repos (Y already known)"]
```

### 4.13 Asynchronous Non-Blocking Avatar Loading & Gravatar Privacy Workflow (FR-5.14)
```text
[UI Surface Requests Avatar: PRList, PRDetail, ChangesTab, CommitDetailPanel]
                               │
                               ▼
            [AvatarWidget.set_avatar(url, username/email)]
                               │
                               ├── 1. Immediately paint fallback badge with 2-letter initials
                               ├── 2. Background color resolved via get_avatar_bg_color(username)
                               │      (deterministic WCAG 2.1 AAA/AA compliant Catppuccin palette)
                               │
                               ▼
                   [AvatarLoader.load_avatar(url)]
                               │
                    ┌──────────┴────────────────────────┐
                    ▼                                   ▼
          [Memory Cache Hit]                  [Memory Cache Miss]
                    │                                   │
                    ├── Return cached QPixmap           ▼
                    └── Instant zero-latency render   [Check On-Disk Cache]
                                                        │
                                                        ├── Path: cache_dir() / "avatars" / "{sha256(url)}.png"
                                                        │
                                             ┌──────────┴────────────────────────┐
                                             ▼                                   ▼
                                    [Disk Cache Valid (< 7d)]         [Disk Miss or Stale (>= 7d)]
                                             │                                   │
                                             ├── Read bytes from disk            ▼
                                             ├── Decode QPixmap            [In-Flight Request Coalescing]
                                             ├── Populate _mem_cache             │
                                             └── Emit avatar_loaded              ├── URL already fetching?
                                                                                 │   └── Attach callback & wait
                                                                                 │
                                                                                 ▼
                                                                   [Background Worker Download]
                                                                                 │
                                                                                 ├── urllib.request.urlopen
                                                                                 │   (5-second timeout)
                                                                                 │
                                                                      ┌──────────┴──────────┐
                                                                      ▼                     ▼
                                                             [Download Success]    [Error / Offline]
                                                                      │                     │
                                                                      ├── Save to disk      └── Fail silently;
                                                                      ├── Store in mem          retain initials
                                                                      └── Emit avatar_loaded
                                                                              │
                                                                              ▼
                                                                   [GUI Thread Qt Dispatch]
                                                                              │
                                                                              └── Smooth cross-fade to
                                                                                  circular anti-aliased
                                                                                  QPixmap in AvatarWidget
```

#### 4.13.1 Gravatar Privacy Opt-In Enforcement
For commit authors, avatar URLs are synthesized by hashing the author's normalized email address (`https://www.gravatar.com/avatar/{hash}`).
To eliminate telemetry leakage and strictly protect developer privacy:
1. **Default-OFF Setting**: The setting `ui.avatars_gravatar` defaults to `False`.
2. **Privacy Gate**: `CommitDetailPanel` checks `settings.get_setting("ui.avatars_gravatar", "false")`. When disabled, zero external network requests are initiated; the widget exclusively displays the author's deterministic initials badge.
3. **Explicit Opt-In**: Users can explicitly enable Gravatar avatar fetching via the "Enable Gravatar avatars for commit authors" checkbox on `SettingsDialog`'s `Appearance` category.

### 4.14 Universal Settings Registry Resolution & Delta Undo Workflow (VP-0, OPT-1..3)
```text
[Component Queries Setting: engine.is_feature_enabled(key, repo_path)]
                              │
                              ▼
        [storage.settings_registry.get_bool(key, repo_path)]
                              │
                              ├── 1. Check in-memory O(1) _effective_cache[(key, repo_path)]
                              │      - Hit? Return in < 0.05 ms (0 lock contention, 0 SQL)
                              │
                              ▼
                      [Cache Miss Path]
                              │
                              ├── 2. Query repo_settings_overrides WHERE repo_path=? AND key=?
                              │      - Found? Populate _effective_cache & return value
                              │
                              ├── 3. Query global_settings WHERE key=?
                              │      - Found? Populate _effective_cache & return value
                              │
                              └── 4. Fall back to DEFAULT_SETTING_SPECS[key].default
                                     - Populate _effective_cache & return default value

[User Mutates Setting in SettingsDialog (e.g., Toggles Feature)]
                              │
                              ▼
             [SettingRowWidget Value Mutation]
                              │
                              ├── Checkbox / Combo / Spin editingFinished ──► Immediate save
                              └── Text / Spin valueChanged ──► 150ms QTimer debounce (flush_pending() on close)
                              │
                              ▼
           [registry.set(key, new_val, repo_path)]
                              │
                              ├── 1. Record inverse delta into SQLite settings_undo_log (capped at 100 entries, OPT-3)
                              ├── 2. UPSERT INTO global_settings OR repo_settings_overrides
                              ├── 3. _delete_stale_legacy_app_settings (clears shadowed v1 rows)
                              ├── 4. Update/invalidate _effective_cache entries for key
                              └── 5. Emit setting_changed(key, new_val, repo_path) Signal
                                           │
                                           ├──► MainWindow._on_registry_setting_changed (live UI/service apply)
                                           └──► CategorySettingsPage.reload_key (preserves active unsaved edits)
```

### 4.15 Git LFS Inspection, Attribute Binding & Pointer File Workflow
```text
[Repository Opened / ChangesTab Loaded]
                  │
                  ▼
   [core.engine.repo_uses_lfs(repo)]
                  │
                  ├── Inspects .gitattributes via pygit2 in-memory
                  │   └── Checks for 'filter=lfs' pattern bindings
                  │
                  ▼
       [Git LFS Installed Check]
                  │
        ┌─────────┴─────────┐
        ▼                   ▼
[git-lfs in PATH]   [git-lfs Missing]
        │                   │
        │                   └── Fail-safe: disable LFS features gracefully
        ▼
[Inspect Suspicious / Large Blob via core.engine.is_lfs_pointer_file]
        │
        ├── In-memory read of file header via pygit2.Blob (0 subprocess overhead)
        │   - Line 1: 'version https://git-lfs.github.com/spec/v1'
        │   - Line 2: 'oid sha256:<64-hex>'
        │   - Line 3: 'size <bytes>'
        │
        ▼
   [LFS Operations via git CLI]
        ├── lfs_track(repo, pattern): appends pattern to .gitattributes, git add .gitattributes
        ├── lfs_untrack(repo, pattern): removes line from .gitattributes
        └── lfs_pull(repo): executes git lfs pull -- with background progress
```

### 4.16 Submodule Lifecycle Management Workflow
```text
[User Opens SubmoduleDialog from Repository Menu]
                        │
                        ▼
    [core.submodules.list_submodules(repo)]
                        │
                        ├── pygit2 in-memory read of .gitmodules config
                        ├── Parses sections [submodule "<name>"]: path, url, branch
                        └── Compares submodule commit SHA against index entry
                        │
                        ▼
       [SubmoduleDialog Displays Submodules Table]
                        │
         ┌──────────────┼──────────────┬──────────────┐
         ▼              ▼              ▼              ▼
     [Add Sub]     [Update All]    [Sync URLs]    [Initialize]
         │              │              │              │
         │       git submodule  git submodule  git submodule
         │       update --init   sync --rec     init <name>
         │        --recursive          │              │
         ▼              │              │              │
   git submodule        ▼              ▼              ▼
   add -b <branch>  [Background Worker Threads with Progress]
   -- <url> <path>      │
         │              ▼
         └────────► [Main Thread Qt Signals: Refresh Dialog Table]
```

### 4.17 Git Bundle Creation, Verification & Restore Workflow
```text
[Backup / Bundle Triggered]
             │
             ▼
[core.bundles.create_bundle(repo, output_path, rev_range="--all")]
             │
             ├── Runs: git bundle create -- <output_path> <rev_range>
             └── Atomic single-file archive generated
             │
             ▼
[core.bundles.verify_bundle(repo, bundle_path)]
             │
             ├── Runs: git bundle verify -- <bundle_path>
             └── Parses output into BundleVerificationResult(is_valid, prerequisites, heads)
             │
             ▼
[core.backup.restore_backup(bundle_path, dest_path)]
             │
             └── Runs: git clone -- <bundle_path> <dest_path>
```

### 4.18 Reflog Inspection, Safe Branching & Reset Workflow
```text
[User Triggers Reflog Inspection in Recovery / History]
                        │
                        ▼
       [core.reflog_ops.list_reflog(repo, ref="HEAD")]
                        │
                        ├── pygit2 / git CLI parses reflog records:
                        │   (index, commit_sha, old_sha, committer, timestamp, message)
                        │
                        ▼
        [Actionable Recovery Options]
                        │
         ┌──────────────┴──────────────┐
         ▼                             ▼
[Create Branch from Reflog]    [Reset to Reflog Entry]
(create_branch_from_reflog)    (reset_to_reflog_entry)
         │                             │
         ├── Safe non-destructive      ├── Safety Snapshot Taken
         │   recovery:                 │   (maybe_create_safety_snapshot)
         └── git branch <name> <sha>   │
                                       └── git reset --hard <sha>
```

### 4.19 Monorepo Scalability, Partial Clone & Sparse-Checkout Workflow (`VP-16`)
```text
[User Opens CloneDialog OR Large Monorepo (100k+ commits)]
         │
         ├──[Clone Path]──► validate_clone_url() (SEC-2) + git clone [--filter=blob:none|tree:0] [--sparse]
         │
         ├──[Repository -> Sparse-Checkout Directories...]──► SparseCheckoutDialog
         │      ├── _TreeExpandWorker (QThreadPool + gen_id OPT-6) -> list_tree_subdirectories()
         │      └── _ApplySparseWorker -> watcher.suspend() -> git sparse-checkout set/disable -> watcher.resume(150ms)
         │
         └──[On Repo Open / Scroll / Diff]
                ├── _CommitGraphWorker (QThreadPool) -> maybe_write_commit_graph() (if maintenance.auto_commit_graph.enabled)
                ├── CommitGraphWidget -> _GraphPageWorker (slices _ACTIVE_WALKER_CACHE by performance.graph_page_size at 80% scroll)
                ├── RepoWatcher -> Tier 1 full_inotify -> (ENOSPC/EMFILE) Tier 2 git_dir_inotify -> Tier 3 polling
                └── DiffView -> caps rendering at 5,000 lines / performance.max_diff_file_size_kb with 1-click full-diff reload
```

### 4.20 Visual Interactive Rebase & `GIT_SEQUENCE_EDITOR` Workflow (`VP-2`)
```text
[User Right-Clicks Commit in CommitGraphWidget -> "Interactive Rebase from Here..."]
         │
         ├── HistoryTab.interactive_rebase_requested(base_oid) -> MainWindow._on_history_interactive_rebase
         ▼
[InteractiveRebaseDialog (ui/dialogs/interactive_rebase_dialog.py)]
         ├── 1. _LoadCommitsWorker (QThreadPool + generation_id OPT-6)
         │      └── engine.list_commits_for_interactive_rebase_checked() -> pygit2 topological reverse walk (<= 1000)
         ├── 2. User edits sequence:
         │      ├── _RebaseTodoTableWidget (InternalMove drag-and-drop -> row_move_requested)
         │      ├── Per-row action selector (pick | reword | edit | squash | fixup | drop)
         │      ├── Inline message editor (reword/squash) & top-row squash/fixup guard
         │      └── Live CliCommandPreviewBar footer (SEC-3 redacted)
         ▼
[User Clicks "Start Rebase" -> _RunInteractiveRebaseWorker]
         ├── Emit rebase_started -> MainWindow suspends RepoWatcher
         ├── core.engine.interactive_rebase -> snapshots.maybe_create_safety_snapshot()
         ├── core.rebase_sequencer.run_interactive_rebase():
         │      ├── Write plan.json inside 0o700 tempdir with 0o600 file permissions (SEC-4)
         │      └── git -C <repo> rebase -i [--autostash] [--autosquash] -- <base_oid> (SEC-1)
         │             ├── GIT_SEQUENCE_EDITOR -> python -m wrench.core.rebase_editor_helper (git-rebase-todo)
         │             └── GIT_EDITOR          -> python -m wrench.core.rebase_editor_helper (COMMIT_EDITMSG)
         └── Emit rebase_completed(RebaseResult) / rebase_failed(redacted_err)
                ├── Resume RepoWatcher (+150ms grace)
                └── Route 'paused' / 'conflict' states to ChangesTab sequencer controls
```

---

## 5. Relational Database Schema (Version 3)

```text
┌──────────────────────────────┐       ┌────────────────────────────────────┐
│            repos             │       │        identity_profiles           │
├──────────────────────────────┤       ├────────────────────────────────────┤
│ id (PK)                      │       │ id (PK)                            │
│ path (UNIQUE)                │       │ label                              │
│ display_name                 │       │ name                               │
│ last_branch                  │       │ email                              │
│ last_opened_at               │       └─────────────────┬──────────────────┘
│ is_missing                   │                         │
│ created_at                   │       ┌─────────────────▼──────────────────┐
└──────┬───────────────┬───────┘       │      repo_identity_overrides       │
       │               │               ├────────────────────────────────────┤
       │               └──────────────►│ repo_id (FK, PK)                   │
       │                               │ identity_id (FK)                   │
       ├───────────────────────┐       └────────────────────────────────────┘
       │                       │
       ▼                       ▼
┌──────────────────────────────┐       ┌────────────────────────────────────┐
│          snapshots           │       │      snapshot_untracked_files      │
├──────────────────────────────┤       ├────────────────────────────────────┤
│ id (PK)                      │◄──────┤ snapshot_id (FK, PK)               │
│ repo_id (FK -> repos.id)     │       │ relative_path (PK)                 │
│ ref_name                     │       │ content_captured                   │
│ trigger_type                 │       │ size_bytes                         │
│ is_manual                    │       └────────────────────────────────────┘
│ label                        │
│ created_at                   │       ┌────────────────────────────────────┐
│ untracked_archive_path       │       │         snapshot_settings          │
└──────────────────────────────┘       ├────────────────────────────────────┤
                                       │ repo_id (FK -> repos.id, PK)       │
┌──────────────────────────────┐       │ trigger_on_commit / timer / risky  │
│       repo_forge_links       │       │ timer_interval_minutes / max_count │
├──────────────────────────────┤       │ max_age_days / untracked_caps      │
│ repo_id (FK -> repos.id, PK) │       └────────────────────────────────────┘       ┌────────────────────────────────────┐
│ remote_name (PK)             │       │           forge_accounts           │
│ forge_account_id (FK)        ├──────►├────────────────────────────────────┤
│ owner_slug / repo_slug       │       │ id (PK)                            │
└──────────────────────────────┘       │ provider / instance_url / label    │
                                       │ username / secret_service_key      │
┌──────────────────────────────┐       │ tls_ca_bundle_path / tls_insecure  │
│         app_settings         │       │ created_at                         │
├──────────────────────────────┤       └────────────────────────────────────┘
│ key (PK)                     │
│ value (session blobs/flags)  │       ┌────────────────────────────────────┐
└──────────────────────────────┘       │      repo_settings_overrides       │
                                       ├────────────────────────────────────┤
┌──────────────────────────────┐       │ repo_path (PK)                     │
│       global_settings        │       │ key (PK)                           │
├──────────────────────────────┤       │ value_json                         │
│ key (PK)                     │       │ updated_at                         │
│ value_json                   │       └────────────────────────────────────┘
│ updated_at                   │
└──────────────────────────────┘
┌───────────────────────────────────────────────────────────────────────────┐
│                            settings_undo_log                              │
├───────────────────────────────────────────────────────────────────────────┤
│ change_id (PK AUTOINCREMENT)                                              │
│ timestamp                                                                 │
│ repo_path                                                                 │
│ key                                                                       │
│ old_value_json                                                            │
│ new_value_json                                                            │
│ undone (0 or 1)                                                           │
└───────────────────────────────────────────────────────────────────────────┘
```

---

## 6. Directory Structure

```
wrench/
├── .github/
│   ├── actions/
│   │   └── setup-test-env/
│   │       └── action.yml        # Composite action: Qt runtime packages & pre-built wheels
│   └── workflows/
│       └── ci.yml                # lint, unit-tests, integration-tests, ui-tests
├── bin/                          # Development helper binaries (uv & uvx with runtime LD_LIBRARY_PATH)
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
│       ├── v2-implementation-plan.md
│       ├── phase-1.md
│       ├── phase-1.5.md
│       ├── phase-2.md
│       ├── phase-3.md
│       ├── phase-4.md
│       ├── phase-4.1.md
│       ├── phase-4.2.md
│       ├── phase-4.3.md
│       ├── phase-4.4.md
│       ├── phase-4.5.md
│       ├── phase-4.6.md
│       └── python-315-migration.md
├── packaging/
│   ├── build-all.sh
│   ├── appimage/                 # AppImage packaging script
│   │   └── build-appimage.sh
│   └── flatpak/                  # Flatpak packaging manifests
├── src/wrench/
│   ├── app.py                    # Application bootstrap & logging configuration
│   ├── core/                     # Core Git engine & platform primitives
│   │   ├── engine.py             # Public unified façade
│   │   ├── models.py             # Core dataclass models (LFS, submodules, bundles, reflog, VP-16)
│   │   ├── read_ops.py           # pygit2 read operations & _ACTIVE_WALKER_CACHE
│   │   ├── write_ops.py          # subprocess CLI write, streaming ops & write_commit_graph
│   │   ├── rebase_sequencer.py   # VP-2: pygit2 rebase walk & GIT_SEQUENCE_EDITOR runner
│   │   ├── rebase_editor_helper.py # VP-2: standalone CLI editor for rebase-todo/COMMIT_EDITMSG
│   │   ├── sparse_checkout.py    # Cone-mode sparse-checkout & HEAD/ls-tree subdir listing
│   │   ├── security_sanitizer.py # Clone URL, git ref & CLI/log secret redaction (SEC-2/SEC-3)
│   │   ├── lfs_ops.py            # Git LFS detection, attributes & pointer inspection
│   │   ├── submodules.py         # Submodule enumeration, update, sync, and init
│   │   ├── bundles.py            # Git bundle creation, verification, and unbundling
│   │   ├── reflog_ops.py         # Reflog listing, branch recovery, and safe reset
│   │   ├── git_credential_helper.py # Standalone git-credential-wrench executable
│   │   ├── ssh_agent.py          # SSH_AUTH_SOCK platform encapsulation
│   │   ├── exceptions.py         # Domain and CLI typed exceptions
│   │   ├── lock_recovery.py      # Stale index.lock detection
│   │   ├── snapshots.py          # Rolling safety snapshots
│   │   ├── reflog.py             # Reflog operations
│   │   ├── identity.py           # Git author configuration
│   │   ├── paths.py              # XDG/platformdirs resolution & resolve_git_dir
│   │   ├── remote_urls.py        # Remote URL parser & host extractor
│   │   ├── backup.py             # Configuration backup & restore helpers
│   │   ├── discovery.py          # FR-1.12: bounded multi-repo directory scanner
│   │   ├── lazy_loader.py        # Explicit lazy import proxy and loader
│   │   ├── lazy_demo.py          # Python 3.15 native lazy import demonstration
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
│   │   ├── capability.py         # ForgeCapability flags, ForgeAdapter ABC & get_avatar_url
│   │   ├── exceptions.py         # Typed forge error hierarchy
│   │   ├── models.py             # Dataclasses: PullRequest, Issue, CIStatus, author_avatar_url
│   │   ├── registry.py           # Dynamic entry point & provider adapter registry
│   │   ├── adapters/             # Forge provider implementations
│   │   │   ├── github.py         # GitHub REST/GraphQL adapter & user.avatar_url
│   │   │   ├── gitlab.py         # GitLab REST adapter & author.avatar_url
│   │   │   ├── forgejo.py        # Forgejo / Gitea REST adapter & user.avatar_url
│   │   │   └── bitbucket.py      # Bitbucket Cloud REST adapter & author avatar link
│   │   └── oauth/                # OAuth flows
│   │       └── github_device_flow.py # RFC 8628 Device Authorization Flow client
│   ├── storage/                  # SQLite storage & repository registry
│   │   ├── db.py                 # SQLite connection management & locks
│   │   ├── settings_registry.py  # Universal Settings Registry (13 cats, 83 specs, Normal/Advanced)
│   │   ├── repo_registry.py      # Repository tracking CRUD & clear_missing
│   │   ├── settings.py           # App, session-blob & alias settings bridge
│   │   ├── forge_accounts.py     # Forge accounts, repo links & TLS settings
│   │   ├── health.py             # Database integrity diagnostics & vacuuming
│   │   ├── snapshots.py          # Safety snapshots metadata
│   │   └── schema.sql            # Normalized relational schema (Schema v3)
│   ├── ui/                       # PySide6 desktop UI
│   │   ├── main_window.py        # Main application window, live settings & repository menu
│   │   ├── theme.py              # Catppuccin Velvet Pastel palettes, pills & dialog styles
│   │   ├── quotes.py             # Clean-state, waiting & wisdom quote banks
│   │   ├── workers.py            # Thread-safe background worker marshaller
│   │   ├── commit_graph/         # Topological DAG layout & paginated table view
│   │   │   ├── layout.py         # S-curve calculation & slot recycling
│   │   │   ├── graph_widget.py   # CommitGraphWidget, QThreadPool workers & QPixmapCache
│   │   │   └── detail_panel.py   # CommitDetailPanel & author Gravatar avatar
│   │   ├── dialogs/              # Interactive dialogs & account managers
│   │   │   ├── about_dialog.py   # About Wrench dialog & rotating wisdom
│   │   │   ├── accounts_dialog.py# Forge accounts manager & OAuth Device Flow
│   │   │   ├── clone_dialog.py   # Partial/sparse CloneDialog & _SingleLinePathLabel
│   │   │   ├── discover_repos_dialog.py # Multi-repo discovery review & batch import
│   │   │   ├── interactive_rebase_dialog.py # VP-2: drag-to-reorder interactive rebase dialog
│   │   │   ├── link_dialog.py    # Remote-to-forge account association dialog
│   │   │   ├── partial_staging_dialog.py # MM/AM intent resolver dialog
│   │   │   ├── push_recovery_dialogs.py # Secret scanning, branch, network & size recovery
│   │   │   ├── remotes_dialog.py # Repository remotes manager & reachability
│   │   │   ├── settings_dialog.py# 13-cat preferences dialog (Normal/Advanced tier switcher)
│   │   │   ├── sparse_checkout_dialog.py # Cone-mode sparse-checkout directory tree dialog
│   │   │   └── submodule_dialog.py # Submodule manager (Add, Update, Sync, Init)
│   │   ├── diff_view/            # Syntax-highlighted diff viewer & staging (5k-line cap)
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
│   │   │   ├── changes_tab.py    # Primary Changes workspace, quotes & account avatar
│   │   │   ├── history_tab.py    # History / Commit graph workspace
│   │   │   ├── pr_list_tab.py    # Pull Requests virtualized list & 24px avatars
│   │   │   ├── pr_detail_tab.py  # Pull Request discussion & 40px avatar header
│   │   │   ├── issue_list_tab.py # Issues virtualized list & 24px avatars
│   │   │   └── issue_detail_tab.py # Issue discussion & 40px avatar header
│   │   └── widgets/              # Reusable UI widgets
│   │       ├── activity_log.py   # Live ActivityLogBar & deque ring buffer
│   │       ├── avatar.py         # AvatarWidget & AvatarLoader singleton
│   │       ├── branch_switcher.py# Interactive branch selector & popup
│   │       ├── cli_preview_bar.py# Secret-redacted CLI command preview footer
│   │       └── loading_overlay.py# Semi-transparent loading spinner overlay
│   └── watcher/                  # 3-tier inotify/git-dir/polling filesystem watcher
├── tests/                        # Comprehensive test suite (core, unit, integration, UI)
│   ├── core/
│   │   ├── test_interactive_rebase.py # VP-2 interactive rebase core & helper tests
│   │   └── test_sparse_checkout.py     # Cone sparse-checkout, partial clone & sanitizer tests
│   ├── integration/                    # Adapter integration suites (github, gitlab, forgejo, bitbucket)
│   ├── unit/                           # Core, storage, credentials, forge & theme/widget unit tests
│   │   ├── test_no_shortcuts_guard.py  # AST security & anti-hallucination guard
│   │   ├── test_settings_registry.py   # SettingsRegistry unit tests
│   │   ├── test_lfs_ops.py             # Git LFS ops unit tests
│   │   ├── test_submodules.py          # Submodule operations unit tests
│   │   ├── test_bundles.py             # Git bundle operations unit tests
│   │   └── test_reflog_ops.py          # Reflog operations unit tests
│   └── ui/
│       ├── test_clone_picker.py        # CloneDialog & _SingleLinePathLabel tests
│       ├── test_forge_repo_switch.py   # Repo switch memory, diff reset & tab disposal tests
│       ├── test_interactive_rebase_dialog.py # VP-2 InteractiveRebaseDialog & theme tests
│       ├── test_large_graph_virtualization.py # 100k+ pagination, diff cap & sparse UI tests
        ├── test_lazy_tabs.py           # Lazy/multi-forge tab lifecycle tests
        ├── test_main_window_feedback.py# ActivityLogBar, humor toggle & AboutDialog tests
        ├── test_partial_staging_dialog.py # PartialStagingDialog tests
        ├── test_settings_dialog.py     # Legacy v1 SettingsDialog compatibility tests
        ├── test_settings_dialog_v2.py  # 13-cat Normal/Advanced & live propagation tests
        └── test_submodule_dialog.py    # SubmoduleDialog UI tests
```

---

## 10. Python 3.15 Runtime & PEP 810 Native Lazy Imports

### 10.1 Execution Model & Runtime Requirements
Wrench requires:
- **Runtime & Compilation Target**: CPython 3.15.0+ with PySide6 6.12.0 (Stable ABI `abi3`), pygit2 1.20+ (compiled C-extension against libgit2), and `uv` 0.13+.
- **Package Constraint**: `requires-python = ">=3.15"` in `pyproject.toml`, enforcing native PEP 810 language syntax across local development, downstream distribution, and automated CI pipelines.

### 10.2 PEP 810 Native Explicit Lazy Imports
Python 3.15 introduces native `lazy import <module>` syntax. Rather than eagerly executing a module's bytecode and registering its symbols into `sys.modules` at startup, Python 3.15 instantiates a lightweight deferred stub. Bytecode execution is suspended until first attribute access.

```text
Application Launch (python -m wrench.app)
  │
  ├─► lazy import secretstorage ───► Stub created (sys.modules untouched)
  ├─► lazy import platformdirs  ───► Stub created (sys.modules untouched)
  ├─► lazy import httpx         ───► Stub created (sys.modules untouched)
  │
  ├─► MainWindow Initialization (instantaneous UI render)
  │
  ▼
On User Interaction / Background Action:
  ├─► User clicks "Fetch/Pull" ──► httpx resolved & initialized on-demand
  └─► Credential lookup        ──► secretstorage resolved & D-Bus connected on-demand
```

### 10.3 Native C-Extension Build System & Linker Guard
For compiled extensions on Python 3.15 (where prebuilt PyPI wheels are not yet available):
1. **User-Space Development Prefix (`.build/`)**: Official `libgit2-devel` and `libffi-devel` headers are vendored inside the workspace, eliminating `sudo` requirements.
2. **Environment Exports**: `init-dev.sh` exports `C_INCLUDE_PATH`, `LIBRARY_PATH`, and `PKG_CONFIG_PATH` to enable seamless `uv pip install -e ".[dev]"`.
3. **Runtime Linker Path**: All developer binaries (`bin/wrench-*`) prepend `.build/libgit2/usr/lib64` to `LD_LIBRARY_PATH` ensuring `libgit2.so.1.9` is resolved dynamically at runtime.

---

## 11. Modern Developer Tooling & UV Workflow Architecture

### 11.1 Fast Standardized Developer Scripts (`bin/wrench-*`)
All development and CI operations are unified under the `bin/wrench-*` executable suite:
- `bin/wrench-run`: Launches the desktop application (`python -m wrench.app`).
- `bin/wrench-debug`: Runs Wrench with full `--debug` logging flags enabled.
- `bin/wrench-test`: Executes the pytest suite under `uv run --no-sync pytest -v "$@"`.
- `bin/wrench-lint`: Runs fast Ruff linting and Black code style verification.
- `bin/wrench-format`: Automatically formats and fixes code violations via Ruff and Black.
- `bin/wrench-ci-check`: Orchestrates linting, formatting, and the complete test suite.

### 11.2 Zero-Sync Execution (`--no-sync`)
By utilizing `uv run --no-sync`, developer scripts avoid re-resolving dependencies and checking network indexes on every command invocation. This reduces test startup latency from hundreds of milliseconds to under 20ms, providing near-instantaneous test and lint cycles.

### 11.3 Automated Runtime Linker Management
All scripts verify the presence of the vendored native prefix (`.build/libgit2/usr/lib64`) and automatically prepend it to `LD_LIBRARY_PATH`. This ensures `libgit2.so` and related system dynamic dependencies load correctly without requiring manual environment export in user shell profiles.

### 11.4 Continuous Integration Pipeline Architecture
GitHub Actions workflows (`.github/workflows/ci.yml`) mirror the local developer environment:
- **Standardized Runtime**: Configured with `actions/checkout@v7` and `actions/setup-python@v7` (Node.js 24 native) targeting Python `3.15` across all pipeline stages (`lint`, `unit-tests`, `integration-tests`, and `ui-tests`).
- **Platform Abstraction Guard**: Enforces architectural boundaries (FR-11.1–FR-11.3) by verifying no platform-specific primitives (`secretstorage`, `SSH_AUTH_SOCK`, `XDG_`) leak outside `src/wrench/credentials/`, `src/wrench/core/paths.py`, or `src/wrench/core/ssh_agent.py`.
- **Composite Setup Action (`.github/actions/setup-test-env/action.yml`)**: Installs minimal Ubuntu Qt runtime libraries (`libgl1`, `libegl1`, `libxkbcommon-x11-0`, `libdbus-1-3`, `libfontconfig1`) with GPG-strict APT retry/mirror fallback (`azure.archive.ubuntu.com` -> `archive.ubuntu.com`) and pre-built Python wheels (`--prefer-binary --only-binary=pygit2,PySide6,cffi`) under headless `QT_QPA_PLATFORM: offscreen` execution.

