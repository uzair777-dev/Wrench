# Phase 4 Summary: Forge Integration Layer

**Status:** Completed  
**Associated SRS Requirements:** FR-5.1 – FR-5.9, NFR Concurrency & Reliability, NFR Performance, NFR Accessibility, NFR Localization  
**Associated Planning Documents:** [`implementation-plan.md`](file:///home/uzair/Projects/wrench/dev/planning/implementation-plan.md), [`srs.md`](file:///home/uzair/Projects/wrench/dev/planning/srs.md), [`ui-planning.md`](file:///home/uzair/Projects/wrench/dev/planning/ui-planning.md), [`ARCHITECTURE.md`](file:///home/uzair/Projects/wrench/ARCHITECTURE.md)

---

## 1. Overview & Objectives

Phase 4 delivered the comprehensive Forge Integration Layer for Wrench, providing first-class, multi-provider git forge support across GitHub, GitLab, Forgejo/Gitea, and Bitbucket Cloud:

1. **Normalized Data Models & Typed Exception Taxonomy (`src/wrench/forge/`)**:
   - Implemented standard domain models (`PullRequest`, `Issue`, `CIStatus`, `ForgeAccount`) with strict state vocabulary normalizations:
     - `PullRequest.state` $\in$ `{"open", "merged", "closed"}`
     - `Issue.state` $\in$ `{"open", "closed"}`
     - `CIStatus.state` $\in$ `{"success", "failure", "pending", "unknown"}`
   - Built a 6-tier typed exception hierarchy (`ForgeError`, `ForgeAuthenticationError`, `ForgeInsufficientScopeError`, `ForgeRateLimitedError`, `ForgeUnreachableError`, `ForgeNotFoundError`) providing precise diagnostic recovery hints.

2. **Abstract Capability & Adapter Base (`ForgeAdapter`)**:
   - Defined capability flags (`ForgeCapability.PULL_REQUESTS`, `ISSUES`, `CI_STATUS`, `ISSUE_LINKING`, `REVIEWS`).
   - Implemented a unified `httpx` HTTP transport layer inside `ForgeAdapter`:
     - Uniform header construction and token resolution from Secret Service.
     - Per-account TLS trust policies (`tls_ca_bundle_path`, `tls_insecure` with diagnostic warning logging).
     - Centralized status-code-to-exception mapping (401 $\to$ `ForgeAuthenticationError`, 403 $\to$ `ForgeInsufficientScopeError` with provider scope hints, 429 $\to$ `ForgeRateLimitedError` with `Retry-After`).
     - Standardized pagination helper (`_paged_get`) with a 10-page (500-item) runaway guard.
     - Core API contracts: `authenticate()`, `list_pull_requests()`, `get_pull_request()`, `create_pull_request()`, `list_issues()`, `get_issue()`, `get_ci_status()`, `submit_review()`.

3. **Pluggable Discovery & Registry (`src/wrench/forge/registry.py`)**:
   - Registered all four forge adapters via Python `entry-points` (`[project.entry-points."wrench.forge_adapters"]`).
   - Memoized adapter discovery with duplicate `provider_id` collision detection to fail loud on conflicts.
   - Account-to-adapter factory (`get_adapter_for_account`) binding account configurations and tokens.

4. **Multi-Account Storage & Link CRUD (`src/wrench/storage/forge_accounts.py`)**:
   - Atomic two-step insert-then-update for `add_account()`: generates a temporary pending key, updates with row id (`wrench:forge:{id}`), stores secret in Secret Service, and cascades deletion on rollback if secret storage fails.
   - Full link management: `link_repo_to_account()`, `get_link_for_remote()`, `get_remote_slug()`, and fast-path credential helper lookup `find_link_by_path()`.

5. **Four Production Forge Adapters (`src/wrench/forge/adapters/`)**:
   - **GitHub Adapter (`github.py`)**: REST v3 (`api.github.com` & GitHub Enterprise Server), `Authorization: Bearer`, PR/Issue filtering on `/issues`, combined status + check-runs CI, and full review submission (`APPROVE`, `REQUEST_CHANGES`, `COMMENT`).
   - **GitLab Adapter (`gitlab.py`)**: REST v4 (`gitlab.com` & self-hosted), `PRIVATE-TOKEN`, MR $\leftrightarrow$ PR vocabulary mapping, pipeline CI status, self-approval 401 trap translation, and narrowed review actions (`approve`, `comment`).
   - **Forgejo / Gitea Adapter (`forgejo.py`)**: REST v1 (`/api/v1`), token auth, review event past-tense mapping (`APPROVED`), combined commit status CI.
   - **Bitbucket Cloud Adapter (`bitbucket.py`)**: REST 2.0 (`api.bitbucket.org/2.0`), HTTP Basic Auth with Atlassian email and API token, state normalization (`OPEN`, `MERGED`, `DECLINED`, `SUPERSEDED`), `next` full-URL pagination, commit statuses CI, and multi-endpoint review actions.

6. **Forge UI Surface & Dynamic Tab Navigation (`src/wrench/ui/tabs/` & `src/wrench/ui/forge_panel/`)**:
   - **`PRListTab` & `IssueListTab`**: Singleton tabs per repository; searchable/filterable table views, SWR cache (60s TTL), load-generation request invalidation, "Create Pull Request" dialog, and double-click detail tab spawning.
   - **`PRDetailTab` & `IssueDetailTab`**: Dynamic entity tabs; single-entity direct fetching via `get_pull_request()` and `get_issue()`, CI status card, in-app review submission (`SubmitReviewDialog`), local branch checkout, "Open in Browser" action, and stale repository warning banner.
   - **Badges & Visuals**: Catppuccin velvet pastel status pills (`PRStateBadge`, `IssueStateBadge`), CI status indicators (`CIIconWidget`), and remote badges (`RemoteBadge`).

7. **Multi-Account Manager & Disambiguation Linking (FR-5.6, FR-5.8, FR-5.9)**:
   - **`AccountsDialog`**: Multi-account management table; test-before-save authentication validation, TLS bundle/skip-verification configuration, token replacement, and cascading unlink confirmations.
   - **Account Disambiguation & Linking**: One-time prompt dialog when multiple accounts share a host (e.g., Work GitHub vs. Personal GitHub); configures local repo `credential.useHttpPath = true`.

8. **Worker Concurrency Architecture & Deadlock Elimination**:
   - Decoupled `run_in_background` from `QThread` event loops, `moveToThread()`, and cross-thread `deleteLater()`.
   - Built a lightweight Python daemon thread runner (`WorkerThread`) and thread-safe queued `_Dispatcher(QObject)` on the Qt main thread, completely eliminating the Python GIL / Qt `signalSlotLock` deadlock and `SIGABRT` crashes.

9. **Repository Switching Synchronization**:
   - Implemented `set_active_repository()` across `PRListTab`, `IssueListTab`, `PRDetailTab`, and `IssueDetailTab`.
   - Wired `TabContainer.update_tab_repo_path()` and `MainWindow._on_repo_changed()` to guarantee tab contents update cleanly when switching active repositories.

10. **Assisted GitHub OAuth Setup & Extended Scope Support (RFC 8628)**:
    - Native Device Authorization Flow (`src/wrench/forge/oauth/github_device_flow.py`) with countdown timer, polling interval backoff (`slow_down`), browser launching, and code copy buttons.
    - Expanded default scope from `"repo"` to `"repo workflow user:email read:org"`, ensuring tokens can manage workflows, verify author identity, and access org resources.
    - Customizable scope picker in `AccountsDialog`: Full Access vs. Public Repositories Only presets, plus expandable Advanced Scopes (`workflow`, `user:email`, `read:org`).
    - In-place re-authorization: Added "Re-authorize…" actions in `AccountsDialog` and `EditAccountDialog` that update existing Secret Service credentials while preserving `repo_forge_links`.

11. **Granular Push Error Classification & Dedicated Recovery Dialogs**:
    - Built comprehensive server-side push rejection classification in `src/wrench/core/write_ops.py` converting opaque stderr messages into typed domain exceptions:
      - `WorkflowScopeRequiredError`: Missing `workflow` OAuth scope when pushing `.github/workflows/`.
      - `SecretScanningRejectedError` (`GH007`): Push blocked due to detected credentials/secrets.
      - `ProtectedBranchRejectedError` (`GH006`): Direct push rejected by branch protection rules.
      - `FileTooLargeRejectedError` (`GH001`): File exceeds 100MB repository quota.
      - `SignedCommitsRequiredError` (`GH008`): Branch requires GPG/SSH signed commits.
      - `RepoPermissionDeniedError` (`403`): Write access denied on remote repository.
    - Specialized recovery dialogs in `src/wrench/ui/dialogs/push_recovery_dialogs.py`:
      - `SecretScanningDialog`: Displays detected secret type and file location with direct 1-click external unblock URL button.
      - `ProtectedBranchDialog`: Guided 1-click creation of a new branch (`patch-1` / `patch-{branch}`) with automated checkout and push.
      - `FileTooLargeDialog`: Displays file size, limits, and recommendations for `git rm --cached` or Git LFS.
      - Targeted messages for signed commits (GPG/SSH commit signing guidance) and permission denials.

12. **Auto-Aligned Local Identity**:
    - Added `adapter.get_primary_email()` across `ForgeAdapter` and `GitHubAdapter` (querying `/user/emails` for verified primary email).
    - Integrated background author identity synchronization into `LinkRepoDialog`: linking a repository to a forge account automatically updates `.git/config` `user.name` and `user.email` to match the authenticated forge profile.

---

## 2. Implemented Components & Architecture

### 2.1 Domain Models & Exceptions (`src/wrench/forge/`)

- **`models.py`**:
  - `PullRequest(id, title, description, source_branch, target_branch, state, url, author, created_at)`
  - `Issue(id, title, description, state, url, author, created_at)`
  - `CIStatus(state, url, description)`
  - `ForgeAccount(id, provider, instance_url, label, username, secret_service_key, tls_ca_bundle_path, tls_insecure)`
- **`exceptions.py`**:
  - `ForgeError`: Base exception for all forge operations.
  - `ForgeAuthenticationError`: Raised on HTTP 401 when tokens are expired or revoked.
  - `ForgeInsufficientScopeError`: Raised on HTTP 403, storing `scope_hint` describing required token permissions.
  - `ForgeRateLimitedError`: Raised on HTTP 429, storing `retry_after_seconds` (parsed from `Retry-After` header or defaulting to 60s).
  - `ForgeUnreachableError`: Raised on connection failure, DNS resolution failure, or timeout.
  - `ForgeNotFoundError`: Raised on HTTP 404 when repositories, PRs, or issues do not exist.

### 2.2 Capability Base & Shared Transport (`src/wrench/forge/capability.py`)

- **`ForgeCapability`**: Bitwise flags for granular feature gating (`PULL_REQUESTS`, `ISSUES`, `CI_STATUS`, `ISSUE_LINKING`, `REVIEWS`).
- **`ForgeAdapter(ABC)`**:
  - Encapsulates `httpx.Client` with timeout configuration (`connect=10s, read=30s, write=10s, pool=10s`).
  - Configures TLS verification: `False` if `account.tls_insecure` (with warning logger), custom CA bundle path if `account.tls_ca_bundle_path`, or system trust store.
  - Standardized `_request(method, path, *, json=None, params=None)` handling auth injection, exception translation, and error body truncation.
  - Pagination helper `_paged_get(path, params, *, per_page=50, max_pages=10)` concatenating results with a 500-item safeguard against runaway loops.
  - Core interface contracts:
    - `authenticate() -> None`
    - `list_pull_requests(owner: str, repo: str, state: str = "open") -> list[PullRequest]`
    - `get_pull_request(owner: str, repo: str, pr_id: str) -> PullRequest`
    - `create_pull_request(owner: str, repo: str, *, title: str, source_branch: str, target_branch: str, description: str = "") -> PullRequest`
    - `list_issues(owner: str, repo: str, state: str = "open") -> list[Issue]`
    - `get_issue(owner: str, repo: str, issue_id: str) -> Issue`
    - `get_ci_status(owner: str, repo: str, ref: str) -> CIStatus`
    - `submit_review(owner: str, repo: str, number: int, *, action: str, body: str = "") -> None`
    - `get_primary_email() -> str | None`: Fetches verified primary email of authenticated user (default returns `None`, overridden in provider adapters).
  - Property `supported_review_actions`: Default `frozenset({"approve", "request_changes", "comment"})`.

### 2.3 Provider Adapters (`src/wrench/forge/adapters/`)

- **`GitHubAdapter` (`github.py`)**:
  - Base URL: `https://api.github.com` (Cloud) or `{instance_url}/api/v3` (Enterprise).
  - Auth: `Authorization: Bearer {token}`.
  - Filtered `/issues`: Discards items with a `pull_request` key to prevent duplicate PR entries.
  - CI Status: Queries `/repos/{owner}/{repo}/commits/{ref}/status` combined status, falling back to `/check-runs`.
  - Review Actions: Maps directly to `APPROVE`, `REQUEST_CHANGES`, `COMMENT`.
  - Primary Email Resolution: Queries `/user/emails` endpoint (requiring `user:email` scope) for verified primary email, falling back to any verified email.
- **`GitLabAdapter` (`gitlab.py`)**:
  - Base URL: `{instance_url}/api/v4`.
  - Auth: `PRIVATE-TOKEN: {token}`.
  - URL Slug: Quotes owner and repository as `{owner}%2F{repo}`.
  - State Mapping: Normalizes GitLab states (`opened` $\to$ `open`, `merged` $\to$ `merged`, `closed` $\to$ `closed`).
  - CI Status: Queries `/projects/{slug}/pipelines?sha={ref}` (maps `canceled` and `skipped` to `unknown`).
  - Review Actions: Overrides `supported_review_actions` to `{"approve", "comment"}`. Traps self-approval 401 error and surfaces actionable `ForgeError("You cannot approve your own merge request.")`.
- **`ForgejoAdapter` (`forgejo.py`)**:
  - Base URL: `{instance_url}/api/v1`.
  - Auth: `Authorization: token {token}`.
  - Review Actions: Critical mapping of normalized `'approve'` to past-tense `'APPROVED'`.
  - CI Status: Queries `/repos/{owner}/{repo}/commits/{ref}/status`.
- **`BitbucketAdapter` (`bitbucket.py`)**:
  - Base URL: `https://api.bitbucket.org/2.0`.
  - Auth: HTTP Basic Auth using Atlassian account email as `username` and API token as `password`.
  - State Mapping: Normalizes PR states (`OPEN` $\to$ `open`, `MERGED` $\to$ `merged`, `DECLINED`/`SUPERSEDED` $\to$ `closed`) and Issue states (`new`/`open` $\to$ `open`, other $\to$ `closed`).
  - Review Actions: Routes to separate endpoints `/pullrequests/{id}/approve`, `/request-changes`, and `/comments` with `{"content": {"raw": body}}`.

### 2.4 Multi-Account Storage & Link CRUD (`src/wrench/storage/forge_accounts.py`)

- **Atomic Key Generation (`add_account`)**:
  1. Inserts account with temporary key `wrench:forge:pending:{uuid}` to satisfy SQLite constraints.
  2. Updates `secret_service_key` with permanent identifier `wrench:forge:{new_id}`.
  3. Stores token in Secret Service backend under `wrench:forge:{new_id}`.
  4. Automatically rolls back (deletes SQLite row) if Secret Service fails, preventing orphaned account records.
- **Account Queries & Removal**:
  - `list_accounts(conn, provider=None)`: Lists configured accounts.
  - `get_account_full(conn, account_id)`: Fetches account including `secret_service_key` strictly for adapter instantiation.
  - `remove_account(conn, account_id)`: Deletes database row (cascading across foreign keys) and best-effort deletes secret from keyring.
- **Remote Linking**:
  - `link_repo_to_account(conn, repo_id, forge_account_id, remote_name, owner_slug, repo_slug)`: Upserts on `(repo_id, remote_name)`.
  - `get_link_for_remote(conn, repo_id, remote_name)`: Retrieves active link for a given repository and remote.
  - `get_remote_slug(conn, repo_id, remote_name)`: Returns `(owner_slug, repo_slug)` tuple.
  - `find_link_by_path(conn, owner_slug, repo_slug)`: Supports fast path-based resolution for `git-credential-wrench`.

### 2.5 UI Tabs & Dialogs (`src/wrench/ui/tabs/` & `src/wrench/ui/dialogs/`)

- **`PRListTab` & `IssueListTab`**:
  - Identified by deduplication key `(tab_type, repo_path)`.
  - Remote selector combo dynamically populates from repository remotes.
  - Search/filter input bar with instant filtering.
  - SWR cache: Returns cached items within 60 seconds unless explicitly refreshed or filtered.
  - Load-generation counter: Discards stale in-flight network responses when switching remotes or repos.
  - `CreatePRDialog`: Modal form for title, description, source branch, and target branch.
  - Double-click row emission opening dynamic entity detail tabs.
- **`PRDetailTab` & `IssueDetailTab`**:
  - Keyed by `(tab_type, repo_path, entity_id)`.
  - Direct retrieval via `adapter.get_pull_request(owner, repo, pr_id)` and `adapter.get_issue(owner, repo, issue_id)`.
  - CI Status card with "View Build" link button.
  - `SubmitReviewDialog`: Modal review submission for Approve, Request Changes, or Comment.
  - Branch Checkout: Checks out branch or sets up a local tracking branch.
  - External Browser navigation via `QDesktopServices.openUrl()`.
  - Stale repository banner displayed when the parent MainWindow changes to another repository.
- **`AccountsDialog` (`src/wrench/ui/dialogs/accounts_dialog.py`)**:
  - Manage configured accounts (Add, Edit, Re-authorize, Remove, Replace Token).
  - **Assisted Setup (Device Flow RFC 8628)**: In-app browser authorization for GitHub and GitHub Enterprise Server requesting `repo workflow user:email read:org` permissions.
  - **Scope Picker UI**: Preset radio buttons ("Full Access" vs. "Public Repositories Only") and collapsible "Advanced Scopes" toggle (`QToolButton` + `advanced_scopes_widget`) exposing checkboxes for `workflow`, `user:email`, and `read:org`.
  - **In-Place Re-authorization**: Re-authorizing an account seamlessly updates the token in the OS Secret Service without generating duplicate account rows or severing dependent repository links (`repo_forge_links`).
  - Validation before persistence: Tests `authenticate()` asynchronously before writing rows or credentials.
  - Advanced TLS configuration: Custom CA bundle (PEM) file picker and explicit skip TLS verification option with security warning.
  - Deletion confirmation warning showing cascading repository link removals.
- **Push Recovery Dialogs (`src/wrench/ui/dialogs/push_recovery_dialogs.py`)**:
  - `SecretScanningDialog`: Actionable recovery for GitHub Secret Scanning (`GH007`) showing detected secret type and file location, with an "Open Unblock URL in Browser" action.
  - `ProtectedBranchDialog`: Guided recovery for Protected Branch (`GH006`) push rejections, providing a 1-click branch creation input (prefilled with `patch-1`), automated checkout, and re-push.
  - `FileTooLargeDialog`: Quota violation dialog (`GH001`) displaying offending filename, file size, quota limit, and remediation guidance for `git rm --cached` and Git LFS.

### 2.6 Server-Side Push Error Classification & Protection (`src/wrench/core/write_ops.py` & `src/wrench/core/exceptions.py`)

- **Domain Exception Taxonomy**:
  - `WorkflowScopeRequiredError`: GitHub enforces that commits touching `.github/workflows/` require the `workflow` OAuth scope.
  - `SecretScanningRejectedError` (`GH007`): Captures detected secret type, file location, and unblock URL from remote output.
  - `ProtectedBranchRejectedError` (`GH006`): Captures branch name and protection rejection reason.
  - `FileTooLargeRejectedError` (`GH001`): Captures filename, file size MB, and quota limit MB.
  - `SignedCommitsRequiredError` (`GH008`): Remote rejects unsigned commits.
  - `RepoPermissionDeniedError` (`403`): Remote permission denied for authenticated account.
  - `PushRejectedError`: Base exception for non-fast-forward divergence.
- **Deterministic Classification (`_classify_git_error`)**:
  - Parsed directly from Git CLI stderr during `push` operations before falling back to generic `PushRejectedError`.
  - `MainWindow._route_remote_error()` surfaces specialized recovery dialogs, completely eliminating confusing "Fetch & Retry / Force Push" loops on policy-rejected pushes.

### 2.7 Background Worker Concurrency Engine (`src/wrench/ui/workers.py`)

- **Root Cause of Prior Crashes**:
  - Using `QThread` event loops with `moveToThread` and cross-thread `deleteLater()` created deadlocks between the Python GIL and Qt's C++ `signalSlotLock` mutex during widget destruction.
  - Premature thread destruction caused `QThread: Destroyed while thread is still running` fatal aborts.
- **Worker Redesign**:
  - Implemented `WorkerThread(threading.Thread)` with daemon execution.
  - Main-thread result dispatching via queued signals on a singleton `_Dispatcher(QObject)`.
  - Completely non-blocking background operations with safe progress, completion, and error propagation back to GUI widgets.

### 2.8 Local Git Identity Alignment (`src/wrench/core/identity.py` & `src/wrench/ui/dialogs/link_dialog.py`)

- **Automated Identity Synchronization**:
  - When linking a repository to a forge account via `LinkRepoDialog`, a background task queries `adapter.get_primary_email()`.
  - If a verified email is retrieved, it automatically sets repository-local git configuration via `identity.set_identity(repo, name, email)`.
  - Ensures commit author headers match the authenticated forge account without manual `git config` terminal commands or identity mismatch warnings.

---

## 3. Test Coverage & Verification

### 3.1 Test Suite Breakdown

- **Forge Models & Base Capability Tests** (`tests/unit/forge/`):
  - Model field structures and normalized state validations.
  - Exception hierarchy mapping and scope hint assertions.
  - Capability bitwise flags operations.
  - `get_primary_email` base contract and GitHub adapter extraction.
- **Adapter Integration Matrix Tests** (`tests/integration/`):
  - **`test_github_adapter.py`**:
    - `test_authenticate_success`, `test_authenticate_auth_error`, `test_authenticate_insufficient_scope`, `test_authenticate_unreachable`, `test_rate_limiting`.
    - `test_list_pull_requests_state_mapping`, `test_list_pull_requests_pagination`, `test_create_pull_request_payload`.
    - `test_get_ci_status_mapping`, `test_submit_review_actions_and_issue_trap`.
    - `test_get_pull_request`, `test_get_issue`.
    - `test_get_primary_email_success`, `test_get_primary_email_fallback`, `test_get_primary_email_error`.
  - **`test_gitlab_adapter.py`**:
    - `test_authenticate_success`, `test_authenticate_auth_error`, `test_authenticate_insufficient_scope`, `test_authenticate_unreachable`, `test_rate_limiting`.
    - `test_list_pull_requests_state_mapping`, `test_list_pull_requests_pagination`, `test_create_pull_request_payload`.
    - `test_get_ci_status_mapping`, `test_submit_review_actions_and_self_approval_trap`.
    - `test_get_pull_request`, `test_get_issue`.
  - **`test_forgejo_adapter.py`**:
    - `test_authenticate_success`, `test_authenticate_auth_error`, `test_authenticate_insufficient_scope`, `test_authenticate_unreachable`, `test_rate_limiting`.
    - `test_list_pull_requests_state_mapping`, `test_list_pull_requests_pagination`, `test_create_pull_request_payload`.
    - `test_get_ci_status_mapping`, `test_submit_review_action_approved_trap`.
    - `test_get_pull_request`, `test_get_issue`.
  - **`test_bitbucket_adapter.py`**:
    - `test_authenticate_success`, `test_authenticate_auth_error`, `test_authenticate_insufficient_scope`, `test_authenticate_unreachable`, `test_rate_limiting`.
    - `test_list_pull_requests_state_mapping`, `test_list_pull_requests_next_url_pagination`, `test_create_pull_request_payload`.
    - `test_get_ci_status_mapping_and_review`.
    - `test_get_pull_request`, `test_get_issue`.
- **Storage & Multi-Account Tests** (`tests/unit/storage/test_forge_accounts.py`):
  - Add, list, remove, and get full account records.
  - Secret service rollback on failed token storage.
  - Upsert repository links and candidate remote filtering.
  - Database schema migration v1 to v2.
- **Core Write Operations & Push Protections** (`tests/unit/core/test_write_ops_remotes.py`, `tests/unit/core/test_exceptions.py`, `tests/unit/core/test_identity.py`):
  - Push error classification for `SecretScanningRejectedError`, `ProtectedBranchRejectedError`, `FileTooLargeRejectedError`, `SignedCommitsRequiredError`, `RepoPermissionDeniedError`, `WorkflowScopeRequiredError`.
  - Git identity verification, setting, and invalid email validation.
- **UI Tabs & Recovery Dialog Tests** (`tests/ui/` & `tests/unit/ui/`):
  - `test_forge_tabs.py`: PR list, Issue list, SWR caching, PR detail single-entity loading, CI status, issue detail rendering.
  - `test_accounts_dialog.py`: Accounts manager rendering, add flow, device flow workflow scope assertion, scope picker controls, token replacement, in-place re-auth, removal.
  - `test_push_recovery_dialogs.py`: `SecretScanningDialog`, `ProtectedBranchDialog`, and `FileTooLargeDialog` field rendering and action callbacks.
  - `test_main_window_remotes.py`: Remote operations error routing for secret scanning, protected branches, file size limits, signed commits, and permission denials.
  - `test_forge_repo_switch.py`: Synchronized repository switching across PR and Issue tabs.
- **Worker Concurrency Tests** (`tests/unit/core/test_workers.py`):
  - High-concurrency worker dispatches without deadlocks or crashes.
  - Progress signal propagation and error recovery.

### 3.2 Verification Results

- **Code Quality Check (`./bin/wrench-lint`)**:
  ```
  Checking ruff linting...
  All checks passed!
  Checking black formatting...
  All done! ✨ 🍰 ✨
  150 files would be left unchanged.
  ```
- **Complete Test Suite (`./bin/wrench-test`)**:
  ```
  ============================= 411 passed in 46.23s =============================
  ```
- **Zero Failures, Zero Deadlocks**: All unit, integration, and UI tests execute smoothly with zero memory errors or GUI thread blocks.
