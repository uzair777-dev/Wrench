# Wrench v2 Implementation Plan (v0.7 — 11-Forge Ecosystem \[Codeberg, Azure Repos, Radicle, Gerrit, SourceHut, Tangled\], Phased Pipeline, Diff Virtualization & Zero-Shortcut Security Edition)

**Scope source:** [srs.md](https://github.com/uzair777-dev/Wrench/blob/master/dev/planning/srs.md) v0.4 §3 rows marked **D (v2)** (`FR-1.13`–`1.18`, `FR-2.4`–`2.10`, `FR-3.4`–`3.9`, `FR-4.5`, `FR-5.10`–`5.13`, `FR-6.3`–`6.4`, `FR-7.4`, `FR-8.3`–`8.12`, `FR-9.1`–`9.5`, `FR-10.5`–`10.6`, `FR-11.3`, `FR-12.1`, `FR-12.4`, and `NFR-5`) and [ui-planning.md](https://github.com/uzair777-dev/Wrench/blob/master/dev/planning/ui-planning.md) v0.3 (§1–§8).

**Purpose of this edition:** This document is engineered so that **any developer or automated coding model (including smaller / lower-tier models)** can execute every phase from `VP-0` through `VP-23` mechanically, step-by-step, without making architectural guesses, missing [ui-planning.md](https://github.com/uzair777-dev/Wrench/blob/master/dev/planning/ui-planning.md) widget specifications, forgetting user configurability, or skipping component-specific performance/memory optimizations.

## 0\. Mandatory Execution Protocol for Coding Models (Read Before Writing Any Code)

Every executor (human or AI model) MUST obey the following 12 rules verbatim. **Do not improvise, do not skip steps, and do not invent your own architecture:**

1. **Strict Phase Sequence (`VP-0` \-\> `VP-1` \-\> ... \-\> `VP-23`):** Never start Phase `VP-N` until Phase `VP-(N-1)`'s completion gates and acceptance checks pass 100%. `VP-0` MUST be completed first because every phase `VP-1`..`VP-23` registers its settings keys into `VP-0`'s `SettingsRegistry` and reuses `VP-0`'s UI infrastructure (`UndoToastWidget`, `LazyTabContainer`, `SettingsDialog`).  
2. **Mandatory `ui-planning.md` Cross-Check Before Writing Any UI Code:**  
   - Every phase below includes a **`Mandatory UI Spec & Optimization Reference`** block pointing to exact sections and step numbers in [ui-planning.md](https://github.com/uzair777-dev/Wrench/blob/master/dev/planning/ui-planning.md) (e.g. `ui-planning.md §6.11, §8 Step 26`).  
   - In `Step 0` of every phase, you MUST open and read the cited `ui-planning.md` sections and implement the exact widget layouts, keyboard shortcuts, `⚙` jump-to-setting header buttons, and `CliCommandPreviewBar` footers specified there.  
3. **Mandatory Component-Specific Optimizations (`ui-planning.md §5.5 OPT-1..OPT-6`):**  
   - Every phase below contains a **`Mandatory Optimizations Reminder for Lower-Tier Models`** block. You MUST implement every optimization listed in that block:  
     - **`OPT-1` (Lazy Page & Tab Instantiation):** Never instantiate unselected `SettingsDialog` category pages or hidden workspace tabs (`HistoryTab`, `PRListTab`, `IssueListTab`) at startup; construct them via factory callables only on first selection.  
     - **`OPT-2` (`150ms` Debounced Auto-Save):** Preferences auto-save without a Save button. Continuous inputs (`QSpinBox`, `QLineEdit`) MUST debounce writes through a `150ms` single-shot `QTimer` so rapid typing/spinning writes to SQLite only once.  
     - **`OPT-3` (Delta-Only Settings Snapshot & Undo/Redo Stack):** Whenever `SettingsRegistry.set(key, new_val, repo_path)` changes a setting, insert **only that single changed key's delta** `(repo_path, key, old_value_json, new_value_json)` into the 100-row ring buffer table `settings_undo_log` so `Ctrl+Z` / `Ctrl+Y` and the Settings History popover can revert mistakes with zero table-copy overhead.  
     - **`OPT-4` (SQLite `WAL` Mode & Batched Transactions):** Enable `PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL;` on `wrench.db` and batch multi-row writes with `executemany()`.  
     - **`OPT-5` (Bounded `5000`\-Line Ring-Buffer & `50ms` Batch Flush for Log Drawers):** Streaming output drawers (`HookOutputDrawer`, `CILogDrawer`, `ActivityLog`) MUST set `setMaximumBlockCount(5000)` and buffer incoming stdout lines into `50ms` `QTimer` flush ticks so verbose scripts never freeze the GUI thread.  
     - **`OPT-6` (Monotonic Worker Generation Tokens):** Every async UI query (`DiffWidget`, `CommitGraphWidget`, `BlameViewerDialog`, `PRReviewOverlay`) MUST attach an incrementing `request_id: int` and discard worker results if `request_id != self._latest_request_id`.  
4. **Zero-Impact Feature Toggle Rule ("We Do Not Forget the User"):**  
   - Every single feature in Wrench (both existing v1 features retrofitted in `VP-0` and new v2 features in `VP-1`..`VP-23`) MUST have its exact `SettingSpec` entries registered in `src/wrench/storage/settings_registry.py`.  
   - Every backend method for an optional feature MUST check `if not self.settings.get_bool("<key>", repo_path=repo_path): return <safe_empty_default>` on its very first line so that a disabled feature consumes **zero CPU, disk I/O, subprocesses, or network calls**.  
   - Every UI widget, tab, toolbar button, sidebar section, badge, or context-menu item for a toggleable feature MUST connect to `self.settings.setting_changed.connect(self._on_setting_changed)` and call `widget.setVisible(self.settings.get_bool("<key>", repo_path=self.repo_path))` so toggling a setting off in Preferences (`Ctrl+,`) hides the UI immediately without requiring an app restart.  
5. **Strict 3-Tier Layering (`ARCHITECTURE.md` §1.2):**  
   - `src/wrench/ui/**` MUST NEVER import `pygit2`, `subprocess`, `sqlite3`, or `httpx`. UI widgets may only call `src/wrench/core/engine.py`, `src/wrench/forge/registry.py`, and `src/wrench/storage/settings_registry.py`.  
6. **Pre-Operation Safety Snapshot & Global Undo Toast Rule (`ARCHITECTURE.md` §1.4, `ui-planning.md §1.4`):**  
   - Every destructive or history-rewriting method in `core/engine.py` (`reset`, `rebase`, `cherry_pick`, `revert`, `stash_drop`, `bisect_reset`, `am`, `restack`) MUST call `self.snapshots.maybe_create_safety_snapshot(repo_path, operation_name)` before invoking `write_ops`, and trigger `UndoToastWidget` (`src/wrench/ui/widgets/undo_toast.py`, `ui-planning.md §1.4`) offering a 1-click `[Undo (Ctrl+Z)]` button.  
7. **Exact File Paths & Signatures Only (`ui-planning.md §7`):** Use the exact repository file paths (`src/wrench/ui/commit_graph/graph_widget.py`, `src/wrench/ui/diff_view/diff_widget.py`, `src/wrench/ui/merge_tool/merge_dialog.py`, `src/wrench/ui/tabs/issue_list_tab.py`, `src/wrench/ui/dialogs/reflog_dialog.py`, `src/wrench/ui/snapshots_panel/__init__.py`, etc.).  
8. **No New Third-Party Pip Dependencies:** Do NOT add any new packages to `pyproject.toml`.  
9. **No Stubs, `pass`, `TODO`, or `NotImplementedError`:** Every function and UI handler must be complete.  
10. **Run Verification Gates After Every Step:** Run each step's exact `pytest` command and never weaken tests.  
11. **No Drive-By Refactoring:** Modify only the files scoped to the current step.

## 0.A Master 6-Stage Phased Delivery Pipeline & Dependency Architecture (Modeled on `implementation-plan.md`)

To ensure lower-tier coding models never lose track of dependencies across the 26 v2 phases (`VP-0` through `VP-26`), execution is organized into **6 sequential Macro Release Stages (`Stage 1`–`Stage 6`)**. No phase in `Stage K+1` may begin until the **Stage-Gate Regression Command** for `Stage K` passes 100%:

```
[STAGE 1: Foundation, Configurability & Zero-Shortcut Guardrails]
   └── VP-0 (SettingsRegistry, SQLite WAL, Delta-Only Settings Undo OPT-3, LazyTabContainer OPT-1, UndoToastWidget, test_no_shortcuts_guard.py)
         │
         ▼
[STAGE 2: Core Local History Rewriting, Worktrees, Submodules & Commit Ergonomics]
   ├── VP-1 (Multi-Commit Cherry-Pick, Revert, Sequencer Banner & Visual Reset Mode Picker + CliCommandPreviewBar)
   ├── VP-2 (Visual Interactive Rebase & GIT_SEQUENCE_EDITOR Helper)
   ├── VP-3 (Git Worktrees UI, Path Templates, Cross-Worktree Cherry-Pick, Bare-Repo Worktree Hub & Named Sessions)
   ├── VP-4 (Git Submodules Lifecycle, Dirty Badges & Fast .gitmodules Short-Circuit)
   └── VP-5 (Commit Message Templates & Cached Co-Author Pill Completer)
         │
         ▼
[STAGE 3: Multi-Forge Collaboration, 5-Stage Mirror Resolution, Combined Mirror History & Virtualized Diff Engine]
   ├── VP-6 (PR Inline Code Review Overlay, ETag Caching, 1-Click PR Checkout & 5,000-Line Ring-Buffer CILogDrawer OPT-5)
   ├── VP-7 (Lazy-Loaded IssueListTab OPT-1 & Zero-Latency SQLite # IssueCompleter OPT-4)
   ├── VP-8 (Multi-Account Directory Prefix Router & Per-Repo GIT_SSH_COMMAND Binding)
   ├── VP-9 (Custom Self-Hosted Forge Domain Mapper & SourceForge Allura Adapter)
   ├── VP-26 (Extended 6-Forge Suite: Codeberg, Azure Repos, Radicle P2P, Gerrit refs/for/, SourceHut GraphQL & Tangled ATProto)
   ├── VP-25 (5-Stage Mirror Resolution Engine OPT-7, Root-Commit Fingerprinting & Combined Multi-Hosting Mirror DAG in CommitGraphWidget)
   ├── VP-10 (Zero-Copy Virtualized DiffLineModel OPT-8, 512-Line LRU Highlighter, Split Diff Ctrl+D, Minimap, Sticky Header & External Tools)
   ├── VP-11 (Debounced Pickaxe -S/-G Search OPT-6 & Visual Reflog Time-Travel Inspector)
   └── VP-12 (Git LFS Lock Manager & .gitattributes Pattern Editor with Fast LFS Detection)
         │
         ▼
[STAGE 4: Linux Desktop Integration, Scheduled Safety Snapshots & Distro Packaging]
   ├── VP-13 (Lazy QSystemTrayIcon Manager & XDG Global Shortcuts)
   ├── VP-14 (Mtime-Deduplicated Scheduled Safety Stash Scheduler & Snapshot Restore Browser)
   └── VP-15 (XDG Secret Portal Fallback, Ephemeral Memory Mode & Arch AUR / Debian / Fedora RPM Packaging)
         │
         ▼
[STAGE 5: Monorepo Scale, Hydrated Git Hooks, GPG/SSH Signing, Visual Bisect & Stacked Branches]
   ├── VP-16 (Partial Clone --filter=blob:none, Lazy SparseCheckoutDialog, Adaptive Inotify Fallback & 100k+ Commit Graph Virtualization)
   ├── VP-17 (Startup-Cached Login-Shell PATH Hook Runner, core.hooksPath Discovery, Ring-Buffer HookOutputDrawer & --no-verify Controls)
   ├── VP-18 (GPG & SSH Commit/Tag Signing, Unix-Socket Askpass Bridge, Viewport-Batched Signature Badges & Hover X-Ray Cards)
   ├── VP-19 (Interactive git bisect Visual Wizard, O(1) Frozenset Graph Dimming & Async bisect run Script Controller)
   └── VP-20 (Stacked Branches via Native git rebase --update-refs, Squash-Merge --onto Recovery, Hunk-to-Commit Routing & Stacked PR Sync)
         │
         ▼
[STAGE 6: Code Archaeology, Granular Stash/Skip-Worktree, Power Tools & 2-Tier Progressive Help]
   ├── VP-21 (Interactive Blame Heatmap Gutter, .git-blame-ignore-revs & Context-Menu git log -L Line History Drawer)
   ├── VP-22 (Granular Stash Modes --staged/--keep-index, Explicit refs/stash@{n} Disambiguation & --skip-worktree Panel)
   ├── VP-23 (Conflict Resolution Memory git rerere Banner, format-patch/am Mailboxes & Pre-Indexed Ctrl+K Command Palette + Custom Actions)
   └── VP-24 (2-Tier Progressive Disclosure Help System: Singleton RichHelpTooltipManager, 25 Offline Topics & Searchable HelpCenterDialog F1)
```

&nbsp;

## 0.B Mandatory 8-Gate Per-Phase Execution Pipeline (No Skipping Allowed)

Every single phase (`VP-0` through `VP-26`) MUST be executed by following this exact 8-gate pipeline in order. A lower-tier model MUST NOT jump straight to writing UI code or skip security/optimization gates:

| Pipeline Gate | Gate Name | Exact Action Required Before Proceeding to Next Gate |
| :---- | :---- | :---- |
| **Gate G1** | **Repo & UI Spec Reconciliation (`Step 0`)** | Run the phase's `Step 0` inspection commands and open the cited `ui-planning.md §x.y` section and `srs.md FR-x.y` rows. Verify all existing imports and method signatures. |
| **Gate G2** | **SQLite DDL & `SettingSpec` Registration** | Add any new SQLite tables to `wrench.db` (using `CREATE TABLE IF NOT EXISTS` and parameterized queries `SEC-5`) and register all phase `SettingSpec` entries (with `parent_toggle_key` and `help_topic_id`) in `src/wrench/storage/settings_registry.py`. |
| **Gate G3** | **Core Plumbing & Security Hardening (`SEC-1`–`SEC-7`)** | Implement read operations in `src/wrench/core/read_ops.py` (or dedicated core module) and write operations in `src/wrench/core/write_ops.py` with `shell=False`, mandatory `--` path/ref delimiters (`SEC-1`), URL scheme validation (`SEC-2`), secret redaction (`SEC-3`), and pre-op safety snapshots (`maybe_create_safety_snapshot`). |
| **Gate G4** | **Zero-Impact Feature-Disable Short-Circuit** | Add `if not self.settings.get_bool("<key>", repo_path): return <empty_default>` as the **very first line** of every optional backend method, worker, and timer so disabled features consume zero CPU, I/O, or RAM (`NFR-5`). |
| **Gate G5** | **Mandatory Component Optimizations (`OPT-1`–`OPT-8`)** | Implement every optimization listed in the phase's `Mandatory Optimizations Reminder` block (lazy instantiation `OPT-1`, `150ms` debounce `OPT-2`, delta undo `OPT-3`, SQLite `WAL` `OPT-4`, `5000`\-line ring buffer `OPT-5`, `request_id` generation tokens `OPT-6`, `blake2b` mirror cache `OPT-7`, or virtualized diff array `OPT-8`). |
| **Gate G6** | **PySide6 UI Widget, `⚙` Jump & `?` Help Wiring** | Build the UI widget/dialog in `src/wrench/ui/` (never importing `pygit2`, `subprocess`, `sqlite3`, or `httpx`), connect `settings.setting_changed` for instant runtime show/hide, add the header `⚙` Settings jump button, and call `attach_help_topic(widget, "<topic_id>")`. |
| **Gate G7** | **Phase Unit & UI Pytest Gate** | Run the phase's `pytest` completion gates (`tests/core/...` and `tests/ui/...`). Fix any failures in implementation code without weakening tests. |
| **Gate G8** | **Automated Anti-Shortcut Security & Optimization Audit** | Run `pytest tests/meta/test_no_shortcuts_guard.py` (defined in `§0.C` below) to statically verify zero security shortcuts, zero layer violations, and zero stubbed functions. |

&nbsp;

## 0.C Non-Negotiable Security & Anti-Shortcut Enforcement Protocol (`SEC-1`–`SEC-7`)

**CRITICAL WARNING FOR LOWER-TIER MODELS:** You are strictly forbidden from taking shortcuts on security or performance optimizations to finish a step faster. Specifically:

1. **`SEC-1` (Git Argument Injection & Subprocess Safety):** Every `subprocess.run` / `Popen` call in `core/` MUST use `shell=False` and pass an explicit `list[str]`. Whenever passing user-controlled or remote-controlled branch names, tag names, commit refs, URLs, or file paths to `git`, you MUST validate that ref/option arguments do not start with `"-"` (unless they are hardcoded flags) and place `"--"` before file paths (`["git", "-C", repo_path, "checkout", "--", file_path]`) to prevent CVE-style `--upload-pack=` or `--output=` argument injection.  
2. **`SEC-2` (Remote/Mirror URL Scheme, `rad://` RID Validation & SSRF Guard):** `src/wrench/core/security_sanitizer.py:validate_remote_url(url, allow_local_http=False)` MUST allow only `https://`, `ssh://`, `git@<host>:<path>` SCP-style URLs, and validated `rad://z[1-9A-HJ-NP-Za-km-z]{20,60}` Radicle RIDs (`VP-26`). It MUST reject `ext::` (which executes arbitrary shell commands in Git\!), `fd::`, `file://` (unless explicitly opening a local repo), and private/loopback HTTP hosts (`127.0.0.0/8`, `169.254.169.254`, `localhost`) unless `allow_local_http=True` is explicitly enabled by the user in Settings.  
3. **`SEC-3` (Automatic Secret & Token Redaction):** Every string displayed in `HookOutputDrawer`, `CILogDrawer`, `ActivityLog`, `CliCommandPreviewBar`, or exception popups MUST pass through `redact_secrets(text: str) -> str`, which scrubs `ghp_*`, `github_pat_*`, `glpat-*`, `Bearer <token>`, and `https://user:token@host` credentials.  
4. **`SEC-4` (`0o600` Temporary File & Socket Permissions):** Every temporary file or Unix socket created by `rebase_sequencer.py` (`VP-2`) or `signing_askpass.py` (`VP-18`) MUST be created inside a directory with mode `0o700` and file mode `0o600` (`os.chmod(path, 0o600)`) so other local users on a shared Linux machine cannot read passphrases or hijack rebase todo lists.  
5. **`SEC-5` (100% Parameterized SQLite Queries):** Every SQL query in `src/wrench/storage/` MUST use `?` parameter binding (`cursor.execute("SELECT ... WHERE key = ?", (key,))`). String formatting (`f"SELECT ... {key}"`) in SQL is strictly banned.  
6. **`SEC-6` (Allowlist-Validated `wrench://` Help URIs):** `HelpCenterDialog` (`VP-24`) MUST validate `wrench://open-setting/<key>` and `wrench://highlight-ui/<widget_id>` against `SettingsRegistry.has_key(key)` and registered widget IDs; never pass URL paths to `subprocess` or `os.system`.  
7. **`SEC-7` (Zero Stubs, Zero `time.sleep` Hacks, Zero Skipped Optimizations):** Never use `pass`, `TODO`, `FIXME`, `NotImplementedError`, or `time.sleep()` in production code.

### Mandatory Automated Guard Test (`tests/meta/test_no_shortcuts_guard.py` — Create in `VP-0 Step 1`)

In `VP-0 Step 1`, create `src/wrench/core/security_sanitizer.py` and `tests/meta/test_no_shortcuts_guard.py` with the following exact verification logic, and run `pytest tests/meta/test_no_shortcuts_guard.py` at the end of **every phase**:

```py
# tests/meta/test_no_shortcuts_guard.py
import ast
import pathlib
import re

SRC_ROOT = pathlib.Path("src/wrench")
UI_ROOT = SRC_ROOT / "ui"
FORBIDDEN_UI_IMPORTS = {"pygit2", "subprocess", "sqlite3", "httpx"}


def test_ui_layer_never_imports_backends_directly() -> None:
    """Enforces ARCHITECTURE.md §1.2 and Rule 5: UI never imports pygit2/subprocess/sqlite3/httpx."""
    for py_file in UI_ROOT.rglob("*.py"):
        tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root_mod = alias.name.split(".")[0]
                    assert root_mod not in FORBIDDEN_UI_IMPORTS, (
                        f"{py_file}: forbidden import {alias.name}"
                    )
            elif isinstance(node, ast.ImportFrom) and node.module:
                root_mod = node.module.split(".")[0]
                assert root_mod not in FORBIDDEN_UI_IMPORTS, (
                    f"{py_file}: forbidden from-import {node.module}"
                )


def test_no_shell_true_or_not_implemented_stubs() -> None:
    """Enforces SEC-1 and SEC-7: No shell=True in core/forge and no NotImplementedError stubs."""
    for py_file in SRC_ROOT.rglob("*.py"):
        source = py_file.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(py_file))
        for node in ast.walk(tree):
            if isinstance(node, ast.Raise) and isinstance(node.exc, ast.Call):
                if getattr(node.exc.func, "id", "") == "NotImplementedError":
                    raise AssertionError(
                        f"{py_file}:{node.lineno} contains NotImplementedError stub"
                    )
            if isinstance(node, ast.Call) and py_file.name != "custom_actions.py":
                for kw in node.keywords:
                    if (
                        kw.arg == "shell"
                        and isinstance(kw.value, ast.Constant)
                        and kw.value.value is True
                    ):
                        raise AssertionError(f"{py_file}:{node.lineno} uses forbidden shell=True")


def test_no_fstring_sql_queries_in_storage() -> None:
    """Enforces SEC-5: SQLite execute() calls must never use JoinedStr (f-strings)."""
    for py_file in (SRC_ROOT / "storage").rglob("*.py"):
        tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and getattr(node.func, "attr", "") in (
                "execute",
                "executemany",
            ):
                if node.args and isinstance(node.args[0], ast.JoinedStr):
                    raise AssertionError(
                        f"{py_file}:{node.lineno} uses forbidden f-string in SQL execute()"
                    )
```

&nbsp;

## 0.D Complete Cross-Document Traceability Matrix (`srs.md` ↔ `ui-planning.md` ↔ `v2-implementation-plan.md`)

| Phase & Stage | `srs.md` & `ui-planning.md` Refs | Target Source Files (`src/wrench/...`) | Optimizations & Security Guards | Verification Gate Command |
| :---- | :---- | :---- | :---- | :---- |
| **VP-0** (Stage 1\) | `FR-13.1`–`13.4`, `NFR-5`, `NFR-6`, `DEC-5`, `DEC-6` · `§1.3`, `§1.4`, `§2.2`, `§5.5`, `§6.11`, `Steps 26–27` | `storage/settings_registry.py`, `core/security_sanitizer.py`, `ui/dialogs/settings_dialog.py`, `ui/widgets/undo_toast.py` | `OPT-1` (Lazy Pages/Tabs), `OPT-2` (`150ms` Auto-Save), `OPT-3` (Delta Undo Stack), `OPT-4` (`WAL`), `SEC-1`–`SEC-7` | `pytest tests/storage/test_settings_registry.py tests/ui/test_settings_dialog.py tests/meta/test_no_shortcuts_guard.py` |
| **VP-1** (Stage 2\) | `FR-2.4`, `FR-3.4` · `§1.4`, `§5.3`, `§6.15`, `Step 28` | `core/read_ops.py`, `core/write_ops.py`, `ui/widgets/cli_preview_bar.py`, `ui/dialogs/reset_dialog.py` | Cached worktree `gitdir`, `SEC-1` `--` delimiters, `SEC-3` CLI preview redaction | `pytest tests/core/test_cherry_pick_revert.py tests/ui/test_reset_and_sequencer_ui.py tests/meta/test_no_shortcuts_guard.py` |
| **VP-2** (Stage 2\) | `FR-3.5`, `FR-10.1` · `§6.16`, `Step 29` | `core/rebase_sequencer.py`, `core/rebase_editor_helper.py`, `ui/dialogs/interactive_rebase_dialog.py` | Bounded `1000`\-commit walk, `SEC-4` `0o600` temp sequence files | `pytest tests/core/test_interactive_rebase.py tests/ui/test_interactive_rebase_dialog.py tests/meta/test_no_shortcuts_guard.py` |
| **VP-3** (Stage 2\) | `FR-1.13`, `FR-1.15`, `FR-1.17` · `§2.1`, `§6.17`, `Step 30` | `core/worktrees.py`, `ui/widgets/worktree_panel.py` | `OPT-6` worker tokens, shared parent ODB cache across worktrees | `pytest tests/core/test_worktrees.py tests/ui/test_worktree_ui.py tests/meta/test_no_shortcuts_guard.py` |
| **VP-4** (Stage 2\) | `FR-1.14` · `§6.3`, `Step 31` | `core/submodules.py`, `ui/widgets/submodule_panel.py` | `< 0.1ms` `.gitmodules` existence check before subprocess spawn | `pytest tests/core/test_submodules.py tests/ui/test_submodule_panel.py tests/meta/test_no_shortcuts_guard.py` |
| **VP-5** (Stage 2\) | `FR-2.5`, `FR-2.6` · `§3.1`, `Step 32` | `core/commit_helpers.py`, `ui/widgets/coauthor_input.py` | `HEAD`\-OID-cached contributor list in memory | `pytest tests/core/test_commit_helpers.py tests/ui/test_commit_templates_coauthors.py tests/meta/test_no_shortcuts_guard.py` |
| **VP-6** (Stage 3\) | `FR-5.10`, `FR-5.13` · `§6.18`, `Step 33` | `forge/capability.py`, `ui/widgets/pr_review_overlay.py` | `OPT-5` (`5000`\-line ring buffer \+ `50ms` flush), HTTP `ETag` caching, `SEC-3` log redaction | `pytest tests/forge/test_pr_inline_review.py tests/ui/test_pr_review_and_ci_logs_ui.py tests/meta/test_no_shortcuts_guard.py` |
| **VP-7** (Stage 3\) | `FR-5.11` · `§2.1`, `§3.1`, `Step 34` | `ui/tabs/issue_list_tab.py`, `ui/widgets/issue_completer.py` | `OPT-1` lazy tab, `OPT-4` batched SQLite issue cache (`< 1ms` `#` lookup) | `pytest tests/forge/test_issues_capability.py tests/ui/test_issues_tab.py tests/meta/test_no_shortcuts_guard.py` |
| **VP-8** (Stage 3\) | `FR-5.12` · `§6.19`, `Step 35` | `credentials/account_router.py`, `ui/dialogs/account_rules_dialog.py` | Prefix-sorted in-memory routing table, `NFR-3` keyring-only tokens | `pytest tests/credentials/test_multi_account.py tests/ui/test_account_rules_dialog.py tests/meta/test_no_shortcuts_guard.py` |
| **VP-9** (Stage 3\) | `FR-6.3`, `FR-6.4` · `§6.11`, `Step 36` | `forge/adapters/sourceforge.py`, `forge/registry.py` | Lazy entry-point loading, `SEC-2` HTTPS enforcement | `pytest tests/forge/test_sourceforge_adapter.py tests/ui/test_custom_forge_domains_ui.py tests/meta/test_no_shortcuts_guard.py` |
| **VP-10** (Stage 3\) | `FR-8.3`, `FR-8.4`, `FR-8.14`, `DEC-9` · `§3.2`, `§3.3`, `Step 37` | `core/external_tools.py`, `ui/diff_view/diff_widget.py` | `OPT-8` (`PatchByteIndex` `array('I')` \+ `DiffLineModel` \+ `512`\-line LRU cache \+ `35ms` coalescer) | `pytest tests/core/test_external_tools_and_diff.py tests/ui/test_diff_enhancements.py tests/meta/test_no_shortcuts_guard.py` |
| **VP-11** (Stage 3\) | `FR-9.1`–`9.3` · `§4.1`, `§6.7`, `Step 38` | `core/reflog_ops.py`, `ui/dialogs/reflog_dialog.py` | `200ms` search debounce \+ `OPT-6` generation tokens, `pygit2` native reflog | `pytest tests/core/test_reflog_and_search.py tests/ui/test_reflog_and_search_ui.py tests/meta/test_no_shortcuts_guard.py` |
| **VP-12** (Stage 3\) | `FR-4.5` · `§6.3`, `Step 39` | `core/lfs_ops.py`, `ui/dialogs/lfs_locks_dialog.py` | Mtime-cached `.gitattributes` `filter=lfs` pre-check | `pytest tests/core/test_lfs_locks.py tests/ui/test_lfs_locks_dialog.py tests/meta/test_no_shortcuts_guard.py` |
| **VP-13** (Stage 4\) | `FR-12.1` · `§1.1`, `§1.3`, `Step 40` | `ui/tray_manager.py`, `ui/main_window.py` | Zero `QSystemTrayIcon` allocation when `desktop.system_tray.enabled == False` | `pytest tests/ui/test_system_tray.py tests/meta/test_no_shortcuts_guard.py` |
| **VP-14** (Stage 4\) | `FR-8.5` · `§6.4`, `Step 41` | `core/snapshots.py`, `ui/snapshots_panel/__init__.py` | `.git/index` mtime \+ OID deduplication before running `git stash create` | `pytest tests/core/test_scheduled_backups.py tests/ui/test_snapshots_dialog.py tests/meta/test_no_shortcuts_guard.py` |
| **VP-15** (Stage 4\) | `FR-12.4` · `§6.11`, `Step 42` | `credentials/portal_secret.py`, `packaging/aur/PKGBUILD`, `packaging/debian/` | Session-cached D-Bus secrets, `NFR-3` no plaintext fallback | `pytest tests/packaging/test_portal_secret.py tests/packaging/test_distro_manifests.py tests/meta/test_no_shortcuts_guard.py` |
| **VP-16** (Stage 5\) | `FR-1.16`, `FR-1.18`, `FR-7.4`, `FR-11.3` · `§4.3`, `§6.2`, `§6.20`, `Step 43` | `core/sparse_checkout.py`, `ui/dialogs/sparse_checkout_dialog.py`, `ui/commit_graph/graph_widget.py` | Viewport-only painting \+ `QPixmapCache` badges \+ lazy tree expansion \+ `.git`\-only watch fallback | `pytest tests/core/test_sparse_checkout.py tests/ui/test_large_graph_virtualization.py tests/meta/test_no_shortcuts_guard.py` |
| **VP-17** (Stage 5\) | `FR-2.7`, `FR-2.8` · `§3.1`, `Step 44` | `core/hook_env.py`, `ui/widgets/hook_output_drawer.py` | Startup-cached shell `PATH`, `OPT-5` `5000`\-line ring buffer, `SEC-3` log redaction | `pytest tests/core/test_hook_env.py tests/ui/test_hook_runner_ui.py tests/meta/test_no_shortcuts_guard.py` |
| **VP-18** (Stage 5\) | `FR-2.9`, `FR-2.10` · `§4.2`, `§6.5`, `Step 45` | `core/signing_ops.py`, `credentials/signing_askpass.py`, `ui/commit_graph/graph_widget.py` | Viewport-batched `git log --no-walk` verification \+ `10000`\-entry LRU cache, `SEC-4` `0o600` socket | `pytest tests/core/test_commit_signing.py tests/ui/test_signing_badges_ui.py tests/meta/test_no_shortcuts_guard.py` |
| **VP-19** (Stage 5\) | `FR-3.6` · `§6.21`, `Step 46` | `core/bisect_ops.py`, `ui/widgets/bisect_banner.py` | $O(1)$ `frozenset` candidate lookup in `paintEvent`, `OPT-6` worker tokens | `pytest tests/core/test_bisect_ops.py tests/ui/test_bisect_wizard.py tests/meta/test_no_shortcuts_guard.py` |
| **VP-20** (Stage 5\) | `FR-3.7`, `FR-3.8`, `FR-5.13` · `§6.22`, `Step 47` | `core/stacks.py`, `ui/widgets/stack_panel.py` | Single-pass `git rebase --update-refs`, non-invasive SQLite stack metadata | `pytest tests/core/test_stacked_branches.py tests/ui/test_stacked_branches_ui.py tests/meta/test_no_shortcuts_guard.py` |
| **VP-21** (Stage 6\) | `FR-9.4`, `FR-9.5` · `§6.23`, `Step 48` | `core/blame_ops.py`, `ui/widgets/blame_viewer.py` | `(repo, path, oid)` blame cache \+ empty-email guard \+ viewport-only gutter painting | `pytest tests/core/test_blame_and_line_history.py tests/ui/test_blame_and_line_history_ui.py tests/meta/test_no_shortcuts_guard.py` |
| **VP-22** (Stage 6\) | `FR-10.5`, `FR-10.6`, `DEC-4` · `§3.1`, `§6.1`, `Step 49` | `core/stash_ops.py`, `ui/widgets/skip_worktree_panel.py` | Explicit `refs/stash@{n}` addressing \+ `.git/index` mtime guard on `ls-files -v` | `pytest tests/core/test_granular_stash_and_skip_worktree.py tests/ui/test_granular_stash_ui.py tests/meta/test_no_shortcuts_guard.py` |
| **VP-23** (Stage 6\) | `FR-3.9`, `FR-8.6`, `FR-8.7` · `§6.6`, `§6.24`, `Step 49` | `core/custom_actions.py`, `ui/dialogs/command_palette.py` | Pre-indexed `< 5ms` `Ctrl+K` palette, `SEC-1` `shlex.quote()` on custom action variables | `pytest tests/core/test_rerere_patches_custom_actions.py tests/ui/test_command_palette.py tests/meta/test_no_shortcuts_guard.py` |
| **VP-24** (Stage 6\) | `FR-8.13`, `FR-14.4`, `DEC-7` · `§5.6`, `§6.25`, `Step 50` | `ui/help_topics.py`, `ui/widgets/rich_help_tooltip.py`, `ui/dialogs/help_center_dialog.py` | Singleton tooltip (`0 KB` per-widget overhead), `OPT-1` lazy topic index, `SEC-6` URI allowlist | `pytest tests/ui/test_rich_help_tooltip.py tests/ui/test_help_center_dialog.py tests/meta/test_no_shortcuts_guard.py` |
| **VP-25** (Stage 3\) | `FR-3.10`, `FR-4.6`, `FR-4.7`, `DEC-8` · `§4.2.5`, `§5.5 OPT-7`, `§6.26`, `Step 51` | `core/mirror_ops.py`, `forge/mirror_resolver.py`, `ui/dialogs/mirror_manager_dialog.py`, `ui/commit_graph/graph_widget.py` | `OPT-7` (`blake2b` ref-digest cache `< 0.5ms`, root-OID fingerprinting, parallel `ls-remote`, `120s` circuit breaker), `SEC-2` URL guard | `pytest tests/core/test_mirror_resolution_and_dag.py tests/ui/test_mirror_manager_ui.py tests/meta/test_no_shortcuts_guard.py` |
| **VP-26** (Stage 3\) | `FR-6.5`–`6.10`, `DEC-10` · `§6.18`, `§6.27`, `Step 52` | `forge/adapters/codeberg.py`, `azure_repos.py`, `radicle.py`, `gerrit.py`, `sourcehut.py`, `tangled.py`, `ui/dialogs/forge_review_push_dialog.py` | Gerrit zero-copy `)]}'` slice, SourceHut batched GraphQL, Radicle local COB ref cache, Tangled DID-\>Knot LRU cache, `SEC-1`/`SEC-2` | `pytest tests/forge/test_extended_forges_vp26.py tests/ui/test_forge_review_push_ui.py tests/meta/test_no_shortcuts_guard.py` |

&nbsp;

## Summary Matrix of All v2 Phases (`VP-0` – `VP-26`)

| Phase | Title | SRS Scope | Primary Files Created / Modified |
| :---- | :---- | :---- | :---- |
| **VP-0** | Universal Settings Registry, v1 Feature Retrofits & Searchable Preferences Center | `FR-8.8`–`8.11`, `NFR-5` | `src/wrench/storage/settings_registry.py`, `src/wrench/ui/dialogs/settings_dialog.py` |
| **VP-1** | Multi-Commit Cherry-Pick, Revert & Visual Reset Mode Picker | `FR-2.4`, `FR-3.4` | `src/wrench/core/write_ops.py`, `src/wrench/ui/dialogs/reset_dialog.py` |
| **VP-2** | Visual Interactive Rebase & Drag-to-Reorder | `FR-3.5`, `FR-10.1` | `src/wrench/core/rebase_sequencer.py`, `src/wrench/ui/dialogs/interactive_rebase_dialog.py` |
| **VP-3** | Git Worktrees UI, Bare-Hub Mode & Cross-Worktree Operations | `FR-1.13`, `FR-1.15`, `FR-1.17` | `src/wrench/core/worktrees.py`, `src/wrench/ui/widgets/worktree_panel.py` |
| **VP-4** | Git Submodules Lifecycle & Batch Sync Manager | `FR-1.14` | `src/wrench/core/submodules.py`, `src/wrench/ui/widgets/submodule_panel.py` |
| **VP-5** | Commit Message Templates & Co-Authors Autocomplete UI | `FR-2.5`, `FR-2.6` | `src/wrench/core/commit_helpers.py`, `src/wrench/ui/widgets/coauthor_input.py` |
| **VP-6** | PR Inline Code Review, Line Comments, 1-Click Checkout & CI Log Streaming | `FR-5.10`, `FR-5.13` | `src/wrench/forge/capability.py`, `src/wrench/ui/widgets/pr_review_overlay.py` |
| **VP-7** | Issue Board / Issue Tracker View & `#` Commit Autocomplete | `FR-5.11` | `src/wrench/ui/tabs/issue_list_tab.py`, `src/wrench/ui/widgets/issue_completer.py` |
| **VP-8** | Multi-Account Switching & Per-Repo Identity/SSH Binding | `FR-5.12` | `src/wrench/credentials/account_router.py`, `src/wrench/ui/dialogs/account_rules_dialog.py` |
| **VP-9** | Custom Forge Domain Registration UI & SourceForge Adapter | `FR-6.3`, `FR-6.4` | `src/wrench/forge/adapters/sourceforge.py`, `src/wrench/forge/registry.py` |
| **VP-10** | Custom External Diff/Merge Tools & Intra-Line / `--color-moved` Diffing | `FR-8.3`, `FR-8.4` | `src/wrench/core/external_tools.py`, `src/wrench/ui/diff_view/diff_widget.py` |
| **VP-11** | Advanced History Search (Pickaxe `-S`/`-G`) & Visual Reflog Inspector | `FR-9.1`–`9.3` | `src/wrench/core/reflog_ops.py`, `src/wrench/ui/dialogs/reflog_dialog.py` |
| **VP-12** | Git LFS Lock Manager & `.gitattributes` Tracked Pattern Editor | `FR-4.5` | `src/wrench/core/lfs_ops.py`, `src/wrench/ui/dialogs/lfs_locks_dialog.py` |
| **VP-13** | System Tray Status Indicator & XDG Global Shortcuts | `FR-12.1` | `src/wrench/ui/tray_manager.py`, `src/wrench/ui/main_window.py` |
| **VP-14** | Scheduled Safety Stash & Background Snapshot Manager | `FR-8.5` | `src/wrench/core/snapshots.py`, `src/wrench/ui/snapshots_panel/__init__.py` |
| **VP-15** | Post-v1 Linux Distro Packaging & XDG Secret Portal Fallback (`VP-15a–d`) | `FR-12.4` | `src/wrench/credentials/portal_secret.py`, `packaging/aur/PKGBUILD`, `packaging/debian/` |
| **VP-16** | Monorepo Engine: Partial Clone, Sparse-Checkout, Adaptive Watcher & 100k+ DAG | `FR-1.16`, `FR-1.18`, `FR-7.4`, `FR-11.3` | `src/wrench/core/sparse_checkout.py`, `src/wrench/ui/dialogs/sparse_checkout_dialog.py` |
| **VP-17** | Git Hook Runner, Login-Shell `PATH` Hydration & `--no-verify` Controls | `FR-2.7`, `FR-2.8` | `src/wrench/core/hook_env.py`, `src/wrench/ui/widgets/hook_output_drawer.py` |
| **VP-18** | GPG & SSH Commit/Tag Signing \+ Askpass Bridge & Verification Badges | `FR-2.9`, `FR-2.10` | `src/wrench/credentials/signing_askpass.py`, `src/wrench/core/signing_ops.py` |
| **VP-19** | Interactive `git bisect` Visual Wizard & Automated `bisect run` Controller | `FR-3.6` | `src/wrench/core/bisect_ops.py`, `src/wrench/ui/widgets/bisect_banner.py` |
| **VP-20** | Stacked Branches (`--update-refs`), Hunk Routing & Stacked PR Sync | `FR-3.7`, `FR-3.8`, `FR-5.13` | `src/wrench/core/stacks.py`, `src/wrench/ui/widgets/stack_panel.py` |
| **VP-21** | Interactive Blame Gutter, `.git-blame-ignore-revs` & Line History (`git log -L`) | `FR-9.4`, `FR-9.5` | `src/wrench/core/blame_ops.py`, `src/wrench/ui/widgets/blame_viewer.py` |
| **VP-22** | Granular Stash Modes (`--staged`, `--keep-index`) & `--skip-worktree` Panel | `FR-10.5`, `FR-10.6` | `src/wrench/core/stash_ops.py`, `src/wrench/ui/widgets/skip_worktree_panel.py` |
| **VP-23** | Conflict Memory (`git rerere`), Patch Mailboxes (`format-patch`/`am`) & `Ctrl+K` Custom Actions | `FR-3.9`, `FR-8.6`, `FR-8.7` | `src/wrench/core/custom_actions.py`, `src/wrench/ui/dialogs/command_palette.py` |
| **VP-24** | 2-Tier Progressive Disclosure Help System (Beginner Hover Cards \+ Offline Help `F1`) | `FR-8.13`, `DEC-7` | `src/wrench/ui/help_topics.py`, `src/wrench/ui/widgets/rich_help_tooltip.py`, `src/wrench/ui/dialogs/help_center_dialog.py` |
| **VP-25** | 5-Stage Mirror Resolution Engine & Combined Multi-Hosting Mirror History DAG | `FR-3.10`, `FR-4.6`, `FR-4.7`, `DEC-8` | `src/wrench/core/mirror_ops.py`, `src/wrench/forge/mirror_resolver.py`, `src/wrench/ui/dialogs/mirror_manager_dialog.py` |
| **VP-26** | Extended Multi-Forge Suite: Codeberg, Azure Repos, Radicle, Gerrit, SourceHut & Tangled | `FR-6.5`–`6.10`, `DEC-10` | `src/wrench/forge/adapters/{codeberg,azure_repos,radicle,gerrit,sourcehut,tangled}.py`, `src/wrench/ui/dialogs/forge_review_push_dialog.py` |

&nbsp;

## VP-0 — Universal Settings Registry, v1 Feature Retrofits & Searchable Preferences Center (`FR-8.8`–`8.11`, `NFR-5`)

**Why this position:** Foundational prerequisite for all of v2. Establishes the `SettingsRegistry` and auto-generated searchable `SettingsDialog` so every v1 feature and every new v2 feature (`VP-1`..`VP-23`) can be tweaked or completely turned off with zero overhead. **Prerequisites:** v1 Phase 7 complete. **Mandatory UI Spec Reference:** MUST read and implement `ui-planning.md §1.3` (Quick-Settings Pin Popover), `§1.4` (`UndoToastWidget`), `§2.2` (`LazyTabContainer`), `§5.5` (`OPT-1`..`OPT-4`), `§6.11` (Modular Settings Center), and `§8 Steps 26–27`. **Mandatory Optimizations Reminder for Lower-Tier Models (`DO NOT SKIP`):**

- **Lazy Category Page Loading (`OPT-1`):** In `SettingsDialog`, do NOT construct all 13 category `QWidget` pages in `__init__`. Store page factory callables and instantiate a category page only when the user clicks that category in `QListWidget` or searches.  
- **Debounced Auto-Save (`OPT-2`):** Do NOT add a Save/Apply button. Connect `QSpinBox` and `QLineEdit` controls to a `150ms` single-shot `QTimer` so rapid typing/spinning writes to SQLite only once after a `150ms` pause.  
- **Delta-Only Settings Snapshot & Undo Stack (`OPT-3`):** When `SettingsRegistry.set()` modifies a key, insert ONLY that single key's `(repo_path, key, old_value_json, new_value_json)` delta into `settings_undo_log` (pruning rows beyond the latest 100 entries). Wire `Ctrl+Z` / `Ctrl+Y` and the `🕓 History` popover in `SettingsDialog` to `undo_last_change()`, `redo_last_change()`, and `revert_specific_change(change_id)`.  
- **Lazy Workspace Tabs (`OPT-1`):** Wrap `HistoryTab`, `PRListTab`, and `IssueListTab` in `LazyTabContainer` in `MainWindow` so opening a repo instantiates only `ChangesTab` upfront.

### Step 0 — Repo-state reconciliation

Run the following inspection commands to verify existing storage, engine, and UI shell classes:

- `ls -la src/wrench/storage/ src/wrench/core/ src/wrench/ui/`  
- Inspect how `wrench.db` is initialized in `src/wrench/storage/` and how preferences/settings are currently opened from `src/wrench/ui/main_window.py`.

### Step 1 — Create `src/wrench/storage/settings_registry.py` with SQLite persistence & live Qt signals

Create `src/wrench/storage/settings_registry.py` implementing the exact schema and classes below:

- **SQLite Tables (add to `wrench.db` initialization):**

```sql
CREATE TABLE IF NOT EXISTS global_settings (
    key TEXT PRIMARY KEY,
    value_json TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS repo_settings_overrides (
    repo_path TEXT NOT NULL,
    key TEXT NOT NULL,
    value_json TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (repo_path, key)
);
CREATE TABLE IF NOT EXISTS settings_undo_log (
    change_id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    repo_path TEXT,
    key TEXT NOT NULL,
    old_value_json TEXT NOT NULL,
    new_value_json TEXT NOT NULL,
    undone INTEGER NOT NULL DEFAULT 0
);
```

- **Exact Dataclasses & Enums:**

```py
from dataclasses import dataclass
from enum import Enum
from typing import Any
from PySide6.QtCore import QObject, Signal


class SettingType(str, Enum):
    BOOL = "bool"
    INT = "int"
    STR = "str"
    CHOICE = "choice"
    PATH = "path"


class SettingScope(str, Enum):
    GLOBAL_ONLY = "global_only"
    REPO_OVERRIDABLE = "repo_overridable"


@dataclass(frozen=True)
class SettingSpec:
    key: str
    category: str
    label: str
    description: str
    setting_type: SettingType
    default: Any
    scope: SettingScope = SettingScope.REPO_OVERRIDABLE
    choices: tuple[str, ...] = ()
    min_value: int | None = None
    max_value: int | None = None
    parent_toggle_key: str | None = None  # Disabled in UI when parent toggle is False
```

- **Exact `SettingsRegistry(QObject)` Methods:**  
  - Signal: `setting_changed = Signal(str, object, object)`  \# `(key, new_value, repo_path_or_none)`  
  - `register(self, spec: SettingSpec) -> None`  
  - `get(self, key: str, repo_path: str | None = None) -> Any` (checks `repo_settings_overrides` first if `repo_path` is provided and `spec.scope == SettingScope.REPO_OVERRIDABLE`, else `global_settings`, else `spec.default`, using an in-memory dictionary cache so `get_bool` takes `< 1 microsecond`).  
  - `get_bool(self, key: str, repo_path: str | None = None) -> bool`  
  - `get_int(self, key: str, repo_path: str | None = None) -> int`  
  - `get_str(self, key: str, repo_path: str | None = None) -> str`  
  - `set(self, key: str, value: Any, repo_path: str | None = None) -> None` (validates type/range/choices, writes to SQLite, updates in-memory cache, and emits `setting_changed.emit(key, value, repo_path)`).  
  - `undo_last_change(self) -> tuple[str, Any] | None` (reverts the most recent `undone=0` delta row in `settings_undo_log`, marks `undone=1`, updates cache, and emits `setting_changed` — `ui-planning.md §5.5 OPT-3`).  
  - `redo_last_change(self) -> tuple[str, Any] | None` (re-applies the most recent `undone=1` delta row in `settings_undo_log`).  
  - `list_recent_changes(self, limit: int = 50) -> list[SettingChangeDelta]` and `revert_specific_change(self, change_id: int) -> None` (allows out-of-order single-setting revert from the Settings History popover in `ui-planning.md §6.11`).  
  - `reset_key(self, key: str, repo_path: str | None = None) -> None`  
  - `reset_all(self, repo_path: str | None = None) -> None`  
  - `apply_preset(self, preset_name: str) -> None` (supports `"default"` and `"minimalist_local_only"`, where `"minimalist_local_only"` sets `forge.enabled=False`, `remote.auto_fetch.enabled=False`, `desktop.system_tray.enabled=False`, `safety.scheduled_backups.enabled=False`, `signing.verify_badges_in_graph.enabled=False`, `stacks.enabled=False`, `worktrees.enabled=False`, `submodules.enabled=False`, `lfs.enabled=False`).  
  - `export_json(self, file_path: str) -> None` and `import_json(self, file_path: str) -> None`.  
- **Pre-register all v1 baseline settings in `DEFAULT_SETTING_SPECS` inside `settings_registry.py`:**  
  - *General & UI*: `ui.theme_mode` (`"system"`, `"dark"`, `"light"`), `ui.font_size_pt` (`10`, min `8`, max `18`), `ui.confirm_destructive_actions` (`True`), `workspace.restore_session_on_startup` (`True`), `repo.recent_max_count` (`20`, min `5`, max `100`), `repo.auto_discovery.enabled` (`True`).  
  - *Staging & Commits*: `staging.line_staging.enabled` (`True`), `commit.subject_max_length_guide` (`50`, min `0`, max `120`), `commit.body_wrap_column` (`72`, min `0`, max `160`), `commit.auto_stage_all_if_empty` (`False`).  
  - *Commit Graph*: `graph.show_lanes` (`True`), `graph.lane_width_px` (`16`, min `10`, max `32`), `graph.row_height_px` (`28`, min `20`, max `48`), `graph.date_format` (`"relative"`, choices `("relative", "iso", "locale")`), `graph.show_avatars` (`True`), `graph.sort_order` (`"topo"`, choices `("topo", "date")`).  
  - *Diff & Merge*: `diff.context_lines` (`3`, min `1`, max `20`), `diff.ignore_whitespace_mode` (`"none"`, choices `("none", "trailing", "all")`), `merge.default_strategy` (`"merge"`, choices `("merge", "ff-only", "no-ff")`), `merge.builtin_3way_tool.enabled` (`True`).  
  - *Remotes & Sync*: `remote.auto_fetch.enabled` (`True`), `remote.auto_fetch.interval_seconds` (`180`, min `30`, max `3600`, `parent_toggle_key="remote.auto_fetch.enabled"`), `remote.pull_default_mode` (`"ff-only"`, choices `("ff-only", "rebase", "merge")`), `remote.force_push_mode` (`"force-with-lease"`, choices `("disabled", "force-with-lease", "force")`), `remote.prune_on_fetch` (`True`).  
  - *Forges & CI*: `forge.enabled` (`True`), `forge.github.enabled` (`True`, parent `"forge.enabled"`), `forge.gitlab.enabled` (`True`, parent `"forge.enabled"`), `forge.forgejo.enabled` (`True`, parent `"forge.enabled"`), `forge.bitbucket.enabled` (`True`, parent `"forge.enabled"`), `forge.ci_badges.enabled` (`True`, parent `"forge.enabled"`), `forge.poll_interval_seconds` (`120`, min `30`, max `3600`, parent `"forge.enabled"`), `forge.allow_third_party_entrypoint_plugins` (`True`, parent `"forge.enabled"`).  
  - *Watcher & Performance*: `watcher.inotify.enabled` (`True`), `watcher.debounce_ms` (`300`, min `50`, max `5000`, parent `"watcher.inotify.enabled"`), `watcher.refresh_on_window_focus` (`True`), `watcher.lock_recovery_prompt.enabled` (`True`), `performance.worker_thread_count` (`4`, min `1`, max `16`), `performance.max_diff_file_size_kb` (`2048`, min `128`, max `32768`).  
  - *Safety & Backups*: `safety.pre_op_snapshot.enabled` (`True`), `stash.ui.enabled` (`True`), `stash.confirm_before_drop` (`True`).  
- **Completion Gate:** `pytest tests/storage/test_settings_registry.py`

### Step 2 — Wire v1 modules to `SettingsRegistry` for immediate zero-impact disabling

Modify existing v1 modules to obey `SettingsRegistry`:

1. In `src/wrench/watcher/inotify_watcher.py`: subscribe to `setting_changed`. When `watcher.inotify.enabled` is `False`, stop the `watchdog` observer thread immediately and do not start it on repo open; update debounce timer interval dynamically when `watcher.debounce_ms` changes.  
2. In `src/wrench/forge/registry.py`: check `settings.get_bool("forge.enabled", repo_path)` and `settings.get_bool(f"forge.{provider}.enabled", repo_path)`. When `False`, return `None` / empty lists immediately without making any `httpx` requests, and hide all Forge/PR/CI UI panels in `MainWindow`.  
3. In `src/wrench/core/snapshots.py`: add `maybe_create_safety_snapshot(repo_path, op_name)` which immediately returns `None` without spawning `git stash create` if `settings.get_bool("safety.pre_op_snapshot.enabled", repo_path)` is `False`.  
4. In `src/wrench/ui/tabs/history_tab.py` and `changes_tab.py`: connect `setting_changed` so toggling `graph.show_lanes`, `graph.show_avatars`, `staging.line_staging.enabled`, or `stash.ui.enabled` immediately updates the UI.  
- **Completion Gate:** `pytest tests/core/test_v1_settings_gates.py`

### Step 3 — Build auto-generated searchable `SettingsDialog` (`src/wrench/ui/dialogs/settings_dialog.py`) & 2-Tier Progressive Help (`rich_help_tooltip.py`, `help_center_dialog.py`)

- Register `help.tooltip_mode` (`CHOICE`, default `"beginner_rich"`, choices `("beginner_rich", "compact_shortcut_only", "off")`, category `"General & UI"`, label `"Tooltip detail level (Beginner Rich Cards with 'Learn More' links vs. Compact)"`) and `help.tooltip_delay_ms` (`INT`, default `500`, min `100`, max `2000`, parent `"help.tooltip_mode"`).  
- Create `src/wrench/ui/widgets/rich_help_tooltip.py` (`attach_help_topic(widget, topic_id)`) rendering the 2-line beginner explanation \+ CLI flag badge \+ `[Read Full Guide (F1) →]` deep-link (`ui-planning.md §5.6`), and `src/wrench/ui/dialogs/help_center_dialog.py` (`F1`) with lazy-loaded offline Markdown topics (`OPT-1`) and `wrench://open-setting/<key>` action links. Create `src/wrench/ui/dialogs/settings_dialog.py` bound to `Ctrl+,` in `MainWindow`:  
- Left sidebar: `QListWidget` listing all distinct `SettingSpec.category` values.  
- Top bar: `QLineEdit` live search filter (filters rows by matching `label`, `description`, or `key`), Scope selector combo-box (`Global Defaults` vs `Repository Override: <current_repo>`), Preset buttons (`Apply Minimalist Local-Only Mode`, `Reset All to Defaults`), and `Export JSON...` / `Import JSON...` buttons.  
- Right pane: `QScrollArea` dynamically rendering a control row per `SettingSpec` (`QCheckBox` for `BOOL`, `QSpinBox` for `INT`, `QComboBox` for `CHOICE`, `QLineEdit` \+ Browse button for `PATH`, `QLineEdit` for `STR`), plus a per-row `Reset` toolbutton and an `"Overridden for this repo"` pill badge when a repo override is active.  
- Automatically disables child controls when `spec.parent_toggle_key` is `False`.  
- **Completion Gate:** `pytest tests/ui/test_settings_dialog.py`

### Forbidden Decisions for Lower-Tier Models

- DO NOT hardcode individual checkboxes in `SettingsDialog` per feature; `SettingsDialog` MUST build its rows dynamically from `SettingsRegistry.list_specs()` so that when `VP-1`..`VP-23` register new `SettingSpec` items, they appear in the Settings menu automatically.  
- DO NOT require an app restart when a user toggles a setting.

### Acceptance Check

- [ ] Opening `Ctrl+,` displays all categories, filters settings in real time via the search bar, and clicking "Apply Minimalist Local-Only Mode" immediately hides all Forge/PR/CI widgets and stops background `inotify` and fetch timers without restarting Wrench.

## VP-1 — Multi-Commit Cherry-Pick, Revert & Visual Reset Mode Picker (`FR-2.4`, `FR-3.4`)

**Why this position:** Directly extends v1's commit graph context menu and conflict resolution state machine. Community grounding: [GitHub Desktop \#3579](https://github.com/desktop/desktop/issues/3579), [HN Reset UX \#45878578](https://news.ycombinator.com/item?id=45878578). **Prerequisites:** `VP-0` acceptance check passed. **Mandatory UI Spec Reference:** MUST read and implement `ui-planning.md §1.4` (Action Undo Toast), `§5.3` (`CliCommandPreviewBar`), `§6.15` (`ResetModeDialog`), and `§8 Step 28`. **Mandatory Optimizations Reminder for Lower-Tier Models (`DO NOT SKIP`):**

- Cache the resolved gitdir path (`pygit2.Repository(repo_path).path`) on the repository context object rather than re-opening `pygit2.Repository` on every status tick when checking `.git/CHERRY_PICK_HEAD` and `.git/REVERT_HEAD`.  
- Reuse a single `CliCommandPreviewBar` widget footer in `ResetModeDialog` (`ui-planning.md §5.3`) and gate it behind `ui.show_cli_preview_in_dialogs`.

### Step 0 — Repo-state reconciliation

- Inspect `src/wrench/core/write_ops.py`, `src/wrench/core/read_ops.py`, `src/wrench/core/engine.py`, and `src/wrench/ui/tabs/history_tab.py`.

### Step 1 — Register `VP-1` settings & implement cherry-pick, revert, and sequencer state in `core`

1. In `src/wrench/storage/settings_registry.py`, register:  
   - `commit.undo_button.enabled` (`BOOL`, default `True`, category `"Staging & Commits"`, label `"Show Undo Last Commit button"`)  
   - `reset.show_visual_preview_dialog` (`BOOL`, default `True`, category `"Branches & Stacks"`, label `"Show visual file-impact preview before Reset"`)  
   - `graph.cherry_pick_revert.enabled` (`BOOL`, default `True`, category `"Commit Graph"`, label `"Enable Cherry-Pick and Revert context menu actions"`)  
   - `graph.cherry_pick_revert.default_no_commit` (`BOOL`, default `False`, category `"Commit Graph"`, label `"Stage cherry-pick/revert changes without committing (--no-commit)"`, parent `"graph.cherry_pick_revert.enabled"`)  
   - `graph.cherry_pick_revert.record_origin_x` (`BOOL`, default `True`, category `"Commit Graph"`, label `"Append '(cherry picked from commit ...)' line (-x)"`, parent `"graph.cherry_pick_revert.enabled"`)  
2. In `src/wrench/core/read_ops.py`, add:

```py
@dataclass(frozen=True)
class SequencerState:
    active_op: str | None  # "cherry-pick", "revert", "rebase", "merge", "am", or None
    current_oid: str | None
    todo_remaining: int


def get_sequencer_state(repo_path: str) -> SequencerState: ...
```

   Check `.git/CHERRY_PICK_HEAD`, `.git/REVERT_HEAD`, `.git/rebase-merge/`, `.git/rebase-apply/`, and `.git/MERGE_HEAD` (resolving worktree gitdir via `pygit2.Repository(repo_path).path`).

3. In `src/wrench/core/write_ops.py`, add exact functions:  
   - `cherry_pick_commits(repo_path: str, oids: list[str], no_commit: bool = False, record_origin: bool = True) -> None`: runs `["git", "-C", repo_path, "cherry-pick", *flags, *oids]`.  
   - `revert_commits(repo_path: str, oids: list[str], no_commit: bool = False, mainline_parent: int | None = None) -> None`: runs `["git", "-C", repo_path, "revert", "--no-edit", *flags, *oids]`.  
   - `sequencer_action(repo_path: str, op: str, action: str) -> None`: where `op in ("cherry-pick", "revert")` and `action in ("continue", "skip", "abort")`, running `["git", "-C", repo_path, op, f"--{action}"]`.  
   - `reset_branch(repo_path: str, target_oid: str, mode: str) -> None`: where `mode in ("soft", "mixed", "hard")`, running `["git", "-C", repo_path, "reset", f"--{mode}", target_oid]`.  
4. Expose all four methods on `src/wrench/core/engine.py`, calling `self.snapshots.maybe_create_safety_snapshot()` before `cherry_pick_commits`, `revert_commits`, and `reset_branch`.  
- **Completion Gate:** `pytest tests/core/test_cherry_pick_revert.py`

### Step 2 — Build `src/wrench/ui/dialogs/reset_dialog.py` & wire `HistoryTab`

1. Create `src/wrench/ui/dialogs/reset_dialog.py` with class `ResetModeDialog(QDialog)`:  
   - Shows three radio cards for `--soft`, `--mixed`, and `--hard` with plain-English explanations and exact counts of staged/modified files that will be kept, unstaged, or discarded.  
   - Includes a `"Don't show this preview again (always use selected mode)"` checkbox that sets `reset.show_visual_preview_dialog = False`.  
2. In `src/wrench/ui/tabs/history_tab.py`, add multi-row selection support (`QAbstractItemView.ExtendedSelection`) and context menu actions for `Cherry-Pick Selected Commits`, `Revert Selected Commits`, and `Reset Current Branch to Here...` (hidden when `graph.cherry_pick_revert.enabled` is `False`).  
3. Add a sequencer status bar at the top of `HistoryTab` and `ChangesTab` when `get_sequencer_state().active_op in ("cherry-pick", "revert")` with `Continue`, `Skip`, and `Abort` buttons.  
- **Completion Gate:** `pytest tests/ui/test_reset_and_sequencer_ui.py`

### Forbidden Decisions for Lower-Tier Models

- DO NOT check `.git/CHERRY_PICK_HEAD` by hardcoding `os.path.join(repo_path, ".git", ...)`; always use `pygit2.Repository(repo_path).path` so linked worktrees (`VP-3`) work properly.

### Acceptance Check

- [ ] Multi-selecting commits and running Cherry-Pick or Revert works end-to-end; conflict states show Continue/Skip/Abort buttons; disabling `graph.cherry_pick_revert.enabled` in Settings hides the context menu items.

## VP-2 — Visual Interactive Rebase & Drag-to-Reorder (`FR-3.5`, `FR-10.1`)

**Why this position:** Builds on `VP-1`'s sequencer banner to deliver visual interactive rebase (`git rebase -i`). **Prerequisites:** `VP-1` acceptance check passed. **Mandatory UI Spec Reference:** MUST read and implement `ui-planning.md §6.16` (`InteractiveRebaseDialog`), `§5.3` (`CliCommandPreviewBar`), and `§8 Step 29`. **Mandatory Optimizations Reminder for Lower-Tier Models (`DO NOT SKIP`):**

- Load only the commits in the range `base_oid..HEAD` via `pygit2` topological walk (capped at `1000` commits) and render rows in `InteractiveRebaseDialog` without spawning any subprocesses until the user clicks `Start Rebase`.

### Step 0 — Repo-state reconciliation

- Inspect `src/wrench/core/write_ops.py` and `src/wrench/ui/tabs/history_tab.py`.

### Step 1 — Register `VP-2` settings & create `src/wrench/core/rebase_sequencer.py`

1. In `src/wrench/storage/settings_registry.py`, register:  
   - `rebase.interactive_ui.enabled` (`BOOL`, default `True`, category `"Branches & Stacks"`, label `"Enable Visual Interactive Rebase UI"`)  
   - `rebase.autostash` (`BOOL`, default `True`, category `"Branches & Stacks"`, label `"Automatically stash and pop dirty working tree during rebase (--autostash)"`, parent `"rebase.interactive_ui.enabled"`)  
   - `rebase.autosquash` (`BOOL`, default `True`, category `"Branches & Stacks"`, label `"Automatically reorder fixup!/squash! commits (--autosquash)"`, parent `"rebase.interactive_ui.enabled"`)  
2. Create `src/wrench/core/rebase_sequencer.py`:

```py
@dataclass
class RebaseTodoEntry:
    action: str  # "pick", "reword", "edit", "squash", "fixup", "drop"
    oid: str
    short_oid: str
    summary: str
    author: str
    new_message: str | None = None
```

   - Implement `list_commits_for_interactive_rebase(repo_path: str, base_oid: str) -> list[RebaseTodoEntry]` using `pygit2` topological walk in oldest-first order (`git rebase -i` order).  
   - Implement `run_interactive_rebase(repo_path: str, base_oid: str, entries: list[RebaseTodoEntry], autostash: bool = True, autosquash: bool = True) -> None`:  
     - Writes a JSON instruction file to a temporary directory and sets `GIT_SEQUENCE_EDITOR` and `GIT_EDITOR` to `sys.executable -m wrench.core.rebase_editor_helper <json_file_path>`.  
     - Create `src/wrench/core/rebase_editor_helper.py` which Git invokes during `git rebase -i`: when passed a path ending in `git-rebase-todo`, it writes the `action short_oid summary` lines; when passed `COMMIT_EDITMSG`, it writes the corresponding `new_message` for `reword`/`squash`.  
- **Completion Gate:** `pytest tests/core/test_interactive_rebase.py`

### Step 2 — Build `src/wrench/ui/dialogs/interactive_rebase_dialog.py`

- Create `InteractiveRebaseDialog(QDialog)` with drag-and-drop row reordering (`QTableWidget` with `InternalMove`), per-row `QComboBox` for `pick`/`reword`/`edit`/`squash`/`fixup`/`drop`, inline message editor popup when `reword` or `squash` is chosen, and a validation rule preventing the top row from being set to `squash` or `fixup`.  
- Wire `"Interactive Rebase from Here..."` into `HistoryTab` commit context menu (hidden if `rebase.interactive_ui.enabled` is `False`).  
- **Completion Gate:** `pytest tests/ui/test_interactive_rebase_dialog.py`

### Forbidden Decisions for Lower-Tier Models

- DO NOT manipulate commit parents manually in `pygit2` to simulate interactive rebase; ALWAYS delegate to `git rebase -i` via `GIT_SEQUENCE_EDITOR` so hooks, conflict markers, and reflogs behave identically to CLI Git.

### Acceptance Check

- [ ] Reordering commits, squashing two commits, rewording a commit, and dropping a commit via `InteractiveRebaseDialog` rewrites history cleanly and takes a pre-op snapshot if `safety.pre_op_snapshot.enabled` is `True`.

## VP-3 — Git Worktrees UI, Bare-Hub Mode & Cross-Worktree Operations (`FR-1.13`, `FR-1.15`, `FR-1.17`)

**Why this position:** Enables multi-branch concurrency across Wrench's workspace tabs ([GitHub Desktop \#19307](https://github.com/desktop/desktop/issues/19307), [\#22308](https://github.com/desktop/desktop/issues/22308), [\#22714](https://github.com/desktop/desktop/issues/22714), [Sublime Merge \#757](https://github.com/sublimehq/sublime_merge/issues/757), [Lazygit \#3100](https://github.com/jesseduffield/lazygit/issues/3100)). **Prerequisites:** `VP-2` acceptance check passed. **Mandatory UI Spec Reference:** MUST read and implement `ui-planning.md §2.1` (Worktree Tabs), `§6.17` (`WorktreePanel` & Bare-Repo Worktree Hub), and `§8 Step 30`. **Mandatory Optimizations Reminder for Lower-Tier Models (`DO NOT SKIP`):**

- Parse `git worktree list --porcelain -z` in a background worker (`OPT-6` generation token) and share the single parent object-database cache across linked worktree tabs so opening 3 worktrees of the same repo does not duplicate forge/avatar caches.

### Step 0 — Repo-state reconciliation

- Inspect `src/wrench/core/read_ops.py` (locate the v1 Bare Repo check), `src/wrench/ui/tabs/tab_bar.py`, and `src/wrench/ui/main_window.py`.

### Step 1 — Register `VP-3` settings & create `src/wrench/core/worktrees.py`

1. In `src/wrench/storage/settings_registry.py`, register:  
   - `worktrees.enabled` (`BOOL`, default `True`, category `"Worktrees & Submodules"`, label `"Enable Git Worktrees management UI"`)  
   - `worktrees.path_template` (`STR`, default `"../{repo_name}-{branch_slug}"`, category `"Worktrees & Submodules"`, label `"Default directory path template for new worktrees"`, parent `"worktrees.enabled"`)  
   - `worktrees.bare_hub.enabled` (`BOOL`, default `True`, category `"Worktrees & Submodules"`, label `"Allow opening bare repositories as a Worktree Hub"`, parent `"worktrees.enabled"`)  
   - `worktrees.cross_cherry_pick.enabled` (`BOOL`, default `True`, category `"Worktrees & Submodules"`, label `"Allow cherry-picking commits directly into another worktree"`, parent `"worktrees.enabled"`)  
   - `workspace.named_sessions.enabled` (`BOOL`, default `True`, category `"General & UI"`, label `"Enable saving and restoring named multi-tab workspace sessions"`)  
2. Create `src/wrench/core/worktrees.py` with:

```py
@dataclass(frozen=True)
class WorktreeInfo:
    path: str
    head_oid: str
    branch_name: str | None
    is_bare: bool
    is_locked: bool
    lock_reason: str | None
    is_prunable: bool
```

   - `list_worktrees(repo_path: str) -> list[WorktreeInfo]` parsing `git -C <repo_path> worktree list --porcelain -z`.  
   - `format_worktree_path(repo_path: str, branch_name: str, template: str) -> str` replacing `{repo_name}` and `{branch_slug}` (where `/` in branch names is replaced with `-`).  
   - `add_worktree(repo_path: str, target_path: str, branch: str, create_branch: bool = False) -> WorktreeInfo`.  
   - `lock_worktree(repo_path: str, worktree_path: str, reason: str = "") -> None` and `unlock_worktree(repo_path: str, worktree_path: str) -> None`.  
   - `remove_worktree(repo_path: str, worktree_path: str, force: bool = False) -> None` and `prune_worktrees(repo_path: str) -> None`.  
3. In `src/wrench/core/read_ops.py`, update the Bare Repo check: if `repo.is_bare` is `True` and `settings.get_bool("worktrees.bare_hub.enabled", repo_path)` is `True`, do NOT raise `BareRepositoryError`; instead return `is_bare_hub=True` so UI opens the Worktree Hub view ([Lazygit \#3100](https://github.com/jesseduffield/lazygit/issues/3100), [\#5469](https://github.com/jesseduffield/lazygit/issues/5469)).  
- **Completion Gate:** `pytest tests/core/test_worktrees.py`

### Step 2 — Build `src/wrench/ui/widgets/worktree_panel.py` & Named Sessions in `wrench.db`

- Create `WorktreePanel(QWidget)` in `src/wrench/ui/widgets/worktree_panel.py` listing linked worktrees with full filesystem path tooltip on hover ([GitHub Desktop Issues](https://github.com/desktop/desktop/issues)), `Open in New Tab`, `Add Worktree` (pre-filling path from `worktrees.path_template`), `Lock/Unlock`, `Remove`, and `Prune`.  
- Add `"Cherry-Pick to Worktree..."` submenu in `HistoryTab` when \>1 worktree exists and `worktrees.cross_cherry_pick.enabled` is `True` ([GitHub Desktop \#22714](https://github.com/desktop/desktop/issues/22714)).  
- Add SQLite table `workspace_sessions(session_name TEXT PRIMARY KEY, repo_paths_json TEXT NOT NULL, active_index INTEGER NOT NULL)` and `SessionMenu` under `File -> Workspace Sessions` ([Sublime Merge \#789](https://github.com/sublimehq/sublime_merge/issues/789)).  
- **Completion Gate:** `pytest tests/ui/test_worktree_ui.py`

### Forbidden Decisions for Lower-Tier Models

- DO NOT allow checking out a branch in Worktree A if `list_worktrees()` shows that branch is already checked out in Worktree B; instead prompt the user to switch to Worktree B's tab.

### Acceptance Check

- [ ] Creating, locking, unlocking, and opening worktrees in tabs works; bare repositories with worktrees open into the Worktree Hub; toggling `worktrees.enabled = False` hides `WorktreePanel` completely.

## VP-4 — Git Submodules Lifecycle & Batch Sync Manager (`FR-1.14`)

**Why this position:** Completes multi-repository hierarchy management alongside `VP-3` worktrees. **Prerequisites:** `VP-3` acceptance check passed. **Mandatory UI Spec Reference:** MUST read and implement `ui-planning.md §6.3` (`SubmodulePanel`) and `§8 Step 31`. **Mandatory Optimizations Reminder for Lower-Tier Models (`DO NOT SKIP`):**

- If `submodules.enabled` is `False` or `.gitmodules` does not exist at `os.path.join(repo_path, ".gitmodules")`, short-circuit `list_submodules()` in `< 0.1ms` without spawning `git submodule status`.

### Step 0 — Repo-state reconciliation

- Inspect `src/wrench/core/engine.py` and the repository sidebar in `src/wrench/ui/`.

### Step 1 — Register `VP-4` settings & create `src/wrench/core/submodules.py`

1. In `src/wrench/storage/settings_registry.py`, register:  
   - `submodules.enabled` (`BOOL`, default `True`, category `"Worktrees & Submodules"`, label `"Enable Git Submodules panel and status checks"`)  
   - `submodules.auto_recurse_on_pull` (`BOOL`, default `False`, category `"Worktrees & Submodules"`, label `"Pass --recurse-submodules automatically on Pull/Fetch"`, parent `"submodules.enabled"`)  
   - `submodules.dirty_badge.enabled` (`BOOL`, default `True`, category `"Worktrees & Submodules"`, label `"Show dirty/uninitialized badges on submodules"`, parent `"submodules.enabled"`)  
2. Create `src/wrench/core/submodules.py` with:

```py
@dataclass(frozen=True)
class SubmoduleInfo:
    name: str
    path: str
    url: str
    head_oid: str | None
    index_oid: str | None
    status: str  # "clean", "uninitialized", "modified", "dirty_workdir"
```

   - `list_submodules(repo_path: str) -> list[SubmoduleInfo]` (returns `[]` immediately if `not settings.get_bool("submodules.enabled", repo_path)`).  
   - `init_submodules(repo_path: str, paths: list[str] | None = None) -> None` (`git submodule update --init --recursive`).  
   - `sync_submodules(repo_path: str) -> None` (`git submodule sync --recursive`).  
   - `add_submodule(repo_path: str, url: str, relative_path: str, branch: str | None = None) -> None`.  
- **Completion Gate:** `pytest tests/core/test_submodules.py`

### Step 2 — Build `src/wrench/ui/widgets/submodule_panel.py`

- Create `SubmodulePanel(QWidget)` in the sidebar with status badges (`clean`, `modified`, `uninitialized`), double-click to open the submodule repository in a new Wrench tab, and toolbar buttons for `Init/Update All`, `Sync URLs`, and `Add Submodule...`.  
- Connect `setting_changed`: when `submodules.enabled` is `False`, hide `SubmodulePanel`.  
- **Completion Gate:** `pytest tests/ui/test_submodule_panel.py`

### Forbidden Decisions for Lower-Tier Models

- DO NOT run `git submodule status` synchronously on the main GUI thread; always dispatch through `ui.workers.run_in_background`.

### Acceptance Check

- [ ] Submodules list with accurate status badges, open in a new tab on double-click, update recursively, and disappear with zero subprocess calls when `submodules.enabled` is `False`.

## VP-5 — Commit Message Templates & Co-Authors Autocomplete UI (`FR-2.5`, `FR-2.6`)

**Why this position:** Enhances the daily commit authoring box in `ChangesTab` before PR/Issue features land. **Prerequisites:** `VP-4` acceptance check passed. **Mandatory UI Spec Reference:** MUST read and implement `ui-planning.md §3.1` (`CoAuthorInputWidget` & Template Selector) and `§8 Step 32`. **Mandatory Optimizations Reminder for Lower-Tier Models (`DO NOT SKIP`):**

- Scan contributor `(name, email)` pairs from `pygit2` once per repo open in a background worker and cache the deduplicated list in memory; only invalidate when `HEAD` OID changes.

### Step 0 — Repo-state reconciliation

- Inspect `src/wrench/ui/tabs/changes_tab.py` and `src/wrench/core/read_ops.py`.

### Step 1 — Register `VP-5` settings & create `src/wrench/core/commit_helpers.py`

1. In `src/wrench/storage/settings_registry.py`, register:  
   - `commit.templates.enabled` (`BOOL`, default `True`, category `"Staging & Commits"`, label `"Enable commit message templates"`)  
   - `commit.templates.auto_load_gitconfig` (`BOOL`, default `True`, category `"Staging & Commits"`, label `"Auto-fill commit box from Git commit.template config"`, parent `"commit.templates.enabled"`)  
   - `commit.coauthors_ui.enabled` (`BOOL`, default `True`, category `"Staging & Commits"`, label `"Show Co-authored-by autocomplete bar in commit box"`)  
2. Create `src/wrench/core/commit_helpers.py`:  
   - `get_gitconfig_commit_template(repo_path: str) -> str | None`: reads `commit.template` via `pygit2.Repository(repo_path).config`, expands `~`, reads file text, and strips lines starting with `#`.  
   - `list_recent_contributors(repo_path: str, limit: int = 200) -> list[tuple[str, str]]`: walks up to `limit` recent commits via `pygit2` and returns deduplicated `(author_name, author_email)` pairs for co-author autocomplete.  
   - `format_commit_message_with_trailers(body: str, coauthors: list[tuple[str, str]]) -> str`: appends `Co-authored-by: Name <email>` trailers cleanly separated by a blank line.  
- **Completion Gate:** `pytest tests/core/test_commit_helpers.py`

### Step 2 — Build `src/wrench/ui/widgets/coauthor_input.py` & Template Selector in `ChangesTab`

- Create `CoAuthorInputWidget(QWidget)` providing a tag/pill input with `QCompleter` matching contributor names and emails, plus a `Template` dropdown button in `ChangesTab` to load/save custom templates in `wrench.db` (`commit_templates` table).  
- Hide `CoAuthorInputWidget` when `commit.coauthors_ui.enabled` is `False`, and hide the template dropdown when `commit.templates.enabled` is `False`.  
- **Completion Gate:** `pytest tests/ui/test_commit_templates_coauthors.py`

### Forbidden Decisions for Lower-Tier Models

- DO NOT overwrite non-empty user-typed text in the commit message box when auto-loading `commit.template`; only populate when the commit message input is empty.

### Acceptance Check

- [ ] Opening a repo with `commit.template` populates the empty commit box; selecting co-authors appends valid `Co-authored-by:` trailers; toggling either setting off in `Ctrl+,` hides its widget immediately.

## VP-6 — PR Inline Code Review, Line Comments, 1-Click Checkout & Live CI Log Streaming (`FR-5.10`, `FR-5.13`)

**Why this position:** Deepens `src/wrench/forge` so users can review PRs, check out PR branches, and read failing CI logs without leaving Wrench ([Lazygit \#3639](https://github.com/jesseduffield/lazygit/issues/3639), [Sublime Merge \#293](https://github.com/sublimehq/sublime_merge/issues/293)). **Prerequisites:** `VP-5` acceptance check passed. **Mandatory UI Spec Reference:** MUST read and implement `ui-planning.md §6.18` (`PRReviewOverlayWidget` & `CILogDrawer`), `§5.5 OPT-5/OPT-6`, and `§8 Step 33`. **Mandatory Optimizations Reminder for Lower-Tier Models (`DO NOT SKIP`):**

- **Ring-Buffer Log Streaming (`OPT-5`):** Set `CILogDrawer` text view to `setMaximumBlockCount(5000)` and batch incoming log chunks into `50ms` `QTimer` flush ticks so large CI logs never freeze the UI.  
- **ETag / Conditional HTTP Requests:** Send `If-None-Match` headers on `httpx` PR comment polls so unchanged PR threads return `304 Not Modified` with zero JSON parsing overhead.

### Step 0 — Repo-state reconciliation

- Inspect `src/wrench/forge/capability.py`, `src/wrench/forge/registry.py`, and `src/wrench/forge/adapters/`.

### Step 1 — Register `VP-6` settings & extend Forge capability adapters

1. In `src/wrench/storage/settings_registry.py`, register:  
   - `forge.pr_inline_comments.enabled` (`BOOL`, default `True`, category `"Forges & CI"`, label `"Show inline PR review comments inside Diff Viewer"`, parent `"forge.enabled"`)  
   - `forge.ci_log_streaming.enabled` (`BOOL`, default `True`, category `"Forges & CI"`, label `"Enable live CI/CD job log streaming and re-run controls"`, parent `"forge.enabled"`)  
2. In `src/wrench/forge/capability.py`, add dataclasses and capability methods:

```py
@dataclass(frozen=True)
class PRReviewComment:
    comment_id: str
    thread_id: str
    path: str
    line: int
    author: str
    body: str
    created_at: str
    is_resolved: bool


class SupportsPRReview(Protocol):
    def list_pr_comments(self, repo_slug: str, pr_number: int) -> list[PRReviewComment]: ...
    def post_pr_line_comment(
        self, repo_slug: str, pr_number: int, commit_id: str, path: str, line: int, body: str
    ) -> PRReviewComment: ...
    def resolve_pr_thread(
        self, repo_slug: str, pr_number: int, thread_id: str, resolved: bool
    ) -> None: ...
    def submit_pr_review(
        self, repo_slug: str, pr_number: int, event: str, body: str
    ) -> None: ...  # event: "APPROVE", "REQUEST_CHANGES", "COMMENT"


class SupportsCILogs(Protocol):
    def get_ci_job_log(self, repo_slug: str, job_id: str) -> str: ...
    def rerun_ci_job(self, repo_slug: str, job_id: str) -> bool: ...
```

   Implement these methods across `github.py`, `gitlab.py`, `forgejo.py`, and `bitbucket.py`, plus `checkout_pr_branch(repo_path: str, remote_name: str, pr_number: int, local_branch_name: str)` in `src/wrench/core/write_ops.py` (`git fetch <remote> pull/<id>/head:<branch>` or `merge-requests/<id>/head:<branch>`).

- **Completion Gate:** `pytest tests/forge/test_pr_inline_review.py`

### Step 2 — Build `src/wrench/ui/widgets/pr_review_overlay.py` & CI Log Drawer

- Create `PRReviewOverlayWidget` rendering collapsible comment threads inside the diff view at `(path, line)` with `Reply`, `Resolve/Unresolve`, and top-level `Approve` / `Request Changes` review submission buttons, plus a `Checkout PR Locally` button.  
- Create `CILogDrawer(QWidget)` displaying step logs and a `Re-run Failed Job` button.  
- Connect both to `SettingsRegistry` so disabling `forge.pr_inline_comments.enabled` or `forge.ci_log_streaming.enabled` hides the UI and stops fetching comment/log payloads.  
- **Completion Gate:** `pytest tests/ui/test_pr_review_and_ci_logs_ui.py`

### Forbidden Decisions for Lower-Tier Models

- DO NOT poll CI logs in an infinite loop when the `CILogDrawer` is closed or hidden; only fetch logs when the user expands a job row and `forge.ci_log_streaming.enabled` is `True`.

### Acceptance Check

- [ ] Viewing a PR renders inline review comments at the matching diff lines, allows replying/resolving and checking out the PR branch in 1 click, and streams CI logs on demand.

## VP-7 — Issue Board / Issue Tracker View & `#` Commit Autocomplete (`FR-5.11`)

**Why this position:** Completes the forge collaboration triad (PRs, CI, Issues) using the same capability adapter pattern. **Prerequisites:** `VP-6` acceptance check passed. **Mandatory UI Spec Reference:** MUST read and implement `ui-planning.md §2.1`, `§2.2` (`LazyTabContainer`), `§3.1` (`IssueCompleter`), and `§8 Step 34`. **Mandatory Optimizations Reminder for Lower-Tier Models (`DO NOT SKIP`):**

- **Lazy Tab Loading (`OPT-1`):** `IssueListTab` MUST remain uninstantiated until the user clicks the `Issues` tab.  
- **Zero-Latency `#` Autocomplete (`OPT-4`):** `IssueCompleter` MUST query the local SQLite `cached_issues` table in memory (`< 1ms`) rather than making network calls on keystrokes.

### Step 0 — Repo-state reconciliation

- Inspect `src/wrench/forge/capability.py` and `src/wrench/ui/tabs/`.

### Step 1 — Register `VP-7` settings & implement Issue CRUD in forge adapters

1. In `src/wrench/storage/settings_registry.py`, register:  
   - `forge.issues_tab.enabled` (`BOOL`, default `True`, category `"Forges & CI"`, label `"Show Issues tab in repository workspace"`, parent `"forge.enabled"`)  
   - `forge.commit_issue_autocomplete.enabled` (`BOOL`, default `True`, category `"Forges & CI"`, label `"Autocomplete #issue numbers in commit message box"`, parent `"forge.enabled"`)  
2. In `src/wrench/forge/capability.py`, verify or add `IssueItem(number, title, state, labels, assignees, author, body, web_url)` and `list_issues`, `create_issue`, `set_issue_state` across GitHub, GitLab, Forgejo, and Bitbucket adapters, caching results in `wrench.db` (`cached_issues` table) for fast `#` autocomplete.  
- **Completion Gate:** `pytest tests/forge/test_issues_capability.py`

### Step 2 — Build `src/wrench/ui/tabs/issue_list_tab.py` & `src/wrench/ui/widgets/issue_completer.py`

- Create `IssuesTab(QWidget)` with Open/Closed filter, search bar, label pills, `New Issue` modal, and a `Create Branch for Issue` button (which creates `issue-{number}-{slug}` and switches to it).  
- Create `IssueCompleter` attached to the commit message `QPlainTextEdit` in `ChangesTab` so typing `#` pops up matching `(number, title)` items (disabled if `forge.commit_issue_autocomplete.enabled` is `False`).  
- Hide `IssuesTab` immediately when `forge.issues_tab.enabled` or `forge.enabled` is `False`.  
- **Completion Gate:** `pytest tests/ui/test_issues_tab.py`

### Forbidden Decisions for Lower-Tier Models

- DO NOT make synchronous network calls on every keystroke after `#`; always query the in-memory / SQLite `cached_issues` list populated in the background.

### Acceptance Check

- [ ] `IssuesTab` lists, filters, and creates issues; typing `#` in the commit box autocompletes issue numbers; turning `forge.issues_tab.enabled` off removes the `Issues` tab immediately.

## VP-8 — Multi-Account Switching & Per-Repo Identity/SSH Binding (`FR-5.12`)

**Why this position:** Allows users with separate Work and Personal accounts on the same forge (e.g. two GitHub accounts) to bind credentials, SSH keys, and Git author identities per repository or parent folder. **Prerequisites:** `VP-7` acceptance check passed. **Mandatory UI Spec Reference:** MUST read and implement `ui-planning.md §6.19` (`AccountRulesDialog`) and `§8 Step 35`. **Mandatory Optimizations Reminder for Lower-Tier Models (`DO NOT SKIP`):**

- Cache `account_routing_rules` sorted by descending `len(path_prefix)` in memory in `AccountRouter` and rebuild the list only when `account_routing_rules` is modified in `AccountRulesDialog`.

### Step 0 — Repo-state reconciliation

- Inspect `src/wrench/credentials/` and `src/wrench/forge/registry.py`.

### Step 1 — Register `VP-8` settings & create `src/wrench/credentials/account_router.py`

1. In `src/wrench/storage/settings_registry.py`, register:  
   - `credentials.multi_account_rules.enabled` (`BOOL`, default `True`, category `"Forges & CI"`, label `"Enable per-repository / directory multi-account & SSH key routing"`)  
2. Create SQLite table `account_routing_rules` in `wrench.db`:

```sql
CREATE TABLE IF NOT EXISTS account_routing_rules (
    rule_id INTEGER PRIMARY KEY AUTOINCREMENT,
    path_prefix TEXT NOT NULL UNIQUE,
    forge_account_id TEXT,
    git_user_name TEXT,
    git_user_email TEXT,
    ssh_key_path TEXT
);
```

3. Create `src/wrench/credentials/account_router.py` with `resolve_account_for_repo(repo_path: str) -> AccountRoute | None` (matching longest `path_prefix` when `credentials.multi_account_rules.enabled` is `True`).  
4. In `src/wrench/core/write_ops.py`, if `resolve_account_for_repo(repo_path)` returns an `ssh_key_path`, pass `GIT_SSH_COMMAND="ssh -i <ssh_key_path> -o IdentitiesOnly=yes"` in the subprocess environment for `fetch`, `pull`, `push`, and `clone`.  
- **Completion Gate:** `pytest tests/credentials/test_multi_account.py`

### Step 2 — Build `src/wrench/ui/dialogs/account_rules_dialog.py`

- Create `AccountRulesDialog(QDialog)` accessible from Preferences and the top-right Account Switcher pill in `MainWindow`, allowing users to map directory prefixes (e.g. `~/work/` vs `~/personal/`) to specific forge accounts, SSH keys, and `user.name`/`user.email`.  
- **Completion Gate:** `pytest tests/ui/test_account_rules_dialog.py`

### Forbidden Decisions for Lower-Tier Models

- DO NOT store API tokens in `account_routing_rules`; store only the `forge_account_id` pointer and fetch the actual secret from `secretstorage` (`NFR-3`).

### Acceptance Check

- [ ] Repositories under `~/work/` automatically authenticate with the Work forge token and Work SSH key, and apply the Work author identity on commit.

## VP-9 — Custom Forge Domain Registration UI & SourceForge Adapter (`FR-6.3`, `FR-6.4`)

**Why this position:** Completes the extensible forge plugin architecture (`SRS §3.6`). **Prerequisites:** `VP-8` acceptance check passed. **Mandatory UI Spec Reference:** MUST read and implement `ui-planning.md §6.11` (Custom Forge Domains & Plugins section) and `§8 Step 36`. **Mandatory Optimizations Reminder for Lower-Tier Models (`DO NOT SKIP`):**

- Discover third-party `importlib.metadata.entry_points(group="wrench.forge.adapters")` lazily only when `forge.enabled` and `forge.allow_third_party_entrypoint_plugins` are both `True`.

### Step 0 — Repo-state reconciliation

- Inspect `src/wrench/forge/registry.py` and `src/wrench/forge/adapters/`.

### Step 1 — Register `VP-9` settings & create `src/wrench/forge/adapters/sourceforge.py`

1. In `src/wrench/storage/settings_registry.py`, register:  
   - `forge.sourceforge.enabled` (`BOOL`, default `True`, category `"Forges & CI"`, label `"Enable SourceForge adapter"`, parent `"forge.enabled"`)  
2. Create SQLite table `custom_forge_domains(domain TEXT PRIMARY KEY, adapter_name TEXT NOT NULL, api_base_url TEXT NOT NULL)` in `wrench.db`.  
3. Create `src/wrench/forge/adapters/sourceforge.py` implementing Allura REST API endpoints (`/rest/p/{project}/{mount}/merge-requests/` and `/rest/p/{project}/tickets/`) against `ForgeCapabilities`.  
4. Update `src/wrench/forge/registry.py` to resolve self-hosted domains from `custom_forge_domains` before falling back to hostname heuristics.  
- **Completion Gate:** `pytest tests/forge/test_sourceforge_adapter.py`

### Step 2 — Add Custom Forge Domain & Plugin Inspector UI in Preferences

- Add a `"Custom Forge Domains & Plugins"` section inside `SettingsDialog` (`Forges & CI` category) allowing users to add/remove custom self-hosted domain mappings (e.g. `git.internal.corp -> gitlab`) and toggle individual entry-point plugins on/off.  
- **Completion Gate:** `pytest tests/ui/test_custom_forge_domains_ui.py`

### Forbidden Decisions for Lower-Tier Models

- DO NOT allow unvalidated `http://` plaintext URLs for custom forge domains unless the user explicitly checks `"Allow insecure HTTP for local/LAN instance"`.

### Acceptance Check

- [ ] Self-hosted domains map cleanly to their chosen adapter; `sourceforge.py` loads MRs and tickets when `forge.sourceforge.enabled` is `True` and is completely bypassed when `False`.

## VP-10 — Custom External Diff/Merge Tools & Intra-Line / `--color-moved` Diffing (`FR-8.3`, `FR-8.4`)

**Why this position:** Upgrades Wrench's diff viewer and 3-way merge tool with word-level diffs, moved-block detection, and external tool launching. **Prerequisites:** `VP-9` acceptance check passed. **Mandatory UI Spec Reference:** MUST read and implement `ui-planning.md §3.2` (Split/Unified Diff Toggle `Ctrl+D`, Interactive Diff Minimap Scrubber, Sticky Function Header, `Alt+W` Whitespace Peek, Intra-line & `--color-moved`), `§3.3`, and `§8 Step 37`. **Mandatory Optimizations Reminder for Lower-Tier Models (`DO NOT SKIP`):**

- **Viewport-Only Highlighting & Hunk Cap:** Skip `difflib.SequenceMatcher` intra-line diffing on hunks \> 500 lines; highlight only visible viewport blocks; and down-sample the Diff Minimap scrubber to at most `200` vertical pixel buckets so painting the minimap takes `< 0.5ms`.

### Step 0 — Repo-state reconciliation

- Inspect diff and merge widgets in `src/wrench/ui/` and diff generation in `src/wrench/core/read_ops.py`.

### Step 1 — Register `VP-10` settings & create `src/wrench/core/external_tools.py`

1. In `src/wrench/storage/settings_registry.py`, register:  
   - `diff.syntax_highlighting.enabled` (`BOOL`, default `True`, category `"Diff & Merge"`, label `"Enable syntax highlighting in diff viewer"`)  
   - `diff.intraline_word_diff.enabled` (`BOOL`, default `True`, category `"Diff & Merge"`, label `"Highlight intra-line word/character changes"`)  
   - `diff.color_moved.enabled` (`BOOL`, default `False`, category `"Diff & Merge"`, label `"Highlight moved code blocks with distinct colors (--color-moved)"`)  
   - `diff.external_tool.enabled` (`BOOL`, default `False`, category `"Diff & Merge"`, label `"Enable launching external diff tool"`)  
   - `diff.external_tool.command` (`STR`, default `"meld {local} {remote}"`, category `"Diff & Merge"`, label `"External diff command template"`, parent `"diff.external_tool.enabled"`)  
   - `merge.external_tool.enabled` (`BOOL`, default `False`, category `"Diff & Merge"`, label `"Enable launching external 3-way merge tool"`)  
   - `merge.external_tool.command` (`STR`, default `"meld {local} {base} {remote} -o {merged}"`, category `"Diff & Merge"`, label `"External merge command template"`, parent `"merge.external_tool.enabled"`)  
2. Create `src/wrench/core/external_tools.py` with `launch_external_diff(repo_path: str, file_path: str, staged: bool = False) -> None` and `launch_external_merge(repo_path: str, file_path: str) -> None` that materialize temporary `base`/`local`/`remote` blobs and invoke the configured command via `shlex.split` (`shell=False`).  
3. Create `src/wrench/ui/diff_view/diff_widget.py` computing intra-line character/word spans using Python's `difflib.SequenceMatcher` (skipped immediately when `diff.intraline_word_diff.enabled` is `False`) and moved-block spans when `diff.color_moved.enabled` is `True`.  
- **Completion Gate:** `pytest tests/core/test_external_tools_and_diff.py`

### Step 2 — Build Zero-Copy Virtualized `DiffLineModel`, `PatchByteIndex` & `DiffWidget` UX (`OPT-8`, `FR-8.14`)

1. In `src/wrench/storage/settings_registry.py`, also register:  
   - `diff.virtualized_renderer.enabled` (`BOOL`, default `True`, category `"Diff & Merge"`, label `"Use zero-copy virtualized line renderer for large diffs"`)  
   - `diff.lru_cache_lines` (`INT`, default `512`, min `128`, max `4096`, category `"Diff & Merge"`, label `"LRU cache capacity for highlighted diff lines"`)  
   - `diff.coalesce_switch_ms` (`INT`, default `35`, min `0`, max `250`, category `"Diff & Merge"`, label `"File-selection coalescing delay in milliseconds"`)  
   - `diff.fold_unchanged_context.enabled` (`BOOL`, default `True`, category `"Diff & Merge"`, label `"Collapse unchanged context regions into expandable divider rows"`)  
2. In `src/wrench/ui/diff_view/diff_widget.py`, implement:

```py
class PatchByteIndex:
    """Indexes raw UTF-8 patch bytes into flat C-arrays in < 3ms for 50,000 lines."""

    raw_bytes: bytes
    line_starts: array  # array('I')
    line_lengths: array  # array('H')
    line_flags: array  # array('B'): 0=ctx, 1=add, 2=del, 3=hunk_hdr, 4=folded_divider
    old_linenos: array  # array('I')
    new_linenos: array  # array('I')
```

   - Implement `DiffLineModel(QAbstractListModel)` \+ `QListView` (`setUniformItemSizes(True)`) and `DiffRowDelegate(QStyledItemDelegate)` that decodes and highlights **only** visible rows `[first_visible_row - 20 : last_visible_row + 20]`, storing computed `(intraline_spans, syntax_tokens)` in an `lru_cache(maxsize=512)` (`OPT-8`).  
   - Implement Split/Unified toggle (`Ctrl+D`), `DiffMinimapWidget` (`12px` right gutter downsampled to `<= 200` buckets), `StickyFunctionHeaderWidget` (`24px` top banner), `Alt+W` whitespace peek, and a `35ms` single-shot `QTimer` coalescing rapid file-selection changes (`ui-planning.md §3.2–§3.3`).  
- **Completion Gate:** `pytest tests/ui/test_diff_enhancements.py tests/meta/test_no_shortcuts_guard.py`

### Forbidden Decisions for Lower-Tier Models

- DO NOT run `difflib.SequenceMatcher` on hunks exceeding 500 lines (`diff.max_intraline_hunk_lines = 500`) to prevent UI frame drops on minified files.

### Acceptance Check

- [ ] Intra-line word diffs and `--color-moved` blocks render accurately and toggle off with zero overhead; external diff/merge tools launch with the right temporary files.

## VP-11 — Advanced History Search (Pickaxe `-S`/`-G`) & Visual Reflog Inspector (`FR-9.1`–`9.3`)

**Why this position:** Provides deep commit search and a visual time-travel safety net (`git reflog`) before advanced rebasing/bisecting phases. **Prerequisites:** `VP-10` acceptance check passed. **Mandatory UI Spec Reference:** MUST read and implement `ui-planning.md §4.1` (Expandable Search/Pickaxe Bar), `§6.7` (`ReflogDialog`), and `§8 Step 38`. **Mandatory Optimizations Reminder for Lower-Tier Models (`DO NOT SKIP`):**

- Debounce the `HistoryTab` search input by `200ms` and attach a monotonic `request_id` (`OPT-6`) so typing fast cancels/ignores outdated `git log -S` subprocesses.

### Step 0 — Repo-state reconciliation

- Inspect `src/wrench/core/read_ops.py` and `src/wrench/ui/tabs/history_tab.py`.

### Step 1 — Register `VP-11` settings & create `src/wrench/core/reflog_ops.py`

1. In `src/wrench/storage/settings_registry.py`, register:  
   - `search.pickaxe_enabled` (`BOOL`, default `True`, category `"Blame & Search"`, label `"Enable code-change pickaxe search (-S / -G) in History"`)  
   - `reflog.inspector_ui.enabled` (`BOOL`, default `True`, category `"Safety & Backups"`, label `"Enable Visual Reflog Time-Travel Inspector"`)  
   - `reflog.max_entries` (`INT`, default `250`, min `50`, max `2000`, category `"Safety & Backups"`, label `"Maximum reflog entries to load"`, parent `"reflog.inspector_ui.enabled"`)  
2. Create `src/wrench/core/reflog_ops.py`:

```py
@dataclass(frozen=True)
class ReflogRecord:
    index: int  # e.g., 0 for HEAD@{0}
    ref_selector: str  # "HEAD@{0}"
    old_oid: str
    new_oid: str
    committer: str
    timestamp: int
    action: str  # e.g., "commit", "rebase (finish)", "reset"
    message: str
    is_unreachable_from_head: bool
```

   - `list_reflog(repo_path: str, ref_name: str = "HEAD", limit: int = 250) -> list[ReflogRecord]` using `pygit2.Repository(repo_path).references[ref_name].log()`.  
   - `search_commits_advanced(repo_path: str, query: str, author: str | None = None, path_filter: str | None = None, pickaxe_literal: str | None = None, pickaxe_regex: str | None = None, limit: int = 500) -> list[str]`.  
- **Completion Gate:** `pytest tests/core/test_reflog_and_search.py`

### Step 2 — Build `src/wrench/ui/dialogs/reflog_dialog.py` & Advanced Filter Bar in `HistoryTab`

- Create `ReflogDrawer(QDialog)` displaying chronological `HEAD@{n}` operations with badges highlighting orphaned/unreachable commits, and 1-click buttons to `Create Branch Here`, `Cherry-Pick Commit`, or `Reset Branch to HEAD@{n}`.  
- Add expandable Author, Path, and Pickaxe (`-S`/`-G`) filter fields to `HistoryTab`'s search bar.  
- Hide the Reflog toolbar button when `reflog.inspector_ui.enabled` is `False`.  
- **Completion Gate:** `pytest tests/ui/test_reflog_and_search_ui.py`

### Forbidden Decisions for Lower-Tier Models

- DO NOT shell out to `git reflog` for reading `HEAD` reflog entries; use `pygit2`'s native `Reference.log()` iterator so parsing is immune to custom user `log.date` or `format.pretty` gitconfigs.

### Acceptance Check

- [ ] Searching history by message, author, file path, and `-S` pickaxe filters `CommitGraphWidget`; opening `ReflogDrawer` recovers a hard-reset commit in one click.

## VP-12 — Git LFS Lock Manager & `.gitattributes` Tracked Pattern Editor (`FR-4.5`)

**Why this position:** Completes Git LFS workflows ([Sublime Merge Forum \#54016](https://forum.sublimetext.com/t/lfs-support/54016)). **Prerequisites:** `VP-11` acceptance check passed. **Mandatory UI Spec Reference:** MUST read and implement `ui-planning.md §6.3` (`LFSLocksDialog`) and `§8 Step 39`. **Mandatory Optimizations Reminder for Lower-Tier Models (`DO NOT SKIP`):**

- Before spawning `git lfs locks`, check if `.gitattributes` contains `filter=lfs` (cached per `.gitattributes` mtime). If the repo does not use LFS, skip all `git lfs` subprocesses automatically.

### Step 0 — Repo-state reconciliation

- Inspect any existing v1 Phase 5 LFS code in `src/wrench/core/` and `src/wrench/ui/`.

### Step 1 — Register `VP-12` settings & create `src/wrench/core/lfs_ops.py`

1. In `src/wrench/storage/settings_registry.py`, register:  
   - `lfs.enabled` (`BOOL`, default `True`, category `"Remotes & LFS"`, label `"Enable Git LFS integration and lock management"`)  
   - `lfs.auto_fetch_locks` (`BOOL`, default `False`, category `"Remotes & LFS"`, label `"Automatically refresh LFS locks on Fetch"`, parent `"lfs.enabled"`)  
2. Create `src/wrench/core/lfs_ops.py` (every function checks `if not settings.get_bool("lfs.enabled", repo_path): return []`):

```py
@dataclass(frozen=True)
class LFSLock:
    lock_id: str
    path: str
    owner_name: str
    locked_at: str
```

   - `list_lfs_locks(repo_path: str) -> list[LFSLock]` (`git -C <repo_path> lfs locks --json`).  
   - `lock_lfs_file(repo_path: str, file_path: str) -> None` (`git -C <repo_path> lfs lock <file_path>`).  
   - `unlock_lfs_file(repo_path: str, file_path: str, force: bool = False) -> None` (`git -C <repo_path> lfs unlock ...`).  
   - `list_lfs_tracked_patterns(repo_path: str) -> list[str]`, `track_lfs_pattern(repo_path: str, pattern: str) -> None`, and `untrack_lfs_pattern(repo_path: str, pattern: str) -> None`.  
   - `prune_lfs_objects(repo_path: str) -> str` (`git -C <repo_path> lfs prune`).  
- **Completion Gate:** `pytest tests/core/test_lfs_locks.py`

### Step 2 — Build `src/wrench/ui/dialogs/lfs_locks_dialog.py`

- Create `LFSLocksDialog(QDialog)` with two tabs: `Active Locks` (table with `Lock File`, `Unlock`, `Force Unlock` buttons) and `Tracked Patterns (.gitattributes)` (pattern list with `Add Pattern *.psd`, `Remove Pattern`, and `Prune Local LFS Cache`).  
- Add lock icon badges on locked files in `ChangesTab` (hidden when `lfs.enabled` is `False`).  
- **Completion Gate:** `pytest tests/ui/test_lfs_locks_dialog.py`

### Forbidden Decisions for Lower-Tier Models

- DO NOT crash if `git-lfs` binary is not installed on the host Linux system; catch `FileNotFoundError` / exit code `1` gracefully and show an inline `"git-lfs is not installed"` banner inside `LFSLocksDialog`.

### Acceptance Check

- [ ] Tracking a pattern updates `.gitattributes`, locking/unlocking files updates `LFSLocksDialog`, and setting `lfs.enabled = False` skips all `git lfs` subprocess calls.

## VP-13 — System Tray Status Indicator & XDG Global Shortcuts (`FR-12.1`)

**Why this position:** Delivers optional desktop-level integration that users can toggle off completely if they prefer standard window-closing behavior. **Prerequisites:** `VP-12` acceptance check passed. **Mandatory UI Spec Reference:** MUST read and implement `ui-planning.md §1.1`, `§1.3`, and `§8 Step 40`. **Mandatory Optimizations Reminder for Lower-Tier Models (`DO NOT SKIP`):**

- Do not instantiate `QSystemTrayIcon` at all when `desktop.system_tray.enabled` is `False` (default), saving D-Bus StatusNotifierItem registration overhead at startup.

### Step 0 — Repo-state reconciliation

- Inspect `src/wrench/ui/main_window.py` and `src/wrench/app.py`.

### Step 1 — Register `VP-13` settings & create `src/wrench/ui/tray_manager.py`

1. In `src/wrench/storage/settings_registry.py`, register:  
   - `desktop.system_tray.enabled` (`BOOL`, default `False`, scope `SettingScope.GLOBAL_ONLY`, category `"General & UI"`, label `"Show Wrench icon in Linux system tray"`)  
   - `desktop.minimize_to_tray_on_close` (`BOOL`, default `False`, scope `SettingScope.GLOBAL_ONLY`, category `"General & UI"`, label `"Keep Wrench running in system tray when main window is closed"`, parent `"desktop.system_tray.enabled"`)  
   - `desktop.notifications.enabled` (`BOOL`, default `True`, scope `SettingScope.GLOBAL_ONLY`, category `"General & UI"`, label `"Show desktop notifications for background fetch and CI failures"`)  
   - `desktop.quick_toggle_shortcut` (`STR`, default `"Ctrl+Alt+G"`, scope `SettingScope.GLOBAL_ONLY`, category `"General & UI"`, label `"Global shortcut to focus/hide Wrench window"`)  
2. Create `src/wrench/ui/tray_manager.py` wrapping `QSystemTrayIcon`:  
   - When `desktop.system_tray.enabled` is `False` (default for clean minimalism, or when toggled off by user), `QSystemTrayIcon.hide()` is called and `closeEvent` on `MainWindow` exits the application normally.  
   - When `True`, displays tray menu (`Show/Hide Wrench`, `Recent Repositories`, `Fetch All`, `Quit`).  
- **Completion Gate:** `pytest tests/ui/test_system_tray.py`

### Forbidden Decisions for Lower-Tier Models

- DO NOT block `MainWindow.close()` when `desktop.system_tray.enabled` is `False` or when `QSystemTrayIcon.isSystemTrayAvailable()` returns `False` (e.g. on trayless tiling window managers).

### Acceptance Check

- [ ] Toggling `desktop.system_tray.enabled` shows/hides the tray icon immediately, and `desktop.minimize_to_tray_on_close` intercepts window close only when both settings are `True`.

## VP-14 — Scheduled Safety Stash & Background Snapshot Manager (`FR-8.5`)

**Why this position:** Extends `core/snapshots.py` with periodic background safety backups and a visual Snapshot Restore Browser. **Prerequisites:** `VP-13` acceptance check passed. **Mandatory UI Spec Reference:** MUST read and implement `ui-planning.md §6.4` (`SnapshotsPanel`) and `§8 Step 41`. **Mandatory Optimizations Reminder for Lower-Tier Models (`DO NOT SKIP`):**

- In `SnapshotScheduler`, before running `git stash create` on a timer tick, check if the repository's `.git/index` mtime or working-tree dirty state has changed since the last snapshot OID; if unchanged, skip subprocess execution completely.

### Step 0 — Repo-state reconciliation

- Inspect `src/wrench/core/snapshots.py` and `src/wrench/storage/`.

### Step 1 — Register `VP-14` settings & extend `src/wrench/core/snapshots.py`

1. In `src/wrench/storage/settings_registry.py`, register:  
   - `safety.scheduled_backups.enabled` (`BOOL`, default `True`, category `"Safety & Backups"`, label `"Enable periodic background safety snapshots of dirty working trees"`)  
   - `safety.scheduled_interval_minutes` (`INT`, default `15`, min `5`, max `240`, category `"Safety & Backups"`, label `"Interval between automatic safety snapshots (minutes)"`, parent `"safety.scheduled_backups.enabled"`)  
   - `safety.max_snapshots_per_repo` (`INT`, default `30`, min `5`, max `200`, category `"Safety & Backups"`, label `"Maximum safety snapshots retained per repository"`)  
   - `safety.include_untracked_tar` (`BOOL`, default `True`, category `"Safety & Backups"`, label `"Include untracked working-tree files in safety snapshots"`)  
2. In `src/wrench/core/snapshots.py`:  
   - Add `SnapshotScheduler(QObject)` using a `QTimer` driven by `safety.scheduled_interval_minutes`. When `safety.scheduled_backups.enabled` is toggled `False`, call `timer.stop()` immediately so zero background timers fire.  
   - Deduplicate snapshots: if `git stash create` returns the exact same `oid` as the most recent snapshot for `repo_path`, do not insert a duplicate row.  
   - Prune oldest rows beyond `safety.max_snapshots_per_repo`.  
- **Completion Gate:** `pytest tests/core/test_scheduled_backups.py`

### Step 2 — Build `src/wrench/ui/snapshots_panel/__init__.py`

- Create `SnapshotsDialog(QDialog)` (`Repository -> Safety Snapshots & Backups...`) listing all pre-operation and scheduled snapshots for the repo with diff preview, `Restore to Working Tree`, `Create Branch from Snapshot`, and `Delete All Snapshots`.  
- **Completion Gate:** `pytest tests/ui/test_snapshots_dialog.py`

### Forbidden Decisions for Lower-Tier Models

- DO NOT mutate `refs/stash` when creating safety snapshots; always use `git stash create` and store the returned commit OID in `wrench.db` (`safety_snapshots` table) so the user's manual `git stash list` remains completely untouched.

### Acceptance Check

- [ ] Dirty working trees are snapshotted at the configured interval, restored cleanly via `SnapshotsDialog`, and the timer stops immediately when `safety.scheduled_backups.enabled` is set to `False`.

## VP-15 — Post-v1 Linux Distro Packaging & XDG Secret Portal Fallback (`VP-15a–d`, `FR-12.4`)

**Why this position:** Completes the four v1 Phase 8 packaging carry-overs (`VP-15a–d`) and adds XDG Desktop Portal secret storage fallback for strict Flatpak sandboxes. **Prerequisites:** `VP-14` acceptance check passed. **Mandatory UI Spec Reference:** MUST read and implement `ui-planning.md §6.11` (Credential Storage Backend selector) and `§8 Step 42`. **Mandatory Optimizations Reminder for Lower-Tier Models (`DO NOT SKIP`):**

- Cache unlocked session credentials in memory for the current process lifetime when `credentials.backend_mode` is active so repeated `git fetch` calls do not trigger redundant D-Bus round-trips.

### Step 0 — Repo-state reconciliation

- Inspect `packaging/` and `src/wrench/credentials/`.

### Step 1 — Register `VP-15` settings & implement `src/wrench/credentials/portal_secret.py` (`VP-15a`)

1. In `src/wrench/storage/settings_registry.py`, register:  
   - `credentials.backend_mode` (`CHOICE`, default `"auto"`, choices `("auto", "secret_service", "xdg_portal", "memory_only_ephemeral")`, scope `SettingScope.GLOBAL_ONLY`, category `"General & UI"`, label `"Credential storage backend (memory_only never writes secrets to keyring)"`)  
   - `desktop.use_xdg_file_portal` (`BOOL`, default `True`, scope `SettingScope.GLOBAL_ONLY`, category `"General & UI"`, label `"Use native desktop portal file chooser dialogs"`)  
2. Create `src/wrench/credentials/portal_secret.py` implementing the `org.freedesktop.portal.Secret` D-Bus call when running inside Flatpak (`/.flatpak-info` exists) or when `credentials.backend_mode == "xdg_portal"`, plus an in-memory session dict when `credentials.backend_mode == "memory_only_ephemeral"` (for users who do not want Wrench touching their system keyring at all).  
- **Completion Gate:** `pytest tests/packaging/test_portal_secret.py`

### Step 2 — Add native Linux packaging manifests (`VP-15b–d`)

- Create `packaging/aur/PKGBUILD` (`VP-15b`), `packaging/debian/control` \+  `packaging/debian/rules` (`VP-15c`), and `packaging/rpm/wrench.spec` (`VP-15d`), plus CI syntax validation in `tests/packaging/test_distro_manifests.py`.  
- **Completion Gate:** `pytest tests/packaging/test_distro_manifests.py`

### Forbidden Decisions for Lower-Tier Models

- DO NOT fall back to storing plaintext tokens in `wrench.db` or JSON files if both Secret Service and XDG Portal are unavailable; fall back only to `memory_only_ephemeral` for the current process lifetime (`NFR-3`).

### Acceptance Check

- [ ] `credentials.backend_mode` switches cleanly between D-Bus Secret Service, XDG Portal, and ephemeral memory-only mode; packaging manifests pass lint/validation tests.

## VP-16 — Monorepo Engine: Partial Clone, Sparse-Checkout, Adaptive Watcher & 100k+ Commit Graph (`FR-1.16`, `FR-1.18`, `FR-7.4`, `FR-11.3`)

**Why this position:** Solves monorepo scale across clone, filesystem watching, and commit graph virtualization ([GitHub Desktop \#17901](https://github.com/desktop/desktop/issues/17901), [GitButler \#5407](https://github.com/gitbutlerapp/gitbutler/issues/5407)). **Prerequisites:** `VP-15` acceptance check passed. **Mandatory UI Spec Reference:** MUST read and implement `ui-planning.md §4.3` (100k+ Commit Graph Virtualization & `QPixmapCache`), `§6.2` (Clone Filter), `§6.20` (`SparseCheckoutDialog`), and `§8 Step 43`. **Mandatory Optimizations Reminder for Lower-Tier Models (`DO NOT SKIP`):**

- **Strict Viewport Clipping & `QPixmapCache`:** In `CommitGraphWidget.paintEvent`, paint ONLY `commits[first_visible_row:last_visible_row]` and cache rendered pill badges/avatars in `QPixmapCache`.  
- **Lazy Directory Tree Expansion:** In `SparseCheckoutDialog`, populate child folders on `itemExpanded` via `pygit2` tree lookup rather than walking all 200,000 monorepo paths upfront.

### Step 0 — Repo-state reconciliation

- Inspect `CloneDialog`, `CommitGraphWidget`, `src/wrench/watcher/inotify_watcher.py`, and `src/wrench/core/write_ops.py`.

### Step 1 — Register `VP-16` settings & create `src/wrench/core/sparse_checkout.py`

1. In `src/wrench/storage/settings_registry.py`, register:  
   - `monorepo.sparse_checkout_ui.enabled` (`BOOL`, default `True`, category `"Worktrees & Submodules"`, label `"Enable Sparse-Checkout directory manager UI"`)  
   - `clone.default_filter_mode` (`CHOICE`, default `"none"`, choices `("none", "blob:none", "tree:0")`, category `"Remotes & LFS"`, label `"Default partial-clone object filter in Clone dialog"`)  
   - `watcher.monorepo_adaptive_fallback.enabled` (`BOOL`, default `True`, category `"Watcher & Performance"`, label `"Automatically fall back to .git-only watching when inotify limit is reached"`, parent `"watcher.inotify.enabled"`)  
   - `performance.graph_page_size` (`INT`, default `500`, min `100`, max `5000`, category `"Watcher & Performance"`, label `"Number of commits fetched per scroll page in Commit Graph"`)  
   - `maintenance.auto_commit_graph.enabled` (`BOOL`, default `True`, category `"Watcher & Performance"`, label `"Maintain .git/objects/info/commit-graph in background for fast graph loading"`)  
2. Create `src/wrench/core/sparse_checkout.py`:  
   - `is_sparse_checkout_enabled(repo_path: str) -> bool`  
   - `init_sparse_checkout(repo_path: str, cone: bool = True) -> None` (`["git", "-C", repo_path, "sparse-checkout", "init", "--cone"]`)  
   - `list_sparse_directories(repo_path: str) -> list[str]` (`["git", "-C", repo_path, "sparse-checkout", "list"]`)  
   - `set_sparse_directories(repo_path: str, dirs: list[str]) -> None` (`["git", "-C", repo_path, "sparse-checkout", "set", *dirs]`)  
   - `disable_sparse_checkout(repo_path: str) -> None` (`["git", "-C", repo_path, "sparse-checkout", "disable"]`)  
   - `list_head_top_directories(repo_path: str, max_depth: int = 2) -> list[str]` (walks `HEAD` tree via `pygit2` without requiring working-tree checkout).  
3. Update `clone_repository()` in `src/wrench/core/write_ops.py` to accept `filter_spec: str | None = None` (`--filter=blob:none`) and `sparse: bool = False` (`--sparse`).  
- **Completion Gate:** `pytest tests/core/test_sparse_checkout.py`

### Step 2 — Adaptive Watcher Fallback, 100k+ Graph Pagination & `SparseCheckoutDialog`

1. In `src/wrench/watcher/inotify_watcher.py`: catch `OSError` (`errno.ENOSPC` / `errno.EMFILE`). When `watcher.monorepo_adaptive_fallback.enabled` is `True`, switch to watching only `<gitdir>/HEAD`, `<gitdir>/index`, and `<gitdir>/refs/` instead of recursive working-tree watching, and emit a non-modal info signal.  
2. In `CommitGraphWidget` / `HistoryTab`: fetch commits in chunks of `settings.get_int("performance.graph_page_size", repo_path)` as the user scrolls within 20% of the bottom scrollbar, and trigger `git -C <repo_path> commit-graph write --reachable` in a low-priority worker on repo open if `maintenance.auto_commit_graph.enabled` is `True`.  
3. Create `src/wrench/ui/dialogs/sparse_checkout_dialog.py` (`Repository -> Sparse-Checkout Directories...`, hidden if `monorepo.sparse_checkout_ui.enabled` is `False`).  
- **Completion Gate:** `pytest tests/ui/test_large_graph_virtualization.py`

### Forbidden Decisions for Lower-Tier Models

- DO NOT load all 100,000+ `pygit2.Commit` objects into a Python `list` at once on repository open; always slice the `pygit2.Walker` iterator by `performance.graph_page_size`.

### Acceptance Check

- [ ] Partial clone (`--filter=blob:none`) and `SparseCheckoutDialog` materialize only selected directories; 100k+ commit graphs load in \<1.5s and paginate smoothly; disabling `maintenance.auto_commit_graph.enabled` skips background `commit-graph write`.

## VP-17 — Git Hook Runner, Login-Shell `PATH` Hydration & `--no-verify` Controls (`FR-2.7`, `FR-2.8`)

**Why this position:** Eliminates Linux/Flatpak pre-commit hook failures (`nvm`, `pyenv`, `mise`, Husky, `.githooks`) while giving users full `--no-verify` control ([GitHub Desktop \#11802](https://github.com/desktop/desktop/issues/11802), [\#17385](https://github.com/desktop/desktop/issues/17385), [\#19247](https://github.com/desktop/desktop/issues/19247), [\#20756](https://github.com/desktop/desktop/issues/20756), [\#21317](https://github.com/desktop/desktop/issues/21317)). **Prerequisites:** `VP-16` acceptance check passed. **Mandatory UI Spec Reference:** MUST read and implement `ui-planning.md §3.1` (`HookOutputDrawer` & Bypass Checkbox), `§5.5 OPT-5`, and `§8 Step 44`. **Mandatory Optimizations Reminder for Lower-Tier Models (`DO NOT SKIP`):**

- Cache the login-shell hydrated `PATH` once at application startup (`hook_env.py`), and enforce `setMaximumBlockCount(5000)` \+ `50ms` batched UI flushes (`OPT-5`) on `HookOutputDrawer`.

### Step 0 — Repo-state reconciliation

- Inspect `src/wrench/core/write_ops.py` and `src/wrench/ui/tabs/changes_tab.py`.

### Step 1 — Register `VP-17` settings & create `src/wrench/core/hook_env.py`

1. In `src/wrench/storage/settings_registry.py`, register:  
   - `hooks.enabled` (`BOOL`, default `True`, category `"Hooks & Signing"`, label `"Run Git hooks during Commit, Merge, and Push (uncheck to always pass --no-verify)"`)  
   - `hooks.show_bypass_checkbox_in_ui` (`BOOL`, default `True`, category `"Hooks & Signing"`, label `"Show 'Bypass Hooks (--no-verify)' checkbox in Commit/Push UI"`, parent `"hooks.enabled"`)  
   - `hooks.hydrate_login_shell_path` (`BOOL`, default `True`, category `"Hooks & Signing"`, label `"Load user login-shell PATH (nvm, pyenv, mise, cargo) for hook execution"`, parent `"hooks.enabled"`)  
   - `hooks.custom_extra_path` (`STR`, default `""`, category `"Hooks & Signing"`, label `"Additional colon-separated PATH directories for Git hooks"`, parent `"hooks.enabled"`)  
   - `hooks.stream_output_drawer.enabled` (`BOOL`, default `True`, category `"Hooks & Signing"`, label `"Show live hook output drawer during Commit and Push"`, parent `"hooks.enabled"`)  
   - `hooks.timeout_seconds` (`INT`, default `300`, min `10`, max `3600`, category `"Hooks & Signing"`, label `"Hook execution timeout in seconds"`, parent `"hooks.enabled"`)  
2. Create `src/wrench/core/hook_env.py`:  
   - `get_hydrated_hook_env(repo_path: str, settings: SettingsRegistry) -> dict[str, str]`:  
     - Starts from `os.environ.copy()`.  
     - If `settings.get_bool("hooks.hydrate_login_shell_path", repo_path)` is `True`, runs `[os.environ.get("SHELL", "/bin/bash"), "-lic", "printf '%s' \"$PATH\""]` once with a 3-second timeout, caches the result in memory, and prepends it to `env["PATH"]`.  
     - Appends `settings.get_str("hooks.custom_extra_path", repo_path)` if non-empty.  
   - `list_active_hooks(repo_path: str) -> list[str]`: checks `core.hooksPath` in `pygit2.Repository(repo_path).config` (defaulting to `<gitdir>/hooks`) and lists executable hook scripts (`pre-commit`, `commit-msg`, `pre-push`, etc.).  
3. Update `commit()`, `merge()`, and `push()` in `src/wrench/core/write_ops.py` to accept `no_verify: bool = False`, automatically set `no_verify = True` when `not settings.get_bool("hooks.enabled", repo_path)`, pass `--no-verify` to `git`, and stream `stderr`/`stdout` lines via an optional `on_output_line: Callable[[str], None] | None = None` callback.  
- **Completion Gate:** `pytest tests/core/test_hook_env.py`

### Step 2 — Build `src/wrench/ui/widgets/hook_output_drawer.py` & Bypass Checkbox in `ChangesTab`

- Create `HookOutputDrawer(QWidget)` in `src/wrench/ui/widgets/hook_output_drawer.py` with a monospace `QPlainTextEdit`, ANSI escape stripper, elapsed timer, and `Abort Hook` button.  
- Add a `"Bypass Hooks (--no-verify)"` checkbox next to the `Commit` button in `ChangesTab` (hidden when `hooks.show_bypass_checkbox_in_ui` or `hooks.enabled` is `False`).  
- **Completion Gate:** `pytest tests/ui/test_hook_runner_ui.py`

### Forbidden Decisions for Lower-Tier Models

- DO NOT run `$SHELL -lic` on every single Git command; cache the hydrated `PATH` string once per session and invalidate only if `hooks.hydrate_login_shell_path` or `hooks.custom_extra_path` changes.

### Acceptance Check

- [ ] Husky/pre-commit hooks locate user `node`/`python` via hydrated `PATH` and stream output into `HookOutputDrawer`; toggling `hooks.enabled = False` in Settings automatically passes `--no-verify` on all commits and pushes and hides the hook drawer.

## VP-18 — GPG & SSH Commit/Tag Signing \+ Askpass Bridge & Verification Badges (`FR-2.9`, `FR-2.10`)

**Why this position:** Delivers frictionless OpenPGP and SSH (`gpg.format = ssh`) commit/tag signing and graph verification badges ([GitHub Desktop \#15302](https://github.com/desktop/desktop/issues/15302), [\#16569](https://github.com/desktop/desktop/issues/16569), [\#17309](https://github.com/desktop/desktop/issues/17309), [\#19482](https://github.com/desktop/desktop/issues/19482)). **Prerequisites:** `VP-17` acceptance check passed. **Mandatory UI Spec Reference:** MUST read and implement `ui-planning.md §4.2` (Signature Badges & Hover X-Ray Commit Preview Cards), `§6.5`, and `§8 Step 45`. **Mandatory Optimizations Reminder for Lower-Tier Models (`DO NOT SKIP`):**

- Batch-verify signatures ONLY for the currently visible viewport commit rows (`first_row..last_row`) in a single `git log --no-walk --format=%H|%G?|%GS|%GF` call, and cache `(oid -> SignatureStatus)` in an LRU dict (`maxsize=10000`) so scrolling back and forth never re-verifies the same commit.

### Step 0 — Repo-state reconciliation

- Inspect `src/wrench/core/write_ops.py`, `src/wrench/core/read_ops.py`, and `src/wrench/ui/tabs/history_tab.py`.

### Step 1 — Register `VP-18` settings & create `src/wrench/core/signing_ops.py` and `signing_askpass.py`

1. In `src/wrench/storage/settings_registry.py`, register:  
   - `signing.enabled` (`BOOL`, default `False`, category `"Hooks & Signing"`, label `"Enable GPG / SSH commit and tag signing override in Wrench"`)  
   - `signing.format` (`CHOICE`, default `"auto"`, choices `("auto", "openpgp", "ssh")`, category `"Hooks & Signing"`, label `"Signing key format (gpg.format)"`, parent `"signing.enabled"`)  
   - `signing.key_id_or_path` (`STR`, default `""`, category `"Hooks & Signing"`, label `"Signing GPG Key ID or SSH Public Key Path (~/.ssh/id_ed25519.pub)"`, parent `"signing.enabled"`)  
   - `signing.sign_commits_by_default` (`BOOL`, default `True`, category `"Hooks & Signing"`, label `"Sign commits by default (-S)"`, parent `"signing.enabled"`)  
   - `signing.sign_tags_by_default` (`BOOL`, default `True`, category `"Hooks & Signing"`, label `"Sign tags by default (-s)"`, parent `"signing.enabled"`)  
   - `signing.gui_askpass_fallback.enabled` (`BOOL`, default `True`, category `"Hooks & Signing"`, label `"Prompt for GPG/SSH key passphrase in Wrench GUI if agent is locked"`)  
   - `signing.verify_badges_in_graph.enabled` (`BOOL`, default `True`, category `"Hooks & Signing"`, label `"Verify and display signature badges (Verified/Unverified) in Commit Graph"`)  
2. Create `src/wrench/core/signing_ops.py`:

```py
@dataclass(frozen=True)
class SignatureStatus:
    oid: str
    state: str  # "verified", "unverified_key", "bad", "unsigned"
    signer: str | None
    key_fingerprint: str | None
```

   - `verify_commit_signatures_batch(repo_path: str, oids: list[str], settings: SettingsRegistry) -> dict[str, SignatureStatus]`:  
     - Immediately returns `{}` if `not settings.get_bool("signing.verify_badges_in_graph.enabled", repo_path)`.  
     - Runs `["git", "-C", repo_path, "log", "--no-walk", "--format=%H|%G?|%GS|%GF", *oids]` in a single batch subprocess call (`G` \= good/verified, `U`/`X`/`Y` \= unverified/expired, `B` \= bad, `N` \= unsigned).  
   - `list_available_signing_keys() -> list[tuple[str, str, str]]`: scans `gpg --list-secret-keys --with-colons` and `~/.ssh/*.pub` so users can pick a key from a dropdown in Settings.  
3. Create `src/wrench/credentials/signing_askpass.py` providing a `GIT_ASKPASS` / `SSH_ASKPASS` helper script that communicates over a local Unix domain socket to pop a Qt `QInputDialog.getText(..., QLineEdit.Password)` modal when `signing.gui_askpass_fallback.enabled` is `True`.  
- **Completion Gate:** `pytest tests/core/test_commit_signing.py`

### Step 2 — Render Signature Badges in `CommitGraphWidget` & Key Picker in Settings

- In `CommitGraphWidget` / `HistoryTab`: asynchronously verify visible commit rows when `signing.verify_badges_in_graph.enabled` is `True` and draw a compact `[Verified]` (green), `[Unverified]` (amber), or `[Bad Sig]` (red) pill badge with tooltip showing signer and fingerprint.  
- When `signing.verify_badges_in_graph.enabled` is toggled `False`, immediately clear badges and stop calling `verify_commit_signatures_batch`.  
- **Completion Gate:** `pytest tests/ui/test_signing_badges_ui.py`

### Forbidden Decisions for Lower-Tier Models

- DO NOT spawn one `git verify-commit <oid>` process per commit row (which would spawn 500 processes per page); ALWAYS batch-verify visible OIDs in a single `git log --no-walk --format=%H|%G?|%GS|%GF` call.

### Acceptance Check

- [ ] Commits signed with GPG or SSH (`gpg.format = ssh`) verify and display badges in `CommitGraphWidget`; toggling `signing.verify_badges_in_graph.enabled = False` hides all badges and spawns zero verification processes.

## VP-19 — Interactive `git bisect` Visual Wizard & Automated `bisect run` Controller (`FR-3.6`)

**Why this position:** Provides a visual regression-hunting workflow directly on the DAG commit graph ([Lazygit \#1542](https://github.com/jesseduffield/lazygit/issues/1542), [Lazygit \#5575](https://github.com/jesseduffield/lazygit/issues/5575)). **Prerequisites:** `VP-18` acceptance check passed. **Mandatory UI Spec Reference:** MUST read and implement `ui-planning.md §6.21` (`BisectBannerWidget` & Graph Dimming Overlay) and `§8 Step 46`. **Mandatory Optimizations Reminder for Lower-Tier Models (`DO NOT SKIP`):**

- Compute the set of candidate bisect OIDs asynchronously in a worker (`OPT-6`) and store them in a Python `frozenset[str]` on `CommitGraphWidget` so `paintEvent` checks `oid in self._bisect_candidates` in $O(1)$ time.

### Step 0 — Repo-state reconciliation

- Inspect `src/wrench/ui/tabs/history_tab.py` and `src/wrench/core/read_ops.py`.

### Step 1 — Register `VP-19` settings & create `src/wrench/core/bisect_ops.py`

1. In `src/wrench/storage/settings_registry.py`, register:  
   - `bisect.ui.enabled` (`BOOL`, default `True`, category `"Commit Graph"`, label `"Enable Interactive Git Bisect wizard and graph overlay"`)  
   - `bisect.auto_snapshot_before_start` (`BOOL`, default `True`, category `"Commit Graph"`, label `"Create safety snapshot before starting git bisect"`, parent `"bisect.ui.enabled"`)  
2. Create `src/wrench/core/bisect_ops.py`:

```py
@dataclass(frozen=True)
class BisectStatus:
    active: bool
    current_oid: str | None
    good_oids: tuple[str, ...]
    bad_oids: tuple[str, ...]
    skip_oids: tuple[str, ...]
    culprit_oid: str | None
    estimated_steps_left: int
```

   - `get_bisect_status(repo_path: str) -> BisectStatus`: checks `<gitdir>/BISECT_START` and `<gitdir>/refs/bisect/*`. Returns `BisectStatus(active=False, ...)` immediately if `BISECT_START` does not exist.  
   - `bisect_start(repo_path: str, bad_oid: str, good_oid: str) -> BisectStatus`: runs `["git", "-C", repo_path, "bisect", "start", bad_oid, good_oid]`.  
   - `bisect_mark(repo_path: str, verdict: str, oid: str | None = None) -> BisectStatus`: where `verdict in ("good", "bad", "skip")`, parses stdout for `"<oid> is the first bad commit"` to populate `culprit_oid`.  
   - `bisect_reset(repo_path: str) -> None`: runs `["git", "-C", repo_path, "bisect", "reset"]`.  
   - `bisect_run_script(repo_path: str, command: str, on_output: Callable[[str], None]) -> BisectStatus`: runs `["git", "-C", repo_path, "bisect", "run", *shlex.split(command)]`.  
- **Completion Gate:** `pytest tests/core/test_bisect_ops.py`

### Step 2 — Build `src/wrench/ui/widgets/bisect_banner.py` & Graph Badges

- Create `BisectBannerWidget(QWidget)` shown at the top of `HistoryTab` when `BisectStatus.active` is `True`, featuring `Mark Good`, `Mark Bad`, `Skip Commit`, `Run Automated Test Script...`, and `Reset Bisect` buttons plus remaining step count.  
- Render `[GOOD]`, `[BAD]`, `[SKIP]`, and `[BISECTING]` badges on `CommitGraphWidget` rows and context menu actions `Start Bisect (Mark as Bad)...` / `Mark as Known Good...` (hidden when `bisect.ui.enabled` is `False`).  
- **Completion Gate:** `pytest tests/ui/test_bisect_wizard.py`

### Forbidden Decisions for Lower-Tier Models

- DO NOT allow starting a bisect when `bisect.ui.enabled` is `False`; hide all bisect menu items cleanly.

### Acceptance Check

- [ ] Marking commits Good/Bad or running `bisect_run_script` isolates the exact first bad commit and displays a culprit summary dialog; `Reset Bisect` returns `HEAD` to the original branch.

## VP-20 — Stacked Branches (`--update-refs`), Hunk Routing & Stacked PR Sync (`FR-3.7`, `FR-3.8`, `FR-5.13`)

**Why this position:** Implements modern stacked-branch workflows on top of standard Git refs (`git rebase --update-refs`) without polluting repositories with proprietary metadata ([Lazygit \#2527](https://github.com/jesseduffield/lazygit/issues/2527), [\#4817](https://github.com/jesseduffield/lazygit/issues/4817), [\#4852](https://github.com/jesseduffield/lazygit/issues/4852), [\#5833](https://github.com/jesseduffield/lazygit/issues/5833), [GitButler \#2513](https://github.com/gitbutlerapp/gitbutler/issues/2513), [\#12355](https://github.com/gitbutlerapp/gitbutler/issues/12355)). **Prerequisites:** `VP-19` acceptance check passed. **Mandatory UI Spec Reference:** MUST read and implement `ui-planning.md §6.22` (`StackPanel` & `HunkTargetCommitDialog`) and `§8 Step 47`. **Mandatory Optimizations Reminder for Lower-Tier Models (`DO NOT SKIP`):**

- Execute entire stack cascade rebases in a single `git rebase --update-refs <root_base>` invocation rather than looping `git rebase` branch-by-branch in Python.

### Step 0 — Repo-state reconciliation

- Inspect branch management in `src/wrench/core/`, `src/wrench/storage/`, and `src/wrench/forge/`.

### Step 1 — Register `VP-20` settings & create `src/wrench/core/stacks.py`

1. In `src/wrench/storage/settings_registry.py`, register:  
   - `stacks.enabled` (`BOOL`, default `True`, category `"Branches & Stacks"`, label `"Enable Stacked Branches & Cascade Rebase (--update-refs) UI"`)  
   - `stacks.auto_update_refs_on_amend` (`BOOL`, default `True`, category `"Branches & Stacks"`, label `"Automatically cascade rebase child branches in stack when amending"`, parent `"stacks.enabled"`)  
   - `stacks.hunk_routing_ui.enabled` (`BOOL`, default `True`, category `"Branches & Stacks"`, label `"Enable 'Amend Hunk into Target Commit/Branch' action in Changes tab"`, parent `"stacks.enabled"`)  
   - `forge.stacked_pr_table_in_body.enabled` (`BOOL`, default `True`, category `"Forges & CI"`, label `"Insert Markdown stack navigation table into Stacked PR descriptions"`, parent `"stacks.enabled"`)  
2. Create SQLite table `branch_stacks` in `wrench.db`:

```sql
CREATE TABLE IF NOT EXISTS branch_stacks (
    repo_path TEXT NOT NULL,
    stack_name TEXT NOT NULL,
    branch_name TEXT NOT NULL,
    parent_branch TEXT NOT NULL,
    ordinal INTEGER NOT NULL,
    pr_number INTEGER,
    PRIMARY KEY (repo_path, branch_name)
);
```

3. Create `src/wrench/core/stacks.py`:  
   - `create_stacked_branch(repo_path: str, stack_name: str, new_branch: str, parent_branch: str) -> None`  
   - `list_stack_branches(repo_path: str, stack_name: str | None = None) -> list[StackBranchNode]` (returns `[]` immediately if `not settings.get_bool("stacks.enabled", repo_path)`).  
   - `restack_chain(repo_path: str, stack_name: str) -> None`: checks out the top branch of `stack_name` and runs `["git", "-C", repo_path, "rebase", "--update-refs", root_parent_branch]`.  
   - `recover_squash_merged_parent(repo_path: str, child_branch: str, old_parent_oid: str, target_base_branch: str) -> None`: runs `["git", "-C", repo_path, "rebase", "--onto", target_base_branch, old_parent_oid, child_branch]` ([Lazygit \#4852](https://github.com/jesseduffield/lazygit/issues/4852)).  
   - `amend_patch_into_commit(repo_path: str, target_oid: str, patch_bytes: bytes) -> None`: applies `patch_bytes` via `git apply --cached`, runs `git commit --fixup=<target_oid>`, and runs `git rebase -i --autosquash --autostash --update-refs <target_oid>~1` with `GIT_SEQUENCE_EDITOR=true` ([GitButler \#2513](https://github.com/gitbutlerapp/gitbutler/issues/2513)).  
- **Completion Gate:** `pytest tests/core/test_stacked_branches.py`

### Step 2 — Build `src/wrench/ui/widgets/stack_panel.py` & Stacked PR Sync

- Create `StackPanel(QWidget)` displaying stacked branch chains with `Add Stacked Branch Above`, `Restack All (--update-refs)`, and `Push & Sync Stack PRs` buttons.  
- In `ChangesTab` diff viewer, add context menu action `"Amend Selected Hunk/Lines into Commit..."` opening a commit picker for the current stack/branch (hidden if `stacks.hunk_routing_ui.enabled` or `stacks.enabled` is `False`).  
- Hide `StackPanel` completely when `stacks.enabled` is `False`.  
- **Completion Gate:** `pytest tests/ui/test_stacked_branches_ui.py`

### Forbidden Decisions for Lower-Tier Models

- DO NOT write custom refs under `.git/refs/wrench/` or modify `.git/config` with non-standard sections that break CLI `git` if the user closes Wrench ([GitButler \#14491](https://github.com/gitbutlerapp/gitbutler/issues/14491)); keep stack parent metadata strictly in `wrench.db`.

### Acceptance Check

- [ ] Amending an earlier branch in a 3-branch stack updates child branch refs via `--update-refs`; routing a diff hunk into a historical commit amends it cleanly via `--fixup` \+ `--autosquash`; disabling `stacks.enabled` hides all stack UI with zero overhead.

## VP-21 — Interactive Blame Gutter, `.git-blame-ignore-revs` & Line History (`git log -L`) (`FR-9.4`, `FR-9.5`)

**Why this position:** Delivers fast file blame and line-range history inspection directly from context menus ([GitHub Desktop \#9580](https://github.com/desktop/desktop/issues/9580), [git-cola \#953](https://github.com/git-cola/git-cola/issues/953), [Sublime Merge \#1098](https://github.com/sublimehq/sublime_merge/issues/1098), [Forum \#39746](https://forum.sublimetext.com/t/feature-request-line-history/39746)). **Prerequisites:** `VP-20` acceptance check passed. **Mandatory UI Spec Reference:** MUST read and implement `ui-planning.md §6.23` (`BlameViewerDialog` & `git log -L` Drawer) and `§8 Step 48`. **Mandatory Optimizations Reminder for Lower-Tier Models (`DO NOT SKIP`):**

- Stream `git blame --line-porcelain --incremental` or cache parsed `BlameLine` lists keyed by `(repo_path, file_path, head_oid, use_ignore_revs)` with `OPT-6` generation tokens, and paint the blame gutter only for visible scroll lines.

### Step 0 — Repo-state reconciliation

- Inspect `src/wrench/core/read_ops.py` and diff/file views in `src/wrench/ui/`.

### Step 1 — Register `VP-21` settings & create `src/wrench/core/blame_ops.py`

1. In `src/wrench/storage/settings_registry.py`, register:  
   - `blame.ui.enabled` (`BOOL`, default `True`, category `"Blame & Search"`, label `"Enable Interactive Git Blame viewer and context menu actions"`)  
   - `blame.use_ignore_revs_file` (`BOOL`, default `True`, category `"Blame & Search"`, label `"Respect .git-blame-ignore-revs / blame.ignoreRevsFile"`, parent `"blame.ui.enabled"`)  
   - `blame.age_heatmap_colors.enabled` (`BOOL`, default `True`, category `"Blame & Search"`, label `"Colorize blame gutter by commit age heatmap"`, parent `"blame.ui.enabled"`)  
   - `line_history.ui.enabled` (`BOOL`, default `True`, category `"Blame & Search"`, label `"Enable 'View Line History (git log -L)' context menu action"`)  
2. Create `src/wrench/core/blame_ops.py`:

```py
@dataclass(frozen=True)
class BlameLine:
    line_no: int
    oid: str
    short_oid: str
    author_name: str
    author_email: str
    timestamp: int
    summary: str
    content: str
```

   - `get_file_blame(repo_path: str, file_path: str, rev: str = "HEAD", use_ignore_revs: bool = True) -> list[BlameLine]`:  
     - If `use_ignore_revs` is `True` and `.git-blame-ignore-revs` exists at `os.path.join(repo_path, ".git-blame-ignore-revs")`, pass `--ignore-revs-file=.git-blame-ignore-revs` to `git -C <repo_path> blame --line-porcelain <rev> -- <file_path>` ([Sublime Merge \#1098](https://github.com/sublimehq/sublime_merge/issues/1098)).  
     - Coalesce empty or missing `author-mail` fields to `""` so commits with empty emails never crash the parser ([Gittyup Issues](https://github.com/Murmele/gittyup/issues)).  
   - `append_commit_to_blame_ignore_revs(repo_path: str, oid: str, comment: str) -> None`: appends `# <comment>\n<oid>\n` to `.git-blame-ignore-revs`.  
   - `get_line_range_history(repo_path: str, file_path: str, start_line: int, end_line: int, max_commits: int = 100) -> str`: runs `["git", "-C", repo_path, "log", "-n", str(max_commits), f"-L{start_line},{end_line}:{file_path}"]`.  
- **Completion Gate:** `pytest tests/core/test_blame_and_line_history.py`

### Step 2 — Build `src/wrench/ui/widgets/blame_viewer.py` & Line History Context Menu

- Create `BlameViewerDialog(QDialog)` displaying file lines alongside an age-heatmap gutter, click-to-select-commit in `HistoryTab`, `"Blame Parent Commit"`, and `"Ignore Commit in .git-blame-ignore-revs"`.  
- Add `"Blame File..."` (visible when `blame.ui.enabled` is `True`) and `"View Selected Line History (git log -L)..."` (visible when `line_history.ui.enabled` is `True`) to the right-click context menu of `ChangesTab`, `HistoryTab` diff views, and the file tree.  
- **Completion Gate:** `pytest tests/ui/test_blame_and_line_history_ui.py`

### Forbidden Decisions for Lower-Tier Models

- DO NOT dereference `signature.email` without `or ""` fallback when parsing blame hunks.

### Acceptance Check

- [ ] Right-clicking selected lines in a diff opens `git log -L` history; `BlameViewerDialog` respects `.git-blame-ignore-revs`; disabling `blame.ui.enabled` or `line_history.ui.enabled` removes their context-menu items immediately.

## VP-22 — Granular Stash Modes (`--staged`, `--keep-index`) & `--skip-worktree` Panel (`FR-10.5`, `FR-10.6`)

**Why this position:** Gives users fine-grained stash controls and local config file ignore tracking ([Lazygit \#458](https://github.com/jesseduffield/lazygit/issues/458), [\#3380](https://github.com/jesseduffield/lazygit/issues/3380), [Sublime Merge \#90](https://github.com/sublimehq/sublime_merge/issues/90), [\#945](https://github.com/sublimehq/sublime_merge/issues/945)). **Prerequisites:** `VP-21` acceptance check passed. **Mandatory UI Spec Reference:** MUST read and implement `ui-planning.md §3.1` (Granular Stash Split-Button & `SkipWorktreePanel`) and `§8 Step 49`. **Mandatory Optimizations Reminder for Lower-Tier Models (`DO NOT SKIP`):**

- Run `git ls-files -v -z` to populate `SkipWorktreePanel` ONLY when `.git/index` mtime changes and `staging.skip_worktree_ui.enabled` is `True`.

### Step 0 — Repo-state reconciliation

- Inspect stash functions in `src/wrench/core/write_ops.py` and `src/wrench/ui/tabs/changes_tab.py`.

### Step 1 — Register `VP-22` settings & create `src/wrench/core/stash_ops.py`

1. In `src/wrench/storage/settings_registry.py`, register:  
   - `stash.granular_modes.enabled` (`BOOL`, default `True`, category `"Staging & Commits"`, label `"Show granular Stash split-button options (--staged, --keep-index, -u)"`, parent `"stash.ui.enabled"`)  
   - `stash.default_mode` (`CHOICE`, default `"all"`, choices `("all", "staged_only", "keep_index", "include_untracked")`, category `"Staging & Commits"`, label `"Default Stash button behavior"`, parent `"stash.ui.enabled"`)  
   - `staging.skip_worktree_ui.enabled` (`BOOL`, default `True`, category `"Staging & Commits"`, label `"Enable 'Ignore Local Modifications (--skip-worktree / --assume-unchanged)' UI"`)  
2. Create `src/wrench/core/stash_ops.py`:  
   - `stash_push_granular(repo_path: str, message: str = "", mode: str = "all", paths: list[str] | None = None) -> None`:  
     - Maps `mode == "staged_only"` \-\> `["--staged"]`, `"keep_index"` \-\> `["--keep-index"]`, `"include_untracked"` \-\> `["--include-untracked"]`, `"all"` \-\> `[]`.  
     - Runs `["git", "-C", repo_path, "stash", "push", *mode_flags, *( ["-m", message] if message else [] ), "--", *(paths or [])]`.  
   - `stash_action_by_index(repo_path: str, index: int, action: str) -> None`: where `action in ("apply", "pop", "drop")`, ALWAYS formatting the target ref as `f"refs/stash@{{{index}}}"` so a branch named `stash` never causes ref ambiguity ([Sublime Merge \#945](https://github.com/sublimehq/sublime_merge/issues/945)).  
   - `set_file_index_flag(repo_path: str, file_path: str, flag: str, enabled: bool) -> None`: where `flag in ("skip-worktree", "assume-unchanged")`, running `["git", "-C", repo_path, "update-index", f"--{'' if enabled else 'no-'}{flag}", "--", file_path]`.  
   - `list_locally_ignored_tracked_files(repo_path: str) -> list[tuple[str, str]]`: returns `[]` immediately if `not settings.get_bool("staging.skip_worktree_ui.enabled", repo_path)`, otherwise parses `git -C <repo_path> ls-files -v -z` for lines starting with `S`  (`skip-worktree`) or `h`  (`assume-unchanged`).  
- **Completion Gate:** `pytest tests/core/test_granular_stash_and_skip_worktree.py`

### Step 2 — Build `src/wrench/ui/widgets/skip_worktree_panel.py` & Stash Split-Button in `ChangesTab`

- Upgrade the Stash button in `ChangesTab` to a split-button (`QToolButton` with `MenuButtonPopup`) offering `Stash All`, `Stash Staged Only (--staged)`, `Stash Unstaged Only (--keep-index)`, and `Stash Including Untracked (-u)` when `stash.granular_modes.enabled` is `True`.  
- Create `SkipWorktreePanel(QWidget)` at the bottom of `ChangesTab` displaying any tracked files marked `skip-worktree` or `assume-unchanged` with a 1-click `Restore Normal Tracking` button, and add `"Ignore Local Changes (--skip-worktree)"` to the `ChangesTab` file context menu (all hidden when `staging.skip_worktree_ui.enabled` is `False`).  
- **Completion Gate:** `pytest tests/ui/test_granular_stash_ui.py`

### Forbidden Decisions for Lower-Tier Models

- DO NOT pass bare `stash@{0}` to `git stash drop/pop/apply`; ALWAYS pass `refs/stash@{0}` (`DEC-4`).

### Acceptance Check

- [ ] `Stash Staged Only (--staged)` stashes only indexed changes; `stash_action_by_index` succeeds even when a branch named `stash` exists; marking a tracked file `--skip-worktree` moves it to `SkipWorktreePanel`, and disabling `staging.skip_worktree_ui.enabled` hides the panel and skips `git ls-files -v`.

## VP-23 — Conflict Memory (`git rerere`), Patch Mailboxes (`format-patch`/`am`) & `Ctrl+K` Custom Actions (`FR-3.9`, `FR-8.6`, `FR-8.7`)

**Why this position:** Completes v2 with `git rerere` conflict memory ([Sublime Merge \#814](https://github.com/sublimehq/sublime_merge/issues/814)), mailing-list patch export/import, and user-defined custom commands ([Lazygit \#3930](https://github.com/jesseduffield/lazygit/issues/3930)) inside a global `Ctrl+K` Command Palette. **Prerequisites:** `VP-22` acceptance check passed. **Mandatory UI Spec Reference:** MUST read and implement `ui-planning.md §6.6` (`git rerere` Merge Banner), `§6.24` (`CommandPaletteDialog` `Ctrl+K`), and `§8 Step 49`. **Mandatory Optimizations Reminder for Lower-Tier Models (`DO NOT SKIP`):**

- Pre-index built-in commands, `SettingsRegistry` boolean toggles, and custom actions in memory so `CommandPaletteDialog` (`Ctrl+K`) fuzzy-filters keystrokes in `< 5ms` on the GUI thread without touching SQLite during typing.

### Step 0 — Repo-state reconciliation

- Inspect the 3-way merge tool in `src/wrench/ui/`, `src/wrench/core/write_ops.py`, and `src/wrench/ui/main_window.py`.

### Step 1 — Register `VP-23` settings & create `src/wrench/core/custom_actions.py`

1. In `src/wrench/storage/settings_registry.py`, register:  
   - `merge.rerere_ui.enabled` (`BOOL`, default `True`, category `"Diff & Merge"`, label `"Enable git rerere automatic conflict resolution memory in 3-Way Merge Tool"`)  
   - `patches.ui.enabled` (`BOOL`, default `True`, category `"Branches & Stacks"`, label `"Enable Patch Export (format-patch) and Apply (git am) menu actions"`)  
   - `patches.am_three_way_by_default` (`BOOL`, default `True`, category `"Branches & Stacks"`, label `"Pass --3way by default when applying patches with git am"`, parent `"patches.ui.enabled"`)  
   - `ui.command_palette.enabled` (`BOOL`, default `True`, category `"General & UI"`, label `"Enable Ctrl+K Fuzzy Command Palette"`)  
   - `custom_actions.enabled` (`BOOL`, default `True`, category `"General & UI"`, label `"Enable user-defined Custom Actions in menus and Command Palette"`)  
2. In `src/wrench/core/write_ops.py`, add:  
   - `get_rerere_resolved_files(repo_path: str) -> list[str]` (`git -C <repo_path> rerere status`) and `rerere_forget_file(repo_path: str, file_path: str) -> None` (`git -C <repo_path> rerere forget -- <file_path>`).  
   - `export_format_patches(repo_path: str, oids_or_range: str, output_dir: str) -> list[str]` (`git -C <repo_path> format-patch -o <output_dir> <oids_or_range>`).  
   - `apply_mailbox_patches(repo_path: str, patch_files: list[str], three_way: bool = True) -> None` (`git -C <repo_path> am --3way ...`).  
3. Create `src/wrench/core/custom_actions.py`:  
   - SQLite table `custom_actions(action_id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, context TEXT NOT NULL, command_template TEXT NOT NULL, shortcut TEXT, show_output_modal INTEGER NOT NULL DEFAULT 1)`.  
   - `render_and_run_custom_action(action: CustomAction, context_vars: dict[str, str], repo_path: str) -> tuple[int, str, str]`: safely quotes each placeholder value (`{repo_path}`, `{branch}`, `{commit_sha}`, `{file_path}`, `{remote_url}`) using `shlex.quote(val)` before substituting into `command_template`, then runs via `subprocess.run(["/bin/sh", "-c", rendered_cmd], cwd=repo_path, capture_output=True, text=True)`.  
- **Completion Gate:** `pytest tests/core/test_rerere_patches_custom_actions.py`

### Step 2 — Build `src/wrench/ui/dialogs/command_palette.py` (`Ctrl+K`) & Custom Actions Editor

- Create `CommandPaletteDialog(QDialog)` bound to `Ctrl+K` and `Ctrl+Shift+P` (disabled when `ui.command_palette.enabled` is `False`) indexing all enabled Wrench actions, branches, worktrees, stashes, and settings toggles (so a user can even toggle any setting directly from `Ctrl+K`\!), plus user-defined Custom Actions when `custom_actions.enabled` is `True`.  
- Add a `"Forget Recorded Rerere Resolution"` button in the 3-way merge banner when `merge.rerere_ui.enabled` is `True`.  
- Add `"Export Patch Series (format-patch)..."` and `"Apply Patch Mailbox (git am)..."` under `Repository` menu (hidden when `patches.ui.enabled` is `False`).  
- **Completion Gate:** `pytest tests/ui/test_command_palette.py`

### Forbidden Decisions for Lower-Tier Models

- DO NOT substitute raw unescaped `{file_path}` or `{branch}` strings into a `/bin/sh -c` command without `shlex.quote()`, as filenames with spaces or shell metacharacters would cause command injection.

### Acceptance Check

- [ ] `Ctrl+K` fuzzy searches and runs built-in commands, custom actions, and settings toggles; `format-patch` and `git am --3way` round-trip commits cleanly; `git rerere` status and forget controls work in the 3-way merge view; disabling any of `merge.rerere_ui.enabled`, `patches.ui.enabled`, `ui.command_palette.enabled`, or `custom_actions.enabled` hides its UI and short-circuits its backend logic immediately.

## VP-24 — 2-Tier Progressive Disclosure Help System: Contextual Beginner Hover Cards & Searchable Offline Help (`F1`) (`FR-8.13`, `DEC-7`)

**Why this position:** Wraps all v1 and v2 surfaces (`VP-0`..`VP-23`, `VP-25`) in a beginner-friendly 2-tier progressive disclosure help system without adding any per-widget memory overhead or unvalidated URI execution risks. **Prerequisites:** `VP-23` acceptance check passed. **Mandatory UI Spec Reference:** MUST read and implement `ui-planning.md §5.6` (Tier 1 `RichHelpTooltip` & Tier 2 `HelpCenterDialog`), `§5.7` (`SEC-6` URI Allowlist), `§6.25`, and `§8 Step 50`. **Mandatory Optimizations & Security Reminder for Lower-Tier Models (`DO NOT SKIP`):**

- **Singleton Tooltip Instance (`0 KB` Per-Widget Overhead):** Install a single `RichHelpTooltipManager(QObject)` event filter that stores only `widget.setProperty("wrench_help_topic_id", topic_id)` on target widgets and reuses one shared `RichHelpTooltip(QFrame)` popup across the entire app.  
- **Lazy Offline Topic Indexing (`OPT-1`):** Load and index the 25 offline help topics in `src/wrench/ui/help_topics.py` only when the user first presses `F1` or clicks `[Read Full Guide (F1) →]`.  
- **Allowlist-Validated `wrench://` URIs (`SEC-6`):** Validate every `wrench://open-setting/<key>` link against `SettingsRegistry.has_key(key)` and every `wrench://highlight-ui/<widget_id>` link against `REGISTERED_UI_WIDGET_IDS` before executing.

### Step 0 — Repo-state reconciliation

- Inspect `src/wrench/ui/main_window.py`, `src/wrench/ui/dialogs/settings_dialog.py`, and `src/wrench/storage/settings_registry.py`.

### Step 1 — Create `src/wrench/ui/help_topics.py` & Singleton `src/wrench/ui/widgets/rich_help_tooltip.py`

1. Create `src/wrench/ui/help_topics.py` defining `@dataclass(frozen=True) class HelpTopic(topic_id, title, category, short_summary, cli_equivalent, shortcut, markdown_body, related_setting_keys, highlight_widget_id)` and a lazy getter `get_help_topics() -> dict[str, HelpTopic]` covering all 25 core & v2 Git/Wrench concepts.  
2. Create `src/wrench/ui/widgets/rich_help_tooltip.py` implementing `RichHelpTooltipManager` with a `500ms` hover trigger timer (`help.tooltip_delay_ms`), a `150ms` cursor-grace timer so users can move the mouse into the popover to click `[Read Full Guide (F1) →]` or `[Switch to Compact Tooltips]`, and automatic fallback to native compact tooltips when `help.tooltip_mode == "compact_shortcut_only"`.  
- **Completion Gate:** `pytest tests/ui/test_rich_help_tooltip.py tests/meta/test_no_shortcuts_guard.py`

### Step 2 — Build `src/wrench/ui/dialogs/help_center_dialog.py` (`F1`) & `UIWidgetHighlighter`

- Create `HelpCenterDialog(QDialog)` bound to `F1` with live keyword search, category tree, offline Markdown renderer, and `SEC-6` allowlist-checked `anchorClicked` handler for `wrench://open-setting/<key>` and `wrench://highlight-ui/<widget_id>`.  
- **Completion Gate:** `pytest tests/ui/test_help_center_dialog.py tests/meta/test_no_shortcuts_guard.py`

### Forbidden Decisions for Lower-Tier Models

- DO NOT instantiate a separate `RichHelpTooltip` `QWidget` per button or row; always use the singleton `RichHelpTooltipManager`.  
- DO NOT pass any `QUrl` from `HelpCenterDialog` to `QDesktopServices.openUrl` or `subprocess` (`SEC-6`).

### Acceptance Check

- [ ] Hovering any control tagged with `attach_help_topic` displays the rich beginner card in `"beginner_rich"` mode, opens `HelpCenterDialog` at that exact topic on clicking `[Read Full Guide (F1) →]`, switches globally to compact tooltips in 1 click, and passes `test_no_shortcuts_guard.py`.

## VP-25 — Multi-Hosting Mirror Resolution Engine & Combined Mirror History DAG (`FR-3.10`, `FR-4.6`, `FR-4.7`, `DEC-8`)

**Why this position:** Unifies multi-remote/multi-forge workflows so repositories mirrored across GitHub, GitLab, Codeberg/Forgejo, Bitbucket, and SourceForge display a combined, de-duplicated commit history tree with instant drift detection and `< 0.5ms` cached mirror resolution. **Prerequisites:** `VP-9` and `VP-16` acceptance checks passed. **Mandatory UI Spec Reference:** MUST read and implement `ui-planning.md §4.2.5` (Combined Multi-Hosting Mirror DAG & Sync/Drift Pills), `§5.5 OPT-7` (5-Stage Mirror Resolution Pipeline), `§6.26` (`MirrorManagerDialog`), and `§8 Step 51`. **Mandatory Optimizations & Security Reminder for Lower-Tier Models (`DO NOT SKIP`):**

- **5-Stage Mirror Resolution (`OPT-7`):**  
  1. Pre-compile URL canonicalization regexes at module import time (`< 10µs` per URL).  
  2. Compute a 16-byte `hashlib.blake2b(digest_size=16)` over sorted `(remote_name, ref_name, oid)` tuples read in-process via `pygit2.Repository(repo_path).references`. If the digest matches `mirror_resolution_cache.ref_digest` in `wrench.db` and `age < mirrors.cache_ttl_seconds` (`300s`), return the cached `MirrorResolutionResult` in **`< 0.5ms` with zero subprocesses or network calls**.  
  3. Verify true mirror equivalence across remotes by comparing their cached root-commit OIDs (`pygit2` walk to initial root commit, cached permanently per `(repo_path, remote_name)` in `wrench.db`), never by naive repo-name string matching.  
  4. When probing remotes on network refresh, use `concurrent.futures.ThreadPoolExecutor(max_workers=4)` running `["git", "-C", repo_path, "ls-remote", "--heads", "--tags", "--refs", "--", remote_name]` with `env={"GIT_TERMINAL_PROMPT": "0"}` and `timeout=4`, paired with shared `httpx.Client(http2=True)` connection pools.  
  5. Maintain an in-memory per-host circuit breaker `_failed_mirror_hosts: dict[str, float]` (`120s` cooldown on timeout/network error) so an offline or VPN-gated mirror never blocks the UI or primary remote.  
- **Security Guard (`SEC-1` & `SEC-2`):** Validate every mirror URL through `security_sanitizer.validate_remote_url(url)` (`SEC-2`, blocking `ext::`, `fd::`, and unapproved loopback SSRF) and pass `"--"` before `remote_name` in `git ls-remote` and `git push` (`SEC-1`).

### Step 0 — Repo-state reconciliation

- Inspect `src/wrench/core/read_ops.py`, `src/wrench/core/write_ops.py`, `src/wrench/forge/registry.py`, and `src/wrench/ui/commit_graph/graph_widget.py`.

### Step 1 — Register `VP-25` settings & create `src/wrench/core/mirror_ops.py` and `src/wrench/forge/mirror_resolver.py`

1. In `src/wrench/storage/settings_registry.py`, register:  
   - `mirrors.unified_history.enabled` (`BOOL`, default `True`, category `"Remotes & LFS"`, label `"Show combined commit history from all hosting mirrors in Commit Graph"`, `help_topic_id="help.mirror_history"`)  
   - `mirrors.collapse_identical_ref_pills` (`BOOL`, default `True`, category `"Remotes & LFS"`, label `"Collapse mirror branch pills pointing to the same commit into a single pill"`, parent `"mirrors.unified_history.enabled"`)  
   - `mirrors.show_drift_warnings` (`BOOL`, default `True`, category `"Remotes & LFS"`, label `"Show warning badges when a mirror branch lags behind or diverges"`, parent `"mirrors.unified_history.enabled"`)  
   - `mirrors.aggregate_cross_forge_ci` (`BOOL`, default `True`, category `"Remotes & LFS"`, label `"Aggregate CI & PR status badges across all active mirror forges"`, parent `"mirrors.unified_history.enabled"`)  
   - `mirrors.push_all_mirrors_by_default` (`BOOL`, default `False`, category `"Remotes & LFS"`, label `"Push to all verified mirror remotes simultaneously on Push"`)  
   - `mirrors.cache_ttl_seconds` (`INT`, default `300`, min `30`, max `3600`, category `"Remotes & LFS"`, label `"Mirror resolution cache TTL in seconds"`)  
   - `mirrors.max_parallel_probes` (`INT`, default `4`, min `1`, max `8`, category `"Remotes & LFS"`, label `"Maximum parallel mirror ls-remote / API probes"`)  
   - `mirrors.probe_timeout_seconds` (`INT`, default `4`, min `1`, max `30`, category `"Remotes & LFS"`, label `"Per-mirror network probe timeout in seconds"`)  
2. Create SQLite table `mirror_resolution_cache` in `wrench.db`:

```sql
CREATE TABLE IF NOT EXISTS mirror_resolution_cache (
    repo_path TEXT NOT NULL,
    remote_name TEXT NOT NULL,
    canonical_host TEXT NOT NULL,
    canonical_slug TEXT NOT NULL,
    forge_provider TEXT,
    root_commit_oid TEXT NOT NULL,
    is_verified_mirror INTEGER NOT NULL DEFAULT 1,
    ref_digest TEXT NOT NULL,
    branch_sync_json TEXT NOT NULL,
    updated_at REAL NOT NULL,
    PRIMARY KEY (repo_path, remote_name)
);
```

3. Create `src/wrench/core/mirror_ops.py` & `src/wrench/forge/mirror_resolver.py` implementing:

```py
@dataclass(frozen=True)
class MirrorBranchDrift:
    branch_name: str
    primary_remote: str
    mirror_remote: str
    primary_oid: str
    mirror_oid: str | None
    ahead_count: int
    behind_count: int
    state: str  # "synced", "behind", "ahead", "diverged", "missing_on_mirror"


@dataclass(frozen=True)
class MirrorNodeGroup:
    commit_oid: str
    branch_name: str
    synced_remotes: tuple[tuple[str, str], ...]  # ((remote_name, provider_short_code), ...)
    drifted_remotes: tuple[MirrorBranchDrift, ...]


# Pre-compiled < 10us 11-Forge URL Canonicalizer (OPT-7 Stage 1)
CANONICAL_FORGE_PATTERNS: tuple[tuple[str, str, re.Pattern[str]], ...] = (
    (
        "github",
        "GH",
        re.compile(
            r"^(?:https://|ssh://git@|git@)github\.com[:/](?P<slug>[^/]+/[^/]+?)(?:\.git)?/?$", re.I
        ),
    ),
    (
        "gitlab",
        "GL",
        re.compile(r"^(?:https://|ssh://git@|git@)gitlab\.com[:/](?P<slug>.+?)(?:\.git)?/?$", re.I),
    ),
    (
        "codeberg",
        "CB",
        re.compile(
            r"^(?:https://|ssh://git@|git@)codeberg\.org[:/](?P<slug>[^/]+/[^/]+?)(?:\.git)?/?$",
            re.I,
        ),
    ),
    (
        "bitbucket",
        "BB",
        re.compile(
            r"^(?:https://[^@]*@?|ssh://git@|git@)bitbucket\.org[:/](?P<slug>[^/]+/[^/]+?)(?:\.git)?/?$",
            re.I,
        ),
    ),
    (
        "sourceforge",
        "SF",
        re.compile(
            r"^(?:https://|ssh://[^@]+@|git://)git\.code\.sf\.net/p/(?P<slug>[^/]+/[^/]+?)(?:\.git)?/?$",
            re.I,
        ),
    ),
    (
        "azure_repos",
        "AZ",
        re.compile(
            r"^(?:https://dev\.azure\.com/(?P<org>[^/]+)/(?P<proj>[^/]+)/_git/(?P<repo>[^/]+?)"
            r"|git@ssh\.dev\.azure\.com:v3/(?P<s_org>[^/]+)/(?P<s_proj>[^/]+)/(?P<s_repo>[^/]+?)"
            r"|https://(?P<v_org>[^.]+)\.visualstudio\.com/(?:DefaultCollection/)?(?P<v_proj>[^/]+)/_git/(?P<v_repo>[^/]+?))(?:\.git)?/?$",
            re.I,
        ),
    ),
    ("radicle", "RAD", re.compile(r"^rad://(?P<slug>z[1-9A-HJ-NP-Za-km-z]{20,60})(?:/.*)?$")),
    (
        "gerrit",
        "GR",
        re.compile(
            r"^(?:ssh://[^@]+@(?P<host>[^:/]+):29418/|https://(?P<h_host>[^/]+)/a/)(?P<slug>.+?)(?:\.git)?/?$",
            re.I,
        ),
    ),
    (
        "sourcehut",
        "SRHT",
        re.compile(
            r"^(?:https://|ssh://git@|git@)git\.sr\.ht[:/]~(?P<slug>[^/]+/[^/]+?)(?:\.git)?/?$",
            re.I,
        ),
    ),
    (
        "tangled",
        "TG",
        re.compile(
            r"^(?:https://|ssh://git@|git@)(?P<host>tangled\.(?:org|sh)|knot[^/]+)[:/]@?(?P<slug>[^/]+/[^/]+?)(?:\.git)?/?$",
            re.I,
        ),
    ),
)


def resolve_repository_mirrors(
    repo_path: str, force_network_probe: bool = False
) -> list[MirrorRemoteStatus]: ...
def build_combined_mirror_dag_walker(
    repo_path: str, include_mirrors: bool = True
) -> list[CommitNode]: ...
def group_mirror_refs_by_commit(repo_path: str) -> dict[str, list[MirrorNodeGroup]]: ...
def sync_mirror_branch(
    repo_path: str,
    source_ref: str,
    target_mirror_remote: str,
    branch_name: str,
    force_with_lease: bool = False,
) -> None: ...
def push_to_all_mirrors_parallel(
    repo_path: str, branch_name: str
) -> dict[str, tuple[bool, str]]: ...
```

- **Completion Gate:** `pytest tests/core/test_mirror_resolution_and_dag.py tests/meta/test_no_shortcuts_guard.py`

### Step 2 — Render Combined Mirror DAG Pills & Drift Badges in `CommitGraphWidget` & Build `MirrorManagerDialog`

1. In `src/wrench/ui/commit_graph/graph_widget.py` (`ui-planning.md §4.2.5`):  
   - Seed the commit graph query with `build_combined_mirror_dag_walker(repo_path, include_mirrors=settings.get_bool("mirrors.unified_history.enabled", repo_path))`.  
   - When `mirrors.collapse_identical_ref_pills` is `True` and `>= 2` mirror remotes point to the same commit OID for `<branch>`, draw a single `QPixmapCache`\-cached pill `[🌐 <branch> · GH · GL · CB ✓]`.  
   - When `mirrors.show_drift_warnings` is `True` and a mirror remote lags/diverges, draw an amber pill `[⚠ <provider>/<branch> ↓N]` with right-click action `Sync Mirror '<remote>/<branch>' Now`.  
   - When `mirrors.aggregate_cross_forge_ci` is `True`, merge CI status badges across all verified mirror forge adapters onto the commit row and Hover X-Ray card.  
2. Create `src/wrench/ui/dialogs/mirror_manager_dialog.py` (`MirrorManagerDialog`, `ui-planning.md §6.26`) with the Mirror Sync Matrix table, root-OID lineage verification badge, circuit-breaker indicator, `Sync Now` / `Push All Mirrors` buttons, and `CliCommandPreviewBar`.  
- **Completion Gate:** `pytest tests/ui/test_mirror_manager_ui.py tests/meta/test_no_shortcuts_guard.py`

### Forbidden Decisions for Lower-Tier Models

- DO NOT probe mirror remotes sequentially on the main GUI thread; always use `mirror_resolution_cache` (`< 0.5ms` `blake2b` digest hit) and dispatch network probes through `ThreadPoolExecutor(max_workers=4)` with the `120s` per-host circuit breaker.  
- DO NOT treat two remotes as mirrors merely because their repository names match; always verify that they share at least one root commit OID (`root_commit_oid`).

### Acceptance Check

- [ ] A repository with `origin` (GitHub), `gitlab` (GitLab), and `codeberg` (Codeberg) displays combined history in `CommitGraphWidget`, collapses synced refs into `[🌐 main · GH · GL · CB ✓]`, highlights lagging mirrors with `[⚠ CB/main ↓2]` and syncs them in 1 click, resolves cached mirror state in `< 0.5ms`, and disables cleanly when `mirrors.unified_history.enabled` is `False`.

## VP-26 — Extended Multi-Forge Suite: Codeberg, Azure Repos, Radicle, Gerrit, SourceHut & Tangled (`FR-6.5`–`6.10`, `DEC-10`)

**Why this position:** Expands Wrench's capability-based forge architecture (`src/wrench/forge/`) to 11 first-class platforms covering community FOSS hosting ([Codeberg / Forgejo API v1](https://forgejo.org/docs/latest/user/api/), [SourceHut sr.ht GraphQL & lists.sr.ht](https://docs.sourcehut.org/git.sr.ht/)), enterprise Git ([Azure Repos REST API v7.1](https://learn.microsoft.com/en-us/rest/api/azure/devops/git/pull-requests?view=azure-devops-rest-7.1)), patchset/change-review systems ([Gerrit Code Review refs/for/ & /a/changes/](https://gerrit-review.googlesource.com/Documentation/intro-user.html)), and next-generation decentralized protocols ([Radicle rad:// & Collaborative Objects](https://radicle.dev/guides/user/), [Tangled tangled.org ATProtocol Knots & Spindles](https://docs.tangled.org/single-page)). **Prerequisites:** `VP-9` and `VP-25` acceptance checks passed. **Mandatory UI Spec Reference:** MUST read and implement `ui-planning.md §4.2.5` (11-Forge Mirror Short Codes `GH`, `GL`, `CB`, `FG`, `BB`, `SF`, `AZ`, `RAD`, `GR`, `SRHT`, `TG`), `§6.18` (Gerrit/Azure voting bars & Radicle/SourceHut/Tangled review drawers), `§6.27` (`ForgeReviewPushDialog`), and `§8 Step 52`. **Mandatory Optimizations & Security Reminder for Lower-Tier Models (`DO NOT SKIP`):**

- **Zero-Impact Per-Forge Disable (`NFR-5`):** Every adapter MUST check `if not self.settings.get_bool("forge.enabled", repo_path) or not self.settings.get_bool(f"forge.{self.provider_key}.enabled", repo_path): return []` on the first line of every method.  
- **Gerrit Zero-Copy XSSI Prefix Slice:** Gerrit REST responses begin with a 5-byte XSSI protection prefix `)]}'\n`. Strip it via `memoryview(raw_bytes)[5:]` (when `raw_bytes.startswith(b")]}'")`) before passing to `json.loads()` rather than allocating a new decoded `str` copy.  
- **Radicle Local COB Ref Fast-Path (`< 1ms`):** For `rad://` repositories, read patch and issue Collaborative Objects (COBs) directly from local Git refs (`refs/namespaces/*/refs/rad/id` and `refs/patches/*`) via `pygit2` or `rad patch --json` / `radicle-httpd` (`127.0.0.1:8080`) without blocking on P2P network discovery; cache parsed COB summaries by `(repo_path, cob_oid)`.  
- **SourceHut Single-Roundtrip GraphQL Batching:** Combine repository metadata, active `todo.sr.ht` tickets, `lists.sr.ht` patchsets, and latest `builds.sr.ht` build statuses into a single GraphQL query (`POST https://git.sr.ht/query`) with cursor pagination.  
- **Tangled DID & Knot Resolution LRU Cache:** Cache ATProtocol handle-to-DID (`@user/repo` \-\> `did:plc:...`) and PDS/Knot endpoint lookups in SQLite (`tangled_knot_cache`, TTL `3600s`) so opening a Tangled repository never blocks on repeated DNS/XRPC identity resolution.  
- **Azure Repos Continuation-Token Pagination & ETag Caching:** Use `$top=50` and `x-ms-continuationtoken` headers on `dev.azure.com/{org}/{project}/_apis/git/repositories/{repo}/pullrequests?api-version=7.1` so large enterprise repos never fetch unbounded PR lists.  
- **Security Hardening (`SEC-1`–`SEC-3`):**  
  - Validate `rad://` URLs against `^rad://z[1-9A-HJ-NP-Za-km-z]{20,60}(/.*)?$` in `security_sanitizer.py` (`SEC-2`).  
  - Validate Gerrit push option values (`topic`, `r`, `cc`) against `^[A-Za-z0-9_.@-]+$` before constructing `HEAD:refs/for/{branch}%{opts}` so a crafted topic or reviewer string can never inject Git refspec flags (`SEC-1`).  
  - Redact Azure DevOps PATs, SourceHut `oauth2`/`personal` bearer tokens, Gerrit HTTP credentials, and ATProto session JWTs in `redact_secrets()` (`SEC-3`).

### Step 0 — Repo-state reconciliation

- Inspect `src/wrench/forge/capability.py`, `src/wrench/forge/registry.py`, `src/wrench/forge/mirror_resolver.py`, and `src/wrench/core/security_sanitizer.py`.

### Step 1 — Register `VP-26` settings, extend `ForgeCapabilities`, and implement the 6 Forge Adapters

1. In `src/wrench/storage/settings_registry.py`, register:

   - **Codeberg (`FR-6.5`):**  
     - `forge.codeberg.enabled` (`BOOL`, default `True`, category `"Forges & CI"`, label `"Enable Codeberg (codeberg.org) adapter & Woodpecker CI badges"`, parent `"forge.enabled"`)  
   - **Azure Repos (`FR-6.6`):**  
     - `forge.azure_repos.enabled` (`BOOL`, default `True`, category `"Forges & CI"`, label `"Enable Azure Repos (dev.azure.com / visualstudio.com) adapter"`, parent `"forge.enabled"`)  
     - `azure_repos.link_work_items.enabled` (`BOOL`, default `True`, category `"Forges & CI"`, label `"Enable Azure Boards #WorkItem autocomplete and PR work-item linking"`, parent `"forge.azure_repos.enabled"`)  
   - **Radicle (`FR-6.7`):**  
     - `forge.radicle.enabled` (`BOOL`, default `True`, category `"Forges & CI"`, label `"Enable Radicle P2P forge adapter (rad://, refs/patches & COBs)"`, parent `"forge.enabled"`)  
     - `radicle.httpd_base_url` (`STR`, default `"http://127.0.0.1:8080"`, category `"Forges & CI"`, label `"Local or seed radicle-httpd API URL"`, parent `"forge.radicle.enabled"`)  
     - `radicle.cli_binary_path` (`PATH`, default `"rad"`, category `"Forges & CI"`, label `"Path to rad CLI binary"`, parent `"forge.radicle.enabled"`)  
   - **Gerrit (`FR-6.8`):**  
     - `forge.gerrit.enabled` (`BOOL`, default `True`, category `"Forges & CI"`, label `"Enable Gerrit Code Review adapter (refs/for/ & Change-Id)"`, parent `"forge.enabled"`)  
     - `gerrit.auto_insert_change_id` (`BOOL`, default `True`, category `"Forges & CI"`, label `"Automatically generate/preserve Change-Id footer in Gerrit commits"`, parent `"forge.gerrit.enabled"`)  
     - `gerrit.default_push_options` (`STR`, default `""`, category `"Forges & CI"`, label `"Default Gerrit push options (e.g. wip,notify=OWNER)"`, parent `"forge.gerrit.enabled"`)  
   - **SourceHut (`FR-6.9`):**  
     - `forge.sourcehut.enabled` (`BOOL`, default `True`, category `"Forges & CI"`, label `"Enable SourceHut (sr.ht) GraphQL, Tickets, Builds & Lists adapter"`, parent `"forge.enabled"`)  
     - `sourcehut.instance_domain` (`STR`, default `"sr.ht"`, category `"Forges & CI"`, label `"SourceHut base domain (git.<domain>, todo.<domain>, lists.<domain>)"`, parent `"forge.sourcehut.enabled"`)  
     - `sourcehut.mailing_list_review.enabled` (`BOOL`, default `True`, category `"Forges & CI"`, label `"Enable lists.sr.ht patchset submission and review UI"`, parent `"forge.sourcehut.enabled"`)  
   - **Tangled (`FR-6.10`):**  
     - `forge.tangled.enabled` (`BOOL`, default `True`, category `"Forges & CI"`, label `"Enable Tangled (tangled.org) ATProtocol Knot & Spindle CI adapter"`, parent `"forge.enabled"`)  
     - `tangled.appview_url` (`STR`, default `"https://tangled.org"`, category `"Forges & CI"`, label `"Tangled AppView / XRPC base URL"`, parent `"forge.tangled.enabled"`)  
     - `tangled.spindle_ci.enabled` (`BOOL`, default `True`, category `"Forges & CI"`, label `"Show Tangled Spindle Nix CI pipeline badges and logs"`, parent `"forge.tangled.enabled"`)  
2. In `src/wrench/forge/capability.py`, add protocol interfaces for multi-paradigm review workflows:

```py
class SupportsMagicRefReviewPush(Protocol):
    def format_review_push_refspec(
        self, target_branch: str, topic: str = "", reviewers: list[str] = (), wip: bool = False
    ) -> str: ...
    def push_for_review(
        self,
        repo_path: str,
        remote_name: str,
        target_branch: str,
        title: str = "",
        description: str = "",
        topic: str = "",
        reviewers: list[str] = (),
        wip: bool = False,
    ) -> str: ...


class SupportsLabelVoting(Protocol):
    def submit_label_votes(
        self, repo_slug: str, change_or_pr_id: str, votes: dict[str, int], message: str = ""
    ) -> None: ...
```

3. Implement the 6 adapter modules under `src/wrench/forge/adapters/` and register them in `src/wrench/forge/registry.py` and `src/wrench/forge/mirror_resolver.py`:

   - `src/wrench/forge/adapters/codeberg.py` (`CodebergAdapter(ForgejoAdapter)`): binds `codeberg.org` (`short_code="CB"`), `/api/v1/repos/{owner}/{repo}/pulls`, `/issues`, and Woodpecker CI status checks.  
   - `src/wrench/forge/adapters/azure_repos.py` (`AzureReposAdapter`): parses `https://dev.azure.com/{org}/{project}/_git/{repo}`, `https://{org}.visualstudio.com/{project}/_git/{repo}`, and `git@ssh.dev.azure.com:v3/{org}/{project}/{repo}` (`short_code="AZ"`); implements PRs (`/pullrequests?api-version=7.1`), inline review threads (`/threads`), 5-state reviewer vote submission (`PUT .../reviewers/{id}` with `vote in (-10, -5, 0, 5, 10)`), Azure Pipelines statuses, and Azure Boards Work Item `#ID` lookup.  
   - `src/wrench/forge/adapters/radicle.py` (`RadicleAdapter`): parses `rad://<rid>` (`short_code="RAD"`); reads/writes Patch and Issue COBs via `radicle-httpd` (`/api/v1/projects/{rid}/patches`) and `rad patch --json` / `rad issue` CLI with `shell=False`; implements `push_for_review` pushing `HEAD:refs/patches` with `-o patch.message="{title}\n\n{description}"` (`git-remote-rad`), `checkout_patch(repo_path, patch_id)` (`rad patch checkout <patch_id>`), and `get_node_status()` (`rad node status --json`).  
   - `src/wrench/forge/adapters/gerrit.py` (`GerritAdapter`): detects Gerrit remotes (`short_code="GR"`), strips `)]}'\n` from `/a/changes/` JSON responses, implements `ensure_change_id_trailer(message: str, tree_oid: str, parent_oid: str, author: str, timestamp: int) -> str` (computing deterministic `Change-Id: I<sha1>` when missing and preserving existing `Change-Id` on amend), formats `HEAD:refs/for/{target_branch}%topic={topic},r={reviewer}` refspecs (`SEC-1` validated), fetches patchset revisions (`refs/changes/{shard}/{change_num}/{patchset}`), and submits `Code-Review` (`-2..+2`) / `Verified` (`-1..+1`) votes via `POST /a/changes/{id}/revisions/{rev}/review`.  
   - `src/wrench/forge/adapters/sourcehut.py` (`SourceHutAdapter`): parses `git.sr.ht/~{owner}/{repo}` (`short_code="SRHT"`), executes batched GraphQL queries against `https://git.sr.ht/query`, `https://todo.sr.ht/query`, `https://lists.sr.ht/query`, and `https://builds.sr.ht/query`, and integrates with `export_format_patches` / `apply_mailbox_patches` (`VP-23`) for `lists.sr.ht` patchset review.  
   - `src/wrench/forge/adapters/tangled.py` (`TangledAdapter`): parses `tangled.org/@{handle}/{repo}`, `tangled.sh/@{handle}/{repo}`, and custom Knot domains (`short_code="TG"`), resolves ATProtocol handles/DIDs with SQLite LRU caching (`tangled_knot_cache`), queries `sh.tangled.repo.pull` (including Jujutsu/Change-ID stacked PR rounds) and `sh.tangled.repo.issue`, and streams Nix **Spindle** CI logs (`sh.tangled.pipeline`).  
4. **Exact Deterministic Implementation Contracts for Each of the 6 New Adapters (Zero Guessing Allowed):**

   - **4.1 Codeberg Adapter (`src/wrench/forge/adapters/codeberg.py` — `FR-6.5`):**

```py
class CodebergAdapter(ForgejoAdapter):
    provider_key = "codeberg"
    short_code = "CB"
    default_api_base = "https://codeberg.org/api/v1"
    default_web_base = "https://codeberg.org"

    def get_ci_statuses(self, repo_slug: str, commit_sha: str) -> list[CIStatusItem]:
        # Short-circuit immediately if forge.enabled or forge.codeberg.enabled is False
        if not self.is_enabled():
            return []
        # Queries GET https://codeberg.org/api/v1/repos/{owner}/{repo}/commits/{sha}/statuses
        # Maps both Forgejo Actions and Woodpecker CI (ci.codeberg.org) contexts cleanly
        ...
```

   - **4.2 Azure Repos / Azure DevOps Adapter (`src/wrench/forge/adapters/azure_repos.py` — `FR-6.6`):**

```py
class AzureReposAdapter:
    provider_key = "azure_repos"
    short_code = "AZ"
    api_version = "7.1"

    # Reviewer vote integer mapping mandated by Azure DevOps REST API v7.1:
    VOTE_APPROVED = 10
    VOTE_APPROVED_WITH_SUGGESTIONS = 5
    VOTE_NO_VOTE = 0
    VOTE_WAITING_FOR_AUTHOR = -5
    VOTE_REJECTED = -10

    def _auth_headers(self, pat_token: str) -> dict[str, str]:
        # Azure DevOps PAT requires Basic base64(":<PAT>")
        b64 = base64.b64encode(f":{pat_token}".encode("utf-8")).decode("ascii")
        return {"Authorization": f"Basic {b64}", "Accept": "application/json"}

    def list_pull_requests(
        self, org: str, project: str, repo: str, status: str = "active"
    ) -> list[PullRequestItem]:
        # GET https://dev.azure.com/{org}/{project}/_apis/git/repositories/{repo}/pullrequests?searchCriteria.status={status}&$top=50&api-version=7.1
        ...

    def submit_reviewer_vote(
        self, org: str, project: str, repo: str, pr_id: int, reviewer_id: str, vote: int
    ) -> None:
        # PUT https://dev.azure.com/{org}/{project}/_apis/git/repositories/{repo}/pullRequests/{pr_id}/reviewers/{reviewer_id}?api-version=7.1
        # Body: {"vote": vote} where vote in (-10, -5, 0, 5, 10)
        ...

    def list_work_items_for_autocomplete(
        self, org: str, project: str, query_text: str
    ) -> list[IssueItem]:
        # POST https://dev.azure.com/{org}/{project}/_apis/wit/wiql?api-version=7.1
        # Batch-fetches top 50 recent Work Items (Bug, Task, User Story) into SQLite cached_issues for < 1ms #ID autocomplete
        ...
```

   - **4.3 Radicle Decentralized P2P Adapter (`src/wrench/forge/adapters/radicle.py` — `FR-6.7`):**

```py
class RadicleAdapter:
    provider_key = "radicle"
    short_code = "RAD"
    RID_PATTERN = re.compile(r"^rad://(?P<rid>z[1-9A-HJ-NP-Za-km-z]{20,60})(?:/.*)?$")

    def list_patches(self, repo_path: str, rid: str) -> list[PullRequestItem]:
        # Fast-path 1: Query local radicle-httpd (default http://127.0.0.1:8080/api/v1/projects/{rid}/patches)
        # Fast-path 2 (Offline P2P COB fallback): Run [rad_bin, "patch", "list", "--json"] with cwd=repo_path, shell=False
        # Parses signed Collaborative Object (COB) revisions, peer DID attestations, and merge state
        ...

    def push_for_review(
        self,
        repo_path: str,
        remote_name: str = "rad",
        target_branch: str = "main",
        title: str = "",
        description: str = "",
        topic: str = "",
        reviewers: list[str] = (),
        wip: bool = False,
    ) -> str:
        # SEC-1: Validate remote_name does not start with "-"
        # Pushes to Radicle's magic ref `refs/patches` using git push options so no interactive $EDITOR blocks the GUI:
        cmd = [
            "git",
            "-C",
            repo_path,
            "push",
            "-o",
            f"patch.message={title}",
            *(["-o", f"patch.message={description}"] if description else []),
            *(["-o", "patch.state=draft"] if wip else []),
            "--",
            remote_name,
            "HEAD:refs/patches",
        ]
        ...
```

   - **4.4 Gerrit Code Review Adapter (`src/wrench/forge/adapters/gerrit.py` — `FR-6.8`):**

```py
class GerritAdapter:
    provider_key = "gerrit"
    short_code = "GR"
    XSSI_PREFIX = b")]}'\n"
    CHANGE_ID_RE = re.compile(r"^Change-Id:\s*(I[0-9a-f]{40})\s*$", re.M)
    SAFE_OPT_RE = re.compile(r"^[A-Za-z0-9_.@-]+$")

    @staticmethod
    def parse_gerrit_json(raw_bytes: bytes) -> Any:
        # OPT-8 / Zero-copy slice: strip 5-byte Gerrit XSSI guard prefix without copying full buffer
        payload = (
            memoryview(raw_bytes)[5:] if raw_bytes.startswith(b")]}'") else memoryview(raw_bytes)
        )
        return json.loads(bytes(payload))

    @classmethod
    def ensure_change_id_trailer(
        cls, message: str, tree_oid: str, parent_oid: str, author: str, timestamp: int
    ) -> str:
        # CRITICAL RULE: If message already contains Change-Id: I<40-hex>, preserve it verbatim for Amend!
        if cls.CHANGE_ID_RE.search(message):
            return message
        seed = f"tree {tree_oid}\nparent {parent_oid}\nauthor {author} {timestamp}\n\n{message}".encode(
            "utf-8"
        )
        digest = hashlib.sha1(seed).hexdigest()
        return message.rstrip() + f"\n\nChange-Id: I{digest}\n"

    @classmethod
    def format_review_push_refspec(
        cls, target_branch: str, topic: str = "", reviewers: list[str] = (), wip: bool = False
    ) -> str:
        if not cls.SAFE_OPT_RE.match(target_branch):
            raise ValueError(f"Unsafe Gerrit target branch: {target_branch}")
        opts: list[str] = []
        if topic:
            if not cls.SAFE_OPT_RE.match(topic):
                raise ValueError(f"Unsafe Gerrit topic: {topic}")
            opts.append(f"topic={topic}")
        for rev in reviewers:
            if not cls.SAFE_OPT_RE.match(rev):
                raise ValueError(f"Unsafe Gerrit reviewer: {rev}")
            opts.append(f"r={rev}")
        if wip:
            opts.append("wip")
        suffix = ("%" + ",".join(opts)) if opts else ""
        return f"HEAD:refs/for/{target_branch}{suffix}"
```

   - **4.5 SourceHut (`sr.ht`) GraphQL & Mailing-List Adapter (`src/wrench/forge/adapters/sourcehut.py` — `FR-6.9`):**

```py
class SourceHutAdapter:
    provider_key = "sourcehut"
    short_code = "SRHT"

    # Single-roundtrip GraphQL query fetching repo metadata + recent build statuses in 1 HTTP call
    REPO_DASHBOARD_GQL = """
    query RepoDashboard($owner: String!, $name: String!) {
      user(username: $owner) {
        repository(name: $name) {
          id
          name
          description
          visibility
          head { name target }
        }
      }
    }
    """

    def execute_graphql(
        self, service: str, query: str, variables: dict[str, Any], token: str
    ) -> dict[str, Any]:
        # service in ("git", "todo", "lists", "builds") -> POST https://{service}.{instance_domain}/query
        # Uses Authorization: Bearer <API-2.0-PAT>
        ...
```

   - **4.6 Tangled (`tangled.org`) ATProtocol Adapter (`src/wrench/forge/adapters/tangled.py` — `FR-6.10`):**

```py
class TangledAdapter:
    provider_key = "tangled"
    short_code = "TG"
    LEXICON_PULL = "sh.tangled.repo.pull"
    LEXICON_ISSUE = "sh.tangled.repo.issue"
    LEXICON_PIPELINE = "sh.tangled.pipeline"

    def resolve_handle_and_knot(self, handle_or_did: str, repo_name: str) -> tuple[str, str]:
        # 1. Check SQLite LRU table `tangled_knot_cache(handle_or_did, repo_name)` (TTL 3600s)
        # 2. On cache miss, resolve handle -> DID via XRPC GET /xrpc/com.atproto.identity.resolveHandle
        #    and resolve the repository's hosting Knot server URL (e.g. knot1.tangled.sh or self-hosted knot)
        ...

    def list_pull_requests(self, handle_or_did: str, repo_name: str) -> list[PullRequestItem]:
        # Queries Tangled AppView / XRPC records for collection="sh.tangled.repo.pull"
        # Preserves round-based patch revisions and Jujutsu/Git Change-ID stack parent links
        ...

    def list_spindle_ci_runs(
        self, handle_or_did: str, repo_name: str, commit_sha: str
    ) -> list[CIStatusItem]:
        # Queries Spindle Nix CI pipeline status records (collection="sh.tangled.pipeline") when tangled.spindle_ci.enabled is True
        ...
```

- **Completion Gate:** `pytest tests/forge/test_extended_forges_vp26.py tests/meta/test_no_shortcuts_guard.py`

### Step 2 — Build `src/wrench/ui/dialogs/forge_review_push_dialog.py` & Wire `ChangesTab`, `PRReviewOverlay`, and `CommitGraphWidget`

1. Create `src/wrench/ui/dialogs/forge_review_push_dialog.py` (`ForgeReviewPushDialog(QDialog)`, `ui-planning.md §6.27`) adapting its form controls to the active remote's forge capability:  
   - **Gerrit mode (`GR`):** Target branch combo, `Topic` input, `Reviewers` / `CC` pill completer, `WIP` checkbox, `Change-Id` verification badge, and `CliCommandPreviewBar` (`$ git push origin HEAD:refs/for/main%topic=...`).  
   - **Radicle mode (`RAD`):** Patch Title, Patch Description, Base branch, and `CliCommandPreviewBar` (`$ git push rad -o patch.message=... HEAD:refs/patches`).  
   - **SourceHut mode (`SRHT`):** Target mailing list (`~owner/devel@lists.sr.ht`), patch version prefix (`PATCH v2`), cover letter editor, and `Send Patch Series` action.  
   - **Tangled / Codeberg / Azure Repos mode (`TG`, `CB`, `AZ`):** Target branch, stacked PR / round selector, Azure Work Item link picker, and 1-click `Push & Create/Update PR`.  
2. In `src/wrench/ui/tabs/changes_tab.py`:  
   - Add the `[Change-Id: Auto ✓]` indicator pill (visible when a Gerrit remote is active and `gerrit.auto_insert_change_id` is `True`).  
   - Add `"Push for Review (Gerrit refs/for / Radicle Patch / SourceHut List)..."` to the Push split-button.  
3. In `src/wrench/ui/widgets/pr_review_overlay.py` (`§6.18`):  
   - Render the Gerrit `Code-Review (-2..+2)` / `Verified (-1..+1)` voting bar and `Patchset PS1..PSN` selector when viewing a Gerrit change, or the Azure Repos 5-state vote selector when viewing an Azure PR.  
4. In `src/wrench/ui/commit_graph/graph_widget.py` (`§4.2.5`):  
   - Support all 11 forge short codes (`GH`, `GL`, `CB`, `FG`, `BB`, `SF`, `AZ`, `RAD`, `GR`, `SRHT`, `TG`) in collapsed mirror pills (`[🌐 main · GH · CB · RAD · TG ✓]`).  
- **Completion Gate:** `pytest tests/ui/test_forge_review_push_ui.py tests/meta/test_no_shortcuts_guard.py`

### Forbidden Decisions for Lower-Tier Models

- DO NOT push directly to `refs/heads/<branch>` on a Gerrit remote when the user clicks `"Push for Review"`; always push to `refs/for/<branch>`.  
- DO NOT generate a brand-new `Change-Id` when amending a commit that already contains a `Change-Id: I...` line in its footer; always preserve the existing `Change-Id` so Gerrit updates the existing change with a new patchset instead of creating a duplicate change.  
- DO NOT allow unvalidated characters in Gerrit `%topic=` or `%r=` push options (`SEC-1`).

### Acceptance Check

- [ ] All 6 new platforms (`Codeberg`, `Azure Repos`, `Radicle`, `Gerrit`, `SourceHut`, `Tangled`) appear in `SettingsDialog -> Forges & CI` (`Ctrl+,`), can be individually toggled off with zero background/UI overhead, resolve cleanly in the 5-stage Mirror Resolver (`VP-25`), and pass `pytest tests/forge/test_extended_forges_vp26.py tests/ui/test_forge_review_push_ui.py tests/meta/test_no_shortcuts_guard.py`.

## Master Sequential Checklist (`VP-0` – `VP-26`)

- [ ] **VP-0.1:** Create `src/wrench/storage/settings_registry.py` with `SettingSpec`, SQLite tables (`global_settings`, `repo_settings_overrides`), and `DEFAULT_SETTING_SPECS` for all v1 features.  
- [ ] **VP-0.2:** Wire all v1 modules (`inotify_watcher.py`, `forge/registry.py`, `snapshots.py`, `history_tab.py`, `changes_tab.py`) to obey `SettingsRegistry` with zero-overhead short-circuiting when disabled.  
- [ ] **VP-0.3:** Build searchable, dynamic `SettingsDialog` (`Ctrl+,`) with per-repo overrides, `Minimalist Local-Only Mode` preset, and JSON import/export.  
- [ ] **VP-1.1:** Register `VP-1` settings and implement `cherry_pick_commits`, `revert_commits`, `sequencer_action`, and `reset_branch` in `core`.  
- [ ] **VP-1.2:** Build `reset_dialog.py` visual file-impact preview and wire Cherry-Pick/Revert/Reset into `HistoryTab`.  
- [ ] **VP-2.1:** Register `VP-2` settings and implement `rebase_sequencer.py` and `rebase_editor_helper.py`.  
- [ ] **VP-2.2:** Build drag-and-drop `interactive_rebase_dialog.py` and wire into `HistoryTab`.  
- [ ] **VP-3.1:** Register `VP-3` settings and implement `worktrees.py`, path templates, cross-worktree cherry-pick, and Bare-Repo Worktree Hub mode.  
- [ ] **VP-3.2:** Build `worktree_panel.py`, full-path hover tooltips, and named workspace sessions in `wrench.db`.  
- [ ] **VP-4.1:** Register `VP-4` settings and implement `submodules.py` (`list`, `init`, `sync`, `add`).  
- [ ] **VP-4.2:** Build `submodule_panel.py` with dirty badges and double-click-to-open-tab.  
- [ ] **VP-5.1:** Register `VP-5` settings and implement `commit_helpers.py` (`commit.template` loader and contributor scanner).  
- [ ] **VP-5.2:** Build `coauthor_input.py` pill completer and template selector in `ChangesTab`.  
- [ ] **VP-6.1:** Register `VP-6` settings and implement inline PR review comments, 1-click PR branch checkout, and CI log streaming in `forge`.  
- [ ] **VP-6.2:** Build `pr_review_overlay.py` and `CILogDrawer` in `ui`.  
- [ ] **VP-7.1:** Register `VP-7` settings and implement Issue CRUD \+ SQLite cache in `forge`.  
- [ ] **VP-7.2:** Build `issues_tab.py` and `#` `issue_completer.py` in `ChangesTab`.  
- [ ] **VP-8.1:** Register `VP-8` settings and implement `account_router.py` and `GIT_SSH_COMMAND` per-repo routing.  
- [ ] **VP-8.2:** Build `account_rules_dialog.py` directory-prefix routing UI.  
- [ ] **VP-9.1:** Register `VP-9` settings and implement `sourceforge.py` adapter and `custom_forge_domains` routing.  
- [ ] **VP-9.2:** Add Custom Forge Domains & Plugin Inspector section to `SettingsDialog`.  
- [ ] **VP-10.1:** Register `VP-10` settings and implement `external_tools.py` and `diff_highlighter.py` (intra-line \+ `--color-moved`).  
- [ ] **VP-10.2:** Wire external diff/merge buttons and live diff highlighter toggles into `ChangesTab` and `HistoryTab`.  
- [ ] **VP-11.1:** Register `VP-11` settings and implement `reflog_ops.py` and pickaxe (`-S`/`-G`) commit search.  
- [ ] **VP-11.2:** Build `reflog_drawer.py` and expandable search filters in `HistoryTab`.  
- [ ] **VP-12.1:** Register `VP-12` settings and implement `lfs_ops.py` (`locks`, `lock`, `unlock`, `track`, `prune`).  
- [ ] **VP-12.2:** Build `lfs_locks_dialog.py` and LFS file lock badges in `ChangesTab`.  
- [ ] **VP-13.1:** Register `VP-13` settings and implement `tray_manager.py` (`QSystemTrayIcon` \+ close-to-tray toggle).  
- [ ] **VP-14.1:** Register `VP-14` settings and implement `SnapshotScheduler` in `snapshots.py`.  
- [ ] **VP-14.2:** Build `snapshots_dialog.py` visual snapshot browser and restore UI.  
- [ ] **VP-15.1:** Register `VP-15` settings and implement `portal_secret.py` (XDG Secret Portal \+ ephemeral memory-only mode).  
- [ ] **VP-15.2:** Create and validate Linux packaging manifests (`PKGBUILD`, `debian/`, `wrench.spec`).  
- [ ] **VP-16.1:** Register `VP-16` settings and implement `sparse_checkout.py` and partial clone (`--filter=blob:none`).  
- [ ] **VP-16.2:** Implement adaptive `inotify` fallback, `CommitGraphWidget` lazy pagination, and `sparse_checkout_dialog.py`.  
- [ ] **VP-17.1:** Register `VP-17` settings and implement `hook_env.py` (login-shell `PATH` hydration \+ `core.hooksPath` discovery).  
- [ ] **VP-17.2:** Build `hook_output_drawer.py` and `--no-verify` bypass controls in `ChangesTab`.  
- [ ] **VP-18.1:** Register `VP-18` settings and implement `signing_ops.py` (batch signature verification \+ GPG/SSH signing) and `signing_askpass.py`.  
- [ ] **VP-18.2:** Render signature verification badges in `CommitGraphWidget` and Signing key picker in `SettingsDialog`.  
- [ ] **VP-19.1:** Register `VP-19` settings and implement `bisect_ops.py` (`start`, `mark`, `reset`, `run_script`).  
- [ ] **VP-19.2:** Build `bisect_banner.py` and `[GOOD]`/`[BAD]`/`[SKIP]` graph overlays.  
- [ ] **VP-20.1:** Register `VP-20` settings and implement `stacks.py` (`--update-refs`, squash-merge `--onto` recovery, hunk-to-commit fixup routing).  
- [ ] **VP-20.2:** Build `stack_panel.py`, hunk routing context menu, and Stacked PR synchronization.  
- [ ] **VP-21.1:** Register `VP-21` settings and implement `blame_ops.py` (`.git-blame-ignore-revs` \+ `git log -L` line history).  
- [ ] **VP-21.2:** Build `blame_viewer.py` and context-menu `"View Line History"` drawer.  
- [ ] **VP-22.1:** Register `VP-22` settings and implement `stash_ops.py` (`--staged`, `--keep-index`, explicit `refs/stash@{n}`, `--skip-worktree`).  
- [ ] **VP-22.2:** Build Stash split-button and `skip_worktree_panel.py` in `ChangesTab`.  
- [ ] **VP-23.1:** Register `VP-23` settings and implement `git rerere` helpers, `format-patch`/`am`, and `custom_actions.py`.  
- [ ] **VP-23.2:** Build `command_palette.py` (`Ctrl+K`) and Custom Actions editor in `SettingsDialog`.  
- [ ] **VP-24.1:** Implement `help_topics.py` (25 offline topics) and singleton `rich_help_tooltip.py` (`§5.6`) with `150ms` hover grace timer and `UIWidgetHighlighter`.  
- [ ] **VP-24.2:** Build lazy-indexed `help_center_dialog.py` (`F1`, `§6.25`) with validated `wrench://open-setting` and `wrench://highlight-ui` action links.  
- [ ] **VP-25.1:** Register `VP-25` mirror settings and implement 5-stage `mirror_ops.py` \+ `mirror_resolver.py` (`blake2b` ref-digest cache `OPT-7`, root-OID fingerprinting, parallel `ls-remote`, and `120s` circuit breaker).  
- [ ] **VP-25.2:** Upgrade `CommitGraphWidget` (`§4.2.5`) with combined multi-mirror DAG walk, collapsed `[🌐 branch · GH · GL ✓]` pills, amber drift badges, and cross-forge CI aggregation.  
- [ ] **VP-25.3:** Build `mirror_manager_dialog.py` (`§6.26`) Mirror Sync Matrix and parallel `push_to_all_mirrors_parallel` orchestrator.  
- [ ] **VP-26.1:** Register `VP-26` settings (`forge.codeberg.enabled`, `forge.azure_repos.enabled`, `forge.radicle.enabled`, `forge.gerrit.enabled`, `forge.sourcehut.enabled`, `forge.tangled.enabled`, and sub-keys) and extend `security_sanitizer.py` (`rad://` RID & Gerrit push-option validation).  
- [ ] **VP-26.2:** Implement `codeberg.py`, `azure_repos.py` (REST v7.1 \+ 5-state votes \+ Work Items), `radicle.py` (`rad://`, `refs/patches`, signed COBs), `gerrit.py` (`/a/changes/` zero-copy XSSI slice, `refs/for/`, `Change-Id` hook, `-2..+2` label voting), `sourcehut.py` (`sr.ht` batched GraphQL \+ `lists.sr.ht` patches), and `tangled.py` (`atproto` Knots \+ Spindle Nix CI).  
- [ ] **VP-26.3:** Register all 11 forge short codes (`GH`, `GL`, `CB`, `FG`, `BB`, `SF`, `AZ`, `RAD`, `GR`, `SRHT`, `TG`) in `mirror_resolver.py` (`VP-25`) and `CommitGraphWidget` (`§4.2.5`).  
- [ ] **VP-26.4:** Build `forge_review_push_dialog.py` (`§6.27`), Gerrit `Change-Id` pill in `ChangesTab`, Radicle node status pill, and Gerrit/Azure voting controls in `PRReviewOverlayWidget` (`§6.18`).