# Wrench Auto-Generated Core API Symbol Map (`dev/REPO_MAP_CORE.md`)

> Generated from `src/wrench/` at git HEAD `552ab29` by
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
- **General & UI:** `ui.theme_mode` (`'system'`), `ui.font_size_pt` (`10`), `ui.confirm_destructive_actions` (`True`), `ui.avatars_gravatar` (`False`), `ui.session_state` (`True`), `ui.humor_lines` (`True`), `ui.activity_dock.max_lines` (`500`), `ui.show_cli_preview_in_dialogs` (`True`), `workspace.restore_session_on_startup` (`True`), `ui.settings_view_mode` (`'normal'`), `repo.recent_max_count` (`20`), `repo.auto_discovery.enabled` (`True`), `help.tooltip_mode` (`'beginner_rich'`), `help.tooltip_delay_ms` (`500`), `ui.history_three_column_layout` (`True`), `ui.show_context_header_bar` (`True`), `ui.show_empty_state_launchpad` (`True`)
- **Hooks & Signing:** `hooks.enabled` (`True`), `signing.enabled` (`False`), `signing.verify_badges_in_graph.enabled` (`True`)
- **Remotes & LFS:** `remote.auto_fetch.enabled` (`True`), `remote.auto_fetch.interval_seconds` (`180`), `remote.pull_default_mode` (`'ff-only'`), `remote.force_push_mode` (`'force-with-lease'`), `remote.prune_on_fetch` (`True`), `lfs.enabled` (`True`), `clone.default_filter_mode` (`'none'`)
- **Safety & Backups:** `safety.commit_partially_staged_mode` (`'prompt'`), `safety.auto_stage_hook_modifications` (`True`), `safety.precommit_tool_search_paths` (`True`), `safety.pre_op_snapshot.enabled` (`True`), `safety.scheduled_backups.enabled` (`False`), `safety.op_log_undo_enabled` (`True`), `stash.ui.enabled` (`True`), `stash.confirm_before_drop` (`True`), `desktop.system_tray.enabled` (`True`)
- **Staging & Commits:** `staging.line_staging.enabled` (`True`), `commit.subject_max_length_guide` (`50`), `commit.body_wrap_column` (`72`), `commit.auto_stage_all_if_empty` (`False`), `commit.undo_button.enabled` (`True`)
- **Watcher & Performance:** `watcher.inotify.enabled` (`True`), `watcher.debounce_ms` (`300`), `watcher.refresh_on_window_focus` (`True`), `watcher.lock_recovery_prompt.enabled` (`True`), `performance.worker_thread_count` (`4`), `performance.max_diff_file_size_kb` (`2048`), `watcher.monorepo_adaptive_fallback.enabled` (`True`), `performance.graph_page_size` (`500`), `maintenance.auto_commit_graph.enabled` (`True`)
- **Worktrees & Submodules:** `worktrees.enabled` (`True`), `worktrees.bare_hub.enabled` (`True`), `submodules.enabled` (`True`), `submodules.auto_init` (`True`), `monorepo.sparse_checkout_ui.enabled` (`True`)

---

## 2. Public Modules, Dataclasses, Signals & Signatures

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

### `src/wrench/core/engine.py` (2087 lines)
- `@dataclass class FileChange` (L43)
  - **Fields:** `path: str; change_type: str; old_path: str | None = None; is_partially_staged: bool = False`
  - `status_code(self) -> str`
- `@dataclass class FileStatusInfo` (L56)
  - **Fields:** `path: str; staged_code: str; unstaged_code: str; is_partially_staged: bool; is_untracked: bool = False; staged_hunks_count: int = 0; unstaged_hunks_count: int = 0`
  - `composite_badge(self) -> str`
- `@dataclass class RepoStatus` (L76)
  - **Fields:** `staged: list[FileChange]; unstaged: list[FileChange]; untracked: list[str]; current_branch: str | None; is_detached: bool; ahead: int; behind: int; has_conflicts: bool; detached_head_sha: str | None = None; head_sha: str | None = None; merge_in_progress: bool = False; rebase_in_progress: bool = False; partially_staged: list[FileChange] = field(default_factory=list)`
  - `branch_name(self) -> str | None`
  - `is_detached_head(self) -> bool`
  - `partially_staged_paths(self) -> set[str]`
