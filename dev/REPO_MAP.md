# Wrench Auto-Generated Full Repository Symbol Map (`dev/REPO_MAP.md`)

> Generated from `src/wrench/` at git HEAD `cc63d64` by
> `scripts/generate_repo_map.py`. Treat every dataclass field, `Signal`,
> `SettingsRegistry` key, and signature below as live ground truth.

---

## 1. Registered `SettingsRegistry` Keys (Do Not Duplicate)

- **Blame & Search:** `blame.enabled` (`True`), `search.pickaxe.enabled` (`True`)
- **Branches & Stacks:** `reset.show_visual_preview_dialog` (`True`), `rebase.interactive_ui.enabled` (`True`), `rebase.autostash` (`True`), `rebase.autosquash` (`True`), `rebase.conflict_prediction_enabled` (`True`), `stacks.enabled` (`True`)
- **Commit Graph:** `graph.show_lanes` (`True`), `graph.lane_width_px` (`16`), `graph.row_height_px` (`28`), `graph.date_format` (`'relative'`), `graph.show_avatars` (`True`), `graph.sort_order` (`'topo'`), `graph.cherry_pick_revert.enabled` (`True`), `graph.cherry_pick_revert.default_no_commit` (`False`), `graph.cherry_pick_revert.record_origin_x` (`True`), `graph.include_remote_branches` (`True`), `graph.show_wip_row` (`True`)
- **Custom Actions & Shortcuts:** `shortcuts.vim_mode_enabled` (`False`), `custom_actions.enabled` (`True`)
- **Diff & Merge:** `diff.context_lines` (`3`), `diff.ignore_whitespace_mode` (`'none'`), `merge.default_strategy` (`'merge'`), `merge.builtin_3way_tool.enabled` (`True`)
- **Forges & CI:** `forge.enabled` (`True`), `forge.github.enabled` (`True`), `forge.gitlab.enabled` (`True`), `forge.forgejo.enabled` (`True`), `forge.bitbucket.enabled` (`True`), `forge.ci_badges.enabled` (`True`), `forge.poll_interval_seconds` (`120`), `forge.allow_third_party_entrypoint_plugins` (`True`)
- **General & UI:** `ui.theme_mode` (`'system'`), `ui.font_size_pt` (`10`), `ui.confirm_destructive_actions` (`True`), `ui.avatars_gravatar` (`False`), `ui.session_state` (`True`), `ui.humor_lines` (`True`), `ui.activity_dock.max_lines` (`500`), `ui.show_cli_preview_in_dialogs` (`True`), `workspace.restore_session_on_startup` (`True`), `ui.settings_view_mode` (`'normal'`), `repo.recent_max_count` (`20`), `repo.auto_discovery.enabled` (`True`), `help.tooltip_mode` (`'beginner_rich'`), `help.tooltip_delay_ms` (`500`), `workspace.named_sessions.enabled` (`True`), `ui.history_three_column_layout` (`True`), `ui.show_context_header_bar` (`True`), `ui.show_empty_state_launchpad` (`True`)
- **Hooks & Signing:** `hooks.enabled` (`True`), `signing.enabled` (`False`), `signing.format` (`'auto'`), `signing.key_id_or_path` (`''`), `signing.sign_commits_by_default` (`True`), `signing.sign_tags_by_default` (`True`), `signing.gui_askpass_fallback.enabled` (`True`), `signing.verify_badges_in_graph.enabled` (`True`)
- **Remotes & LFS:** `remote.auto_fetch.enabled` (`True`), `remote.auto_fetch.interval_seconds` (`180`), `remote.pull_default_mode` (`'ff-only'`), `remote.force_push_mode` (`'force-with-lease'`), `remote.prune_on_fetch` (`True`), `lfs.enabled` (`True`), `clone.default_filter_mode` (`'none'`)
- **Safety & Backups:** `safety.commit_partially_staged_mode` (`'prompt'`), `safety.auto_stage_hook_modifications` (`True`), `safety.precommit_tool_search_paths` (`True`), `safety.pre_op_snapshot.enabled` (`True`), `safety.scheduled_backups.enabled` (`False`), `safety.op_log_undo_enabled` (`True`), `stash.ui.enabled` (`True`), `stash.confirm_before_drop` (`True`), `desktop.system_tray.enabled` (`True`)
- **Staging & Commits:** `staging.line_staging.enabled` (`True`), `commit.subject_max_length_guide` (`50`), `commit.body_wrap_column` (`72`), `commit.auto_stage_all_if_empty` (`False`), `commit.undo_button.enabled` (`True`)
- **Watcher & Performance:** `watcher.inotify.enabled` (`True`), `watcher.debounce_ms` (`300`), `watcher.refresh_on_window_focus` (`True`), `watcher.lock_recovery_prompt.enabled` (`True`), `performance.worker_thread_count` (`4`), `performance.max_diff_file_size_kb` (`2048`), `watcher.monorepo_adaptive_fallback.enabled` (`True`), `performance.graph_page_size` (`500`), `maintenance.auto_commit_graph.enabled` (`True`)
- **Worktrees & Submodules:** `worktrees.enabled` (`True`), `worktrees.bare_hub.enabled` (`True`), `worktrees.path_template` (`'../{repo_name}-{branch_slug}'`), `worktrees.cross_cherry_pick.enabled` (`True`), `submodules.enabled` (`True`), `submodules.auto_init` (`True`), `monorepo.sparse_checkout_ui.enabled` (`True`)

---

## 2. Public Modules, Dataclasses, Signals & Signatures

### `src/wrench/app.py` (131 lines)
- `def setup_logging(debug: bool = False)` (L20)
- `def main()` (L45)

### `src/wrench/core/backup.py` (21 lines)
- `def create_backup(repo_path: Path, output_path: Path) -> None` (L10)
- `def restore_backup(bundle_path: Path, dest_path: Path) -> None` (L16)

### `src/wrench/core/bundles.py` (92 lines)
- `def create_bundle(repo, output_path: Path | str, revs: list[str] | None = None) -> Path` (L12)
- `def verify_bundle(bundle_path: Path | str, repo = None) -> bool` (L29)
- `def unbundle(repo, bundle_path: Path | str) -> list[str]` (L40)
- `def get_bundle_info(bundle_path: Path | str, repo = None) -> BundleInfo` (L55)

### `src/wrench/core/crash_handler.py` (141 lines)
- `def set_active_window(window: Any) -> None` (L22)
- `def save_emergency_session(error: Exception | str, tb_str: str, repo_path: str | None = None) -> Path` (L28)
- `def install_crash_handler(window: Any = None) -> None` (L133)

### `src/wrench/core/discovery.py` (73 lines)
- `def discover_repos(root: Path | str, *, max_depth: int = 3, cancel_event: threading.Event | None = None, on_progress: Callable[[int], None] | None = None) -> list[Path]` (L20)

### `src/wrench/core/engine.py` (2320 lines)
- `@dataclass class FileChange` (L46)
  - **Fields:** `path: str; change_type: str; old_path: str | None = None; is_partially_staged: bool = False`
  - `status_code(self) -> str`
- `@dataclass class FileStatusInfo` (L59)
  - **Fields:** `path: str; staged_code: str; unstaged_code: str; is_partially_staged: bool; is_untracked: bool = False; staged_hunks_count: int = 0; unstaged_hunks_count: int = 0`
  - `composite_badge(self) -> str`
- `@dataclass class RepoStatus` (L79)
  - **Fields:** `staged: list[FileChange]; unstaged: list[FileChange]; untracked: list[str]; current_branch: str | None; is_detached: bool; ahead: int; behind: int; has_conflicts: bool; detached_head_sha: str | None = None; head_sha: str | None = None; merge_in_progress: bool = False; rebase_in_progress: bool = False; partially_staged: list[FileChange] = field(default_factory=list); is_bare: bool = False; is_bare_hub: bool = False`
  - `branch_name(self) -> str | None`
  - `is_detached_head(self) -> bool`
  - `partially_staged_paths(self) -> set[str]`
- `@dataclass class FileStat` (L110)
  - **Fields:** `path: str; change_type: str; additions: int; deletions: int`
- `@dataclass class RefLabel` (L120)
  - **Fields:** `name: str; kind: str`
- `@dataclass class Commit` (L128)
  - **Fields:** `sha: str; message: str; author_name: str; author_email: str; author_date: str; parent_shas: list[str]; refs: list[RefName] = field(default_factory=list)`
  - `author(self) -> str`
  - `hex(self) -> str`
- `@dataclass class BlameLine` (L147)
  - **Fields:** `line_no: int; commit_sha: str; author: str; line_content: str`
- `@dataclass class DiffLine` (L155)
  - **Fields:** `content: str; origin: str; old_lineno: int | None; new_lineno: int | None`
- `@dataclass class Hunk` (L163)
  - **Fields:** `id: str; old_start: int; old_count: int; new_start: int; new_count: int; lines: list[DiffLine]`
- `@dataclass class Diff` (L173)
  - **Fields:** `path: str; is_binary: bool; hunks: list[Hunk]; is_truncated: bool = False; total_lines: int = 0; truncated_reason: str | None = None`
- `@dataclass class MergeResult` (L183)
  - **Fields:** `status: str; commit_sha: str | None = None; conflicted_files: list[str] = field(default_factory=list)`
- `@dataclass class RebaseResult` (L190)
  - **Fields:** `status: str; conflicted_files: list[str] = field(default_factory=list)`
- `@dataclass class Remote` (L196)
  - **Fields:** `name: str; url: str`
- `@dataclass class ReflogEntry` (L202)
  - **Fields:** `sha: str; message: str; timestamp: str`
- `@dataclass class Submodule` (L209)
  - **Fields:** `path: str; url: str; initialized: bool`
- `@dataclass class SubmoduleStatus` (L216)
  - **Fields:** `path: str; current_commit: str; is_dirty: bool`
- `@dataclass class LogFilter` (L223)
  - **Fields:** `author: str | None = None; message_substring: str | None = None; date_from: str | None = None; date_to: str | None = None; path: str | None = None`
- `@dataclass class CloneResult` (L232)
  - **Fields:** `path: Path`
- `@dataclass class RemoteInfo` (L239)
  - **Fields:** `name: str; url: str; last_fetch_at: str | None = None; is_reachable: bool | None = None`
  - `fetch_url(self) -> str`
- `class RepoHandle` (L252)
  - `__init__(self, pygit2_repo: pygit2.Repository | str | Path, path: Path | str | None = None)`
  - `reload(self) -> None`
