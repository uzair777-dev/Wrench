# UI Planning — Wrench

**Status:** Draft  
**Purpose:** Detailed UI specification for Wrench's desktop interface. Written to be executable by a lower-tier model — every layout, widget, interaction, and edge case is spelled out explicitly.

---

## 0. Reading Guide

This document describes the UI **from the outermost container inward**:
1. §1 — Window Chrome (menu bar, title bar)
2. §2 — Tab System (the primary navigation layer)
3. §3 — Changes Tab (staging, commit, diff)
4. §4 — History Tab (branch graph, commit details)
5. §5 — Cross-Cutting Concerns (theme, keyboard, a11y, status bar, localization)
6. §6 — Secondary UI Surfaces (stash, clone, LFS/submodules, snapshots, identity, 3-way merge tool, reflog recovery, remotes, backup/restore)
7. §7 — File/Component Mapping
8. §8 — Implementation Order

Each section includes: **layout**, **widget specs**, **interactions**, **edge cases**, and **visual notes**.

> [!IMPORTANT]
> This replaces the existing Phase 1 MVP UI layout (`MainWindow` with `QSplitter` holding sidebar + staging + diff). The current `RepoSidebar`, `DiffView`, and `DiffWidget` components can be reused internally, but the outer shell and layout structure are redesigned.

---

## 1. Window Chrome

### 1.1 Layout

```
┌──────────────────────────────────────────────────────────────┐
│  [Menu Bar]  File  Edit  View  Help                          │
├──────────────────────────────────────────────────────────────┤
│                                                              │
│               Tab System + Tab Content                       │
│              (see §2, §3, §4)                                │
│                                                              │
└──────────────────────────────────────────────────────────────┘
```

- The menu bar is a **standard `QMenuBar`** — native OS menu bar, not a custom widget. PySide6 handles platform integration automatically.
- Window title: `"Wrench"` (static, does not change per repo/tab).
- Default window size: `1200 × 800` (resizable, minimum `900 × 600`).

### 1.2 Menu Structure

#### File
| Item | Shortcut | Action |
|---|---|---|
| New Repository… | `Ctrl+N` | Opens a dialog to `git init` a new repo at a chosen directory |
| Open Repository… | `Ctrl+O` | Opens a file picker to add an existing repo to the registry |
| Clone Repository… | `Ctrl+Shift+C` | Opens a clone dialog (URL + destination path) (§6.2) |
| --- | | *(separator)* |
| Close Repository | `Ctrl+W` | Removes the current repo from the active view (does not delete files) |
| --- | | *(separator)* |
| Backup Repository… | — | Creates a full repository backup to an external path/USB/NAS (§6.9) |
| Restore from Backup… | — | Restores a repository from an external backup (§6.9) |
| Snapshots… | — | Opens the Snapshot Browser panel (§6.4) for the current repo |
| --- | | *(separator)* |
| Preferences… | `Ctrl+,` | Opens settings/preferences dialog (placeholder for now) |
| --- | | *(separator)* |
| Quit | `Ctrl+Q` | Closes the application |

#### Edit
| Item | Shortcut | Action |
|---|---|---|
| Undo | `Ctrl+Z` | Standard text undo (commit message / description fields) |
| Redo | `Ctrl+Shift+Z` | Standard text redo |
| --- | | *(separator)* |
| Cut | `Ctrl+X` | Standard cut |
| Copy | `Ctrl+C` | Standard copy |
| Paste | `Ctrl+V` | Standard paste |
| Select All | `Ctrl+A` | Standard select all |
| --- | | *(separator)* |
| Stash Changes… | `Ctrl+Shift+S` | Creates a stash (optionally named) from working tree changes (§6.1) |
| Pop Stash | `Ctrl+Shift+P` | Pops the most recent stash (apply + drop) |
| Manage Stashes… | — | Opens the Stash Manager dialog (§6.1) |
| --- | | *(separator)* |
| Manage Remotes… | — | Opens the Remotes configuration dialog (§6.8) |
| Reflog Recovery… | — | Opens the Reflog history & restore dialog (§6.7) |
| Git Identity… | — | Opens the git identity override dialog for the current repo (§6.5) |

#### View
| Item | Shortcut | Action |
|---|---|---|
| Toggle Tab Orientation | `Ctrl+Shift+T` | Switches between vertical (side) and horizontal (top) tab bar |
| --- | | *(separator)* |
| Zoom In | `Ctrl+=` | Increases UI font/scale (placeholder) |
| Zoom Out | `Ctrl+-` | Decreases UI font/scale (placeholder) |
| Reset Zoom | `Ctrl+0` | Resets to default scale (placeholder) |

#### Help
| Item | Shortcut | Action |
|---|---|---|
| About Wrench | — | Shows version, license (AGPL-3.0), and credits dialog |
| Documentation | — | Opens online docs in system browser (placeholder URL) |
| Report a Bug… | — | Opens issue tracker in system browser (placeholder URL) |

> [!NOTE]
> Menu items marked "placeholder" should be wired to a no-op or stub dialog showing "Coming soon" for now. The menu structure exists so items can be filled in incrementally without restructuring.

### 1.3 Window-Level Edge Cases

| Case | Behavior |
|---|---|
| **Quit with unsaved commit message** | If the commit message or description field in the Changes tab contains text, show a confirmation dialog: "You have an unsaved commit message. Quit anyway?" with "Quit" and "Cancel" buttons. Do not silently discard typed text |
| **Quit during background operation** | If a push/pull/fetch/clone is in progress (tracked via `workers.py`), show: "An operation is in progress. Quitting may leave your repository in an inconsistent state. Quit anyway?" with "Quit" and "Cancel" |
| **Window geometry persistence** | Save window position, size, and splitter positions to `app_settings` on close. Restore on next launch. If saved geometry is off-screen (monitor unplugged), fall back to default centered position |

---

## 2. Tab System

### 2.1 Concept

The tab system is the **primary navigation layer** inside the window, directly below the menu bar. It works like **browser tabs** — can be displayed **vertically on the left side** (default, GitKraken-style) or **horizontally on top** (toggled via View → Toggle Tab Orientation).

**Tab model: Hybrid (category singletons + dynamic detail tabs)**

Tabs fall into two categories:

| Category | Examples | Behavior |
|---|---|---|
| **Category tabs** (singleton) | Changes, History, PR List, Issues List | Only one instance allowed at a time. Opening one that's already open switches to it. Changes tab is pinned (non-closable); others are closable. |
| **Detail tabs** (dynamic) | A specific PR (#42), a specific Issue (#17), file blame | Opened by clicking an item inside a category tab (e.g., clicking PR #42 in the PR list opens a "PR #42" detail tab). Closable. Multiple detail tabs can coexist (e.g., PR #42 and PR #99 open simultaneously). |

**Per-repo deduplication rule**: A detail tab is uniquely identified by `(tab_type, repo_path, entity_id)`. For example, `("pr_detail", "/home/user/my-repo", "42")`. If the user tries to open a tab that matches an already-open identity triple, the existing tab is focused instead of opening a duplicate. This prevents opening the same PR/Issue twice for the same repo, while still allowing the same PR number from different repos.

### 2.2 Layout — Vertical Mode (Default)

```
┌─────────────────────────────────────────────────────────┐
│  Menu Bar                                               │
├──────┬──────────────────────────────────────────────────┤
│      │                                                  │
│  C   │                                                  │
│  H   │         Active Tab Content                       │
│  PR  │         (fills remaining space)                  │
│  #42 │                                                  │
│      │                                                  │
│  [+] │                                                  │
│      │                                                  │
├──────┴──────────────────────────────────────────────────┤
```

- `C` = Changes (pinned), `H` = History, `PR` = Pull Requests list, `#42` = PR detail tab
- The tab bar is a **narrow vertical strip** on the left edge (width: ~48px icon-only, or ~140px with labels, user preference TBD).
- Each tab shows an **icon** and optionally a **short label** below/beside it.
- The `[+]` button is at the **bottom** of the vertical tab bar (trailing edge).
- Active tab is visually highlighted (background color change + left accent border).
- Category tabs appear first (pinned order), followed by dynamic detail tabs in the order they were opened.

### 2.3 Layout — Horizontal Mode

```
┌─────────────────────────────────────────────────────────┐
│  Menu Bar                                               │
├─────────────────────────────────────────────────────────┤
│  [Changes] [History] [PR] [PR #42] [Issue #17]  [+]     │
├─────────────────────────────────────────────────────────┤
│                                                          │
│              Active Tab Content                          │
│              (fills remaining space)                     │
│                                                          │
└─────────────────────────────────────────────────────────┘
```

- Tabs are laid out left-to-right with the `[+]` button at the **right end** (trailing edge).
- Active tab is visually highlighted (bottom accent border + background).

### 2.4 Tab Bar Widget Spec

| Property | Detail |
|---|---|
| Widget | Custom `QWidget` subclass (`TabBar`) — **not** `QTabWidget` (need full control over orientation flipping, styling, and the add/close buttons) |
| Orientation | `Qt.Vertical` (default) or `Qt.Horizontal`, stored in user preferences |
| Toggle | `View → Toggle Tab Orientation` menu action, or a small toggle icon in the tab bar itself |
| Tab items | Each is a clickable widget with: icon, label text, optional close button (`×`) on hover |
| Add button | `+` icon button at the trailing edge — opens a dropdown/menu listing available **category** tab types to add |
| Reordering | Tabs are **drag-reorderable** within the bar |
| Closable | All tabs show a close `×` on hover, except the Changes tab which **cannot be closed** (it's the home tab) |
| Keyboard | `Ctrl+1/2/3/…` switches to tab by position |
| Tab label | Category tabs show their type name ("Changes", "History"). Detail tabs show entity info: "PR #42 — Fix login bug" (type + ID + truncated title) |

### 2.5 Default Tabs

On first launch, the tab bar contains:
1. **Changes** (cannot be closed, always present)
2. **History**

Other category tabs (PR List, Issues List) are added via the `[+]` button and are forge-dependent — they only appear in the `[+]` menu when a forge account is linked to the current repo.

Detail tabs are never in the `[+]` menu — they're opened contextually from within category tabs (clicking an item in a list).

### 2.6 The `[+]` Button Menu

When clicked, shows a dropdown with available **category** tab types:

| Tab Type | Condition to Appear | Icon |
|---|---|---|
| History | Always (if not already open) | `git-branch` / branch icon |
| Pull Requests | Only when a forge account is linked to the current repo | `git-pull-request` icon |
| Issues | Only when a forge account is linked to the current repo | `circle-dot` / issue icon |

> [!NOTE]
> Duplicate **category** tabs of the same type are **not allowed**. If "History" is already open, it does not appear in the `[+]` menu. Clicking `[+]` when all possible category tabs are already open shows "All tabs are open" as a disabled item.
> 
> **Detail tabs** are not opened via `[+]` — they're opened by clicking items in category tabs (e.g., clicking a PR in the PR list). Detail tabs follow the per-repo dedup rule: if the same `(type, repo, entity_id)` is already open, focus it instead of opening a duplicate.

### 2.7 Detail Tab Lifecycle

| Trigger | Opens Detail Tab? | Tab Label |
|---|---|---|
| Click a PR in the PR List tab | Yes | `"PR #42 — Fix login bug"` |
| Click an issue in the Issues List tab | Yes | `"Issue #17 — Dashboard crash"` |
| Click a commit in the History graph | **No** — uses the existing slide-in detail panel within the History tab (§4.5). Commits are viewed in-context, not in separate tabs | N/A |
| Double-click a file in Changes tab | **No (v1)** — the diff view is inline. Opening files in tabs is deferred | N/A |

> [!TIP]
> The detail tab model is extensible — future features like file blame, commit detail tabs, or merge conflict resolution can open as detail tabs without changing the tab system architecture.

### 2.8 Tab System Edge Cases

| Case | Behavior |
|---|---|
| **Tab persistence across app restarts** | The set of open tabs (both category and detail) and their order is saved to `app_settings` on close and restored on next launch. If a saved tab type is no longer available (e.g., PR tab was open but forge account has since been unlinked), silently skip it and open only valid tabs. Detail tabs that can't be restored (entity no longer exists, or forge disconnected) are silently dropped |
| **Repo switch updates all tabs** | When the user switches repos via the Changes tab dropdown, **all open tabs refresh** to show the new repo's data. The History tab reloads its graph, the PR/Issues tabs (if open) re-fetch from the new repo's linked forge account. If the new repo has no forge link, forge-dependent tabs show an inline message: "Connect a forge account to view pull requests" rather than closing the tab. **Detail tabs from the previous repo are NOT auto-closed** — they remain open but show stale data with a subtle banner: "This tab shows data from {old_repo_name}. Switch to that repo to refresh." |
| **Tab focus on repo switch** | The currently active tab stays active after a repo switch. Do not auto-switch to the Changes tab |
| **Dedup: same entity, same repo** | If user clicks PR #42 and a tab for `(pr_detail, current_repo, 42)` already exists, focus that tab. Don't open a second one |
| **Dedup: same entity, different repo** | Allowed — PR #42 from repo A and PR #42 from repo B are distinct tabs |
| **Many open tabs (10+)** | Tab bar becomes scrollable. In vertical mode, a scroll indicator (small arrows or fade) appears. In horizontal mode, tabs compress and a scroll arrow appears at the edges. Overflow tabs accessible via a dropdown "▾" at the trailing edge |
| **Closing the last detail tab** | Focus returns to the category tab that spawned it (e.g., close PR #42 → focus the PR List tab). If the parent category tab is also closed, focus the Changes tab |

---

## 3. Changes Tab

This is the **default/home tab** and cannot be closed. It shows the working copy status, file staging, commit controls, and the diff view. Layout inspired by **GitHub Desktop**.

### 3.1 Overall Layout

```
┌──────────────────────────────────┬──────────────────────────────────┐
│         LEFT COLUMN              │         RIGHT COLUMN             │
│         (width: ~35%)            │         (width: ~65%)            │
│                                  │                                  │
│  ┌────────────────────────────┐  │                                  │
│  │  Current Repo Dropdown     │  │                                  │
│  ├────────────────────────────┤  │                                  │
│  │  🌿 main  ▾               │  │                                  │
│  └────────────────────────────┘  │        Diff View                 │
│                                  │        of selected file          │
│  ┌────────────────────────────┐  │                                  │
│  │  [☑ Select All]  42 files  │  │        OR                       │
│  │  ☑ src/main.py             │  │                                  │
│  │  ☑ README.md               │  │        Empty State:             │
│  │  ☐ .gitignore              │  │        "No changes" (bold)       │
│  │  ...                       │  │        + motivating quote        │
│  └────────────────────────────┘  │                                  │
│                                  │                                  │
│  ┌────────────────────────────┐  │                                  │
│  │ [👤] [Commit message     ] │  │                                  │
│  │      [Description...     ] │  │                                  │
│  │ [☐ Amend] [Commit to main] │  │                                  │
│  └────────────────────────────┘  │                                  │
│                                  │                                  │
└──────────────────────────────────┴──────────────────────────────────┘
```

The two columns are separated by a **`QSplitter`** (horizontal) so the user can drag to resize.

### 3.2 Left Column — Top: Repository Selector

| Property | Detail |
|---|---|
| Widget | Custom styled `QComboBox` — flush/borderless design, blends with the background theme |
| Content | Lists all repositories from the `repo_registry` (display name or basename of path) |
| Current | Shows the currently active repo name, highlighted |
| On change | Switching the dropdown triggers `_open_repo_path()` — loads the selected repo, restarts watcher, refreshes status |
| Style | No visible border in resting state. Subtle hover highlight. Dropdown arrow is minimal/integrated. Should feel like a native part of the panel, not a floating widget. The dropdown blends with the surrounding panel background color |

> [!TIP]
> The `RepoSidebar` from Phase 1 is replaced by this dropdown. The sidebar widget can be removed or repurposed. All repo-switching now goes through the dropdown at the top of the Changes tab.

#### Repository Selector Edge Cases

| Case | Behavior |
|---|---|
| **Zero repos registered** | Dropdown shows placeholder text: "No repositories". The file list area shows an empty state: "Open or clone a repository to get started" in bold, centered, with two action buttons below: "Open Repository…" and "Clone Repository…" that trigger the same actions as the File menu items |
| **No repo selected on launch** | On first-ever launch (no repos in registry), show the zero-repos state above. On subsequent launches, auto-select the most recently opened repo (`last_opened_at DESC`) |
| **Missing/relocated repo selected** | If a repo is marked `is_missing` in the registry, show it in the dropdown with a ⚠️ warning icon and strikethrough or muted text. Selecting it shows a dialog: "Repository not found at {path}. Relocate or remove?" with "Locate…" (opens file picker), "Remove" (removes from registry), and "Cancel" buttons. The Locate option calls `repo_registry.relocate_repo()` |
| **Repo added/removed externally** | The dropdown refreshes its list from `repo_registry` whenever: (a) the Changes tab becomes visible, (b) a File → Open/Clone/New action completes, (c) a repo is removed via File → Close Repository |

### 3.2b Left Column — Branch Indicator / Switcher

Directly below the repo dropdown, a **branch indicator row** shows the current branch and provides quick branch switching.

| Property | Detail |
|---|---|
| Widget | Custom widget: `QPushButton` styled as a flat label with a branch icon (`🌿`) and the current branch name, plus a dropdown arrow (`▾`) |
| Display | Shows: `🌿 main ▾` (icon + branch name + dropdown indicator). Flush/borderless style matching the repo dropdown above it |
| Click | Opens a **filterable branch picker dropdown** — a popup with a `QLineEdit` search box at the top and a list of all local branches below, sorted alphabetically. Remote tracking branches are shown in a separate group below locals, with muted text. Typing in the search box filters the list in real-time (case-insensitive substring match) |
| Switch | Selecting a branch calls `engine.switch_branch(name)`. If the working tree has uncommitted changes, show a confirmation: "You have uncommitted changes. Stash and switch, or cancel?" with "Stash & Switch", "Switch Anyway" (discards), and "Cancel" buttons |
| Right-click | Context menu on the branch indicator: "Create New Branch…", "Rename Branch…", "Delete Branch…" (with confirmation). These call the corresponding `engine` functions |
| Detached HEAD | Shows `🔗 HEAD detached at {short_sha}` in orange/warning color. Right-click offers "Create Branch Here…" |

> [!NOTE]
> This widget provides the primary UI surface for SRS FR-1.6 (Branch create/switch/rename/delete). The History tab's graph context menu (§4.8) offers the same operations on arbitrary commits, but this widget makes them accessible without leaving the Changes tab.

### 3.3 Left Column — Middle: Changed Files List

This is a **single unified list** of all changed files (staged + unstaged + untracked combined). It replaces the Phase 1 split "Staged Changes" / "Unstaged Changes" two-list design.

#### Behavior

| Property | Detail |
|---|---|
| Widget | `QListWidget` or custom `QTreeView` with checkboxes |
| Default state | **All files are checked (selected for commit) by default** when changes are detected |
| Checkbox | Each file row has a checkbox on the left. Checked = will be staged before commit. Unchecked = excluded |
| Select All | A **single checkbox** at the top of the list. Uses **tri-state** (`Qt.PartiallyChecked`): fully checked when all files are checked, unchecked when none are, **indeterminate (dash/minus icon)** when some are checked and some aren't. Clicking it when indeterminate or unchecked → checks all. Clicking it when fully checked → unchecks all |
| File display | Show the file path relative to repo root. Prefix or color-code by change type: modified (M), added (A), deleted (D), renamed (R), untracked (?) |
| Sorting | Group by: staged first (if any are already staged), then unstaged, then untracked. Within each group, alphabetical by path |
| Click on file row | Selects the file and shows its diff in the right column. Does NOT toggle the checkbox — only clicking the checkbox toggles it |
| Selected highlight | The currently-selected file (whose diff is shown) gets a visual selection highlight (background color). This is independent of the checkbox state |

#### Right-Click Context Menu (File List)

Right-clicking a file row shows a context menu:

| Item | Action |
|---|---|
| Stage File | Immediately stages the file via `engine.stage_file()` (independent of checkbox state) |
| Unstage File | Immediately unstages the file via `engine.unstage_file()` |
| Discard Changes | Restores the file to its last committed state (`git checkout -- {path}`). **Shows a confirmation dialog first**: "Discard all changes to {filename}? This cannot be undone." |
| --- | *(separator)* |
| Open in File Manager | Opens the file's parent directory in the system file manager via `QDesktopServices.openUrl()` |
| Copy Relative Path | Copies the file's repo-relative path to the clipboard |
| Copy Absolute Path | Copies the file's absolute filesystem path to the clipboard |

#### Staging Logic

The checkbox model is a **"commit selection" model**, not direct staging:
- When the user clicks **"Commit"**, all **checked** files are staged (`git add`) and then committed in one operation.
- Files that are **unchecked** remain unstaged after the commit.
- This matches GitHub Desktop's model: the user thinks in terms of "which files do I want in this commit?" not "stage then commit."

> [!IMPORTANT]
> Behind the scenes, the commit flow is: (1) unstage everything, (2) stage only checked files, (3) commit, (4) refresh. This ensures the checkbox state is the source of truth, not the git index. The existing `engine.stage_file()` and `engine.unstage_file()` functions handle the actual git operations.

### 3.4 Left Column — Bottom: Commit Section

Layout (top to bottom):

```
┌────────────────────────────────────────┐
│ [👤 icon]  [Commit message...       ]  │
│            [Description...           ] │
│            [     Commit to main     ]  │
└────────────────────────────────────────┘
```

#### Account Icon

| Property | Detail |
|---|---|
| Widget | `QPushButton` with icon, square, to the left of the commit message |
| Size | ~32×32px |
| Icon | Shows the avatar/icon of the currently linked forge account for this repo. If no forge account is linked, show a generic user silhouette icon |
| Hover | Tooltip showing: account username, email, forge provider name (e.g., "uzair — GitHub") |
| Click | Opens a small popup/dropdown menu with: (1) list of logged-in forge accounts (radio-select to switch), (2) separator, (3) "Add Account…" option that opens the forge account setup flow |

#### Commit Message Field

| Property | Detail |
|---|---|
| Widget | `QLineEdit` (single line) |
| Placeholder | `"Commit message"` (gray placeholder text) |
| Max length | Soft limit at 72 characters (visual indicator like a subtle color change past 72 chars, not a hard block) |
| Position | To the right of the account icon, top row |

#### Description Field

| Property | Detail |
|---|---|
| Widget | `QTextEdit` (multi-line, resizable) |
| Placeholder | `"Description"` (gray placeholder text) |
| Height | Default 3–4 lines, user can drag to resize vertically |
| Position | Below the commit message, full width of the commit section |

> [!NOTE]
> The commit message maps to the first line of the git commit message. The description maps to the body (separated by a blank line). If description is empty, the commit has only a subject line. This matches the git convention of `subject\n\nbody`.

#### Commit Button

| Property | Detail |
|---|---|
| Widget | `QPushButton` |
| Label | `"Commit to {branch_name}"` — dynamically shows the current branch name (e.g., "Commit to main"). When amend mode is active, label changes to `"Amend commit on {branch_name}"` |
| Position | Below the description field, full width |
| Enabled | Only enabled when: (1) commit message is non-empty, AND (2) at least one file is checked |
| Disabled state | Grayed out with tooltip explaining why it's disabled ("Enter a commit message" or "Select files to commit") |

#### Amend Commit Toggle

| Property | Detail |
|---|---|
| Widget | `QCheckBox` labeled "Amend" |
| Position | To the left of the commit button, on the same row (button shrinks slightly to make room) |
| Behavior | When checked: (1) the commit button label changes to "Amend commit on {branch}", (2) the commit message and description fields are **pre-filled** with the most recent commit's message and body, (3) the file list shows the changes from the last commit *combined* with any new working-tree changes, (4) committing calls `engine.commit(msg, amend=True)` |
| Guard | If the repo has zero commits (unborn branch), this checkbox is hidden/disabled — there's nothing to amend |
| Warning | On first check per session, show a subtle inline warning beneath the checkbox: "This will modify the most recent commit" (not a blocking dialog — amending is a normal workflow, not a dangerous one) |

> [!NOTE]
> Unchecking "Amend" restores the commit message/description to whatever the user had typed before amend was enabled (not cleared). The pre-amend text is stashed in a local variable, not discarded.

### 3.5 Right Column — Diff View

| Property | Detail |
|---|---|
| Widget | Reuse existing `DiffView` / `DiffWidget` from Phase 1 (`src/wrench/ui/diff_view/`) |
| Trigger | Updates when a file is selected (clicked) in the left column's file list |
| Content | Shows the unified diff for the selected file (same as current implementation — syntax-highlighted, line numbers, hunk headers) |
| Hunk staging | Existing hunk-level and line-level staging buttons remain functional within the diff view |
| Binary files | If the selected file is binary (`Diff.is_binary`), show a centered message: "Binary file changed" with the file size. Do not attempt to render diff content. Hunk/line staging controls are hidden; only whole-file staging is available |

#### Empty State (No Changes)

When there are **no changed files at all** (clean working tree):

```
┌──────────────────────────────────────┐
│                                      │
│                                      │
│           No changes                 │  ← Bold, large font, centered
│                                      │
│   "The best code is the code you     │  ← Regular font, muted color,
│    don't have to debug."             │    centered, italic
│                                      │
│                                      │
└──────────────────────────────────────┘
```

| Property | Detail |
|---|---|
| "No changes" | Bold, ~18pt font, centered horizontally and vertically in the right column |
| Quote | Random motivating/programming quote from a hardcoded list of ~20 quotes. Changes each time the empty state is shown. Regular weight, italic, muted/secondary text color |
| Behavior | This state is shown when: (1) the file list is empty (no changes), OR (2) no file is selected in the list but changes exist — in case (2), show "Select a file to view changes" instead of the quote |

#### Quote Pool (hardcoded)

```
"The best code is the code you don't have to debug."
"First, solve the problem. Then, write the code." — John Johnson
"Clean code always looks like it was written by someone who cares." — Robert C. Martin
"Simplicity is the soul of efficiency." — Austin Freeman
"Talk is cheap. Show me the code." — Linus Torvalds
"Any fool can write code that a computer can understand. Good programmers write code that humans can understand." — Martin Fowler
"Code is like humor. When you have to explain it, it's bad." — Cory House
"The only way to go fast, is to go well." — Robert C. Martin
"Programs must be written for people to read, and only incidentally for machines to execute." — Harold Abelson
"Make it work, make it right, make it fast." — Kent Beck
"Perfection is achieved, not when there is nothing more to add, but when there is nothing left to take away." — Antoine de Saint-Exupéry
"The most important property of a program is whether it accomplishes the intention of its user." — C.A.R. Hoare
"Before software can be reusable it first has to be usable." — Ralph Johnson
"It works on my machine." — Every developer ever
"git push --force and pray." — Anonymous
"There are only two hard things in Computer Science: cache invalidation and naming things." — Phil Karlton
"It compiles; ship it." — Anonymous
"Debugging is twice as hard as writing the code in the first place." — Brian Kernighan
"A ship in harbor is safe, but that is not what ships are built for." — John A. Shedd
"Your code is your craft. Commit with pride."
```

### 3.6 Changes Tab Edge Cases

| Case | Behavior |
|---|---|
| **Dirty commit fields on repo switch** | If the user has typed a commit message or description and switches repos via the dropdown, **save the draft per-repo** in memory (a dict keyed by repo path). When switching back to that repo, restore the draft. Drafts are lost on app quit (not persisted to disk — they're ephemeral scratch, not worth the complexity of DB storage) |
| **File list refresh during typing** | The file list refreshes on every watcher event (filesystem change). Refreshing must **preserve**: (1) the currently selected file highlight, (2) all checkbox states. If the selected file disappears (was committed or discarded externally), clear the diff view and show "Select a file to view changes" |
| **Very long file paths** | File paths in the list are truncated with `…` from the left if they overflow the column width (e.g., `…/deeply/nested/file.py`), showing the filename and closest parent. Full path is visible in a tooltip on hover |
| **Large number of changed files (100+)** | No pagination — show all files in a scrollable list. The `QListWidget` handles this natively. Consider adding a count badge next to the select-all checkbox: "☑ 42 files" |
| **Detached HEAD state** | Commit button label changes to "Commit on detached HEAD" with an orange/warning tint. A small info banner appears above the commit section: "You are in detached HEAD state. Consider creating a branch before committing." |
| **Unborn branch (zero commits)** | Commit button label: "Create initial commit". Amend checkbox is hidden. Everything else works normally |
| **Merge conflict state** | If `RepoStatus.has_conflicts` is true, show a persistent banner at the top of the Changes tab: "Merge in progress — resolve conflicts and commit to complete" with a link/button to the merge tool. Conflicted files are highlighted in red in the file list with a `⚠ C` prefix |

---

## 4. History Tab

The History tab shows a **GitKraken-style visual branch graph** — a scrollable, interactive visualization of the repository's commit history with branch lines, merge nodes, and commit metadata.

### 4.1 Overall Layout

```
┌─────────────────────────────────────────────────────────────────┐
│                                                                 │
│  ● ─── Commit message preview (HEAD)              2 min ago     │
│  │                                                              │
│  ● ─── Fix typo in README                         1 hour ago    │
│  │ \                                                            │
│  │  ● ── Add feature X (feature/x)                3 hours ago   │
│  │  │                                                           │
│  │  ● ── WIP: feature X progress                  5 hours ago   │
│  │ /                                                            │
│  ● ─── Merge branch 'feature/x'                   6 hours ago   │
│  │                                                              │
│  ● ─── Initial commit                             2 days ago    │
│                                                                 │
│                    (scrollable ↕)                                │
└─────────────────────────────────────────────────────────────────┘
```

### 4.2 Graph Rendering

| Property | Detail |
|---|---|
| Widget | Custom `QWidget` subclass (`CommitGraphWidget`) with a `QPainter`-based render pipeline — **not** a `QGraphicsScene` (too heavy for this use case). Alternatively, a `QAbstractScrollArea` subclass for efficient scroll handling of large histories |
| Direction | Vertical, top-to-bottom. **Newest commits at the top**, oldest at the bottom |
| Scrolling | The widget is scrollable vertically. Uses **virtual scrolling / lazy loading** — only renders visible commits + a buffer. Loads more commits as the user scrolls down |
| Row height | Fixed per commit row (~36–40px). Each row contains: the graph rail(s), commit dot, commit message preview, timestamp |
| Branch rails | Colored vertical lines (rails) representing branches. Each branch gets a **distinct color** from a palette. Rails shift left/right to show branching and merging |
| Commit nodes | Solid circles (`●`) on the rail. Merge commits have a slightly larger dot or a double-ring style |
| Branch labels | Branch name labels (e.g., `main`, `feature/x`, `HEAD`) appear as **rounded pill badges** next to the commit they point to. `HEAD` gets a special color (e.g., green) |
| Tag labels | Tag names appear as pill badges with a different style (e.g., outlined instead of filled) |

### 4.3 Commit Row Content

Each row displays (left to right):

```
[Graph rails + dot]  [Commit message (truncated)]  [Author avatar]  [Relative time]
```

| Element | Detail |
|---|---|
| Graph area | Fixed-width area (~80–150px depending on max branch depth) showing the rail lines and commit dot |
| Commit message | Single-line preview, truncated with `…` if too long. Uses the **subject line** (first line of commit message) |
| Author | Small avatar circle or initials badge (~20px). If gravatar/forge avatar is available, use it; otherwise show initials |
| Timestamp | Relative time ("2 min ago", "3 hours ago", "2 days ago"). On hover, show absolute timestamp in tooltip |

### 4.4 Hover Interaction — Tooltip Preview

When the user **hovers** over a commit row, a **tooltip-style popup** appears near the cursor showing:

```
┌─────────────────────────────────────┐
│  Fix typo in README                 │  ← Subject (bold)
│                                     │
│  Fixed a typo in the installation   │  ← Description body (if any)
│  section of README.md               │
│                                     │
│  ── Files Changed ──                │
│  M  src/main.py        +12  -3      │  ← change type, path, insertions, deletions
│  A  docs/guide.md      +45  -0      │
│  D  old_config.yaml     +0  -18     │
│                                     │
│  Author: uzair                      │
│  SHA: a1b2c3d4                      │
│  Date: 2025-08-26 18:30:00          │
└─────────────────────────────────────┘
```

| Property | Detail |
|---|---|
| Widget | `QToolTip` or a custom lightweight popup `QWidget` with `Qt.ToolTip` window flag |
| Delay | Standard tooltip delay (~500ms hover before appearing) |
| Content | Subject line (bold), description body (if exists), file changes overview with diff stats (+/-), author, short SHA, absolute date |
| Diff stats | Per-file: change type indicator (M/A/D/R), file path, `+N` insertions (green), `-N` deletions (red) |
| Dismiss | Disappears when cursor moves off the commit row |

### 4.5 Click Interaction — Slide-In Detail Panel

When the user **clicks** on a commit row, a **slide-in panel** appears from the right side, showing the full commit details and diff.

#### Layout

```
┌────────────────────────────────────┬───────────────────────────────┐
│                                    │                               │
│     Commit Graph                   │    Commit Detail Panel        │
│     (compressed but still          │    (slide-in from right)      │
│      visible and interactive)      │                               │
│                                    │    [×] Close                  │
│                                    │                               │
│                                    │    SHA: a1b2c3d4e5f6...       │
│                                    │    Author: uzair              │
│                                    │    Date: 2025-08-26 18:30     │
│                                    │                               │
│                                    │    ── Commit Message ──       │
│                                    │    Fix typo in README         │
│                                    │                               │
│                                    │    Fixed a typo in the...     │
│                                    │                               │
│                                    │    ── Files Changed (3) ──    │
│                                    │    ▸ src/main.py  +12 -3      │
│                                    │    ▸ docs/guide.md +45 -0     │
│                                    │    ▸ old_config.yaml +0 -18   │
│                                    │                               │
│                                    │    ── Diff ──                 │
│                                    │    (full diff of selected     │
│                                    │     file, or first file)      │
│                                    │                               │
└────────────────────────────────────┴───────────────────────────────┘
```

| Property | Detail |
|---|---|
| Widget | `QWidget` inside a `QSplitter` with the graph — OR an animated `QWidget` that slides in with a `QPropertyAnimation` on its width |
| Width | ~40–50% of the tab content area. The graph compresses to ~50–60% but remains visible and interactive |
| Animation | Slides in from the right edge with a smooth ~200ms ease-out animation |
| Close | `×` button in the top-right corner of the panel, OR clicking the same commit row again, OR pressing `Escape` |
| Header | Full SHA (copyable on click), author name + email, absolute date + relative time |
| Commit message | Full subject + full description body |
| Files list | Collapsible/expandable list of changed files. Each shows: change type, path, `+N -M` stats. Clicking a file shows its diff below |
| Diff view | Reuses the same `DiffView`/`DiffWidget` component from the Changes tab. Shows the diff for the selected file in the files list. If no file is selected, shows the diff for the first file |
| Scroll | The detail panel is independently scrollable |

### 4.6 Search & Filter Bar

A search/filter bar sits at the **top** of the History tab, above the graph:

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│  [🔍 Search commits...]  [Author ▾]  [Path / File ▾]  [Date range ▾]  [× Clear]  │
├─────────────────────────────────────────────────────────────────────────────────┤
│  (graph below)                                                                  │
```

| Element | Detail |
|---|---|
| Search box | `QLineEdit` with placeholder "Search commits…". Filters commit messages by case-insensitive substring match. Debounced (300ms single-shot `QTimer`) — does not search on every keystroke |
| Author filter | Dropdown/chip showing commit authors in this repo. Selecting one filters the graph to only that author's commits |
| Path / File filter | Dropdown/searchable picker to filter commits that modified a specific file or folder path (satisfies SRS FR-2.3) |
| Date range | A date-range picker popup (From / To dates). Filters commits to the selected range |
| Clear | A small `×` button inside the search box (or "Clear filters" button) to reset all filters to default |
| Results | Filtering does **not** remove non-matching commits from the graph — it **highlights matching commits** and dims/fades non-matching ones, preserving the visual branch structure. If the user wants to jump to the next match, `Enter` / `F3` scrolls to the next highlighted commit |

> [!NOTE]
> The search/filter maps directly to the `LogFilter` dataclass in `core/read_ops.py`. The filter is composed into a single `LogFilter(author=..., message_substring=..., path=..., date_from=..., date_to=...)` and passed to `engine.get_log()`.

### 4.7 Graph Layout Algorithm

The commit graph needs a layout algorithm to position rails and determine branching/merging visuals. High-level approach:

1. **Topological sort**: Walk commits from `HEAD` using `pygit2`'s `repo.walk()` with `GIT_SORT_TOPOLOGICAL | GIT_SORT_TIME`.
2. **Lane assignment**: Each active branch occupies a "lane" (column). When a commit has two parents (merge), the secondary parent's lane merges in. When a commit is a fork point, a new lane spawns.
3. **Color assignment**: Each lane gets a color from a rotating palette. Colors persist for the lifetime of the lane.
4. **Rendering**: For each visible row, draw:
   - Vertical rail lines for all active lanes
   - The commit dot on its assigned lane
   - Diagonal/curved merge lines connecting parent lanes
   - Branch/tag label badges

> [!IMPORTANT]
> The graph rendering is the most complex widget in the app. It should be implemented as a standalone, self-contained widget (`CommitGraphWidget`) with a clear API: `set_repo(repo_handle)`, `refresh()`, and signals for `commit_hovered(sha)`, `commit_clicked(sha)`. Keep the layout algorithm in a separate pure-Python module (`ui/commit_graph/layout.py`) testable without Qt.

### 4.8 Performance Considerations

| Concern | Strategy |
|---|---|
| Large repos (10k+ commits) | Virtual scrolling — only compute layout and render for visible rows + 50-row buffer above/below |
| Initial load | Load first 200 commits eagerly. Load more in batches of 100 as user scrolls |
| Scroll performance | Cache painted rows as pixmaps. Only repaint on resize or data change |
| Graph computation | Run the lane assignment algorithm in a background thread, emit results to UI thread |

### 4.9 Graph Interactions — Right-Click Context Menu

Right-clicking a **commit row** shows:

| Item | Action |
|---|---|
| Copy SHA | Copies the full SHA to clipboard |
| Copy Commit Message | Copies the subject line to clipboard |
| Cherry-pick this commit | Calls `engine.cherry_pick(sha)`. Shows a confirmation first: "Cherry-pick commit {short_sha} onto {current_branch}?" |
| Revert this commit | Calls `engine.revert(sha)`. Creates a new commit that inverts the changes of the selected commit (with confirmation dialog) |
| Rebase current branch onto here | Calls `engine.rebase(onto=sha)` (SRS FR-3.3) — rebases `{current_branch}` onto the selected commit |
| Reset {current_branch} to here… | Opens a sub-menu: **Soft** (keep changes staged), **Mixed** (keep changes unstaged), **Hard** (discard all working tree changes — shows prominent red warning dialog) |
| --- | *(separator)* |
| Create branch here… | Opens a dialog to create a new branch pointing at this commit |
| Create tag here… | Opens a dialog to create a lightweight or annotated tag at this commit |

Right-clicking a **branch label badge** shows:

| Item | Action |
|---|---|
| Switch to this branch | Calls `engine.switch_branch(name)` |
| Merge into {current_branch} | Calls `engine.merge(name)` (merges clicked branch into active branch) |
| Rebase {current_branch} onto this branch | Calls `engine.rebase(upstream=name)` (SRS FR-3.3) |
| Fast-forward {current_branch} to this branch | Fast-forwards active branch if it is directly behind the clicked branch |
| --- | *(separator)* |
| Rename branch… | Opens an inline rename dialog |
| Delete branch | Calls `engine.delete_branch(name)` with confirmation |
| Push to remote / Pull from remote | If a remote tracking branch exists, triggers push/pull for this branch |

Right-clicking a **tag label badge** shows:

| Item | Action |
|---|---|
| Copy tag name | Copies the tag name to clipboard |
| Push tag to remote | Pushes the tag to the default remote |
| Delete tag | Deletes the tag locally with confirmation dialog |

### 4.10 Empty State (No Commits)

When the repository has zero commits (unborn branch):

```
┌──────────────────────────────────────┐
│                                      │
│          No history yet              │  ← Bold, large, centered
│                                      │
│    Make your first commit to see     │  ← Muted text
│    the branch graph here.            │
│                                      │
└──────────────────────────────────────┘
```

### 4.11 History Tab Edge Cases

| Case | Behavior |
|---|---|
| **No repo selected** | Show the same zero-repos empty state as the Changes tab: "Open or clone a repository to get started" |
| **Clicking a different commit while detail panel is open** | The panel **updates in place** with the new commit's data — no close-and-reopen animation. Only the initial open and final close are animated |
| **Clicking the same commit that's already shown** | Closes the detail panel (toggle behavior) |
| **Scrolling while detail panel is open** | The panel stays open and pinned. The graph scrolls behind it. The highlighted commit row remains visually marked even if it scrolls out of the visible area |
| **Selecting a file in the detail panel's file list** | Updates the diff view within the panel. Does **not** affect the Changes tab's diff view — these are independent instances |
| **Very wide graphs (many branches)** | The graph area width is dynamic. If more than ~8 active lanes exist, the graph area expands horizontally and a horizontal scrollbar appears. The commit message column shrinks proportionally but never below ~200px |
| **Octopus merges (3+ parents)** | Treat as a regular merge for visual purposes — show connections to all parent lanes. The commit dot uses the same enlarged/double-ring style as a 2-parent merge |

---

## 5. Cross-Cutting Concerns

### 5.1 Theme / Styling

- All custom widgets must respect the application's `QPalette` and not hardcode colors (so dark/light themes work).
- The tab bar, repo dropdown, and commit section should feel **integrated and cohesive** — no visual breaks between them. Use subtle separators (1px lines, `QPalette.Mid` color), not heavy borders.
- The branch graph rails should use a curated color palette that works on both light and dark backgrounds:

```python
GRAPH_COLORS = [
    "#4C9EEB",  # blue
    "#E55B5B",  # red
    "#50C878",  # green
    "#F5A623",  # orange
    "#9B59B6",  # purple
    "#1ABC9C",  # teal
    "#E67E22",  # amber
    "#3498DB",  # light blue
    "#E74C3C",  # crimson
    "#2ECC71",  # emerald
]
```

### 5.2 Keyboard Navigation

| Context | Shortcut | Action |
|---|---|---|
| Global | `Ctrl+1`, `Ctrl+2`, ... | Switch to tab by position |
| Global | `Ctrl+T` | Open the `[+]` tab menu |
| Changes tab | `↑` / `↓` | Navigate file list |
| Changes tab | `Space` | Toggle checkbox on focused file |
| Changes tab | `Ctrl+Enter` | Commit (if message is non-empty and files are checked) |
| History tab | `↑` / `↓` | Navigate commits |
| History tab | `Enter` | Open detail panel for focused commit |
| History tab | `Escape` | Close detail panel |

### 5.3 Status Bar

Retain the `QStatusBar` from Phase 1. It shows contextual info:
- After repo switch: `"Opened repository: {name}"`
- After commit: `"Committed {short_sha}"`
- During background operations: `"Fetching…"` / `"Pushing…"`
- Idle: Shows current branch name and ahead/behind count if tracking upstream

### 5.4 Accessibility (SRS §4 NFR)

All UI surfaces must satisfy the SRS accessibility NFR. This section specifies the concrete requirements for each widget area.

| Requirement | Detail |
|---|---|
| **Keyboard navigation** | Every interactive element must be reachable via `Tab` / `Shift+Tab`. Focus order follows visual top-to-bottom, left-to-right order within each tab. Enter/Escape behavior must be consistent: `Enter` activates focused button/item, `Escape` closes dialogs/popups/panels |
| **Screen-reader labels** | All icon-only buttons (`QPushButton` with icon and no visible text) must have an `accessibleName` set: the account icon → "Forge account", the `+` tab button → "Add new tab", the `×` close buttons → "Close tab", the branch dropdown → "Switch branch: {current_branch}" |
| **Accessible descriptions** | The commit button shows dynamic text ("Commit to main") which is already accessible. When disabled, set `accessibleDescription` to explain why ("Enter a commit message" or "Select files to commit") |
| **File list** | Each file row's accessible name must include the change type and full path: "Modified src/main.py, checked" / "Added README.md, unchecked". The select-all checkbox → "Select all files, 3 of 5 selected" |
| **Graph widget** | The commit graph is a custom-painted `QWidget` which is inherently inaccessible to screen readers. Provide a parallel `QTreeView`-based accessible fallback (same data, no visual graph lines) that can be toggled via View menu or auto-activated when a screen reader is detected (`QAccessible::isActive()`) |
| **Tooltips** | All tooltips must also be available as `accessibleDescription` — screen readers can't read tooltips that only appear on hover |
| **Verification** | Before v1 ships: complete a keyboard-only walkthrough of every M-priority flow (add repo, stage files, commit, switch branch, navigate history, open PR) with no mouse. Document any gaps |

> [!IMPORTANT]
> The commit graph accessible fallback is the highest-effort a11y item. It should be implemented alongside the graph widget in Phase 2, not deferred to polish.

### 5.5 Localization Readiness (SRS §4 NFR)

All user-facing strings must be wrapped in `self.tr()` (PySide6's Qt Linguist integration) from day one. This includes:
- Menu item labels
- Button text
- Placeholder text in input fields
- Dialog titles and messages
- Status bar messages
- Empty state text (including the programming quotes — they're user-facing even if decorative)
- Tooltip text

English-only ships in v1, but wrapping now means translation can be done post-v1 without touching every file.

> [!NOTE]
> Do NOT use `tr()` for: log messages (they're developer-facing), internal identifiers, or test assertions.

---

## 6. Secondary UI Surfaces

These features are required by the SRS but don't have a dedicated tab. They're accessed via menus, popups, or embedded sections within existing tabs.

### 6.1 Stash Panel (SRS FR-1.7)

The stash feature provides create/apply/drop operations with named stashes.

#### Access Points
- **Menu**: Edit → Stash Changes (`Ctrl+Shift+S`), Edit → Pop Stash (`Ctrl+Shift+P`)
- **Changes tab**: When the branch switcher detects uncommitted changes during a switch, the "Stash & Switch" button triggers a stash-then-switch sequence

#### Stash Manager Popup

Triggered via Edit → Manage Stashes…

```
┌───────────────────────────────────────┐
│  Stashes                    [×]       │
├───────────────────────────────────────┤
│  stash@{0}: WIP on main        2h ago│
│  stash@{1}: fix: login bug     1d ago│
│  stash@{2}: experiment          3d ago│
├───────────────────────────────────────┤
│  [Apply]  [Pop]  [Drop]              │
└───────────────────────────────────────┘
```

| Property | Detail |
|---|---|
| Widget | `QDialog` (modal) |
| Stash list | `QListWidget` showing all stashes. Each row: stash ref, message (or auto-generated "WIP on {branch}"), relative time |
| Apply | Applies the selected stash without removing it (`engine.stash_apply(index)`) |
| Pop | Applies and removes the selected stash (`engine.stash_pop(index)`) |
| Drop | Removes the selected stash without applying (`engine.stash_drop(index)`) with confirmation: "Drop stash '{message}'? This cannot be undone." |
| Create | Not in this dialog — stash creation is via the menu shortcut or the branch-switch dialog |
| Named stashes | When creating via menu (Ctrl+Shift+S), show a small inline dialog: "Stash message (optional):" with a text field. If left empty, use git's default message |

### 6.2 Clone Dialog (SRS FR-4.1)

Triggered via File → Clone Repository… (`Ctrl+Shift+C`).

```
┌───────────────────────────────────────┐
│  Clone Repository               [×]  │
├───────────────────────────────────────┤
│  URL:                                 │
│  [https://github.com/user/repo.git ]  │
│                                       │
│  Destination:                         │
│  [/home/user/Projects/repo ] [Browse] │
│                                       │
│  ☐ Clone recursively (init submodules)│
│                                       │
│  [     Clone     ]                    │
│                                       │
│  ▓▓▓▓▓▓▓▓░░░░░░░░░ 45% — Receiving…  │
└───────────────────────────────────────┘
```

| Property | Detail |
|---|---|
| Widget | `QDialog` (modal) |
| URL field | `QLineEdit`, placeholder "Repository URL (HTTPS or SSH)". Auto-detects SSH vs HTTPS format |
| Destination | `QLineEdit` + "Browse…" button (opens XDG Desktop Portal folder picker). Default: `~/Projects/{repo_name}` derived from URL. If the directory already exists and is non-empty, show a warning icon |
| Recursive | `QCheckBox` — if checked, calls `engine.clone(url, dest, recursive=True)` to init submodules |
| Progress | `QProgressBar` + status text below the clone button. Progress is parsed from git's clone output (objects received, deltas resolved). Button changes to "Cancel" during clone |
| On success | Add the cloned repo to `repo_registry`, select it in the Changes tab dropdown, close the dialog |
| Error handling | Show inline error text (red) below the URL field for: invalid URL format, network errors, auth failures (suggest checking credentials) |

### 6.3 LFS & Submodule Indicators (SRS FR-6.1, FR-6.2)

> [!NOTE]
> Full LFS and submodule management UI is deferred to Phase 5 (implementation-plan.md). This section specifies the **indicators and basic operations** that should be present in v1's Changes tab.

#### LFS in the Changes Tab

| Element | Behavior |
|---|---|
| File list indicator | Files tracked by LFS show a small "LFS" badge or icon next to their path. This is informational only — the file is still staged/committed normally |
| Diff view | LFS-tracked files that changed show: "LFS tracked file (pointer changed)" instead of a content diff. Display the old and new pointer OIDs side by side |

#### Submodule in the Changes Tab

| Element | Behavior |
|---|---|
| File list indicator | Submodule entries in the changed files list show a "📦" icon or "submodule" badge. Change type shows the commit the submodule moved to |
| Diff view | Submodule changes show: "Submodule {name} updated: {old_sha} → {new_sha}" with a link to the submodule's commit if forge is linked |

### 6.4 Snapshot Browser (SRS FR-10.6)

> [!NOTE]
> The snapshot system's storage and triggers are implemented in Phase 1 (core) and Phase 2 (trigger wiring). This section specifies the **browse/restore UI panel** referenced in Phase 2 step 6 of implementation-plan.md as `ui/snapshots_panel/`.

#### Access Points
- **Menu**: File → Snapshots… or Edit → Browse Snapshots
- **History tab**: A small "Snapshots" button/link in the toolbar area (near the search bar) opens the panel

#### Snapshot Panel

```
┌───────────────────────────────────────┐
│  Snapshots for {repo_name}     [×]    │
├───────────────────────────────────────┤
│  ★ "Before refactor"    manual  2h ago│
│    Auto (on commit)     auto    4h ago│
│    Auto (on commit)     auto    1d ago│
│    Auto (timer)         auto    1d ago│
│    Pre-merge snapshot   auto    2d ago│
├───────────────────────────────────────┤
│  [Restore]  [Delete]                  │
│                                       │
│  ⚠ Restoring will replace your       │
│    working tree and index.            │
└───────────────────────────────────────┘
```

| Property | Detail |
|---|---|
| Widget | `QDockWidget` or `QDialog` (modal). Slide-in panel from the right or a dialog — TBD based on usage frequency |
| Snapshot list | Scrollable list showing: icon (★ for manual, ● for auto), label or trigger type, trigger source (commit/timer/pre-merge/manual), relative timestamp. Manual snapshots are visually distinct (bold, star icon) |
| Restore | Restores working tree + index to the selected snapshot's state. **Does not rewrite branch history** (no force-push risk). Shows a confirmation dialog: "Restore to snapshot from {timestamp}? Your current working tree changes will be replaced." |
| Delete | Deletes the selected snapshot with confirmation. Manual snapshots warn additionally: "This is a manually-named snapshot. Are you sure?" |
| Empty state | "No snapshots yet. Snapshots are created automatically on commit, on a timer, and before risky operations." |

### 6.5 Git Identity Override (SRS FR-1.5, FR-7.1)

The account icon (§3.4) handles **forge** accounts. Git **commit identity** (user.name, user.email) is separate.

| Element | Location | Behavior |
|---|---|---|
| Identity display | Status bar or tooltip on the account icon | Shows "Committing as: {user.name} <{user.email}>" — reads from the repo's git config, falling back to global |
| Override | Accessible via right-click on the account icon → "Change Git Identity…" or via Edit → Git Identity… | Opens a small dialog with name + email fields. Saves to the repo's local `.git/config` (`engine.set_identity(name, email)`) |
| First-use check | On repo open, if `user.name` or `user.email` is unset (neither repo-local nor global), show a non-blocking info banner at the top of the Changes tab: "Git identity not configured. Set your name and email before committing." with a "Configure…" link |

### 6.6 3-Way Merge Tool (SRS FR-3.2)

When a merge or rebase encounters conflicts (`RepoStatus.has_conflicts` is true), clicking the "Resolve Conflicts" button or double-clicking a conflicted file (`⚠ C`) opens the **3-Way Merge Tool**. It is a full-featured visual resolution interface.

#### Layout (3-Pane Top + Result Bottom)

```
┌──────────────────────────────────────────────────────────────────────────────┐
│  Conflict 2 of 5: src/engine.py           [◀ Prev Conflict] [Next Conflict ▶]│
├──────────────────────┬───────────────────────┬───────────────────────────────┤
│  OURS (Current)      │  BASE (Common Ances.) │  THEIRS (Incoming)            │
│  [Accept Current]    │                       │  [Accept Incoming]            │
├──────────────────────┼───────────────────────┼───────────────────────────────┤
│  def calculate():    │  def calculate():     │  def calculate():             │
│      return x * 2    │      return x         │      return x * 10            │
│                      │                       │                               │
├──────────────────────┴───────────────────────┴───────────────────────────────┤
│  RESULT (Editable)   [Accept Both (Ours ➔ Theirs)]   [Accept Both (Theirs ➔ Ours)]│
├──────────────────────────────────────────────────────────────────────────────┤
│  def calculate():                                                            │
│      return x * 2                                                            │
│                                                                              │
├──────────────────────────────────────────────────────────────────────────────┤
│  [Abort Merge]                                 [Mark Resolved & Next ➔]      │
└──────────────────────────────────────────────────────────────────────────────┘
```

| Property | Detail |
|---|---|
| Window/Widget | `QDialog` (maximized/modal) or a dedicated full-screen overlay in the main window |
| Top Splitter | 3 side-by-side synchronized diff panes: **Ours** (local branch changes), **Base** (common ancestor commit), **Theirs** (incoming branch changes). Panes scroll synchronously to keep conflicting lines aligned |
| Bottom Pane | **Result Editor** (`QPlainTextEdit` with syntax highlighting and line numbers). Pre-populated with resolution choice; directly editable by the user for manual edits |
| Conflict Navigation | Toolbar shows "Conflict N of Total" for the current file, with `◀ Prev Conflict` and `Next Conflict ▶` buttons to jump between conflict blocks |
| Resolution Actions | 1. **Accept Current (Ours)**: Replaces conflict block with Ours<br>2. **Accept Incoming (Theirs)**: Replaces conflict block with Theirs<br>3. **Accept Both (Ours ➔ Theirs)**: Inserts both blocks in order<br>4. **Accept Both (Theirs ➔ Ours)**: Inserts both blocks in reverse order<br>5. **Manual Edit**: User edits the Result pane directly |
| File Resolution | Once all conflicts in the file are resolved, clicking **"Mark Resolved & Next"** writes the file to disk, stages it via `engine.stage_file()`, and advances to the next conflicted file |
| Abort Merge | **"Abort Merge"** button with confirmation dialog calls `engine.merge_abort()`, restoring the working copy to pre-merge state |

### 6.7 Reflog Recovery Dialog (SRS FR-1.10)

Accessible via **Edit → Reflog Recovery…** or from the History tab toolbar. Provides the standard safety net for recovering from lost commits, bad rebases, or accidental branch resets.

```
┌──────────────────────────────────────────────────────────────────────────────┐
│  Reflog Recovery for {repo_name}                                        [×]  │
├──────────────────────────────────────────────────────────────────────────────┤
│  Reflog entry                                             Date               │
├──────────────────────────────────────────────────────────────────────────────┤
│  HEAD@{0}  commit: Fix database migration index           10 mins ago        │
│  HEAD@{1}  checkout: moving from feature/login to main    1 hour ago         │
│  HEAD@{2}  rebase -i (finish): returning to refs/heads/...2 hours ago        │
│  HEAD@{3}  commit: WIP on auth backend                    5 hours ago        │
│  HEAD@{4}  reset: moving to HEAD~1                        1 day ago          │
├──────────────────────────────────────────────────────────────────────────────┤
│  SHA: 7a8b9c0d  •  Author: Uzair <uzair@example.com>                         │
│  [View Diff Preview]                                                         │
├──────────────────────────────────────────────────────────────────────────────┤
│  ⚠ Restoring will reset current HEAD to the selected state (git reset --hard)│
│  [Cancel]                                        [Restore Current Branch ➔]  │
└──────────────────────────────────────────────────────────────────────────────┘
```

| Property | Detail |
|---|---|
| Widget | `QDialog` (modal, `800×600`) |
| Entry List | `QTreeView` / `QListWidget` showing pygit2 `repo.head.log()` entries in reverse chronological order (newest first). Columns: Selector (`HEAD@{N}`), Action / Message, Relative Timestamp |
| Selection Preview | Selecting a row shows the commit metadata (SHA, author, full message) and an expandable inline diff preview |
| Restore Action | **"Restore Current Branch"** button triggers `engine.restore_to_ref(sha)`. Shows a prominent confirmation dialog: *"This will reset {current_branch} to {sha} and discard any uncommitted working tree changes (`git reset --hard`). Are you sure?"* |
| Guard | Disabled if `RepoStatus.has_conflicts` is true (must resolve or abort conflict first) |

### 6.8 Remote Management Dialog (SRS FR-4.4)

Accessible via **Edit → Manage Remotes…** or repository settings.

```
┌──────────────────────────────────────────────────────────────────────────────┐
│  Manage Remotes — {repo_name}                                           [×]  │
├─────────────────────────┬────────────────────────────────────────────────────┤
│  Remotes:               │  Remote Details:                                   │
│  ┌───────────────────┐  │  Name:      [origin                 ]              │
│  │ ★ origin          │  │  Fetch URL: [git@github.com:uzair/repo.git       ] │
│  │   upstream        │  │  Push URL:  [git@github.com:uzair/repo.git       ] │
│  │                   │  │  [✓] Same as Fetch URL                             │
│  └───────────────────┘  │                                                    │
│  [+ Add]  [- Remove]    │  [Test Connection] [Fetch Prune]                   │
├─────────────────────────┴────────────────────────────────────────────────────┤
│  [Close]                                                 [Save Changes]      │
└──────────────────────────────────────────────────────────────────────────────┘
```

| Property | Detail |
|---|---|
| Widget | `QDialog` (modal) |
| Remotes List | Left pane listing all configured remotes (`origin`, `upstream`, etc.) with default/starred indicator |
| Remote Details | Right pane editing `name`, `fetch_url`, `push_url` (with auto-sync toggle) |
| Actions | 1. **Add Remote**: Input name + URL, validates URL format<br>2. **Remove Remote**: Prompts confirmation before removing<br>3. **Test Connection**: Runs background check against the remote via `workers.py`<br>4. **Fetch & Prune**: Fetches remote refs and prunes deleted tracking branches |

### 6.9 On-Demand Backup & Restore Dialog (SRS FR-8.1–8.4)

Accessible via **File → Backup Repository…** and **File → Restore from Backup…**. Provides manual, point-in-time disaster-recovery snapshots to external storage (USB drives, mounted NAS shares, or separate disks).

```
┌──────────────────────────────────────────────────────────────────────────────┐
│  Backup Repository                                                      [×]  │
├──────────────────────────────────────────────────────────────────────────────┤
│  Source Repository:                                                          │
│  /home/uzair/Projects/wrench (Branch: main, 142 commits)                     │
│                                                                              │
│  Destination Backup Folder (USB / NAS / Disk):                               │
│  [/run/media/uzair/USB_BACKUP/wrench_backups          ] [Browse Portal...]   │
│                                                                              │
│  Backup Options:                                                             │
│  [✓] Include uncommitted working tree changes (as stash bundle)              │
│  [✓] Compress archive (.tar.gz)                                              │
│                                                                              │
│  [     Create Backup Now     ]                                               │
│  ▓▓▓▓▓▓▓▓▓▓▓▓▓▓░░░░ 70% — Creating bundle...                                 │
└──────────────────────────────────────────────────────────────────────────────┘
```

| Property | Detail |
|---|---|
| Widget | `QDialog` (modal) |
| Destination | Uses XDG Desktop Portal file picker (folder select mode) to securely access removable drives/NAS paths under Flatpak sandbox |
| Execution | Generates a full git bundle (`git bundle create`) + optional untracked changes archive via `workers.run_in_background` with live progress bar |
| Restore Flow | **File → Restore from Backup…** opens a restore wizard: selects backup file/folder, validates bundle integrity, and unpacks to a chosen target folder with automatic registration in `repo_registry` |

---

## 7. File/Component Mapping

Summary of new and modified files for implementation:

| File | Status | Purpose |
|---|---|---|
| `src/wrench/ui/main_window.py` | **REWRITE** | New layout: menu bar + tab system + tab content + dialog triggers |
| `src/wrench/ui/tabs/tab_bar.py` | **NEW** | Custom tab bar widget (vertical/horizontal, add/close/reorder, hybrid model) |
| `src/wrench/ui/tabs/changes_tab.py` | **NEW** | Changes tab: repo selector, branch switcher, file list, commit section, diff view |
| `src/wrench/ui/tabs/history_tab.py` | **NEW** | History tab: graph widget + search bar + detail panel container |
| `src/wrench/ui/tabs/pr_list_tab.py` | **NEW** | PR/MR list tab: category tab listing PRs for the current repo's forge |
| `src/wrench/ui/tabs/issue_list_tab.py` | **NEW** | Issues list tab: category tab listing issues for the current repo's forge |
| `src/wrench/ui/tabs/pr_detail_tab.py` | **NEW** | PR detail tab: dynamic tab showing a single PR's details (opened from PR list) |
| `src/wrench/ui/tabs/issue_detail_tab.py` | **NEW** | Issue detail tab: dynamic tab showing a single issue's details (opened from issues list) |
| `src/wrench/ui/commit_graph/graph_widget.py` | **NEW/REWRITE** | Visual commit graph with `QPainter` rendering + accessible tree fallback |
| `src/wrench/ui/commit_graph/layout.py` | **NEW** | Pure-Python lane assignment algorithm (testable without Qt) |
| `src/wrench/ui/commit_graph/detail_panel.py` | **NEW** | Slide-in commit detail panel |
| `src/wrench/ui/merge_tool/merge_dialog.py` | **NEW** | Visual 3-way merge conflict resolution tool (§6.6, FR-3.2) |
| `src/wrench/ui/dialogs/clone_dialog.py` | **NEW** | Clone Repository dialog (§6.2, FR-4.1) |
| `src/wrench/ui/dialogs/stash_dialog.py` | **NEW** | Stash Manager dialog (§6.1, FR-1.7) |
| `src/wrench/ui/dialogs/reflog_dialog.py` | **NEW** | Reflog History & Recovery dialog (§6.7, FR-1.10) |
| `src/wrench/ui/dialogs/remotes_dialog.py` | **NEW** | Remotes Configuration dialog (§6.8, FR-4.4) |
| `src/wrench/ui/dialogs/backup_dialog.py` | **NEW** | Backup & Restore dialogs (§6.9, FR-8.1–8.4) |
| `src/wrench/ui/dialogs/identity_dialog.py` | **NEW** | Git Identity override dialog (§6.5, FR-1.5) |
| `src/wrench/ui/snapshots_panel.py` | **NEW** | Snapshot browse/restore panel (§6.4, FR-10.6) |
| `src/wrench/ui/widgets/branch_switcher.py` | **NEW** | Branch indicator/switcher widget (§3.2b, FR-1.6) |
| `src/wrench/ui/diff_view/diff_widget.py` | **KEEP** | Reused as-is in Changes tab, History detail panel, and PR detail tab |
| `src/wrench/ui/sidebar/` | **DEPRECATE** | Replaced by repo dropdown in Changes tab. Remove in Phase 1.5 |
| `src/wrench/ui/workers.py` | **KEEP** | Background thread infrastructure unchanged |

---

## 8. Implementation Order

> [!IMPORTANT]
> Each step must be completed and visually verified before moving to the next. Do not skip ahead.

1. **Menu bar + window chrome** — Wire up `QMenuBar` with all items from §1.2. Wire quit guards and geometry persistence.
2. **Tab bar widget** — Build the `TabBar` with vertical/horizontal toggle, add button, close button, reordering, and hybrid model support (category singletons + dynamic detail tabs + per-repo dedup).
3. **Changes tab — left column** — Repo dropdown, branch switcher widget (`🌿 main ▾`), unified file list with checkboxes, tri-state select-all toggle.
4. **Changes tab — commit section** — Account icon, commit message, description, amend toggle, commit button with branch name.
5. **Changes tab — right column** — Integrate existing `DiffView`. Implement empty state with motivating quotes and binary file handling.
6. **Changes tab — wiring** — Connect file list selection → diff view. Connect commit button → staging + commit flow. Connect repo dropdown → repo switching. Connect branch switcher → branch operations.
7. **Stash dialog** — Implement the Stash Manager (§6.1). Wire to Edit menu shortcuts.
8. **Clone dialog** — Implement the Clone dialog (§6.2). Wire to File → Clone with progress bar.
9. **Reflog recovery dialog** — Implement the Reflog dialog (§6.7). Wire to Edit → Reflog Recovery.
10. **Identity dialog** — Implement git identity override (§6.5). Wire first-use check on repo open.
11. **History tab — graph layout algorithm** — Implement `layout.py` with lane assignment. Unit test without Qt.
12. **History tab — graph rendering** — Implement `CommitGraphWidget` with `QPainter`. Virtual scrolling. Accessible tree fallback.
13. **History tab — hover tooltip** — Implement commit hover preview.
14. **History tab — click detail panel** — Implement slide-in panel with animation, diff view, close behavior.
15. **History tab — search/filter bar** — Implement debounced message search, author filter, date range, and path filter.
16. **3-Way Merge Tool** — Implement the 3-pane + result conflict resolution dialog (§6.6). Wire to conflict banner and rebase/merge conflict states.
17. **Snapshot panel** — Implement browse/restore UI (§6.4). Wire to menu.
18. **Remotes & Backup dialogs** — Implement Remotes Manager (§6.8) and Backup/Restore dialogs (§6.9).
19. **Polish** — Keyboard shortcuts, theme consistency, status bar updates, accessibility audit, localization check (`tr()`), edge cases.