- `@dataclass class FileStat` (L105)
  - **Fields:** `path: str; change_type: str; additions: int; deletions: int`
- `@dataclass class RefLabel` (L115)
  - **Fields:** `name: str; kind: str`
- `@dataclass class Commit` (L123)
  - **Fields:** `sha: str; message: str; author_name: str; author_email: str; author_date: str; parent_shas: list[str]; refs: list[RefName] = field(default_factory=list)`
  - `author(self) -> str`
  - `hex(self) -> str`
- `@dataclass class BlameLine` (L142)
  - **Fields:** `line_no: int; commit_sha: str; author: str; line_content: str`
- `@dataclass class DiffLine` (L150)
  - **Fields:** `content: str; origin: str; old_lineno: int | None; new_lineno: int | None`
- `@dataclass class Hunk` (L158)
  - **Fields:** `id: str; old_start: int; old_count: int; new_start: int; new_count: int; lines: list[DiffLine]`
- `@dataclass class Diff` (L168)
  - **Fields:** `path: str; is_binary: bool; hunks: list[Hunk]; is_truncated: bool = False; total_lines: int = 0; truncated_reason: str | None = None`
- `@dataclass class MergeResult` (L178)
  - **Fields:** `status: str; commit_sha: str | None = None; conflicted_files: list[str] = field(default_factory=list)`
- `@dataclass class RebaseResult` (L185)
  - **Fields:** `status: str; conflicted_files: list[str] = field(default_factory=list)`
- `@dataclass class Remote` (L191)
  - **Fields:** `name: str; url: str`
- `@dataclass class ReflogEntry` (L197)
  - **Fields:** `sha: str; message: str; timestamp: str`
- `@dataclass class Submodule` (L204)
  - **Fields:** `path: str; url: str; initialized: bool`
- `@dataclass class SubmoduleStatus` (L211)
  - **Fields:** `path: str; current_commit: str; is_dirty: bool`
- `@dataclass class LogFilter` (L218)
  - **Fields:** `author: str | None = None; message_substring: str | None = None; date_from: str | None = None; date_to: str | None = None; path: str | None = None`
- `@dataclass class CloneResult` (L227)
  - **Fields:** `path: Path`
- `@dataclass class RemoteInfo` (L234)
  - **Fields:** `name: str; url: str; last_fetch_at: str | None = None; is_reachable: bool | None = None`
  - `fetch_url(self) -> str`
- `class RepoHandle` (L247)
  - `__init__(self, pygit2_repo: pygit2.Repository | str | Path, path: Path | str | None = None)`
  - `reload(self) -> None`