- `def init_repo(path: Path | str) -> RepoHandle` (L334)
- `def clone_repo(url: str, dest: Path | str, *, progress_cb = None, cancel_event = None, branch: str | None = None, recursive: bool = False, filter_spec: str | None = None, sparse: bool = False) -> CloneResult` (L340)
- `def open_repo(path: Path | str, *, configure_credentials: bool = True) -> RepoHandle` (L367)
- `def get_status(repo: RepoHandle) -> RepoStatus` (L400)
- `def get_diff(repo: RepoHandle, path: str, *, staged: bool, max_lines: int | None = None, max_bytes: int | None = None) -> Diff` (L404)
- `def get_log(repo: RepoHandle, filter: LogFilter | None = None, *, limit: int = 100, offset: int = 0, all_refs: bool = False) -> list[Commit]` (L421)
- `def get_log_page(repo: RepoHandle, filter: LogFilter | None = None, *, limit: int = 500, cursor_sha: str | None = None, all_refs: bool = False) -> LogPage` (L432)
- `def iter_commits(repo: RepoHandle, *, all_refs: bool = False)` (L449)
- `def get_commit_diff(repo: RepoHandle, sha: str, path: str | None = None, *, max_lines: int | None = None, max_bytes: int | None = None) -> Diff` (L453)
- `def get_commit_file_stats(repo: RepoHandle, sha: str) -> list[FileStat]` (L470)
- `def get_ref_labels(repo: RepoHandle) -> dict[str, list[RefLabel]]` (L474)
- `def get_repo_refs_signature(repo: RepoHandle) -> tuple[str, bool, bool, str, str, str] | None` (L478)
- `def blame(repo: RepoHandle, path: str) -> list[BlameLine]` (L484)
- `def stage_file(repo: RepoHandle, path: str) -> None` (L488)
- `def unstage_file(repo: RepoHandle, path: str) -> None` (L502)
- `def stage_hunk(repo: RepoHandle, path: str, hunk_id: str) -> None` (L516)
- `def stage_lines(repo: RepoHandle, path: str, line_numbers: list[int]) -> None` (L535)
- `def commit(repo: RepoHandle, message: str, *, amend: bool = False) -> str` (L619)
- `def list_branches(repo: RepoHandle, *, local: bool | None = None, remote: bool | None = None, include_remote: bool = False) -> list[str]` (L625)
- `def create_branch(repo: RepoHandle, name: str, *, from_ref: str = 'HEAD') -> None` (L658)
- `def switch_branch(repo: RepoHandle, name: str) -> None` (L662)
- `def delete_branch(repo: RepoHandle, name: str, *, force: bool = False) -> None` (L667)
- `def rename_branch(repo: RepoHandle, old: str, new: str) -> None` (L674)
- `def discard_file(repo: RepoHandle, path: str) -> None` (L678)
- `def stash_create(repo: RepoHandle, message: str | None = None) -> str` (L684)
- `def stash_pop(repo: RepoHandle, stash_id: str | int = 0) -> None` (L690)
- `def stash_apply(repo: RepoHandle, stash_id: str) -> None` (L695)
- `def stash_drop(repo: RepoHandle, stash_id: str) -> None` (L700)
- `def check_identity(repo_or_path: RepoHandle | Path | str) -> tuple[str, str]` (L704)
- `def set_identity(repo_or_path: RepoHandle | Path | str, name: str, email: str) -> None` (L709)
- `def get_reflog(repo: RepoHandle) -> list[ReflogEntry]` (L714)
- `def restore_to_ref(repo: RepoHandle, sha: str) -> None` (L718)
- `def push(repo: RepoHandle, remote: str, branch: str, *, force: bool = False, extra_config: dict[str, str] | None = None, timeout: float = 1800.0, progress_cb = None, cancel_event = None) -> None` (L722)
- `def push_incremental_batches(repo: RepoHandle, remote: str, branch: str, *, chunk_size: int = 20, force: bool = False, extra_config: dict[str, str] | None = None, progress_cb = None, cancel_event = None) -> None` (L745)
- `def pull(repo: RepoHandle, remote: str, branch: str, *, progress_cb = None, cancel_event = None) -> None` (L768)
- `def fetch(repo: RepoHandle, remote: str, *, db_conn = None, progress_cb = None, cancel_event = None) -> None` (L785)
- `def list_remotes(repo: RepoHandle, *, db_conn: sqlite3.Connection | None = None) -> list[RemoteInfo]` (L830)
- `def probe_remotes_async(repo: RepoHandle, *, db_conn: sqlite3.Connection | None = None, on_complete: Callable[[], None] | None = None) -> threading.Thread` (L932)
- `def add_remote(repo: RepoHandle, name: str, url: str, *, db_conn: sqlite3.Connection | None = None) -> None` (L957)
- `def remove_remote(repo: RepoHandle, name: str) -> None` (L984)
- `def set_remote_url(repo: RepoHandle, name: str, url: str) -> None` (L993)
- `def get_remote_url(repo: RepoHandle, name: str) -> str` (L1005)
- `def count_unpushed_commits(repo: RepoHandle, remote: str, branch: str) -> int` (L1013)
- `def merge(repo: RepoHandle, source_branch: str) -> MergeResult` (L1026)
- `def merge_abort(repo: RepoHandle) -> None` (L1030)
- `def rebase(repo: RepoHandle, onto: str) -> RebaseResult` (L1035)
- `def rebase_continue(repo: RepoHandle) -> RebaseResult` (L1039)
- `def rebase_abort(repo: RepoHandle) -> None` (L1043)
- `def create_tag(repo: RepoHandle, name: str, target: str = 'HEAD') -> None` (L1048)
- `def check_repo_guard(repo: RepoHandle, timeout: float = 3.0)` (L1053)
- `def sweep_repo_debris(repo: RepoHandle) -> list[str]` (L1059)
- `def get_git_config(repo: RepoHandle | Path | str | None, key: str, scope: str = 'local') -> str | None` (L1066)
- `def set_git_config(repo: RepoHandle | Path | str | None, key: str, value: str, scope: str = 'local') -> None` (L1091)
- `def get_http_post_buffer(repo: RepoHandle | Path | str | None = None, scope: str = 'local') -> int | None` (L1110)
- `def set_http_post_buffer(repo: RepoHandle | Path | str | None, buffer_bytes: int, scope: str = 'local') -> None` (L1124)
- `def get_http_version(repo: RepoHandle | Path | str | None = None, scope: str = 'local') -> str | None` (L1133)
- `def set_http_version(repo: RepoHandle | Path | str | None, version: str, scope: str = 'local') -> None` (L1141)
- `def scan_unpushed_large_blobs(repo: RepoHandle, remote: str = 'origin', branch: str | None = None, threshold_mb: float = 50.0) -> list[tuple[str, float]]` (L1163)
- `class GitEngine` (L1239)
  - `__init__(self, repo: RepoHandle | None = None, settings: Any = None) -> None`
  - `get_settings(self) -> Any`
  - `is_feature_enabled(self, key: str, repo_path: str | None = None) -> bool`
  - `open_repo(path: Path | str) -> RepoHandle`
  - `init_repo(path: Path | str, bare: bool = False) -> RepoHandle`
  - `clone_repo(url: str, dest: Path | str, branch: str | None = None, progress_cb: Callable[[int, int, int], None] | None = None, cancel_event: threading.Event | None = None, recursive: bool = False, filter_spec: str | None = None, sparse: bool = False) -> CloneResult`
  - `get_status(self, repo: RepoHandle | None = None) -> RepoStatus`
  - `stage_file(self, path: str, repo: RepoHandle | None = None) -> None`
  - `unstage_file(self, path: str, repo: RepoHandle | None = None) -> None`
  - `stage_all(self, repo: RepoHandle | None = None) -> None`
  - `unstage_all(self, repo: RepoHandle | None = None) -> None`
  - `commit(self, message: str, amend: bool = False, author: tuple[str, str] | None = None, repo: RepoHandle | None = None) -> str`
  - `get_diff(self, path: str, staged: bool = False, repo: RepoHandle | None = None, *, max_lines: int | None = None, max_bytes: int | None = None) -> Diff`
  - `get_commit_history(self, max_count: int = 100, skip: int = 0, branch: str | None = None, filter_opts: LogFilter | None = None, repo: RepoHandle | None = None) -> list[Commit]`
  - `get_log_page(self, filter: LogFilter | None = None, *, limit: int = 500, cursor_sha: str | None = None, all_refs: bool = False, repo: RepoHandle | None = None) -> LogPage`
  - `list_branches(self, *, local: bool | None = None, remote: bool | None = None, include_remote: bool = False, repo: RepoHandle | str | Path | None = None) -> list[str]`
  - `create_branch(self, name: str, start_point: str | None = None, repo: RepoHandle | None = None) -> None`
  - `checkout_branch(self, name: str, repo: RepoHandle | None = None) -> None`
  - `fetch_remote(self, remote: str = 'origin', repo: RepoHandle | None = None) -> None`
  - `pull_remote(self, remote: str = 'origin', branch: str | None = None, repo: RepoHandle | None = None) -> MergeResult`
  - `push_remote(self, remote: str = 'origin', branch: str | None = None, set_upstream: bool = False, force: bool = False, repo: RepoHandle | None = None) -> None`
  - `get_remotes(self, repo: RepoHandle | None = None) -> list[Remote]`
  - `is_lfs_installed() -> bool`
  - `lfs_available() -> bool`
  - `is_lfs_pointer(content: str) -> bool`
  - `parse_lfs_pointer(content: str) -> tuple[str, str] | None`
  - `lfs_files(self, paths: list[str], repo: RepoHandle | None = None) -> set[str]`
  - `lfs_track(self, pattern: str, repo: RepoHandle | None = None) -> None`
  - `lfs_untrack(self, pattern: str, repo: RepoHandle | None = None) -> None`
  - `lfs_pull(self, repo: RepoHandle | None = None) -> None`
  - `lfs_push(self, remote: str = 'origin', branch: str | None = None, repo: RepoHandle | None = None) -> None`
  - `lfs_status(self, repo: RepoHandle | None = None) -> list[LfsFileStatus]`
  - `lfs_locks(self, repo: RepoHandle | None = None) -> list[LFSLock]`
  - `lfs_lock(self, path: str, repo: RepoHandle | None = None) -> None`
  - `lfs_unlock(self, path: str, force: bool = False, repo: RepoHandle | None = None) -> None`
  - `list_submodules(self, repo: RepoHandle | None = None) -> list[Submodule]`
  - `submodule_status(self, path: str, repo: RepoHandle | None = None) -> SubmoduleStatus`
  - `init_submodule(self, path: str | None = None, repo: RepoHandle | None = None) -> None`
  - `update_submodules(self, path: str | None = None, recursive: bool = True, repo: RepoHandle | None = None) -> None`
  - `sync_submodules(self, path: str | None = None, repo: RepoHandle | None = None) -> None`
  - `add_submodule(self, url: str, path: str, repo: RepoHandle | None = None) -> None`
  - `create_bundle(self, output_path: Path | str, revs: list[str] | None = None, repo: RepoHandle | None = None) -> Path`
  - `verify_bundle(bundle_path: Path | str, repo: RepoHandle | None = None) -> bool`
  - `unbundle(self, bundle_path: Path | str, repo: RepoHandle | None = None) -> list[str]`
  - `get_bundle_info(bundle_path: Path | str, repo: RepoHandle | None = None) -> BundleInfo`
  - `list_reflog(self, ref: str = 'HEAD', limit: int = 100, repo: RepoHandle | None = None) -> list[ReflogEntry]`
  - `reset_to_reflog_entry(self, sha: str, mode: str = 'hard', repo: RepoHandle | None = None) -> None`
  - `create_branch_from_reflog(self, branch_name: str, sha: str, repo: RepoHandle | None = None) -> None`
  - `is_unborn_repo(repo_path: Path | str) -> bool`
  - `refresh_repo_handle(repo: RepoHandle | None) -> None`
  - `get_repo_refs_signature(repo: RepoHandle) -> tuple[str, bool, bool, str, str, str] | None`
  - `is_sparse_checkout_enabled(repo_path: Path | str) -> bool`
  - `get_sparse_checkout_state(repo_path: Path | str) -> SparseCheckoutState`
  - `init_sparse_checkout(repo_path: Path | str, cone: bool = True) -> None`
  - `list_sparse_directories(repo_path: Path | str) -> list[str]`
  - `set_sparse_directories(repo_path: Path | str, dirs: list[str], *, cone: bool = True, warnings_out: list[str] | None = None) -> None`
  - `disable_sparse_checkout(repo_path: Path | str, *, warnings_out: list[str] | None = None) -> None`
  - `list_head_top_directories(repo_path: Path | str, max_depth: int = 2) -> list[str]`
  - `list_tree_subdirectories(repo_path: Path | str, parent_rel_path: str = '') -> list[TreeDirectoryEntry]`
  - `write_commit_graph(repo_path: Path | str, *, reachable: bool = True, changed_paths: bool = True, timeout: int = 120) -> CommitGraphStats`
  - `maybe_write_commit_graph(self, repo_path: Path | str | None = None, *, settings_registry: Any = None) -> CommitGraphStats`
  - `list_commits_for_interactive_rebase(self, base_oid: str, repo: RepoHandle | None = None, *, limit: int = 1000) -> list[RebaseTodoEntry]`
  - `interactive_rebase(self, base_oid: str, entries: list[RebaseTodoEntry], repo: RepoHandle | None = None, *, autostash: bool | None = None, autosquash: bool | None = None, conn: sqlite3.Connection | None = None) -> RebaseResult`
  - `get_branch_sync_status(self, repo: RepoHandle | Path | str | None = None, branch_name: str | None = None) -> BranchSyncStatus`
  - `get_ref_sidebar_tree(self, repo: RepoHandle | Path | str | None = None) -> RefSidebarTree`
  - `get_commit(self, sha: str, repo: RepoHandle | Path | str | None = None) -> Commit | None`
  - `get_commit_details(self, sha: str, repo: RepoHandle | Path | str | None = None) -> Commit | None`
  - `list_worktrees(self, repo: RepoHandle | Path | str | None = None) -> list[WorktreeInfo]`
  - `format_worktree_path(self, branch_name: str, template: str | None = None, repo: RepoHandle | Path | str | None = None) -> Path`
  - `add_worktree(self, target_path: Path | str, branch: str | None = None, *, branch_name: str | None = None, create_branch: bool = False, new_branch: bool = False, commit: str | None = None, repo: RepoHandle | Path | str | None = None) -> WorktreeInfo`
  - `lock_worktree(self, worktree_path: Path | str, reason: str = '', repo: RepoHandle | Path | str | None = None) -> None`
  - `unlock_worktree(self, worktree_path: Path | str, repo: RepoHandle | Path | str | None = None) -> None`
  - `remove_worktree(self, worktree_path: Path | str, *, force: bool = False, repo: RepoHandle | Path | str | None = None) -> None`
  - `prune_worktrees(self, repo: RepoHandle | Path | str | None = None) -> None`
  - `cross_worktree_cherry_pick(self, target_worktree_path: Path | str, commit_oid: str, repo: RepoHandle | Path | str | None = None) -> None`
  - `verify_commit_signatures(self, commit_oids: list[str], repo: RepoHandle | Path | str | None = None) -> dict[str, SignatureStatus]`
  - `list_signing_keys(self) -> list[SigningKey]`
  - `run_terminal_command(self, subcommand_args: list[str] | str, repo: RepoHandle | Path | str | None = None) -> tuple[int, str, str, float]`
  - `run_git_terminal_command(self, subcommand_args: list[str] | str, repo: RepoHandle | Path | str | None = None) -> tuple[int, str, str, float]`
- `def run_git_terminal_command(repo_path: Path | str, subcommand_args: list[str] | str, timeout: float = 15.0) -> tuple[int, str, str, float]` (L1984)
- `def get_branch_sync_status(repo: RepoHandle | Path | str) -> BranchSyncStatus` (L2048)
- `def get_ref_sidebar_tree(repo: RepoHandle | Path | str) -> RefSidebarTree` (L2054)
- `def get_commit(repo: RepoHandle | Path | str, sha: str) -> Commit | None` (L2060)
- `def get_commit_details(repo: RepoHandle | Path | str, sha: str) -> Commit | None` (L2066)
- `def is_unborn_repo(repo_path: Path | str) -> bool` (L2072)
- `def refresh_repo_handle(repo: RepoHandle | None) -> None` (L2080)
- `def is_sparse_checkout_enabled(repo_path: Path | str) -> bool` (L2090)
- `def get_sparse_checkout_state(repo_path: Path | str) -> SparseCheckoutState` (L2094)
- `def init_sparse_checkout(repo_path: Path | str, cone: bool = True) -> None` (L2098)
- `def list_sparse_directories(repo_path: Path | str) -> list[str]` (L2102)
- `def set_sparse_directories(repo_path: Path | str, dirs: list[str], *, cone: bool = True, warnings_out: list[str] | None = None) -> None` (L2106)
- `def disable_sparse_checkout(repo_path: Path | str, *, warnings_out: list[str] | None = None) -> None` (L2121)
- `def list_head_top_directories(repo_path: Path | str, max_depth: int = 2) -> list[str]` (L2129)
- `def list_tree_subdirectories(repo_path: Path | str, parent_rel_path: str = '') -> list[TreeDirectoryEntry]` (L2133)
- `def write_commit_graph(repo_path: Path | str, *, reachable: bool = True, changed_paths: bool = True, timeout: int = 120) -> CommitGraphStats` (L2140)
- `def maybe_write_commit_graph(repo_path: Path | str, settings_registry: Any = None) -> CommitGraphStats` (L2155)
- `def build_interactive_rebase_cli_args(base_oid: str, *, autostash: bool = True, autosquash: bool = True) -> list[str]` (L2170)
- `def get_interactive_rebase_target_label(repo: RepoHandle | Path | str, base_oid: str) -> tuple[str, str, bool]` (L2183)
- `def list_commits_for_interactive_rebase_checked(repo: RepoHandle | Path | str, base_oid: str, *, limit: int = 1000) -> tuple[list[RebaseTodoEntry], bool]` (L2191)
- `def list_commits_for_interactive_rebase(repo: RepoHandle | Path | str, base_oid: str, *, limit: int = 1000) -> list[RebaseTodoEntry]` (L2205)
- `def interactive_rebase(repo: RepoHandle, base_oid: str, entries: list[RebaseTodoEntry], *, autostash: bool = True, autosquash: bool = True, conn: sqlite3.Connection | None = None) -> RebaseResult` (L2219)
- `def list_worktrees(repo: RepoHandle | Path | str) -> list[WorktreeInfo]` (L2242)
- `def format_worktree_path(repo: RepoHandle | Path | str, branch_name: str, template: str | None = None) -> Path` (L2247)
- `def add_worktree(repo: RepoHandle | Path | str, target_path: Path | str, branch: str | None = None, *, branch_name: str | None = None, create_branch: bool = False, new_branch: bool = False, commit: str | None = None) -> WorktreeInfo` (L2256)
- `def lock_worktree(repo: RepoHandle | Path | str, worktree_path: Path | str, reason: str = '') -> None` (L2278)
- `def unlock_worktree(repo: RepoHandle | Path | str, worktree_path: Path | str) -> None` (L2287)
- `def remove_worktree(repo: RepoHandle | Path | str, worktree_path: Path | str, *, force: bool = False) -> None` (L2292)
- `def prune_worktrees(repo: RepoHandle | Path | str) -> None` (L2302)
- `def cross_worktree_cherry_pick(target_worktree_path: Path | str, commit_oid: str) -> None` (L2307)
- `def verify_commit_signatures(repo: RepoHandle | Path | str, commit_oids: list[str]) -> dict[str, SignatureStatus]` (L2311)
- `def list_signing_keys() -> list[SigningKey]` (L2319)

### `src/wrench/core/exceptions.py` (354 lines)
- `class WrenchGitError(Exception)` (L4)
  - `__init__(self, message: str, *, stderr: str | None = None)`
- `class WrenchRepoNotFoundError(WrenchGitError)` (L12)
- `class EmptyCommitMessageError(WrenchGitError)` (L16)
- `class BranchAlreadyExistsError(WrenchGitError)` (L20)
- `class BranchNotFullyMergedError(WrenchGitError)` (L24)
- `class PatchApplyError(WrenchGitError)` (L28)
- `class BinaryFileStagingError(WrenchGitError)` (L32)
- `class IdentityRequiredError(WrenchGitError)` (L36)
  - `__init__(self, missing: list[str])`
- `class StaleLockDetectedError(WrenchGitError)` (L44)
  - `__init__(self, lock_path: str)`
- `class GitCommandError(WrenchGitError)` (L52)
  - `__init__(self, args: list[str], returncode: int, stderr: str, *, stdout: str = '')`
