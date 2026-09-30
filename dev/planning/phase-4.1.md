# Phase 4.1 Summary: Credential-Aware Clone & Open-Time Link Resolution

**Status:** Completed  
**Associated SRS Requirements:** FR-4.6, FR-5.13, NFR Concurrency & Reliability, NFR Performance  
**Associated Planning Documents:** [`implementation-plan.md`](file:///home/uzair/Projects/wrench/dev/planning/implementation-plan.md), [`srs.md`](file:///home/uzair/Projects/wrench/dev/planning/srs.md), [`phase-4.md`](file:///home/uzair/Projects/wrench/dev/planning/phase-4.md)

---

## 1. Overview & Objectives

Phase 4.1 delivered seamless credential integration and forge disambiguation across repository cloning and opening lifecycles:

1. **Shared Pure-Python Remote URL Parser (`src/wrench/core/remote_urls.py`)**:
   - Implemented `RemoteUrlParts` frozen dataclass (`protocol`, `host`, `owner`, `repo`).
   - Implemented `parse_remote_url(url: str) -> RemoteUrlParts | None` with zero exceptions raised on malformed input. Supports HTTPS/HTTP, SCP-style SSH (`git@host:owner/repo`), standard SSH URLs (`ssh://`), and local `file://`/bare paths.
   - Re-homed `host_of_instance_url(instance_url: str) -> str` from the credential helper, strictly preserving host normalization (lowercased, port-stripped).
   - Re-pointed `src/wrench/core/git_credential_helper.py` and `src/wrench/ui/dialogs/link_dialog.py` to use the shared parser.

2. **Clone-Time Credential Plumbing (`src/wrench/core/write_ops.py`)**:
   - Prepended `-c credential.helper=wrench -c credential.useHttpPath=true` to all `git clone` invocations before the `clone` command arguments.
   - Guaranteed credentials in Secret Service are usable during initial clone before local `.git/config` is written, without exposing tokens on the CLI or in environment variables.

3. **Multi-Account Clone Disambiguation & Pre-Creation Rollback (`src/wrench/ui/main_window.py`)**:
   - In `_on_clone_repo`, queries candidate accounts matching the clone target's host.
   - For 0 accounts: proceeds anonymously.
   - For 1 account: proceeds silently (unique host match).
   - For ≥2 accounts: displays an account disambiguation picker dialog.
   - Upon account selection, pre-creates the repository registry row and `repo_forge_links` row before the clone worker starts.
   - **Mandatory Rollback**: If the clone is canceled or fails, `repo_registry.remove_repo()` immediately removes the pre-created repository and cascades deletion to the link row.

4. **Open-Time Link Resolution (`src/wrench/ui/tabs/changes_tab.py` & `src/wrench/ui/main_window.py`)**:
   - Implemented `_maybe_offer_forge_link(repo_record)` on `MainWindow`, triggered in background after repository switch/open, before any auto-fetch.
   - For 1 matching account: silently links the repository and displays a transient status bar notification.
   - For ≥2 matching accounts: displays a non-modal warning banner inside the Changes tab ("Multiple forge accounts can reach {owner}/{repo} — [Link account…] [Dismiss]").
   - Dismissing the banner records a persistent marker in `app_settings` under `forge.link_declined` (`["{repo_id}:{remote_name}", ...]`) preventing repeated prompts.
   - Non-HTTPS and already-linked remotes are safely skipped.

---

## 2. Step 0 Reconciliation Results

Reconciliation performed against codebase prior to implementation:

| Grep / Target | Codebase Location & Findings |
|---|---|
| Clone / Open Funnels | `_on_clone_repo` and `_on_open_repo` located in `src/wrench/ui/main_window.py` |
| `clone_repo` Signature | `def clone_repo(url, dest, progress_cb=None, cancel_event=None)` in `src/wrench/core/write_ops.py` (both progress and cancel event present) |
| Picker Dialog Class | Located `LinkRepoDialog` and `AccountsDialog` in `src/wrench/ui/dialogs/`; modal account selection dialog integrated into `_on_clone_repo` |
| `_host_of` in Helper | `_host_of` in `src/wrench/core/git_credential_helper.py` extracted to `remote_urls.host_of_instance_url` |
| Error Routing | `_route_remote_error` in `src/wrench/ui/main_window.py` handling `AuthRequiredError`, `AuthFailedError`, `MergeRequiredError`, etc. |
| Repo Changed Seam | `_on_repo_changed` in `src/wrench/ui/main_window.py` hooks active repository transitions |

---

## 3. Test Matrix & Verification

### Unit & UI Tests
- `tests/unit/core/test_remote_urls.py`: 23 test cases covering full URL parsing matrix (HTTPS, HTTP, SCP, SSH, file, bare paths, port stripping, error resilience).
- `tests/unit/core/test_git_credential_helper.py`: 11 test cases confirming helper behavior unchanged following `_host_of` re-homing.
- `tests/unit/core/test_write_ops_remotes.py`: 30 test cases verifying `-c credential.helper=wrench` and `-c credential.useHttpPath=true` arg injection.
- `tests/ui/test_clone_picker.py`: 6 UI tests validating multi-account picker behavior, cancellation, pre-creation, rollback on error, and SSH bypass.
- `tests/ui/test_forge_link_resolution.py`: 8 UI tests validating single-account silent linking, multi-account non-modal banner, dismiss decline persistence, and link dialog opening.

### Full CI Gate Verification
```bash
./bin/wrench-lint
# Checking ruff linting... All checks passed!
# Checking black formatting... All done! 153 files left unchanged.

./bin/wrench-ci-check
# 438 passed in 17.94s (100% green, 0 failures)
```