- `def init_repo(path: Path | str) -> RepoHandle` (L320)
- `def clone_repo(url: str, dest: Path | str, *, progress_cb = None, cancel_event = None, branch: str | None = None, recursive: bool = False, filter_spec: str | None = None, sparse: bool = False) -> CloneResult` (L326)
- `def open_repo(path: Path | str, *, configure_credentials: bool = True) -> RepoHandle` (L353)
- `def get_status(repo: RepoHandle) -> RepoStatus` (L386)
- `def get_diff(repo: RepoHandle, path: str, *, staged: bool, max_lines: int | None = None, max_bytes: int | None = None) -> Diff` (L390)
- `def get_log(repo: RepoHandle, filter: LogFilter | None = None, *, limit: int = 100, offset: int = 0, all_refs: bool = False) -> list[Commit]` (L407)
- `def get_log_page(repo: RepoHandle, filter: LogFilter | None = None, *, limit: int = 500, cursor_sha: str | None = None, all_refs: bool = False) -> LogPage` (L418)
- `def iter_commits(repo: RepoHandle, *, all_refs: bool = False)` (L435)
- `def get_commit_diff(repo: RepoHandle, sha: str, path: str | None = None, *, max_lines: int | None = None, max_bytes: int | None = None) -> Diff` (L439)
- `def get_commit_file_stats(repo: RepoHandle, sha: str) -> list[FileStat]` (L456)
- `def get_ref_labels(repo: RepoHandle) -> dict[str, list[RefLabel]]` (L460)
- `def get_repo_refs_signature(repo: RepoHandle) -> tuple[str, bool, bool, str, str, str] | None` (L464)
- `def blame(repo: RepoHandle, path: str) -> list[BlameLine]` (L470)
- `def stage_file(repo: RepoHandle, path: str) -> None` (L474)
- `def unstage_file(repo: RepoHandle, path: str) -> None` (L488)
- `def stage_hunk(repo: RepoHandle, path: str, hunk_id: str) -> None` (L502)
- `def stage_lines(repo: RepoHandle, path: str, line_numbers: list[int]) -> None` (L521)
- `def commit(repo: RepoHandle, message: str, *, amend: bool = False) -> str` (L605)
- `def list_branches(repo: RepoHandle, *, local: bool | None = None, remote: bool | None = None, include_remote: bool = False) -> list[str]` (L611)
- `def create_branch(repo: RepoHandle, name: str, *, from_ref: str = 'HEAD') -> None` (L644)
- `def switch_branch(repo: RepoHandle, name: str) -> None` (L648)
- `def delete_branch(repo: RepoHandle, name: str, *, force: bool = False) -> None` (L653)
- `def rename_branch(repo: RepoHandle, old: str, new: str) -> None` (L660)
- `def discard_file(repo: RepoHandle, path: str) -> None` (L664)
- `def stash_create(repo: RepoHandle, message: str | None = None) -> str` (L670)
- `def stash_pop(repo: RepoHandle, stash_id: str | int = 0) -> None` (L676)
- `def stash_apply(repo: RepoHandle, stash_id: str) -> None` (L681)
- `def stash_drop(repo: RepoHandle, stash_id: str) -> None` (L686)
- `def check_identity(repo_or_path: RepoHandle | Path | str) -> tuple[str, str]` (L690)
- `def set_identity(repo_or_path: RepoHandle | Path | str, name: str, email: str) -> None` (L695)
- `def get_reflog(repo: RepoHandle) -> list[ReflogEntry]` (L700)
- `def restore_to_ref(repo: RepoHandle, sha: str) -> None` (L704)
- `def push(repo: RepoHandle, remote: str, branch: str, *, force: bool = False, extra_config: dict[str, str] | None = None, timeout: float = 1800.0, progress_cb = None, cancel_event = None) -> None` (L708)
- `def push_incremental_batches(repo: RepoHandle, remote: str, branch: str, *, chunk_size: int = 20, force: bool = False, extra_config: dict[str, str] | None = None, progress_cb = None, cancel_event = None) -> None` (L731)
- `def pull(repo: RepoHandle, remote: str, branch: str, *, progress_cb = None, cancel_event = None) -> None` (L754)
- `def fetch(repo: RepoHandle, remote: str, *, db_conn = None, progress_cb = None, cancel_event = None) -> None` (L771)
- `def list_remotes(repo: RepoHandle, *, db_conn: sqlite3.Connection | None = None) -> list[RemoteInfo]` (L816)
- `def probe_remotes_async(repo: RepoHandle, *, db_conn: sqlite3.Connection | None = None, on_complete: Callable[[], None] | None = None) -> threading.Thread` (L918)
- `def add_remote(repo: RepoHandle, name: str, url: str, *, db_conn: sqlite3.Connection | None = None) -> None` (L943)
- `def remove_remote(repo: RepoHandle, name: str) -> None` (L970)
- `def set_remote_url(repo: RepoHandle, name: str, url: str) -> None` (L979)
- `def get_remote_url(repo: RepoHandle, name: str) -> str` (L991)
- `def count_unpushed_commits(repo: RepoHandle, remote: str, branch: str) -> int` (L999)
- `def merge(repo: RepoHandle, source_branch: str) -> MergeResult` (L1012)
- `def merge_abort(repo: RepoHandle) -> None` (L1016)
- `def rebase(repo: RepoHandle, onto: str) -> RebaseResult` (L1021)
- `def rebase_continue(repo: RepoHandle) -> RebaseResult` (L1025)
- `def rebase_abort(repo: RepoHandle) -> None` (L1029)
- `def create_tag(repo: RepoHandle, name: str, target: str = 'HEAD') -> None` (L1034)
- `def check_repo_guard(repo: RepoHandle, timeout: float = 3.0)` (L1039)
- `def sweep_repo_debris(repo: RepoHandle) -> list[str]` (L1045)
- `def get_git_config(repo: RepoHandle | Path | str | None, key: str, scope: str = 'local') -> str | None` (L1052)
- `def set_git_config(repo: RepoHandle | Path | str | None, key: str, value: str, scope: str = 'local') -> None` (L1077)
- `def get_http_post_buffer(repo: RepoHandle | Path | str | None = None, scope: str = 'local') -> int | None` (L1096)
- `def set_http_post_buffer(repo: RepoHandle | Path | str | None, buffer_bytes: int, scope: str = 'local') -> None` (L1110)
- `def get_http_version(repo: RepoHandle | Path | str | None = None, scope: str = 'local') -> str | None` (L1119)
- `def set_http_version(repo: RepoHandle | Path | str | None, version: str, scope: str = 'local') -> None` (L1127)
- `def scan_unpushed_large_blobs(repo: RepoHandle, remote: str = 'origin', branch: str | None = None, threshold_mb: float = 50.0) -> list[tuple[str, float]]` (L1149)
- `class GitEngine` (L1225)
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
  - `list_branches(self, *, local: bool | None = None, remote: bool | None = None, include_remote: bool = False, repo: RepoHandle | None = None) -> list[str]`
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
  - `run_terminal_command(self, subcommand_args: list[str] | str, repo: RepoHandle | Path | str | None = None) -> tuple[int, str, str, float]`
  - `run_git_terminal_command(self, subcommand_args: list[str] | str, repo: RepoHandle | Path | str | None = None) -> tuple[int, str, str, float]`
