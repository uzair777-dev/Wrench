# Phase 3 Summary: Remote Operations & Credential Infrastructure

**Status:** Completed  
**Associated SRS Requirements:** FR-4.1 – FR-4.5, FR-11.1 – FR-11.3, NFR Concurrency & Reliability, NFR Performance  
**Associated Planning Documents:** [`implementation-plan.md`](file:///home/uzair/Projects/wrench/dev/planning/implementation-plan.md), [`srs.md`](file:///home/uzair/Projects/wrench/dev/planning/srs.md), [`ARCHITECTURE.md`](file:///home/uzair/Projects/wrench/ARCHITECTURE.md)

---

## 1. Overview & Objectives

Phase 3 delivered the complete remote transport, credential management, and background network operation infrastructure for Wrench:

1. **Secret Service D-Bus Credential Infrastructure (`SecretServiceBackend`)**:
   - Implemented native Secret Service D-Bus integration via `secretstorage` conforming to Freedesktop Secret Service specifications.
   - Support for collection auto-unlocking (`unlock()`), thread-safe locked collection error handling, and environment-aware packaging context detection (`flatpak`, `snap`, `appimage`, `system`).
   - Flatpak permissions configured with `--socket=ssh-auth` and `--talk-name=org.freedesktop.secrets`.

2. **Standalone `git-credential-wrench` Helper**:
   - Built a standalone Git credential helper binary (`git-credential-wrench`) communicating over standard IO per Git's credential protocol.
   - Deterministic multi-account disambiguation: resolves credentials first by explicit repository link (`repo_forge_links`), falling back to unique host matching, and strictly failing closed without guessing when multiple accounts share a host.
   - Read-only WAL SQLite access with locked-retry resilience and empty-stdout/exit-0 protocol adherence.

3. **Deadlock-Free Streaming Git Execution (`run_git_streaming`)**:
   - Implemented concurrent dual-pipe draining threads for `stdout` and `stderr` using `subprocess.Popen`, completely eliminating the classic 64 KiB OS pipe buffer deadlock.
   - Carriage-return `\r` and newline `\n` progress stream parsing capturing stages (`Enumerating`, `Counting`, `Compressing`, `Writing`, `Receiving`, `Resolving`) and percentage completions.
   - Cooperative cancellation via `threading.Event` enforcing graceful termination (`SIGTERM` ➔ 3s grace window ➔ `SIGKILL`).
   - Structured exception classification mapping CLI failures to typed exceptions (`PushRejectedError`, `MergeRequiredError`, `AuthFailedError`, `AuthRequiredError`, `CLITimeoutError`).

4. **Platform-Abstraction Guard (FR-11.1–11.3)**:
   - Strictly isolated all platform-specific dependencies (`secretstorage`, `SSH_AUTH_SOCK`, `XDG_`) to authorized platform modules (`credentials/secret_service.py`, `core/ssh_agent.py`, `core/paths.py`).
   - Automated CI verification guard ensuring 0 unauthorized leaks across all core and UI layers.

5. **Safe Remote Operations & Remotes Management Façade**:
   - `push`: Always uses `--force-with-lease` when force-pushing (never bare `--force`).
   - `pull`: Enforces `--ff-only` to guarantee no implicit, uninspected merge commits mid-pull, surfacing divergence as `MergeRequiredError`.
   - `fetch`: Prunes stale remote-tracking branches (`--prune`) and stores UTC ISO-8601 timestamps in settings.
   - `clone_repo`: Clones into a temporary directory on the destination filesystem, performs an atomic move upon completion, automatically configures credential helper local settings, and cleans up on cancel or error.
   - Remotes Façade: `list_remotes` (instant, non-blocking), `add_remote`, `remove_remote`, `set_remote_url`, and `probe_remotes_async` background reachability probe.
   - **Auto-Configuring Credential Helper on Open**: When opening any existing repository (`engine.open_repo`), local git config automatically configures `credential.helper = wrench` and `credential.useHttpPath = true`.

6. **UI Integration & Remote Resolution Enhancements**:
   - `BusyOperationDialog`: Modal progress tracker with determinate/indeterminate progress and cancellation button.
   - `RemotesDialog`: Repository remote manager with reachability indicators, async refresh (`probe_finished` Qt signal), and automatic background reachability probing.
   - `MainWindow` Wiring: Added **Repository** menu (Fetch, Pull, Push, Remotes...) and intelligent error routing for auth failures, push rejections, and merge divergence.
   - **Dynamic Upstream Tracking Remote Resolution**: `_get_default_remote()` inspects the active branch's configured tracking remote (`branch.<name>.remote` and `branch.upstream`), falling back cleanly to `"origin"` and configured remotes.
   - **Background Reachability on Open**: Opening a repository automatically kicks off non-blocking reachability probing for all configured remotes in a background daemon thread.

7. **Catppuccin Velvet Pastel Design System & Instant Theme Switching**:
   - Implemented the complete **Catppuccin Velvet Pastel** theme system across all application surfaces:
     - **Catppuccin Latte Pastel (Light Mode)**: Warm mist canvas (`#eff1f5`), card bases (`#ffffff`), charcoal slate text (`#4c4f69`), sapphire accents (`#1e66f5`), muted slate subtext (`#7c7f93`).
     - **Catppuccin Mocha Velvet Pastel (Dark Mode)**: Deep twilight slate canvas (`#181825`), deep crust card bases (`#11111b`), frosted white text (`#cdd6f4`), pastel sky accents (`#89b4fa`), soft lavender-gray subtext (`#9399b2`).
   - Centralized theme engine in `src/wrench/ui/theme.py` with **View → Theme** menu options (`Auto`, `Pastel Light`, `Pastel Dark`).
   - Solved Qt container stylesheet palette isolation (`QSplitter`, `QGroupBox`) by implementing recursive descendant palette propagation across all `topLevelWidgets()` and their child widgets.
   - Implemented event recursion protection (`_updating_style`, `_refreshing_theme`, `_updating_display_active`) to eliminate `maximum recursion depth exceeded` when `setStyleSheet` triggers `QEvent.PaletteChange`.
   - Luminance-based detection `is_dark_theme(widget)` evaluating `(Window.lightnessF() + Base.lightnessF()) / 2.0 < 0.5` to eliminate host desktop color scheme mismatches on Linux (KDE Plasma / GNOME).
   - Explicitly bound `TabButton` text colors (`palette(window-text)` on active tabs, `palette(placeholder-text)` on inactive tabs) and added `refresh_theme()` to `TabContainer` and `TabButton`.
   - **Mode-Isolated ChangesTab Styling**: Resolved light mode visibility issues without altering dark mode appearance:
     - Repository dropdown (`repo_combo`): in dark mode, keeps original stylesheet (`color: palette(window-text);`); in light mode, uses explicit `#4c4f69` charcoal text on `#ffffff` popup to prevent white-on-light illegibility.
     - Commit button (`commit_btn`): in dark mode, preserves native Qt button rendering (`setStyleSheet("")`) completely untouched; in light mode, applies Catppuccin Sapphire (`#1e66f5`) with crisp white `#ffffff` text (disabled: `#e6e9ef` with `#7c7f93`), eliminating washed-out flat grey buttons.

8. **Commit Graph Smooth Scrolling & Synchronized DAG Scrollbar**:
   - Configured `CommitGraphWidget` with `ScrollPerPixel` to deliver fluid, continuous horizontal scrolling across table columns without column snapping.
   - Dynamically synchronized Column 0 DAG lane horizontal scrollbar with Column 0's viewport coordinate (`viewport().x() + header.sectionViewportPosition(0)`), translating smoothly to the left as the table scrolls right and hiding cleanly when off-screen or when lanes fit.

---

## 2. Implemented Components & Architecture

### 2.1 Credential Infrastructure (`src/wrench/credentials/`)
- **`SecretServiceBackend` (`secret_service.py`)**:
  - Subclasses `CredentialBackend`.
  - Implements `get_secret(key)`, `store_secret(key, secret)`, and `delete_secret(key)`.
  - Automatic collection unlocking via `secretstorage.collection.create_collection` / `collection.unlock()`.
  - Detailed diagnostic help texts customized for Flatpak sandboxes, desktop keyrings (GNOME Keyring / KWallet), and headless environments.
- **Factory & Detection (`credentials/__init__.py`)**:
  - `get_backend()` singleton factory caching the active platform backend.
  - `detect_packaging_context()` detecting Flatpak (`/.flatpak-info`), Snap (`SNAP`), and AppImage (`APPIMAGE`).

### 2.2 Git Credential Helper (`src/wrench/core/git_credential_helper.py`)
- **CLI Entry Point**: Exposed as `git-credential-wrench` via `pyproject.toml` console scripts.
- **Protocol Handlers**:
  - `get`: Parses `protocol`, `host`, `path`, and `username` from stdin. Resolves credentials via `repo_forge_links` or `forge_accounts`, outputting `username=<user>` and `password=<secret>`.
  - `store` & `erase`: Handled gracefully per protocol.
- **Resilience**: Connects to SQLite database in read-only URI mode (`file:...?mode=ro`) with SQLite busy timeouts and retry loops.

### 2.3 Streaming Git Execution & Remote Operations (`src/wrench/core/`)
- **Streaming Runner (`write_ops.py`)**:
  - `run_git_streaming(repo_path, args, *, timeout=600, on_stderr_line=None, cancel_event=None) -> tuple[int, str, str]`
  - Dual background threads reading `stdout.readline` and `stderr.readline` into buffers concurrently.
  - Progress line parser `_parse_progress(line)` extracting `(stage, percent)`.
- **SSH Agent Encapsulation (`ssh_agent.py`)**:
  - `get_ssh_auth_socket() -> str | None`: Reads `SSH_AUTH_SOCK` from environment without leaking platform calls.
  - `configure_ssh_env(env: dict[str, str]) -> None`: Safely injects the unmodified socket path into subprocess environments.
- **Façade Operations (`engine.py`)**:
  - `push(repo, remote, branch, *, force=False, progress_cb=None, cancel_event=None)`
  - `pull(repo, remote, branch, *, progress_cb=None, cancel_event=None)`
  - `fetch(repo, remote, *, progress_cb=None, cancel_event=None)`
  - `clone_repo(url, dest, *, progress_cb=None, cancel_event=None) -> CloneResult`
  - `list_remotes(repo) -> list[RemoteInfo]`
  - `add_remote(repo, name, url)`
  - `remove_remote(repo, name)`
  - `set_remote_url(repo, name, url)`
- **Failure Classification (`write_ops.py` & `exceptions.py`)**:
  - Non-zero CLI exits map deterministically to typed exceptions:
    - `rejected` ➔ `PushRejectedError`
    - `Not possible to fast-forward` ➔ `MergeRequiredError`
    - `Authentication failed` / `401` / `403` / `Permission denied (publickey)` ➔ `AuthFailedError`
    - `could not read Username` / `Password` / `terminal prompts disabled` ➔ `AuthRequiredError`
    - Timeout expired ➔ `CLITimeoutError`

### 2.4 UI Layer & Dialogs (`src/wrench/ui/`)
- **Background Worker Progress Adapter (`workers.py`)**:
  - Adapted `GitOperationWorker.run()` to accept `(pct, stage)` progress callbacks and emit `Signal(int)` to GUI widgets without breaking existing callers.
- **Busy Modal Dialog (`recovery/busy_dialog.py`)**:
  - `BusyOperationDialog`: Provides progress bar (determinate or indeterminate), status text update, and interactive cancellation triggering `cancel_event.set()`.
- **Remotes Configuration Dialog (`dialogs/remotes_dialog.py`)**:
  - `RemotesDialog`: Table view with columns `Name`, `URL`, `Last Fetch`, and `Reachability`.
  - Operations: `Add Remote` (with name regex & URL validation), `Edit Remote`, `Remove Remote` (with confirmation), and `Refresh Status` (reachability probe via `git ls-remote`).
- **Main Window Remote Wiring (`main_window.py`)**:
  - **Repository Menu**: `Fetch` (`Ctrl+Shift+F`), `Pull` (`Ctrl+Shift+L`), `Push` (`Ctrl+Shift+U`), `Remotes…`.
  - **Async Clone Flow**: Rewrote `_on_clone_repo` to run asynchronously through `run_in_background` with cancellation support.
  - **Error Routing**:
    - `AuthRequiredError`: Prompt explaining credentials are required and naming the host.
    - `AuthFailedError`: Notification that credentials on file were rejected.
    - `PushRejectedError`: Actionable choice offering "Fetch & Retry", "Force Push (with lease)", or "Cancel".
    - `MergeRequiredError`: Actionable choice offering "Merge", "Rebase", or "Cancel".
    - `RemoteNotFoundError`: Opens Remotes dialog.
    - `CloneAbortedError`: Clean dismissal without error alerts.

### 2.5 Theme Engine & Catppuccin Velvet Pastel Styling (`src/wrench/ui/theme.py`)
- **Pastel Palettes**:
  - `create_pastel_light_palette()`: Catppuccin Latte Pastel palette.
  - `create_pastel_dark_palette()`: Catppuccin Mocha Velvet Pastel palette.
- **Application & Descendant Propagation**:
  - `apply_theme(app, mode)`: Sets palette on `app` and recursively propagates to all top-level windows and their child widgets via `findChildren(QWidget)`.
- **Luminance Detection**:
  - `is_dark_theme(widget)`: Computes palette lightness `(Window.lightnessF() + Base.lightnessF()) / 2.0 < 0.5`.
- **Design Tokens**:
  - `DIFF_STYLES`: Additions, deletions, hunk headers, and editor container stylesheets.
  - `BADGE_STYLES`: Status pills (`M`, `A`, `D`, `R`, `?`, `⚠ C`).
  - `CONFLICT_BANNER_STYLES`: Frame and label styles for active merge conflict banners.
  - `SECONDARY_TEXT`: Muted subtext colors.
  - `ACCENT_COLORS`: Warning borders and detached HEAD indicator colors.
  - `COMMIT_STAT_COLORS`: Green `+` additions and red `-` deletions.
- **Theme Lifecycles**:
  - `TabButton`: Recursion-guarded `changeEvent` and `_update_style()` applying `color: palette(window-text)` (active) and `color: palette(placeholder-text)` (inactive).
  - `TabContainer`: `refresh_theme()` method propagating changes to all child tab buttons.
  - `ChangesTab`: `refresh_theme()` re-evaluating mode-isolated `repo_combo` (`_update_repo_combo_theme()`), `commit_btn` (`_update_commit_btn_theme()`), `branch_switcher`, status badges, conflict banner, and secondary labels.
  - `HistoryTab`: `refresh_theme()` forwarding updates to `detail_panel` and requesting graph viewport repaints.
  - `BranchSwitcherWidget`: Adapts to theme changes with `ACCENT_COLORS` and `palette(placeholder-text)`.

### 2.6 Commit Graph Horizontal Smooth Scrolling (`src/wrench/ui/commit_graph/graph_widget.py`)
- **`ScrollPerPixel` Mode**: Configured on `CommitGraphWidget` to replace default per-column step scrolling with fluid pixel scrolling.
- **Dynamic Scrollbar Synchronization**:
  - Dedicated Column 0 horizontal scrollbar tracks Column 0 viewport coordinate: `viewport().x() + header.sectionViewportPosition(0)`.
  - Overrides `scrollContentsBy(dx, dy)` and connects to `valueChanged`, `rangeChanged`, and `header.geometriesChanged`.
  - Bounded by viewport geometry to prevent overlapping the vertical scrollbar, and automatically hidden when Column 0 scrolls off-screen.

---

## 3. Test Coverage & Verification

- **Platform-Abstraction Guard Check**:
  - Executed: `grep -rn "secretstorage\|SSH_AUTH_SOCK\|XDG_" src/wrench --include="*.py" | grep -v -E "credentials/(backend|secret_service|__init__)\.py|core/(paths|ssh_agent)\.py"`
  - Result: **0 violations / Passed**.
- **Credentials & Secret Service Tests** (`tests/unit/credentials/test_secret_service.py`):
  - Secret retrieval, storage, and deletion.
  - Collection unlock workflows and locked error handling.
  - Platform detection and packaging context logic.
- **Credential Helper Tests** (`tests/unit/core/test_git_credential_helper.py`):
  - Helper protocol parsing (`get`, `store`, `erase`).
  - Disambiguation order: exact path link ➔ single-account host match ➔ ambiguous fails closed.
- **Write Operations & Remotes Tests** (`tests/unit/core/test_write_ops_remotes.py` & `test_engine_remotes.py`):
  - Push happy path, non-fast-forward push rejection.
  - Fast-forward pull and diverged pull error classification.
  - Fetch timestamp recording in settings.
  - Deadlock prevention on >64 KiB pipe buffer output.
  - Atomic clone temp-dir handling and cancellation cleanup.
  - Remotes CRUD and reachability probing.
- **UI & Theme Switching Tests** (`tests/unit/ui/test_theme_switching.py`):
  - `test_pastel_palettes`: Verified Catppuccin Latte & Mocha palette colors.
  - `test_is_dark_theme`: Verified luminance-based theme detection.
  - `test_badge_colors`: Verified pastel foreground and background pairs for all 6 change types.
  - `test_diff_widget_theme_switching`: Verified HTML diff rendering and container styling in light and dark modes.
  - `test_repo_combo_stylesheet_and_file_item_badge`: Verified mode-isolated theme styling — dark mode untouched native `commit_btn` (`setStyleSheet("")`) and `palette(window-text)` on `repo_combo`; light mode explicit `#4c4f69` on `repo_combo` and Sapphire `#1e66f5` / `#ffffff` / `#7c7f93` on `commit_btn`, plus badge styling across modes.
  - `test_main_window_theme_menu_and_persistence`: Verified `View → Theme` menu actions and SQLite persistence.
  - `test_tab_button_and_container_theme_refresh`: Verified tab button active and inactive text color updates.
  - `test_changes_tab_palette_propagation`: Verified recursive palette propagation down to `files_list` and `commit_desc_input`.
- **History Tab & Graph Tests** (`tests/unit/ui/test_history_tab.py`):
  - Empty repository rendering, multi-commit rendering, filter search.
  - `test_history_tab_pixel_scroll_and_graph_scrollbar_tracking`: Verified `ScrollPerPixel` mode and Column 0 scrollbar geometry tracking during horizontal table scrolling.
- **UI Dialog Tests** (`tests/unit/ui/test_busy_operation_dialog.py`, `test_remotes_dialog.py`, `test_main_window_remotes.py`):
  - Busy dialog progress updates and cancellation signaling.
  - Remotes table rendering, addition validation, editing, and removal.
  - Repository menu actions, async clone execution, and error routing.
- **Full Test Suite**: **229 passed in 27.76s**.
- **Code Quality**: `bin/wrench-format` and `bin/wrench-lint` pass cleanly across all 118 files with zero errors.
