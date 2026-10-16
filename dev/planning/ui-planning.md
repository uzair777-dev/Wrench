# UI Planning — Wrench (`dev/planning/ui-planning.md`)

**Version:** 0.6 (v2 Complete UI/UX Specification: Virtualized Diff Engine, Multi-Hosting Mirror DAG, 2-Tier Help & Zero-Shortcut Security) **Status:** Authoritative UI Specification for v1 and v2 (`VP-0`–`VP-23`) **Purpose:** Detailed UI and UX specification for [Wrench](https://github.com/uzair777-dev/Wrench)'s native Linux desktop interface. Written to be deterministically executable by a lower-tier coding model — every layout, widget hierarchy, signal connection, keyboard shortcut, zero-impact disable gate, and performance optimization is spelled out explicitly so the model never improvises.

**Companion Documents:**

- [`srs.md`](https://github.com/uzair777-dev/Wrench/blob/master/dev/planning/srs.md) — source of every `(SRS FR-x.y)` and `(NFR-z)` tag; priorities (`M`/`S`/`D`) and setting keys live there.  
- [`implementation-plan.md`](https://github.com/uzair777-dev/Wrench/blob/master/dev/planning/implementation-plan.md) — v1 phases building baseline surfaces (§5; §12 owns v1 execution order).  
- [`v2-implementation-plan.md`](https://github.com/uzair777-dev/Wrench/blob/master/dev/planning/v2-implementation-plan.md) — v2 phases (`VP-0`..`VP-23`). Every phase in `v2-implementation-plan.md` links back to an exact `§x.y` section in this file.  
- [`../ARCHITECTURE.md`](https://github.com/uzair777-dev/Wrench/blob/master/ARCHITECTURE.md) — as-built 3-tier architecture (`UI -> core.engine / forge.registry / storage.settings_registry -> backends`).

## 0\. Reading Guide & Mandatory Rules for Coding Models

This document is organized from the outermost window container inward:

1. **§1 — Window Chrome** (Title bar, Menu bar, Global Status Bar, Global Action Undo Toast, Focus/Zen Mode, Quick-Settings Pin Popover)  
2. **§2 — Tab System** (Hybrid singleton/detail tabs, Lazy Tab Instantiation, Worktree/Submodule tabs)  
3. **§3 — Changes Tab** (3-column staging/commit/diff layout, Diff Minimap, Sticky Function Headers, CLI Dry-Run Preview, Hook Drawer, Skip-Worktree Panel)  
4. **§4 — History Tab** (Search/Pickaxe filters, Virtualized `CommitGraphWidget`, Hover X-Ray Cards, Signature Badges, Bisect Overlay, Slide-In Detail Panel)  
5. **§5 — Cross-Cutting Concerns & Mandatory UI Optimizations** (Themes, Shortcuts, `Ctrl+K` Command Palette, a11y, i18n, and **6 Non-Negotiable UI Optimization Patterns**)  
6. **§6 — Secondary UI Surfaces (`§6.1`–`§6.24`)** (Detailed widget specs for every dialog, panel, and v2 surface, including the **Modular Settings Center in `§6.11`** with Lazy Page Loading, 150ms Debounced Auto-Save, and Delta-Only Settings Undo/Redo)  
7. **§7 — Complete File/Component Mapping** (Exact file paths under `src/wrench/ui/`)  
8. **§8 — Sequential UI Implementation Order** (v1 Steps 1–25 \+ v2 Steps 26–49 mapped 1-to-1 to `VP-0`..`VP-23`)

### Mandatory UI Rules for Lower-Tier Models (DO NOT VIOLATE)

1. **Zero Direct Backend Imports in `src/wrench/ui/**`:** UI files MUST NEVER import `pygit2`, `subprocess`, `sqlite3`, or `httpx`. Always call `self.engine`, `self.forge_registry`, or `self.settings`.  
2. **Every UI Element Obeys `SettingsRegistry` Live Signals:** Every optional surface, toolbar button, badge, gutter, or tab MUST subscribe to `self.settings.setting_changed.connect(self._on_setting_changed)` and call `self.setVisible(self.settings.get_bool("<key>", self.repo_path))` so turning a feature off in Settings (`Ctrl+,`) hides it immediately without leaving blank gaps or requiring an app restart.  
3. **Contextual Gear (`⚙`) Jump-to-Setting Button:** Every panel header and dialog title bar MUST include a compact `16x16` `QToolButton("⚙")` with tooltip `"Configure <Feature> in Settings..."` that calls `MainWindow.open_settings_at_category("<Category Name>", highlight_key="<key>")`.  
4. **Apply All §5.5 Optimizations:** Never instantiate hidden tabs or unselected Settings pages eagerly; always use lazy factory instantiation, debounced auto-save, bounded ring buffers, and worker generation tokens as specified in §5.5.

## 1\. Window Chrome (`SRS FR-1.1`, `FR-8.8`–`8.11`, `FR-12.1`)

### 1.1 Title Bar & Window Frame

- Native OS window frame (`QMainWindow`) with dynamic title:  
  - Normal repo: `Wrench — {repo_name} ({branch_name})`  
  - Linked worktree (`VP-3`): `Wrench — {repo_name} [worktree: {worktree_folder}] ({branch_name})`  
  - Active sequencer/bisect state (`VP-1`, `VP-2`, `VP-19`): `Wrench — {repo_name} ({branch_name} | REBASING 2/5)`  
- Persists window geometry (`size`, `pos`, `isMaximized`, splitter ratios) in `SettingsRegistry` via a `250ms` debounced `resizeEvent`/`moveEvent` timer so dragging window edges never hammers SQLite.

### 1.2 Menu Bar (`QMenuBar`)

Eight top-level menus, where every v2 action dynamically hides if its feature toggle in `SettingsRegistry` is `False`:

- **File:** `Open Repository... (Ctrl+O)`, `Clone Repository... (Ctrl+Shift+O)`, `Discover Repositories...`, `Workspace Sessions ▸` (`Save Current Session...`, `Manage Sessions...`, recent sessions list — gated by `workspace.named_sessions.enabled`), `Quick Settings Popover (Ctrl+Shift+,)`, `Settings... (Ctrl+,)`, `Quit (Ctrl+Q)`.  
- **Edit:** `Undo Last Git Action (Ctrl+Z)` (wired to `core/snapshots.py` / `UndoManager`), `Undo Last Setting Change (Ctrl+Alt+Z)`, `Command Palette... (Ctrl+K)`, `Find in Diff (Ctrl+F)`, `Search Commits (Ctrl+Shift+F)`.  
- **View:** `Focus / Zen Mode (F11)` (collapses left columns/sidebars to maximize diff/merge area — gated by `ui.zen_mode.enabled`), `Toggle Tab Orientation (Vertical/Horizontal)`, `Toggle Split/Unified Diff (Ctrl+D)`, `Toggle Activity Dock (Ctrl+\`)`,` Zoom In (Ctrl+=)`,` Zoom Out (Ctrl+-)`,` Reset Zoom (Ctrl+0)`,` Refresh (F5)\`.  
- **Repository:** `Fetch (Ctrl+Shift+T)`, `Pull (Ctrl+Shift+P)`, `Push (Ctrl+P)`, `Remotes...`, `Sparse-Checkout Directories...` (`VP-16`, gated by `monorepo.sparse_checkout_ui.enabled`), `Git Maintenance ▸` (`Run Maintenance Now`, `Write Commit-Graph`), `Export Patch Series (format-patch)...` & `Apply Patch Mailbox (git am)...` (`VP-23`, gated by `patches.ui.enabled`), `Safety Snapshots & Backups...`.  
- **Branch:** `New Branch... (Ctrl+B)`, `New Stacked Branch on Top...` (`VP-20`, gated by `stacks.enabled`), `Switch Branch...`, `Merge into Current Branch...`, `Rebase Current Branch...`, `Interactive Rebase...` (`VP-2`, gated by `rebase.interactive_ui.enabled`), `Restack Branch Chain (--update-refs)` (`VP-20`, gated by `stacks.enabled`), `Start Git Bisect...` (`VP-19`, gated by `bisect.ui.enabled`).  
- **Stash:** `Stash All Changes (Ctrl+S)`, `Stash Staged Only (--staged)` (`VP-22`), `Stash Unstaged Only (--keep-index)` (`VP-22`), `Pop Latest Stash`, `Stash Manager...`.  
- **Tools:** `3-Way Merge Tool...`, `Worktrees Manager...` (`VP-3`, gated by `worktrees.enabled`), `Submodules Manager...` (`VP-4`, gated by `submodules.enabled`), `LFS Locks & Patterns...` (`VP-12`, gated by `lfs.enabled`), `Reflog Time-Travel Inspector...` (`VP-11`, gated by `reflog.inspector_ui.enabled`), `Account & SSH Routing Rules...` (`VP-8`), `Custom Actions...` (`VP-23`, gated by `custom_actions.enabled`).  
- **Help:** `Keyboard Shortcuts Reference (Ctrl+?)`, `Documentation`, `Report an Issue`, `About Wrench`.

### 1.3 Global Status Bar (`SRS FR-1.1`, `FR-14.2`)

- **Left Zone:** Current background operation spinner \+ witty/informative progress text (`ui.humor_lines` toggleable; when `False`, displays strictly clinical Git command strings like `Running git fetch origin...`).  
- **Center Zone:** Ahead/Behind pill (`↑2 ↓1`), active sequencer/bisect badge (`[BISECTING: ~3 steps left]`), and active Sparse-Checkout indicator (`[Sparse: 4 dirs]`).  
- **Right Zone:**  
  - **Quick-Settings Pin Button (`★ Quick Toggles`):** Opens a lightweight floating `QMenu`/`QFrame` listing any settings the user has starred/pinned in `SettingsDialog` (`§6.11`) for 1-click toggling without opening the full Preferences dialog.  
  - **Activity Log Toggle (`>_ Log`)**, **Theme Toggle (`☀/☾`)**, and **Memory/Watcher Badge** (optional diagnostic indicator gated by `ui.show_perf_badge`: shows `.git-only watch mode` when monorepo fallback is active).

### 1.4 Non-Intrusive Action & Undo Toast Banner (`src/wrench/ui/widgets/undo_toast.py`)

- **Purpose:** Gives users immediate confidence that any mutation can be undone with 1 click.  
- **Behavior:** Whenever a mutating operation completes (`Commit`, `Amend`, `Reset`, `Rebase`, `Cherry-Pick`, `Stash Push/Drop`, `Discard Hunk`), a floating pill toast appears centered `16px` above the Global Status Bar for `8000ms` (configurable via `ui.undo_toast.duration_ms`, or disabled completely via `ui.undo_toast.enabled`):  
  - Text: `"Committed 4f9a2b1 ('Fix parser edge case')"` \+ Button: **`[Undo (Ctrl+Z)]`** \+ Button: **`[Show CLI]`** \+ Dismiss `✕`.  
  - Clicking **`[Undo]`** invokes `engine.undo_last_action(repo_path)` (restoring the pre-op safety snapshot from `core/snapshots.py` or running `git reset --soft HEAD~1` if the last action was a commit).  
- **Optimization Reminder for Models:** Reuse a single `UndoToastWidget` instance attached to `MainWindow` and reset its `QTimer` on new events; NEVER allocate and leak new `QWidget` toast instances per Git operation.

## 2\. Tab System (`SRS FR-1.1`, `FR-1.13`, `FR-1.15`)

### 2.1 Hybrid Tab Model & Multi-Worktree Tabs

- **Category Singletons per Repository/Worktree:** `Changes`, `History`, `Pull Requests` (hidden if `forge.enabled == False`), `Issues` (`VP-7`, hidden if `forge.issues_tab.enabled == False` or `forge.enabled == False`).  
- **Dynamic Detail Tabs:** Individual PR detail (`PR #42`), Issue detail (`Issue #19`), Blame/Line-History viewer (`Blame: engine.py`), or Snapshot comparison. Strictly de-duplicated by `(repo_path, tab_type, entity_id)`.  
- **Worktree Tab Binding (`VP-3`):** Opening a linked worktree opens a top-level workspace tab badged with `[WT: {branch}]` and a full-path hover tooltip (`[GitHub Desktop Issues](https://github.com/desktop/desktop/issues)`).

### 2.2 Mandatory Optimization: Lazy Tab Instantiation (`QStackedWidget` Factory Pattern)

- **Rule for Lower-Tier Models:** When opening a repository in `MainWindow`, instantiate **ONLY** the initially visible tab (`ChangesTab`). Wrap `HistoryTab`, `PRListTab`, and `IssuesTab` in a `LazyTabContainer(factory_callable)` inside `QStackedWidget` so their widgets, models, and background queries are constructed **only on the first `currentChanged` signal selecting that tab**. This cuts initial repository-open latency by \>60% and saves \~45MB of idle Qt widget allocations.

## 3\. Changes Tab (`SRS FR-2.1`–`2.8`, `FR-10.5`–`10.6`)

### 3.1 Layout Overview (3-Column Splitter with Zen Mode Support)

- **Left Column (`240px`–`320px`):** Repo/Worktree Dropdown, Branch Switcher (`🌿 main ▾`), Stash Split-Button (`VP-22`), Collapsible Sidebar Panels (`Worktrees` `VP-3`, `Submodules` `VP-4`, `Stacked Branches` `VP-20`), Unified Staged/Unstaged File List, and Collapsible `Locally Ignored (--skip-worktree)` Panel (`VP-22`) at the bottom.  
- **Center Column (`280px`–`360px`):** Account/Identity Selector Pill (`VP-8`), Template Selector (`VP-5`), Commit Summary (`QLineEdit` with live character counter badge against `commit.subject_max_length_guide`, turning amber above `50` chars), Commit Description (`QPlainTextEdit` with `#` `IssueCompleter` `VP-7`), `CoAuthorInputWidget` (`VP-5`), Options Row (`Amend` checkbox, `Sign Commit (-S)` checkbox `VP-18`, `Bypass Hooks (--no-verify)` checkbox `VP-17`), `Commit` Split-Button, and Collapsible `HookOutputDrawer` (`VP-17`).  
- **Right Column (Flexible Stretch):** Enhanced `DiffWidget` (`src/wrench/ui/diff_view/diff_widget.py`). Pressing `F11` (`Focus / Zen Mode`) animates Left and Center columns to `width = 0` so `DiffWidget` fills 100% of the window width.

### 3.2 New UI/UX Features in `DiffWidget` (`src/wrench/ui/diff_view/diff_widget.py`)

Every sub-feature below has its own toggle in `SettingsRegistry` (`Diff & Merge` category):

1. **Unified vs. Side-by-Side Split Diff Toggle (`Ctrl+D`, `diff.view_mode`: `"unified"` / `"split"`):**  
   - Toolbar segmented button switching instantly between single-column unified diff and dual-pane synchronized-scroll side-by-side diff ([Lazygit \#155](https://github.com/jesseduffield/lazygit/issues/155)).  
2. **Interactive Diff Minimap Scrubber (`diff.minimap.enabled`, default `True`):**  
   - A `12px`\-wide vertical canvas strip docked beside the vertical scrollbar painting proportional green ticks for additions, red ticks for deletions, blue ticks for moved blocks (`--color-moved`), and purple ticks for inline PR comments (`VP-6`). Clicking or dragging on the minimap scrolls directly to that hunk.  
3. **Sticky File & Function Context Header (`diff.sticky_function_header.enabled`, default `True`):**  
   - A `24px`\-tall pinned banner at the top of the diff viewport displaying the current file path and the enclosing function/class signature extracted from the hunk header (`@@ -120,7 +120,9 @@ def calculate_graph_lanes(commits):`) so users scrolling through large hunks never lose context.  
4. **Hold `Alt+W` to Peek Whitespace Changes (`diff.whitespace_peek_shortcut.enabled`, default `True`):**  
   - Holding `Alt+W` temporarily renders visible whitespace markers (`·` for space, `→` for tab, `↵` for CRLF) and includes whitespace-only changes without mutating the persistent `diff.ignore_whitespace_mode` setting.  
5. **Right-Click Context Menu Actions on Selected Diff Lines:**  
   - `Stage Selected Lines (s)` / `Unstage Selected Lines (u)` (`FR-2.1`)  
   - `Discard Selected Lines` (guarded by confirmation \+ safety snapshot; addresses [Sublime Merge \#814](https://github.com/sublimehq/sublime_merge/issues/814))  
   - `Amend Selected Hunk/Lines into Earlier Commit...` (`VP-20`, `FR-3.8`; addresses [GitButler \#2513](https://github.com/gitbutlerapp/gitbutler/issues/2513))  
   - `Move Selected Hunk to Stacked Branch...` (`VP-20`)  
   - `View Line History (git log -L)...` (`VP-21`, `FR-9.5`; addresses [Sublime Merge Forum \#39746](https://forum.sublimetext.com/t/feature-request-line-history/39746))  
   - `Open File Blame at Line...` (`VP-21`, `FR-9.4`; addresses [git-cola \#953](https://github.com/git-cola/git-cola/issues/953))

### 3.3 Deep Diff Viewer Architecture & Virtualization Pipeline (`SRS FR-8.14`, `OPT-8` — MANDATORY)

To guarantee `< 3ms` file-switch latency and locked `60fps` scrolling even on 50,000-line diffs, coding models MUST implement the **4-Stage Virtualized Diff Rendering Pipeline** inside `src/wrench/ui/diff_view/diff_widget.py`:

1. **Stage 1 — Zero-Copy Byte-Offset Patch Indexer (`PatchByteIndex`):**  
   - Instead of splitting a massive patch string into 50,000 Python `str` objects and inserting them into a heavy `QTextDocument` (`QPlainTextEdit`), store the raw UTF-8 `bytes` buffer once and build two flat `array('I')` C-arrays: `line_start_offsets` and `line_flags` (`bit 0-1`: context/add/del/hunk\_header/folded\_divider, `bit 2`: moved\_block, `bit 3`: has\_pr\_comment).  
   - Indexing 50,000 diff lines takes `< 3ms` and `< 800 KB` of RAM.  
2. **Stage 2 — Virtualized `DiffLineModel(QAbstractListModel)` \+ `QListView(uniformItemSizes=True)`:**  
   - Render diff rows using a `QListView` with `setUniformItemSizes(True)` and a custom `DiffRowDelegate(QStyledItemDelegate)` (or a `QAbstractScrollArea` viewport painter) that decodes UTF-8 slices `raw_bytes[start:end]` **only for the \~45 rows currently visible in the viewport**.  
   - In Side-by-Side Split mode (`Ctrl+D`), use a dual-column virtualized row model (`LeftLineSlice`, `RightLineSlice`) sharing a single vertical scrollbar so left and right panes never desynchronize by even 1 pixel.  
3. **Stage 3 — Viewport-Scoped Intra-Line & Syntax LRU Cache (`maxsize=512`):**  
   - Compute `difflib.SequenceMatcher` intra-line character/word spans and syntax-highlight token spans **lazily inside `DiffRowDelegate.paint()`** only for rows in `[first_visible_row - 20 : last_visible_row + 20]`, and memoize the resulting `(bg_spans, fg_tokens)` tuple in an in-memory `functools.lru_cache(maxsize=512)` keyed by `(file_oid_pair, row_index, width_px, theme_id)`.  
   - Automatically skip `SequenceMatcher` on any single hunk exceeding `diff.max_intraline_hunk_lines` (`500` lines).  
4. **Stage 4 — Collapsible Unchanged Context Dividers & `35ms` File-Switch Coalescing:**  
   - Collapse unchanged regions between hunks into a single interactive divider row (`[↕ Expand 20 unchanged lines above/below — def parse_tokens():]`), expanding slices in-place in `DiffLineModel` without re-running `pygit2` diff generation.  
   - Route `ChangesTab` and `HistoryTab` file-selection changes through a `35ms` single-shot coalescing `QTimer` (`diff.coalesce_switch_ms = 35`) with an incrementing `request_id` (`OPT-6`) so holding the Down arrow key across 100 files never queues redundant diff workers.  
   - **Binary & Large-File Guard:** If a file diff exceeds `performance.max_diff_file_size_kb` (`2048 KB`), render a lightweight placeholder card (`"Diff is 4.8 MB — [Load Virtualized Diff Anyway] [Open in External Diff Tool]"`).

## 4\. History Tab (`SRS FR-3.1`–`3.8`, `FR-9.1`–`9.5`)

### 4.1 Layout Overview

- **Top Bar:** Search & Filter Bar (`QLineEdit` with `200ms` debounce) \+ expandable filter chips (`Author`, `File Path`, `Date Range`, `Pickaxe Code Search -S/-G` `VP-11`) \+ `Reflog Time-Travel` button (`VP-11`) \+ `⚙` Settings shortcut.  
- **Optional Top Banner Slot:** Dynamically mounts `BisectBannerWidget` (`VP-19`) when bisect is active, or `SequencerBannerWidget` (`VP-1`/`VP-2`) when cherry-pick/revert/rebase is paused on a conflict.  
- **Center Area:** `CommitGraphWidget` (`src/wrench/ui/commit_graph/graph_widget.py`).  
- **Right Slide-In Panel:** `CommitDetailPanel` (`src/wrench/ui/commit_graph/detail_panel.py`).

### 4.2 New UI/UX Features in `CommitGraphWidget`

1. **Hover "X-Ray" Commit & Branch Preview Card (`graph.hover_xray_card.enabled`, default `True`):**  
   - Hovering over a commit node or branch pill for `400ms` (`QTimer` single-shot) displays a themed popup card showing: Full commit SHA (with 1-click Copy button), Author avatar \+ email, Relative \+ ISO timestamp, Diffstat summary bar (`5 files changed, +142 / -38`), GPG/SSH Signature status & fingerprint (`VP-18`), and linked PR/CI status badge.  
2. **Signature Verification Pill Badges (`VP-18`, `signing.verify_badges_in_graph.enabled`):**  
   - Draws compact `[✓ Verified]`, `[? Unverified]`, or `[✕ Bad Sig]` badges on commit rows using cached `QPixmap` glyphs.  
3. **Interactive Bisect Visual Overlay (`VP-19`, `bisect.ui.enabled`):**  
   - Dims commits outside the active `(good, bad)` DAG range to `35%` opacity, highlights candidate commits with a pulsing accent ring, and renders `[GOOD]`, `[BAD]`, and `[SKIP]` pills.  
4. **Stacked Branch Connectors (`VP-20`, `stacks.enabled`):**  
   - Renders stacked branch pills in a connected vertical bracket `[stack: auth-v2 1/3 -> 2/3 -> 3/3]` so stack hierarchy is immediately visible on the graph.  
5. **Combined Multi-Hosting Mirror DAG & Sync/Drift Pills (`VP-25`, `SRS FR-3.10`, `FR-4.6`):**  
   - **Unified Multi-Remote Graph Walk:** When `mirrors.unified_history.enabled` is `True`, `CommitGraphWidget` displays the combined commit DAG across all configured hosting mirrors (`origin` on GitHub, `gitlab` on GitLab, `codeberg` on Forgejo/Codeberg, `bitbucket` on Bitbucket, `sf` on SourceForge) so commits pushed to any mirror appear in one unified topological timeline.  
   - **Synced Mirror Group Pill Collapsing (`mirrors.collapse_identical_ref_pills`):** When multiple mirror remotes point to the exact same commit OID for a branch (e.g. `origin/main`, `gitlab/main`, and `codeberg/main` are all at `a1b2c3d`), `CommitGraphWidget` collapses them into a single compact pill: **`[🌐 main · GH · GL · CB ✓]`** instead of 3 separate cluttering pills.  
   - **Mirror Drift & Divergence Warning Badges (`mirrors.show_drift_warnings`):** When a mirror lags behind or diverges from the primary remote on the same branch name (e.g. `gitlab/main` is 4 commits behind `origin/main`), renders a distinct amber pill **`[⚠ GL/main ↓4]`** on the lagging commit node with a right-click context menu action **`Sync Mirror 'gitlab/main' Now`** (`git push gitlab origin/main:refs/heads/main`) and **`Push to All Mirrors`**.  
   - **Cross-Hosting CI & PR Aggregation (`mirrors.aggregate_cross_forge_ci`):** Displays combined per-forge CI status icons (`[GH ✓ | GL ✕]`) on commit rows and lists all mirror PRs/MRs and pipeline links inside the `400ms` Hover X-Ray Card.

### 4.3 Mandatory Optimizations for `CommitGraphWidget` (`100,000+` Commits at 60fps)

- **Strict Viewport Clipping (`paintEvent`):** In `CommitGraphWidget.paintEvent(event)`, compute `first_row = verticalScrollBar().value() // row_height` and `last_row = first_row + (viewport().height() // row_height) + 2`. Iterate and paint **ONLY** `commits[first_row:last_row]`. Never loop over all loaded commits during a paint event.  
- **`QPixmapCache` for Badges & Avatars:** Pre-render pill badges (`[Verified]`, `[GOOD]`, `[BAD]`, branch tags) and scaled circular avatars into `QPixmapCache` keyed by `(text, color_scheme, dpr)` so `paintEvent` performs fast `painter.drawPixmap()` blits instead of recalculating `QFontMetrics` and `QPainterPath` on every frame.  
- **Windowed `fetchMore` Pagination & Generation Tokens:** Fetch commits in pages of `performance.graph_page_size` (`500`). When the user types in the search bar, increment an integer `_search_generation_id` so any in-flight background worker from an older keystroke discards its result on completion instead of overwriting newer results.

## 5\. Cross-Cutting Concerns & Mandatory UI Optimization Rules

### 5.1 Theme System & Live Styling (`SRS FR-8.1`)

- Supports `System (Follow Desktop Portal / KStyle)`, `Dark`, `Light`, and `High-Contrast` themes (`ui.theme_mode`), plus customizable UI font size (`ui.font_size_pt`) and monospace diff font (`diff.font_family`, `diff.font_size_pt`).

### 5.2 Keyboard System, Vim Navigation & `Ctrl+K` Command Palette (`VP-23`)

- Optional Vim-style navigation toggle (`ui.vim_navigation.enabled`, default `False`): when enabled, `j`/`k` steps rows/hunks, `s`/`u` stages/unstages, `c` focuses the commit box, and `/` focuses search.  
- Global `Ctrl+K` / `Ctrl+Shift+P` Fuzzy Command Palette (`§6.24`) searches every menu action, branch, worktree, custom action, and **every setting toggle** in real time.

### 5.3 Universal CLI Command Preview / Dry-Run Footer (`ui.show_cli_preview_in_dialogs`, default `True`)

- **Purpose:** Demystifies Git GUI operations and prevents user anxiety before destructive actions.  
- **Design:** Every action dialog (`ResetModeDialog`, `InteractiveRebaseDialog`, `CloneDialog`, `SparseCheckoutDialog`, `MergeDialog`, `AddWorktreeDialog`) embeds a reusable `CliCommandPreviewBar(QWidget)` (`src/wrench/ui/widgets/cli_preview_bar.py`) at the bottom:  
  - Displays the exact command array that will run: e.g. `$ git -C /home/user/repo rebase --update-refs origin/main` with a `Copy Command` icon button.  
  - Controlled globally by `ui.show_cli_preview_in_dialogs` (when `False`, the preview bar is hidden across all dialogs).

### 5.5 Mandatory UI & Storage Optimization Rules for Coding Models (DO NOT SKIP)

Every coding model implementing or modifying UI and storage code in `VP-0`..`VP-23` MUST implement these 6 optimizations:

| Optimization ID | Pattern Name | Exact Implementation Requirement |
| :---- | :---- | :---- |
| **OPT-1** | **Lazy Page & Tab Instantiation** | Never instantiate hidden `QWidget` pages upfront. In `SettingsDialog` (`§6.11`) and `MainWindow` tabs (`§2.2`), store page builder callables in a dict and instantiate a category page only when the user clicks that category or searches. |
| **OPT-2** | **150ms Debounced Auto-Save in Settings** | `SettingsDialog` has **no "Save" or "Apply" button** — all changes auto-save. For discrete controls (`QCheckBox`, `QComboBox`), call `settings.set()` immediately. For continuous controls (`QSpinBox`, `QLineEdit`), route `valueChanged`/`textChanged` through a `150ms` single-shot `QTimer` before calling `settings.set()` so rapid typing or spinning writes to SQLite only once after the user pauses. |
| **OPT-3** | **Delta-Only Settings Snapshot & Undo/Redo Stack** | Never snapshot or copy the entire `global_settings` table on change. Whenever `settings.set(key, new_val, repo_path)` is called and `new_val != old_val`, insert **only a single delta row** `(change_id, timestamp, repo_path, key, old_value_json, new_value_json)` into a bounded 100-entry SQLite ring-buffer table `settings_undo_log`. Expose `settings.undo_last_change()` (`Ctrl+Z` in `SettingsDialog`) and `settings.redo_last_change()` (`Ctrl+Y`). |
| **OPT-4** | **SQLite WAL Mode & Prepared Statement Batching** | Enable `PRAGMA journal_mode=WAL;` and `PRAGMA synchronous=NORMAL;` on `wrench.db` connection open so UI reads never block on background worker writes. Use `executemany()` inside a single `with conn:` transaction when caching forge issues/PRs or applying presets. |
| **OPT-5** | **Bounded Ring-Buffer Output Widgets** | For streaming log widgets (`HookOutputDrawer` `VP-17`, `CILogDrawer` `VP-6`, `ActivityLog` `§6.13`), call `QPlainTextEdit.setMaximumBlockCount(5000)` and batch incoming stdout lines into `50ms` UI flush ticks (`QTimer`) so a fast subprocess printing 20,000 lines per second never freezes the Qt event loop. |
| **OPT-6** | **Worker Generation Tokens & Cancellation** | Every background task dispatched from a UI view (`DiffWidget`, `CommitGraphWidget`, `BlameViewerDialog`, `PRReviewOverlay`) must carry a monotonically increasing `request_id: int`. When the worker finishes, if `request_id != self._latest_request_id`, discard the result immediately without touching the DOM/widgets. |
| **OPT-7** | **5-Stage Mirror Resolution & `blake2b` Ref-Digest Cache** | Resolve multi-hosting mirrors via: (1) `< 10µs` pre-compiled URL canonicalizer, (2) `< 0.5ms` local `.git/packed-refs` \+ `.git/refs/remotes/` `blake2b` digest lookup in SQLite `mirror_resolution_cache`, (3) cached \$O(1)\$ root-commit OID equivalence check (`git rev-list --max-parents=0`), (4) parallel `ThreadPoolExecutor(max_workers=4)` `git ls-remote --refs` \+ HTTP/2 `httpx` pooling, and (5) a `120s` per-host circuit breaker for unreachable mirrors. |
| **OPT-8** | **Zero-Copy Virtualized Diff Model & 512-Line LRU Cache** | Index patches into flat `array('I')` byte-offset tables (`< 3ms` for 50k lines), render only visible rows via `DiffLineModel(QAbstractListModel)` \+ `QListView(uniformItemSizes=True)`, memoize visible intra-line/syntax spans in a `512`\-entry LRU cache, and coalesce file-selection changes over a `35ms` timer. |

### 5.6 2-Tier Progressive Disclosure Help System (`SRS FR-8.13`, `help.tooltip_mode`)

- **Tier 1 — Contextual Beginner Hover Popover (`RichHelpTooltip`, `src/wrench/ui/widgets/rich_help_tooltip.py`):**  
  - Attached to any Git concept or control via helper `attach_help_topic(widget, topic_id="rebase.update_refs")`.  
  - Controlled by `help.tooltip_mode` in `SettingsRegistry`:  
    1. `"beginner_rich"` (Default): Hovering for `help.tooltip_delay_ms` (`500ms`) opens a rich themed `QFrame` popover containing:  
       - **Title & Shortcut:** e.g. `Cascade Rebase (--update-refs)  [Ctrl+Shift+U]`  
       - **2-Line Plain-English Summary:** *"Updates this branch and automatically moves any child branches stacked on top of it so you don't have to rebase them one by one."*  
       - **CLI Equivalent Badge:** `git rebase --update-refs`  
       - **Footer Links:** **`[Read Full Guide (F1) →]`** (opens `HelpCenterDialog` directly to `topic_id`) and **`[Hide Beginner Tips]`** (sets `help.tooltip_mode = "compact_shortcut_only"` in 1 click).  
    2. `"compact_shortcut_only"`: Uses standard native Qt tooltip showing only `"Cascade Rebase (Ctrl+Shift+U)"` with zero custom widget overhead.  
    3. `"off"`: Suppresses tooltips completely.  
- **Tier 2 — Searchable Offline Help & Git Concept Encyclopedia (`HelpCenterDialog` / `F1`, `src/wrench/ui/dialogs/help_center_dialog.py`):**  
  - Opened via `F1`, `Help -> Wrench & Git Guide`, or clicking **`[Read Full Guide →]`** inside any Tier 1 hover tooltip.  
  - **Left Pane:** Instant keyword search bar (`QLineEdit`) \+ topic tree (*Getting Started*, *Staging & Hunks*, *Branches, Rebasing & Stacks*, *Worktrees & Submodules*, *Resolving Conflicts & Rerere*, *Forges, PRs & CI*, *Troubleshooting Hooks & Signing*).  
  - **Right Pane (`QTextBrowser`):** Renders bundled offline Markdown/HTML articles explaining both the Git concept (with visual ASCII/SVG diagrams) and how Wrench's UI executes it, plus interactive action links (`wrench://open-setting/<key>` to jump straight to that setting in `SettingsDialog`, or `wrench://highlight-ui/<widget_id>` to pulse-highlight the button in the main window).  
  - **Mandatory Optimization (`OPT-1` Lazy Topic Loading):** Help articles are stored as lightweight Markdown files under `src/wrench/ui/help_topics/` and parsed/indexed **only when `F1` or `Read Full Guide` is triggered**, consuming `0 KB` of RAM during normal app usage.

### 5.7 Mandatory Security & Secret-Redaction UI Rules (`SEC-1`–`SEC-7`)

- **Automatic Credential & Token Redaction (`SEC-3`):** Before appending any text to `HookOutputDrawer`, `CILogDrawer`, `ActivityLog`, `CliCommandPreviewBar`, or error dialogs, pass the string through `src/wrench/core/security_sanitizer.py:redact_secrets(text)` which scrubs `ghp_[A-Za-z0-9_]+`, `github_pat_[A-Za-z0-9_]+`, `glpat-[A-Za-z0-9\-_]+`, `Bearer\s+\S+`, and basic-auth URLs (`https://[^:/\s]+:[^@\s]+@` \-\> `https://***:***@`).  
- **Safe `wrench://` Help URI Allowlisting (`SEC-6`):** `HelpCenterDialog` must reject any `QUrl` whose scheme is not `wrench` or whose target setting key / widget ID is not in the registered `SettingsRegistry` / `HELP_TOPICS` allowlist.

## 6\. Secondary UI Surfaces (`§6.1` – `§6.24`)

### 6.1–6.10 Core v1 Surfaces (Enhanced with v2 Toggles & Previews)

- **§6.1 Stash Panel (`stash_dialog.py`):** Upgraded in `VP-22` with mode badges (`staged-only`, `keep-index`, `untracked`), explicit `refs/stash@{n}` actions ([Sublime Merge \#945](https://github.com/sublimehq/sublime_merge/issues/945)), and `CliCommandPreviewBar`.  
- **§6.2 Clone Dialog (`clone_dialog.py`):** Upgraded in `VP-16` with a `Partial Clone Filter` combo-box (`Full Clone`, `Blobless (--filter=blob:none)`, `Treeless (--filter=tree:0)`) and a `Configure Sparse-Checkout Immediately After Clone` checkbox ([GitHub Desktop \#17901](https://github.com/desktop/desktop/issues/17901)).  
- **§6.3 LFS & Submodules (`lfs_locks_dialog.py`, `submodule_panel.py`):** Upgraded in `VP-4` & `VP-12` with dirty badges, recursive update toggles, and `.gitattributes` pattern management.  
- **§6.4 Safety Snapshots Browser (`snapshots_panel/__init__.py`):** Upgraded in `VP-14` to display both pre-operation snapshots and periodic scheduled snapshots (`safety.scheduled_backups.enabled`) with side-by-side diff preview and 1-click restore.  
- **§6.5 Identity & Commit Signing Dialog (`identity_dialog.py`):** Upgraded in `VP-8` & `VP-18` with GPG/SSH key selector (`gpg.format = ssh` or `openpgp`), `allowed_signers` auto-generator, and multi-account directory routing link.  
- **§6.6 3-Way Merge Tool (`merge_tool/merge_dialog.py`):** Upgraded in `VP-10` & `VP-23` with an top info banner when `git rerere` auto-resolved conflicts (`"2 conflict hunks auto-resolved from your recorded git rerere memory — [Forget Recorded Resolution]"`, [Sublime Merge \#814](https://github.com/sublimehq/sublime_merge/issues/814)) and an `"Open in External Merge Tool"` button.  
- **§6.7 Reflog History & Recovery Dialog (`reflog_dialog.py`):** Upgraded in `VP-11` with an `"Orphaned / Unreachable Commits Only"` filter chip, action badges (`reset`, `rebase`, `commit (amend)`), and 1-click `Restore Branch Here`.  
- **§6.8–6.10 Remotes, Backup/Bundle, and Repository Discovery Dialogs:** Equipped with `⚙` settings jump links and `CliCommandPreviewBar`.

### 6.11 Modular Settings Center (`src/wrench/ui/dialogs/settings_dialog.py` — `VP-0`, `SRS FR-8.8`–`8.11`)

**Design Mandate:** Every single feature and threshold in Wrench is controllable here. Built for speed, discoverability, and mistake-proof Undo.

- **Window Layout (`920px x 640px` minimum, non-blocking modal or dockable tab):**  
  - **Top Header Bar:**  
    1. **Instant Search Input (`QLineEdit`, focused on `Ctrl+F` or automatically on open):** Filters categories and highlights matching setting labels, descriptions, and keys in `<16ms`.  
    2. **Scope Selector (`QComboBox`):** Switches between `🌐 Global Defaults` and `📁 Repository Override: {current_repo_name}`.  
    3. **"Modified Only" Filter Pill (`QToolButton`, checkable):** When checked, hides all settings currently at their default value, showing only user-modified settings and active per-repo overrides.  
    4. **Undo / Redo Buttons (`↶ Undo (Ctrl+Z)`, `↷ Redo (Ctrl+Y)`, `🕓 History`):** Wired to the **Delta-Only Settings Undo Stack (`OPT-3`)**. Shows a badge with the number of undoable setting changes in the current session. Clicking `🕓 History` opens a popover listing the last 50 individual setting deltas (`"18:42 — graph.lane_width_px: 16 → 22 [Revert This]"`) so the user can revert any specific past tweak even out of order\!  
    5. **Preset & Portability Menu (`Presets & JSON ▾`):** `Apply Minimalist Local-Only Mode`, `Apply Power-User Full Mode`, `Export Settings to JSON...`, `Import Settings from JSON...`, `Reset All to Factory Defaults`.  
  - **Left Category Navigation (`QListWidget`, 12 Categories):**  
    1. `General & UI`  
    2. `Staging & Commits`  
    3. `Commit Graph`  
    4. `Diff & Merge`  
    5. `Branches & Stacks`  
    6. `Worktrees & Submodules`  
    7. `Remotes & LFS`  
    8. `Forges & CI`  
    9. `Hooks & Signing`  
    10. `Blame & Search`  
    11. `Watcher & Performance`  
    12. `Safety & Backups`  
    13. `Custom Actions & Shortcuts`  
  - **Right Content Area (`QStackedWidget` with `OPT-1` Lazy Page Instantiation):**  
    - Each category page is constructed **only when first selected** (or when a search query matches a setting inside that category).  
    - **Live Interactive Mini-Preview Card at Top of Visual Categories:** In `Commit Graph`, `Diff & Merge`, and `General & UI`, a `72px`\-tall embedded preview strip renders a sample commit graph row or sample 4-line diff that updates live as the user drags `graph.lane_width_px`, `graph.row_height_px`, `ui.font_size_pt`, or toggles `diff.intraline_word_diff.enabled`.  
    - **Per-Setting Row Anatomy (`SettingRowWidget`):**  
      - Left: `★` Pin-to-Quick-Settings toggle icon \+ **Bold Label** \+ muted description subtitle \+ `(key_name)` badge \+ `[Repo Override]` pill if overridden for the current repo.  
      - Right: Input control (`QCheckBox`, debounced `QSpinBox`, `QComboBox`, or `QLineEdit`) \+ `↺` Reset-to-Default button (visible only when current value `!= spec.default`).  
      - Dependency dimming: If `spec.parent_toggle_key` is `False`, the child row is automatically disabled (`setEnabled(False)`) with a note `"Requires <Parent Setting> to be enabled"`.  
  - **Bottom Floating Toast inside `SettingsDialog`:**  
    - Whenever any setting is changed, a subtle footer bar shows: `✓ Auto-saved 'graph.show_avatars' (True → False)  [Undo (Ctrl+Z)]`.

### 6.12–6.14 Avatars, Activity Log (`ui.humor_lines`), and About Dialog

- Preserved from v1 Phase 4.4–4.6 and wired into `SettingsRegistry` (`graph.show_avatars`, `ui.humor_lines`, `ui.activity_dock.max_lines`).

### 6.15 Visual Reset Mode Picker (`src/wrench/ui/dialogs/reset_dialog.py` — `VP-1`)

- Displays target commit summary and three selectable mode cards:  
  - **Soft (`--soft`):** Green badge — *"Moves branch pointer only. All commits between here and HEAD become Staged Changes."* (Shows exact count: `+N files will be staged`).  
  - **Mixed (`--mixed`, Default):** Amber badge — *"Moves branch pointer and unstages index. All changes remain safely in your working files."*  
  - **Hard (`--hard`):** Red badge — *"Discards all staged and working-tree modifications since target commit. Wrench will create an automatic safety snapshot first."*  
- Includes `CliCommandPreviewBar` at bottom (`$ git reset --mixed <oid>`) and a `"Don't show this dialog again"` checkbox (`reset.show_visual_preview_dialog`).

### 6.16 Visual Interactive Rebase Dialog (`src/wrench/ui/dialogs/interactive_rebase_dialog.py` — `VP-2`)

- Top summary bar: `"Rebasing N commits onto <base_branch> (<base_short_oid>)"` \+ `Autostash (--autostash)` and `Autosquash (--autosquash)` checkboxes.  
- Center `QTableWidget`: Drag-handle column (`≡`), Action `QComboBox` (`pick`, `reword`, `edit`, `squash`, `fixup`, `drop` color-coded by action), Short OID, Commit Summary, Author.  
- Selecting `reword` or `squash` expands an inline `QPlainTextEdit` below the table to pre-edit the resulting commit message before starting the rebase.  
- Validation rule: If row 0 is set to `squash` or `fixup`, disables `Start Rebase` and highlights row 0 with `"Cannot squash/fixup the first commit — no previous commit above it"`.

### 6.17 Worktree Manager Panel & Bare-Repo Worktree Hub (`src/wrench/ui/widgets/worktree_panel.py` — `VP-3`)

- Sidebar collapsible panel listing active worktrees with branch badge, lock icon (`🔒`), dirty indicator dot, and full filesystem path tooltip on hover ([GitHub Desktop Issues](https://github.com/desktop/desktop/issues)).  
- When a bare repository with worktrees is opened (`worktrees.bare_hub.enabled`), `MainWindow` displays a full-window **Bare Repository Worktree Hub** card grid allowing the user to open any linked worktree tab or create a new worktree from a branch ([Lazygit \#3100](https://github.com/jesseduffield/lazygit/issues/3100)).

### 6.18 PR Inline Review Overlay & Live CI Log Drawer (`src/wrench/ui/widgets/pr_review_overlay.py` — `VP-6`)

- Inline comment cards mounted inside `DiffWidget` below commented lines with `Reply`, `Resolve Thread`, and Markdown formatting preview.  
- Top PR toolbar button `Checkout PR #N Locally` (`git fetch origin pull/N/head:pr-N`).  
- Bottom collapsible `CILogDrawer` with `OPT-5` 5,000-line ring buffer, step filter, and `Re-run Failed Jobs` button.

### 6.19 Multi-Account Directory Routing Dialog (`src/wrench/ui/dialogs/account_rules_dialog.py` — `VP-8`)

- Table of directory prefix rules (`~/work/ -> GitHub (@corp-user), SSH: ~/.ssh/id_work, Author: Name <work@corp.com>`) with `Add Rule`, `Edit`, `Delete`, and a live `"Test Repository Path"` verifier input.

### 6.20 Sparse-Checkout Directory Tree Dialog (`src/wrench/ui/dialogs/sparse_checkout_dialog.py` — `VP-16`)

- Lazy-loaded `QTreeWidget` populated from `HEAD` tree objects via `pygit2` (`list_head_top_directories`), allowing users in monorepos to check/uncheck folders to materialize via `git sparse-checkout set` ([GitHub Desktop \#17901](https://github.com/desktop/desktop/issues/17901)).

### 6.21 Interactive Git Bisect Control Banner (`src/wrench/ui/widgets/bisect_banner.py` — `VP-19`)

- Docked at the top of `HistoryTab` during active bisect: shows current commit under test, progress bar (`~4 steps remaining`), `✓ Mark Good`, `✕ Mark Bad`, `⏭ Skip`, `▶ Run Automated Script...`, and `Abort / Reset Bisect` buttons ([Lazygit \#1542](https://github.com/jesseduffield/lazygit/issues/1542), [\#5575](https://github.com/jesseduffield/lazygit/issues/5575)).

### 6.22 Stacked Branches Sidebar & Hunk-to-Commit Picker (`src/wrench/ui/widgets/stack_panel.py` — `VP-20`)

- Visual stack tree in `ChangesTab` left column showing ordered branches in the current stack, `New Stacked Branch on Top`, `Restack All (--update-refs)`, and `Push & Sync Stack PRs`.  
- Includes `HunkTargetCommitDialog` allowing users to pick any historical commit in the current branch/stack to receive a selected diff hunk via automated `--fixup` \+ `--autosquash` ([GitButler \#2513](https://github.com/gitbutlerapp/gitbutler/issues/2513)).

### 6.23 Interactive Blame Viewer & Line History (`git log -L`) Drawer (`src/wrench/ui/widgets/blame_viewer.py` — `VP-21`)

- Split view: left gutter renders commit short SHA, author, date, and age-heatmap bar; right pane renders syntax-highlighted file lines.  
- Toolbar includes `Respect .git-blame-ignore-revs` checkbox, `Blame Parent Commit (<<)` button, `Add Selected Commit to .git-blame-ignore-revs` button, and a bottom drawer showing `git log -L <start>,<end>:<file>` commit diffs for any highlighted line range ([Sublime Merge Forum \#39746](https://forum.sublimetext.com/t/feature-request-line-history/39746)).

### 6.24 Global Fuzzy Command Palette (`Ctrl+K`) & Custom Actions (`src/wrench/ui/dialogs/command_palette.py` — `VP-23`)

- Frameless, centered top overlay (`600px` wide) opened with `Ctrl+K` or `Ctrl+Shift+P`.  
- Searches 4 unified providers in `<10ms`:  
  1. **Built-in Commands** (e.g. `Branch: Interactive Rebase...`, `Stash: Stash Staged Only`)  
  2. **Branches & Worktrees** (type a branch name to switch immediately)  
  3. **User Custom Actions** (`VP-23`, e.g. `Run pytest on current file`)  
  4. **Settings Quick-Toggles** (type `toggle blame` or `togglelanes` to flip any `SettingsRegistry` boolean setting inline without even opening `SettingsDialog`\!).

### 6.26 Multi-Hosting Mirror Manager & Sync Matrix Dialog (`src/wrench/ui/dialogs/mirror_manager_dialog.py` — `VP-25`, `SRS FR-3.10`, `FR-4.6`, `FR-4.7`)

- **Purpose:** Lets users manage repositories mirrored across multiple hosting sites (GitHub, GitLab, Codeberg/Forgejo, Bitbucket, SourceForge), inspect cross-mirror branch drift, and push/fetch across all mirrors in parallel.  
- **Layout (`780px x 520px` dialog opened via `Repository -> Mirrors & Multi-Hosting Sync...` or clicking any `[🌐 ...]` mirror pill in `CommitGraphWidget`):**  
  - **Top Summary Bar:** Displays canonical Root-Commit Fingerprint (`Root OID: 8f3a1c9... — Verified across N mirrors`), `Probe All Mirrors Now` button, `Push All Synced Branches to All Mirrors` button, and `⚙` Settings shortcut.  
  - **Center Mirror Sync Matrix Table (`QTableWidget`):**  
    - Columns: `Remote Name` (`origin`, `gitlab`, `codeberg`), `Hosting Forge` (icon \+ detected adapter), `Canonical URL`, `Root Lineage Match` (`✓ Verified Mirror` vs `✕ Unrelated Repo`), `Branch Sync Status` (`✓ All 6 branches synced` or `⚠ main ↓4 behind origin`), `Circuit-Breaker / Latency` (`142ms` or `⚡ Offline — circuit open 95s`), and `Quick Actions` (`[Sync Now]`, `[Open Web]`).  
  - **Bottom `CliCommandPreviewBar` (`§5.3`):** Previews the exact parallel `git push` / `git fetch --multiple` command that will run.

## 7\. Complete File / Component Mapping (v1 \+ v2)

| File Path | Status | Owning Phase & UI Section |
| :---- | :---- | :---- |
| `src/wrench/storage/settings_registry.py` | **NEW (v2)** | `VP-0` (§6.11, §5.5 `OPT-2`/`OPT-3` Delta Undo Stack) |
| `src/wrench/ui/main_window.py` | **EXTEND** | `VP-0`..`VP-23` (§1 Window Chrome, Lazy Tabs `OPT-1`, Zen Mode `F11`) |
| `src/wrench/ui/widgets/undo_toast.py` | **NEW (v2)** | `VP-0` / `VP-1` (§1.4 Global Action & Undo Toast Banner) |
| `src/wrench/ui/widgets/cli_preview_bar.py` | **NEW (v2)** | `VP-1` (§5.3 CLI Command Dry-Run Preview Footer) |
| `src/wrench/ui/dialogs/settings_dialog.py` | **REWRITE (v2)** | `VP-0` (§6.11 Lazy Pages, Debounced Auto-Save, Delta Undo/Redo) |
| `src/wrench/ui/dialogs/reset_dialog.py` | **NEW (v2)** | `VP-1` (§6.15 Visual Reset Mode Picker) |
| `src/wrench/ui/dialogs/interactive_rebase_dialog.py` | **NEW (v2)** | `VP-2` (§6.16 Drag-and-Drop Interactive Rebase UI) |
| `src/wrench/ui/widgets/worktree_panel.py` | **NEW (v2)** | `VP-3` (§6.17 Worktree Sidebar & Bare-Repo Worktree Hub) |
| `src/wrench/ui/widgets/submodule_panel.py` | **NEW (v2)** | `VP-4` (§6.3 Submodules Panel & Dirty Badges) |
| `src/wrench/ui/widgets/coauthor_input.py` | **NEW (v2)** | `VP-5` (§3.1 Co-Author Pill Completer) |
| `src/wrench/ui/widgets/pr_review_overlay.py` | **NEW (v2)** | `VP-6` (§6.18 Inline PR Diff Review & `CILogDrawer`) |
| `src/wrench/ui/tabs/issue_list_tab.py` | **EXTEND (v2)** | `VP-7` (§2.1 Issues Tab & `issue_completer.py`) |
| `src/wrench/ui/dialogs/account_rules_dialog.py` | **NEW (v2)** | `VP-8` (§6.19 Multi-Account Directory Routing Dialog) |
| `src/wrench/ui/diff_view/diff_widget.py` | **EXTEND (v2)** | `VP-10` (§3.2 Split Diff, Minimap, Sticky Header, Intra-line, `--color-moved`) |
| `src/wrench/ui/dialogs/reflog_dialog.py` | **EXTEND (v2)** | `VP-11` (§6.7 Orphaned Commit Filter & 1-Click Recovery) |
| `src/wrench/ui/dialogs/lfs_locks_dialog.py` | **NEW (v2)** | `VP-12` (§6.3 LFS Locks & `.gitattributes` Pattern Editor) |
| `src/wrench/ui/tray_manager.py` | **NEW (v2)** | `VP-13` (§1.1 System Tray Indicator & Close-to-Tray) |
| `src/wrench/ui/snapshots_panel/__init__.py` | **EXTEND (v2)** | `VP-14` (§6.4 Scheduled Safety Snapshots & Restore Browser) |
| `src/wrench/ui/dialogs/sparse_checkout_dialog.py` | **NEW (v2)** | `VP-16` (§6.20 Sparse-Checkout Directory Picker) |
| `src/wrench/ui/widgets/hook_output_drawer.py` | **NEW (v2)** | `VP-17` (§3.1 Live Hook Output Ring-Buffer Drawer & `--no-verify`) |
| `src/wrench/ui/commit_graph/graph_widget.py` | **EXTEND (v2)** | `VP-16`, `VP-18`, `VP-19`, `VP-20` (§4.2 Signature Badges, Hover X-Ray, Bisect, 100k+ Paging) |
| `src/wrench/ui/widgets/bisect_banner.py` | **NEW (v2)** | `VP-19` (§6.21 Interactive Bisect Banner & Script Runner) |
| `src/wrench/ui/widgets/stack_panel.py` | **NEW (v2)** | `VP-20` (§6.22 Stacked Branches Sidebar & Hunk Routing Picker) |
| `src/wrench/ui/widgets/blame_viewer.py` | **NEW (v2)** | `VP-21` (§6.23 Blame Heatmap Gutter & `git log -L` Drawer) |
| `src/wrench/ui/widgets/skip_worktree_panel.py` | **NEW (v2)** | `VP-22` (§3.1 Locally Ignored `--skip-worktree` Drawer & Stash Split-Button) |
| `src/wrench/ui/dialogs/command_palette.py` | **NEW (v2)** | `VP-23` (§6.24 `Ctrl+K` Fuzzy Command Palette & Custom Actions) |

## 8\. Sequential UI Implementation Order (v1 Steps 1–25 \+ v2 Steps 26–49)

- **Steps 1–25 (v1 Baseline):** As specified in v1 (`implementation-plan.md` Phases 1–7).  
- **Step 26 (`VP-0`):** Implement `SettingsRegistry` with Delta-Only Undo Stack (`OPT-3`), WAL mode (`OPT-4`), and rewrite `settings_dialog.py` (§6.11) with Lazy Category Pages (`OPT-1`), `150ms` Debounced Auto-Save (`OPT-2`), Live Mini-Preview cards, and Quick-Settings Pinning (§1.3).  
- **Step 27 (`VP-0`):** Implement `LazyTabContainer` (`OPT-1`, §2.2), `UndoToastWidget` (§1.4), and `Focus / Zen Mode (F11)` (§1.2) on `MainWindow`.  
- **Step 28 (`VP-1`):** Build `CliCommandPreviewBar` (§5.3), `ResetModeDialog` (§6.15), and multi-select Cherry-Pick/Revert context menus in `HistoryTab`.  
- **Step 29 (`VP-2`):** Build `InteractiveRebaseDialog` (§6.16) with drag-and-drop row reordering and inline message editor.  
- **Step 30 (`VP-3`):** Build `WorktreePanel` and Bare-Repo Worktree Hub (§6.17) \+ Workspace Sessions menu (§1.2).  
- **Step 31 (`VP-4`):** Build `SubmodulePanel` (§6.3) with dirty badges and double-click-to-open-tab.  
- **Step 32 (`VP-5`):** Build `CoAuthorInputWidget` and Commit Template selector in `ChangesTab` (§3.1).  
- **Step 33 (`VP-6`):** Build `PRReviewOverlayWidget` and `CILogDrawer` with 5,000-line ring buffer (`OPT-5`, §6.18).  
- **Step 34 (`VP-7`):** Extend `IssueListTab` and wire `#` `IssueCompleter` into `ChangesTab` (§2.1, §3.1).  
- **Step 35 (`VP-8`):** Build `AccountRulesDialog` (§6.19) and top-right Account/Identity Switcher pill.  
- **Step 36 (`VP-9`):** Add Custom Forge Domains & Plugin Inspector UI to `SettingsDialog` (`Forges & CI` page, §6.11).  
- **Step 37 (`VP-10`):** Upgrade `DiffWidget` (§3.2) with Split/Unified toggle (`Ctrl+D`), Diff Minimap Scrubber, Sticky Function Header, `Alt+W` whitespace peek, intra-line word diff, and `--color-moved`.  
- **Step 38 (`VP-11`):** Upgrade `ReflogDialog` (§6.7) and add Pickaxe (`-S`/`-G`) search filters to `HistoryTab` (§4.1).  
- **Step 39 (`VP-12`):** Build `LFSLocksDialog` (§6.3) and locked-file icons in `ChangesTab`.  
- **Step 40 (`VP-13`):** Build `TrayManager` (§1.1) obeying `desktop.system_tray.enabled`.  
- **Step 41 (`VP-14`):** Upgrade `SnapshotsPanel` (§6.4) with scheduled backup interval controls and diff restore preview.  
- **Step 42 (`VP-15`):** Add Credential Backend selector (`auto` / `secret_service` / `xdg_portal` / `memory_only_ephemeral`) to `SettingsDialog`.  
- **Step 43 (`VP-16`):** Upgrade `CloneDialog` (§6.2) with `--filter=blob:none`, build `SparseCheckoutDialog` (§6.20), and add 100k+ commit lazy pagination \+ `QPixmapCache` to `CommitGraphWidget` (§4.3).  
- **Step 44 (`VP-17`):** Build `HookOutputDrawer` (`OPT-5`, §3.1) and `--no-verify` bypass controls in `ChangesTab`.  
- **Step 45 (`VP-18`):** Add `[✓ Verified]` signature badges and Hover X-Ray Commit Preview Cards (§4.2) to `CommitGraphWidget`.  
- **Step 46 (`VP-19`):** Build `BisectBannerWidget` (§6.21) and bisect visual dimming/badges on `CommitGraphWidget`.  
- **Step 47 (`VP-20`):** Build `StackPanel` and `HunkTargetCommitDialog` (§6.22) for stacked branches and hunk-to-commit routing.  
- **Step 48 (`VP-21`):** Build `BlameViewerDialog` and `"View Line History (git log -L)"` context menu drawer (§6.23).  
- **Step 49 (`VP-22` & `VP-23`):** Build Granular Stash split-button and `SkipWorktreePanel` (§3.1), `git rerere` banner in `MergeDialog` (§6.6), and `CommandPaletteDialog` (`Ctrl+K`, §6.24).  
- **Step 50 (`VP-24`):** Build `RichHelpTooltipManager` (§5.6), `HelpCenterDialog` (`F1`, §6.25), `UIWidgetHighlighter`, and `help_topics.py`.  
- **Step 51 (`VP-25`):** Build `MirrorManagerDialog` (§6.26) and multi-mirror unified ref pills, drift badges, and cross-forge CI aggregation in `CommitGraphWidget` (§4.2.5).