- `def run_git_terminal_command(repo_path: Path | str, subcommand_args: list[str] | str, timeout: float = 15.0) -> tuple[int, str, str, float]` (L1832)
- `def get_branch_sync_status(repo: RepoHandle | Path | str) -> BranchSyncStatus` (L1896)
- `def get_ref_sidebar_tree(repo: RepoHandle | Path | str) -> RefSidebarTree` (L1902)
- `def get_commit(repo: RepoHandle | Path | str, sha: str) -> Commit | None` (L1908)
- `def get_commit_details(repo: RepoHandle | Path | str, sha: str) -> Commit | None` (L1914)
- `def is_unborn_repo(repo_path: Path | str) -> bool` (L1920)
- `def refresh_repo_handle(repo: RepoHandle | None) -> None` (L1928)
- `def is_sparse_checkout_enabled(repo_path: Path | str) -> bool` (L1938)
- `def get_sparse_checkout_state(repo_path: Path | str) -> SparseCheckoutState` (L1942)
- `def init_sparse_checkout(repo_path: Path | str, cone: bool = True) -> None` (L1946)
- `def list_sparse_directories(repo_path: Path | str) -> list[str]` (L1950)
- `def set_sparse_directories(repo_path: Path | str, dirs: list[str], *, cone: bool = True, warnings_out: list[str] | None = None) -> None` (L1954)
- `def disable_sparse_checkout(repo_path: Path | str, *, warnings_out: list[str] | None = None) -> None` (L1969)
- `def list_head_top_directories(repo_path: Path | str, max_depth: int = 2) -> list[str]` (L1977)
- `def list_tree_subdirectories(repo_path: Path | str, parent_rel_path: str = '') -> list[TreeDirectoryEntry]` (L1981)
- `def write_commit_graph(repo_path: Path | str, *, reachable: bool = True, changed_paths: bool = True, timeout: int = 120) -> CommitGraphStats` (L1988)
- `def maybe_write_commit_graph(repo_path: Path | str, settings_registry: Any = None) -> CommitGraphStats` (L2003)
- `def build_interactive_rebase_cli_args(base_oid: str, *, autostash: bool = True, autosquash: bool = True) -> list[str]` (L2018)
- `def get_interactive_rebase_target_label(repo: RepoHandle | Path | str, base_oid: str) -> tuple[str, str, bool]` (L2031)
- `def list_commits_for_interactive_rebase_checked(repo: RepoHandle | Path | str, base_oid: str, *, limit: int = 1000) -> tuple[list[RebaseTodoEntry], bool]` (L2039)
- `def list_commits_for_interactive_rebase(repo: RepoHandle | Path | str, base_oid: str, *, limit: int = 1000) -> list[RebaseTodoEntry]` (L2053)
- `def interactive_rebase(repo: RepoHandle, base_oid: str, entries: list[RebaseTodoEntry], *, autostash: bool = True, autosquash: bool = True, conn: sqlite3.Connection | None = None) -> RebaseResult` (L2067)