- `class NothingToCommitError(WrenchGitError)` (L71)
  - `__init__(self, message: str = 'Nothing to commit, working tree clean', *, stderr: str | None = None, stdout: str | None = None)`
- `class DirtyTreeError(WrenchGitError)` (L85)
  - `__init__(self, dirty_files: list[str], *, stderr: str | None = None)`
- `class RepoBusyError(WrenchGitError)` (L94)
  - `__init__(self, operation: str, state: str, *, stderr: str | None = None)`
- `class CloneAbortedError(WrenchGitError)` (L106)
  - `__init__(self, message: str = 'Clone operation was cancelled by user.', *, stderr: str | None = None)`
- `class AuthRequiredError(WrenchGitError)` (L115)
  - `__init__(self, host: str | None = None, path_component: str | None = None, *, stderr: str | None = None)`
- `class AuthFailedError(WrenchGitError)` (L131)
  - `__init__(self, host: str | None = None, *, stderr: str | None = None)`
- `class PushRejectedError(GitCommandError)` (L143)
  - `__init__(self, stderr_or_args: str | list[str] = '', returncode: int = 1, stderr: str | None = None)`
- `class WorkflowScopeRequiredError(GitCommandError)` (L158)
  - `__init__(self, stderr_or_args: str | list[str] = '', returncode: int = 1, stderr: str | None = None)`
- `class SecretScanningRejectedError(PushRejectedError)` (L173)
  - `__init__(self, stderr_or_args: str | list[str] = '', returncode: int = 1, stderr: str | None = None, *, secret_type: str | None = None, file_location: str | None = None, unblock_url: str | None = None) -> None`
- `class ProtectedBranchRejectedError(PushRejectedError)` (L192)
  - `__init__(self, stderr_or_args: str | list[str] = '', returncode: int = 1, stderr: str | None = None, *, branch_name: str | None = None, reason: str | None = None) -> None`
- `class FileTooLargeRejectedError(PushRejectedError)` (L209)
  - `__init__(self, stderr_or_args: str | list[str] = '', returncode: int = 1, stderr: str | None = None, *, filename: str | None = None, filesize_mb: float | None = None, limit_mb: float = 100.0) -> None`
- `class SignedCommitsRequiredError(PushRejectedError)` (L228)
- `class RepoPermissionDeniedError(PushRejectedError)` (L232)
- `class GitNetworkTransferError(PushRejectedError)` (L236)
  - `__init__(self, stderr_or_args: str | list[str] = '', returncode: int = 1, stderr: str | None = None, stdout: str = '', *, kind: str = 'timeout_408', status_code: int | None = None, curl_code: int | None = None, payload_mb: float | None = None, commit_count: int | None = None) -> None`
  - `is_timeout(self) -> bool`
  - `is_http2_error(self) -> bool`
  - `is_payload_too_large(self) -> bool`
- `class MergeRequiredError(GitCommandError)` (L284)
  - `__init__(self, stderr_or_args: str | list[str] = '', returncode: int = 1, stderr: str | None = None)`
- `class RemoteExistsError(WrenchGitError)` (L299)
  - `__init__(self, name: str, *, stderr: str | None = None)`
- `class RemoteNotFoundError(WrenchGitError)` (L307)
  - `__init__(self, name: str, *, stderr: str | None = None)`
- `class CLITimeoutError(GitCommandError)` (L315)
  - `__init__(self, args_or_msg: list[str] | str = '', returncode_or_timeout: int | float = -1, stderr: str = '', timeout: float | None = None)`
- `class LfsUnavailableError(WrenchGitError)` (L338)
  - `__init__(self, message: str = 'Git LFS is not installed. Please install git-lfs to use LFS features.')`
- `class WorktreeAlreadyCheckedOutError(WrenchGitError)` (L348)
  - `__init__(self, branch: str, existing_path: str)`

### `src/wrench/core/git_credential_helper.py` (200 lines)
- `def main() -> None` (L82)

### `src/wrench/core/identity.py` (52 lines)
- `def check_identity(repo_path: Path | str) -> tuple[str, str]` (L13)
- `def set_identity(repo_path: Path | str, name: str, email: str) -> None` (L45)

### `src/wrench/core/lazy_demo.py` (26 lines)
- `def calculate_square_root(value: float) -> float` (L11)
- `def serialize_json(data: dict) -> str` (L16)

### `src/wrench/core/lazy_loader.py` (58 lines)
- `class LazyProxyModule(types.ModuleType)` (L16)
  - `__init__(self, name: str) -> None`
- `def lazy_import(name: str) -> types.ModuleType` (L47)

### `src/wrench/core/lfs_ops.py` (260 lines)
- `def is_lfs_installed() -> bool` (L18)
- `def lfs_available() -> bool` (L43)
- `def is_lfs_pointer(content: str) -> bool` (L61)
- `def parse_lfs_pointer(content: str) -> tuple[str, str] | None` (L74)
- `def lfs_files(repo, paths: list[str]) -> set[str]` (L97)
- `def lfs_track(repo, pattern: str) -> None` (L121)
- `def lfs_untrack(repo, pattern: str) -> None` (L127)
- `def lfs_pull(repo) -> None` (L133)
- `def lfs_push(repo, remote: str = 'origin', branch: str | None = None) -> None` (L139)
- `def lfs_status(repo) -> list[LfsFileStatus]` (L151)
- `def lfs_locks(repo) -> list[LFSLock]` (L230)
- `def lfs_lock(repo, path: str) -> None` (L247)
- `def lfs_unlock(repo, path: str, *, force: bool = False) -> None` (L253)

### `src/wrench/core/lock_recovery.py` (55 lines)
- `def check_lock(repo_path: Path | str) -> None` (L15)
- `def remove_lock(repo_path: Path | str) -> None` (L34)
- `def check_all_repos(conn) -> list[tuple[int, str, str]]` (L42)

### `src/wrench/core/models.py` (432 lines)
- `@dataclass class FileChange` (L10)
  - **Fields:** `path: str; change_type: str; old_path: str | None = None; is_partially_staged: bool = False`
  - `status_code(self) -> str`
- `@dataclass class FileStatusInfo` (L23)
  - **Fields:** `path: str; staged_code: str; unstaged_code: str; is_partially_staged: bool; is_untracked: bool = False; staged_hunks_count: int = 0; unstaged_hunks_count: int = 0`
  - `composite_badge(self) -> str`
- `@dataclass class RepoStatus` (L43)
  - **Fields:** `staged: list[FileChange]; unstaged: list[FileChange]; untracked: list[str]; current_branch: str | None; is_detached: bool; ahead: int; behind: int; has_conflicts: bool; detached_head_sha: str | None = None; head_sha: str | None = None; merge_in_progress: bool = False; rebase_in_progress: bool = False; partially_staged: list[FileChange] = field(default_factory=list); is_bare: bool = False; is_bare_hub: bool = False`
  - `partially_staged_paths(self) -> set[str]`
  - `branch_name(self) -> str | None`
  - `is_detached_head(self) -> bool`
- `@dataclass class FileStat` (L74)
  - **Fields:** `path: str; change_type: str; additions: int; deletions: int`
- `class RefName(str)` (L83)
- `@dataclass class RefLabel` (L99)
  - **Fields:** `name: str; kind: str`
- `@dataclass class Commit` (L107)
  - **Fields:** `sha: str; message: str; author_name: str; author_email: str; author_date: str; parent_shas: list[str]; refs: list[RefName] = field(default_factory=list)`
  - `author(self) -> str`
  - `hex(self) -> str`
- `@dataclass class BlameLine` (L126)
  - **Fields:** `line_no: int; commit_sha: str; author: str; line_content: str`
- `@dataclass class DiffLine` (L134)
  - **Fields:** `content: str; origin: str; old_lineno: int | None; new_lineno: int | None`
- `@dataclass class Hunk` (L142)
  - **Fields:** `id: str; old_start: int; old_count: int; new_start: int; new_count: int; lines: list[DiffLine]`
- `@dataclass class Diff` (L152)
  - **Fields:** `path: str; is_binary: bool; hunks: list[Hunk]; is_truncated: bool = False; total_lines: int = 0; truncated_reason: str | None = None`
- `@dataclass class MergeResult` (L162)
  - **Fields:** `status: str; commit_sha: str | None = None; conflicted_files: list[str] = field(default_factory=list)`
- `@dataclass class RebaseResult` (L169)
  - **Fields:** `status: str; conflicted_files: list[str] = field(default_factory=list)`
- `@dataclass class Remote` (L175)
  - **Fields:** `name: str; url: str`
- `@dataclass class ReflogEntry` (L181)
  - **Fields:** `sha: str; message: str; timestamp: str`
- `@dataclass class Submodule` (L188)
  - **Fields:** `path: str; url: str; initialized: bool`
- `@dataclass class SubmoduleStatus` (L195)
  - **Fields:** `path: str; current_commit: str; is_dirty: bool`
- `@dataclass class LogFilter` (L202)
  - **Fields:** `author: str | None = None; message_substring: str | None = None; date_from: str | None = None; date_to: str | None = None; path: str | None = None`
- `@dataclass class CloneResult` (L211)
  - **Fields:** `path: Path`
- `@dataclass class RemoteInfo` (L218)
  - **Fields:** `name: str; url: str; last_fetch_at: str | None = None; is_reachable: bool | None = None`
  - `fetch_url(self) -> str`
- `@dataclass class LfsFileStatus` (L232)
  - **Fields:** `path: str; is_pointer: bool; oid: str | None = None; size: int | None = None; is_locked: bool = False; locked_by: str | None = None`
- `@dataclass class LFSLock` (L244)
  - **Fields:** `lock_id: str; path: str; owner: str`
- `@dataclass class BundleInfo` (L253)
  - **Fields:** `path: Path; is_valid: bool; prerequisites: list[str] = field(default_factory=list); references: list[str] = field(default_factory=list)`
- `@dataclass class SparseCheckoutState` (L263)
  - **Fields:** `enabled: bool; cone_mode: bool; directories: tuple[str, ...]; partial_filter: str | None = None`
- `@dataclass class TreeDirectoryEntry` (L273)
  - **Fields:** `name: str; rel_path: str; has_children: bool; is_selected: bool = False`
- `@dataclass class LogPage` (L283)
  - **Fields:** `commits: tuple[Commit, ...]; next_cursor_sha: str | None; has_more: bool; scanned_count: int = 0`
- `@dataclass class CommitGraphStats` (L293)
  - **Fields:** `written: bool; duration_ms: int; skipped_reason: str | None = None; graph_file_size_bytes: int = 0`
- `@dataclass class WatcherStatusInfo` (L303)
  - **Fields:** `mode: str; is_fallback: bool; watched_paths: tuple[str, ...]; reason: str | None = None`
- `@dataclass class RebaseTodoEntry` (L313)
  - **Fields:** `action: str; oid: str; short_oid: str; summary: str; author: str; new_message: str | None = None`
- `@dataclass class BranchInfo` (L330)
  - **Fields:** `name: str; is_head: bool; upstream_name: str | None = None; ahead: int = 0; behind: int = 0; target_oid: str = ''`
- `@dataclass class TagInfo` (L342)
  - **Fields:** `name: str; target_oid: str; message: str | None = None; tagger_date: str | None = None`
- `@dataclass class StashEntry` (L352)
  - **Fields:** `index: int; message: str; oid: str; timestamp: str | None = None`
- `@dataclass class BranchSyncStatus` (L362)
  - **Fields:** `branch_name: str; upstream_name: str | None; ahead: int = 0; behind: int = 0; is_detached: bool = False`
- `@dataclass class RefSidebarTree` (L373)
  - **Fields:** `local_branches: tuple[BranchInfo, ...] = (); remote_branches: tuple[BranchInfo, ...] = (); tags: tuple[TagInfo, ...] = (); stashes: tuple[StashEntry, ...] = ()`
- `@dataclass class WorktreeInfo` (L388)
  - **Fields:** `path: str; head_oid: str; branch_name: str | None; is_bare: bool; is_locked: bool; lock_reason: str | None = None; is_prunable: bool = False; is_main: bool = False; is_detached: bool = False`
- `@dataclass class WorkspaceSession` (L403)
  - **Fields:** `session_name: str; repo_paths: tuple[str, ...]; active_index: int; tabs: tuple[dict[str, Any], ...] = ()`
- `@dataclass class SignatureStatus` (L413)
  - **Fields:** `oid: str; state: str; signer: str | None = None; key_fingerprint: str | None = None; key_type: str | None = None; validity_details: str | None = None`
- `@dataclass class SigningKey` (L425)
  - **Fields:** `key_id: str; key_type: str; display_name: str; fingerprint: str; email: str | None = None`

### `src/wrench/core/paths.py` (61 lines)
- `def data_dir() -> Path` (L12)
- `def config_dir() -> Path` (L17)
- `def state_dir() -> Path` (L22)
- `def cache_dir() -> Path` (L27)
- `def resolve_git_dir(repo_path: Path | str) -> Path` (L32)

### `src/wrench/core/read_ops.py` (1761 lines)
- `def configure_libgit2_cache_limits(*, force: bool = False) -> None` (L225)
- `def configure_libgit2_memory_limits(max_cache_mb: int = 32) -> None` (L242)
- `def get_status(repo: RepoHandle) -> RepoStatus` (L249)
- `def get_diff(repo: RepoHandle, path: str, *, staged: bool, max_lines: int | None = None, max_bytes: int | None = None) -> Diff` (L806)
- `def get_commit_diff(repo: RepoHandle, sha: str, path: str | None = None, *, max_lines: int | None = None, max_bytes: int | None = None) -> Diff` (L998)
- `def get_commit_file_stats(repo: RepoHandle, sha: str) -> list[FileStat]` (L1048)
- `def get_ref_labels(repo: RepoHandle) -> dict[str, list[RefLabel]]` (L1099)
- `def iter_commits(repo: RepoHandle, *, all_refs: bool = False) -> Iterator[Commit]` (L1166)
- `def get_log_page(repo: RepoHandle, filter: LogFilter | None = None, *, limit: int = 500, cursor_sha: str | None = None, all_refs: bool = False) -> LogPage` (L1337)
- `def get_log(repo: RepoHandle, filter: LogFilter | None = None, *, limit: int = 100, offset: int = 0, all_refs: bool = False) -> list[Commit]` (L1442)
- `def get_commit(repo: RepoHandle | Path | str, sha: str) -> Commit | None` (L1490)
- `def get_commit_details(repo: RepoHandle | Path | str, sha: str) -> Commit | None` (L1505)
- `def blame_file(repo: RepoHandle, path: str) -> list[BlameLine]` (L1510)
- `def get_repo_refs_signature(repo: RepoHandle) -> tuple[str, bool, bool, str, str, str] | None` (L1545)
- `def get_branch_sync_status(repo_path: Path | str) -> BranchSyncStatus` (L1604)
- `def get_ref_sidebar_tree(repo_path: Path | str) -> RefSidebarTree` (L1668)

### `src/wrench/core/rebase_editor_helper.py` (145 lines)
- `def apply_sequence_plan(todo_path: Path, plan: dict[str, Any]) -> None` (L40)
- `def apply_commit_message(msg_path: Path, plan_path: Path, plan: dict[str, Any]) -> None` (L94)
- `def main(argv: list[str] | None = None) -> int` (L120)

