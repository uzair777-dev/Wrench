# Phase 1.5 Summary: UI Shell Overhaul & Hybrid Navigation

**Status:** Completed  
**Associated SRS Requirements:** FR-1.1 – FR-1.7, FR-2.1, FR-2.2, FR-4.1, FR-6.1, FR-6.2, FR-10.6, NFR Accessibility, NFR Localization  
**Associated Planning Document:** [`ui-planning.md`](file:///home/uzair/Projects/wrench/dev/planning/ui-planning.md)

---

## 1. Overview & Objectives

Phase 1.5 replaced the MVP 3-pane `QSplitter` layout with a modern, dynamic, tabbed desktop interface:
1. **Hybrid Tab System & Shell**: Implemented a custom `TabBar`, `TabStripWidget`, and `TabContainer` supporting vertical (sidebar) and horizontal (top bar) orientations, dynamic tab pinning/unpinning, drag-and-drop tab reordering, closable dynamic detail tabs, per-repo deduplication, and an add (`+`) menu.
2. **Repository Selector Dropdown**: Migrated repository selection from a static sidebar list into a flush, borderless `QComboBox` at the top of the Changes tab, complete with auto-locate recovery for moved or deleted repository paths.
3. **Branch Indicator / Switcher Widget**: Built an interactive `BranchSwitcherWidget` (`🌿 main ▾` / `🔗 HEAD detached at {sha}`) with search filtering, safe branch switching (Stash & Switch / Switch Anyway / Cancel), and right-click branch management (create, rename, delete).
4. **Redesigned Changes Tab**: Unified the previous two-list "Staged" / "Unstaged" layout into a single, unified changed files list with change badges (`M`, `A`, `D`, `R`, `?`, `⚠ C`), path tooltips, tri-state select-all checkbox, and comprehensive context actions.
5. **Commit Section**: Designed an intuitive commit box featuring forge account picker icon, 72-character soft limit visual cues, multi-line description editor, amend toggle with previous commit pre-filling, and dynamic commit button labels.
6. **History Tab Skeleton**: Established the Phase 2 commit graph slot, top search and filter bar (with 300ms debouncing for author, message, path, and date filters), unborn branch empty states, and hidden detail panel slot.
7. **Main Window Shell Rewrite & Session Engine**: Rebuilt `MainWindow` with native `QMenuBar` (File, Edit, View, Help), 1000ms debounced auto-save session state engine, window geometry persistence, per-repo draft persistence, quit confirmation guards for unsaved commit messages, and clean lifecycle management.
8. **Visible Section Dividers & Refined Aesthetics**: Added subtle 1px divider lines between the tab strip sidebar/topbar and content area, `QSplitter` divider handles with hover highlight, and dark/light adaptive diff viewer styling.
9. **Sidebar Deprecation & Comprehensive Tests**: Cleanly deprecated and deleted `src/wrench/ui/sidebar/`, updated imports across the codebase, and added component tests for all new widgets and lifecycle flows.

---

## 2. Implemented Components & Architecture

### 2.1 Hybrid Tab Navigation System (`src/wrench/ui/tabs/tab_bar.py`)
- **`TabContainer` & `TabButton`**:
  - **Orientation Modes**: Dynamically toggles between `Qt.Vertical` (left tab strip, default) and `Qt.Horizontal` (top tab bar) via `View → Toggle Tab Orientation` (`Ctrl+Shift+T`), persisted in `app_settings`.
  - **Dynamic Tab Model & Pinning**: All tabs are dynamic. Right-click context menu provides `Pin Tab` / `Unpin Tab`, `Close Tab`, `Close Other Tabs`, and `Close Tabs to the Right/Below`. Pinned tabs show a `📌` badge prefix and hide the `×` close button.
  - **Drag-and-Drop Tab Reordering**:
    - `TabButton` captures mouse drag motions via `installEventFilter` and initiates `QDrag` with visual pixmap snapshots.
    - `TabStripWidget` implements drag target tracking (`dragEnterEvent`, `dragMoveEvent`, `dragLeaveEvent`, `dropEvent`) and renders a 2px visual insertion line in `paintEvent`.
    - `move_tab(from_index, to_index)` enforces the pinned grouping constraint (pinned tabs reorder among pinned tabs; unpinned tabs reorder among unpinned tabs).
    - Active tab focus is retained during reordering and triggers `tabs_mutated` for debounced auto-save persistence.
  - **Category Tabs (Singletons)**: `Changes`, `History`, `PR List`, `Issues List` are singletons per repository.
  - **Dynamic Detail Tabs**: Supports parallel tabs for specific entities (e.g. `PR #42`, `Issue #17`).
  - **Deduplication Rule**: Enforces tab identity `(tab_type, repo_path, entity_id)` — attempting to open an existing tab brings it to focus rather than spawning duplicates.
  - **Category Add Menu (`+`)**: Trailing tool button displaying a dropdown of unopened category tabs.
  - **Keyboard Navigation**: `Ctrl+1` through `Ctrl+9` shortcuts for instant tab switching.

### 2.2 Branch Indicator / Switcher (`src/wrench/ui/widgets/branch_switcher.py`)
- **`BranchSwitcherWidget`**:
  - Displays active branch name with icon (`🌿 main ▾`).
  - **Detached HEAD Support**: Displays `🔗 HEAD detached at {short_sha} ▾` with amber warning highlighting.
  - **Unborn Branch Support**: Displays `🌿 {branch} (initial)` in muted color for fresh repositories.
  - **Branch Picker Popup (`BranchPickerPopup`)**: Searchable/filterable dialog listing local branches on top and remote tracking branches (`☁️ origin/...`) below.
  - **Uncommitted Changes Guard**: Prompting dialog with `Stash & Switch`, `Switch Anyway`, or `Cancel` when switching branches with dirty working trees.
  - **Context Menu**: Right-click actions for `Create New Branch…`, `Rename Branch…`, and `Delete Branch…`.

### 2.3 Redesigned Changes Tab (`src/wrench/ui/tabs/changes_tab.py`)
- **`ChangesTab` & `FileListItemWidget`**:
  - **Repository Selector**: Flush/borderless `QComboBox` populated from `repo_registry.list_repos()`, sorted by `last_opened_at DESC`.
  - **Missing Repo Recovery**: Detects missing repositories (`is_missing=1`), rendering them with `⚠️ {name} (missing)` and prompting with a `Locate / Remove / Cancel` dialog.
  - **Merge Conflict Banner**: Persistent banner when `RepoStatus.has_conflicts` is active with a `Resolve…` trigger.
  - **Unified Changed Files List**: Single `QListWidget` displaying all changed files (staged, unstaged, untracked) with status badges (`M`, `A`, `D`, `R`, `?`, `⚠ C`).
  - **Tri-State Select-All Checkbox**: Header checkbox cycling `Unchecked ➔ All Checked ➔ All Unchecked`, with real-time count badge (`☑ N files`).
  - **File Context Actions**: Right-click menu for `Stage File`, `Unstage File`, `Discard Changes…` (with confirmation), `Copy Relative Path`, and `Copy Absolute Path`.
  - **Commit Box**:
    - Account avatar button (`👤`) with tooltip and account menu.
    - Single-line summary input with 72-character soft limit border warning.
    - Multi-line description input.
    - Amend toggle checkbox pre-filling summary and body from the latest commit.
    - Dynamic commit button (`Commit to {branch}`, `Amend commit on {branch}`, `Commit on detached HEAD`, `Create initial commit`), enabled only when a message is provided and files are selected.
  - **Per-Repository Selections & Draft State**:
    - `get_current_repo_state()` and `restore_repo_state()` save and restore active file diff selection, checked files list, commit message, description, and amend toggle per repository.
    - `save_splitter_state()` and `restore_splitter_state()` preserve user-adjusted column proportions.
  - **Integrated DiffView**: Right-column diff viewer with hunk-staging support, binary file detection, and theme-adaptive dark/light styling.
  - **Staging Logic Bridge**: Synchronizes index state with checked files at commit time without overwriting line-level staging.

### 2.4 History Tab Skeleton (`src/wrench/ui/tabs/history_tab.py`)
- **`HistoryTab`**:
  - **Search & Filter Bar**: Header layout with commit message search, author filter dropdown, file/path filter input, and clear button, debounced at 300ms via `QTimer`.
  - **Graph Container**: Swappable container ready to host Phase 2's `CommitGraphWidget`.
  - **Unborn Branch Empty State**: Centered placeholder `"No history yet — Make your first commit to see the branch graph here."`
  - **Detail Panel Slot**: Hidden slide-in slot reserved for Phase 2 commit inspection.
  - **Signal Coordination**: Resets and updates author lists on `repo_changed` signals.

### 2.5 Main Window Shell & GUI Session Persistence Engine (`src/wrench/ui/main_window.py`)
- **`MainWindow`**:
  - Native `QMenuBar` with **File** (New, Open, Clone, Close, Quit), **Edit** (Undo, Redo, Cut, Copy, Paste, Select All, Stash, Pop Stash, Git Identity), **View** (Toggle Tab Orientation), and **Help** (About, Report Bug).
  - **Debounced Auto-Save Engine**: 1000ms timer (`_auto_save_timer`) coalescing all UI events (typing, toggling checkboxes, reordering tabs, switching repos, resizing splitters) into an atomic JSON snapshot in `app_settings` (`ui.session_state`).
  - **Crash & Force-Quit Resilience**: Continuous background auto-save prevents lost work on unexpected termination; synchronous flush on `closeEvent(event)` ensures zero state loss on standard exit.
  - **State Schema (`ui.session_state`)**:
    ```json
    {
      "window": {
        "geometry": "<hex>",
        "state": "<hex>",
        "tab_orientation": "vertical"
      },
      "tabs": [
        {"type": "changes", "label": "Changes", "repo_path": "/path/to/repo", "is_pinned": true},
        {"type": "history", "label": "History", "repo_path": "/path/to/repo", "is_pinned": false}
      ],
      "active_tab_index": 0,
      "active_repo_path": "/path/to/repo",
      "repos_state": {
        "/path/to/repo": {
          "active_file": "src/main.py",
          "checked_files": ["src/main.py", "README.md"],
          "commit_summary": "feat: add tab reordering",
          "commit_description": "Implements drag and drop tab reordering.",
          "is_amend": false,
          "splitter_state": "<hex>"
        }
      }
    }
    ```
  - **Startup Guard**: `_is_restoring` flag suppresses mutation signals during startup restore so saved drafts and selections are not overwritten.
  - Safe quit guards: Prompts user confirmation if an uncommitted commit draft is in progress or background operations are running.
  - Status bar tracking opened repository name and active branch.

### 2.6 Section Dividers & Visual Hierarchy
- Subtle 1px divider lines added to `TabStripWidget` (`border-right` in vertical mode, `border-bottom` in horizontal mode).
- `QSplitter::handle` in `ChangesTab` styled with 1px width, divider line color, and interactive hover highlight.
- Dark/light mode theme adaptive contrast in `DiffView`.

### 2.7 Sidebar Deprecation & Cleanup
- Removed `src/wrench/ui/sidebar/repo_list.py` and `src/wrench/ui/sidebar/__init__.py`.
- Cleaned up obsolete imports across the codebase.

---

## 3. Verification & UI Component Tests

Updated `tests/ui/test_ui_components.py` with comprehensive coverage of all UI components and session persistence:
- **`TestTabContainer`**:
  - `test_pinned_and_closable_tabs`: Verifies pinned tabs hide close buttons and unpinned tabs show close buttons.
  - `test_pin_and_unpin_tab`: Verifies toggling tab pinning status and pin badge updates.
  - `test_close_other_and_right_tabs`: Verifies context actions for closing other tabs and closing tabs to right/below.
  - `test_deduplication_rule`: Verifies `(tab_type, repo_path, entity_id)` identity deduplication.
  - `test_orientation_toggle`: Verifies vertical and horizontal orientation switches.
  - `test_move_tab_and_focus_retention`: Verifies tab reordering updates tab positions and keeps the active tab focused.
  - `test_reorder_with_pinned_tabs`: Verifies reordering pinned tabs within the pinned group.
- **`TestBranchSwitcherWidget`**: Validates branch text formatting and repository connection.
- **`TestChangesTab`**: Validates repository dropdown population and commit button enabling/disabling logic.
- **`TestHistoryTab`**: Validates filter bar and placeholder container rendering.
- **`TestMainWindow`**:
  - `test_main_window_initialization`: Validates window setup, menu bar creation, and tab container integration.
  - `test_session_state_persistence_and_restore`: Validates full round-trip session persistence (geometry, tabs, active repo, draft text, checkboxes, splitter state).
  - `test_auto_save_debounce_coalescing`: Validates that rapid UI changes coalesce into a single write after 1000ms.
  - `test_corrupt_session_state_fallback`: Validates fallback to defaults when stored session state is malformed.
- **CI Test Suite**: All **66/66 unit and UI tests** passing with clean Ruff and Black formatting via `bin/wrench-ci-check`.