### `src/wrench/core/exceptions.py` (345 lines)
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

### `src/wrench/core/models.py` (376 lines)
- `@dataclass class FileChange` (L9)
  - **Fields:** `path: str; change_type: str; old_path: str | None = None; is_partially_staged: bool = False`
  - `status_code(self) -> str`
- `@dataclass class FileStatusInfo` (L22)
  - **Fields:** `path: str; staged_code: str; unstaged_code: str; is_partially_staged: bool; is_untracked: bool = False; staged_hunks_count: int = 0; unstaged_hunks_count: int = 0`
  - `composite_badge(self) -> str`
- `@dataclass class RepoStatus` (L42)
  - **Fields:** `staged: list[FileChange]; unstaged: list[FileChange]; untracked: list[str]; current_branch: str | None; is_detached: bool; ahead: int; behind: int; has_conflicts: bool; detached_head_sha: str | None = None; head_sha: str | None = None; merge_in_progress: bool = False; rebase_in_progress: bool = False; partially_staged: list[FileChange] = field(default_factory=list)`
  - `partially_staged_paths(self) -> set[str]`
  - `branch_name(self) -> str | None`
  - `is_detached_head(self) -> bool`
- `@dataclass class FileStat` (L71)
  - **Fields:** `path: str; change_type: str; additions: int; deletions: int`
- `class RefName(str)` (L80)
- `@dataclass class RefLabel` (L96)
  - **Fields:** `name: str; kind: str`
- `@dataclass class Commit` (L104)
  - **Fields:** `sha: str; message: str; author_name: str; author_email: str; author_date: str; parent_shas: list[str]; refs: list[RefName] = field(default_factory=list)`
  - `author(self) -> str`
  - `hex(self) -> str`
- `@dataclass class BlameLine` (L123)
  - **Fields:** `line_no: int; commit_sha: str; author: str; line_content: str`
- `@dataclass class DiffLine` (L131)
  - **Fields:** `content: str; origin: str; old_lineno: int | None; new_lineno: int | None`
- `@dataclass class Hunk` (L139)
  - **Fields:** `id: str; old_start: int; old_count: int; new_start: int; new_count: int; lines: list[DiffLine]`
- `@dataclass class Diff` (L149)
  - **Fields:** `path: str; is_binary: bool; hunks: list[Hunk]; is_truncated: bool = False; total_lines: int = 0; truncated_reason: str | None = None`
- `@dataclass class MergeResult` (L159)
  - **Fields:** `status: str; commit_sha: str | None = None; conflicted_files: list[str] = field(default_factory=list)`
- `@dataclass class RebaseResult` (L166)
  - **Fields:** `status: str; conflicted_files: list[str] = field(default_factory=list)`
- `@dataclass class Remote` (L172)
  - **Fields:** `name: str; url: str`
- `@dataclass class ReflogEntry` (L178)
  - **Fields:** `sha: str; message: str; timestamp: str`
- `@dataclass class Submodule` (L185)
  - **Fields:** `path: str; url: str; initialized: bool`
- `@dataclass class SubmoduleStatus` (L192)
  - **Fields:** `path: str; current_commit: str; is_dirty: bool`