### `src/wrench/core/rebase_sequencer.py` (354 lines)
- `def build_interactive_rebase_cli_args(base_oid: str, *, autostash: bool = True, autosquash: bool = True) -> list[str]` (L82)
- `def get_interactive_rebase_target_label(repo_path: Path | str, base_oid: str) -> tuple[str, str, bool]` (L99)
- `def list_commits_for_interactive_rebase_checked(repo_path: Path | str, base_oid: str, *, limit: int = MAX_INTERACTIVE_REBASE_COMMITS) -> tuple[list[RebaseTodoEntry], bool]` (L142)
- `def list_commits_for_interactive_rebase(repo_path: Path | str, base_oid: str, *, limit: int = MAX_INTERACTIVE_REBASE_COMMITS) -> list[RebaseTodoEntry]` (L205)
- `def run_interactive_rebase(repo_path: Path | str, base_oid: str, entries: Sequence[RebaseTodoEntry], *, autostash: bool = True, autosquash: bool = True, timeout: int = 300) -> RebaseResult` (L228)

### `src/wrench/core/recovery/actions.py` (599 lines)
- `@dataclass class ActionResult` (L20)
  - **Fields:** `success: bool; message: str; error: str | None = None`
- `class RecoveryAction` (L26)
  - **Fields:** `action_id: str = 'base'; title: str = 'Recover'; description: str = ''; is_primary: bool = False`
  - `execute(self, repo_path: Path | str, context: dict | None = None) -> ActionResult`
- `class ReleaseStaleLockAction(RecoveryAction)` (L38)
  - `__init__(self, lock_path: Path | str | None = None)`
  - `execute(self, repo_path: Path | str, context: dict | None = None) -> ActionResult`
- `def find_project_binary(repo_path: Path | str, binary_name: str) -> Path | None` (L72)
- `class StageHookModificationsAndRetryAction(RecoveryAction)` (L94)
  - `execute(self, repo_path: Path | str, context: dict | None = None) -> ActionResult`
- `class AutoFormatAndRetryAction(RecoveryAction)` (L156)
  - `execute(self, repo_path: Path | str, context: dict | None = None) -> ActionResult`
- `class RunPreCommitFixAction(RecoveryAction)` (L231)
  - `execute(self, repo_path: Path | str, context: dict | None = None) -> ActionResult`
- `class CommitNoVerifyAction(RecoveryAction)` (L295)
  - `execute(self, repo_path: Path | str, context: dict | None = None) -> ActionResult`
- `class AutoStashAndRetryAction(RecoveryAction)` (L327)
  - `__init__(self, operation_callback: Callable[[], None] | None = None)`
  - `execute(self, repo_path: Path | str, context: dict | None = None) -> ActionResult`
- `class QuarantineUntrackedAction(RecoveryAction)` (L401)
  - `__init__(self, conflicting_files: list[str] | None = None)`
  - `execute(self, repo_path: Path | str, context: dict | None = None) -> ActionResult`
- `class AbortInterruptedOperationAction(RecoveryAction)` (L436)
  - `__init__(self, mode: str = 'merge')`
  - `execute(self, repo_path: Path | str, context: dict | None = None) -> ActionResult`
- `class RebuildCorruptIndexAction(RecoveryAction)` (L474)
  - `execute(self, repo_path: Path | str, context: dict | None = None) -> ActionResult`
- `class WaitForRepoReleaseAction(RecoveryAction)` (L512)
  - `__init__(self, timeout: float = 30.0)`
  - `execute(self, repo_path: Path | str, context: dict | None = None) -> ActionResult`
- `class PullAndRebaseAction(RecoveryAction)` (L533)
  - `execute(self, repo_path: Path | str, context: dict | None = None) -> ActionResult`
- `class SyncSubmodulesAction(RecoveryAction)` (L556)
  - `execute(self, repo_path: Path | str, context: dict | None = None) -> ActionResult`
- `class PruneWorktreesAction(RecoveryAction)` (L579)
  - `execute(self, repo_path: Path | str, context: dict | None = None) -> ActionResult`

### `src/wrench/core/recovery/classifier.py` (288 lines)
- `class ErrorCategory(str, Enum)` (L26)
- `@dataclass class DiagnosticReport` (L41)
  - **Fields:** `category: ErrorCategory; title: str; description: str; technical_details: str = ''; actions: list[RecoveryAction] = field(default_factory=list)`
  - `primary_action(self) -> RecoveryAction | None`
- `def diagnose_error(error: Exception | str, *, repo_path: Path | str | None = None, stderr: str | None = None, stdout: str | None = None, command: list[str] | str | None = None) -> DiagnosticReport` (L56)

### `src/wrench/core/recovery/process_guard.py` (228 lines)
- `def is_pid_alive(pid: int) -> bool` (L16)
- `def get_process_cmdline(pid: int) -> str` (L39)
- `def find_active_git_processes_for_repo(repo_path: Path | str) -> list[tuple[int, str]]` (L63)
- `def inspect_locks(repo_path: Path | str) -> list[tuple[Path, int | None, str, float]]` (L88)
- `@dataclass class GuardResult` (L157)
  - **Fields:** `status: str; lock_path: Path | None = None; pid: int | None = None; process_cmd: str | None = None; age_seconds: float = 0.0`
- `def acquire_repo_guard(repo_path: Path | str, timeout: float = 3.0, poll_interval: float = 0.3) -> GuardResult` (L165)
- `def remove_lock(lock_path: Path | str) -> bool` (L212)

### `src/wrench/core/recovery/sweeper.py` (66 lines)
- `def sweep_debris(repo_path: Path | str) -> list[str]` (L15)

### `src/wrench/core/recovery/transaction.py` (71 lines)
- `class WorkspaceTransaction` (L14)
  - `__init__(self, repo_path: Path | str, name: str = 'transaction')`
  - `register_temp_path(self, path: Path | str) -> Path`
  - `register_temp_dir(self, dir_path: Path | str) -> Path`
  - `rollback(self) -> None`
  - `commit(self) -> None`
- `def workspace_transaction(repo_path: Path | str, name: str = 'operation') -> Generator[WorkspaceTransaction, None, None]` (L59)

### `src/wrench/core/reflog.py` (18 lines)
- `def get_reflog(repo: RepoHandle) -> list[ReflogEntry]` (L11)
- `def restore_to_ref(repo: RepoHandle, sha: str) -> None` (L16)

### `src/wrench/core/reflog_ops.py` (85 lines)
- `def list_reflog(repo, ref: str = 'HEAD', limit: int = 100) -> list[ReflogEntry]` (L13)
- `def reset_to_reflog_entry(repo, sha: str, mode: str = 'hard') -> None` (L68)
- `def create_branch_from_reflog(repo, branch_name: str, sha: str) -> None` (L83)

### `src/wrench/core/remote_urls.py` (117 lines)
- `@dataclass class RemoteUrlParts` (L12)
  - **Fields:** `protocol: str; host: str; owner: str; repo: str`
- `def parse_remote_url(url: str) -> RemoteUrlParts | None` (L21)
- `def host_of_instance_url(instance_url: str) -> str` (L96)

### `src/wrench/core/security_sanitizer.py` (108 lines)
- `def validate_clone_url(url: str) -> str` (L31)
- `def validate_git_ref(ref: str) -> str` (L77)
- `def redact_secrets(text: str) -> str` (L99)

### `src/wrench/core/signing_ops.py` (249 lines)
- `def parse_signature_log_output(output: str) -> dict[str, SignatureStatus]` (L21)
- `def verify_commit_signatures_batch(repo_path: Path | str, oids: list[str], settings: Any = None) -> dict[str, SignatureStatus]` (L86)
- `def clear_signature_cache() -> None` (L174)
- `def list_available_signing_keys() -> list[SigningKey]` (L179)

### `src/wrench/core/snapshots.py` (290 lines)
- `@dataclass class Snapshot` (L22)
  - **Fields:** `id: int; created_at: str; trigger_type: str; is_manual: bool; label: str | None; ref_name: str`
- `@dataclass class SnapshotSettings` (L32)
  - **Fields:** `trigger_on_commit: bool; trigger_on_timer: bool; timer_interval_minutes: int; trigger_before_risky_op: bool; max_count: int; max_age_days: int | None; untracked_capture_mode: str; untracked_per_file_cap_mb: int; untracked_total_cap_mb: int`
- `def maybe_create_safety_snapshot(repo: RepoHandle, op_name: str, *, conn: sqlite3.Connection | None = None, repo_id: int | None = None) -> Snapshot | None` (L62)
- `def take_snapshot(repo: RepoHandle, trigger_type: str, *, label: str | None = None, conn: sqlite3.Connection | None = None, repo_id: int | None = None) -> Snapshot | None` (L87)
- `def list_snapshots(repo: RepoHandle, *, conn: sqlite3.Connection | None = None, repo_id: int | None = None) -> list[Snapshot]` (L154)
- `def restore_snapshot(repo: RepoHandle, snapshot_id: int, *, conn: sqlite3.Connection | None = None) -> None` (L179)
- `def prune_snapshots(repo: RepoHandle, *, conn: sqlite3.Connection | None = None, repo_id: int | None = None) -> int` (L199)
- `def get_snapshot_settings(repo: RepoHandle, *, conn: sqlite3.Connection | None = None, repo_id: int | None = None) -> SnapshotSettings` (L226)
- `def update_snapshot_settings(repo: RepoHandle, settings: SnapshotSettings, *, conn: sqlite3.Connection | None = None, repo_id: int | None = None) -> None` (L260)

### `src/wrench/core/sparse_checkout.py` (456 lines)
- `def is_sparse_checkout_enabled(repo_path: Path | str) -> bool` (L171)
- `def get_sparse_checkout_state(repo_path: Path | str) -> SparseCheckoutState` (L181)
- `def init_sparse_checkout(repo_path: Path | str, *, cone: bool = True) -> None` (L216)
- `def list_sparse_directories(repo_path: Path | str, *, _repo: pygit2.Repository | None = None, _sparse_file: Path | None = None, _cone_mode: bool | None = None) -> list[str]` (L224)
- `def set_sparse_directories(repo_path: Path | str, dirs: list[str], *, cone: bool = True, warnings_out: list[str] | None = None) -> None` (L272)
- `def disable_sparse_checkout(repo_path: Path | str, *, warnings_out: list[str] | None = None) -> None` (L306)
- `def list_tree_subdirectories(repo_path: Path | str, parent_rel_path: str = '') -> list[TreeDirectoryEntry]` (L322)
- `def list_head_top_directories(repo_path: Path | str, max_depth: int = 2) -> list[str]` (L419)

### `src/wrench/core/ssh_agent.py` (17 lines)
- `def get_ssh_auth_socket() -> str | None` (L6)
- `def configure_ssh_env(env: dict[str, str]) -> None` (L11)

### `src/wrench/core/submodules.py` (159 lines)
- `def list_submodules(repo) -> list[Submodule]` (L30)
- `def submodule_status(repo, path: str) -> SubmoduleStatus` (L70)
- `def init_submodule(repo, path: str | None = None) -> None` (L102)
- `def update_submodules(repo, path: str | None = None, recursive: bool = True) -> None` (L116)
- `def sync_submodules(repo, path: str | None = None) -> None` (L129)
- `def add_submodule(repo, url: str, path: str) -> None` (L137)

### `src/wrench/core/worktrees.py` (213 lines)
- `def list_worktrees(repo_path: Path | str) -> list[WorktreeInfo]` (L20)
- `def format_worktree_path(repo_path: Path | str, branch_name: str, template: str | None = None) -> Path` (L95)
- `def add_worktree(repo_path: Path | str, target_path: Path | str, branch: str | None = None, *, branch_name: str | None = None, create_branch: bool = False, new_branch: bool = False, commit: str | None = None) -> WorktreeInfo` (L118)
- `def lock_worktree(repo_path: Path | str, worktree_path: Path | str, reason: str = '') -> None` (L172)
- `def unlock_worktree(repo_path: Path | str, worktree_path: Path | str) -> None` (L184)
- `def remove_worktree(repo_path: Path | str, worktree_path: Path | str, *, force: bool = False) -> None` (L189)
- `def prune_worktrees(repo_path: Path | str) -> None` (L203)
- `def cross_worktree_cherry_pick(target_worktree_path: Path | str, commit_oid: str) -> None` (L208)

### `src/wrench/core/write_ops.py` (1293 lines)
- `def run_git(repo_path: Path | str, args: list[str], *, timeout: int = 30, check: bool = True, input_text: str | None = None) -> subprocess.CompletedProcess` (L64)
- `def ensure_wrench_credential_config(repo_path: Path | str, pygit2_repo: pygit2.Repository | None = None) -> None` (L154)
- `def run_git_streaming(repo_path: Path | str, args: list[str], *, timeout: int = 600, on_stderr_line: Callable[[str], None] | None = None, cancel_event: threading.Event | None = None) -> tuple[int, str, str]` (L498)
- `def commit(repo_path: Path, message: str, *, amend: bool = False) -> str` (L653)
- `def create_branch(repo_path: Path, name: str, from_ref: str = 'HEAD') -> None` (L681)
- `def switch_branch(repo_path: Path, name: str) -> None` (L693)
- `def delete_branch(repo_path: Path, name: str, *, force: bool = False) -> None` (L698)
- `def rename_branch(repo_path: Path, old: str, new: str) -> None` (L712)
- `def create_tag(repo_path: Path | str, name: str, target: str = 'HEAD') -> None` (L717)
- `def stash_push(repo_path: Path, message: str | None = None) -> str` (L722)
- `def stash_pop(repo_path: Path | str, stash_id: str | int = 0) -> None` (L731)
- `def stash_apply(repo_path: Path | str, stash_id: str) -> None` (L737)
- `def stash_drop(repo_path: Path | str, stash_id: str) -> None` (L742)
- `def discard_file(repo_path: Path | str, file_path: str) -> None` (L747)
- `def init_repo(repo_path: Path | str) -> None` (L765)
- `def push(repo_path: Path | str, remote: str, branch: str, *, force: bool = False, extra_config: dict[str, str] | None = None, timeout: float = 1800.0, progress_cb: Callable[[int, str], None] | None = None, cancel_event: threading.Event | None = None) -> None` (L772)
- `def push_incremental_batches(repo_path: Path | str, remote: str, branch: str, *, chunk_size: int = 20, force: bool = False, extra_config: dict[str, str] | None = None, progress_cb: Callable[[int, str], None] | None = None, cancel_event: threading.Event | None = None) -> None` (L820)
- `def pull(repo_path: Path | str, remote: str, branch: str, *, progress_cb: Callable[[int, str], None] | None = None, cancel_event: threading.Event | None = None) -> None` (L908)
- `def fetch(repo_path: Path | str, remote: str, *, db_conn: sqlite3.Connection | None = None, progress_cb: Callable[[int, str], None] | None = None, cancel_event: threading.Event | None = None) -> None` (L946)
- `def clone_repo(url: str, dest: Path | str, *, timeout: int = 600, progress_cb: Callable[[int, str], None] | None = None, cancel_event: threading.Event | None = None, branch: str | None = None, recursive: bool = False, filter_spec: str | None = None, sparse: bool = False) -> CloneResult` (L1014)
- `def merge(repo_path: Path | str, source_branch: str) -> MergeResult` (L1119)
- `def merge_abort(repo_path: Path | str) -> None` (L1161)
- `def rebase(repo_path: Path | str, onto: str) -> RebaseResult` (L1167)
- `def rebase_continue(repo_path: Path | str) -> RebaseResult` (L1204)
- `def rebase_abort(repo_path: Path | str) -> None` (L1224)
- `def write_commit_graph(repo_path: Path | str, *, reachable: bool = True, changed_paths: bool = True, timeout: int = 120) -> CommitGraphStats` (L1230)

### `src/wrench/credentials/__init__.py` (30 lines)
- `def get_backend() -> CredentialBackend` (L18)

