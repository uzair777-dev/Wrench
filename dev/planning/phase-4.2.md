# Phase 4.2 Summary: Repository Switching UX, Lazy Tabs, Loading States & Auto-Fetch

**Status:** Completed  
**Associated SRS Requirements:** FR-1.17, FR-4.7, NFR Concurrency & Reliability, NFR Performance  
**Associated Planning Documents:** [`implementation-plan.md`](file:///home/uzair/Projects/wrench/dev/planning/implementation-plan.md), [`srs.md`](file:///home/uzair/Projects/wrench/dev/planning/srs.md), [`ui-planning.md`](file:///home/uzair/Projects/wrench/dev/planning/ui-planning.md), [`dev/scratch/TODO.md`](file:///home/uzair/Projects/wrench/dev/scratch/TODO.md) (Items 5 & 6)  

---

## 1. Overview & Objectives

Phase 4.2 delivered responsive repository switching and deferred tab widget instantiation across the UI:

1. **Lazy Tab Construction (`src/wrench/ui/tabs/tab_bar.py`)**:
   - Enhanced `TabMetadata` with `factory: Callable[[], QWidget] | None = None` and `is_loaded: bool = True`.
   - Updated `TabContainer.add_tab` to accept a callable factory and an `activate: bool = True` parameter. When passed a callable and `activate=False`, creates a lightweight `QFrame` placeholder (`accessibleName="not loaded"`) and defers widget construction.
   - Added `TabContainer.ensure_loaded(index: int) -> QWidget | None` to materialise the real widget on demand, swapping out the placeholder in the `QStackedWidget` and invoking the factory exactly once.
   - Hooked `TabContainer.set_current_index` to invoke `ensure_loaded(index)` before switching.
   - Preserved all existing deduplication, pinning, unpinning, and closing behaviors without forcing lazy tabs to materialise prematurely.

2. **Non-Modal Loading Overlay (`src/wrench/ui/widgets/loading_overlay.py`)**:
   - Implemented `SpinnerWidget`, a lightweight arc-rotating spinner driven by a 40ms `QTimer` that stops automatically when hidden to consume zero CPU when idle.
   - Implemented `TabLoadingOverlay`, parented over `TabContainer._stack` with a message label and spinner.
   - Exposed `TabContainer.show_loading(repo_name)` and `TabContainer.hide_loading()` proxy methods.
   - Added `resizeEvent` on `TabContainer` to ensure the overlay stays locked to the stack geometry.

3. **Switch Pipeline & Generation Counter (`src/wrench/ui/main_window.py`)**:
   - Added `_repo_switch_generation: int = 0` counter to `MainWindow`.
   - Refactored `_on_repo_changed` into an asynchronous-friendly pipeline: bumps generation counter to invalidate stale background results, displays non-modal loading overlay, refreshes active tab first, materialises only loaded tabs (skipping unloaded lazy placeholders), hides overlay, runs open-time forge link resolution, and triggers auto-fetch.
   - Guaranteed `hide_loading()` is called in both success and exception paths to prevent stuck overlays.

4. **Background Auto-Fetch on Open/Switch (FR-4.7, `src/wrench/ui/main_window.py`)**:
   - Implemented `_maybe_auto_fetch(gen)` triggered at the end of `_on_repo_changed` after forge link resolution.
   - Resolves the default remote (`_get_default_remote()`) and executes `engine.fetch` in a background worker via `run_in_background`.
   - Generation guard in callbacks: `_on_auto_fetch_finished` and `_on_auto_fetch_failed` discard results if `gen != self._repo_switch_generation`.
   - Quiet error handling: network or authentication errors produce only a transient 5-second message in `statusBar().showMessage()`. Never opens modal dialogs or error popups.
   - Setting persistence: reads `repo.auto_fetch_on_open` from SQLite app settings (defaults to enabled/`true`).
   - Single-source setter: `_set_auto_fetch(enabled)` centralizes setting writes.

5. **Repository Menu Toggle (`src/wrench/ui/main_window.py`)**:
   - Added a checkable action "Fetch automatically when opening a repository" (`act_auto_fetch`) to the Repository menu.
   - Synchronised check state on menu creation and dynamically via `repo_menu.aboutToShow.connect(self._sync_auto_fetch_action)`.
   - Used `blockSignals(True)` during sync to prevent signal loops.

6. **Session Restore Refactoring (`src/wrench/ui/main_window.py`)**:
   - Updated `_restore_session_state` to register `pr_list`, `issues_list`, `pr_detail`, and `issue_detail` tabs as lazy factory closures with `activate=False`.
   - Used explicit default-argument capture (e.g. `repo=tab_repo`, `remote=parts[0]`, `pr_id=parts[1]`) to eliminate late-binding closure bugs.
   - Preserved eager construction for pre-existing singleton widgets (`changes`, `history`, `snapshots`).
   - At end of restore, activated only the single saved active tab via `set_current_index(idx)`.

---

## 2. Test Matrix & Verification

### Unit & UI Tests
- `tests/ui/test_lazy_tabs.py`: 9 test cases covering:
  - Placeholder creation and `is_loaded=False` for factory tabs
  - Materialisation on activation (`set_current_index`) invoking factory once
  - Double-activation idempotence (factory never invoked second time)
  - `ensure_loaded` return value
  - Eager tab backward compatibility
  - Deduplication without premature tab materialisation
  - Pinning/unpinning without premature materialisation
  - Loading overlay show/hide and visibility states
  - Session restore deferred construction of forge tabs
- `tests/ui/test_auto_fetch.py`: 11 test cases covering:
  - Default auto-fetch enabled (`_is_auto_fetch_enabled` returns `True`)
  - Setting disabled when `repo.auto_fetch_on_open` is `"false"`
  - `_set_auto_fetch` persistence in SQLite database
  - `_sync_auto_fetch_action` menu toggle sync without firing signal
  - Auto-fetch decision tree: disabled skips fetch
  - Auto-fetch decision tree: missing repository skips fetch
  - Auto-fetch decision tree: missing default remote skips fetch
  - Auto-fetch decision tree: enabled repository with remote triggers `engine.fetch`
  - Generation counter: stale switch discards successful fetch
  - Generation counter: stale switch discards failed fetch
  - Transient status bar message on fetch failure (no modal dialog)
- `tests/ui/test_ui_components.py`: All 15 existing UI component tests pass unmodified.
- Full CI test suite: **458/458 passed** in 69.69s.
- Lint suite: Ruff and Black pass with **zero errors**.