- `@dataclass class LogFilter` (L199)
  - **Fields:** `author: str | None = None; message_substring: str | None = None; date_from: str | None = None; date_to: str | None = None; path: str | None = None`
- `@dataclass class CloneResult` (L208)
  - **Fields:** `path: Path`
- `@dataclass class RemoteInfo` (L215)
  - **Fields:** `name: str; url: str; last_fetch_at: str | None = None; is_reachable: bool | None = None`
  - `fetch_url(self) -> str`
- `@dataclass class LfsFileStatus` (L229)
  - **Fields:** `path: str; is_pointer: bool; oid: str | None = None; size: int | None = None; is_locked: bool = False; locked_by: str | None = None`
- `@dataclass class LFSLock` (L241)
  - **Fields:** `lock_id: str; path: str; owner: str`
- `@dataclass class BundleInfo` (L250)
  - **Fields:** `path: Path; is_valid: bool; prerequisites: list[str] = field(default_factory=list); references: list[str] = field(default_factory=list)`
- `@dataclass class SparseCheckoutState` (L260)
  - **Fields:** `enabled: bool; cone_mode: bool; directories: tuple[str, ...]; partial_filter: str | None = None`
- `@dataclass class TreeDirectoryEntry` (L270)
  - **Fields:** `name: str; rel_path: str; has_children: bool; is_selected: bool = False`
- `@dataclass class LogPage` (L280)
  - **Fields:** `commits: tuple[Commit, ...]; next_cursor_sha: str | None; has_more: bool; scanned_count: int = 0`
- `@dataclass class CommitGraphStats` (L290)
  - **Fields:** `written: bool; duration_ms: int; skipped_reason: str | None = None; graph_file_size_bytes: int = 0`
- `@dataclass class WatcherStatusInfo` (L300)
  - **Fields:** `mode: str; is_fallback: bool; watched_paths: tuple[str, ...]; reason: str | None = None`
- `@dataclass class RebaseTodoEntry` (L310)
  - **Fields:** `action: str; oid: str; short_oid: str; summary: str; author: str; new_message: str | None = None`
- `@dataclass class BranchInfo` (L327)
  - **Fields:** `name: str; is_head: bool; upstream_name: str | None = None; ahead: int = 0; behind: int = 0; target_oid: str = ''`
- `@dataclass class TagInfo` (L339)
  - **Fields:** `name: str; target_oid: str; message: str | None = None; tagger_date: str | None = None`
- `@dataclass class StashEntry` (L349)
  - **Fields:** `index: int; message: str; oid: str; timestamp: str | None = None`
- `@dataclass class BranchSyncStatus` (L359)
  - **Fields:** `branch_name: str; upstream_name: str | None; ahead: int = 0; behind: int = 0; is_detached: bool = False`
- `@dataclass class RefSidebarTree` (L370)
  - **Fields:** `local_branches: tuple[BranchInfo, ...] = (); remote_branches: tuple[BranchInfo, ...] = (); tags: tuple[TagInfo, ...] = (); stashes: tuple[StashEntry, ...] = ()`

### `src/wrench/core/paths.py` (61 lines)
- `def data_dir() -> Path` (L12)
- `def config_dir() -> Path` (L17)
- `def state_dir() -> Path` (L22)
- `def cache_dir() -> Path` (L27)
- `def resolve_git_dir(repo_path: Path | str) -> Path` (L32)