### `src/wrench/credentials/backend.py` (21 lines)
- `class CredentialBackendUnavailableError(Exception)` (L6)
- `class CredentialBackend(ABC)` (L10)
  - `store_secret(self, key: str, secret: str, *, label: str) -> None`
  - `get_secret(self, key: str) -> str | None`
  - `delete_secret(self, key: str) -> None`
  - `unavailable_help_text(self) -> str`

### `src/wrench/credentials/secret_service.py` (65 lines)
- `class SecretServiceBackend(CredentialBackend)` (L12)
  - `store_secret(self, key: str, secret: str, *, label: str) -> None`
  - `get_secret(self, key: str) -> str | None`
  - `delete_secret(self, key: str) -> None`
- `class FlatpakSecretServiceBackend(SecretServiceBackend)` (L46)
  - `unavailable_help_text(self) -> str`
- `class AppImageSecretServiceBackend(SecretServiceBackend)` (L56)
  - `unavailable_help_text(self) -> str`

### `src/wrench/credentials/signing_askpass.py` (126 lines)
- `class SigningAskpassBridge` (L17)
  - `__init__(self, prompt_callback: Callable[[str], str]) -> None`
  - `start(self) -> dict[str, str]`
  - `stop(self) -> None`

### `src/wrench/forge/adapters/bitbucket.py` (264 lines)
- `class BitbucketAdapter(ForgeAdapter)` (L18)
  - `capabilities(self) -> ForgeCapability`
  - `authenticate(self) -> None`
  - `list_pull_requests(self, owner: str, repo: str, state: str = 'open') -> list[PullRequest]`
  - `create_pull_request(self, owner: str, repo: str, *, title: str, source_branch: str, target_branch: str, description: str = '') -> PullRequest`
  - `submit_review(self, owner: str, repo: str, number: int, *, action: str, body: str = '') -> None`
  - `get_ci_status(self, owner: str, repo: str, ref: str) -> CIStatus`
  - `list_issues(self, owner: str, repo: str, state: str = 'open') -> list[Issue]`
  - `get_pull_request(self, owner: str, repo: str, pr_id: str) -> PullRequest`
  - `get_issue(self, owner: str, repo: str, issue_id: str) -> Issue`
  - `get_avatar_url(self) -> str | None`

### `src/wrench/forge/adapters/forgejo.py` (217 lines)
- `class ForgejoAdapter(ForgeAdapter)` (L11)
  - `capabilities(self) -> ForgeCapability`
  - `list_pull_requests(self, owner: str, repo: str, state: str = 'open') -> list[PullRequest]`
  - `create_pull_request(self, owner: str, repo: str, *, title: str, source_branch: str, target_branch: str, description: str = '') -> PullRequest`
  - `submit_review(self, owner: str, repo: str, number: int, *, action: str, body: str = '') -> None`
  - `get_ci_status(self, owner: str, repo: str, ref: str) -> CIStatus`
  - `list_issues(self, owner: str, repo: str, state: str = 'open') -> list[Issue]`
  - `get_pull_request(self, owner: str, repo: str, pr_id: str) -> PullRequest`
  - `get_issue(self, owner: str, repo: str, issue_id: str) -> Issue`
  - `get_avatar_url(self) -> str | None`

### `src/wrench/forge/adapters/github.py` (279 lines)
- `class GitHubAdapter(ForgeAdapter)` (L15)
  - `capabilities(self) -> ForgeCapability`
  - `list_pull_requests(self, owner: str, repo: str, state: str = 'open') -> list[PullRequest]`
  - `create_pull_request(self, owner: str, repo: str, *, title: str, source_branch: str, target_branch: str, description: str = '') -> PullRequest`
  - `submit_review(self, owner: str, repo: str, number: int, *, action: str, body: str = '') -> None`
  - `get_ci_status(self, owner: str, repo: str, ref: str) -> CIStatus`
  - `list_issues(self, owner: str, repo: str, state: str = 'open') -> list[Issue]`
  - `get_pull_request(self, owner: str, repo: str, pr_id: str) -> PullRequest`
  - `get_issue(self, owner: str, repo: str, issue_id: str) -> Issue`
  - `get_primary_email(self) -> str | None`
  - `get_avatar_url(self) -> str | None`

### `src/wrench/forge/adapters/gitlab.py` (254 lines)
- `class GitLabAdapter(ForgeAdapter)` (L12)
  - `capabilities(self) -> ForgeCapability`
  - `supported_review_actions(self) -> frozenset[str]`
  - `list_pull_requests(self, owner: str, repo: str, state: str = 'open') -> list[PullRequest]`
  - `create_pull_request(self, owner: str, repo: str, *, title: str, source_branch: str, target_branch: str, description: str = '') -> PullRequest`
  - `submit_review(self, owner: str, repo: str, number: int, *, action: str, body: str = '') -> None`
  - `get_ci_status(self, owner: str, repo: str, ref: str) -> CIStatus`
  - `list_issues(self, owner: str, repo: str, state: str = 'open') -> list[Issue]`
  - `get_pull_request(self, owner: str, repo: str, pr_id: str) -> PullRequest`
  - `get_issue(self, owner: str, repo: str, issue_id: str) -> Issue`
  - `get_avatar_url(self) -> str | None`

### `src/wrench/forge/capability.py` (303 lines)
- `class ForgeCapability(Flag)` (L26)
- `class ForgeAdapter(ABC)` (L34)
  - **Fields:** `provider_id: str; account: ForgeAccount`
  - `__init__(self, account: ForgeAccount) -> None`
  - `close(self) -> None`
  - `capabilities(self) -> ForgeCapability`
  - `supported_review_actions(self) -> frozenset[str]`
  - `authenticate(self) -> None`
  - `list_pull_requests(self, owner: str, repo: str, state: str = 'open') -> list[PullRequest]`
  - `create_pull_request(self, owner: str, repo: str, *, title: str, source_branch: str, target_branch: str, description: str = '') -> PullRequest`
  - `submit_review(self, owner: str, repo: str, number: int, *, action: str, body: str = '') -> None`
  - `get_ci_status(self, owner: str, repo: str, ref: str) -> CIStatus`
  - `list_issues(self, owner: str, repo: str, state: str = 'open') -> list[Issue]`
  - `get_pull_request(self, owner: str, repo: str, pr_id: str) -> PullRequest`
  - `get_issue(self, owner: str, repo: str, issue_id: str) -> Issue`
  - `get_primary_email(self) -> str | None`
  - `get_avatar_url(self) -> str | None`

### `src/wrench/forge/exceptions.py` (46 lines)
- `class ForgeError(Exception)` (L4)
- `class ForgeAdapterNotFoundError(ForgeError)` (L8)
  - `__init__(self, provider: str)`
- `class ForgeUnreachableError(ForgeError)` (L16)
  - `__init__(self, instance_url: str, cause: str)`
- `class ForgeAuthenticationError(ForgeError)` (L25)
- `class ForgeInsufficientScopeError(ForgeError)` (L29)
  - `__init__(self, message: str, *, scope_hint: str = '')`
- `class ForgeRateLimitedError(ForgeError)` (L37)
  - `__init__(self, retry_after_seconds: int)`
- `class ForgeCapabilityNotSupportedError(ForgeError)` (L45)

### `src/wrench/forge/models.py` (74 lines)
- `@dataclass class PullRequest` (L7)
  - **Fields:** `id: str; title: str; description: str; source_branch: str; target_branch: str; state: str; url: str; author: str; created_at: str; author_avatar_url: str | None = None`
- `@dataclass class Issue` (L23)
  - **Fields:** `id: str; title: str; description: str; state: str; url: str; author: str; created_at: str; author_avatar_url: str | None = None`
- `@dataclass class CIStatus` (L37)
  - **Fields:** `state: str; url: str | None = None; description: str | None = None`
- `@dataclass class RepoMetadata` (L46)
  - **Fields:** `owner: str; repo: str; default_branch: str; is_mirror: bool = False; mirror_source_url: str | None = None; is_readonly: bool = False; description: str | None = None`
- `@dataclass class ForgeAccount` (L59)
  - **Fields:** `id: int; provider: str; instance_url: str; label: str; username: str | None; secret_service_key: str; tls_ca_bundle_path: str | None = None; tls_insecure: bool = False`

### `src/wrench/forge/oauth/github_device_flow.py` (209 lines)
- `@dataclass class DeviceFlowCodes` (L22)
  - **Fields:** `device_code: str; user_code: str; verification_uri: str; interval: int; expires_in: int`
- `def request_device_code(client_id: str, scope: str = 'repo workflow', instance_url: str = 'https://github.com') -> DeviceFlowCodes` (L52)
- `def poll_for_token(client_id: str, device_code: str, interval: int, expires_in: int, cancel_event: threading.Event, instance_url: str = 'https://github.com') -> str` (L122)

### `src/wrench/forge/registry.py` (210 lines)
- `def discover_adapters() -> dict[str, type[ForgeAdapter]]` (L20)
- `def get_adapter_class(provider: str) -> type[ForgeAdapter]` (L49)
- `def is_forge_enabled(repo_path: str | None = None) -> bool` (L58)
- `def is_provider_enabled(provider: str, repo_path: str | None = None) -> bool` (L69)
- `def get_adapter_for_account(account: ForgeAccount, repo_path: str | None = None, check_enabled: bool = False) -> ForgeAdapter | None` (L82)
- `def clear_adapter_cache() -> None` (L100)
- `def close_avatar_http_client() -> None` (L136)
- `def fetch_avatar_bytes(url: str, headers: dict[str, str] | None = None, timeout: float = 10.0) -> bytes` (L158)

### `src/wrench/storage/__init__.py` (10 lines)
- `def get_connection(*args, **kwargs)` (L4)

### `src/wrench/storage/db.py` (111 lines)
- `def get_connection() -> sqlite3.Connection` (L17)
- `def run_migrations(conn: sqlite3.Connection) -> None` (L43)

### `src/wrench/storage/forge_accounts.py` (322 lines)
- `@dataclass class ForgeAccountRecord` (L17)
  - **Fields:** `id: int; provider: str; instance_url: str; label: str; username: str | None; created_at: str; tls_ca_bundle_path: str | None = None; tls_insecure: bool = False`
- `@dataclass class RepoForgeLink` (L31)
  - **Fields:** `repo_id: int; forge_account_id: int; remote_name: str; owner_slug: str; repo_slug: str`
- `def add_account(conn: sqlite3.Connection, provider: str, instance_url: str, label: str, username: str | None, token: str, *, tls_ca_bundle_path: str | None = None, tls_insecure: bool = False) -> int` (L39)
- `def list_accounts(conn: sqlite3.Connection, provider: str | None = None) -> list[ForgeAccountRecord]` (L91)
- `def get_account_secret_key(conn: sqlite3.Connection, account_id: int) -> str | None` (L121)
- `def get_account_full(conn: sqlite3.Connection, account_id: int) -> ForgeAccount | None` (L131)
- `def update_account(conn: sqlite3.Connection, account_id: int, *, label: str, username: str | None = None, tls_ca_bundle_path: str | None = None, tls_insecure: bool = False) -> None` (L155)
- `def update_username(conn: sqlite3.Connection, account_id: int, username: str) -> None` (L175)
- `def remove_account(conn: sqlite3.Connection, account_id: int) -> None` (L185)
- `def link_repo_to_account(conn: sqlite3.Connection, repo_id: int, forge_account_id: int, remote_name: str, owner_slug: str, repo_slug: str) -> None` (L205)
- `def unlink_repo_account(conn: sqlite3.Connection, repo_id: int, remote_name: str) -> None` (L228)
- `def get_link_for_remote(conn: sqlite3.Connection, repo_id: int, remote_name: str) -> RepoForgeLink | None` (L238)
- `def list_links_for_repo(conn: sqlite3.Connection, repo_id: int) -> list[RepoForgeLink]` (L260)
- `def find_link_by_path(conn: sqlite3.Connection, owner_slug: str, repo_slug: str, candidate_account_ids: list[int] | None = None) -> RepoForgeLink | None` (L282)
- `def get_remote_slug(conn: sqlite3.Connection, repo_id: int, remote_name: str) -> tuple[str, str] | None` (L316)

### `src/wrench/storage/health.py` (103 lines)
- `def check_database_health(conn: sqlite3.Connection) -> dict[str, Any]` (L17)
- `def repair_database(db_path: Path | str) -> sqlite3.Connection` (L46)
- `def garbage_collect_snapshots(repo_path: Path | str, conn: sqlite3.Connection) -> int` (L67)

### `src/wrench/storage/repo_registry.py` (159 lines)
- `@dataclass class RepoRecord` (L12)
  - **Fields:** `id: int; path: str; display_name: str; last_branch: str | None; last_opened_at: str | None; is_missing: bool; created_at: str`
- `def add_repo(conn: sqlite3.Connection, path: str, display_name: str | None = None) -> int` (L34)
- `def list_repos(conn: sqlite3.Connection) -> list[RepoRecord]` (L60)
- `def get_repo_by_path(conn: sqlite3.Connection, path: str) -> RepoRecord | None` (L69)
- `def get_repo_by_id(conn: sqlite3.Connection, repo_id: int) -> RepoRecord | None` (L75)
- `def remove_repo(conn: sqlite3.Connection, path_or_id: str | int) -> None` (L81)
- `def touch_repo(conn: sqlite3.Connection, path_or_id: str | int) -> None` (L91)
- `def update_last_opened(conn: sqlite3.Connection, path_or_id: str | int) -> None` (L108)
- `def update_last_branch(conn: sqlite3.Connection, path_or_id: str | int, branch: str) -> None` (L112)
- `def mark_missing(conn: sqlite3.Connection, path_or_id: str | int) -> None` (L127)
- `def clear_missing(conn: sqlite3.Connection, path_or_id: str | int) -> None` (L136)
- `def relocate_repo(conn: sqlite3.Connection, old_path_or_id: str | int, new_path: str) -> None` (L146)

### `src/wrench/storage/session_storage.py` (98 lines)
- `def save_session(conn: sqlite3.Connection, session_name: str, repo_paths: list[str] | tuple[str, ...], active_index: int = 0, tabs: list[dict[str, Any]] | tuple[dict[str, Any], ...] = ()) -> None` (L23)
- `def load_session(conn: sqlite3.Connection, session_name: str) -> WorkspaceSession | None` (L51)
- `def list_sessions(conn: sqlite3.Connection) -> list[str]` (L85)
- `def delete_session(conn: sqlite3.Connection, session_name: str) -> bool` (L91)

### `src/wrench/storage/settings.py` (103 lines)
- `def get_setting(conn: sqlite3.Connection, key: str) -> str | None` (L30)
- `def set_setting(conn: sqlite3.Connection, key: str, value: str) -> None` (L60)
- `def delete_setting(conn: sqlite3.Connection, key: str) -> None` (L86)

### `src/wrench/storage/settings_registry.py` (1857 lines)
- `class SettingType(str, Enum)` (L26)
- `class SettingScope(str, Enum)` (L34)
- `class SettingTier(str, Enum)` (L39)
- `@dataclass class SettingSpec` (L45)
  - **Fields:** `key: str; category: str; label: str; description: str; setting_type: SettingType; default: Any; scope: SettingScope = SettingScope.REPO_OVERRIDABLE; choices: tuple[str, ...] = (); min_value: int | None = None; max_value: int | None = None; parent_toggle_key: str | None = None; tier: SettingTier = SettingTier.ADVANCED; requires_restart: bool = False`
- `@dataclass class SettingDelta` (L62)
  - **Fields:** `change_id: int; timestamp: str; repo_path: str | None; key: str; old_value: Any; new_value: Any; undone: bool = False`
