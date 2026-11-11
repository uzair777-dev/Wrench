"""Universal settings registry with SQLite persistence, live Qt signals, and undo stack.

Implements VP-0: Total User Configurability.
Provides typed access, per-repository overrides, O(1) cached reads, and delta undo/redo.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, Signal

from wrench.storage.db import _db_lock, get_connection

logger = logging.getLogger(__name__)


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
    parent_toggle_key: str | None = None


@dataclass(frozen=True)
class SettingDelta:
    change_id: int
    timestamp: str
    repo_path: str | None
    key: str
    old_value: Any
    new_value: Any
    undone: bool = False


# Canonical 13-category setting specs covering all v1 & v2 modules
DEFAULT_SETTING_SPECS: dict[str, SettingSpec] = {
    # 1. General & UI
    "ui.theme_mode": SettingSpec(
        key="ui.theme_mode",
        category="General & UI",
        label="Color Theme",
        description="Application color palette (system default, dark, or light).",
        setting_type=SettingType.CHOICE,
        default="system",
        choices=("system", "dark", "light"),
        scope=SettingScope.GLOBAL_ONLY,
    ),
    "ui.font_size_pt": SettingSpec(
        key="ui.font_size_pt",
        category="General & UI",
        label="Interface Font Size",
        description="Base UI typography size in points.",
        setting_type=SettingType.INT,
        default=10,
        min_value=8,
        max_value=18,
        scope=SettingScope.GLOBAL_ONLY,
    ),
    "ui.confirm_destructive_actions": SettingSpec(
        key="ui.confirm_destructive_actions",
        category="General & UI",
        label="Confirm Destructive Actions",
        description=(
            "Prompt for confirmation before discarding "
            "changes, hard resets, or deleting branches."
        ),
        setting_type=SettingType.BOOL,
        default=True,
    ),
    "ui.avatars_gravatar": SettingSpec(
        key="ui.avatars_gravatar",
        category="General & UI",
        label="Gravatar Avatar Integration",
        description="Fetch author avatars from Gravatar service when local avatar is missing.",
        setting_type=SettingType.BOOL,
        default=False,
    ),
    "ui.session_state": SettingSpec(
        key="ui.session_state",
        category="General & UI",
        label="Restore Session State",
        description=(
            "Reopen previously active repositories, panels, " "and selected branches upon startup."
        ),
        setting_type=SettingType.BOOL,
        default=True,
        scope=SettingScope.GLOBAL_ONLY,
    ),
    "ui.humor_lines": SettingSpec(
        key="ui.humor_lines",
        category="General & UI",
        label="Lighthearted Status Messages",
        description="Display witty status lines in the bottom activity bar during idle periods.",
        setting_type=SettingType.BOOL,
        default=True,
        scope=SettingScope.GLOBAL_ONLY,
    ),
    "ui.activity_dock.max_lines": SettingSpec(
        key="ui.activity_dock.max_lines",
        category="General & UI",
        label="Activity Log History Depth",
        description="Maximum lines preserved in the bottom activity log drawer before truncation.",
        setting_type=SettingType.INT,
        default=500,
        min_value=50,
        max_value=5000,
        scope=SettingScope.GLOBAL_ONLY,
    ),
    "ui.show_cli_preview_in_dialogs": SettingSpec(
        key="ui.show_cli_preview_in_dialogs",
        category="General & UI",
        label="CLI Command Preview Footer",
        description=(
            "Render the exact equivalent Git CLI " "invocation at the bottom of action dialogs."
        ),
        setting_type=SettingType.BOOL,
        default=True,
    ),
    "workspace.restore_session_on_startup": SettingSpec(
        key="workspace.restore_session_on_startup",
        category="General & UI",
        label="Restore Open Repositories on Startup",
        description=(
            "Automatically reopen all workspace repository tabs " "active when the app last closed."
        ),
        setting_type=SettingType.BOOL,
        default=True,
        scope=SettingScope.GLOBAL_ONLY,
    ),
    "repo.recent_max_count": SettingSpec(
        key="repo.recent_max_count",
        category="General & UI",
        label="Recent Repositories Limit",
        description="Maximum number of repositories remembered in the File > Open Recent menu.",
        setting_type=SettingType.INT,
        default=20,
        min_value=5,
        max_value=100,
        scope=SettingScope.GLOBAL_ONLY,
    ),
    "repo.auto_discovery.enabled": SettingSpec(
        key="repo.auto_discovery.enabled",
        category="General & UI",
        label="Background Repository Discovery",
        description=(
            "Scan common development directories for " "newly initialized or cloned repositories."
        ),
        setting_type=SettingType.BOOL,
        default=True,
        scope=SettingScope.GLOBAL_ONLY,
    ),
    "help.tooltip_mode": SettingSpec(
        key="help.tooltip_mode",
        category="General & UI",
        label="Tooltip Detail Level",
        description=(
            "Style and verbosity of contextual hover " "cards across Git operations and settings."
        ),
        setting_type=SettingType.CHOICE,
        default="beginner_rich",
        choices=("beginner_rich", "compact_shortcut_only", "off"),
        scope=SettingScope.GLOBAL_ONLY,
    ),
    "help.tooltip_delay_ms": SettingSpec(
        key="help.tooltip_delay_ms",
        category="General & UI",
        label="Tooltip Hover Delay",
        description="Milliseconds pointer must hover before contextual explanation appears.",
        setting_type=SettingType.INT,
        default=500,
        min_value=100,
        max_value=2000,
        parent_toggle_key="help.tooltip_mode",
        scope=SettingScope.GLOBAL_ONLY,
    ),
    # 2. Staging & Commits
    "staging.line_staging.enabled": SettingSpec(
        key="staging.line_staging.enabled",
        category="Staging & Commits",
        label="Interactive Hunk & Line Staging",
        description=(
            "Allow staging or discarding individual diff " "lines and hunks in the Changes view."
        ),
        setting_type=SettingType.BOOL,
        default=True,
    ),
    "commit.subject_max_length_guide": SettingSpec(
        key="commit.subject_max_length_guide",
        category="Staging & Commits",
        label="Subject Line Length Guide",
        description="Soft character limit guide displayed in commit editor summary field.",
        setting_type=SettingType.INT,
        default=50,
        min_value=0,
        max_value=120,
    ),
    "commit.body_wrap_column": SettingSpec(
        key="commit.body_wrap_column",
        category="Staging & Commits",
        label="Body Wrap Column Guide",
        description="Column guide marker for wrapping commit description body text.",
        setting_type=SettingType.INT,
        default=72,
        min_value=0,
        max_value=160,
    ),
    "commit.auto_stage_all_if_empty": SettingSpec(
        key="commit.auto_stage_all_if_empty",
        category="Staging & Commits",
        label="Auto-stage All If Staging Empty",
        description=(
            "Automatically stage all tracked modified files " "when committing with an empty stage."
        ),
        setting_type=SettingType.BOOL,
        default=False,
    ),
    "commit.undo_button.enabled": SettingSpec(
        key="commit.undo_button.enabled",
        category="Staging & Commits",
        label="Show Undo Last Commit Button",
        description=(
            "Render an instant 1-click Undo button in the "
            "Changes view right after a commit is created."
        ),
        setting_type=SettingType.BOOL,
        default=True,
    ),
    # 3. Commit Graph
    "graph.show_lanes": SettingSpec(
        key="graph.show_lanes",
        category="Commit Graph",
        label="Render Branch Lanes",
        description="Draw topological branch lane curves connecting commits in the history table.",
        setting_type=SettingType.BOOL,
        default=True,
    ),
    "graph.lane_width_px": SettingSpec(
        key="graph.lane_width_px",
        category="Commit Graph",
        label="Branch Lane Column Width",
        description="Pixel width per parallel branch lane in the DAG visualization.",
        setting_type=SettingType.INT,
        default=16,
        min_value=10,
        max_value=32,
    ),
    "graph.row_height_px": SettingSpec(
        key="graph.row_height_px",
        category="Commit Graph",
        label="Graph Row Height",
        description="Pixel height per commit row in the history list.",
        setting_type=SettingType.INT,
        default=28,
        min_value=20,
        max_value=48,
    ),
    "graph.date_format": SettingSpec(
        key="graph.date_format",
        category="Commit Graph",
        label="Commit Date Display Format",
        description="How commit timestamps are formatted in history tables.",
        setting_type=SettingType.CHOICE,
        default="relative",
        choices=("relative", "iso", "locale"),
    ),
    "graph.show_avatars": SettingSpec(
        key="graph.show_avatars",
        category="Commit Graph",
        label="Render Author Avatars",
        description="Display circular author avatar images in commit history rows.",
        setting_type=SettingType.BOOL,
        default=True,
    ),
    "graph.sort_order": SettingSpec(
        key="graph.sort_order",
        category="Commit Graph",
        label="Commit Sort Order",
        description=(
            "Ordering rule for commits in the " "graph (topological DAG order vs chronological)."
        ),
        setting_type=SettingType.CHOICE,
        default="topo",
        choices=("topo", "date"),
    ),
    "graph.cherry_pick_revert.enabled": SettingSpec(
        key="graph.cherry_pick_revert.enabled",
        category="Commit Graph",
        label="Enable Cherry-Pick & Revert Context Actions",
        description="Provide Cherry-Pick and Revert actions in commit context menus.",
        setting_type=SettingType.BOOL,
        default=True,
    ),
    "graph.cherry_pick_revert.default_no_commit": SettingSpec(
        key="graph.cherry_pick_revert.default_no_commit",
        category="Commit Graph",
        label="Stage Cherry-Pick/Revert Without Committing",
        description=(
            "Pass --no-commit by default so changes " "are staged for review before committing."
        ),
        setting_type=SettingType.BOOL,
        default=False,
        parent_toggle_key="graph.cherry_pick_revert.enabled",
    ),
    "graph.cherry_pick_revert.record_origin_x": SettingSpec(
        key="graph.cherry_pick_revert.record_origin_x",
        category="Commit Graph",
        label="Append -x Origin Line to Cherry-Picks",
        description=(
            "Append '(cherry picked from commit " "...)' line to cherry-picked commit messages."
        ),
        setting_type=SettingType.BOOL,
        default=True,
        parent_toggle_key="graph.cherry_pick_revert.enabled",
    ),
    # 4. Diff & Merge
    "diff.context_lines": SettingSpec(
        key="diff.context_lines",
        category="Diff & Merge",
        label="Diff Context Lines",
        description="Number of unchanged surrounding context lines rendered around diff hunks.",
        setting_type=SettingType.INT,
        default=3,
        min_value=1,
        max_value=20,
    ),
    "diff.ignore_whitespace_mode": SettingSpec(
        key="diff.ignore_whitespace_mode",
        category="Diff & Merge",
        label="Whitespace Comparison Mode",
        description="Filter rule for whitespace modifications in diff calculations.",
        setting_type=SettingType.CHOICE,
        default="none",
        choices=("none", "trailing", "all"),
    ),
    "merge.default_strategy": SettingSpec(
        key="merge.default_strategy",
        category="Diff & Merge",
        label="Default Merge Strategy",
        description="Fast-forward strategy applied when merging branches.",
        setting_type=SettingType.CHOICE,
        default="merge",
        choices=("merge", "ff-only", "no-ff"),
    ),
    "merge.builtin_3way_tool.enabled": SettingSpec(
        key="merge.builtin_3way_tool.enabled",
        category="Diff & Merge",
        label="Built-in 3-Way Conflict Resolver",
        description="Launch Wrench's visual 3-way conflict resolver for conflicted files.",
        setting_type=SettingType.BOOL,
        default=True,
    ),
    # 5. Branches & Stacks
    "reset.show_visual_preview_dialog": SettingSpec(
        key="reset.show_visual_preview_dialog",
        category="Branches & Stacks",
        label="Show Visual Reset Impact Preview",
        description=(
            "Present a visual explanation card before "
            "executing soft, mixed, or hard branch resets."
        ),
        setting_type=SettingType.BOOL,
        default=True,
    ),
    "rebase.interactive_ui.enabled": SettingSpec(
        key="rebase.interactive_ui.enabled",
        category="Branches & Stacks",
        label="Enable Visual Interactive Rebase UI",
        description="Provide graphical drag-and-drop reordering, squashing, and rewording dialog.",
        setting_type=SettingType.BOOL,
        default=True,
    ),
    "rebase.autostash": SettingSpec(
        key="rebase.autostash",
        category="Branches & Stacks",
        label="Auto-stash During Rebase (--autostash)",
        description=(
            "Automatically stash and pop dirty " "working directory modifications across rebases."
        ),
        setting_type=SettingType.BOOL,
        default=True,
        parent_toggle_key="rebase.interactive_ui.enabled",
    ),
    "rebase.autosquash": SettingSpec(
        key="rebase.autosquash",
        category="Branches & Stacks",
        label="Auto-squash Fixup Commits (--autosquash)",
        description="Automatically sort and merge fixup! and squash! commits into target commits.",
        setting_type=SettingType.BOOL,
        default=True,
        parent_toggle_key="rebase.interactive_ui.enabled",
    ),
    "rebase.conflict_prediction_enabled": SettingSpec(
        key="rebase.conflict_prediction_enabled",
        category="Branches & Stacks",
        label="Predict Rebase Conflicts in Advance",
        description=(
            "Dry-run rebase commits against upstream tree " "to warn of merge conflicts beforehand."
        ),
        setting_type=SettingType.BOOL,
        default=True,
        parent_toggle_key="rebase.interactive_ui.enabled",
    ),
    "stacks.enabled": SettingSpec(
        key="stacks.enabled",
        category="Branches & Stacks",
        label="Stacked Branches Workflow",
        description=(
            "Manage dependent stacked feature branches "
            "with automated cascade restacking (--update-refs)."
        ),
        setting_type=SettingType.BOOL,
        default=True,
    ),
    # 6. Worktrees & Submodules
    "worktrees.enabled": SettingSpec(
        key="worktrees.enabled",
        category="Worktrees & Submodules",
        label="Git Worktrees Manager",
        description=(
            "Inspect, add, and switch linked "
            "working trees for parallel multi-branch development."
        ),
        setting_type=SettingType.BOOL,
        default=True,
    ),
    "worktrees.bare_hub.enabled": SettingSpec(
        key="worktrees.bare_hub.enabled",
        category="Worktrees & Submodules",
        label="Bare Repository Hub Mode",
        description=(
            "Render a centralized worktree management " "grid when opening bare Git repositories."
        ),
        setting_type=SettingType.BOOL,
        default=True,
        parent_toggle_key="worktrees.enabled",
    ),
    "submodules.enabled": SettingSpec(
        key="submodules.enabled",
        category="Worktrees & Submodules",
        label="Git Submodules Manager",
        description="Display submodules panel with recursive sync, init, and dirty status badges.",
        setting_type=SettingType.BOOL,
        default=True,
    ),
    "submodules.auto_init": SettingSpec(
        key="submodules.auto_init",
        category="Worktrees & Submodules",
        label="Auto-initialize Submodules",
        description=(
            "Run git submodule update --init " "--recursive automatically after clone or fetch."
        ),
        setting_type=SettingType.BOOL,
        default=True,
        parent_toggle_key="submodules.enabled",
    ),
    "monorepo.sparse_checkout_ui.enabled": SettingSpec(
        key="monorepo.sparse_checkout_ui.enabled",
        category="Worktrees & Submodules",
        label="Sparse-Checkout Directory Manager UI",
        description=(
            "Enable the monorepo sparse-checkout directory picker dialog "
            "and Clone dialog partial/sparse options."
        ),
        setting_type=SettingType.BOOL,
        default=True,
    ),
    # 7. Remotes & LFS
    "remote.auto_fetch.enabled": SettingSpec(
        key="remote.auto_fetch.enabled",
        category="Remotes & LFS",
        label="Background Remote Auto-Fetch",
        description="Periodically check configured remotes in the background for incoming commits.",
        setting_type=SettingType.BOOL,
        default=True,
    ),
    "remote.auto_fetch.interval_seconds": SettingSpec(
        key="remote.auto_fetch.interval_seconds",
        category="Remotes & LFS",
        label="Auto-Fetch Interval (seconds)",
        description="Seconds between automatic background fetch operations.",
        setting_type=SettingType.INT,
        default=180,
        min_value=30,
        max_value=3600,
        parent_toggle_key="remote.auto_fetch.enabled",
    ),
    "remote.pull_default_mode": SettingSpec(
        key="remote.pull_default_mode",
        category="Remotes & LFS",
        label="Default Pull Mode",
        description=(
            "Strategy used when pulling upstream " "branches (fast-forward only, rebase, or merge)."
        ),
        setting_type=SettingType.CHOICE,
        default="ff-only",
        choices=("ff-only", "rebase", "merge"),
    ),
    "remote.force_push_mode": SettingSpec(
        key="remote.force_push_mode",
        category="Remotes & LFS",
        label="Force Push Restriction Mode",
        description=(
            "Allow or restrict force pushes " "to prevent accidental remote history clobbering."
        ),
        setting_type=SettingType.CHOICE,
        default="force-with-lease",
        choices=("disabled", "force-with-lease", "force"),
    ),
    "remote.prune_on_fetch": SettingSpec(
        key="remote.prune_on_fetch",
        category="Remotes & LFS",
        label="Prune Stale Remote Branches on Fetch",
        description=(
            "Remove local remote-tracking references that no "
            "longer exist on the remote repository."
        ),
        setting_type=SettingType.BOOL,
        default=True,
    ),
    "lfs.enabled": SettingSpec(
        key="lfs.enabled",
        category="Remotes & LFS",
        label="Git LFS Support",
        description="Detect LFS tracked files, inspect locks, and manage LFS object downloads.",
        setting_type=SettingType.BOOL,
        default=True,
    ),
    "clone.default_filter_mode": SettingSpec(
        key="clone.default_filter_mode",
        category="Remotes & LFS",
        label="Default Partial-Clone Object Filter",
        description=(
            "Pre-selected Git partial-clone --filter preset in the Clone Repository dialog "
            "(none for full clone, blob:none for treeless blobs, tree:0 for minimal trees)."
        ),
        setting_type=SettingType.CHOICE,
        default="none",
        choices=("none", "blob:none", "tree:0"),
        scope=SettingScope.GLOBAL_ONLY,
    ),
    # 8. Forges & CI
    "forge.enabled": SettingSpec(
        key="forge.enabled",
        category="Forges & CI",
        label="Forge Integrations Master Toggle",
        description=(
            "Enable online forge capabilities (pull " "requests, issues, review overlays, CI logs)."
        ),
        setting_type=SettingType.BOOL,
        default=True,
    ),
    "forge.github.enabled": SettingSpec(
        key="forge.github.enabled",
        category="Forges & CI",
        label="GitHub Integration",
        description="Connect to GitHub.com and GitHub Enterprise instances.",
        setting_type=SettingType.BOOL,
        default=True,
        parent_toggle_key="forge.enabled",
    ),
    "forge.gitlab.enabled": SettingSpec(
        key="forge.gitlab.enabled",
        category="Forges & CI",
        label="GitLab Integration",
        description="Connect to GitLab.com and self-hosted GitLab servers.",
        setting_type=SettingType.BOOL,
        default=True,
        parent_toggle_key="forge.enabled",
    ),
    "forge.forgejo.enabled": SettingSpec(
        key="forge.forgejo.enabled",
        category="Forges & CI",
        label="Forgejo / Gitea Integration",
        description="Connect to Forgejo and Gitea lightweight self-hosted forges.",
        setting_type=SettingType.BOOL,
        default=True,
        parent_toggle_key="forge.enabled",
    ),
    "forge.bitbucket.enabled": SettingSpec(
        key="forge.bitbucket.enabled",
        category="Forges & CI",
        label="Bitbucket Integration",
        description="Connect to Bitbucket Cloud and Data Center workspaces.",
        setting_type=SettingType.BOOL,
        default=True,
        parent_toggle_key="forge.enabled",
    ),
    "forge.ci_badges.enabled": SettingSpec(
        key="forge.ci_badges.enabled",
        category="Forges & CI",
        label="Render CI Status Badges",
        description="Display pass/fail/pending CI build status icons directly on commit rows.",
        setting_type=SettingType.BOOL,
        default=True,
        parent_toggle_key="forge.enabled",
    ),
    "forge.poll_interval_seconds": SettingSpec(
        key="forge.poll_interval_seconds",
        category="Forges & CI",
        label="Forge Status Poll Interval (seconds)",
        description="Interval between background queries for PR and CI status updates.",
        setting_type=SettingType.INT,
        default=120,
        min_value=30,
        max_value=3600,
        parent_toggle_key="forge.enabled",
    ),
    "forge.allow_third_party_entrypoint_plugins": SettingSpec(
        key="forge.allow_third_party_entrypoint_plugins",
        category="Forges & CI",
        label="Allow Third-Party Forge Plugins",
        description="Discover and load community forge adapter plugins via entry_points.",
        setting_type=SettingType.BOOL,
        default=True,
        parent_toggle_key="forge.enabled",
    ),
    # 9. Hooks & Signing
    "hooks.enabled": SettingSpec(
        key="hooks.enabled",
        category="Hooks & Signing",
        label="Execute Git Client Hooks",
        description="Run pre-commit, commit-msg, and pre-push hooks located in .git/hooks.",
        setting_type=SettingType.BOOL,
        default=True,
    ),
    "signing.enabled": SettingSpec(
        key="signing.enabled",
        category="Hooks & Signing",
        label="Cryptographic Commit & Tag Signing",
        description="Sign all newly created commits and tags using GPG or SSH keys.",
        setting_type=SettingType.BOOL,
        default=False,
    ),
    "signing.verify_badges_in_graph.enabled": SettingSpec(
        key="signing.verify_badges_in_graph.enabled",
        category="Hooks & Signing",
        label="Verify Signatures in Graph",
        description="Validate and display [✓ Verified] cryptographic signature badges on commits.",
        setting_type=SettingType.BOOL,
        default=True,
    ),
    # 10. Blame & Search
    "blame.enabled": SettingSpec(
        key="blame.enabled",
        category="Blame & Search",
        label="Interactive File Blame Gutter",
        description=(
            "Render syntax-highlighted blame gutters with " "commit provenance and age heatmaps."
        ),
        setting_type=SettingType.BOOL,
        default=True,
    ),
    "search.pickaxe.enabled": SettingSpec(
        key="search.pickaxe.enabled",
        category="Blame & Search",
        label="Pickaxe (-S/-G) Code History Search",
        description=(
            "Search repository commit history for additions " "or removals of specific code tokens."
        ),
        setting_type=SettingType.BOOL,
        default=True,
    ),
    # 11. Watcher & Performance
    "watcher.inotify.enabled": SettingSpec(
        key="watcher.inotify.enabled",
        category="Watcher & Performance",
        label="Filesystem Watcher (inotify)",
        description=(
            "Monitor working tree changes in real "
            "time and refresh the Changes view automatically."
        ),
        setting_type=SettingType.BOOL,
        default=True,
    ),
    "watcher.debounce_ms": SettingSpec(
        key="watcher.debounce_ms",
        category="Watcher & Performance",
        label="File Watcher Debounce (ms)",
        description="Milliseconds to coalesce rapid filesystem events before triggering UI reload.",
        setting_type=SettingType.INT,
        default=300,
        min_value=50,
        max_value=5000,
        parent_toggle_key="watcher.inotify.enabled",
    ),
    "watcher.refresh_on_window_focus": SettingSpec(
        key="watcher.refresh_on_window_focus",
        category="Watcher & Performance",
        label="Refresh on Window Focus",
        description="Trigger repository status check whenever Wrench window regains desktop focus.",
        setting_type=SettingType.BOOL,
        default=True,
    ),
    "watcher.lock_recovery_prompt.enabled": SettingSpec(
        key="watcher.lock_recovery_prompt.enabled",
        category="Watcher & Performance",
        label="Stale Lock Recovery Prompt",
        description=(
            "Offer to safely clear lingering " "index.lock files after an interrupted operation."
        ),
        setting_type=SettingType.BOOL,
        default=True,
    ),
    "performance.worker_thread_count": SettingSpec(
        key="performance.worker_thread_count",
        category="Watcher & Performance",
        label="Background Worker Threads",
        description=(
            "Number of concurrent worker threads allocated "
            "for diff, walk, and network operations."
        ),
        setting_type=SettingType.INT,
        default=4,
        min_value=1,
        max_value=16,
        scope=SettingScope.GLOBAL_ONLY,
    ),
    "performance.max_diff_file_size_kb": SettingSpec(
        key="performance.max_diff_file_size_kb",
        category="Watcher & Performance",
        label="Maximum Diff File Size (KB)",
        description=(
            "Files larger than this threshold show a "
            "collapsed warning rather than full syntax diff."
        ),
        setting_type=SettingType.INT,
        default=2048,
        min_value=128,
        max_value=32768,
    ),
    "watcher.monorepo_adaptive_fallback.enabled": SettingSpec(
        key="watcher.monorepo_adaptive_fallback.enabled",
        category="Watcher & Performance",
        label="Monorepo Adaptive Watcher Fallback",
        description=(
            "Automatically fall back to watching only .git metadata (HEAD, index, refs) "
            "when full working-tree inotify reaches OS watch limits."
        ),
        setting_type=SettingType.BOOL,
        default=True,
        parent_toggle_key="watcher.inotify.enabled",
    ),
    "performance.graph_page_size": SettingSpec(
        key="performance.graph_page_size",
        category="Watcher & Performance",
        label="Commit Graph Scroll Page Size",
        description=(
            "Number of commits fetched per incremental page when scrolling through "
            "large commit histories."
        ),
        setting_type=SettingType.INT,
        default=500,
        min_value=100,
        max_value=5000,
    ),
    "maintenance.auto_commit_graph.enabled": SettingSpec(
        key="maintenance.auto_commit_graph.enabled",
        category="Watcher & Performance",
        label="Background Commit-Graph Maintenance",
        description=(
            "Maintain .git/objects/info/commit-graph with changed-path bloom filters "
            "in the background when opening large repositories."
        ),
        setting_type=SettingType.BOOL,
        default=True,
    ),
    # 12. Safety & Backups
    "safety.commit_partially_staged_mode": SettingSpec(
        key="safety.commit_partially_staged_mode",
        category="Safety & Backups",
        label="Partially Staged Commit Behavior",
        description=(
            "Behavior when committing checked files that have both staged "
            "hunks and unstaged working-tree modifications."
        ),
        setting_type=SettingType.CHOICE,
        default="prompt",
        choices=("prompt", "stage_all", "staged_only"),
        scope=SettingScope.REPO_OVERRIDABLE,
    ),
    "safety.auto_stage_hook_modifications": SettingSpec(
        key="safety.auto_stage_hook_modifications",
        category="Safety & Backups",
        label="Auto-Stage Hook Formatter Output",
        description=(
            "Automatically offer 1-click re-staging and commit retry when "
            "formatters modify files and abort commit."
        ),
        setting_type=SettingType.BOOL,
        default=True,
    ),
    "safety.precommit_tool_search_paths": SettingSpec(
        key="safety.precommit_tool_search_paths",
        category="Safety & Backups",
        label="Virtualenv Tool Discovery",
        description=(
            "Search local project virtual environments (.venv, venv, node_modules) "
            "for linters and formatters before system PATH."
        ),
        setting_type=SettingType.BOOL,
        default=True,
    ),
    "safety.pre_op_snapshot.enabled": SettingSpec(
        key="safety.pre_op_snapshot.enabled",
        category="Safety & Backups",
        label="Pre-Operation Safety Snapshots",
        description=(
            "Create automatic rolling Git stashes before "
            "hard resets, rebases, or destructive actions."
        ),
        setting_type=SettingType.BOOL,
        default=True,
    ),
    "safety.scheduled_backups.enabled": SettingSpec(
        key="safety.scheduled_backups.enabled",
        category="Safety & Backups",
        label="Periodic Background Safety Backups",
        description="Capture periodic working directory snapshots on a background timer.",
        setting_type=SettingType.BOOL,
        default=False,
    ),
    "safety.op_log_undo_enabled": SettingSpec(
        key="safety.op_log_undo_enabled",
        category="Safety & Backups",
        label="Operation Log & Rollback Engine",
        description=(
            "Record Git operations in a local "
            "journal allowing 1-click rollback of recent commands."
        ),
        setting_type=SettingType.BOOL,
        default=True,
    ),
    "stash.ui.enabled": SettingSpec(
        key="stash.ui.enabled",
        category="Safety & Backups",
        label="Stash Management Surface",
        description="Provide dedicated Stashes drawer and stash/pop/apply toolbar actions.",
        setting_type=SettingType.BOOL,
        default=True,
    ),
    "stash.confirm_before_drop": SettingSpec(
        key="stash.confirm_before_drop",
        category="Safety & Backups",
        label="Confirm Stash Drop",
        description=(
            "Prompt for confirmation before permanently " "dropping or clearing saved stashes."
        ),
        setting_type=SettingType.BOOL,
        default=True,
    ),
    "desktop.system_tray.enabled": SettingSpec(
        key="desktop.system_tray.enabled",
        category="Safety & Backups",
        label="System Tray Indicator",
        description=(
            "Show Wrench status icon in the "
            "system notification tray with quick repository switcher."
        ),
        setting_type=SettingType.BOOL,
        default=True,
        scope=SettingScope.GLOBAL_ONLY,
    ),
    # 13. Custom Actions & Shortcuts
    "shortcuts.vim_mode_enabled": SettingSpec(
        key="shortcuts.vim_mode_enabled",
        category="Custom Actions & Shortcuts",
        label="Vim-Style Navigation Keys",
        description="Use h/j/k/l keys for navigating commit lists and diff panels.",
        setting_type=SettingType.BOOL,
        default=False,
        scope=SettingScope.GLOBAL_ONLY,
    ),
    "custom_actions.enabled": SettingSpec(
        key="custom_actions.enabled",
        category="Custom Actions & Shortcuts",
        label="User Custom Script Actions",
        description=(
            "Enable custom shell commands and script "
            "actions configurable in Command Palette (Ctrl+K)."
        ),
        setting_type=SettingType.BOOL,
        default=True,
    ),
}

CATEGORIES_ORDER = (
    "General & UI",
    "Staging & Commits",
    "Commit Graph",
    "Diff & Merge",
    "Branches & Stacks",
    "Worktrees & Submodules",
    "Remotes & LFS",
    "Forges & CI",
    "Hooks & Signing",
    "Blame & Search",
    "Watcher & Performance",
    "Safety & Backups",
    "Custom Actions & Shortcuts",
)


class SettingsRegistry(QObject):
    """Central registry and reactive store for all Wrench preferences."""

    setting_changed = Signal(str, object, object)  # (key, new_value, repo_path_or_none)

    def __init__(self, conn: sqlite3.Connection | None = None) -> None:
        super().__init__()
        self._conn = conn
        self._lock = threading.Lock()
        self._specs: dict[str, SettingSpec] = dict(DEFAULT_SETTING_SPECS)
        # Cache keyed by (repo_path_or_none, key) -> effective value
        self._effective_cache: dict[tuple[str | None, str], Any] = {}
        self._init_storage()

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is not None:
            return self._conn
        return get_connection()

    def _init_storage(self) -> None:
        """Create tables if missing and run initial migration from legacy v1 tables."""
        conn = self._get_conn()
        with _db_lock, self._lock:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS global_settings (
                    key             TEXT PRIMARY KEY,
                    value_json      TEXT NOT NULL,
                    updated_at      TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS repo_settings_overrides (
                    repo_path       TEXT NOT NULL,
                    key             TEXT NOT NULL,
                    value_json      TEXT NOT NULL,
                    updated_at      TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (repo_path, key)
                )
                """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS settings_undo_log (
                    change_id       INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp       TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    repo_path       TEXT,
                    key             TEXT NOT NULL,
                    old_value_json  TEXT NOT NULL,
                    new_value_json  TEXT NOT NULL,
                    undone          INTEGER NOT NULL DEFAULT 0
                )
                """)
            self._migrate_legacy_settings(conn)
            self._warm_cache(conn)

    def _migrate_legacy_settings(self, conn: sqlite3.Connection) -> None:
        """One-time migration copying legacy app_settings rows into global_settings."""
        try:
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='app_settings'"
            )
            if not cursor.fetchone():
                return

            rows = conn.execute("SELECT key, value FROM app_settings").fetchall()
            for row in rows:
                k = row[0] if isinstance(row, tuple) else row["key"]
                v = row[1] if isinstance(row, tuple) else row["value"]

                # Translate common legacy keys
                target_key = k
                if k == "theme":
                    target_key = "ui.theme_mode"
                elif k == "repo.auto_fetch_on_open":
                    target_key = "remote.auto_fetch.enabled"
                elif k == "ui.tab_orientation":
                    target_key = "ui.tab_orientation"  # Preserved for tabs page

                spec = self._specs.get(target_key)
                parsed_val: Any = v
                if spec:
                    if spec.setting_type == SettingType.BOOL:
                        parsed_val = str(v).lower() in ("true", "1", "yes")
                    elif spec.setting_type == SettingType.INT:
                        try:
                            parsed_val = int(v)
                        except ValueError, TypeError:
                            parsed_val = spec.default
                else:
                    # Generic string/json parse attempt
                    if str(v).lower() in ("true", "false"):
                        parsed_val = str(v).lower() == "true"
                    else:
                        try:
                            parsed_val = json.loads(v)
                        except json.JSONDecodeError, TypeError:
                            parsed_val = v

                conn.execute(
                    "INSERT OR IGNORE INTO global_settings (key, value_json) VALUES (?, ?)",
                    (target_key, json.dumps(parsed_val)),
                )
            conn.commit()
        except sqlite3.Error as err:
            logger.debug("Legacy settings migration skipped or already completed: %s", err)

    def _warm_cache(self, conn: sqlite3.Connection) -> None:
        """Pre-populate in-memory cache for all global settings."""
        try:
            rows = conn.execute("SELECT key, value_json FROM global_settings").fetchall()
            for row in rows:
                k = row[0] if isinstance(row, tuple) else row["key"]
                raw_json = row[1] if isinstance(row, tuple) else row["value_json"]
                try:
                    self._effective_cache[(None, k)] = json.loads(raw_json)
                except json.JSONDecodeError:
                    self._effective_cache[(None, k)] = raw_json
        except sqlite3.Error as err:
            logger.debug("Failed warming settings cache: %s", err)

    def register(self, spec: SettingSpec) -> None:
        """Register a new SettingSpec in the registry."""
        with self._lock:
            self._specs[spec.key] = spec

    def get_spec(self, key: str) -> SettingSpec | None:
        """Return the spec for key, or None if unregistered."""
        return self._specs.get(key)

    def list_specs(self, category: str | None = None) -> list[SettingSpec]:
        """Return registered SettingSpecs, optionally filtered by category."""
        with self._lock:
            specs = list(self._specs.values())
        if category:
            return [s for s in specs if s.category == category]
        return specs

    def list_categories(self) -> list[str]:
        """Return ordered list of distinct categories."""
        found: set[str] = set()
        result: list[str] = []
        # First include canonical categories in defined order
        for cat in CATEGORIES_ORDER:
            if cat in found:
                continue
            with self._lock:
                has_spec = any(s.category == cat for s in self._specs.values())
            if has_spec:
                result.append(cat)
                found.add(cat)
        # Then append any custom categories
        with self._lock:
            for spec in self._specs.values():
                if spec.category not in found:
                    result.append(spec.category)
                    found.add(spec.category)
        return result

    def get(self, key: str, repo_path: str | None = None) -> Any:
        """Retrieve setting value. Checks repo override first, then global, then spec default."""
        cache_key = (repo_path, key)
        if cache_key in self._effective_cache:
            return self._effective_cache[cache_key]

        spec = self._specs.get(key)

        # Check repository override if repo_path provided and scope allows
        if repo_path and (spec is None or spec.scope == SettingScope.REPO_OVERRIDABLE):
            conn = self._get_conn()
            with _db_lock:
                try:
                    row = conn.execute(
                        "SELECT value_json FROM repo_settings_overrides "
                        "WHERE repo_path = ? AND key = ?",
                        (repo_path, key),
                    ).fetchone()
                    if row:
                        val = json.loads(row[0] if isinstance(row, tuple) else row["value_json"])
                        self._effective_cache[cache_key] = val
                        return val
                except sqlite3.Error as err:
                    logger.debug("Error checking repo setting override: %s", err)

        # Check global cache / database
        global_key = (None, key)
        if global_key in self._effective_cache:
            val = self._effective_cache[global_key]
            if repo_path:
                self._effective_cache[cache_key] = val
            return val

        conn = self._get_conn()
        with _db_lock:
            try:
                row = conn.execute(
                    "SELECT value_json FROM global_settings WHERE key = ?",
                    (key,),
                ).fetchone()
                if row:
                    val = json.loads(row[0] if isinstance(row, tuple) else row["value_json"])
                    self._effective_cache[global_key] = val
                    if repo_path:
                        self._effective_cache[cache_key] = val
                    return val
            except sqlite3.Error as err:
                logger.debug("Error checking global setting: %s", err)

        # Fallback to spec default
        default_val = spec.default if spec else None
        self._effective_cache[global_key] = default_val
        if repo_path:
            self._effective_cache[cache_key] = default_val
        return default_val

    def get_bool(self, key: str, repo_path: str | None = None) -> bool:
        """Type-safe boolean getter taking < 1 microsecond from memory cache."""
        val = self.get(key, repo_path)
        if isinstance(val, bool):
            return val
        if isinstance(val, (int, float)):
            return bool(val)
        if isinstance(val, str):
            return val.lower() in ("true", "1", "yes", "on")
        return bool(val)

    def is_enabled(self, key: str, repo_path: str | None = None) -> bool:
        """Alias for get_bool."""
        return self.get_bool(key, repo_path)

    def get_int(self, key: str, repo_path: str | None = None) -> int:
        """Type-safe integer getter."""
        val = self.get(key, repo_path)
        try:
            return int(val)
        except ValueError, TypeError:
            spec = self._specs.get(key)
            return int(spec.default) if spec and spec.default is not None else 0

    def get_str(self, key: str, repo_path: str | None = None) -> str:
        """Type-safe string getter."""
        val = self.get(key, repo_path)
        if val is None:
            spec = self._specs.get(key)
            return str(spec.default) if spec and spec.default is not None else ""
        return str(val)

    def set(self, key: str, value: Any, repo_path: str | None = None) -> None:
        """Validate, persist to SQLite, record undo delta, update cache, and emit signal."""
        spec = self._specs.get(key)
        validated_value = self._validate_value(spec, value)
        old_value = self.get(key, repo_path)

        conn = self._get_conn()
        with _db_lock, self._lock:
            val_json = json.dumps(validated_value)
            old_json = json.dumps(old_value)

            if repo_path and (spec is None or spec.scope == SettingScope.REPO_OVERRIDABLE):
                conn.execute(
                    """
                    INSERT INTO repo_settings_overrides (repo_path, key, value_json, updated_at)
                    VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(repo_path, key) DO UPDATE SET
                        value_json = excluded.value_json,
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    (repo_path, key, val_json),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO global_settings (key, value_json, updated_at)
                    VALUES (?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(key) DO UPDATE SET
                        value_json = excluded.value_json,
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    (key, val_json),
                )

            # Record change in settings_undo_log (OPT-3 delta stack)
            conn.execute(
                """
                INSERT INTO settings_undo_log
                (repo_path, key, old_value_json, new_value_json, undone)
                VALUES (?, ?, ?, ?, 0)
                """,
                (repo_path, key, old_json, val_json),
            )
            # Prune undo log beyond latest 100 entries
            conn.execute("""
                DELETE FROM settings_undo_log WHERE change_id NOT IN (
                    SELECT change_id FROM settings_undo_log ORDER BY change_id DESC LIMIT 100
                )
                """)
            conn.commit()

            # Invalidate/update cache
            self._effective_cache[(repo_path, key)] = validated_value
            if repo_path is None:
                # Invalidate any cached repo entries that were falling back to global
                keys_to_clear = [
                    k for k in self._effective_cache if k[1] == key and k[0] is not None
                ]
                for k in keys_to_clear:
                    self._effective_cache.pop(k, None)

        self.setting_changed.emit(key, validated_value, repo_path)

    def set_value(self, key: str, value: Any, repo_path: str | None = None) -> None:
        """Alias for set."""
        self.set(key, value, repo_path)

    def _validate_value(self, spec: SettingSpec | None, value: Any) -> Any:
        if spec is None:
            return value

        if spec.setting_type == SettingType.BOOL:
            if isinstance(value, str):
                return value.lower() in ("true", "1", "yes", "on")
            return bool(value)

        if spec.setting_type == SettingType.INT:
            int_val = int(value)
            if spec.min_value is not None:
                int_val = max(spec.min_value, int_val)
            if spec.max_value is not None:
                int_val = min(spec.max_value, int_val)
            return int_val

        if spec.setting_type == SettingType.CHOICE:
            str_val = str(value)
            if spec.choices and str_val not in spec.choices:
                return spec.default
            return str_val

        if spec.setting_type in (SettingType.STR, SettingType.PATH):
            return str(value)

        return value

    def reset_key(self, key: str, repo_path: str | None = None) -> None:
        """Reset key to default (or delete repo override)."""
        old_val = self.get(key, repo_path)
        spec = self._specs.get(key)
        new_val = spec.default if spec else None

        conn = self._get_conn()
        with _db_lock, self._lock:
            if repo_path:
                conn.execute(
                    "DELETE FROM repo_settings_overrides WHERE repo_path = ? AND key = ?",
                    (repo_path, key),
                )
            else:
                conn.execute("DELETE FROM global_settings WHERE key = ?", (key,))

            conn.execute(
                """
                INSERT INTO settings_undo_log
                (repo_path, key, old_value_json, new_value_json, undone)
                VALUES (?, ?, ?, ?, 0)
                """,
                (repo_path, key, json.dumps(old_val), json.dumps(new_val)),
            )
            conn.commit()

            self._effective_cache.pop((repo_path, key), None)
            if repo_path is None:
                self._effective_cache.pop((None, key), None)

        self.setting_changed.emit(key, new_val, repo_path)

    def reset_category(self, category: str, repo_path: str | None = None) -> None:
        """Reset all settings in a specific category."""
        specs = self.list_specs(category=category)
        for spec in specs:
            self.reset_key(spec.key, repo_path=repo_path)

    def reset_all(self, repo_path: str | None = None) -> None:
        """Reset all settings for repo or globally."""
        with self._lock:
            all_keys = list(self._specs.keys())
        for key in all_keys:
            self.reset_key(key, repo_path=repo_path)

    def undo_last_change(self) -> tuple[str, Any] | None:
        """Revert the most recent undone=0 delta row in settings_undo_log (OPT-3)."""
        conn = self._get_conn()
        with _db_lock, self._lock:
            row = conn.execute("""
                SELECT change_id, repo_path, key, old_value_json, new_value_json
                FROM settings_undo_log
                WHERE undone = 0
                ORDER BY change_id DESC LIMIT 1
                """).fetchone()
            if not row:
                return None

            change_id = row[0] if isinstance(row, tuple) else row["change_id"]
            repo_path = row[1] if isinstance(row, tuple) else row["repo_path"]
            key = row[2] if isinstance(row, tuple) else row["key"]
            old_val = json.loads(row[3] if isinstance(row, tuple) else row["old_value_json"])

            # Apply old value back to storage
            if repo_path:
                if old_val is None:
                    conn.execute(
                        "DELETE FROM repo_settings_overrides WHERE repo_path = ? AND key = ?",
                        (repo_path, key),
                    )
                else:
                    conn.execute(
                        """
                        INSERT INTO repo_settings_overrides (repo_path, key, value_json, updated_at)
                        VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                        ON CONFLICT(repo_path, key) DO UPDATE SET
                            value_json = excluded.value_json,
                            updated_at = CURRENT_TIMESTAMP
                        """,
                        (repo_path, key, json.dumps(old_val)),
                    )
            else:
                if old_val is None:
                    conn.execute("DELETE FROM global_settings WHERE key = ?", (key,))
                else:
                    conn.execute(
                        """
                        INSERT INTO global_settings (key, value_json, updated_at)
                        VALUES (?, ?, CURRENT_TIMESTAMP)
                        ON CONFLICT(key) DO UPDATE SET
                            value_json = excluded.value_json,
                            updated_at = CURRENT_TIMESTAMP
                        """,
                        (key, json.dumps(old_val)),
                    )

            conn.execute(
                "UPDATE settings_undo_log SET undone = 1 WHERE change_id = ?", (change_id,)
            )
            conn.commit()

            self._effective_cache[(repo_path, key)] = old_val

        self.setting_changed.emit(key, old_val, repo_path)
        return (key, old_val)

    def redo_last_change(self) -> tuple[str, Any] | None:
        """Re-apply the most recent undone=1 delta row in settings_undo_log."""
        conn = self._get_conn()
        with _db_lock, self._lock:
            row = conn.execute("""
                SELECT change_id, repo_path, key, new_value_json
                FROM settings_undo_log
                WHERE undone = 1
                ORDER BY change_id DESC LIMIT 1
                """).fetchone()
            if not row:
                return None

            change_id = row[0] if isinstance(row, tuple) else row["change_id"]
            repo_path = row[1] if isinstance(row, tuple) else row["repo_path"]
            key = row[2] if isinstance(row, tuple) else row["key"]
            new_val = json.loads(row[3] if isinstance(row, tuple) else row["new_value_json"])

            if repo_path:
                conn.execute(
                    """
                    INSERT INTO repo_settings_overrides (repo_path, key, value_json, updated_at)
                    VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(repo_path, key) DO UPDATE SET
                        value_json = excluded.value_json,
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    (repo_path, key, json.dumps(new_val)),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO global_settings (key, value_json, updated_at)
                    VALUES (?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(key) DO UPDATE SET
                        value_json = excluded.value_json,
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    (key, json.dumps(new_val)),
                )

            conn.execute(
                "UPDATE settings_undo_log SET undone = 0 WHERE change_id = ?", (change_id,)
            )
            conn.commit()

            self._effective_cache[(repo_path, key)] = new_val

        self.setting_changed.emit(key, new_val, repo_path)
        return (key, new_val)

    def list_recent_changes(self, limit: int = 50) -> list[SettingDelta]:
        """Return the most recent delta entries from settings_undo_log."""
        conn = self._get_conn()
        with _db_lock:
            rows = conn.execute(
                """
                SELECT change_id, timestamp, repo_path, key, old_value_json, new_value_json, undone
                FROM settings_undo_log
                ORDER BY change_id DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()

        results: list[SettingDelta] = []
        for r in rows:
            cid = r[0] if isinstance(r, tuple) else r["change_id"]
            ts = r[1] if isinstance(r, tuple) else r["timestamp"]
            rp = r[2] if isinstance(r, tuple) else r["repo_path"]
            k = r[3] if isinstance(r, tuple) else r["key"]
            old_v = json.loads(r[4] if isinstance(r, tuple) else r["old_value_json"])
            new_v = json.loads(r[5] if isinstance(r, tuple) else r["new_value_json"])
            und = bool(r[6] if isinstance(r, tuple) else r["undone"])
            results.append(
                SettingDelta(
                    change_id=cid,
                    timestamp=ts,
                    repo_path=rp,
                    key=k,
                    old_value=old_v,
                    new_value=new_v,
                    undone=und,
                )
            )
        return results

    def revert_specific_change(self, change_id: int) -> None:
        """Revert a single historical change out of order."""
        conn = self._get_conn()
        with _db_lock, self._lock:
            row = conn.execute(
                """
                SELECT repo_path, key, old_value_json
                FROM settings_undo_log
                WHERE change_id = ?
                """,
                (change_id,),
            ).fetchone()
            if not row:
                return

            repo_path = row[0] if isinstance(row, tuple) else row["repo_path"]
            key = row[1] if isinstance(row, tuple) else row["key"]
            old_val = json.loads(row[2] if isinstance(row, tuple) else row["old_value_json"])

        self.set(key, old_val, repo_path=repo_path)

    def apply_preset(self, preset_name: str, repo_path: str | None = None) -> None:
        """Apply a named preset: 'minimalist_local_only', 'power_user_full', or 'default'."""
        if preset_name in ("minimalist_local_only", "local_only"):
            self.apply_minimalist_local_only_preset(repo_path=repo_path)
        elif preset_name in ("default", "factory"):
            self.reset_all(repo_path=repo_path)
        elif preset_name == "power_user_full":
            self.set("forge.enabled", True, repo_path)
            self.set("remote.auto_fetch.enabled", True, repo_path)
            self.set("desktop.system_tray.enabled", True, repo_path)
            self.set("safety.scheduled_backups.enabled", True, repo_path)
            self.set("signing.verify_badges_in_graph.enabled", True, repo_path)
            self.set("stacks.enabled", True, repo_path)
            self.set("worktrees.enabled", True, repo_path)
            self.set("submodules.enabled", True, repo_path)
            self.set("lfs.enabled", True, repo_path)
            self.set("shortcuts.vim_mode_enabled", True, repo_path)

    def apply_minimalist_local_only_preset(self, repo_path: str | None = None) -> None:
        """Configure Wrench for distraction-free, zero-network, local-only Git operations."""
        toggles = [
            ("forge.enabled", False),
            ("remote.auto_fetch.enabled", False),
            ("desktop.system_tray.enabled", False),
            ("safety.scheduled_backups.enabled", False),
            ("signing.verify_badges_in_graph.enabled", False),
            ("stacks.enabled", False),
            ("worktrees.enabled", False),
            ("submodules.enabled", False),
            ("lfs.enabled", False),
        ]
        for key, val in toggles:
            self.set(key, val, repo_path=repo_path)

    def export_json(self, file_path: str | Path) -> None:
        """Export all user-modified global and repo settings to JSON."""
        conn = self._get_conn()
        with _db_lock:
            global_rows = conn.execute("SELECT key, value_json FROM global_settings").fetchall()
            repo_rows = conn.execute(
                "SELECT repo_path, key, value_json FROM repo_settings_overrides"
            ).fetchall()

        data: dict[str, Any] = {
            "version": 1,
            "global_settings": {
                (r[0] if isinstance(r, tuple) else r["key"]): json.loads(
                    r[1] if isinstance(r, tuple) else r["value_json"]
                )
                for r in global_rows
            },
            "repo_settings_overrides": [
                {
                    "repo_path": r[0] if isinstance(r, tuple) else r["repo_path"],
                    "key": r[1] if isinstance(r, tuple) else r["key"],
                    "value": json.loads(r[2] if isinstance(r, tuple) else r["value_json"]),
                }
                for r in repo_rows
            ],
        }
        Path(file_path).write_text(json.dumps(data, indent=2), encoding="utf-8")

    def import_json(self, file_path: str | Path) -> None:
        """Import settings from JSON file and apply them."""
        raw_content = Path(file_path).read_text(encoding="utf-8")
        data = json.loads(raw_content)

        globals_dict = data.get("global_settings", {})
        for k, v in globals_dict.items():
            self.set(k, v, repo_path=None)

        repo_list = data.get("repo_settings_overrides", [])
        for item in repo_list:
            rp = item.get("repo_path")
            k = item.get("key")
            v = item.get("value")
            if k is not None:
                self.set(k, v, repo_path=rp)


_GLOBAL_REGISTRY: SettingsRegistry | None = None
_GLOBAL_REGISTRY_LOCK = threading.Lock()


def peek_settings_registry() -> SettingsRegistry | None:
    """Return initialized SettingsRegistry singleton if present, without touching disk DB."""
    return _GLOBAL_REGISTRY


def get_settings_registry(conn: sqlite3.Connection | None = None) -> SettingsRegistry:
    """Return the global SettingsRegistry singleton, instantiating if needed."""
    global _GLOBAL_REGISTRY
    with _GLOBAL_REGISTRY_LOCK:
        if _GLOBAL_REGISTRY is None or (conn is not None and _GLOBAL_REGISTRY._conn != conn):
            _GLOBAL_REGISTRY = SettingsRegistry(conn=conn)
        return _GLOBAL_REGISTRY