### `src/wrench/core/read_ops.py` (1743 lines)
- `def configure_libgit2_cache_limits(*, force: bool = False) -> None` (L225)
- `def configure_libgit2_memory_limits(max_cache_mb: int = 32) -> None` (L242)
- `def get_status(repo: RepoHandle) -> RepoStatus` (L249)
- `def get_diff(repo: RepoHandle, path: str, *, staged: bool, max_lines: int | None = None, max_bytes: int | None = None) -> Diff` (L788)
- `def get_commit_diff(repo: RepoHandle, sha: str, path: str | None = None, *, max_lines: int | None = None, max_bytes: int | None = None) -> Diff` (L980)
- `def get_commit_file_stats(repo: RepoHandle, sha: str) -> list[FileStat]` (L1030)
- `def get_ref_labels(repo: RepoHandle) -> dict[str, list[RefLabel]]` (L1081)
- `def iter_commits(repo: RepoHandle, *, all_refs: bool = False) -> Iterator[Commit]` (L1148)
- `def get_log_page(repo: RepoHandle, filter: LogFilter | None = None, *, limit: int = 500, cursor_sha: str | None = None, all_refs: bool = False) -> LogPage` (L1319)
- `def get_log(repo: RepoHandle, filter: LogFilter | None = None, *, limit: int = 100, offset: int = 0, all_refs: bool = False) -> list[Commit]` (L1424)
- `def get_commit(repo: RepoHandle | Path | str, sha: str) -> Commit | None` (L1472)
- `def get_commit_details(repo: RepoHandle | Path | str, sha: str) -> Commit | None` (L1487)
- `def blame_file(repo: RepoHandle, path: str) -> list[BlameLine]` (L1492)
- `def get_repo_refs_signature(repo: RepoHandle) -> tuple[str, bool, bool, str, str, str] | None` (L1527)
- `def get_branch_sync_status(repo_path: Path | str) -> BranchSyncStatus` (L1586)
- `def get_ref_sidebar_tree(repo_path: Path | str) -> RefSidebarTree` (L1650)

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

### `src/wrench/storage/db.py` (96 lines)
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

### `src/wrench/storage/settings.py` (103 lines)
- `def get_setting(conn: sqlite3.Connection, key: str) -> str | None` (L30)
- `def set_setting(conn: sqlite3.Connection, key: str, value: str) -> None` (L60)
- `def delete_setting(conn: sqlite3.Connection, key: str) -> None` (L86)

### `src/wrench/storage/settings_registry.py` (1769 lines)
- `class SettingType(str, Enum)` (L26)
- `class SettingScope(str, Enum)` (L34)
- `class SettingTier(str, Enum)` (L39)
- `@dataclass class SettingSpec` (L45)
  - **Fields:** `key: str; category: str; label: str; description: str; setting_type: SettingType; default: Any; scope: SettingScope = SettingScope.REPO_OVERRIDABLE; choices: tuple[str, ...] = (); min_value: int | None = None; max_value: int | None = None; parent_toggle_key: str | None = None; tier: SettingTier = SettingTier.ADVANCED; requires_restart: bool = False`
- `@dataclass class SettingDelta` (L62)
  - **Fields:** `change_id: int; timestamp: str; repo_path: str | None; key: str; old_value: Any; new_value: Any; undone: bool = False`
- `class SettingsRegistry(QObject)` (L1043)
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
- `def peek_settings_registry() -> SettingsRegistry | None` (L1758)
- `def get_settings_registry(conn: sqlite3.Connection | None = None) -> SettingsRegistry` (L1763)

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

### `src/wrench/ui/icons.py` (267 lines)
- `def list_available_icons() -> set[str]` (L226)
- `def get_pixmap(name: str, color: str = DEFAULT_ICON_COLOR, size: int = 16) -> QPixmap` (L235)
- `def get_icon(name: str, color: str = DEFAULT_ICON_COLOR, size: int = 16) -> QIcon` (L264)

### `src/wrench/ui/main_window.py` (3772 lines)
- `class MainWindow(QMainWindow)` (L219)
  - `__init__(self, conn: Any = None, parent = None)`
  - `moveEvent(self, event) -> None`
  - `restart_snapshot_timer(self) -> None`
  - `focus_active_settings_dialog(self) -> None`
  - `open_settings_at_category(self, category: str, highlight_key: str | None = None, parent_dialog: QWidget | None = None) -> None`
  - `request_restart(self) -> bool`

### `src/wrench/ui/theme.py` (1106 lines)
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
- `def get_remote_status_color(is_reachable: bool | None, is_dark: bool) -> QColor` (L991)
- `def get_avatar_bg_color(identifier: str, is_dark: bool) -> str` (L1034)
- `def get_avatar_fg_color(is_dark: bool) -> str` (L1041)
- `def get_readonly_field_qss(is_dark: bool, *, placeholder: bool = False) -> str` (L1077)

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