- `class SettingsRegistry(QObject)` (L1131)
  - **Signals:** `setting_changed = Signal(str, object, object)`
  - `__init__(self, conn: sqlite3.Connection | None = None) -> None`
  - `register(self, spec: SettingSpec) -> None`
  - `get_spec(self, key: str) -> SettingSpec | None`
  - `has_explicit_setting(self, key: str, repo_path: str | None = None) -> bool`
  - `list_specs(self, category: str | None = None) -> list[SettingSpec]`
  - `list_categories(self) -> list[str]`
  - `get(self, key: str, repo_path: str | None = None) -> Any`
  - `get_bool(self, key: str, repo_path: str | None = None) -> bool`
  - `is_enabled(self, key: str, repo_path: str | None = None) -> bool`
  - `get_int(self, key: str, repo_path: str | None = None) -> int`
  - `get_str(self, key: str, repo_path: str | None = None) -> str`
  - `set(self, key: str, value: Any, repo_path: str | None = None) -> None`
  - `set_value(self, key: str, value: Any, repo_path: str | None = None) -> None`
  - `reset_key(self, key: str, repo_path: str | None = None) -> None`
  - `reset_category(self, category: str, repo_path: str | None = None) -> None`
  - `reset_all(self, repo_path: str | None = None) -> None`
  - `undo_last_change(self) -> tuple[str, Any] | None`
  - `redo_last_change(self) -> tuple[str, Any] | None`
  - `list_recent_changes(self, limit: int = 50) -> list[SettingDelta]`
  - `revert_specific_change(self, change_id: int) -> None`
  - `apply_preset(self, preset_name: str, repo_path: str | None = None) -> None`
  - `apply_minimalist_local_only_preset(self, repo_path: str | None = None) -> None`
  - `export_json(self, file_path: str | Path) -> None`
  - `import_json(self, file_path: str | Path) -> None`
- `def peek_settings_registry() -> SettingsRegistry | None` (L1846)
- `def get_settings_registry(conn: sqlite3.Connection | None = None) -> SettingsRegistry` (L1851)

### `src/wrench/storage/snapshots.py` (116 lines)
- `@dataclass class SnapshotRecord` (L10)
  - **Fields:** `id: int; repo_id: int; ref_name: str; trigger_type: str; is_manual: bool; label: str | None; created_at: str; untracked_archive_path: str | None`
- `@dataclass class SnapshotSettingsRecord` (L22)
  - **Fields:** `repo_id: int; trigger_on_commit: bool; trigger_on_timer: bool; timer_interval_minutes: int; trigger_before_risky_op: bool; max_count: int; max_age_days: int | None; untracked_capture_mode: str; untracked_per_file_cap_mb: int; untracked_total_cap_mb: int`
- `def insert_snapshot(conn: sqlite3.Connection, *, repo_id: int, ref_name: str, trigger_type: str, is_manual: bool = False, label: str | None = None, untracked_archive_path: str | None = None) -> int` (L35)
- `def list_snapshots(conn: sqlite3.Connection, repo_id: int) -> list[SnapshotRecord]` (L56)
- `def delete_snapshot(conn: sqlite3.Connection, snapshot_id: int) -> None` (L77)
- `def get_snapshot_settings(conn: sqlite3.Connection, repo_id: int) -> SnapshotSettingsRecord | None` (L83)
- `def ensure_snapshot_settings(conn: sqlite3.Connection, repo_id: int) -> SnapshotSettingsRecord` (L104)

### `src/wrench/ui/changes_view.py` (407 lines)
- `class ZeroChangesLaunchpadWidget(QWidget)` (L192)
  - **Signals:** `sync_clicked = Signal(); terminal_clicked = Signal(); file_manager_clicked = Signal(); history_clicked = Signal(); command_palette_clicked = Signal()`
  - `cards(self) -> list[_LaunchpadActionCard]`
  - `quote_lbl(self) -> QLabel`
  - `__init__(self, parent: QWidget | None = None) -> None`
  - `update_sync_status(self, ahead: int, behind: int, upstream: str | None = None) -> None`
  - `refresh_quote(self) -> None`

### `src/wrench/ui/commit_graph/detail_panel.py` (498 lines)
- `class CommitDetailPanel(QWidget)` (L35)
  - `__init__(self, parent: QWidget | None = None)`
  - `set_compact_vertical_layout(self, enabled: bool) -> None`
  - `refresh_theme(self) -> None`
  - `set_repo(self, repo: RepoHandle | None)`
  - `refresh_avatar(self) -> None`
  - `set_commit(self, commit: Commit | None)`

### `src/wrench/ui/commit_graph/graph_widget.py` (1554 lines)
- `class GraphItemDelegate(QStyledItemDelegate)` (L76)
  - `__init__(self, parent: QWidget | None = None)`
- `class RefLabelDelegate(QStyledItemDelegate)` (L202)
  - `__init__(self, parent: QWidget | None = None)`
- `class CommitTableModel(QAbstractTableModel)` (L315)
  - `__init__(self, parent: QWidget | None = None)`
  - `set_three_column_mode(self, enabled: bool) -> None`
  - `max_active_lane(self) -> int`
  - `set_rows(self, rows: list[GraphRow])`
  - `append_rows(self, new_rows: list[GraphRow]) -> None`
- `class CommitGraphWidget(QTableView)` (L713)
  - **Signals:** `commit_selected = Signal(object); rebase_requested = Signal(str); interactive_rebase_requested = Signal(str); merge_requested = Signal(str); create_branch_requested = Signal(str); create_tag_requested = Signal(str); cherry_pick_to_worktree_requested = Signal(str, str); graph_scroll_changed = Signal(int, int)`
  - `__init__(self, parent: QWidget | None = None, *, settings_registry: SettingsRegistry | None = None)`
  - `set_three_column_mode(self, enabled: bool) -> None`
  - `select_and_scroll_to_commit(self, sha: str) -> bool`
  - `set_settings_registry(self, registry: SettingsRegistry | None) -> None`
  - `invalidate_paint_caches(self) -> None`
  - `remote_urls(self) -> list[str]`
  - `graph_scrollbar(self) -> QScrollBar`
  - `bind_horizontal_scrollbar(self, scrollbar: QScrollBar) -> None`
  - `scrollContentsBy(self, dx: int, dy: int) -> None`
  - `set_graph_scroll_x(self, val: int) -> None`
  - `set_repo(self, repo: RepoHandle | None)`
  - `set_all_refs_mode(self, all_refs: bool)`
  - `apply_filter(self, log_filter: LogFilter | None)`
  - `reload_commits(self)`

### `src/wrench/ui/commit_graph/layout.py` (242 lines)
- `class ConnectorKind(str, Enum)` (L16)
- `@dataclass class Lane` (L25)
  - **Fields:** `expected_sha: str | None; color: str; index: int`
- `@dataclass class Connector` (L32)
  - **Fields:** `from_lane: int; to_lane: int; color: str; kind: ConnectorKind = ConnectorKind.MERGE_UP`
- `@dataclass class GraphRow` (L40)
  - **Fields:** `commit: Commit; lane_index: int; active_lanes: list[int]; active_lane_colors: list[tuple[int, str]] = field(default_factory=list); node_color: str = GRAPH_COLORS[0]; has_top_rail: bool = False; connectors: list[Connector] = field(default_factory=list); ref_labels: list[RefLabel] = field(default_factory=list)`
- `@dataclass class GraphLayoutState` (L52)
  - **Fields:** `lanes: list[Lane | None] = field(default_factory=list); color_counter: int = 0`
- `def compute_graph_layout_step(commits: list[Commit], ref_labels: dict[str, list[RefLabel]] | None = None, state: GraphLayoutState | None = None) -> tuple[list[GraphRow], GraphLayoutState]` (L59)
- `def compute_graph_layout(commits: list[Commit], ref_labels: dict[str, list[RefLabel]] | None = None) -> list[GraphRow]` (L200)
- `def matches_filter(commit: Commit, log_filter: LogFilter | None, matching_shas: set[str] | None = None) -> bool` (L212)

### `src/wrench/ui/dialogs/about_dialog.py` (185 lines)
- `class AboutDialog(QDialog)` (L31)
  - `__init__(self, parent: QWidget | None = None)`
  - `done(self, result: int) -> None`

### `src/wrench/ui/dialogs/accounts_dialog.py` (1571 lines)
- `class AddAccountDialog(QDialog)` (L218)
  - `__init__(self, parent: QWidget | None = None, initial_page: int = 0, reauth_account_id: int | None = None) -> None`
  - `reject(self) -> None`
  - `done(self, result: int) -> None`
- `class EditAccountDialog(QDialog)` (L1137)
  - `__init__(self, record: forge_accounts.ForgeAccountRecord, parent: QWidget | None = None) -> None`
- `class AccountsDialog(QDialog)` (L1348)
  - `__init__(self, parent: QWidget | None = None) -> None`
  - `done(self, result: int) -> None`
  - `reload_accounts(self) -> None`

### `src/wrench/ui/dialogs/add_worktree_dialog.py` (337 lines)
- `class AddWorktreeDialog(QDialog)` (L33)
  - `__init__(self, engine: Any, settings: Any, repo_path: str, parent: QWidget | None = None) -> None`
  - `created_worktree(self) -> WorktreeInfo | None`

### `src/wrench/ui/dialogs/clone_dialog.py` (580 lines)
- `class CloneDialog(QDialog)` (L110)
  - `__init__(self, parent: QWidget | None = None, *, settings_registry: SettingsRegistry | None = None, conn: Any = None, initial_url: str = '', initial_dest_parent: str = '') -> None`
  - `done(self, result: int) -> None`
  - `set_filter_mode(self, mode: str) -> None`
  - `clone_url(self) -> str`
  - `dest_parent(self) -> str`
  - `repo_name(self) -> str`
  - `target_dest(self) -> str`
  - `filter_spec(self) -> str`
  - `sparse_enabled(self) -> bool`
  - `selected_account_id(self) -> int | None`

### `src/wrench/ui/dialogs/discover_repos_dialog.py` (108 lines)
- `class DiscoverReposDialog(QDialog)` (L18)
  - `__init__(self, repos: list[Path], root_dir: Path, parent: QWidget | None = None) -> None`
  - `selected_repositories(self) -> list[Path]`

### `src/wrench/ui/dialogs/interactive_rebase_dialog.py` (1087 lines)
- `class InteractiveRebaseDialog(QDialog)` (L318)
  - **Signals:** `rebase_started = Signal(); rebase_completed = Signal(object); rebase_failed = Signal(str)`
  - `__init__(self, repo: RepoHandle | Path | str, base_oid: str, parent: QWidget | None = None, *, settings_registry: SettingsRegistry | None = None) -> None`
  - `move_row(self, from_row: int, to_row: int) -> None`
  - `set_row_action(self, row: int, action: str) -> None`
  - `planned_entries(self) -> list[RebaseTodoEntry]`

### `src/wrench/ui/dialogs/link_dialog.py` (343 lines)
- `class LinkRepoDialog(QDialog)` (L32)
  - **Signals:** `links_changed = Signal()`
  - `__init__(self, repo_path: str, parent: QWidget | None = None, conn: Any = None) -> None`
  - `reload_data(self) -> None`

### `src/wrench/ui/dialogs/partial_staging_dialog.py` (180 lines)
- `class PartialStagingChoice(str, Enum)` (L24)
- `class PartialStagingDialog(QDialog)` (L30)
  - `__init__(self, file_paths: list[str], commit_message: str = '', parent: QWidget | None = None)`
  - `prompt(cls, parent: QWidget | None, file_paths: list[str], commit_message: str = '', default_choice: PartialStagingChoice | None = None) -> tuple[PartialStagingChoice, bool]`

### `src/wrench/ui/dialogs/push_recovery_dialogs.py` (542 lines)
- `class SecretScanningDialog(QDialog)` (L33)
  - `__init__(self, exc: SecretScanningRejectedError, parent = None) -> None`
- `class ProtectedBranchDialog(QDialog)` (L91)
  - `__init__(self, exc: ProtectedBranchRejectedError, default_new_branch: str = 'patch-1', parent = None) -> None`
  - `get_new_branch_name(self) -> str`
- `class FileTooLargeDialog(QDialog)` (L149)
  - `__init__(self, exc: FileTooLargeRejectedError, parent = None) -> None`
- `class PrePushLargeFilesDialog(QDialog)` (L203)
  - `__init__(self, large_blobs: list[tuple[str, float]], remote: str = 'origin', branch: str = 'main', parent = None) -> None`
- `class GitNetworkRecoveryDialog(QDialog)` (L340)
  - `__init__(self, exc: GitNetworkTransferError, remote_url: str | None = None, unpushed_large_blobs: list[tuple[str, float]] | None = None, has_multiple_commits: bool = False, parent = None) -> None`
  - `get_action(self) -> str`
  - `get_config_overrides(self) -> dict[str, str]`
  - `get_ssh_url(self) -> str | None`

### `src/wrench/ui/dialogs/remotes_dialog.py` (385 lines)
- `class AddRemoteDialog(QDialog)` (L48)
  - `__init__(self, parent: QWidget | None = None) -> None`
  - `get_remote_data(cls, parent: QWidget | None = None) -> tuple[str, str] | None`
- `class RemotesDialog(QDialog)` (L136)
  - **Signals:** `probe_finished = Signal()`
  - `__init__(self, repo: RepoHandle, parent: QWidget | None = None, *, db_conn: Any = None, auto_probe: bool = False) -> None`

### `src/wrench/ui/dialogs/settings_dialog.py` (1994 lines)
- `class SettingsPage(QWidget)` (L86)
  - `__init__(self, main_window: MainWindow, parent: QWidget | None = None) -> None`
  - `title(self) -> str`
  - `build(self) -> None`
  - `load(self) -> None`
- `class AppearancePage(SettingsPage)` (L105)
  - `title(self) -> str`
  - `build(self) -> None`
  - `load(self) -> None`
- `class TokenPreviewStrip(QWidget)` (L186)
  - `__init__(self, parent: QWidget | None = None) -> None`
- `class TabsPage(SettingsPage)` (L258)
  - `title(self) -> str`
  - `build(self) -> None`
  - `load(self) -> None`
- `class RepositoriesPage(SettingsPage)` (L299)
  - `title(self) -> str`
  - `build(self) -> None`
  - `load(self) -> None`
- `class SnapshotsPage(SettingsPage)` (L430)
  - `title(self) -> str`
  - `build(self) -> None`
  - `load(self) -> None`
- `class ForgePage(SettingsPage)` (L608)
  - `title(self) -> str`
  - `build(self) -> None`
  - `load(self) -> None`
- `class AdvancedPage(SettingsPage)` (L651)
  - `title(self) -> str`
  - `build(self) -> None`
  - `load(self) -> None`
- `class SettingsDialog(QDialog)` (L688)
  - `__init__(self, main_window: MainWindow | None = None, parent: QWidget | None = None, v1_compat: bool | None = None) -> None`
  - `has_pending_changes(self) -> bool`
  - `is_key_pending(self, key: str, repo_path: str | None = None) -> bool`
  - `get_effective_value(self, key: str, repo_path: str | None = None) -> Any`
  - `pending_requires_restart(self) -> bool`
  - `stage_change(self, key: str, val: Any, repo_path: str | None = None) -> None`
  - `apply_pending_changes(self) -> bool`
  - `select_category(self, category: str, highlight_key: str | None = None) -> None`
  - `pages(self) -> list[Any]`
  - `done(self, result: int) -> None`
