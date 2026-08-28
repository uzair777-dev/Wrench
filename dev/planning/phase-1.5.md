# Phase 1.5 Summary: UI Shell Overhaul & Hybrid Navigation

**Status:** Completed  
**Associated SRS Requirements:** FR-1.1 – FR-1.7, FR-2.1, FR-2.2, FR-4.1, FR-6.1, FR-6.2, FR-10.6, NFR Accessibility, NFR Localization  
**Associated Planning Document:** [`ui-planning.md`](file:///home/uzair/Projects/wrench/dev/planning/ui-planning.md)

---

## 1. Overview & Objectives

Phase 1.5 replaced the MVP 3-pane `QSplitter` layout with a modern, dynamic, tabbed desktop interface:
1. **Hybrid Tab System & Shell**: Implemented a custom `TabBar` and `TabContainer` supporting vertical (sidebar) and horizontal (top bar) orientations, pinned singleton category tabs, closable dynamic detail tabs, per-repo deduplication, and an add (`+`) menu.
2. **Repository Selector Dropdown**: Migrated repository selection from a static sidebar list into a flush, borderless `QComboBox` at the top of the Changes tab, complete with auto-locate recovery for moved or deleted repository paths.
3. **Branch Indicator / Switcher Widget**: Built an interactive `BranchSwitcherWidget` (`🌿 main ▾` / `🔗 HEAD detached at {sha}`) with search filtering, safe branch switching (Stash & Switch / Switch Anyway / Cancel), and right-click branch management (create, rename, delete).
4. **Redesigned Changes Tab**: Unified the previous two-list "Staged" / "Unstaged" layout into a single, unified changed files list with change badges (`M`, `A`, `D`, `R`, `?`, `⚠ C`), path tooltips, tri-state select-all checkbox, and comprehensive context actions.
5. **Commit Section**: Designed an intuitive commit box featuring forge account picker icon, 72-character soft limit visual cues, multi-line description editor, amend toggle with previous commit pre-filling, and dynamic commit button labels.
6. **History Tab Skeleton**: Established the Phase 2 commit graph slot, top search and filter bar (with 300ms debouncing for author, message, path, and date filters), unborn branch empty states, and hidden detail panel slot.
7. **Main Window Shell Rewrite**: Rebuilt `MainWindow` with native `QMenuBar` (File, Edit, View, Help), geometry persistence, tab orientation persistence, quit confirmation guards for unsaved commit messages, and clean lifecycle management.
8. **Sidebar Deprecation & Test Updates**: Cleanly deprecated and deleted `src/wrench/ui/sidebar/`, updated imports across the codebase, and added component tests for all new widgets.

---

## 2. Implemented Components & Architecture

### 2.1 Hybrid Tab Navigation System (`src/wrench/ui/tabs/tab_bar.py`)
- **`TabContainer` & `TabButton`**:
  - **Orientation Modes**: Dynamically toggles between `Qt.Vertical` (left tab strip, default) and `Qt.Horizontal` (top tab bar) via `View → Toggle Tab Orientation` (`Ctrl+Shift+T`), persisted in `app_settings`.
  - **Pinned vs. Closable Tabs**: Index 0 is permanently pinned to the Changes tab (non-closable). Other tabs feature hover-activated `×` close buttons.
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
    - In-memory per-repo draft persistence across repository switches.
  - **Integrated DiffView**: Right-column diff viewer with binary file detection and clean-state programming quotes.
  - **Staging Logic Bridge**: Synchronizes index state with checked files at commit time without overwriting line-level staging.

### 2.4 History Tab Skeleton (`src/wrench/ui/tabs/history_tab.py`)
- **`HistoryTab`**:
  - **Search & Filter Bar**: Header layout with commit message search, author filter dropdown, file/path filter input, and clear button, debounced at 300ms via `QTimer`.
  - **Graph Container**: Swappable container ready to host Phase 2's `CommitGraphWidget`.
  - **Unborn Branch Empty State**: Centered placeholder `"No history yet — Make your first commit to see the branch graph here."`
  - **Detail Panel Slot**: Hidden slide-in slot reserved for Phase 2 commit inspection.
  - **Signal Coordination**: Resets and updates author lists on `repo_changed` signals.

### 2.5 Main Window Shell Rewrite (`src/wrench/ui/main_window.py`)
- **`MainWindow`**:
  - Native `QMenuBar` with **File** (New, Open, Clone, Close, Quit), **Edit** (Undo, Redo, Cut, Copy, Paste, Select All, Stash, Pop Stash, Git Identity), **View** (Toggle Tab Orientation), and **Help** (About, Report Bug).
  - State persistence: Window geometry and tab orientation stored in `app_settings` via SQLite.
  - Safe quit guards: Prompts user confirmation if an uncommitted commit draft is in progress or background operations are running.
  - Status bar tracking opened repository name and active branch.

### 2.6 Sidebar Deprecation & Cleanup
- Removed `src/wrench/ui/sidebar/repo_list.py` and `src/wrench/ui/sidebar/__init__.py`.
- Cleaned up obsolete imports across the codebase.

---

## 3. Verification & UI Component Tests

Updated `tests/ui/test_ui_components.py` with full coverage of the new architecture:
- **`TestTabContainer`**: Validates pinning of Changes tab, closable tabs removal, orientation toggling, and per-repo deduplication.
- **`TestBranchSwitcherWidget`**: Validates branch text formatting and repository connection.
- **`TestChangesTab`**: Validates repository dropdown population and commit button enabling/disabling logic.
- **`TestHistoryTab`**: Validates filter bar and placeholder container rendering.
- **`TestMainWindow`**: Validates window initialization, menu bar creation, and tab container integration.
- **Syntax Compilation**: Verified clean compilation across all new modules via `python3 -m py_compile`.