- `class SettingRowWidget(QFrame)` (L1458)
  - `__init__(self, spec: SettingSpec, registry: SettingsRegistry, repo_path: str | None = None, parent: QWidget | None = None, on_changed: Callable[[str, Any], None] | None = None, on_stage: Callable[[str, Any, str | None], None] | None = None, value_getter: Callable[[str, str | None], Any] | None = None, is_pending_fn: Callable[[str, str | None], bool] | None = None) -> None`
  - `set_repo_path(self, repo_path: str | None) -> None`
  - `reload_value(self) -> None`
  - `update_parent_dependency(self) -> None`
  - `cancel_pending_timer(self) -> None`
  - `flush_pending(self) -> None`
  - `matches_query(self, query: str) -> bool`
- `class CategorySettingsPage(QWidget)` (L1855)
  - `__init__(self, category: str, registry: SettingsRegistry, repo_path: str | None = None, parent: QWidget | None = None, on_setting_changed: Callable[[str, Any], None] | None = None, on_stage: Callable[[str, Any, str | None], None] | None = None, value_getter: Callable[[str, str | None], Any] | None = None, is_pending_fn: Callable[[str, str | None], bool] | None = None) -> None`
  - `set_repo_path(self, repo_path: str | None) -> None`
  - `reload_all(self) -> None`
  - `reload_key(self, key: str) -> None`
  - `apply_theme(self) -> None`
  - `update_dependencies(self) -> None`
  - `filter_rows(self, query: str, modified_only: bool = False, view_tier: SettingTier = SettingTier.ADVANCED) -> int`

### `src/wrench/ui/dialogs/sparse_checkout_dialog.py` (875 lines)
- `class SparseCheckoutDialog(QDialog)` (L227)
  - **Signals:** `sparse_checkout_changed = Signal(); apply_failed = Signal(str); apply_started = Signal(); apply_finished = Signal(bool); apply_warning = Signal(str)`
  - `__init__(self, repo_path: Path | str, parent: QWidget | None = None, *, settings_registry: SettingsRegistry | None = None) -> None`
  - `done(self, result: int) -> None`
  - `selected_directories(self) -> list[str]`

### `src/wrench/ui/dialogs/submodule_dialog.py` (235 lines)
- `class SubmoduleDialog(QDialog)` (L31)
  - **Signals:** `submodules_changed = Signal()`
  - `__init__(self, repo: RepoHandle, parent: QWidget | None = None) -> None`
  - `refresh(self) -> None`

### `src/wrench/ui/diff_view/diff_widget.py` (465 lines)
- `class DiffWidget(QWidget)` (L43)
  - **Signals:** `file_staged = Signal(str, bool); hunk_staged = Signal(str, str); full_diff_requested = Signal()`
  - `__init__(self, parent: QWidget | None = None, *, settings_registry: SettingsRegistry | None = None)`
  - `set_settings_registry(self, registry: SettingsRegistry | None) -> None`
  - `set_repo(self, repo: RepoHandle | None)`
  - `set_file(self, path: str, *, staged: bool)`
  - `set_diff_model(self, diff: Diff, *, title: str = '', read_only: bool = True, reset_force: bool = True)`
  - `hunk_count(self) -> int`
  - `refresh(self)`
  - `refresh_theme(self) -> None`

### `src/wrench/ui/forge_panel/badges.py` (135 lines)
- `def paint_pr_state_badge(painter: QPainter, rect: QRect, state: str, is_dark: bool) -> None` (L16)
- `def paint_issue_state_badge(painter: QPainter, rect: QRect, state: str, is_dark: bool) -> None` (L47)
- `class PRStateBadge(QLabel)` (L52)
  - `__init__(self, state: str = 'open', parent = None)`
  - `set_state(self, state: str) -> None`
- `class IssueStateBadge(QLabel)` (L73)
  - `__init__(self, state: str = 'open', parent = None)`
  - `set_state(self, state: str) -> None`
- `class CIIconWidget(QLabel)` (L94)
  - `__init__(self, ci_status: CIStatus | None = None, parent = None)`
  - `set_status(self, ci_status: CIStatus | None) -> None`
- `class RemoteBadge(QLabel)` (L119)
  - `__init__(self, remote_name: str, provider: str, parent = None)`
  - `update_remote(self, remote_name: str, provider: str) -> None`

### `src/wrench/ui/forge_panel/create_pr_dialog.py` (169 lines)
- `class CreatePRDialog(QDialog)` (L22)
  - **Signals:** `pr_created = Signal(object)`
  - `__init__(self, adapter: ForgeAdapter, owner: str, repo: str, branches: list[str], current_branch: str, default_target_branch: str = 'main', parent = None)`

### `src/wrench/ui/forge_panel/error_banner.py` (155 lines)
- `class ForgeErrorBanner(QFrame)` (L24)
  - **Signals:** `action_requested = Signal(str)`
  - `__init__(self, parent = None)`
  - `show_error(self, exc: Exception) -> None`
  - `hide_banner(self) -> None`

### `src/wrench/ui/forge_panel/info_popover.py` (86 lines)
- `class InfoPopover(QFrame)` (L16)
  - `__init__(self, parent: QWidget | None = None) -> None`
  - `show_at(self, global_pos: QPoint, text: str) -> None`
- `class InfoButton(QToolButton)` (L59)
  - `__init__(self, tooltip_html: str, parent: QWidget | None = None) -> None`
  - `set_tooltip_html(self, html: str) -> None`

### `src/wrench/ui/forge_panel/review_dialog.py` (157 lines)
- `class SubmitReviewDialog(QDialog)` (L19)
  - **Signals:** `review_submitted = Signal()`
  - `__init__(self, adapter: ForgeAdapter, owner: str, repo: str, pr_number: int, parent = None)`

### `src/wrench/ui/history_view.py` (1046 lines)
- `class AvatarPixmapCache` (L88)
  - `__init__(self, maxsize: int = 128) -> None`
  - `clear(self) -> None`
  - `get_or_render(self, name: str, email: str, size: int, ring_color_hex: str, *, remote_urls: list[str] | None = None, db_conn: Any = None, is_dark: bool = True) -> QPixmap`
- `def clear_avatar_cache() -> None` (L208)
- `class CommitGraphRowDelegate(QStyledItemDelegate)` (L212)
  - `__init__(self, parent: QWidget | None = None) -> None`
- `class RefsSidebarWidget(QWidget)` (L532)
  - **Signals:** `ref_selected = Signal(str, str); branch_checkout_requested = Signal(str)`
  - `__init__(self, parent: QWidget | None = None) -> None`
  - `set_tree_data(self, tree_data: RefSidebarTree) -> None`
- `class CommitInspectorDock(QWidget)` (L693)
  - **Signals:** `parent_clicked = Signal(str)`
  - `__init__(self, parent: QWidget | None = None) -> None`
  - `set_repo(self, repo: RepoHandle | None) -> None`
  - `set_commit(self, commit: Commit | None) -> None`
- `class HistoryView(QWidget)` (L919)
  - `__init__(self, parent: QWidget | None = None, *, settings_registry: SettingsRegistry | None = None) -> None`
  - `set_repo(self, repo: RepoHandle | None) -> None`
  - `refresh(self) -> None`
  - `save_splitter_state(self) -> str`
  - `restore_splitter_state(self, hex_state: str) -> None`
  - `save_header_state(self) -> str`
  - `restore_header_state(self, hex_state: str) -> None`

### `src/wrench/ui/icons.py` (267 lines)
- `def list_available_icons() -> set[str]` (L226)
- `def get_pixmap(name: str, color: str = DEFAULT_ICON_COLOR, size: int = 16) -> QPixmap` (L235)
- `def get_icon(name: str, color: str = DEFAULT_ICON_COLOR, size: int = 16) -> QIcon` (L264)

### `src/wrench/ui/main_window.py` (4150 lines)
- `class MainWindow(QMainWindow)` (L220)
  - `__init__(self, conn: Any = None, parent = None)`
  - `moveEvent(self, event) -> None`
  - `restart_snapshot_timer(self) -> None`
  - `focus_active_settings_dialog(self) -> None`
  - `open_settings_at_category(self, category: str, highlight_key: str | None = None, parent_dialog: QWidget | None = None) -> None`
  - `request_restart(self) -> bool`

### `src/wrench/ui/merge_tool/merge_dialog.py` (274 lines)
- `class MergeDialog(QDialog)` (L37)
  - `__init__(self, repo: RepoHandle, file_path: str, *, mode: str = 'merge', parent: QWidget | None = None)`

### `src/wrench/ui/quotes.py` (121 lines)
- `def random_quote(bank: Sequence[str] | Sequence[tuple[str, str]]) -> str | tuple[str, str]` (L119)

### `src/wrench/ui/recovery/busy_dialog.py` (282 lines)
- `class BusyDialog(QDialog)` (L24)
  - **Signals:** `lock_released = Signal(); force_unlocked = Signal()`
  - `__init__(self, repo_path: Path | str, guard_result: GuardResult, parent: QWidget | None = None)`
  - `done(self, result: int) -> None`
- `class BusyOperationDialog(QDialog)` (L144)
  - `__init__(self, title: str, message: str, *, cancel_event: threading.Event | None = None, humor_enabled: bool = True, parent: QWidget | None = None)`
  - `set_progress(self, pct: int) -> None`
  - `update_message(self, message: str) -> None`
  - `done(self, result: int) -> None`

### `src/wrench/ui/recovery/recovery_dialog.py` (134 lines)
- `class RecoveryDialog(QDialog)` (L26)
  - **Signals:** `action_completed = Signal(str)`
  - `__init__(self, report: DiagnosticReport, repo_path: Path | str | None = None, context: dict | None = None, parent: QWidget | None = None)`

### `src/wrench/ui/snapshots_panel/snapshots_panel.py` (227 lines)
- `class SnapshotsPanel(QWidget)` (L33)
  - `__init__(self, conn: Any = None, parent: QWidget | None = None)`
  - `set_repo(self, repo: RepoHandle | None) -> None`
  - `refresh_if_visible(self) -> None`
  - `refresh(self) -> None`

### `src/wrench/ui/tabs/changes_tab.py` (1824 lines)
- `class FileListItemWidget(QWidget)` (L76)
  - **Signals:** `checked_changed = Signal(bool)`
  - `__init__(self, path: str, change_type: str, checked: bool = True, parent: QWidget | None = None, is_dark: bool | None = None)`
  - `refresh_theme(self) -> None`
  - `is_checked(self) -> bool`
  - `set_checked(self, checked: bool, emit_signal: bool = False) -> None`
- `class SelectAllCheckBox(QCheckBox)` (L173)
  - `nextCheckState(self) -> None`
- `class ChangedFilesList(QListWidget)` (L187)
- `class ChangesTab(QWidget)` (L209)
  - **Signals:** `repo_changed = Signal(str); state_changed = Signal(); open_repo_dialog_requested = Signal(); clone_repo_dialog_requested = Signal(); resolve_conflicts_requested = Signal(); forge_accounts_requested = Signal(); link_repo_requested = Signal(str)`
  - `__init__(self, conn: Any, parent: QWidget | None = None)`
  - `load_repos(self, select_path: str | None = None, *, auto_open: bool = True, opened_repo: RepoHandle | None = None) -> None`
  - `set_repo(self, repo: RepoHandle | None) -> None`
  - `refresh(self) -> None`
  - `show_forge_link_banner(self, owner: str, repo: str, repo_id: int, remote_name: str, on_link: Callable, on_dismiss: Callable) -> None`
  - `hide_forge_link_banner(self) -> None`
  - `refresh_theme(self) -> None`
  - `refresh_humor_setting(self) -> None`
  - `has_unsaved_commit_text(self) -> bool`
  - `get_current_repo_state(self) -> dict`
  - `restore_repo_state(self, state: dict) -> None`
  - `save_splitter_state(self) -> str`
  - `restore_splitter_state(self, hex_str: str) -> None`

### `src/wrench/ui/tabs/history_tab.py` (458 lines)
- `class HistoryTab(QWidget)` (L46)
  - **Signals:** `commit_hovered = Signal(str); commit_clicked = Signal(str); rebase_requested = Signal(str); interactive_rebase_requested = Signal(str); merge_requested = Signal(str); create_branch_requested = Signal(str); create_tag_requested = Signal(str); cherry_pick_to_worktree_requested = Signal(str, str)`
  - `__init__(self, parent: QWidget | None = None, *, settings_registry: SettingsRegistry | None = None)`
  - `set_settings_registry(self, registry: SettingsRegistry | None) -> None`
  - `graph_scrollbar(self) -> QScrollBar`
  - `set_repo(self, repo: RepoHandle | None) -> None`
  - `refresh(self, force: bool = False) -> None`
  - `clear_filters(self) -> None`
  - `save_header_state(self) -> str`
  - `restore_header_state(self, hex_str: str) -> None`
  - `save_splitter_state(self) -> str`
  - `restore_splitter_state(self, hex_str: str) -> None`
  - `refresh_theme(self) -> None`

### `src/wrench/ui/tabs/issue_detail_tab.py` (223 lines)
- `class IssueDetailTab(QWidget)` (L30)
  - `__init__(self, repo_path: str, remote_name: str, issue_id: str, parent = None)`
  - `set_active_repository(self, active_path: str) -> None`

### `src/wrench/ui/tabs/issue_list_tab.py` (443 lines)
- `class IssueStateDelegate(QStyledItemDelegate)` (L45)
- `class IssueTableModel(QAbstractTableModel)` (L57)
  - `__init__(self, parent = None)`
  - `set_issues(self, issues: list[Issue]) -> None`
  - `filter_items(self, search_text: str) -> None`
  - `get_issue_at(self, row: int) -> Issue | None`
- `class IssueListTab(QWidget)` (L139)
  - **Signals:** `issue_selected = Signal(str, str, str); link_requested = Signal(str)`
  - `__init__(self, repo_path: str, parent = None)`
  - `reload_links_and_data(self) -> None`
  - `load_issues(self, bypass_cache: bool = False) -> None`
  - `set_active_repository(self, active_path: str) -> None`

### `src/wrench/ui/tabs/pr_detail_tab.py` (338 lines)
- `class PRDetailTab(QWidget)` (L33)
  - **Signals:** `branch_checkout_requested = Signal(str)`
  - `__init__(self, repo_path: str, remote_name: str, pr_id: str, parent = None)`
  - `set_active_repository(self, active_path: str) -> None`

### `src/wrench/ui/tabs/pr_list_tab.py` (492 lines)
- `class PRStateDelegate(QStyledItemDelegate)` (L47)
- `class PRTableModel(QAbstractTableModel)` (L59)
  - `__init__(self, parent = None)`
  - `set_prs(self, prs: list[PullRequest]) -> None`
  - `filter_items(self, search_text: str) -> None`
  - `get_pr_at(self, row: int) -> PullRequest | None`
- `class PRListTab(QWidget)` (L147)
  - **Signals:** `pr_selected = Signal(str, str, str); link_requested = Signal(str)`
  - `__init__(self, repo_path: str, parent = None)`
  - `reload_links_and_data(self) -> None`
  - `load_prs(self, bypass_cache: bool = False) -> None`
  - `set_active_repository(self, active_path: str) -> None`

### `src/wrench/ui/tabs/tab_bar.py` (998 lines)
- `@dataclass class TabMetadata` (L51)
  - **Fields:** `widget: QWidget; label: str; icon: QIcon | None; tab_type: str; repo_path: str; entity_id: str | None = None; closable: bool = True; is_pinned: bool = False; factory: Callable[[], QWidget] | None = None; is_loaded: bool = True`
- `class TabButton(QWidget)` (L64)
  - **Signals:** `clicked = Signal(); close_requested = Signal(); pin_toggled = Signal(); close_others_requested = Signal(); close_right_requested = Signal()`
  - `__init__(self, label: str, icon: QIcon | None = None, closable: bool = True, is_pinned: bool = False, parent: QWidget | None = None)`
  - `refresh_theme(self) -> None`
  - `set_tab_index(self, index: int) -> None`
  - `set_label(self, label: str) -> None`
  - `set_pinned(self, pinned: bool) -> None`
  - `set_active(self, active: bool) -> None`
  - `set_orientation(self, orientation: Qt.Orientation) -> None`
- `class TabStripWidget(QWidget)` (L288)
  - `__init__(self, container: TabContainer, parent: QWidget | None = None)`
  - `dragEnterEvent(self, event) -> None`
  - `dragMoveEvent(self, event) -> None`
  - `dragLeaveEvent(self, event) -> None`
  - `dropEvent(self, event) -> None`
- `class TabLifecycle` (L420)
  - `tab_activated(self) -> None`
  - `tab_deactivated(self) -> None`
- `class SafeStackedWidget(QStackedWidget)` (L432)
  - `addWidget(self, widget: QWidget) -> int`
  - `insertWidget(self, index: int, widget: QWidget) -> int`
  - `removeWidget(self, widget: QWidget) -> None`
- `class TabContainer(QWidget)` (L469)
  - **Signals:** `current_changed = Signal(int); tab_closed = Signal(int); tabs_mutated = Signal(); orientation_changed = Signal(Qt.Orientation); add_category_tab_requested = Signal(str)`
  - `__init__(self, orientation: Qt.Orientation = Qt.Vertical, parent: QWidget | None = None)`
  - `move_tab(self, from_index: int, to_index: int) -> None`
  - `set_orientation(self, orientation: Qt.Orientation) -> None`
  - `orientation(self) -> Qt.Orientation`
  - `count(self) -> int`
  - `current_index(self) -> int`
  - `current_widget(self) -> QWidget | None`
  - `widget(self, index: int) -> QWidget | None`
  - `tab_metadata(self, index: int) -> TabMetadata | None`
  - `update_tab_repo_path(self, index: int, repo_path: str) -> None`
  - `find_tab(self, tab_type: str, repo_path: str, entity_id: str | None = None) -> int | None`
  - `add_tab(self, widget: QWidget | Callable[[], QWidget], label: str, icon: QIcon | None = None, tab_type: str = 'custom', repo_path: str = '', entity_id: str | None = None, closable: bool = True, is_pinned: bool = False, activate: bool = True) -> int`
  - `pin_tab(self, index: int) -> None`
  - `unpin_tab(self, index: int) -> None`
  - `toggle_pin(self, index: int) -> None`
  - `close_other_tabs(self, keep_index: int) -> None`
  - `close_tabs_to_right(self, index: int) -> None`
  - `remove_tab(self, index: int) -> None`
  - `clear_tabs(self) -> None`
  - `serialize_tabs(self) -> dict`
  - `set_current_index(self, index: int) -> None`
  - `ensure_loaded(self, index: int) -> QWidget | None`
  - `show_loading(self, repo_name: str) -> None`
  - `hide_loading(self) -> None`
  - `set_tab_label(self, index: int, label: str) -> None`
  - `refresh_theme(self) -> None`

### `src/wrench/ui/theme.py` (1151 lines)
- `def is_dark_theme(widget_or_palette: QWidget | QPalette | None = None) -> bool` (L26)
- `def create_pastel_light_palette() -> QPalette` (L133)
- `def create_pastel_dark_palette() -> QPalette` (L156)
- `def build_catppuccin_palette(theme_name: str = 'mocha') -> QPalette` (L179)
- `def get_global_catppuccin_qss(theme_name: str = 'mocha') -> str` (L239)
- `def normalize_theme_mode(mode: str | None, *, target: str = 'canonical') -> str` (L354)
- `def repolish_widget(widget: QWidget | None) -> None` (L362)
- `def apply_theme(app: QApplication, mode: str) -> None` (L379)
- `def get_badge_colors(change_type: str, is_dark: bool) -> tuple[str, str]` (L555)
- `def get_graph_lane_color(index: int, is_dark: bool) -> str` (L633)
- `def get_graph_lane_qcolor(index: int, is_dark: bool) -> QColor` (L639)
- `def get_ref_badge_color(kind: str, is_dark: bool) -> str` (L660)
- `def get_ref_badge_qcolor(kind: str, is_dark: bool) -> QColor` (L666)
- `def get_banner_style(level: str, is_dark: bool) -> dict[str, str]` (L689)
- `def get_remote_badge_colors(is_dark: bool) -> tuple[str, str]` (L725)
- `def get_info_popover_style(is_dark: bool) -> str` (L751)
- `def get_merge_mode_color(mode: str, is_dark: bool) -> str` (L771)
- `def get_secondary_button_style(is_dark: bool, *, compact: bool = False) -> str` (L833)
- `def get_icon_button_style(is_dark: bool, *, rounded: bool = False) -> str` (L867)
- `def get_status_pill_style(kind: str, is_dark: bool) -> dict[str, str]` (L896)
- `def get_tree_widget_qss(is_dark: bool) -> str` (L926)
- `def get_settings_badge_qss(is_dark: bool) -> str` (L945)
- `def get_signature_badge_qss(state: str, is_dark: bool) -> str` (L970)
- `def get_worktree_status_color(kind: str, is_dark: bool) -> str` (L993)
- `def get_remote_status_color(is_reachable: bool | None, is_dark: bool) -> QColor` (L1036)
- `def get_avatar_bg_color(identifier: str, is_dark: bool) -> str` (L1079)
- `def get_avatar_fg_color(is_dark: bool) -> str` (L1086)
- `def get_readonly_field_qss(is_dark: bool, *, placeholder: bool = False) -> str` (L1122)

### `src/wrench/ui/widgets/activity_log.py` (194 lines)
- `@dataclass class LogEntry` (L29)
  - **Fields:** `text: str; level: str; timestamp: float = field(default_factory=time.time)`
  - `time_str(self) -> str`
- `class ActivityLogModel(QObject)` (L39)
  - **Signals:** `entry_added = Signal(object)`
  - `__init__(self, maxlen: int = 200, parent: QObject | None = None)`
  - `entries(self) -> list[LogEntry]`
  - `set_maxlen(self, maxlen: int) -> None`
  - `post(self, text: str, level: str = 'info') -> None`
- `class ActivityLogBar(QWidget)` (L64)
  - `__init__(self, model: ActivityLogModel, parent: QWidget | None = None)`
  - `refresh_theme(self) -> None`
  - `set_max_lines(self, max_lines: int) -> None`

### `src/wrench/ui/widgets/avatar.py` (499 lines)
- `def clear_author_avatar_cache() -> None` (L37)
- `def resolve_author_avatar_url(name: str, email: str, remote_urls: list[str] | None = None, db_conn: Any = None) -> str | None` (L42)
- `def get_gravatar_url(email: str, size: int = 80) -> str` (L122)
- `def render_initials_tile(name_or_email: str, size: int = 40, is_dark: bool = False) -> QPixmap` (L144)
- `class AvatarLoader(QObject)` (L213)
  - **Signals:** `avatar_ready = Signal(str, int)`
  - `__init__(self, parent: QObject | None = None, *, max_cache_size: int = AVATAR_MEM_CACHE_MAX_SIZE) -> None`
  - `get_cached_avatar(self, url: str | None, size: int = 40) -> QPixmap | None`
  - `get_avatar(self, url: str | None, name_or_email: str, size: int = 40, is_dark: bool = False) -> QPixmap`
- `def get_avatar_loader() -> AvatarLoader` (L433)
- `class AvatarWidget(QLabel)` (L440)
  - `__init__(self, size: int = 40, parent: QWidget | None = None) -> None`
  - `set_avatar(self, url: str | None, name_or_email: str) -> None`

### `src/wrench/ui/widgets/branch_switcher.py` (431 lines)
- `class BranchPickerPopup(QDialog)` (L36)
  - **Signals:** `branch_selected = Signal(str)`
  - `__init__(self, repo: RepoHandle, current_branch: str | None, parent: QWidget | None = None)`
- `class BranchSwitcherWidget(QWidget)` (L126)
  - **Signals:** `branch_switched = Signal(str); branch_operation_completed = Signal()`
  - `__init__(self, parent: QWidget | None = None)`
  - `set_repo(self, repo: RepoHandle | None) -> None`
  - `refresh(self, status: RepoStatus | None = None) -> None`

### `src/wrench/ui/widgets/cli_preview_bar.py` (201 lines)
- `class CliCommandPreviewBar(QFrame)` (L28)
  - `__init__(self, parent: QWidget | None = None, *, settings_registry: SettingsRegistry | None = None, repo_path: Path | str | None = None) -> None`
  - `set_settings_registry(self, registry: SettingsRegistry | None) -> None`
  - `set_repo_path(self, repo_path: Path | str | None) -> None`
  - `set_command(self, command: str | Sequence[str]) -> None`
  - `preview_text(self) -> str`

### `src/wrench/ui/widgets/context_header_bar.py` (717 lines)
- `class RepoContextCell(QFrame)` (L53)
  - **Signals:** `clicked = Signal()`
  - `__init__(self, parent: QWidget | None = None) -> None`
  - `set_repo_name(self, name: str | None) -> None`
- `class BranchContextCell(QFrame)` (L108)
  - **Signals:** `clicked = Signal()`
  - `__init__(self, parent: QWidget | None = None) -> None`
  - `set_branch_sync(self, status: BranchSyncStatus) -> None`
- `class SyncActionCell(QFrame)` (L190)
  - **Signals:** `sync_requested = Signal(str)`
  - `__init__(self, parent: QWidget | None = None) -> None`
  - `set_sync_status(self, status: BranchSyncStatus) -> None`
- `class QuickActionsStrip(QWidget)` (L316)
  - **Signals:** `undo_clicked = Signal(); pull_clicked = Signal(); push_clicked = Signal(); stash_clicked = Signal(); pop_clicked = Signal(); terminal_toggled = Signal(); palette_clicked = Signal()`
  - `__init__(self, parent: QWidget | None = None) -> None`
  - `set_terminal_active(self, active: bool) -> None`
- `class ContextHeaderBar(QFrame)` (L400)
  - **Signals:** `repo_selector_clicked = Signal(); branch_selector_clicked = Signal(); sync_requested = Signal(str); fetch_requested = Signal(); sync_clicked = Signal(); fetch_clicked = Signal(); undo_clicked = Signal(); undo_requested = Signal(); pull_requested = Signal(); push_requested = Signal(); stash_requested = Signal(); pop_requested = Signal(); terminal_toggled = Signal(); terminal_clicked = Signal(); command_palette_requested = Signal()`
  - `__init__(self, parent: QWidget | None = None) -> None`
  - `repo_cell(self) -> RepoContextCell`
  - `branch_cell(self) -> BranchContextCell`
  - `sync_cell(self) -> SyncActionCell`
  - `quick_actions(self) -> QuickActionsStrip`
  - `set_repo_info(self, name: str | None, path: str | None = None) -> None`
  - `set_branch_sync_status(self, status: BranchSyncStatus) -> None`
  - `update_repo(self, repo: Any = None, branch_name: str | None = None, is_detached: bool = False) -> None`
  - `update_sync_status(self, status_or_ahead: BranchSyncStatus | int = 0, behind: int = 0, fetching: bool = False) -> None`
- `class GitTerminalDrawer(QFrame)` (L567)
  - **Signals:** `closed = Signal()`
  - `__init__(self, parent: QWidget | None = None) -> None`
  - `is_expanded(self) -> bool`
  - `toggle(self) -> None`
  - `toggle_drawer(self) -> None`
  - `set_command_runner(self, runner: Callable[[list[str]], tuple[int, str, str, float]] | None) -> None`
  - `append_log(self, text: str) -> None`
  - `clear_log(self) -> None`

### `src/wrench/ui/widgets/loading_overlay.py` (102 lines)
- `class SpinnerWidget(QWidget)` (L15)
  - `__init__(self, parent: QWidget | None = None, size: int = 32)`
- `class TabLoadingOverlay(QWidget)` (L62)
  - `__init__(self, parent: QWidget | None = None)`
  - `show_loading(self, repo_name: str) -> None`
  - `hide_loading(self) -> None`

### `src/wrench/ui/widgets/worktree_panel.py` (542 lines)
- `class SuppressTextDelegate(QStyledItemDelegate)` (L35)
- `class WorktreeCardWidget(QFrame)` (L44)
  - `__init__(self, wt: WorktreeInfo, on_open: Any, on_lock: Any = None, on_unlock: Any = None, on_remove: Any = None, parent: QWidget | None = None) -> None`
- `class WorktreePanel(QWidget)` (L185)
  - **Signals:** `open_worktree_requested = Signal(str); worktree_added = Signal(str); worktree_removed = Signal(str)`
  - `__init__(self, engine: Any, settings: Any, parent: QWidget | None = None) -> None`
  - `set_repo_path(self, repo_path: str | None) -> None`
  - `tab_activated(self) -> None`
  - `refresh(self) -> None`

### `src/wrench/ui/workers.py` (253 lines)
- `def set_activity_log(log: Any) -> None` (L21)
- `def clear_activity_log(expected_log: Any = None) -> None` (L27)
- `class GitOperationWorker(QObject)` (L102)
  - **Signals:** `finished = Signal(object); failed = Signal(Exception); progress = Signal(int)`
  - `__init__(self, fn: Callable[..., Any], *args: Any, cancel_event: threading.Event | None = None, **kwargs: Any)`
  - `run(self) -> None`
- `class WorkerThread(threading.Thread)` (L141)
  - `__init__(self, fn: Callable[..., Any], args: tuple[Any, ...], kwargs: dict[str, Any], op_name: str = '', on_finished: Callable[[Any], None] | None = None, on_failed: Callable[[Exception], None] | None = None, on_progress: Callable[[int], None] | None = None, cancel_event: threading.Event | None = None)`
  - `run(self) -> None`
  - `isRunning(self) -> bool`
  - `wait(self, timeout: float | None = None) -> bool`
  - `quit(self) -> None`
- `def wait_for_active_workers(timeout: float = 2.0) -> bool` (L220)
- `def run_in_background(fn: Callable[..., Any], *args: Any, op_name: str = '', on_finished: Callable[[Any], None] | None = None, on_failed: Callable[[Exception], None] | None = None, on_progress: Callable[[int], None] | None = None, cancel_event: threading.Event | None = None, **kwargs: Any) -> WorkerThread` (L230)

### `src/wrench/watcher/inotify_watcher.py` (667 lines)
- `def stop_all_active_watchers() -> None` (L214)
- `class RepoWatcher(QObject)` (L224)
  - **Signals:** `status_changed = Signal(); adaptive_fallback_activated = Signal(str, str)`
  - `__init__(self, repo_path: Path | str, on_change = None, parent = None, debounce_ms: int | None = None, settings_registry: SettingsRegistry | None = None)`
  - `status_info(self) -> WatcherStatusInfo`
  - `suspend(self) -> None`
  - `resume(self, grace_ms: int = 150) -> None`
  - `start(self) -> None`
  - `wait_until_ready(self, timeout: float = 3.0) -> bool`
  - `stop(self) -> None`

### `src/wrench/watcher/polling_fallback.py` (107 lines)
- `class PollingFallback(QObject)` (L18)
  - `__init__(self, repo_path: Path, signal: Signal, parent = None, interval_ms: int = 2000, git_dir: Path | None = None)`
  - `start(self) -> None`
  - `stop(self) -> None`
