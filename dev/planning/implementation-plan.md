# Implementation Plan — Wrench

**Derived from:** `srs.md` v0.1
**Purpose:** Translate the SRS into an actionable, phased build plan — architecture, tech decisions with rationale, packaging mechanics, CI/CD, and risk mitigations.

**Note on detail level:** This revision is written to be executable step-by-step, including concrete file paths, function/class signatures, database schemas, and config file skeletons — so each task can be implemented without needing to infer missing design decisions. Where a decision was previously implicit, it has been made explicit below.

---

## 0. How to Execute This Plan (read this first)

This section exists so an implementer — including a less capable model — can execute the rest of this document mechanically, without having to make judgment calls this document should have made instead.

### 0.1 Non-negotiable rules
1. **Follow phase order strictly.** Do not start Phase N+1 until Phase N's acceptance check has actually been run and has actually passed — not "should pass." If a check fails, stop and fix it before writing any code for the next phase.
2. **Every `...` in a code block in this document is a stub, not a spec.** `def foo(...) -> X: ...` means "implement this fully." Never leave a bare `...`, `pass`, or `# TODO` as final code. If the exact logic isn't spelled out nearby, it has been spelled out in the relevant phase step below (staging, lock recovery, the credential helper protocol, watcher debounce, and commit-graph layout all have exact algorithms written out — don't invent alternatives to these).
3. **Do not rename anything.** Every file path, module name, function name, class name, and table/column name in §3 and §4 is exact and must be used verbatim. A different name might seem better — that's a documentation change to propose, not a silent rename while coding. Inconsistent naming across files is the most common way a multi-file implementation quietly breaks.
4. **Don't add dependencies not listed in §2's Technology Decisions table.** A step that seems to need an unlisted library is an open question to flag, not a free choice — new dependencies have Flatpak packaging consequences (§6.1) that aren't free to add later.
5. **If two parts of this document seem to contradict each other, stop and flag it.** Do not silently pick one interpretation and continue.

### 0.2 Where development happens
Phases 1–5 (all feature work) are built and tested in a **plain local Python virtual environment** — not inside a Flatpak build. The Flatpak build is only exercised at the end of Phase 0 (skeleton must build), continuously in CI on every PR (§7), and again at Phase 6 (hardening). Don't run `flatpak-builder` after every code change during feature phases; the acceptance checks in Phases 1–5 all run against plain `pytest`.

### 0.3 Standard commands (use these exactly)

Environment setup, once:
```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pre-commit install
```

Every work session:
```bash
source .venv/bin/activate
```

Run the app locally, outside Flatpak, for fast iteration:
```bash
python -m wrench
```

Run tests:
```bash
pytest -v                      # everything
pytest tests/unit -v           # unit only
pytest tests/integration -v    # integration only
```

Lint/format — must be clean before any commit, this is what CI's `lint` job enforces (§7):
```bash
ruff check .
black --check .
```

Build and run the Flatpak, only at the points named in §0.2:
```bash
flatpak-builder --user --install --force-clean build-dir packaging/flatpak/io.github.uzair.Wrench.yaml
flatpak run io.github.uzair.Wrench
```

### 0.4 If you get stuck
Stop and report exactly which numbered step you're on, what you tried, and what happened. Do not silently skip a step, do not silently substitute a different design, and do not mark an acceptance check as passed without having actually run it.

---

## 1. Architecture Overview

```
┌─────────────────────────────────────────────────────────┐
│  UI Layer (PySide6 widgets, plain Qt — no KDE Frameworks)│
│  - Repo sidebar / registry view                          │
│  - Diff tab (default) · Commit graph tab · Merge tool     │
│  - Forge panel (PR/MR, issues, CI status)                 │
└───────────────┬────────────────────────┬──────────────────┘
                │                        │
   ┌────────────▼───────────┐  ┌─────────▼──────────────┐
   │   Core Git Engine       │  │  Forge Integration Layer│
   │   - pygit2 (reads,      │  │  - Capability-based      │
   │     status, diff, log)  │  │    provider interface    │
   │   - git subprocess      │  │  - Entry-points adapter   │
   │     (push/pull/rebase/  │  │    registration            │
   │     merge, credential   │  │  - GitHub adapter          │
   │     negotiation)        │  │  - GitLab adapter          │
   └────────────┬────────────┘  │  - Forgejo/Gitea adapter   │
                │               │  - Bitbucket Cloud adapter │
                │               └────────────┬───────────────┘
                │                            │
   ┌────────────▼───────────┐   ┌────────────▼───────────────┐
   │  Credential Manager      │   │  Local Data Store (SQLite)  │
   │  - Secret Service D-Bus  │   │  - Repo registry             │
   │  - SSH agent socket       │   │  - Forge account configs     │
   └───────────────────────────┘   └───────────────────────────┘
```

**Key architectural decision**: the Core Git Engine is split — `pygit2`/libgit2 handles all *read* operations (status, diff, log, blame) where it's fast and safe, while the actual `git` CLI binary (via subprocess) handles *risky write* operations (push, rebase, merge, credential handshakes). This avoids relying on libgit2/pygit2's less battle-tested merge/rebase edge-case handling and inherits git's own conflict resolution behavior — the same pattern several mature clients use rather than trusting a single library end-to-end.

**Data flow rule (explicit)**: UI code never calls `pygit2` or `subprocess` directly. All git operations go through `core/engine.py` façade functions. All forge operations go through `forge/registry.py` → capability interface. This one-directional dependency (`ui → core/forge → (pygit2 | subprocess | httpx)`) must hold everywhere; if a UI file imports `pygit2` directly, that's a bug.

---

## 2. Technology Decisions

| Component | Choice | Rationale |
|---|---|---|
| UI toolkit | PySide6, plain Qt widgets only | LGPL, official Qt Company binding, avoids PyQt6 GPL/commercial licensing questions against AGPL-3.0. **No KDE Frameworks (KF6) dependency** — revised from an earlier commitment so a future Windows/macOS port (SRS §7.3) is additive, not a rewrite (SRS §3.12/FR-11.4) |
| Platform paths | `platformdirs` (PyPI) | Resolves data/config/cache dirs per-OS; v1 only exercises its Linux/XDG behavior, but every call site goes through this from day one rather than a hardcoded `$XDG_DATA_HOME` (FR-11.2) |
| Git read engine | `pygit2` (libgit2 bindings) | Mature, safe for status/diff/log/blame |
| Git write engine | System `git` binary via subprocess | Inherits git's own tested merge/rebase/credential logic |
| Local data | SQLite (`sqlite3` stdlib) | Zero extra dependency, sufficient for repo registry and settings |
| Credential storage | `CredentialBackend` interface (§4.7); freedesktop Secret Service (`python-secretstorage`) is the only concrete v1 implementation | Portable — auto-backed by KWallet on Plasma, GNOME Keyring elsewhere. Interface shape is platform-neutral so a future Keychain/Credential-Manager backend doesn't touch calling code (FR-11.1) |
| HTTP client (forge APIs) | `httpx` (sync client, no async runtime needed for v1) | Modern `requests`-alternative with typed timeouts, HTTP/2, easy to mock in tests |
| Language/runtime | Python 3.12+ | Team preference; bundle explicitly in packaging (see §5) |
| License | AGPL-3.0 | Confirmed |
| Forge adapter registration | Python packaging entry points (`wrench.forge_adapters` group) against a capability-based interface | Confirmed v1 mechanism — adapters (including the four confirmed backends) are discovered as plugins rather than hardcoded, so community/third-party adapters install without touching core |
| Packaging manager (dev) | `pip` + stdlib `venv` | No extra tool to install before you can even start (§0.3's setup commands use this directly); simplicity over speed for a project this size. If `uv` is preferred later, that's a §0.3 update to make explicitly, not a silent switch — don't mix the two |
| Testing | `pytest`, `pytest-qt`, `responses` (HTTP mocking) | Standard, well-documented, works in CI without network |

---

## 3. Proposed Project Structure

```
wrench/
├── dev/                            # planning docs + scratch space, not shipped, not imported by src/
│   ├── planning/
│   │   ├── srs.md                  # this SRS, tracked in git — the record of *why*, not just *what*
│   │   └── implementation-plan.md  # this document, tracked in git for the same reason
│   ├── scratch/                    # gitignored (see .gitignore below) — local notes, throwaway
│   │                                #   sketches, anything not meant to be public or permanent
│   └── README.md                   # explains the split above in ~5 lines, for future-you or a contributor
├── src/wrench/
│   ├── __init__.py
│   ├── __main__.py                # entry point: `python -m wrench`
│   ├── app.py                     # QApplication bootstrap, main window wiring
│   ├── core/
│   │   ├── __init__.py
│   │   ├── engine.py              # public façade: init_repo(), open_repo(), stage(), commit(), etc.
│   │   ├── read_ops.py            # pygit2-backed: status, diff, log, blame
│   │   ├── write_ops.py           # subprocess-backed: push, pull, fetch, rebase, merge
│   │   ├── lock_recovery.py       # FR-1.9: detect/clear stale .git/index.lock
│   │   ├── reflog.py              # FR-1.10: reflog read + restore-to-ref
│   │   ├── snapshots.py           # FR-10.x: rolling snapshot capture/restore/prune (§4.6)
│   │   ├── identity.py            # FR-1.1/1.5: user.name/email check, per-repo override
│   │   ├── backup.py              # FR-8.1-8.5: git bundle create/restore
│   │   ├── paths.py               # FR-11.2: platformdirs wrapper — the only file that resolves data/config dirs, §4.7
│   │   ├── ssh_agent.py           # FR-11.3: isolates $SSH_AUTH_SOCK access, §4.7
│   │   └── exceptions.py          # WrenchGitError and subclasses
│   ├── forge/
│   │   ├── __init__.py
│   │   ├── capability.py          # ForgeCapability enum + ForgeAdapter ABC (the interface, FR-5.1)
│   │   ├── registry.py            # entry-points discovery + adapter instantiation (FR-5.7)
│   │   ├── models.py              # dataclasses: PullRequest, Issue, CIStatus, ForgeAccount
│   │   ├── exceptions.py          # forge error hierarchy (§4.3.A) — separate from core/exceptions.py
│   │   │                          #   because these aren't git errors: they must never be conflated
│   │   │                          #   by the UI's git-error dialog path
│   │   └── adapters/
│   │       ├── __init__.py
│   │       ├── github.py          # FR-5.2
│   │       ├── gitlab.py          # FR-5.3
│   │       ├── forgejo.py         # FR-5.4
│   │       └── bitbucket.py       # FR-5.5
│   ├── credentials/
│   │   ├── __init__.py             # get_backend() factory — FR-11.1, §4.7
│   │   ├── backend.py              # CredentialBackend ABC — the platform-neutral interface, §4.7
│   │   └── secret_service.py      # FR-4.3: shared D-Bus logic + FlatpakSecretServiceBackend/AppImageSecretServiceBackend, §4.5
│   ├── storage/
│   │   ├── __init__.py
│   │   ├── schema.sql             # DDL, versioned (see §3.1 below)
│   │   ├── db.py                  # connection management, migrations
│   │   ├── repo_registry.py       # FR-1.2/1.3: CRUD for known repos
│   │   ├── forge_accounts.py      # FR-5.6/5.8: CRUD for forge_accounts + repo_forge_links
│   │   ├── snapshots.py           # FR-10.x: CRUD for snapshots + snapshot_settings tables
│   │   └── settings.py            # app-level + per-repo settings CRUD
│   ├── watcher/
│   │   ├── __init__.py
│   │   ├── inotify_watcher.py     # FR-1.8: primary, via `watchdog`
│   │   └── polling_fallback.py    # FR-1.8: debounced fallback when inotify limits hit
│   ├── ui/
│   │   ├── __init__.py
│   │   ├── main_window.py
│   │   ├── workers.py              # GitOperationWorker + run_in_background — §4.8, used by every
│   │   │                            #   UI call site that invokes a long-running core.engine function
│   │   ├── sidebar/                # [DEPRECATED by Phase 1.5] replaced by repo dropdown in changes_tab
│   │   ├── tabs/                   # Phase 1.5: hybrid tab navigation shell (singletons + dynamic detail tabs)
│   │   │   ├── __init__.py
│   │   │   ├── tab_bar.py          # custom TabBar widget (vertical/horizontal, closable, dedup, +)
│   │   │   ├── changes_tab.py      # repo selector + branch switcher + unified file list + commit + diff
│   │   │   ├── history_tab.py      # skeleton: search bar + graph placeholder + detail panel slot
│   │   │   ├── pr_list_tab.py      # Phase 4: PR/MR list category tab
│   │   │   ├── pr_detail_tab.py    # Phase 4: PR detail dynamic tab
│   │   │   ├── issue_list_tab.py   # Phase 4: Issues list category tab
│   │   │   └── issue_detail_tab.py # Phase 4: Issue detail dynamic tab
│   │   ├── widgets/                # Reusable UI widgets
│   │   │   ├── __init__.py
│   │   │   └── branch_switcher.py  # branch indicator/switcher dropdown (FR-1.6, ui-planning §3.2b)
│   │   ├── dialogs/                # Dedicated dialogs
│   │   │   ├── __init__.py
│   │   │   ├── clone_dialog.py     # Clone repository dialog (FR-4.1, ui-planning §6.2)
│   │   │   ├── stash_dialog.py     # Stash manager dialog (FR-1.7, ui-planning §6.1)
│   │   │   ├── identity_dialog.py  # Git identity override dialog (FR-1.5, ui-planning §6.5)
│   │   │   ├── reflog_dialog.py    # Reflog history & restore dialog (FR-1.10, ui-planning §6.7)
│   │   │   ├── remotes_dialog.py   # Manage remotes configuration dialog (FR-4.4, ui-planning §6.8)
│   │   │   └── backup_dialog.py    # On-demand backup & restore dialogs (FR-8.1-8.4, ui-planning §6.9)
│   │   ├── diff_view/              # FR-2.1 (re-parented into changes_tab in Phase 1.5)
│   │   ├── commit_graph/           # FR-2.2/2.3 (plugs into history_tab's graph slot in Phase 2)
│   │   │   ├── graph_widget.py     # custom QPainter commit graph + accessible tree fallback
│   │   │   ├── layout.py           # pure-python lane assignment
│   │   │   └── detail_panel.py     # slide-in commit detail panel
│   │   ├── merge_tool/             # FR-3.2: 3-way visual conflict resolution tool (ui-planning §6.6)
│   │   │   ├── __init__.py
│   │   │   └── merge_dialog.py     # 3-pane top (Ours/Base/Theirs) + Result bottom editor
│   │   ├── forge_panel/            # FR-5.x UI
│   │   └── snapshots_panel/       # FR-10.6: browse/restore rolling snapshots (ui-planning §6.4);
│   │                              #   package on disk, panel implemented in its __init__.py
│   └── py.typed
├── tests/
│   ├── unit/
│   │   ├── core/
│   │   ├── forge/
│   │   ├── storage/
│   │   └── credentials/
│   ├── integration/                # mocked forge API tests, one dir per adapter
│   │   ├── github/
│   │   ├── gitlab/
│   │   ├── forgejo/
│   │   └── bitbucket/
│   ├── ui/                         # pytest-qt widget tests
│   └── fixtures/
│       ├── git_repos.py            # pytest fixtures: create throwaway repos in tmp_path
│       └── forge_responses/        # recorded JSON fixtures per provider
├── packaging/
│   ├── flatpak/
│   │   ├── io.github.uzair.Wrench.yaml        # Flatpak manifest
│   │   ├── io.github.uzair.Wrench.metainfo.xml
│   │   ├── io.github.uzair.Wrench.desktop
│   │   └── build-flatpak.sh        # §6.3: produces a distributable .flatpak bundle
│   ├── appimage/
│   │   └── build-appimage.sh       # §6.3: thin wrapper around Briefcase
│   └── build-all.sh                # §6.3: orchestrates both, single entry point for "build everything"
├── .github/workflows/
│   └── ci.yml
├── .gitignore                      # see Phase 0 step 1 for required entries
├── LICENSE (AGPL-3.0)
├── pyproject.toml                  # also holds [tool.briefcase.*] config, added in §6.3
└── README.md
```

### 3.1 SQLite Schema (`storage/schema.sql`)

Concrete DDL so `storage/db.py` has an unambiguous target. Use `PRAGMA user_version` for migration tracking (start at `1`).

```sql
-- schema version 1
PRAGMA user_version = 1;

CREATE TABLE repos (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    path            TEXT NOT NULL UNIQUE,   -- absolute filesystem path
    display_name    TEXT NOT NULL,          -- defaults to dir basename, user-editable
    last_branch     TEXT,
    last_opened_at  TEXT,                   -- ISO 8601
    is_missing      INTEGER NOT NULL DEFAULT 0,  -- FR-1.3: 1 if path not found on last check
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE identity_profiles (        -- FR-7.1
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    label           TEXT NOT NULL,          -- e.g. "Work", "Personal"
    name            TEXT NOT NULL,
    email           TEXT NOT NULL
);

CREATE TABLE repo_identity_overrides (  -- FR-1.5/7.1: per-repo identity assignment
    repo_id         INTEGER NOT NULL REFERENCES repos(id) ON DELETE CASCADE,
    identity_id     INTEGER NOT NULL REFERENCES identity_profiles(id) ON DELETE CASCADE,
    PRIMARY KEY (repo_id)
);

CREATE TABLE forge_accounts (           -- FR-5.6
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    provider        TEXT NOT NULL,          -- 'github' | 'gitlab' | 'forgejo' | 'bitbucket'
    instance_url    TEXT NOT NULL,          -- e.g. https://github.com, or self-hosted URL
    label           TEXT NOT NULL,          -- user-facing name, e.g. "Work Forgejo"
    username         TEXT,
    -- per-account TLS policy (SRS §6.1's self-signed-cert question, resolved §11
    -- item 13): NULL bundle + tls_insecure=0 → system trust store only (default).
    -- bundle path set → verify against that PEM. tls_insecure=1 → skip
    -- verification entirely (opt-in only, warning-gated in the accounts dialog).
    tls_ca_bundle_path TEXT,
    tls_insecure     INTEGER NOT NULL DEFAULT 0,
    -- NOTE: no token/secret column here — credentials live only in Secret Service,
    -- referenced by a secret_service_key, never stored in SQLite (NFR: no plaintext secrets).
    secret_service_key TEXT NOT NULL UNIQUE,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE repo_forge_links (         -- links a local repo to a forge account + remote
    repo_id         INTEGER NOT NULL REFERENCES repos(id) ON DELETE CASCADE,
    forge_account_id INTEGER NOT NULL REFERENCES forge_accounts(id) ON DELETE CASCADE,
    remote_name     TEXT NOT NULL DEFAULT 'origin',
    owner_slug      TEXT NOT NULL,          -- org/user namespace on the forge
    repo_slug       TEXT NOT NULL,
    PRIMARY KEY (repo_id, remote_name)
);

CREATE TABLE snapshots (                -- FR-10.x: local rolling safety-net snapshots
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    repo_id         INTEGER NOT NULL REFERENCES repos(id) ON DELETE CASCADE,
    ref_name        TEXT NOT NULL,          -- refs/wrench/snapshots/{id} — points at the git-native
                                             -- object created by `git stash create` (or HEAD if clean)
    trigger_type    TEXT NOT NULL,          -- 'commit' | 'timer' | 'pre_risky_op' | 'manual'
    is_manual       INTEGER NOT NULL DEFAULT 0,  -- FR-10.5: manual snapshots pruned last, exempt from age cutoff
    label           TEXT,                   -- user-supplied, only meaningful when is_manual = 1
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    untracked_archive_path TEXT             -- path under app data dir to this snapshot's untracked-file
                                             -- tar.gz, NULL if untracked capture was off or nothing untracked existed
);

CREATE TABLE snapshot_untracked_files (  -- FR-10.3: per-file record within a snapshot's untracked capture
    snapshot_id     INTEGER NOT NULL REFERENCES snapshots(id) ON DELETE CASCADE,
    relative_path   TEXT NOT NULL,
    content_captured INTEGER NOT NULL,   -- 0 if skipped (over the size cap), 1 if actually in the archive
    size_bytes      INTEGER NOT NULL,
    PRIMARY KEY (snapshot_id, relative_path)
);

CREATE TABLE snapshot_settings (         -- FR-10.2/10.4: per-repo configuration, one row per repo
    repo_id                  INTEGER NOT NULL REFERENCES repos(id) ON DELETE CASCADE,
    trigger_on_commit        INTEGER NOT NULL DEFAULT 1,
    trigger_on_timer         INTEGER NOT NULL DEFAULT 1,
    timer_interval_minutes   INTEGER NOT NULL DEFAULT 10,
    trigger_before_risky_op  INTEGER NOT NULL DEFAULT 1,
    max_count                INTEGER NOT NULL DEFAULT 25,   -- user-adjustable; 25 is the default midpoint of 20-30
    max_age_days             INTEGER,      -- NULL = no age cutoff, count-based pruning only
    untracked_capture_mode   TEXT NOT NULL DEFAULT 'capped',  -- 'none' | 'capped' | 'unlimited'
    untracked_per_file_cap_mb INTEGER NOT NULL DEFAULT 50,    -- used when mode = 'capped'
    untracked_total_cap_mb   INTEGER NOT NULL DEFAULT 500,    -- used when mode = 'capped'
    PRIMARY KEY (repo_id)
);

CREATE TABLE app_settings (             -- generic key/value for app-level config
    key             TEXT PRIMARY KEY,
    value           TEXT NOT NULL
);
```

`storage/db.py` responsibilities:
- `get_connection() -> sqlite3.Connection` — opens `paths.data_dir() / "wrench.db"` (§4.7 — never a hardcoded `~/.local/share/...` or raw `$XDG_DATA_HOME` read; this is the app's own private data dir either way, so no extra Flatpak permission is needed), enables `PRAGMA foreign_keys = ON` (SQLite has this **off by default** — every `ON DELETE CASCADE` in §3.1's schema silently does nothing until this pragma is set on the connection, which is a classic, easy-to-miss SQLite footgun) and `PRAGMA journal_mode = WAL` (write-ahead logging — lets a background snapshot/prune operation read the DB without blocking a concurrent UI-thread write, which matters once the snapshot timer trigger is running alongside normal use).
- **Connection lifecycle**: one connection, opened once at app startup and held for the process lifetime, not one-per-operation and not one-per-repo. SQLite connections are cheap to hold open and expensive to keep re-opening; a single shared connection also means the `PRAGMA` settings above only need to be applied once. All `storage/*.py` CRUD functions take the connection as an explicit parameter rather than opening their own — this makes them trivially testable against an in-memory `sqlite3.connect(":memory:")` connection in unit tests, without needing to touch the real on-disk database file at all.
- `run_migrations(conn)` — reads `PRAGMA user_version`; if it's `0` (a brand-new, just-created database file), apply `schema.sql` directly and set `user_version` to the current target version. If it's a positive number less than the current target, apply any `schema_v{N}.sql` files found in `storage/migrations/` greater than the current version, in order, inside a single transaction (so a failed migration halfway through doesn't leave the schema in an inconsistent state) — call this once at startup, before any other `storage/*.py` function touches the connection.
- Never construct SQL with string interpolation — use parameterized queries (`?` placeholders) everywhere, including in `repo_registry.py` and `settings.py`.

**Storage-layer record types** (returned by the CRUD functions in `repo_registry.py`/`forge_accounts.py` throughout §5 — one dataclass per table row, field names matching the schema column names exactly so mapping a `sqlite3.Row` to one of these is a direct, unambiguous `dataclass(**dict(row))` rather than a hand-written field-by-field translation):

```python
@dataclass
class RepoRecord:
    id: int
    path: str
    display_name: str
    last_branch: str | None
    last_opened_at: str | None
    is_missing: bool
    created_at: str


@dataclass
class ForgeAccountRecord:
    id: int
    provider: str
    instance_url: str
    label: str
    username: str | None
    tls_ca_bundle_path: str | None  # per-account TLS policy (schema comment, §3.1)
    tls_insecure: int               # raw 0/1 from SQLite, kept as int so
                                    # dataclass(**dict(row)) stays field-name-exact
    created_at: str
    # secret_service_key is deliberately excluded from this record — callers that
    # need it (the credential helper, account removal) read it directly from the
    # forge_accounts table, so it never travels through a generic list_accounts()
    # result that UI code might log or display


@dataclass
class RepoForgeLink:
    repo_id: int
    forge_account_id: int
    remote_name: str
    owner_slug: str
    repo_slug: str
```

---

## 4. Core Interfaces (concrete signatures)

These are the actual function/class signatures Phase 1–4 code should implement. Treat this as the contract; UI and tests are written against it.

### 4.1 `core/engine.py` (façade — the only module UI imports from `core`)

```python
from pathlib import Path
from dataclasses import dataclass, field

@dataclass
class RepoStatus:
    staged: list["FileChange"]
    unstaged: list["FileChange"]
    untracked: list[str]
    current_branch: str | None   # None when is_detached is True. An "unborn" branch (repo has
                                  # zero commits yet) still has a real name here — e.g. "main" —
                                  # even though it doesn't point anywhere; don't confuse the two
                                  # states. Check is_detached explicitly rather than treating a
                                  # falsy current_branch as meaning detached.
    is_detached: bool
    ahead: int
    behind: int
    has_conflicts: bool
    detached_head_sha: str | None = None   # only set when is_detached is True
    merge_in_progress: bool = False    # Phase 2 addition: GIT_REPOSITORY_STATE_MERGE. Distinct
                                       # from has_conflicts — a merge whose conflicts are all
                                       # resolved reports has_conflicts=False but is still an
                                       # open merge until the user commits; the Changes-tab
                                       # banner (ui-planning §3.6) stays up on this flag
    rebase_in_progress: bool = False   # Phase 2 addition: GIT_REPOSITORY_STATE_REBASE_MERGE /
                                       # _APPLY — drives the same banner and the merge tool's
                                       # rebase mode (§5 Phase 2 step 5)

@dataclass
class FileChange:
    path: str
    change_type: str   # 'added' | 'modified' | 'deleted' | 'renamed'
    old_path: str | None = None  # set when change_type == 'renamed'

@dataclass
class Commit:
    sha: str
    message: str
    author_name: str
    author_email: str
    author_date: str          # ISO 8601
    parent_shas: list[str]    # required by the commit-graph lane-assignment algorithm (§5 Phase 2, step 1) —
                               # don't omit this field, the graph can't be laid out without it

@dataclass
class BlameLine:
    line_no: int
    commit_sha: str
    author: str
    line_content: str

@dataclass
class DiffLine:
    content: str
    origin: str                # '+' | '-' | ' ' (context) — mirrors pygit2's own line.origin values directly
    old_lineno: int | None
    new_lineno: int | None

@dataclass
class Hunk:
    id: str                    # stable within one Diff; this is the hunk_id stage_hunk(path, hunk_id) takes
    old_start: int
    old_count: int
    new_start: int
    new_count: int
    lines: list[DiffLine]

@dataclass
class Diff:
    path: str
    is_binary: bool
    hunks: list[Hunk]          # empty for binary files — check is_binary before reading this, don't infer
                                # binary-ness from an empty hunks list, that conflates two different states

@dataclass
class MergeResult:
    status: str                 # 'up_to_date' | 'merged' | 'conflict' — see §5 Phase 2 step 3 for
                                 # how each status is derived from git's exit code and output
    commit_sha: str | None = None
    conflicted_files: list[str] = field(default_factory=list)

@dataclass
class RebaseResult:
    status: str                  # 'complete' | 'conflict' | 'aborted'
    conflicted_files: list[str] = field(default_factory=list)

@dataclass
class FileStat:
    """One row of the 'Files changed' list in a commit's detail view / hover tooltip
    (ui-planning §4.4/§4.5). Phase 2 addition."""
    path: str
    change_type: str        # 'added' | 'modified' | 'deleted' | 'renamed'
    additions: int
    deletions: int

@dataclass
class RefLabel:
    """A badge rendered on the commit graph (ui-planning §4.2/§4.3). Phase 2 addition."""
    name: str               # 'main', 'feature/x', 'v1.0.0', 'HEAD'
    kind: str               # 'branch' | 'tag' | 'head' — 'head' gets its own pill style

@dataclass
class Remote:
    name: str
    url: str

@dataclass
class RemoteInfo:
    """Phase 3 addition (§5 Phase 3 step 5). One row of the Remotes dialog —
    a Remote plus health metadata. `last_fetch_at` is the ISO-8601 timestamp of
    the most recent successful fetch against this remote recorded by
    `fetch()` (None if never fetched through Wrench), and `is_reachable` is
    the result of the last connectivity probe (`git ls-remote` with a short
    timeout) — None means "not yet probed", True/False are the probed result."""
    name: str
    url: str
    last_fetch_at: str | None = None
    is_reachable: bool | None = None

@dataclass
class CloneResult:
    """Phase 3 addition (§5 Phase 3 step 3). Returned by clone_repo on success —
    the UI needs the final path (which equals `dest` on success, but returning
    it explicitly lets the dialog open the new repo without re-deriving it)."""
    path: Path

# The exact callback contract for every progress-reporting engine function
# (clone_repo, push, pull, fetch). `percent` is an int 0-100 parsed from git's
# progress stream; `stage` is the human-readable phase label git reported
# ("Enumerating objects", "Counting objects", "Compressing objects",
# "Receiving objects", "Resolving deltas", ...) so the UI can render
# "Receiving objects: 42%" without inventing its own strings. GUI widgets
# subscribe via ui.workers.run_in_background's on_progress — which emits the
# percent only; the stage string stays available to call sites that pass a
# richer callback of their own.
ProgressCallback = Callable[[int, str], None]  # (percent, stage); requires
# `from collections.abc import Callable` (or typing.Callable) at the top of the
# module — §4.1's import list above predates this alias; add the import when the
# alias is added.

@dataclass
class ReflogEntry:
    sha: str
    message: str
    timestamp: str               # ISO 8601

@dataclass
class Submodule:
    path: str
    url: str
    initialized: bool

@dataclass
class SubmoduleStatus:
    path: str
    current_commit: str
    is_dirty: bool

@dataclass
class LogFilter:
    author: str | None = None
    message_substring: str | None = None
    date_from: str | None = None       # ISO 8601
    date_to: str | None = None         # ISO 8601
    path: str | None = None
    # matching is plain case-insensitive substring search, not regex — see §5 Phase 2 step 2

def init_repo(path: Path) -> None: ...
def clone_repo(url: str, dest: Path, *, progress_cb: "ProgressCallback | None" = None) -> "CloneResult": ...
    # Phase 3 (§5 Phase 3 steps 2–3): clones into tempfile.mkdtemp() first, moves to
    # `dest` only on success, and writes the credential helper config into the new
    # repo (§5 Phase 3 steps 2a–2b apply — every repo that enters the app gets this
    # config, not just clones). Raises CloneAbortedError on user cancellation,
    # AuthRequiredError when the remote demands credentials that don't resolve,
    # and GitCommandError for anything else. Never raises bare subprocess errors.
def open_repo(path: Path) -> "RepoHandle": ...   # raises WrenchRepoNotFoundError if missing

def get_status(repo: "RepoHandle") -> RepoStatus: ...
def get_diff(repo: "RepoHandle", path: str, *, staged: bool) -> Diff: ...
def get_log(repo: "RepoHandle", filter: LogFilter | None = None, *, limit: int = 100, offset: int = 0) -> list[Commit]: ...
def blame(repo: "RepoHandle", path: str) -> list[BlameLine]: ...
def stage_file(repo: "RepoHandle", path: str) -> None: ...
def stage_hunk(repo: "RepoHandle", path: str, hunk_id: str) -> None: ...
def stage_lines(repo: "RepoHandle", path: str, line_numbers: list[int]) -> None: ...
def unstage_file(repo: "RepoHandle", path: str) -> None: ...

def commit(repo: "RepoHandle", message: str, *, amend: bool = False) -> str: ...  # returns new commit sha

def list_branches(repo: "RepoHandle") -> list[str]: ...
def create_branch(repo: "RepoHandle", name: str, *, from_ref: str = "HEAD") -> None: ...
def switch_branch(repo: "RepoHandle", name: str) -> None: ...
def delete_branch(repo: "RepoHandle", name: str, *, force: bool = False) -> None: ...
def rename_branch(repo: "RepoHandle", old: str, new: str) -> None: ...

def stash_create(repo: "RepoHandle", message: str | None = None) -> str: ...  # returns stash id
def stash_apply(repo: "RepoHandle", stash_id: str) -> None: ...
def stash_drop(repo: "RepoHandle", stash_id: str) -> None: ...

def push(repo: "RepoHandle", remote: str, branch: str, *, force: bool = False,
         progress_cb: "ProgressCallback | None" = None,
         cancel_event: "threading.Event | None" = None) -> None: ...
    # Phase 3 (§5 Phase 3 step 3). `force=True` maps to `git push --force-with-lease`
    # — NEVER bare `--force`, which silently clobbers remote history another client
    # updated in the meantime. Raises PushRejectedError (non-FF / stale remote info),
    # AuthRequiredError, or GitCommandError.
def pull(repo: "RepoHandle", remote: str, branch: str, *,
         progress_cb: "ProgressCallback | None" = None,
         cancel_event: "threading.Event | None" = None) -> None: ...
    # Phase 3 (§5 Phase 3 step 3): `git pull --ff-only` — a pull that can't fast-forward
    # raises MergeRequiredError (typed), which the UI turns into an explicit
    # merge/rebase choice instead of letting git create a surprise merge commit.
def fetch(repo: "RepoHandle", remote: str, *,
          progress_cb: "ProgressCallback | None" = None,
          cancel_event: "threading.Event | None" = None) -> None: ...
    # Phase 3 (§5 Phase 3 step 3): records a successful fetch's timestamp into
    # storage (keyed on (repo_id, remote_name)) so list_remotes can populate
    # RemoteInfo.last_fetch_at without shelling out to git log analysis.

def list_remotes(repo: "RepoHandle") -> list["RemoteInfo"]: ...
    # Phase 3 (§5 Phase 3 step 5): `git remote -v` parse + stored last-fetch metadata.
    # Push and fetch URLs that differ collapse into one RemoteInfo row keyed on the
    # fetch URL (the credential-relevant one); the divergence is a display detail
    # for the Remotes dialog, not a second row.
def add_remote(repo: "RepoHandle", name: str, url: str) -> None: ...
    # Phase 3 (§5 Phase 3 step 5 — full contract there): validates name/url, rejects
    # duplicate names via RemoteExistsError, writes the credential helper config
    # FIRST (§5 Phase 3 step 2) so a failure leaves no half-configured remote,
    # then `git remote add`, then fires a connectivity probe in the background.
def remove_remote(repo: "RepoHandle", name: str) -> None: ...
    # Phase 3 (§5 Phase 3 step 5): pre-checks existence, raises RemoteNotFoundError
    # from the precheck (not git's stderr), then `git remote remove`.
def set_remote_url(repo: "RepoHandle", name: str, url: str) -> None: ...
    # Phase 3 (§5 Phase 3 step 5): same validation as add_remote; `git remote set-url`.

def merge(repo: "RepoHandle", source_branch: str) -> "MergeResult": ...
def rebase(repo: "RepoHandle", onto: str) -> "RebaseResult": ...

# --- Phase 2 surface (implementations land in Phase 2; signatures fixed here so
#     ui/history_tab.py, ui/commit_graph/, and ui/merge_tool/ can be written against
#     them without drift) ---

def get_commit_diff(repo: "RepoHandle", sha: str, path: str | None = None) -> Diff: ...
    # Diff of a commit against its FIRST parent (roots: against the empty tree).
    # Merge commits diff against the first parent only — v1 renders no combined diffs.
    # `path` narrows to a single file, matching get_diff's per-file contract. This is
    # what the History detail panel and hover tooltips render through the same Diff
    # model the Changes tab already uses.
def get_commit_file_stats(repo: "RepoHandle", sha: str) -> list[FileStat]: ...
    # per-file additions/deletions for the detail panel's file list and the hover
    # tooltip's +N/-M columns (ui-planning §4.4/§4.5); computed from the same
    # first-parent diff as get_commit_diff via diff.patch / per-file line counts
def get_ref_labels(repo: "RepoHandle") -> dict[str, list[RefLabel]]: ...
    # sha -> [RefLabel] for the commit-graph pill badges: one entry per branch tip,
    # tag target, and HEAD. Detached HEAD contributes a single 'head' label at
    # detached_head_sha. Annotated tag refs must be peeled to their commit target
    # (ref.peel() returns the Commit object; for tags the peel target is accessible
    # via .target, so e.g. ref.peel().target gives the commit the tag points at).
    # Cheap, un-paginated — called once per graph refresh

def iter_commits(repo: "RepoHandle", *, all_refs: bool = False) -> "Iterator[Commit]":
    # One live pygit2 walker kept open and yielded from — the commit-graph's batch
    # loader advances THIS iterator across scroll batches rather than re-issuing
    # get_log(offset=...) per batch, which re-walks the whole DAG every time and turns
    # incremental scroll into O(n²) on large repos. The walker is seeded from HEAD
    # (always) plus every local branch ref under refs/heads/* and tag ref under
    # refs/tags/* when all_refs=True. Seeds are sorted by full ref name before
    # pushing, so lane assignment is deterministic across refreshes and test runs
    # (§5 Phase 2 step 1a). Yields Commit objects in walk order
    # (GIT_SORT_TOPOLOGICAL | GIT_SORT_TIME). Do NOT re-issue get_log(offset=N)
    # for each batch — re-walking from the root each time is O(n²) and ruins the
    # promise of virtualized rendering; advance this single generator instead.
def rebase_continue(repo: "RepoHandle") -> None: ...   # run_git(["rebase", "--continue"]);
                                                       # non-zero exit means another conflict —
                                                       # NOT an exception (§5 Phase 2 step 5)
def rebase_abort(repo: "RepoHandle") -> None: ...      # run_git(["rebase", "--abort"])
```

#### 4.1.A `core/exceptions.py` — Phase 3 additions (exact definitions)

The Phase 3 steps below reference these exception types. All of them live in `core/exceptions.py` alongside the Phase 1/2 hierarchy and follow the same pattern: they subclass `WrenchGitError`, carry structured fields (never just a bundled message string), and are the ONLY exception types that `core.engine` remote-operation wrappers ever raise — a lower layer surfacing `subprocess.CalledProcessError` or `pygit2.GitError` through the façade is a façade bug, not an acceptable leak.

```python
class CloneAbortedError(WrenchGitError):
    """User cancelled a clone via cancel_event; the temp directory was cleaned
    up and `dest` was never written. UI shows no error dialog — this is the
    normal outcome of pressing Cancel, distinguished from failure precisely so
    the UI can tell the two apart."""

class AuthRequiredError(WrenchGitError):
    """Git asked for credentials and the credential helper produced none —
    either no matching account exists in `forge_accounts`, or the Secret
    Service lookup returned nothing. Carries `host: str | None` and
    `path_component: str | None` parsed from the remote URL so the dialog can
    pre-fill the account-creation flow. Distinguish from AuthFailedError:
    AuthRequired means 'no credential on file', AuthFailed means 'credential
    on file was rejected'."""

class AuthFailedError(WrenchGitError):
    """The credential helper DID supply a credential and the server rejected it
    (HTTP 401/403 from a forge host, or 'Permission denied (publickey)' over
    SSH). The credential is almost certainly expired/revoked — the UI response
    is 'edit this account's token', NOT 'try again'. Carries `host: str`."""

class PushRejectedError(GitCommandError):
    """`git push` exited non-zero with 'rejected' in stderr — non-fast-forward,
    remote ref moved, or a server-side hook refused the push. The stderr text
    is attached via the usual error_attributes mechanism; the UI offers
    'fetch and retry' as the default corrective action, or force-with-lease
    behind a confirmation."""

class MergeRequiredError(GitCommandError):
    """`git pull --ff-only` failed because the branches diverged — git refuses
    rather than creating an implicit merge (see §5 Phase 3 step 3). The UI's
    response is a merge-vs-rebase choice, wired to the Phase 2 machinery."""

class RemoteExistsError(WrenchGitError):
    """add_remote was asked to create a remote whose name is already configured.
    Raised BEFORE invoking git so the git-level error string never leaks."""

class RemoteNotFoundError(WrenchGitError):
    """fetch/pull/push/add_remote probe referenced a remote name with no
    configured URL. UI turns this into 'add a remote first' guidance."""

class CLITimeoutError(GitCommandError):
    """The git subprocess exceeded its timeout (§5 Phase 3 step 3's per-op
    timeout table, not the generic 30s default). Distinct from a network
    failure: the process may still be alive server-side, so this message must
    not pretend to know the remote state."""
```

`RepoHandle` wraps a `pygit2.Repository` for reads and the repo's filesystem `Path` for subprocess calls. It is created once per opened repo and cached by `ui/main_window.py`; never re-open a repo per operation.

**Where implementation lives vs. what UI calls**: `core/read_ops.py` and `core/write_ops.py` (§5 Phase 1, steps 1–2) contain the actual `pygit2`/subprocess logic; `core/engine.py` re-exports every one of these as a thin façade function (e.g. `engine.get_log = read_ops.get_log`, or a one-line wrapper if error-translation is needed per step 5 below). UI code calls `core.engine.get_log(...)`, `core.engine.get_diff(...)`, etc. — **never** `core.read_ops.get_log(...)` directly, per §1's one-directional dependency rule. This applies uniformly to every function above, including the read-path ones.

### 4.2 `core/write_ops.py` (subprocess wrapper conventions)

- All `git` invocations go through one helper: `run_git(repo_path: Path, args: list[str], *, timeout: int = 30) -> subprocess.CompletedProcess`. This is the single place that sets `cwd`, environment (notably `GIT_TERMINAL_PROMPT=0` so git never blocks waiting for interactive credential input — credential negotiation happens via the credential helper below instead), and timeout.
- **Timeout table for network operations** (Phase 3): the 30s default is right for local ops but wrong for anything that traverses the network. `push`, `pull`, `fetch`, and `clone` override with `timeout=600` (10 minutes). `git ls-remote` probes (§5 Phase 3 step 5) use `timeout=15`. Nothing network-touching uses an unbounded timeout — a wedged connection must surface as `CLITimeoutError`, not hang the worker thread forever. A timeout kill is signalled by `subprocess.TimeoutExpired` inside `run_git`, which translates to `CLITimeoutError` at the write_ops layer.
- **Locale-stable output, or your parsing breaks for real users.** The same `env` must also set `LC_ALL=C` on every invocation: Phases 2–3 parse git's stdout/stderr ("Already up to date", "rejected", dirty-tree refusal messages) to derive typed results, and all of that pattern-matching silently stops matching the moment a user's `LANG`/`LC_MESSAGES` localizes git's strings. English-only parsing is a deliberate v1 constraint. Corollary: read stderr/stdout as bytes and decode with `errors="replace"` — a C-locale git can emit raw non-UTF-8 bytes for non-UTF-8 filenames, which a strict UTF-8 decode would turn into an exception instead of a diff.
- Credential negotiation: configure a custom `credential.helper` pointing at a small internal script (`core/git_credential_helper.py`, invoked as `git credential-wrench`) that reads/writes via `credentials/secret_service.py` instead of any host credential helper (per SRS constraint — never shell out to `git-credential-libsecret` on the host).
- **Multi-account (FR-4.5)**: also set `credential.useHttpPath = true` in the same repo-local config write — by default git does *not* send the URL path to credential helpers, only protocol+host, which is fine for a single account per host but ambiguous the moment a second account on the same host exists. With `useHttpPath` on, the helper receives enough to disambiguate by repo, not just host (exact matching logic in §5 Phase 3).
- Every `write_ops.py` function must raise a typed exception (`core/exceptions.py`) on non-zero exit, with the raw stderr attached, so the UI layer can show a real error instead of a generic failure.

### 4.3 `forge/capability.py` (the abstraction FR-5.1/5.7 depend on)

`forge/models.py` first — every adapter maps its provider's own response shape onto these, so nothing provider-specific ever reaches `ui/forge_panel/`:

```python
from dataclasses import dataclass


@dataclass
class PullRequest:
    id: str  # provider's native ID as a string — GitHub's are ints, GitLab/Forgejo
    # vary, normalize to str here so callers never branch on adapter identity
    title: str
    description: str
    source_branch: str
    target_branch: str
    state: str  # normalized: 'open' | 'merged' | 'closed' — each adapter maps its own
    # vocabulary onto this set (e.g. GitLab's 'opened' → 'open') internally
    url: str
    author: str
    created_at: str  # ISO 8601


@dataclass
class Issue:
    id: str
    title: str
    description: str
    state: str  # normalized: 'open' | 'closed'
    url: str
    author: str
    created_at: str


@dataclass
class CIStatus:
    state: str  # normalized: 'success' | 'failure' | 'pending' | 'unknown' — the
    # 'unknown' value matters: it's the correct result when a ref has no
    # CI configured at all, which must render differently in the UI than
    # 'pending' (CI configured but still running)
    url: str | None  # link to the CI provider's own detail page, when available
    description: str | None  # short human-readable status text, e.g. "3/3 checks passed"


@dataclass
class ForgeAccount:
    id: int
    provider: str  # 'github' | 'gitlab' | 'forgejo' | 'bitbucket'
    instance_url: str
    label: str
    username: str | None
    tls_ca_bundle_path: str | None  # CA bundle to verify against, or None = system store
    tls_insecure: bool              # True = skip TLS verification (schema stores 0/1;
    # this rich type converts at the row→dataclass seam; adapters read it in
    # _client construction, §5 Phase 4 step 2)
    secret_service_key: str  # unlike ForgeAccountRecord (§3.1) — this full ForgeAccount type,
    # with the key included, is only ever constructed to be handed to a ForgeAdapter's
    # constructor (§4.4 builds one adapter instance per operation) and, through it, to
    # the credentials backend. UI code may fetch it solely to pass it to the registry
    # inside one background operation (§5 Phase 4 step 6) — never to display, log, or
    # persist it; everywhere else the UI works with ForgeAccountRecord.
```

```python
from abc import ABC, abstractmethod
from enum import Flag, auto
from .models import PullRequest, Issue, CIStatus, ForgeAccount


class ForgeCapability(Flag):
    PULL_REQUESTS = auto()
    ISSUES = auto()
    CI_STATUS = auto()
    ISSUE_LINKING = auto()
    REVIEWS = auto()  # PR review actions — approve / request-changes / comment.
    # All four built-in providers support them (§11 item 14, resolved: the SRS's
    # "review" wording means real in-app actions), but the flag exists so a
    # third-party read-only adapter can simply not set it.


class ForgeAdapter(ABC):
    """One instance per configured forge_account row — the account is bound at
    construction and reachable as self.account for the adapter's lifetime."""

    provider_id: str  # e.g. 'github' — must match storage.forge_accounts.provider

    account: ForgeAccount  # bound by __init__; the registry constructs cls(account)
    # (§5 Phase 4 step 3), so no method below takes an account parameter

    def __init__(self, account: ForgeAccount) -> None:
        self.account = account

    @property
    @abstractmethod
    def capabilities(self) -> ForgeCapability: ...

    @abstractmethod
    def authenticate(self) -> None:
        """Validate the stored credential for self.account against the provider's
        identity endpoint; raise ForgeAuthenticationError (§4.3.A) on rejection"""

    @abstractmethod
    def list_pull_requests(self, owner: str, repo: str) -> list[PullRequest]: ...

    @abstractmethod
    def create_pull_request(
        self,
        owner: str,
        repo: str,
        *,
        title: str,
        source_branch: str,
        target_branch: str,
        description: str = "",
    ) -> PullRequest: ...

    @abstractmethod
    def submit_review(
        self,
        owner: str,
        repo: str,
        number: int,
        *,
        action: str,  # normalized: 'approve' | 'request_changes' | 'comment'
        body: str = "",
    ) -> None: ...
    """Submit a PR review. The action vocabulary is the three values above and
    nothing else; each provider maps it to its own endpoint shape (§5 Phase 4
    step 5). Per-user review threads stay view-in-browser for v1 — this method
    is the action surface only."""

    @property
    def supported_review_actions(self) -> frozenset[str]:
        """The subset of {'approve', 'request_changes', 'comment'} this provider
        can express (GitLab has no first-class request-changes, so a GitLab
        adapter returns {'approve', 'comment'} and the UI grays that button at
        render time — never a runtime surprise)."""
        return frozenset({"approve", "request_changes", "comment"})

    @abstractmethod
    def get_ci_status(self, owner: str, repo: str, ref: str) -> CIStatus: ...

    # Optional capabilities — default to NotImplementedError, only override if
    # `ForgeCapability.ISSUES in self.capabilities`
    def list_issues(self, owner: str, repo: str) -> list[Issue]:
        raise NotImplementedError(f"{self.provider_id} does not support issues")
```

Every adapter (`forge/adapters/*.py`) subclasses `ForgeAdapter`. UI code must check `adapter.capabilities` before showing a feature (e.g. don't render an "Issues" tab if `ForgeCapability.ISSUES` isn't set) rather than calling the method and catching `NotImplementedError`.

#### 4.3.A `forge/exceptions.py` — the exact hierarchy the adapters raise (referenced by §5 Phase 4, previously never defined)

```python
class ForgeError(Exception):
    """Root of every forge-layer failure. UI catches this for the generic
    'forge operation failed' path; concrete subclasses get tailored dialogs."""


class ForgeAdapterNotFoundError(ForgeError):
    """registry.get_adapter_for_account() found no entry point registered for
    the account's provider string. Means the install is broken or the provider
    column contains a typo — this is a bug-level failure, not user error."""

    def __init__(self, provider: str):
        super().__init__(f"No forge adapter registered for provider {provider!r}")
        self.provider = provider


class ForgeUnreachableError(ForgeError):
    """The instance URL could not be reached at all — connection refused, DNS
    failure, timeout. Distinct from auth failure: no amount of re-entering the
    token fixes this, so the UI guidance directs at the network/VPN, not the
    credential."""

    def __init__(self, instance_url: str, cause: str):
        super().__init__(f"Can't reach {instance_url}: {cause}")
        self.instance_url = instance_url


class ForgeAuthenticationError(ForgeError):
    """401 — the stored token is invalid or expired. The UI's response is the
    token re-entry flow, never a silent retry."""


class ForgeInsufficientScopeError(ForgeError):
    """403 — token is valid but lacks the permission this operation needs (e.g.
    a read-only token trying to create a PR). Carries a provider-specific hint
    on which scope to add so the fix dialog can be specific."""

    def __init__(self, message: str, *, scope_hint: str = ""):
        super().__init__(message)
        self.scope_hint = scope_hint


class ForgeRateLimitedError(ForgeError):
    """429 — per-adapter `Retry-After` parsing lives in the shared _request()
    helper (§5 Phase 4 step 2), which is why this class can carry a uniform
    retry_after_seconds across all four providers despite their response shape
    differences."""

    def __init__(self, retry_after_seconds: int):
        super().__init__(f"Rate limited — retry in {retry_after_seconds}s")
        self.retry_after_seconds = retry_after_seconds
```

These classes are deliberately **not** in `core/exceptions.py`: nothing in `core/` may import `forge` (§1's one-direction rule), and keeping forge errors in `forge/exceptions.py` makes that rule self-enforcing — an accidental `core → forge` import shows up as an import error in the first test run, not as a hidden layering violation.

### 4.4 `forge/registry.py` (entry-points discovery, FR-5.7)

```python
from importlib.metadata import entry_points
from .capability import ForgeAdapter
from .exceptions import ForgeAdapterNotFoundError

_ENTRY_POINT_GROUP = "wrench.forge_adapters"


def discover_adapters() -> dict[str, type[ForgeAdapter]]:
    """Returns {provider_id: AdapterClass} for every registered adapter,
    including the four built-in ones (which register themselves the same way
    third-party packages would — no special-casing in this function)."""
    adapters = {}
    for ep in entry_points(group=_ENTRY_POINT_GROUP):
        cls = ep.load()
        adapters[cls.provider_id] = cls
    return adapters


def get_adapter_for_account(account: "ForgeAccount") -> ForgeAdapter:
    adapters = discover_adapters()
    cls = adapters.get(account.provider)
    if cls is None:
        raise ForgeAdapterNotFoundError(account.provider)
    return cls(account)
```

`pyproject.toml` entry for the four built-in adapters (this is what makes discovery work — write it exactly like this):

```toml
[project.entry-points."wrench.forge_adapters"]
github    = "wrench.forge.adapters.github:GitHubAdapter"
gitlab    = "wrench.forge.adapters.gitlab:GitLabAdapter"
forgejo   = "wrench.forge.adapters.forgejo:ForgejoAdapter"
bitbucket = "wrench.forge.adapters.bitbucket:BitbucketAdapter"
```

A third-party package adding SourceForge or Radicle support later just needs its own `pyproject.toml` with a `[project.entry-points."wrench.forge_adapters"]` section — no Wrench core changes (this is the mechanism §7.1 of the SRS roadmap relies on).

### 4.5 `credentials/secret_service.py` — shared D-Bus logic, two thin context-specific subclasses

**The split that matters is not "different storage code" — it's "different failure message."** Every D-Bus Secret Service call below is identical whether Wrench is running under Flatpak, as an AppImage, or from a bare `pip install`; there is exactly one thing that legitimately differs by packaging context, and it's what to tell the user when `_collection()` can't reach a provider at all.

```python
import secretstorage
from secretstorage.exceptions import SecretServiceNotAvailableException, LockedException
from .backend import CredentialBackend, CredentialBackendUnavailableError

_ATTR_APP = "wrench"


class SecretServiceBackend(CredentialBackend):
    """Base class holding all the real D-Bus logic. Never instantiate this directly —
    use FlatpakSecretServiceBackend or AppImageSecretServiceBackend (below) via
    credentials.get_backend(), so unavailable_help_text() is always the right one
    for the context Wrench is actually running in."""

    def _collection(self):
        try:
            bus = secretstorage.dbus_init()
            collection = secretstorage.get_default_collection(bus)
        except SecretServiceNotAvailableException as e:
            raise CredentialBackendUnavailableError(self.unavailable_help_text()) from e
        if collection.is_locked():
            try:
                collection.unlock()  # typically triggers the OS's own keyring-unlock
                # prompt (GNOME Keyring/KWallet) — this call blocks
                # until the user responds to that prompt or cancels
            except LockedException as e:
                raise CredentialBackendUnavailableError(self.unavailable_help_text()) from e
        return collection

    def store_secret(self, key: str, secret: str, *, label: str) -> None:
        self._collection().create_item(
            label, {"application": _ATTR_APP, "key": key}, secret, replace=True
        )

    def get_secret(self, key: str) -> str | None:
        items = self._collection().search_items({"application": _ATTR_APP, "key": key})
        for item in items:
            return item.get_secret().decode("utf-8")  # first match; keys are unique by construction
        return None

    def delete_secret(self, key: str) -> None:
        for item in self._collection().search_items({"application": _ATTR_APP, "key": key}):
            item.delete()


class FlatpakSecretServiceBackend(SecretServiceBackend):
    def unavailable_help_text(self) -> str:
        return (
            "Wrench couldn't reach a secret storage service. Under Flatpak this is almost "
            "always a missing permission, not a missing service — check with Flatseal, or run:\n"
            "  flatpak override --talk-name=org.freedesktop.secrets io.github.uzair.Wrench\n"
            "then restart Wrench."
        )


class AppImageSecretServiceBackend(SecretServiceBackend):
    def unavailable_help_text(self) -> str:
        return (
            "Wrench couldn't reach a secret storage service. There's no sandbox permission "
            "to fix here — this means no Secret Service provider (GNOME Keyring, KWallet, or "
            "similar) is currently running. Most full desktop environments start one "
            "automatically; on a minimal window manager (i3, sway, etc.) you may need to "
            "start one yourself, e.g.:\n"
            "  gnome-keyring-daemon --start --components=secrets"
        )
```

`key` values are namespaced strings like `wrench:forge:{forge_account.id}` — this is the value stored in `forge_accounts.secret_service_key`. `search_items()` (not `get_all_items()` + manual filtering) is the correct `secretstorage` API for an attribute-based lookup — it asks the Secret Service daemon to do the filtering, rather than pulling every stored secret across the whole system into Python to check one field.

### 4.6 `core/snapshots.py` (FR-10.x rolling snapshot engine)

```python
from dataclasses import dataclass


@dataclass
class Snapshot:
    id: int
    created_at: str
    trigger_type: str  # 'commit' | 'timer' | 'pre_risky_op' | 'manual'
    is_manual: bool
    label: str | None
    ref_name: str


@dataclass
class SnapshotSettings:
    trigger_on_commit: bool
    trigger_on_timer: bool
    timer_interval_minutes: int
    trigger_before_risky_op: bool
    max_count: int
    max_age_days: int | None
    untracked_capture_mode: str  # 'none' | 'capped' | 'unlimited'
    untracked_per_file_cap_mb: int
    untracked_total_cap_mb: int


def take_snapshot(
    repo: "RepoHandle", trigger_type: str, *, label: str | None = None
) -> Snapshot | None: ...
def list_snapshots(repo: "RepoHandle") -> list[Snapshot]: ...
def restore_snapshot(repo: "RepoHandle", snapshot_id: int) -> None: ...
def prune_snapshots(repo: "RepoHandle") -> None: ...
def get_snapshot_settings(repo: "RepoHandle") -> SnapshotSettings: ...
def update_snapshot_settings(repo: "RepoHandle", settings: SnapshotSettings) -> None: ...
```

**Capture algorithm — `take_snapshot` (exact; don't substitute a different git primitive):**
1. Check the relevant toggle in `SnapshotSettings` first — e.g. if `trigger_type == "timer"` and `settings.trigger_on_timer` is False, return `None` immediately.
2. **Idempotency check**: run `run_git(["stash", "create"])`. If its stdout is empty (working tree exactly matches HEAD) *and* the most recent snapshot already points at current HEAD with an empty untracked set, skip and return `None` — otherwise the timer trigger fills the rolling window with identical no-op snapshots during idle time.
3. If step 2's stdout had a sha, that's `tracked_sha`. If it was empty (clean tree), use current HEAD's sha instead.
4. `run_git(["update-ref", f"refs/wrench/snapshots/{db_id}", tracked_sha])`. **Why a real ref and not a bare object reference**: an unreferenced object is only protected from `git gc` for a grace period (`gc.pruneExpire`, ~2 weeks by default); a real ref keeps it reachable indefinitely until this code deletes the ref during pruning — the same technique tools like `git-branchless` use. Note `git stash create` never touches the working tree, index, HEAD, or `refs/stash` — that's different from `git stash push`/`save`, which *would* mutate all of those; do not substitute them here.
5. If `settings.untracked_capture_mode != "none"` and untracked files exist (pygit2 status filtered to `GIT_STATUS_WT_NEW`): build one `tar.gz` at `paths.data_dir() / "snapshots" / str(repo_id) / f"{db_id}.tar.gz"` (§4.7 — not a hardcoded `$XDG_DATA_HOME` read; this is the app's own private data dir, so it needs **no additional Flatpak permission**, unlike repo folders). Per file: if `mode == "unlimited"`, or (file size ≤ `untracked_per_file_cap_mb` **and** running archive total ≤ `untracked_total_cap_mb`), add it and record `content_captured = 1`; otherwise record path + size with `content_captured = 0` and skip its content.
6. Insert the `snapshots` row (+ `snapshot_untracked_files` rows), then call `prune_snapshots(repo)`.

**Restore algorithm — `restore_snapshot` (exact — the naive approach silently corrupts branch history):**
1. UI confirms with the user first (destructive to current working tree/index) — not this function's job.
2. Call `take_snapshot(repo, trigger_type="pre_risky_op")` **first** — restoring is itself risky and should be undoable too.
3. **Do not use `git reset --hard <snapshot_sha>`.** The sha from `git stash create` is a synthetic commit with an unusual parent structure (HEAD-at-capture-time plus a separate index-state commit); resetting the branch onto it would splice that odd object into the branch's real history, corrupting the ancestry the user sees afterward.
4. Instead: `run_git(["read-tree", "--reset", "-u", snapshot_sha])` — resets the index and working tree to the snapshot's tree **without moving HEAD or any branch ref**. The user stays on their current branch with unchanged history; only the working tree/index change.
5. If `untracked_archive_path` is set, extract it over the working tree (confirm overwrite first). For any file with `content_captured = 0`, surface it in the confirmation UI as "existed at snapshot time but wasn't captured (over the size cap) — not restorable," so missing content isn't a silent surprise.

**Pruning algorithm — `prune_snapshots` (exact ordering; implements FR-10.4/10.5):**
1. Load all snapshots for the repo; split into `manual` (`is_manual=1`) and `auto` (`is_manual=0`), each oldest-first.
2. Apply `max_age_days` (if set) to the `auto` group only — manual snapshots are exempt.
3. If the combined count still exceeds `max_count`: delete oldest `auto` snapshots first; only begin deleting `manual` snapshots (oldest-first) once `auto` is fully empty and still over the limit.
4. Deleting one: `run_git(["update-ref", "-d", ref_name])`, delete `untracked_archive_path` if present, delete the DB row (cascades). The underlying git objects become unreachable but aren't removed from `.git/objects` until the next `git gc` — expected, not a bug.

**Trigger wiring** (implemented incrementally across Phases 1–2, not all at once — see §5):
- `commit` → `core/engine.py::commit()` calls `take_snapshot(repo, "commit")` after a successful commit.
- `timer` → a per-repo `QTimer`, active only while that repo is the focused/open one, firing every `settings.timer_interval_minutes`.
- `pre_risky_op` → `merge()`, `rebase()`, `delete_branch()`, and `restore_snapshot()` itself all call `take_snapshot(repo, "pre_risky_op")` before doing anything destructive.
- `manual` → a UI button calling `take_snapshot(repo, "manual", label=user_text)` — the only path setting `is_manual=True`.

### 4.7 Platform abstraction layer (FR-11.1–11.3 — mandatory in v1, second implementation deferred to SRS §7.3)

Three narrow seams, each isolating exactly one platform-specific concern behind an interface that today has only a Linux implementation. The discipline that matters isn't the interface design (all three are small) — it's **never bypassing them**: no other file in the codebase reads `$SSH_AUTH_SOCK`, constructs an XDG path, or talks to `secretstorage` directly. Every call site goes through these three modules, from the first commit that needs them, not retrofitted later.

The Flatpak manifest (§6.1, Phase 0 step 6) targets the `org.kde.Platform` runtime — a packaging/distribution choice (it's the most complete, best-tested Qt-providing runtime on Flathub today), not an application-code one. Building on `org.kde.Platform` does not require, and here deliberately does not use, KDE Frameworks Python APIs (KConfig/KXmlGui/KIO) inside `src/wrench` — FR-11.4 and this runtime choice operate at different layers and aren't in tension.

**`credentials/backend.py`** — the interface `secret_service.py` (§4.5) already shapes itself to. Note the addition of `unavailable_help_text()`: it's abstract here specifically because it's the *only* thing that should ever differ between Linux packaging contexts — see the corrected factory below for why.

```python
from abc import ABC, abstractmethod


class CredentialBackendUnavailableError(Exception):
    """Raised when no secret storage provider could be reached. The message is
    always context-specific remediation text, not a generic failure — see
    SecretServiceBackend._collection() and each subclass's unavailable_help_text()."""


class CredentialBackend(ABC):
    @abstractmethod
    def store_secret(self, key: str, secret: str, *, label: str) -> None: ...
    @abstractmethod
    def get_secret(self, key: str) -> str | None: ...
    @abstractmethod
    def delete_secret(self, key: str) -> None: ...
    @abstractmethod
    def unavailable_help_text(self) -> str:
        """User-facing remediation shown when the backend can't be reached at all."""
```

**Corrected factory** — an earlier version of this function checked only `sys.platform`, which returns the identical value (`"linux"`) whether Wrench is running under Flatpak, as an AppImage, or from a plain `pip install`. That check cannot tell these three contexts apart, which defeats the point of having context-specific remediation text at all:

```python
# credentials/__init__.py
import os
import sys
from .backend import CredentialBackend


def _detect_packaging_context() -> str:
    """Returns 'flatpak', 'appimage', or 'bare'. Checked in this order because a
    Flatpak sandbox could in principle still see an inherited APPIMAGE env var from
    outside the sandbox in some edge case — Flatpak's own markers take priority."""
    if os.environ.get("FLATPAK_ID") or os.path.exists("/.flatpak-info"):
        return "flatpak"
    if os.environ.get("APPIMAGE"):
        return "appimage"
    return "bare"  # plain `pip install` / running from source, not packaged at all


def get_backend() -> CredentialBackend:
    if sys.platform.startswith("linux") or sys.platform.startswith("freebsd"):
        context = _detect_packaging_context()
        if context == "flatpak":
            from .secret_service import FlatpakSecretServiceBackend

            return FlatpakSecretServiceBackend()
        # 'appimage' and 'bare' share a backend: both are unsandboxed, and both fail
        # the same way (no Secret Service *provider* running) — there's no separate
        # permission system to give 'bare' its own remediation text, so a third class
        # would just duplicate AppImage's, which is why v1 ships exactly two, not three
        from .secret_service import AppImageSecretServiceBackend

        return AppImageSecretServiceBackend()
    raise NotImplementedError(
        f"No CredentialBackend for platform {sys.platform!r} yet — see SRS §7.3"
    )
```

Every caller (the credential helper in §5 Phase 3, `forge_accounts.py`) calls `credentials.get_backend()` once and uses the returned object — never imports `secret_service` directly, and never checks packaging context itself. That check now happens in exactly one place.

**`core/paths.py`** — wraps `platformdirs` rather than calling it ad hoc at each call site, so a Wrench-specific convention (e.g. the exact app name/author string passed to `platformdirs`) is defined once:

```python
import platformdirs

APP_NAME = "wrench"


def data_dir() -> "Path":
    return Path(platformdirs.user_data_dir(APP_NAME))


def config_dir() -> "Path":
    return Path(platformdirs.user_config_dir(APP_NAME))


def state_dir() -> "Path":  # used by FR-9.2's log file
    return Path(platformdirs.user_state_dir(APP_NAME))
```

`storage/db.py` (§3.1) calls `paths.data_dir() / "wrench.db"`, and `core/snapshots.py`'s untracked-archive storage (§4.6) calls `paths.data_dir() / "snapshots" / ...` — neither hardcodes `$XDG_DATA_HOME` or any other env var directly. On Linux, `platformdirs` resolves this to the same path either way; the payoff is invisible today and only matters the day a second platform shows up.

**`core/ssh_agent.py`** — deliberately the thinnest of the three, because it's the one where v1's Linux behavior and a hypothetical Windows implementation would look *nothing* alike (Unix socket path vs. named-pipe handle), so isolating it matters more than the interface being elegant:

```python
import os


def get_ssh_auth_socket() -> str | None:
    """Linux/BSD: reads $SSH_AUTH_SOCK directly. A Windows implementation would
    resolve \\\\.\\pipe\\openssh-ssh-agent instead — entirely different mechanism,
    which is exactly why this is its own one-line function and not inlined
    wherever push/pull needs it (§5 Phase 3, step 4)."""
    return os.environ.get("SSH_AUTH_SOCK")
```

### 4.8 Threading model (a gap in earlier revisions of this document — every phase depends on this)

**The problem, stated plainly**: every `core.engine` function described in §4.1 is a plain, blocking Python call. `run_git(["clone", ...])` can legitimately take minutes on a large repo over a slow connection; `run_git(["push", ...])`, `merge()`, and `rebase()` can each take seconds to minutes too. If any of these are called directly from a button's `clicked` slot, they run **on Qt's main thread — the same thread that repaints the window and processes clicks**. The result isn't a slow operation with a progress bar; it's a frozen, "Not Responding" window, because nothing else can happen until the blocking call returns. This was never addressed anywhere in Phases 0–8 before now, which means every UI-triggered operation described so far has an implicit bug unless this pattern is applied.

**The fix — every write operation and every progress-capable operation goes through a worker thread, never called directly from a UI slot:**

```python
# ui/workers.py — one shared helper, used by every UI call site that invokes core.engine
from PySide6.QtCore import QObject, QThread, Signal


class GitOperationWorker(QObject):
    """Runs exactly one core.engine call on a background thread. Create a new
    instance per operation — do not reuse one worker across multiple calls."""

    finished = Signal(object)  # emits the function's return value on success
    failed = Signal(Exception)  # emits the exception on failure — connect this to
    # the same error-dialog code core.engine's typed
    # exceptions (§5 Phase 1 step 5) already feed
    progress = Signal(int)  # 0-100; only emitted by clone/push/pull/fetch

    def __init__(self, fn, *args, **kwargs):
        super().__init__()
        self._fn, self._args, self._kwargs = fn, args, kwargs

    def run(self):
        try:
            if "progress_cb" in self._fn.__code__.co_varnames:
                self._kwargs.setdefault("progress_cb", self.progress.emit)
            self.finished.emit(self._fn(*self._args, **self._kwargs))
        except Exception as e:
            self.failed.emit(e)


def run_in_background(
    fn, *args, on_finished=None, on_failed=None, on_progress=None, **kwargs
) -> QThread:
    """Standard call pattern. Returns the QThread — the caller MUST keep a reference
    to it (e.g. as self._active_thread on the widget) for as long as it might be
    running. A QThread that gets garbage-collected mid-run is a real, silently-crashing
    bug in PySide6, not a theoretical one — this is the single most common way a first
    attempt at this pattern breaks."""
    thread = QThread()
    worker = GitOperationWorker(fn, *args, **kwargs)
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    if on_finished:
        worker.finished.connect(on_finished)
    if on_failed:
        worker.failed.connect(on_failed)
    if on_progress:
        worker.progress.connect(on_progress)
    worker.finished.connect(thread.quit)
    worker.failed.connect(thread.quit)
    thread.start()
    return thread
```

**Which calls need this, which don't:**
- **Always background**: `clone_repo`, `push`, `pull`, `fetch`, `merge`, `rebase` — all subprocess-based, all can run long. Never call these synchronously from a slot.
- **Synchronous is fine by default**: `get_status`, `get_diff`, `blame` on typical repos — these complete well within the NFR's 200ms budget and a worker-thread round-trip would add more latency than it saves for the common case.
- **The exception that proves the rule**: `get_log` on a 100k+-commit repo (the same repo size the commit-graph NFR explicitly targets) can itself take long enough to matter. `ui/commit_graph/`'s initial load calls `get_log` through `run_in_background` too, not synchronously — the one read-path operation this applies to.

**Cancellation, specifically for `clone_repo`**: keep the `subprocess.Popen` handle (not just its final `CompletedProcess`) so a "Cancel" button can call `.terminate()`, escalating to `.kill()` after a short grace period if the process doesn't exit. A cancelled or failed clone must never leave a half-populated directory at the user's chosen destination — clone into a temp directory first (`tempfile.mkdtemp()`), and only `shutil.move()` it to the real destination on confirmed success. This also means a cancelled clone requires zero cleanup at the destination path, since nothing was ever written there.

**SQLite and background threads**: since snapshot triggers (the timer especially, §4.6) and now these worker threads can touch `storage/*.py` from a thread other than the main one, `storage/db.py`'s connection must be opened with `check_same_thread=False`, and every CRUD function must acquire a single module-level `threading.Lock()` before executing and release it after. This is a deliberately coarse-grained lock, not a connection pool or per-thread connections — the DB here holds small metadata rows (repo registry, settings, snapshot records), not git objects, so serializing all access through one lock is simple, correct, and not a real performance bottleneck at this scale. Don't over-engineer this into a connection-per-thread design; that solves a contention problem this app doesn't have.

---

## 5. Phased Roadmap

Each phase should be independently shippable/testable — don't let phases bleed together. Every phase below lists concrete subtasks and an explicit **acceptance check** — a command or manual test that proves the phase is done, so "done" isn't a judgment call.

### Phase 0 — Project Setup
**Prerequisites:** none — this is the starting point.
1. `git init` in an empty directory. Add `LICENSE` — the full, unmodified AGPL-3.0 text (pulled verbatim from `https://www.gnu.org/licenses/agpl-3.0.txt`, not paraphrased or reformatted — license texts need to match exactly to be unambiguous). Add a `README.md` stub containing only: a one-paragraph project description, a "Status: pre-alpha, under active development" line, and a placeholder "Building" heading to be filled in properly at Phase 7 — don't write build instructions yet, since the tooling itself isn't finalized until later steps in this same phase.
   - Create `dev/planning/` and move this SRS and this implementation plan into it (`dev/planning/srs.md`, `dev/planning/implementation-plan.md`) — commit them normally, they're project history worth keeping, not scratch. Create `dev/scratch/` as an empty directory (a `.gitkeep` file inside it, since git doesn't track empty directories) for whatever local notes/sketches don't belong in a tracked planning doc. Write `dev/README.md` in about five lines: what `planning/` is for, that `scratch/` is gitignored on purpose and nothing put there should be assumed to survive a fresh clone, and a pointer back to `dev/planning/implementation-plan.md` §0 for how to actually execute the plan.
   - Write `.gitignore` now, before any of the directories it references exist, so nothing generated ever gets accidentally committed in a moment of forgetting later:
     ```gitignore
     # Python
     __pycache__/
     *.pyc
     .venv/
     *.egg-info/

     # Build outputs — generated, never committed; see packaging/build-all.sh
     build-dir/
     .flatpak-builder/
     dist/
     linux/               # Briefcase's generated AppImage build tree (§6.3)

     # Local-only scratch space (dev/planning/ is NOT here — that's tracked deliberately)
     dev/scratch/*
     !dev/scratch/.gitkeep
     ```
2. `pyproject.toml`: PEP 621 `[project]` metadata (`name = "wrench"`, `version = "0.1.0"`, `requires-python = ">=3.12"`), `dependencies` (`PySide6`, `pygit2`, `secretstorage`, `platformdirs`, `httpx`, `watchdog`), `[project.optional-dependencies].dev` (`pytest`, `pytest-qt`, `responses`, `ruff`, `black`, `briefcase` — the AppImage tool, §6.3), and the `[project.entry-points."wrench.forge_adapters"]` section from §4.4 — add this now even though the adapters it references don't exist yet; a forward-declared, empty-feeling entry-points section costs nothing today and means Phase 4 doesn't have to remember to add it later. Also add the `[project.scripts]` entry for `git-credential-wrench` (§5 Phase 3 step 2) for the same reason: declare the shape now, fill in the implementation later.
3. Linting config, in `pyproject.toml` itself rather than a separate `ruff.toml` (keeps config in one file): `[tool.ruff]` enabling at minimum `E`/`F` (pycodestyle/pyflakes basics), `I` (import sorting — replaces a separate isort step), and `B` (bugbear, which catches real bugs like mutable default arguments). `[tool.black]` with `line-length = 100` — chosen over Black's default 88 because §4's type-annotated function signatures get long; pick one value and commit to it rather than leaving it at an undecided default.
4. `.pre-commit-config.yaml`: hooks running `ruff --fix` and `black` on every commit, activated via `pre-commit install` (already in §0.3's setup commands). This catches formatting/lint issues locally before they reach CI — it doesn't replace CI's own lint job (§7), which stays the real enforcement gate for contributors who haven't run `pre-commit install`.
5. Create the full `src/wrench/` directory skeleton from §3 — every file listed there should exist now, even if its entire content is a module docstring naming the FR(s) it implements (e.g. `"""FR-1.9: detect and clear stale .git/index.lock files."""`) plus a `raise NotImplementedError` in any stub functions. Doing this now, before real logic exists, means every later phase is "fill in this already-named function" rather than "decide where this code should live" — that decision gets made exactly once, here.
6. `packaging/flatpak/io.github.uzair.Wrench.yaml`: a minimal but real manifest — `app-id: io.github.uzair.Wrench`, `runtime: org.kde.Platform`, `runtime-version` set to whatever the current KF6 Flatpak runtime actually is at implementation time (check `flatpak remote-info flathub org.kde.Platform` rather than hardcoding a guess that may already be stale), `sdk: org.kde.Sdk`, `command: wrench` (matching the console-script entry from step 2), and a single `modules` entry that `pip install`s the still-nearly-empty package and confirms `QMainWindow().show()` launches. Leave `finish-args` (the permissions list) minimal/empty at this stage — §6.1's least-privilege permissions are added deliberately in Phase 6, not accumulated ad hoc as each feature phase happens to need something.
7. Generate pinned pip sources for every dependency in step 2 via `flatpak-pip-generator` (from the `flatpak-builder-tools` repo) and add the resulting `sources:` block to the manifest's Python module. **Why this has to happen now, not later**: Flathub's real build infrastructure runs network-isolated after an initial source fetch — a manifest that works locally via a live `pip install <package>` call will fail on Flathub's builders with a network error. Discovering that at Phase 6 instead of Phase 0 means re-diagnosing a packaging problem on top of a much larger, feature-complete codebase instead of an empty one.
8. **Acceptance check**: run `flatpak-builder --user --install build-dir packaging/flatpak/io.github.uzair.Wrench.yaml` once to fetch sources, then re-run with `flatpak-builder --disable-download build-dir packaging/flatpak/io.github.uzair.Wrench.yaml` against those already-fetched sources — this simulates Flathub's network-isolated build and both invocations must succeed. Then `flatpak run io.github.uzair.Wrench` must open a visible, empty `QMainWindow`. Do not proceed to Phase 1 on a manifest that only works with live network access.

### Phase 1 — Core Local Git Engine + MVP UI
**Prerequisites:** Phase 0's acceptance check passed (skeleton Flatpak builds and launches an empty window).
1. `core/read_ops.py`: four functions against a `pygit2.Repository` (via `RepoHandle.pygit2_repo`):
   - `get_status(repo) -> RepoStatus`: use `pygit2.Repository.status()` (returns a dict of path → flag bitmask) and translate the `GIT_STATUS_*` flags into `RepoStatus`/`FileChange` — staged vs unstaged is read directly off whether the `INDEX_*` or `WT_*` bit is set, not a separate query. Populate `ahead`/`behind` via `repo.ahead_behind(local_oid, upstream_oid)` when an upstream is configured, else default to `0, 0`. Populate `has_conflicts` via `repo.index.conflicts is not None`. **Two states easy to get wrong, both must be handled explicitly, not left to whatever pygit2 happens to return:** (1) *detached HEAD* — check `repo.head_is_detached`; if true, set `is_detached=True`, `current_branch=None`, `detached_head_sha=str(repo.head.target)`, and skip the ahead/behind lookup entirely (there's no branch to compare against an upstream). (2) *unborn branch* — a freshly-`init_repo`'d repository with zero commits; check `repo.head_is_unborn` (a distinct pygit2 property from `head_is_detached`) — `repo.head.target` raises on an unborn repo, so guard this check *before* touching `repo.head.target` anywhere else in this function. In this state, `current_branch` is still the real default-branch name (from `repo.head.shorthand`, which works even when unborn), `is_detached=False`, `ahead=0`, `behind=0`.
   - `get_diff(repo, path, *, staged) -> Diff`: `repo.diff(cached=staged)` filtered to the one path; return hunks with old/new line numbers, since the UI's hunk-level staging (step 6) needs that detail directly.
   - `get_log(repo, filter=None, *, limit=100, offset=0) -> list[Commit]`: walk `repo.walk(repo.head.target, GIT_SORT_TOPOLOGICAL | GIT_SORT_TIME)`, paginated via `limit`/`offset` rather than materializing full history at once — see the NFR performance target for why. Same unborn-branch guard as `get_status` applies here: if `repo.head_is_unborn`, return `[]` immediately rather than calling `repo.walk(repo.head.target, ...)`, which raises on an unborn repo.
   - `blame(repo, path) -> list[BlameLine]`: `repo.blame(path)`, one `BlameLine(line_no, commit_sha, author, line_content)` per line.
   Unit tests in `tests/unit/core/test_read_ops.py` against throwaway repos (`tests/fixtures/git_repos.py` — a `pytest.fixture` doing `pygit2.init_repository(tmp_path)` plus fixture commits); include a zero-commit repo (`get_log` must return `[]`, not raise; `get_status().current_branch` must still be a real name, not `None`), a detached-HEAD repo (checkout a commit sha directly, assert `is_detached=True` and `current_branch is None`), and a binary file (`get_diff` must report it as binary rather than attempting a text diff).
2. `core/write_ops.py`: the `run_git()` helper exactly per §4.2, then the thin wrappers over it:
   - `commit(repo, message, *, amend=False)`: `run_git(["commit", "-m", message] + (["--amend"] if amend else []))`; reject an empty/whitespace-only `message` *before* calling git (raise `EmptyCommitMessageError`) rather than surfacing git's own less-friendly error.
   - `create_branch(repo, name, from_ref="HEAD")`: `run_git(["branch", name, from_ref])`; a name collision exits nonzero — let that become `BranchAlreadyExistsError` via `core/exceptions.py`, don't swallow it.
   - `switch_branch(repo, name)`: `run_git(["switch", name])` — not the older `checkout`; `switch` is git's modern, branch-specific command and won't accidentally also touch working-tree files the way some `checkout <path>` forms can.
   - `delete_branch(repo, name, force=False)`: `run_git(["branch", "-D" if force else "-d", name])`; lowercase `-d` refuses to delete an unmerged branch — surface that refusal as a UI confirmation ("this branch has unmerged commits — delete anyway?") that retries with `force=True`, rather than defaulting to force and silently losing commits.
   - `rename_branch(repo, old, new)`: `run_git(["branch", "-m", old, new])`.
   - `stash_create/apply/drop`: `run_git(["stash", "push", "-m", message])` / `["stash", "apply", stash_id]` / `["stash", "drop", stash_id]` — this is git's *real* stash (`stash push`, which does modify the working tree), a different thing from the `git stash create` primitive the snapshot system uses internally (§4.6), which deliberately modifies nothing. Don't conflate the two just because they share a subcommand name.
3. `core/identity.py`: FR-1.1 — `run_git(["config", "--get", "user.name"])` and the same for `user.email`, checked once (git already falls back from repo-level to global automatically, so a single call per key is enough — no separate `--global` query needed). If either is empty/unset, raise `IdentityRequiredError(missing=["name", "email"])`, caught by `ui/main_window.py` and turned into a blocking two-field dialog. On submit, write `run_git(["config", "user.name", value])` — repo-local, not `--global`, since a repo-local identity is the safer default and composes correctly with FR-7.1's per-repo identity profiles later. Validate the email field with a simple `"@" in value and "." in value.split("@")[-1]` check, not full RFC 5322 validation — unnecessary complexity here that would also reject some technically-valid addresses.
4. `storage/schema.sql` + `storage/db.py` + `storage/repo_registry.py`: create the schema from §3.1. **Thread-safety (needed starting here, not deferred)**: open the connection with `sqlite3.connect(path, check_same_thread=False)`, and wrap every CRUD function across every `storage/*.py` module in a single module-level `threading.Lock()` (acquired before the query, released after) — §4.8 explains why this coarse-grained approach is the right call rather than a connection pool. **Corruption handling**: wrap the initial connection open in a `try/except sqlite3.DatabaseError` — a corrupted DB file (power loss mid-write, truncated by a full disk) raises this on the very first query, not on connect; on catching it, back up the corrupt file (rename to `wrench.db.corrupt-{timestamp}`) and create a fresh one rather than crashing on every subsequent launch, and surface a one-time notice telling the user their repo registry/settings were reset (their actual git repos and commits are entirely unaffected — this database only holds Wrench's own metadata). Then:
   - `add_repo(path, display_name=None) -> int`: inserts into `repos`, defaulting `display_name` to `path.name`; returns the new row's `id`.
   - `list_repos() -> list[RepoRecord]`: `SELECT * FROM repos ORDER BY last_opened_at DESC NULLS LAST`.
   - `remove_repo(repo_id) -> None`: deletes the row (cascades to `repo_identity_overrides`, `repo_forge_links`, `snapshots`, `snapshot_settings` via their `ON DELETE CASCADE` FKs) — **this never touches the actual filesystem repo**, it only forgets it.
   - `update_last_opened(repo_id) -> None`: called from `open_repo`, sets `last_opened_at = datetime('now')`.
   - `mark_missing(repo_id) -> None`: sets `is_missing = 1`, called when `open_repo` finds the stored `path` doesn't exist.
   - `relocate_repo(repo_id, new_path) -> None`: updates `path` in place and resets `is_missing = 0` — critically, this updates the existing row rather than delete-and-recreate, so `repo_identity_overrides`/`repo_forge_links`/`snapshots` rows (all keyed on the same `repo_id`) survive a user moving a folder.
5. `core/engine.py`: wire the façade functions from §4.1 on top of steps 1–4. The real job here is **error translation**, not new logic: every `pygit2.GitError` and every nonzero-exit `run_git` call must be caught at this layer and re-raised as a typed exception from `core/exceptions.py` (e.g. `WrenchRepoNotFoundError`, `BranchAlreadyExistsError`) — UI code should never catch `pygit2.GitError` or `subprocess.CalledProcessError` directly; if it does, that's a gap in this façade. `open_repo(path)` specifically: check `repo_registry` first — an unregistered path gets an implicit `add_repo`; a registered-but-missing path (`is_missing`) raises `WrenchRepoNotFoundError` immediately rather than attempting to open a nonexistent directory and surfacing a confusing pygit2 error instead.
6. Staging granularity (FR-1.4): `stage_file` (whole-file, via pygit2 index manipulation: `index.add(path); index.write()`). For `stage_hunk`/`stage_lines`, pygit2 has no clean hunk-level staging API, so construct a partial unified-diff patch and apply it with `git apply --cached` — a deliberate, documented exception to the read/write split in §1, not a violation of it. **Exact algorithm (don't improvise a different one):**
   a. Get the full diff for the file via pygit2's diff API (`repo.diff(cached=False)` filtered to the one path) — this gives hunks with line-level detail.
   b. For `stage_hunk(path, hunk_id)`: identify the target hunk by its index in that diff, and emit *only* that hunk's lines as a standalone patch, with a header (`--- a/{path}`, `+++ b/{path}`, `@@ -{old_start},{old_count} +{new_start},{new_count} @@`) whose line numbers describe only that one hunk, not the whole file.
   c. For `stage_lines(path, line_numbers)`: same as (b), but first narrow the containing hunk further so only the requested `+`/`-` lines are marked as changes and every other line in that hunk's range is re-emitted as unchanged context (a leading space) — this synthetic, smaller hunk is what makes line-level staging different from hunk-level.
   d. Write the constructed patch text to a temp file and run `run_git(["apply", "--cached", tmp_patch_path])`.
   e. If `git apply --cached` exits nonzero, raise a typed `PatchApplyError` with stderr attached — never silently fall back to whole-file staging, since that would stage more than the user asked for.
   **Edge cases this algorithm must handle, each a real way a first attempt breaks:**
   - **Binary files**: check `Diff.is_binary` before attempting hunk/line staging at all — there's no meaningful "hunk" for a binary diff. `stage_hunk`/`stage_lines` on a binary file should raise a clear `BinaryFileStagingError` (caught by the UI to disable hunk/line controls and offer only whole-file staging) rather than constructing a nonsensical text patch.
   - **Pure additions** (new file, or a hunk that's 100% new lines): `old_start`/`old_count` are `0, 0` in the patch header — don't assume the old side always has at least one line.
   - **Pure deletions** (last hunk of a file being fully removed): `new_start`/`new_count` are `0, 0` symmetrically.
   - **Mode-only changes** (e.g. `chmod +x` with no content change): pygit2's diff reports this as a separate mode-change entry with an empty hunk list — `stage_hunk` has nothing to construct a patch from here; route this case to `stage_file` instead (mode changes aren't meaningfully partial-stageable) and surface that in the UI as a single "permission change" row rather than a hunk.
   - **No trailing newline**: if the file's last line has no trailing `\n`, the constructed patch must include a literal `\ No newline at end of file` marker line immediately after that line, exactly as git itself emits it — omitting this makes `git apply` reject the patch outright on this specific case, not silently mishandle it.
   Unit test: a fixture file with 3+ separate hunks; staging one hunk must leave the other two under `get_status().unstaged`.
7. `watcher/inotify_watcher.py`: FR-1.8, via `watchdog.observers.Observer` watching the repo's working tree, filtering out any event whose path starts with `.git/` (the directory's own internal churn during commits would otherwise trigger spurious refreshes). **Watch for moved/renamed events, not just modified ones**: many editors (vim, most JetBrains IDEs, several others) save atomically by writing to a temp file and renaming it over the original, rather than modifying the original file in place. A watcher that only subscribes to `on_modified` never fires for these saves — it needs `on_moved` too (`watchdog`'s `FileSystemEventHandler.on_moved`, firing on `IN_MOVED_TO` under the hood), checking whether the event's *destination* path is inside the watched tree, since that's what a rename-based save looks like from the filesystem's perspective. **Exact debounce mechanism (use this, not a bare `time.sleep`, which would block the Qt event loop):** construct a `QTimer` with `setSingleShot(True)`, connected once to a `_do_refresh` slot. On every filesystem event — modified or moved — call `self._debounce_timer.start(300)` — calling `.start()` on a running single-shot `QTimer` restarts its countdown rather than stacking timers, so a burst of many file-save events in under 300ms collapses into exactly one `_do_refresh`, fired 300ms after the *last* event in the burst. `_do_refresh` emits a Qt signal (e.g. `status_changed = Signal()`) that `ui/diff_view/` and `ui/commit_graph/` connect to — the watcher never imports or calls into `ui` directly, keeping §1's one-directional dependency rule intact. Unit test: save a file via the write-to-temp-then-rename pattern directly (not a plain in-place write) and assert the watcher's refresh signal still fires — a naive `on_modified`-only implementation silently fails this case.
8. `watcher/polling_fallback.py`: FR-1.8 fallback — catch `OSError` (`ENOSPC`, the inotify-limit errno) from the watcher, log it, switch to a `QTimer`-driven poll (e.g. every 2s) and show a persistent UI banner explaining the fallback is active.
9. `core/lock_recovery.py`: FR-1.9. **Exact algorithm (deliberately simple — do not attempt to inspect the PID that created the lock):** under Flatpak sandboxing the app cannot reliably see host process IDs, so a PID-liveness check would be unreliable; this design uses mtime only.
   a. Before any write op in `run_git`/`write_ops.py`, check whether `{repo_path}/.git/index.lock` exists.
   b. If it exists and `now - mtime < 5 seconds`, assume a concurrent legitimate git operation is in progress (e.g. run from a terminal alongside the app); wait 1s and check once more rather than treating it as stale immediately.
   c. If it still exists and `now - mtime >= 5 seconds`, treat it as stale. Do **not** delete it automatically — raise a `StaleLockDetectedError` that the UI turns into a confirmation dialog ("A previous operation may have been interrupted. Remove the lock file and continue?"). Only unlink the file after explicit user confirmation.
   d. On app startup, run this same check against every registry repo with `is_missing = 0`, so a stale lock from a crash is surfaced on next launch, not only on next write attempt.
   Unit test: create `.git/index.lock` and backdate its mtime with `os.utime`; assert the check returns "stale." Create one with mtime = now; assert it returns "recent, not stale."
10. `core/reflog.py`: FR-1.10.
    - `get_reflog(repo) -> list[ReflogEntry]`: via pygit2's reflog API (`repo.head.log()`, iterating `RefLogEntry` objects with `.oid_old`, `.oid_new`, `.message`, `.committer.time`), mapped into `ReflogEntry(sha, message, timestamp)`, listed newest-first.
    - `restore_to_ref(repo, sha)`: `run_git(["reset", "--hard", sha])` — **unlike the snapshot system's restore (§4.6), this legitimately uses `reset --hard`**, because reflog recovery is explicitly about moving the *current branch* back to a prior state of itself, not about restoring a synthetic side-object without disturbing history. Gate this behind a confirmation dialog in `ui/main_window.py` stating plainly that it discards uncommitted changes — it's destructive to the working tree.
11. `core/snapshots.py` + `storage/snapshots.py`: FR-10.1–10.5, FR-10.7 — implement `take_snapshot`/`prune_snapshots` exactly per §4.6, with the `commit` and `manual` triggers wired now (`timer` and `pre_risky_op` are wired in Phase 2, once a timer surface and risky operations both exist). Include `delete_branch` as a `pre_risky_op` trigger point here in Phase 1, since branch deletion already exists by this point. **Two edge cases specific to this feature:**
    - **Submodules**: `git stash create` — the primitive the whole capture algorithm depends on (§4.6) — has known, longstanding limitations with submodule state; it does not reliably capture uncommitted changes *inside* a submodule the way it does for the parent repo. This is a real, documented git limitation, not a Wrench bug to fix. Don't attempt to work around it in v1 — instead, if `repo.listall_submodules()` is non-empty when `take_snapshot` runs, note this honestly: the snapshot's `label` (for manual snapshots) or a UI tooltip should indicate "submodule state not captured" so a restore doesn't silently produce a false sense of completeness.
    - **Concurrent triggers**: two triggers can fire close together (e.g. a commit completes right as the timer also fires). Since `take_snapshot`'s idempotency check (§4.6 step 2) already compares against the *most recent* snapshot before doing any work, the second call in a near-simultaneous pair naturally becomes a no-op rather than a duplicate — but this only holds if the DB insert and the idempotency check happen inside the same `threading.Lock()`-protected section (§4.8) as one atomic unit. If they're two separate lock acquisitions, a race exists: both calls could pass the "no recent snapshot" check before either has inserted its row. Implement the check-then-insert as a single locked operation, not two.
12. UI shell:
    - `ui/main_window.py`: a `QMainWindow` containing a `QSplitter` — sidebar on the left (`ui/sidebar/`), tabbed content area on the right. This is the lifecycle owner of the single currently-open `RepoHandle` and its per-repo `QTimer` instances (status-watcher debounce now, the snapshot timer once Phase 2 adds it — "a natural place to own its lifecycle" in that step refers to this class).
    - `ui/sidebar/`: a `QListWidget` populated from `repo_registry.list_repos()`, each row showing `display_name`, `last_branch`, and a small indicator icon when `is_missing` is set. Clicking a row calls `core.engine.open_repo(path)` and swaps the content area to that repo's tabs.
    - `ui/diff_view/`: the default tab (FR-2.1) — a two-pane layout: a `QListWidget` of changed files on the left (from `RepoStatus.staged`/`.unstaged`/`.untracked`, each row carrying a checkbox reflecting staged state), and a syntax-highlighted diff render of the selected file on the right, built from `get_diff`'s hunk data. Toggling a file's checkbox calls `stage_file`/`unstage_file`; a right-click context menu on a hunk exposes "Stage hunk" (`stage_hunk`), and drag-selecting specific lines within a hunk exposes "Stage selected lines" (`stage_lines`) — this is the concrete UI surface for the staging algorithm in step 6.
13. **Acceptance check**: `pytest tests/unit/core tests/unit/storage -v` all green; manual QA — install via Flatpak, add a repo, stage/commit a line-level change, create/switch/delete a branch, stash and reapply, kill the app mid-write to leave a lock file and confirm the app detects and offers recovery on next launch, confirm a snapshot appears after a commit and after a manual "snapshot now" click.

### Phase 1.5 — UI Shell Overhaul
**Prerequisites:** Phase 1's acceptance check passed. The core engine, storage, watcher, and diff view all work. This phase restructures the UI *around* those existing components — it does not rewrite any core logic.

**Design reference:** All layout, widget specs, interactions, and edge cases for this phase are defined in [`ui-planning.md`](file:///home/uzair/Projects/wrench/dev/planning/ui-planning.md). This section specifies only the **implementation steps and file-level changes** — for visual layouts, exact widget properties, and behavioral edge cases, cross-reference the corresponding `ui-planning.md` section cited in each step.

**Scope boundary:** This phase delivers the tab-system shell, the fully redesigned Changes tab, and a **skeleton History tab** (container + empty state + placeholder for the commit graph widget). The full commit graph rendering, lane-assignment algorithm, and search/filter implementation remain in Phase 2 — this phase creates the slot they plug into.

1. **Window chrome and menu bar** (`ui/main_window.py` rewrite) — ref: `ui-planning.md` §1
   - Replace the existing `QSplitter`-based layout with a `QVBoxLayout` containing: (a) a `QMenuBar` at the top, (b) the tab system widget (step 2) filling the remaining space.
   - Implement the full menu structure per §1.2: File (New/Open/Clone/Close/Quit), Edit (Undo/Redo/Cut/Copy/Paste/Select All/Find), View (Tab Position toggle, Zoom), Help (About/Docs). Wire the File menu items to their existing `core.engine` functions (init_repo, open_repo, clone_repo). Edit and View items can be stubs initially except Quit (which must work).
   - Session & GUI state persistence: save window geometry/state, splitter ratios, open tab order/pin states, active repository, and per-repo selections/drafts to `app_settings` key `ui.session_state`.
   - Uses a coalesced 1000ms debounce auto-save timer (`QTimer`) across all UI mutation signals + immediate synchronous flush on `closeEvent` to ensure state is never lost even if the process is killed unexpectedly. If restored geometry places the window off-screen, fall back to default `1200×800` centered.
   - Quit guards per §1.3: check for (a) non-empty commit message/description text fields, (b) in-progress background operations via `workers.py`. Show appropriate confirmation dialogs before allowing close.
   - Default size `1200×800`, minimum `900×600`.

2. **Tab bar widget** (`ui/tabs/tab_bar.py` [NEW]) — ref: `ui-planning.md` §2
   - Create a custom `TabContainer`, `TabStripWidget`, and `TabButton` widget providing full styling control and dynamic tab lifecycle.
   - Dynamic tab model (§2.1): All tabs (Changes, History, PRs, Issues, detail tabs) are dynamic and closable by default, with right-click context pinning (`Pin Tab` / `Unpin Tab`). Pinned tabs show a `📌` badge, hide the `×` button, and are protected from accidental removal.
   - Drag-and-drop tab reordering: tabs can be reordered via mouse drag. Pinned tabs are grouped at the top/left and reorderable among pinned tabs; unpinned tabs are reorderable among unpinned tabs. Active tab focus is preserved and order is persisted via `ui.session_state`.
   - Section dividers: 1px subtle divider line between the tab strip and main content area (`border-right` in vertical mode, `border-bottom` in horizontal mode).
   - Per-repo deduplication rule (§2.1, §2.8): tab identity is `(tab_type, repo_path, entity_id)`. Opening an existing entity focuses that tab instead of opening a duplicate.
   - Vertical tab mode (default): tab buttons stacked vertically on the left edge, content area to the right. Horizontal mode: tab buttons across the top. Toggled via View → Tab Position menu, persisted to `ui.session_state`.
   - Trailing `+` button dropdown adds available category tabs ("Changes", "History", "Pull Requests", "Issues").
   - Keyboard: `Ctrl+1/2/3…` switches by position.
   - Tab persistence: serialize full tab list, order, pin state, and active index to `ui.session_state`.
   - API: `add_tab(...)`, `remove_tab(index)`, `pin_tab(index)`, `unpin_tab(index)`, `move_tab(from_index, to_index)`, `serialize_tabs()`, signals `current_changed(int)`, `tab_closed(int)`, `tabs_mutated()`, `orientation_changed(Orientation)`.

3. **Changes tab — repository selector & branch switcher** (`ui/tabs/changes_tab.py` [NEW], `ui/widgets/branch_switcher.py` [NEW]) — ref: `ui-planning.md` §3.2, §3.2b
   - Top of the Changes tab: a custom-styled `QComboBox` (flush, borderless, blended with theme) populated from `repo_registry.list_repos()`, sorted by `last_opened_at DESC`.
   - On selection change → call `_open_repo_path()`, restart watcher, refresh status, and emit a signal (`repo_changed(path)`) that all open tabs connect to for refresh.
   - Directly below repo dropdown: Branch indicator/switcher widget (`🌿 main ▾`, `ui-planning.md` §3.2b). Clicking opens a filterable branch popup list; switching branch calls `engine.switch_branch()`. If uncommitted changes exist, prompt with "Stash & Switch / Switch Anyway / Cancel". Right-click menu exposes Create/Rename/Delete branch operations.
   - **Edge cases (all from §3.2, §3.2b):**
     - Zero repos: show placeholder "No repositories" in dropdown; file list area shows centered empty state with "Open or clone a repository to get started" and two action buttons ("Open Repository…", "Clone Repository…") triggering the same File menu actions.
     - First launch: auto-select most recently opened repo.
     - Missing repo: show with ⚠️ icon and muted text. Selecting triggers a "Locate / Remove / Cancel" dialog. "Locate" uses a file picker → `repo_registry.relocate_repo()`.
     - Detached HEAD: branch switcher shows `🔗 HEAD detached at {short_sha}` in warning color.
     - Dropdown refreshes on: tab visibility, File → Open/Clone/New completion, repo removal.

4. **Changes tab — unified file list** (`ui/tabs/changes_tab.py` continued) — ref: `ui-planning.md` §3.3
   - Replace the Phase 1 split "Staged"/"Unstaged" two-list design with a **single unified `QListWidget`** showing all changed files (staged + unstaged + untracked combined). Each row has: a checkbox (checked = selected for commit), a change-type indicator (M/A/D/R/?), and the file's repo-relative path.
   - **Select-all checkbox**: tri-state (`Qt.PartiallyChecked`). Fully checked when all files checked, unchecked when none, indeterminate when mixed. Click cycles: indeterminate/unchecked → all checked → all unchecked.
   - All files checked by default when changes are detected.
   - Sorting: staged first, then unstaged, then untracked. Alphabetical within each group.
   - Click on row = select for diff display (does NOT toggle checkbox). Only clicking the checkbox toggles it.
   - **Right-click context menu**: Stage File, Unstage File, Discard Changes (with confirmation), separator, Open in File Manager, Copy Relative Path, Copy Absolute Path.
   - **Edge cases**: file list refresh preserves selection and checkbox states; if the selected file disappears, clear diff and show "Select a file to view changes"; long paths truncated with `…` from the left, full path in tooltip; count badge next to select-all ("☑ 42 files").

5. **Changes tab — commit section** (`ui/tabs/changes_tab.py` continued) — ref: `ui-planning.md` §3.4
   - Bottom of the left column. Layout top-to-bottom:
     a. **Account icon** (leftmost): a small circular icon showing the current forge account's avatar/initial. Hover → tooltip with account details. Click → account picker popup (logged-in accounts + "Add account…"). If no forge account linked, show a generic user icon.
     b. **Commit message** (`QLineEdit`): single-line, placeholder "Commit message", soft 72-char limit (subtle color change past 72, not a hard block). Positioned to the right of the account icon.
     c. **Description** (`QTextEdit`): multi-line, placeholder "Description", 3-4 lines default height, user-resizable.
     d. **Amend checkbox** + **Commit button** on the same row: `QCheckBox` "Amend" on the left, `QPushButton` "Commit to {branch}" on the right. Amend checkbox toggles amend mode — pre-fills message/description from the last commit, button label changes to "Amend commit on {branch}", committing calls `engine.commit(msg, amend=True)`. Hidden/disabled on unborn branches.
   - Commit button enabled only when: message non-empty AND at least one file checked. Disabled state shows tooltip explaining why.
   - **Edge cases**: detached HEAD → "Commit on detached HEAD" with warning tint and info banner; unborn branch → "Create initial commit", amend hidden; merge conflict → persistent banner at top of Changes tab; dirty commit fields on repo switch → save per-repo draft in memory (dict keyed by path), restore on switch-back, lost on quit.

6. **Changes tab — diff view** (reuse `ui/diff_view/`) — ref: `ui-planning.md` §3.5
   - Right column of the Changes tab. Reuse the existing `DiffView`/`DiffWidget` from Phase 1 — embed it as a child widget of `changes_tab.py`'s right-side layout. No reimplementation needed; just re-parent it from the old `QSplitter` into the new `QVBoxLayout`.
   - Add binary file detection: if `Diff.is_binary`, show centered "Binary file changed" with file size. Hide hunk/line staging controls; only whole-file staging is available.
   - Empty state per §3.5: no changes → "No changes" + random programming quote; no file selected → "Select a file to view changes".

7. **Staging logic bridge** — ref: `ui-planning.md` §3.3 "Staging Logic"
   - The checkbox model is a "commit selection" model, not direct staging. The commit flow sequence (called by the commit button's click handler) is:
     a. `engine.unstage_all()` — reset the index to HEAD.
     b. For each checked file: `engine.stage_file(path)`.
     c. `engine.commit(message, amend=amend_checked)`.
     d. Refresh the file list.
   - This ensures the git index always reflects exactly the user's checkbox selection at commit time, regardless of any manual staging/unstaging done via the diff view's hunk buttons between checkbox interactions.

8. **History tab — skeleton** (`ui/tabs/history_tab.py` [NEW]) — ref: `ui-planning.md` §4
   - Create a container widget with three zones (top-to-bottom):
     a. **Search/filter bar** (§4.6): a `QHBoxLayout` with a `QLineEdit` ("Search commits…"), an author filter dropdown, and a date-range picker. Wire the search box to a `LogFilter` dataclass but **do not implement the filter logic or debounce yet** — that's Phase 2. The bar exists as a visible, interactive-looking element that is non-functional until Phase 2 fills it in.
     b. **Graph area**: a placeholder `QWidget` (or `QLabel` with centered text "Commit graph — coming in Phase 2") that Phase 2's `CommitGraphWidget` will replace. Wrap it in a layout that makes the swap a one-liner: `self.graph_layout.replaceWidget(placeholder, commit_graph_widget)`.
     c. **Detail panel slot**: an empty `QWidget` at the right edge (or bottom), hidden by default. Phase 2 will insert the slide-in commit detail panel here.
   - **Empty state** (no repo selected): same as Changes tab — "Open or clone a repository to get started". (No commits): "No history yet — Make your first commit to see the branch graph here."
   - **Signals**: `commit_hovered(sha: str)`, `commit_clicked(sha: str)` — defined but not emitted until Phase 2 connects them to the graph widget.
   - **Repo-switch handling**: connect to `changes_tab.repo_changed` signal. On repo switch, the graph placeholder resets. Once Phase 2 is implemented, this triggers a graph reload instead.

9. **Sidebar deprecation**
   - Remove `ui/sidebar/` module entirely (the `RepoSidebar` widget, `sidebar/__init__.py`). All its functionality is now covered by: (a) the repo dropdown in the Changes tab, (b) the tab bar for navigation.
   - Remove the sidebar from `ui/main_window.py`'s layout. Remove the `QSplitter` that held sidebar + content area — the tab system widget is now the sole child of the main window's central widget.
   - Update any imports or references to the sidebar in test files.

10. **Tab-system wiring in main_window.py**
    - `main_window.py` becomes a thin shell: `QMainWindow` with a `QMenuBar` and a `TabBar` as its central widget. It owns the `RepoHandle` lifecycle, passes it down to tabs via a shared reference or signal.
    - The Changes tab is always present (index 0, non-closable). History tab is added by default (index 1, closable).
    - Connect `changes_tab.repo_changed(path)` to a slot that updates `self._current_repo` and emits a signal all tabs listen to.

11. **Theme and style integration**
    - Ensure the new widgets (tab bar, repo dropdown, file list, commit section) inherit the existing `QApplication` style/palette. No custom stylesheets yet — use the default Qt theme. Custom theming (dark mode, accent colors) is deferred to Phase 7 polish.
    - The repo dropdown's "flush" styling is achieved by setting `QComboBox { border: none; background: transparent; }` in a minimal stylesheet scoped to that widget only — not a global stylesheet change.

12. **Test updates** (`tests/ui/`)
    - Remove or rewrite any `pytest-qt` tests that reference `RepoSidebar`.
    - Add basic widget tests for:
      - `TabBar`: verify Changes tab is always present, add/remove tabs, keyboard switching.
      - `ChangesTab`: repo dropdown populates from registry, file list checkbox tri-state, commit button enable/disable logic, amend pre-fill.
      - `HistoryTab`: skeleton renders, empty state displays correctly.
    - Existing `tests/unit/core/` and `tests/unit/storage/` tests are unaffected — this phase touches zero core logic.

13. **Acceptance check**: `pytest tests/ -v` all green (including new UI tests and unchanged core tests); manual QA:
    - Launch app → Changes tab visible with repo dropdown, tab bar on left.
    - Toggle tab bar to horizontal (View → Tab Position → Top) and back.
    - Add a repo via File → Open, confirm it appears in dropdown.
    - Stage files via checkboxes, verify tri-state select-all behavior.
    - Type a commit message → commit → file list refreshes, message clears.
    - Check "Amend" → verify message pre-fills from last commit, commit button label changes.
    - Switch to History tab → see placeholder/empty state (no graph yet).
    - Switch repos via dropdown → verify all tabs refresh (History shows correct empty state for new repo).
    - Close and reopen app → verify tab layout, window geometry, and last-selected repo are restored.
    - Quit with text in commit message → verify confirmation dialog appears.

### Phase 2 — Commit Graph & Merge Tooling
**Prerequisites:** Phase 1.5's acceptance check passed (tab-based UI shell, Changes tab redesign, and History tab skeleton all working). Phase 2 now fills in the History tab's graph and adds merge tooling.

**Read-first note (added during a Phase 2 review pass):** this phase's steps below are the improved, tightened version. The step *numbers* and their scope are unchanged from the original pass, and §4.1's Phase-2 additions (`merge_abort`, `rebase_continue`, `rebase_abort`, `get_commit_diff`, `get_commit_file_stats`, `get_ref_labels`, `RepoStatus.merge_in_progress`/`rebase_in_progress`) exist specifically to close gaps this phase's UI surfaces were already promised (ui-planning §6.6 called `engine.merge_abort()` before any such signature existed — now it does).
1. `ui/commit_graph/`: FR-2.2 — render commits from `core.engine.get_log()` (paginated, not loading full history eagerly — see NFR performance target; the underlying implementation is `core/read_ops.py`, but per §4.1's façade rule the UI only ever calls the `core.engine` re-export). **Simplified v1 lane-assignment algorithm** (deliberately *not* a full min-crossing DAG layout — that's a hard graph problem, out of scope for v1 by design, not by oversight; matches the SRS's "simple yet colorful" requirement rather than over-building):
   a. **Walk scope — all refs, not just HEAD.** A graph that only draws HEAD-reachable commits can never show FR-2.2's "multi-branch visualization," so Phase 1's HEAD-only walk is insufficient here even though it's still correct for other callers. Add an `all_refs: bool = False` keyword to `get_log` (additive; existing callers keep their behavior). When `True`, seed the walk from every local branch head under `refs/heads/*`, every tag target under `refs/tags/*`, **and** HEAD (pygit2's walker supports repeated `.push()` for each seed; dedup across overlapping histories is the walker's job, not yours). The Phase 1 zero-commit guard (`repo.head_is_unborn` → return `[]`) still runs first. The graph calls `get_log(all_refs=True)`; nothing else in v1 does. **Determinism matters:** `.push()` seeds are sorted by full ref name before being passed to the walker — `Repository.references` iteration order is not contractually stable, and lane assignment is a function of walk order, so an unsorted seed order produces lanes that re-shuffle between refreshes and CI runs. A stable sort makes the layout reproducible (and unit-testable) rather than "differs by hash-order luck."
   b. **Lane-assignment rules (rigid, replacing the earlier a–f sketch — it broke in three specific places on real repos).** State: `lanes: list[Lane]`, each `Lane(expected_sha: str | None, color)`. Output per commit: `(commit, lane_index, connectors)` where a connector is `(from_lane, to_lane)` for drawing. Process commits in walk order (`GIT_SORT_TOPOLOGICAL | GIT_SORT_TIME`):
      - **R1.** If one or more lanes expect this commit's sha, it occupies the **lowest-numbered** such lane; every *other* lane also expecting this sha is closed here, emitting a connector from each into the occupied lane. (Skipping this rule leaves dangling duplicate rails after histories reconverge — e.g. after one merge both the feature lane and the main lane expect the same next parent.)
      - **R2.** If no lane expects it (a branch tip we've just met), open a new lane assigned to it, then continue with R3.
      - **R3.** Let `P1..Pn` be the commit's parents (`commit.parent_shas` — required by §4.1 exactly for this). For `P1`: if no *other surviving* lane already expects `P1`, this lane's `expected_sha = P1`. If another lane already expects `P1`, close this lane with a connector into that one — otherwise two rails descend separately onto the same commit and that commit gets drawn twice (or a rail vanishes mid-graph). For `P2..Pn` (merge commits; octopus merges, `n >= 3`, are the same rule, per ui-planning §4.11): if some lane already expects `Pi`, emit a connector into that lane; otherwise open a new lane expecting `Pi`, appended at the right end.
      - **R4.** No parents (a root): close the lane after this row.
      - **R5.** Colors come from the **ten**-entry `GRAPH_COLORS` palette in ui-planning §5.1 (an earlier draft of this step said "~8" — ui-planning's shipped list is authoritative), assigned in lane-creation order, cycling; a lane keeps its color for its whole lifetime, including across pagination boundaries (see (d)).
   c. **Pagination and layout consistency.** Initial load 200 commits, then batches of 100 on scroll (ui-planning §4.8). On each new batch, recompute lanes **from scratch over the entire loaded window** — never maintain incremental lane state across batches. The algorithm is O(n), so even the NFR's 100k-commit target is tens of milliseconds of pure Python; an incremental lane state that drifts at batch boundaries is the classic "lanes shuffle when I scroll" bug and buys nothing. `get_log` calls — and any lane computation over a window larger than a few thousand commits — go through `ui.workers.run_in_background` per §4.8 (the history tab is the one place even a *read* operation falls under that rule).
   d. **Ref labels for the pill badges:** one `get_ref_labels(repo)` call per refresh (§4.1), mapping `sha -> [RefLabel]`; it's cheap and un-paginated. Detached HEAD renders the `HEAD` pill at `detached_head_sha` in addition to any branch labels.
   e. **Pure layout core:** `ui/commit_graph/layout.py` takes `list[Commit]` and `dict[str, list[RefLabel]]` and returns the row/connector structure — no Qt imports, fully unit-testable without a displayserver. `graph_widget.py` only paints what `layout.py` emits.
   f. **Accessible fallback ships with the graph, not in Phase 7** (ui-planning §5.4 flags this as the highest-effort a11y item): the History tab hosts a `QTreeView` over the same row data (subject, short sha, author, relative time, branch labels), toggled via the View menu and auto-activated when `QAccessible.isActive()`. The custom `QPainter` widget is invisible to screen readers; a tree of the same data is not.
   g. **Integration with the Phase 1.5 skeleton:** swap `self.graph_placeholder` out of `self.graph_layout` via the `replaceWidget` seam written into `history_tab.py`. The zero-commit ("No history yet") and no-repo empty states already exist in the skeleton — the graph widget only ever replaces the placeholder, never the empty-state widget. Wire the skeleton's existing `commit_hovered`/`commit_clicked` signals to the graph.
   h. **Detail panel (ui-planning §4.5/§4.11):** on `commit_clicked`, fill the detail-panel slot with: metadata header (full SHA copy-on-click, author, absolute+relative time), the full message, a file list driven by `get_commit_file_stats(sha)` (change type, `+N/-M` per `FileStat`), and a `DiffView` instance fed by `get_commit_diff(sha, path)` — initial selection is the first file. Semantics per ui-planning: clicking the *same* commit toggles the panel closed; clicking a *different* commit updates in place without re-animating; `Escape` closes; the panel is scroll-pinned independent of the graph. **Staging controls are hidden in this DiffView usage** — hunk/line staging is a working-tree concept and is meaningless against a historical commit; reusing the widget without suppressing those buttons would present actions that can never succeed. The hover tooltip (§4.4) renders from the same `get_commit_file_stats` list.
   Unit tests: a linear 5-commit fixture → exactly 1 lane throughout and zero connectors; the one-merge fixture → 2 lanes between fork and merge, converged after (the original check); an octopus fixture (3 parents) → 3 connectors into the merge row; a repo where two branches re-merge twice → no lane duplicates (R1); and a 250-commit fixture loaded as `200 + 50` → identical lane indices to a single 250-commit load (the (c)-recompute contract).
2. FR-2.3: search/filter over the log (ref: `ui-planning.md` §4.6). **Two-mechanism split — the earlier wording contradicted itself here** (it told you both to pass the filter into `get_log` *and* to dim non-matching commits; narrowed results can't be dimmed, they just vanish):
   a. **Graph filtering is client-side highlighting.** A pure predicate `matches_filter(commit, filter: LogFilter) -> bool` — implemented in `ui/commit_graph/layout.py` alongside the layout logic, since both operate on `list[Commit]` — is evaluated over the currently loaded window. Matches render normally; non-matches render dimmed; structure and lanes are untouched (ui-planning §4.6). `Enter`/`F3` cycles to the next match. The `filter=` parameter on `get_log` (Phase 1's API, §4.1) is **not** the mechanism for this tab — leave it for future callers that genuinely want a narrowed list, and don't wire the search box to it.
   b. **Field semantics** (same rules for `matches_filter` and `get_log`): plain case-insensitive substring for `author` and `message_substring` (not regex — regex is a v2 nicety, not a v1 requirement); `date_from`/`date_to` are lexicographic compares against `Commit.author_date`, which is only valid because `read_ops` normalizes every timestamp to UTC ISO-8601 (`datetime.fromtimestamp(tz=utc).isoformat()`) — keep that normalization invariant or filtering silently corrupts.
   c. **Close a Phase 1 gap while here: `filter.path` is currently silently ignored by `read_ops.get_log`** (author/message/date are implemented; path isn't). Implement it now, semantics: a commit matches iff `path` appears in its diff against its first parent (`commit.tree.diff_to_tree(commit.parents[0].tree)` deltas; roots diff against the empty tree). It's O(diff) per commit, so path filtering runs inside `run_in_background` and applies only over the loaded window — a documented v1 limitation; full-history path filtering via `git log --follow -- path` is a v2 optimization, noted here and not built.
   d. **Author dropdown** populates from the distinct authors of the loaded window (sufficient for v1), refreshed per repo. Debounce the search box with the 300ms single-shot `QTimer` pattern from §5 Phase 1 step 7.
3. `core/engine.py::merge()`: FR-3.1 — `run_git(["merge", source_branch])`. Outcome derivation stays as originally specified: exit 0 with "Already up to date" in stdout → `MergeResult(status="up_to_date")`; exit 0 otherwise → `MergeResult(status="merged", commit_sha=...)`; nonzero exit with `<<<<<<<` conflict markers in the working tree → `MergeResult(status="conflict", conflicted_files=[...])` from index conflicts, **not raised as an exception** — a merge conflict is an expected, routine outcome the UI routes into the merge tool, not an error state. New specifics the original text left implicit:
   - **That stdout sniffing now has a hard precondition**: §4.2 mandates `LC_ALL=C` in `run_git`'s environment for exactly this parsing. If the Phase 2 implementer finds that rule missing in code, fix §4.2 first — do not write regexes against localized output.
   - **Dirty-tree precondition, checked not parsed.** Before invoking git, if `get_status` reports staged or unstaged changes, raise `DirtyTreeError` (new in `core/exceptions.py`) with the affected paths — git refuses with "Your local changes..." anyway; a typed precheck is a testable branch instead of stderr string-matching. Untracked files alone don't block unless git reports "untracked working tree files would be overwritten" — keep one stderr→`DirtyTreeError` fallback mapping for exactly that message.
   - **Snapshot first:** `take_snapshot(repo, "pre_risky_op")` runs at the top of the function, before any `run_git` call (step 6 explains why trigger wiring lives in the engine, not the UI).
   - **Record the state, not just the outcome.** `get_status` learns `merge_in_progress`/`rebase_in_progress` here (§4.1), read from `repo.pygit2_repo.state()` (`GIT_REPOSITORY_STATE_MERGE` / `GIT_REPOSITORY_STATE_REBASE_MERGE` / `_REBASE_APPLY`). This is what keeps the Changes-tab banner alive after the *last* conflict is resolved — `has_conflicts` goes false the moment the final file is staged, but the merge is still open until its commit. A banner that vanishes at that moment is a UI lie that strands users mid-merge with no visible way to finish.
   - `merge_abort(repo)` (§4.1): `run_git(["merge", "--abort"])`; nonzero exit → `GitCommandError`. Aborting on a repo that isn't mid-merge *is* a real failure — don't swallow it.
4. `ui/merge_tool/merge_dialog.py`: FR-3.2 (ref: `ui-planning.md` §6.6) — 3-pane top layout (Ours / Base / Theirs synchronized diff panes) + editable Result pane at the bottom. Core reading as originally specified: iterate `repo.pygit2_repo.index.conflicts` — `(ancestor, ours, theirs)` `IndexEntry` tuples, any of which may be `None` for add/delete conflicts — and read blob content via `repo.pygit2_repo[entry.id].data.decode("utf-8", errors="replace")`. Resolution actions: "Accept Current (Ours)", "Accept Incoming (Theirs)", "Accept Both (Ours ➔ Theirs)", "Accept Both (Theirs ➔ Ours)", plus direct manual editing; navigation `◀ Prev Conflict` / `Next Conflict ▶` with "Conflict N of Total". New specifics the original text left implicit:
   - **Launch paths:** (1) the Changes tab conflict banner's "Resolve Conflicts" button, gated on `merge_in_progress`/`rebase_in_progress`/`has_conflicts`; (2) double-clicking a `⚠`-flagged conflicted file row; (3) programmatically from step 5's rebase loop.
   - **Mode parameter and the rebase inversion trap:** `MergeDialog(repo, *, mode: "merge" | "rebase")`. During a *rebase*, git's stage-entry semantics invert: "ours" is the upstream you're replaying onto, "theirs" is *your* commit being replayed. The dialog must label panes accordingly — e.g. "Upstream (base of rebase)" / "Your commit (being replayed)" — with a one-line explainer banner, instead of the merge-mode "Ours (current branch)" / "Theirs (incoming)". Treat labels as a correctness issue: a merge tool that teaches users to resolve backwards during rebases is worse than no tool.
   - **Binary conflicts:** "Keep ours / keep theirs" only. "Keep both" is ill-defined for binary content without inventing a rename convention — v1 doesn't (noted, not built). Detection rule: UTF-8 decode attempt on the blob; failure → binary UI.
   - **Never stage markers.** Before `stage_file`, rescan the Result text for remaining `<<<<<<<` / `=======` / `>>>>>>>` lines; if any remain, refuse to stage and highlight them. Users resolving hunks across a long file *will* save a stray marker eventually without this guard.
   - **Completion flow:** when every conflicted file is resolved and staged, close the dialog and leave the repo in merge state — the **Changes tab** completes the merge with a normal commit, pre-filling its message from `.git/MERGE_MSG` when present (git already writes "Merge branch 'x'…" there) while `merge_in_progress` is true. The dialog never creates the merge commit itself.
   - **Abort:** confirmation dialog → `engine.merge_abort()` (`engine.rebase_abort()` in rebase mode) → close → refresh status.
   - Threading: everything here is local index/working-tree work, well under the NFR's responsiveness budget — §4.8's background rule does not apply inside this dialog.
5. `core/engine.py::rebase()`: FR-3.3, deliberately **non-interactive only** in v1 (no commit reordering/squashing UI — that's FR-2.4, deferred to v2). `run_git(["rebase", onto])`; conflict detection identical to `merge()`'s. Detailing the loop the original text only described in prose:
   - Same `DirtyTreeError` precondition and the same **one-time** `pre_risky_op` snapshot at entry — `--continue`ing a rebase is resuming the *already snapshotted* risky operation, not a new one; snapshotting per step would flood the rolling window with one snapshot per replayed-and-conflicted commit.
   - **Facade trio and their contract:** `rebase_continue(repo)` → `run_git(["rebase", "--continue"])`; a nonzero exit code *with* conflict markers means "next conflict, keep looping" — a routine result, not an exception (only raise `GitCommandError` on nonzero exits *without* conflicts). `rebase_abort(repo)` → `run_git(["rebase", "--abort"])`.
   - **UI loop:** conflict result → open the merge dialog in `mode="rebase"` → user resolves all listed files, they get staged → call `rebase_continue()` → repeat until git reports the rebase complete; `rebase_abort()` is reachable from both the dialog and the Changes-tab banner (which shows for `rebase_in_progress` exactly as it does for merges) at every iteration.
   - **Guard clause:** `rebase_continue`/`rebase_abort` verify `repo.pygit2_repo.state()` reports a rebase before running, raising `GitCommandError` otherwise — keeps the UI loop stateless: it never has to guess whether git still considers the rebase open.
   - **Threading:** `rebase_continue` is `rebase --continue` — it can replay thousands of commits on the next leg. It falls under §4.8's background rule exactly as `rebase` itself does; only the dialog's index/working-tree work (step 4) is exempt.
6. Complete snapshot trigger wiring (FR-10.2), plus the browse/restore surface:
   - **`pre_risky_op` now lives in the engine**: `take_snapshot(repo, "pre_risky_op")` is called at the top of `engine.merge()`, `engine.rebase()`, and (already, since Phase 1) `delete_branch()` — engine-level, not UI-level, so *any* future caller of these façade functions inherits the safety net automatically.
   - **Timer lifecycle after the 1.5 redesign:** Phase 1.5 moved repo switching into the Changes tab dropdown, which means the old "main window owns it" note needs an explicit update path: `main_window.py` owns a single snapshot `QTimer` (alongside its existing autosave timer); on `changes_tab.repo_changed` the timer is **stopped and re-created** from the newly active repo's `SnapshotSettings` — `interval = timer_interval_minutes * 60_000`, running only if `trigger_on_timer` is set; on repo close it stops; on app quit it stops. Expose `restart_snapshot_timer()` as a public slot on `MainWindow` and call it wherever snapshot settings get saved (today: directly after `update_snapshot_settings` succeeds) so settings changes take effect without a repo switch. Timer fire → `take_snapshot(repo, "timer")` — synchronous is fine: the command it's built on is local and fast, and the idempotency check makes idle ticks near-free.
    - **`ui/snapshots_panel/`** (ui-planning §6.4): list snapshots for the active repo (icon for manual vs. auto, label or trigger type, relative timestamp), a Restore action (`snapshots.restore_snapshot` behind the destructive-action confirmation from §4.6: "Replace working tree with snapshot from {timestamp}?"), a Delete action (extra confirmation when `is_manual`), and the empty state ("No snapshots yet…"). The skeleton on disk already created this as a package — the panel implementation lives in `ui/snapshots_panel/__init__.py`.
   - **New guard — never restore into a merge/rebase in progress:** `restore_snapshot` raises a typed `RepoBusyError` (new in `core/exceptions.py`) when `merge_in_progress` or `rebase_in_progress` is true; `read-tree --reset -u` mid-merge silently scrambles the index/conflict state, exactly at the moment the user thinks they're being rescued. The panel disables Restore with a tooltip when `get_status` reports either state, and the same guard applies to `reflog.restore_to_ref` (FR-1.10's `reset --hard` is equally destructive mid-merge).
7. **Acceptance check**: `pytest -v` all green, which must now specifically include: `tests/unit/core/test_merge.py` — fast-forward merge, up-to-date (proving the `LC_ALL=C` parse path), dirty-tree raises `DirtyTreeError` *before* git is invoked, conflict → `MergeResult(conflict)` with `merge_in_progress` true, `merge_abort()` returns status to clean; `tests/unit/core/test_rebase.py` — conflict → merge-tool-resolve → `rebase_continue()` loop completes the rebase, and `rebase_abort()` mid-conflict restores the original branch tip; `tests/unit/core/test_snapshots.py` — the original checks (a `pre_risky_op` snapshot exists before a merge/rebase; restoring via `read-tree --reset -u` never moves `repo.head.target`) plus restore-while-merging raising `RepoBusyError`; `tests/unit/core/test_read_ops.py` — a new case asserting `filter.path` actually narrows results (regression coverage for the silent-no-op gap); `tests/unit/ui/commit_graph/test_layout.py` (or the `tests/unit/ui/` equivalent location used by the repo) — step 1's lane cases, including the cross-batch lane-index equality case; plus a `run_git` test asserting `LC_ALL=C` is present in the spawned environment. Manual QA: a real two-parent merge with a conflict, resolved through the merge tool to a correct commit (verified with `git log` external to the app); a rebase conflict round-trip; the timer trigger visibly producing a snapshot during idle (log line); restoring a snapshot with uncommitted changes pending; the graph rendering two branches with correct lane colors and label pills; and the accessible tree fallback toggling over the same data.

### Phase 3 — Remote Operations
**Prerequisites:** Phase 2's acceptance check passed (commit graph, merge, non-interactive rebase, and the built-in merge tool all working).

**Step 0 — repo-state reconciliation (fixes against the current codebase, do these first).** Earlier phases scaffolded Phase 3's entry points, so parts of this phase are corrections of existing code rather than greenfield work. Verified against the tree at Phase 2 completion:
   - `credentials/backend.py` and the factory (`_detect_packaging_context()`/`get_backend()`) in `credentials/__init__.py` are **already implemented per §4.5/§4.7** — verify, don't rewrite. `credentials/secret_service.py` is a stub: all five methods raise `NotImplementedError`. Step 1 completes only that file.
   - `engine.py` already contains `push`/`pull`/`fetch` **with the old signatures** (no `progress_cb`/`cancel_event`), raising `NotImplementedError`. Step 3 **replaces** these stubs with the §4.1 signatures — do not add duplicate overloads beside them.
   - `write_ops` already has a `clone_repo`, but it (a) accepts and then **ignores** `progress_cb`, and (b) clones **directly into `dest`** — both contradict this phase's spec. Step 3 **rewrites** it. The `clone` alias in `engine.py`, and the File-menu/`main_window._on_clone_repo()` call site, keep working against the new signature without changes at their call sites (kwarg names are unchanged).
   - `run_git` (write_ops) is built on `subprocess.run(capture_output=True)` — a fully-buffered call that cannot stream progress. Do **not** stretch it; step 3a adds a sibling helper instead, and step 3 converts only the four network ops to it. Every other `run_git` caller stays untouched.
   - `pyproject.toml` **already** declares both the `git-credential-wrench` console script (§5 Phase 3 step 2) and the four forge-adapter entry points (§4.4). If either is missing when you get here, re-add exactly per §0 rule 4 before continuing — but expect them present.
   - The `Remote` dataclass exists in `engine.py` (name, url). Phase 3 introduces the wider `RemoteInfo` (§4.1) — `Remote` stays for internal pygit2-adjacent use; `RemoteInfo` is what `list_remotes` returns to the UI.
   - `ui/workers.py` exists with a `progress = Signal(int)`. The §4.1 `ProgressCallback` is `(percent: int, stage: str)` — reconcile at the injection seam (step 3e), not by widening the signal: the busy dialog only needs percent.

1. `credentials/` package — complete `secret_service.py`; verify the rest:
   - `credentials/backend.py` and `credentials/__init__.py` were delivered by scaffolding (Step 0) and should already match §4.7 verbatim — `CredentialBackend` ABC with abstract `store_secret`/`get_secret`/`delete_secret`/`unavailable_help_text`, `CredentialBackendUnavailableError`, `_detect_packaging_context()` returning `"flatpak"|"appimage"|"bare"` (checking `FLATPAK_ID`/`/.flatpak-info` first, then `APPIMAGE`), and `get_backend()` dispatching to `FlatpakSecretServiceBackend` only for `flatpak` and `AppImageSecretServiceBackend` for both other contexts (`bare` shares AppImage's remediation text because bare installs fail the same way — no sandbox permission to fix). If any drift from §4.7 is found, fix the drift; do not extend the interface.
   - `credentials/secret_service.py`: fill in `SecretServiceBackend`'s five methods with the §4.5 bodies (`_collection()` handling `SecretServiceNotAvailableException` and the locked-collection `unlock()` path; `store_secret` with `replace=True`; `get_secret` via `search_items` returning the first match's decoded secret or `None`; `delete_secret` iterating matches). The two subclasses keep their existing `unavailable_help_text()` overrides and gain nothing else.
   - **Key namespace rule**: keys passed to these methods are always the row's `forge_accounts.secret_service_key` value, formatted exactly `wrench:forge:{account_id}` (§4.5). The credential helper (step 2) and account CRUD both rely on this exact format — log the key, never the secret, when debugging.
   - **Tests** (`tests/unit/credentials/test_secret_service.py` — currently `tests/unit/credentials/` holds only an `__init__.py`): these specific cases, all with `secretstorage.dbus_init`/`get_default_collection` mocked so CI needs no real keyring:
     a. `get_secret` happy path returns the decoded secret of the first `search_items` hit.
     b. `get_secret` returns `None` when `search_items` yields nothing (no exception).
     c. `store_secret` calls `create_item` with `replace=True` and attributes exactly `{"application": "wrench", "key": key}`.
     d. `delete_secret` calls `.delete()` on every matched item (not just the first).
     e. `_collection` with `is_locked()==True` calls `unlock()`; `LockedException` → `CredentialBackendUnavailableError` whose message is the subclass's `unavailable_help_text()`.
     f. `SecretServiceNotAvailableException` from `dbus_init` → `CredentialBackendUnavailableError` with the same subclass-specific text (assert the Flatpak and AppImage texts differ, locking in the §4.5 dispatch rationale).
     g. `get_backend()` returns `FlatpakSecretServiceBackend` when `_detect_packaging_context()` is monkeypatched to `"flatpak"`, `AppImageSecretServiceBackend` for `"appimage"` and `"bare"`.
     h. `_detect_packaging_context()`: monkeypatched env-var/file-exists permutations for all three outcomes (including the Flatpak-wins-over-APPIMAGE precedence case).
     i. `get_backend()` with `sys.platform` monkeypatched to `"win32"` raises `NotImplementedError`.
     j. Optional real-backend smoke test guarded by `pytest.mark.skipif` on `shutil.which("dbus-launch") is None or not _detect_packaging_context()=="bare"` — skipped in CI, for local sanity only.
2. `core/git_credential_helper.py`: implement `main()` — the entry point is already declared in `pyproject.toml` (`git-credential-wrench = "wrench.core.git_credential_helper:main"`, Step 0) and git invokes it as an external helper executable named exactly `git-credential-wrench`. **Git's helper protocol, exact (easy to get subtly wrong if improvised):**
   - Git invokes the helper with exactly one argument: `get`, `store`, or `erase`. Any other argv → exit 1 with nothing on stdout.
   - Git writes `key=value` lines to **stdin**, one per line (typical keys: `protocol`, `host`, `path`, `username`; `store`/`erase` also include `password`), terminated by a blank line or EOF. Parse with `line.split("=", 1)` — values may legitimately contain `=` (some tokens do), a naive `split("=")` silently truncates them. Ignore blank lines; tolerate unknown keys without error.
   - **Only handle `protocol=http` and `protocol=https`** — any other protocol (or a missing protocol key), print nothing and exit 0. SSH transport never reaches this helper (step 4), and silently no-oping is the defined behavior for a protocol the helper doesn't know.
   - `get`: resolve which account applies, then whether we have a secret for it. **Account disambiguation (FR-4.5/FR-5.8) — exact matching order:**
     1. **Host match.** Parse stdin's `host` (strip a trailing `:port` if present before comparing). Find all `forge_accounts` whose `instance_url`'s `http(s)://{host}` component equals it (compare hosts case-insensitively; the full-URL parse belongs in one small `_host_of(instance_url)` helper in this file so the normalization can't drift between call sites).
     2. **Path+link refinement.** When stdin carries `path` (only present because we set `credential.useHttpPath = true` — see below), and exactly one candidate from step 1 is referenced by a `repo_forge_links` row whose `owner_slug/repo_slug` combined path matches stdin's `path` prefix (`owner/repo.git` vs `owner/repo` — normalize both by stripping a trailing `.git` and leading `/`), choose **that** account. This is the multi-account disambiguation path.
     3. **Fallback.** If host matching resolved exactly one account, use it (single-account host — the common case). If it resolved zero, or more than one with no disambiguating path/link, print nothing and exit 0: **"not found," never a guess** (§8.1; pushing as the wrong identity is worse than failing).
     4. With the account chosen, fetch `credentials.get_backend().get_secret(account.secret_service_key)`. `None` → print nothing, exit 0. A value → write exactly `username={account.username}\npassword={secret}\n` to **stdout** and exit 0. `username` comes from the `forge_accounts` row — git requires the helper to supply it on HTTPS, and a blank username line confuses some servers into re-prompting. If the row's `username` is NULL, write the password line alone rather than fabricating one.
   - `store`: read stdin (now including `password`), and *locate the matching account row exactly as in `get` steps 1–3*. If none matches, exit 0 (nothing to update — git tolerates this; the recovery UI watches for "stores that never landed" separately, §5 Phase 4's account-edit flow). If found: `credentials.get_backend().store_secret(key=account.secret_service_key, secret=password_from_stdin, label=f"Wrench: {account.label}")`, exit 0. **Also update `forge_accounts.username` if stdin's `username` differs from the stored row** — this is how a first-time HTTPS clone's username self-populates without a separate settings trip (the `store` git issues right after a successful authenticated op carries the username that just worked).
   - `erase`: stdin has no `password`. Match the account as in `get`; if found, `credentials.get_backend().delete_secret(account.secret_service_key)`, exit 0; else exit 0 silently. (Erase races matter less than writes — a delete that misses is idempotent-safe.)
   - **Every failure inside `main()` — backend down, DB locked, malformed stdin — prints nothing to stdout and exits 0**, logging the real error to stderr only. A credential helper that exits non-zero makes git itself fail with a generic "helper failed" message that obscures the actual problem; git's designed fallback on empty-helper-output is to move on to the next config source, which produces the intelligible "could not read Username" chain the UI already knows how to classify (step 3c).
   - **DB access from the helper (subprocess, no Qt):** the helper is a *separate short-lived process* spawned by git. It must not import `wrench.app`, touch Qt, or use the app's shared `storage/db.py` connection (wrong process). Resolve the DB path via `core.paths.data_dir() / "wrench.db"` (§4.7 — same resolution the app uses, no duplication), open it with `sqlite3.connect(f"file:{path}?mode=ro", uri=True)` — **read-only**: the helper only reads; `store`'s username-backfill is the single write, and that write goes through the normal `sqlite3.connect(path)` (read-write) connection opened *only in the store branch*, so a `get` against a concurrently migrating DB can't interfere. Wrap reads in a retry loop (3 attempts, 100ms apart) that tolerates `sqlite3.OperationalError: database is locked` — the app's WAL-mode writer (§3.1) may legitimately hold the DB at the moment git spawns us. All account/link reads run through `storage/forge_accounts.py`'s query helpers with this connection passed in — never inline SQL in the helper.
   - **Concurrency with the app:** the app's `storage/db.py` uses WAL mode specifically so a background reader like this helper never blocks the UI (§3.1). Do not add any lock file, socket, or mutex for the helper — WAL + the read-only connection is the whole mechanism, and anything on top of it is a new bug farm.
   - **Storage reads the helper depends on (implement these in `storage/forge_accounts.py` NOW, in this phase — the full CRUD set lands in Phase 4 step 4, but the helper cannot wait for it):** the current tree has `list_accounts`/`add_account`/`remove_account` as `NotImplementedError` stubs and **no** link-reading function at all. Add exactly these two read-only helpers, each taking `conn` as the first parameter per §3.1's convention:
     - `list_accounts(conn) -> list[ForgeAccountRecord]` — `SELECT * FROM forge_accounts` mapped to the §3.1 dataclass (which deliberately excludes `secret_service_key`); the helper then needs the key, so it additionally runs `SELECT secret_service_key FROM forge_accounts WHERE id = ?` for the chosen row only — keep the secret-key column out of bulk list results (§3.1's rationale), one targeted lookup per `get` call.
     - `find_link_by_path(conn, owner_slug, repo_slug) -> RepoForgeLink | None` — `SELECT * FROM repo_forge_links WHERE owner_slug = ? AND repo_slug = ?` — the disambiguation lookup from step 2's matching order. (Phase 4 adds `get_link_for_remote` keyed by `(repo_id, remote_name)`; this path-keyed variant is what the *helper* can compute from git's stdin alone — it never knows our internal `repo_id`.)
     Both functions stay in `storage/forge_accounts.py` alongside the Phase 4 write helpers — no separate module, no duplicated SQL. If `storage/forge_accounts.py` currently lacks a `RepoForgeLink` import/circuit, add only what these two functions need.
   - **Config — the helper is useless if git never calls it.** On every `open_repo` (engine, after the registry check), and once at the end of `clone_repo` (step 3d, also for the clone's own origin), run:
     ```
     run_git(repo_path, ["config", "credential.helper", "wrench"])
     run_git(repo_path, ["config", "credential.useHttpPath", "true"])
     ```
     Repo-local config only — never `--global`, never the user's `~/.gitconfig`. `credential.helper = wrench` resolves to the `git-credential-wrench` executable on PATH (git prepends `git credential-` itself; that is why the entry-point name must be exactly `git-credential-wrench`). Writing on *every* `open_repo` is deliberately idempotent — a repo the user opened before upgrading Wrench, or one whose config was clobbered, self-heals on next open. These two lines must also be the FIRST thing `add_remote` does before its `git remote add` (step 5), so a remote added to a not-yet-configured repo can't strand the first push.
   - **`credential.useHttpPath = true` explained (why it's mandatory, not cosmetic):** without it git sends the helper only `protocol`+`host`; two accounts on `github.com` then look identical and step 2's path-matching never fires. This bit is what carries the repo path into stdin (`path=owner/repo.git`). The Phase 2-era note "configure on open_repo" is superseded by the exact two commands above.
   - **Tests** — `tests/unit/core/test_git_credential_helper.py` (invoke `main()` directly with `sys.stdin`/`sys.stdout` monkeypatched via `io.StringIO`; a fake `sqlite3` DB in `tmp_path` seeded through the real `storage/forge_accounts.py` helpers; `credentials.get_backend()` monkeypatched to a stub backend whose `get/store/delete` record calls):
     a. `get` happy path: one account row, its key in the stub backend → stdout contains `username=…` and `password=…` lines and nothing else.
     b. `get` unknown host → stdout empty, exit 0.
     c. `get` two accounts same host, no `path` in stdin → stdout empty, exit 0 (ambiguity must not guess).
     d. `get` two accounts same host, stdin `path=owner/repo.git` matching one account's `repo_forge_links` row → linked account's secret returned, not the other's. 
     e. As (d) but stdin `path=owner/repo` (no `.git`) — identical result (normalization can't be off-by-suffix).
     f. `get` non-HTTP protocol (`protocol=ssh`) → empty stdout, exit 0, backend not touched.
     g. `store` with matching account: backend `store_secret` called with the row's `secret_service_key`, and the row's NULL username backfilled from stdin's `username=`.
     h. `store` with no matching account → backend untouched, exit 0.
     i. `erase` with matching account → backend `delete_secret` called once; without → exit 0, backend untouched.
     j. Malformed stdin (`password=a=b=c` — `=` inside a secret value) parses with the full value intact (the split-once rule).
     k. Backend raising `CredentialBackendUnavailableError` during `get` → caught in `main()`, empty stdout, exit 0, message on stderr (the silent-to-git rule).
     l. `database is locked` on the first two attempts, success on the third → retry loop returns the row (patch `sqlite3.connect` to sequence the errors).
3. `core/write_ops.py` + `core/engine.py`: `push`, `pull`, `fetch`, and the `clone_repo` rewrite. Read all sub-steps before writing code — 3a is the shared foundation the rest assume.
   a. **New streaming sibling: `run_git_streaming(repo_path, args, *, timeout, on_stderr_line, cancel_event=None) -> tuple[int, str, str]`.** The existing `run_git` (`subprocess.run`, fully buffered) cannot report progress — do not modify it; every existing Phase 1–2 caller keeps using it. The new helper uses `subprocess.Popen` with `stderr=subprocess.PIPE, stdout=subprocess.PIPE`, the **same env** as `run_git` (including `GIT_TERMINAL_PROMPT=0`, `LC_ALL=C`, and the SSH passthrough from step 4 — factor env construction into one `_git_env()` used by both helpers so they cannot drift), and:
      - Drains **both** pipes concurrently (two reader threads, or `selectors` — either; a single-threaded read that waits on one pipe the whole run deadlocks the moment git's progress flood fills the 64 KiB stderr pipe while you're blocked on stdout, and vice versa). This deadlock is the #1 real-world failure of naive Popen progress readers; the test in (f) covers it with a >64 KiB-stderr fixture.
      - Decodes each stderr line as bytes → `str` with `errors="replace"` (§4.2's C-locale byte rule), and for every line calls `on_stderr_line(line)`. Progress arrives carriage-return-separated within a line (`Receiving objects:  12%...\rReceiving objects:  34%...`); split on `\r` as well as `\n` before invoking the callback per fragment — parsing only whole `\n`-terminated lines shows the bar frozen until git happens to flush.
      - `cancel_event` polling: check `cancel_event.is_set()` on each read-loop iteration and at least every 100ms; on set → `proc.terminate()`, wait 3s grace, then `proc.kill()`; treat the resulting non-zero exit as *aborted*, not *failed* (callers translate per (c)/(d)).
      - Timeout: enforce the caller's `timeout` for the whole process; on expiry kill and raise `CLITimeoutError`. Network ops pass `timeout=600` (§4.2's table); no unbounded waits.
      - Returns `(returncode, stdout_text, stderr_full_text)` — the full stderr is needed by the classifier in (c) even though each line was already streamed.
   b. **Progress parsing (one function, `_parse_progress(line) -> tuple[int, str] | None`, used by all four ops):** match `^([\w ]+?):\s+(\d+)%\s*\((\d+)/(\d+)\)` — captures (stage, percent). Git's stages include `Enumerating objects`, `Counting objects`, `Compressing objects`, `Receiving objects`, `Resolving deltas`, `Writing objects`; lines prefixed `remote: ` have the prefix stripped first. Non-matching lines return `None` silently (git emits plenty of informational chatter; a parser that raises on it breaks on every git version bump). Each match calls the op's `progress_cb(percent, stage)` (the §4.1 `ProgressCallback`). If git omits `%` entirely (small fetches finish under the reporting threshold), it is valid for `progress_cb` to never fire — the UI must treat "no progress signal" as "indeterminate spinner," not "stalled."
   c. **Failure classification — exact mapping, applied in this order, on non-zero exit from push/pull/fetch** (case-sensitive against `LC_ALL=C` output; all classes from §4.1.A):

      | stderr contains | raise |
      |---|---|
      | `rejected` (push only) | `PushRejectedError(stderr)` |
      | `Not possible to fast-forward` (pull) | `MergeRequiredError(stderr)` |
      | `Authentication failed` / `403` / `401` | `AuthFailedError(host=parsed_host)` |
      | `Permission denied (publickey)` | `AuthFailedError(host=parsed_host)` |
      | `could not read Username` / `could not read Password` / `terminal prompts disabled` | `AuthRequiredError(host=parsed_host)` |
      | `Could not resolve hostname` / `Connection timed out` / `Failed to connect` | `GitCommandError` with stderr attached (UI shows "network unreachable" wording from the stderr; don't invent a new class without amending §4.1.A) |
      | _anything else_ | `GitCommandError(stderr)` as usual |

      The **order matters**: `rejected` before the generic "error: failed to push some refs" line that accompanies it, and auth lines before the generic fallback. `parsed_host` comes from the remote's URL via the same `_host_of()` helper the credential helper uses (step 2) — import it from `core.git_credential_helper` rather than re-deriving URL parsing in a second place.
   d. **The four operations:**
      - `push(repo, remote, branch, *, force=False, progress_cb=None, cancel_event=None)`: `["push", "--progress", remote, branch]`; `force=True` maps to `--force-with-lease` (**never** bare `--force` — lease refuses exactly when someone else updated the ref since our last fetch, which is the only safe auto-force). Success → also refresh `ahead`/`behind` by letting the UI's normal status refresh run (don't hand-compute).
      - `pull(repo, remote, branch, *, progress_cb=None, cancel_event=None)`: `["pull", "--progress", "--ff-only", remote, branch]`. The `--ff-only` refusal is an expected branch, classified as `MergeRequiredError` by (c) — the UI then offers merge or rebase using the existing Phase 2 machinery. Never `pull` without `--ff-only`: a surprise merge commit mid-pull is exactly the behavior the façade exists to prevent.
      - `fetch(repo, remote, *, progress_cb=None, cancel_event=None)`: `["fetch", "--progress", "--prune", remote]` (`--prune` keeps stale remote-tracking branches from accumulating forever; without it the branch-switcher remote section fills with ghosts of deleted branches). On success, record the fetch timestamp via the existing flat settings store — `storage/settings.py` exposes exactly `get_setting(conn, key) -> str | None` and `set_setting(conn, key, value)` over `app_settings`; per-repo values are stored as **namespaced keys**: `set_setting(conn, f"repo.{repo_id}.remote_last_fetch.{remote}", now_iso)`. Do **not** add a per-repo settings table or new accessor functions for this — namespacing one string key is the whole mechanism, keeps this phase migration-free, and matches how `ui.session_state` blobs already key per-repo draft state. `list_remotes` (step 5) and the reachability probe read back through the same `get_setting` call. ISO-8601 UTC for the value.
      - `clone_repo(url, dest, *, progress_cb=None)` **(rewrite of the existing stub):**
        1. Reject early if `dest` exists and is non-empty → `GitCommandError` with "destination exists" — don't let git's own message be the first thing the user sees.
        2. `temp_dir = tempfile.mkdtemp(prefix="wrench-clone-", dir=dest.parent)` — same filesystem as `dest` so the final move is atomic rename, not a cross-device copy.
        3. `run_git_streaming(dest.parent, ["clone", "--progress", url, temp_dir], timeout=600, on_stderr_line=..., cancel_event=...)` — note `cwd` is `dest.parent`, not the nonexistent repo path; `run_git`'s `repo_path` parameter is a *working directory*, not necessarily a repo.
        4. On success: `shutil.move(temp_dir, dest)` — but if anything exists at `dest` by now (race), fail with the error rather than overwriting.
        5. **Write the credential config into the fresh clone** (step 2's two `git config` commands verbatim) — the first fetch/push from this repo must go through the helper.
        6. On any exception or cancellation: `shutil.rmtree(temp_dir, ignore_errors=True)`; `dest` is left exactly as found. Cancellation raises `CloneAbortedError` (§4.1.A); the UI shows no error for it.
        7. Return `CloneResult(path=dest)`. The engine wrapper stays a thin pass-through; opening the repo flows through the UI's existing `open_repo` completion path (which auto-registers in `repo_registry`).
   e. **engine.py wiring + the workers.py int-signal reconciliation.** Replace the three `NotImplementedError` stubs with the §4.1 signatures, delegating to write_ops, translating per (c). `ui/workers.py` keeps `progress = Signal(int)` — in `GitOperationWorker.run`, inject `progress_cb=lambda pct, stage: self.progress.emit(pct)` when the target accepts `progress_cb` (the stage string is dropped at this boundary; call sites that want stage text pass their own callback object instead of taking the signal). One adapter line, no Qt signature churn, and the busy dialog's bar keeps its existing int contract.
   f. **Tests** (`tests/unit/core/test_write_ops_remotes.py`, new): against a **bare fixture remote** (`git init --bare` in `tmp_path`, clone it, commit, push) — real git both sides, no mocks:
      1. push happy path: new commit pushed to bare remote; assert exit 0 and the ref exists in the bare repo.
      2. push non-fast-forward (advance the bare repo from a second clone) → `PushRejectedError`.
      3. pull with diverged branches → `MergeRequiredError`, and pull after a plain commit → fast-forwards cleanly.
      4. fetch records `remote_last_fetch.origin` in settings (assert the key, don't parse the value's format).
      5. Pull-request of progress: mock nothing — intercept `on_stderr_line` in the streaming helper test with a fake `args=["-c", "..."]`-style subprocess substitute (a tiny Python script via `sys.executable` that writes `>64 KiB` of progress-shaped lines to stderr): assert all lines streamed and no deadlock at the pipe buffer (this is the (a) deadlock regression test — keep it).
      6. `cancel_event` set mid-clone (threading.Timer at ~0.2s against a deliberately slow local source — a repo with `uploadpack` throttled, or simply assert the aborted exception class and that `dest` does not exist): `CloneAbortedError`, no partial dir.
      7. Classifier unit table: feed each (c) row's literal stderr into the classifier function directly, assert the exception type — no subprocess needed for this one.
4. SSH agent (FR-4.2/FR-11.3) — verification and the one code hook, not new machinery:
   - **Manifest check (must be true before any QA):** `packaging/flatpak/io.github.uzair.Wrench.yaml` `finish-args` contains `--socket=ssh-auth`. If it's missing, add it in this phase, not Phase 6 — a missing socket makes every SSH remote in Flatpak fail with "Permission denied (publickey)" and the failure mode is invisible from logs until you strace ssh.
   - **Code hook (exactly one):** in the shared `_git_env()` from step 3a, `sock = core.ssh_agent.get_ssh_auth_socket()`; if non-None, put it into the subprocess env as `SSH_AUTH_SOCK` **unmodified**; if None, omit the variable entirely (never inject an empty string — ssh treats an empty `SSH_AUTH_SOCK` as "agent configured at empty path" and fails differently than "no agent," which misleads the (c) classifier). `core/ssh_agent.py` itself is already correct per §4.7 — one function, `get_ssh_auth_socket()`, nothing else; do not extend it in this phase.
   - **No force-loading:** do not spawn `ssh-agent`, prompt for passphrases, or list identities. Git+ssh inherit the user's agent state as-is; v1's documented scope (SRS §7) is "works with a running plain ssh-agent; GPG-agent/hardware-key setups are known-unsupported and documented, not silently broken."
   - **Tests:** `tests/unit/core/test_ssh_agent.py` — `get_ssh_auth_socket()` returns `None` with the env var unset and the value when set (trivial, but it pins the contract every `_git_env` user depends on); plus one `_git_env()` test asserting the var is passed through when present and absent from the mapping entirely when None.
5. FR-4.4 — remotes management (engine + one dialog):
   - `engine.list_remotes(repo) -> list[RemoteInfo]` (§4.1): read `pygit2.Repository.remotes` (name + fetch URL); for each, look up settings keys `repo.{repo_id}.remote_last_fetch.{name}` and `repo.{repo_id}.remote_reachable.{name}` (step 3d's namespace convention) to fill `last_fetch_at`/`is_reachable`. **Connectivity probes never run inside `list_remotes`** — it must be instant; probes are (a) fired in the background by `add_remote`, and (b) re-fired only by an explicit "Refresh status" action in the dialog. A `list_remotes` call that touches the network freezes the dialog for up-to-timeout seconds on every open.
   - `engine.add_remote(repo, name, url) -> None` — **ordered contract, exactly this sequence:** (1) validate `name` against `^[A-Za-z0-9][A-Za-z0-9._-]*$` (reject empties/spaces/leading-dash with `GitCommandError` carrying the message "invalid remote name" — surface it verbatim, it's a programmer error the user can fix); (2) validate `url` is parseable as one of `https://…`, `http://…`, `ssh://…`, or scp-style `user@host:path` — reject anything else with a clear message (a malformed URL accepted here fails four steps later as an opaque transport error); (3) check `name` against existing remotes → `RemoteExistsError` before any git call; (4) write the credential config (step 2's two `git config` commands) so the repo is helper-ready even if it was registered before Wrench managed it; (5) `run_git(["remote", "add", name, url])`; (6) fire the reachability probe — `run_git(repo_path, ["ls-remote", name, "HEAD"], timeout=15)` — in a background thread, storing the boolean outcome under the settings key `repo.{repo_id}.remote_reachable.{name}` (same namespace as step 3d); probe failure does NOT fail `add_remote` (the remote is real even if the host is down right now).
   - `engine.remove_remote(repo, name)` → `run_git(["remote", "remove", name])`; unknown name → `RemoteNotFoundError` from a pre-check, not from git's stderr. `engine.set_remote_url(repo, name, url)` → `["remote", "set-url", name, url]` with the same validation + not-found prechecks as `add_remote`. Both also touched when the dialog's Edit/Remove buttons exist — without them the dialog is read-only, which is not FR-4.4.
   - **UI: `ui/dialogs/remotes_dialog.py`** (create the `ui/dialogs/` package if this is its first member in the working tree; keep the dialog consistent with wherever the Phase 2 recovery/merge dialogs live — check the current tree before creating parallel structure). Contents: a table (Name, URL, Last fetch, Reachability dot), buttons Add / Edit / Remove / "Refresh status"; Remove requires the project's standard destructive-action confirmation. Modest size, launched from the menu — **S**-priority surface (SRS §3.4), no top-level tab.
   - **UI wiring for the operations themselves (where push/pull/fetch are triggered):** add a **Repository** menu to `main_window.py`'s menu bar next to File/Edit/View — Fetch, Pull, Push, separator, Remotes…. Each action: run through `ui.workers.run_in_background` (§4.8, mandatory), reuse the Phase 2 busy/cancel dialog (`BusyOperationDialog` in the recovery dialogs module — locate wherever `recovery_dialog.py` lives in the tree; do not build a second busy dialog), wire `on_progress` to its bar, and on success call the main window's existing full-refresh path (fetch changes `refs/remotes/*`, so status + branch switcher + commit graph all need it; the inotify watcher does not reliably fire for packed-refs updates — force the refresh, don't wait for the watcher). Failure routing: `AuthRequiredError` → open the account/link flow placeholder ("Add account…" lands properly in Phase 4; for now the dialog explains no credential was found and names the host); `AuthFailedError` → "stored credential rejected, check the account token"; `PushRejectedError` → offer Fetch-then-retry; `MergeRequiredError` → offer merge/rebase via the Phase 2 entry points; `RemoteNotFoundError` → open the Remotes dialog.
   - **The clone flow**: the existing File → Clone (`main_window._on_clone_repo`) keeps its URL/destination inputs but must route `engine.clone_repo` through `run_in_background` with the busy dialog + progress + cancel button, per §4.8/§5 Phase 3 step 3d; on success, open the repo via the existing post-open path. If the current implementation calls it synchronously, this step is where that gets fixed (Step 0's note).
6. **Acceptance check — Phase 3 is done when ALL of the following have actually been executed, not eyeballed:**
   - **Automated:** `pytest tests/unit/credentials tests/unit/core -v` green — which now must include the step-1 credential cases (a–j), the step-2 helper cases (a–l), step 3f's remote-op tests, and step 4's ssh env tests. `ruff check . && black --check .` clean.
   - **Credential plumbing, end to end (manual):** with a throwaway HTTPS repo on GitHub (a private test repo on a PAT is ideal — a guessed-at docs URL won't exercise auth), push, pull, and fetch all succeed with the credential supplied exclusively by the helper. Verify the plumbing, not just the outcome: `GIT_TRACE=1 GIT_CURL_VERBOSE=0 git -C <repo> fetch` from a terminal using the repo-local config shows `git credential-wrench get` being invoked. Then the plaintext audit — `strace -f -e trace=openat,open,creat -o /tmp/wrench-strace.log python -m wrench`, run a push+pull, quit, and `grep -i -E "credential|password|token" /tmp/wrench-strace.log` shows only the keyring paths (e.g. `org.freedesktop.secrets` D-Bus traffic, gnome-keyring files); **zero** opens of ad-hoc credential files under the repo or home dir. `git config --list --local` inside the repo shows exactly `credential.helper=wrench` and `credential.useHttpPath=true`, nothing credential-ish in plaintext.
   - **Wrong-identity audit:** configure two accounts on the same host (e.g. two GitHub PATs with different usernames), link the test repo to account A via `repo_forge_links`, push, and confirm via the remote's API/audit view (or the commit's pusher identity) that account A's token was used. Then delete the link row, re-push, and confirm it now fails with the "no credential" path (ambiguity must never silently pick one) — restore the link row afterward.
   - **Rejection paths (manual, not just unit):** a non-fast-forward push produces the PushRejected dialog with the fetch-and-retry action; a diverged pull produces the merge/rebase chooser; an SSH remote with no agent produces `AuthFailedError`'s message, not a hang.
   - **UI responsiveness (§4.8 enforcement):** clone a repo large enough to take visible seconds (e.g. ≥50 MB), confirm the window drags/resizes *during* the clone, the progress bar moves with real percents, and a mid-clone Cancel leaves no directory at the destination — not empty, *absent*. Repeat once for a mid-push cancel of a large push.
   - **SSH scope check:** push/pull over `git@`-style SSH with plain `ssh-agent` works (§9's documented v1 scope); confirm GPG-agent/hardware-key cases fail with the documented-limitation message and not a stack trace.
   - **State visible in UI:** Remotes dialog lists `origin` with a real last-fetch time after a fetch; Add/Edit/Remove round-trip against git's own `git remote -v` output.

### Phase 4 — Forge Integration Layer
**Prerequisites:** Phase 3's acceptance check passed (push/pull/fetch working with Secret-Service-backed credentials, at least over plain ssh-agent and HTTPS).

**Step 0 — repo-state reconciliation (verified against the tree at Phase 3 completion; per Phase 3's precedent, corrections here beat greenfield assumptions):**
   - `forge/` exists with `models.py`, `capability.py`, `registry.py`, and `adapters/{github,gitlab,forgejo,bitbucket}.py` — **all stubs raising `NotImplementedError`**. The class names and module paths are already correct per §3; this phase fills bodies, not files. There is **no `forge/exceptions.py`** — step 1 creates it per §4.3.A.
   - `pyproject.toml` **already** registers all four adapters under `[project.entry-points."wrench.forge_adapters"]` (§4.4) — step 3 only verifies; do not re-add duplicate entries.
   - `storage/forge_accounts.py` has `ForgeAccountRecord`/`RepoForgeLink` dataclasses plus `NotImplementedError` stubs for `add_account`/`remove_account`/the link helpers; the two read helpers (`list_accounts`, `find_link_by_path`) were implemented in **Phase 3 step 2** because the credential helper needed them — step 4 verifies those two already exist, completes the write/link CRUD, and adds one more read the UI needs (`get_account_full`).
   - `ui/forge_panel/__init__.py` exists as an empty package; the §3 layout lists `ui/tabs/pr_list_tab.py`, `pr_detail_tab.py`, `issue_list_tab.py`, `issue_detail_tab.py`, which **do not exist yet**. Step 6 creates the tabs per the §3 names (the tab system's dedup key `(tab_type, repo_path, entity_id)` from Phase 1.5 governs their lifecycle).
   - `tests/integration/{github,gitlab,forgejo,bitbucket}/` exist containing only `.gitkeep`; `tests/fixtures/forge_responses/` does not exist — step 5 creates it alongside each adapter's tests.
   - **A spec snag to resolve before step 4**: `forge_accounts.secret_service_key` is documented (§4.5) as `wrench:forge:{account.id}` — but the id doesn't exist until the row is inserted, so the key can't be computed at INSERT time. Step 4's `add_account` resolves this with a two-step insert-update; follow that exactly rather than redesigning the key format.

1. `forge/models.py` + `forge/exceptions.py`: fill in the dataclasses exactly as §4.3 defines them (`PullRequest`, `Issue`, `CIStatus`, `ForgeAccount` — the stubs exist; replace the stub bodies, keeping field names/order identical because `storage/forge_accounts.py` and the credential helper already import these names), and create `exceptions.py` with the six-class hierarchy in §4.3.A verbatim. `state` normalization rules to encode as module-level docstring + per-adapter maps (step 5): `PullRequest.state` ∈ `{"open","merged","closed"}` — GitHub's `open/closed`+`merged_at!=null`, GitLab's `opened/merged/closed`, Forgejo's `open/closed`+`merged` bool, Bitbucket's `OPEN/MERGED/DECLINED/SUPERSEDED` (DECLINED and SUPERSEDED both map to `"closed"`). `Issue.state` ∈ `{"open","closed"}`. `CIStatus.state` ∈ `{"success","failure","pending","unknown"}` — **the "no CI configured" case returns `CIStatus(state="unknown", url=None, description=None)`, never raises**: a repo without CI is a normal state, not an error, and the UI renders it as a neutral icon distinct from pending. Unit test per mapping table row in each adapter's test file (step 5 enumerates them).
2. `forge/capability.py`: implement `ForgeCapability` and `ForgeAdapter` exactly as in §4.3 — this file should need no changes once Phase 4 starts writing adapters; if an adapter's needs don't fit the existing interface, that's a signal to revisit §4.3 deliberately, not to bolt on a one-off adapter-specific method. **Add a shared HTTP layer on `ForgeAdapter` itself** so the four adapters never call `httpx` directly — this is deliberate, not incidental: rate-limit handling, offline detection, and auth-failure translation are identical logic that four independently-written adapters would otherwise each get slightly wrong in their own way. Exact contract:
   - `self._client = httpx.Client(base_url=<adapter-specific>, verify=<per-account TLS policy: False if account.tls_insecure, else account.tls_ca_bundle_path or True>, timeout=httpx.Timeout(connect=10.0, read=30.0, write=10.0, pool=10.0), follow_redirects=True)` created in `__init__` from the account. The `verify=` value comes straight from the `forge_accounts` columns (§3.1 — item 13's resolution: system trust store by default, a user-supplied PEM bundle for self-signed instances, explicit skip-verification as the last-resort option); whenever `tls_insecure` is in effect, `_client` construction also emits a WARNING log line naming the account **label** (never the token) — insecure TLS must be loud in the diagnostics log, not silent. **Base URL derivation is per-adapter**: GitHub always `https://api.github.com` for `github.com` accounts, but a self-hosted GitHub Enterprise uses `{instance_url}/api/v3` — GitLab `{instance_url}/api/v4`, Forgejo `{instance_url}/api/v1`, Bitbucket Cloud always `https://api.bitbucket.org/2.0` (no self-hosted variant in v1). Each adapter owns its `base_url` construction in `__init__`; `_request` only joins paths.
   - `self._request(method, path, *, json=None, params=None) -> httpx.Response` — the only HTTP verb surface adapters use:
     a. Inject the auth header from `self._auth_headers()` (abstract per adapter — GitHub `Authorization: Bearer {token}`, GitLab `PRIVATE-TOKEN: {token}`, Forgejo `Authorization: token {token}`, Bitbucket HTTP Basic via `httpx.BasicAuth(email, token)` passed as `auth=`). The token itself comes from `credentials.get_backend().get_secret(account.secret_service_key)` — fetched in `authenticate()` and cached on `self`; never log it, never put it in params.
     b. Execute with the timeout above; catch `httpx.ConnectError`/`httpx.TimeoutException` → `ForgeUnreachableError(self.account.instance_url, str(e))` (§4.3.A).
     c. `401` → `ForgeAuthenticationError(f"{self.account.provider} token for {self.account.label} was rejected — it may be expired or revoked")`; `403` → `ForgeInsufficientScopeError(...)` with a `scope_hint` string naming the conventional fix ("needs `repo` scope" / "needs `api` scope" — per adapter, known per provider, step 5).
     d. `429` → `ForgeRateLimitedError(retry_after_seconds=int(response.headers.get("Retry-After", "60")))`.
     e. Other 4xx/5xx → `ForgeError(f"{provider} API error {status}: {body[:300]}")` — truncate the body, API error pages can be huge HTML.
     f. Success → return the response; adapters do their own `.json()` and field mapping.
   - `authenticate()` (no parameter — the account was bound in `__init__`, §4.3): each adapter implements it as "one cheap authenticated GET against the provider's identity endpoint" (GitHub `GET /user`, GitLab `GET /user`, Forgejo `GET /user`, Bitbucket `GET /user`) purely through `self._request` — so the exception translation above already applies. It exists to validate a token *before* it's saved in the Add-account flow (step 7 — construct the adapter with a not-yet-persisted account and call this), and to revalidate on 401 recovery. No side effects beyond the request; success = no exception.
   - **Pagination helper** `_paged_get(path, params, *, per_page=50) -> list[dict]`: the three pagination shapes (Link header, page/limit+X-Total-Count, full-URL-in-body from §5 Phase 4 step 5) are adapter-specific in *mechanism* but uniform in *contract*: return the concatenated item list; cap at 10 pages (500 items) per call as a runaway guard — a repo with more open PRs than that is beyond v1's UI design anyway, and an uncapped loop turns a provider bug into an infinite request storm; pass the cap through as a keyword so tests can set it to 2.
   - Threading: `ForgeAdapter` instances are created and used inside `run_in_background` workers from the UI; the httpx client is not thread-shared — one adapter instance per background operation, no caching across threads.
3. `forge/registry.py`: implement `discover_adapters()`/`get_adapter_for_account()` exactly per §4.4. **The entry-points section is already in `pyproject.toml`** (Step 0) — verify it matches §4.4 verbatim; if it was regenerated/lost, re-add in this same commit. Two implementation details §4.4 leaves open, settled here: (a) cache the `discover_adapters()` result in a module-level dict after first call — `importlib.metadata.entry_points()` re-scans installed distributions on every call, and the UI calls `get_adapter_for_account` per panel render; (b) construct the adapter with the account passed to `__init__(account)` (§4.3's "one instance per configured forge_account row" — the adapter binds its account at construction, which is why step 2's `authenticate()` takes no parameter). A duplicate `provider_id` across two entry points raises `ForgeError` at discovery time listing both sources — never silently last-one-wins; a shadowed built-in adapter is a debugging nightmare and must fail loud.
4. `storage/forge_accounts.py`: complete the CRUD. The Phase 3 read helpers (`list_accounts`, `find_link_by_path`) already exist — verify them against §5 Phase 3 step 2's contract rather than rewriting; everything else below is new this phase:
   - `add_account(conn, provider, instance_url, label, username, token, *, tls_ca_bundle_path=None, tls_insecure=False) -> int` — **note the signature takes the raw token, not a key** (the key can't be computed before insert: it embeds the row id — §4.5's format `wrench:forge:{id}`). Exact two-step sequence: (1) `INSERT INTO forge_accounts (provider, instance_url, label, username, tls_ca_bundle_path, tls_insecure, secret_service_key) VALUES (?, ?, ?, ?, ?, ?, ?)` with a placeholder key `wrench:forge:pending:{uuid4().hex}` (satisfies the NOT NULL UNIQUE column during the insert); (2) immediately `UPDATE forge_accounts SET secret_service_key = ? WHERE id = ?` with `f"wrench:forge:{new_id}"`. Then (3) `credentials.get_backend().store_secret(key, token, label=f"Wrench: {label}")`. **Order is not negotiable**: row insert first, secret second — if the secret store throws (`CredentialBackendUnavailableError`, locked keyring), delete the row and re-raise, because an account row pointing at a never-stored secret is a silent credential failure later (the helper finds the row, gets `None` from the backend, and the user gets an inexplicable "auth failed" loop). The whole sequence runs under the module lock §4.8 requires.
   - `list_accounts(conn, provider=None) -> list[ForgeAccountRecord]`: all accounts, optionally filtered — used by the account-picker UI (step 7). Already implemented in Phase 3; add the `provider` filter parameter if missing.
   - `get_account_full(conn, account_id) -> ForgeAccount | None`: returns the §4.3 `ForgeAccount` (WITH `secret_service_key`) for adapter construction — this is the one function that intentionally bypasses §3.1's "record excludes the key" rule, because the registry needs the key to build an adapter (`get_adapter_for_account` takes a full `ForgeAccount`). The only legitimate caller is the forge-panel load path (step 6): fetch it, hand it to `registry.get_adapter_for_account` within the same background operation, done — never display, log, or cache the result anywhere else.
   - `remove_account(conn, account_id) -> None`: read the row's `secret_service_key` first, delete the row (cascades to `repo_forge_links` — the links vanish, by design: an account without a row can't be linked anyway), then `credentials.get_backend().delete_secret(key)`. Same rationale as before: never an orphaned secret in the keyring. If the backend delete throws (keyring down), the row is already gone — log and continue; a stranded secret is far less harmful than a stranded account row.
   - `link_repo_to_account(conn, repo_id, forge_account_id, remote_name, owner_slug, repo_slug) -> None`: upsert on the `(repo_id, remote_name)` primary key (`INSERT ... ON CONFLICT(repo_id, remote_name) DO UPDATE SET forge_account_id=excluded.forge_account_id, owner_slug=excluded.owner_slug, repo_slug=excluded.repo_slug`) — relinking a remote to a different account is a normal operation, not an error.
   - `get_link_for_remote(conn, repo_id, remote_name) -> RepoForgeLink | None`: the (repo,remote)-keyed lookup the forge panel needs; complements Phase 3's path-keyed `find_link_by_path`.
   - `get_remote_slug(conn, repo_id, remote_name) -> tuple[str, str] | None`: returns `(owner_slug, repo_slug)` from the link row — the forge panel needs this on every load to know which owner/repo path to query, without parsing the remote URL itself.
   - Unit tests (`tests/unit/storage/test_forge_accounts.py`, in-memory `sqlite3.connect(":memory:")` per §3.1): full add→list→get_full→link→get_link→remove lifecycle; the add-account secret-store-failure path (mock the backend to raise) → no row remains and the exception propagates; upsert link twice with different accounts → second read returns the second account; two accounts same provider+instance_url coexist (the no-uniqueness-constraint property that FR-5.8 depends on).
5. Adapter implementation order (build GitHub first — best-documented API, most available test fixtures — then reuse its test patterns for the rest). **Shared rules for all four** before per-adapter notes:
   - Every adapter subclasses `ForgeAdapter`, sets `provider_id` to the entry-point key verbatim (`"github"`, `"gitlab"`, `"forgejo"`, `"bitbucket"`), declares its real `capabilities` set (all four: `PULL_REQUESTS | ISSUES | CI_STATUS | ISSUE_LINKING` — Bitbucket's issues endpoint exists in 2.0; if a provider legitimately lacked one, the correct answer is a smaller capability set, and the UI already gates on it).
   - Every adapter lives entirely behind `self._request` (step 2) — `grep -n "httpx\." src/wrench/forge/adapters/ | grep -v capability` must return **zero hits** in review; CI-enforceable later if it drifts.
   - All list methods take `(owner, repo)` and accept an optional `state` filter that the panel passes through; never enumerate more than the `_paged_get` cap from step 2.
   - Each adapter's test file lives in `tests/integration/{provider}/test_{provider}_adapter.py`, using `responses` with fixtures from `tests/fixtures/forge_responses/{provider}/*.json` — filenames named after the endpoint action (`list_prs_ok.json`, `list_prs_page2.json`, `create_pr.json`, `ci_success.json`, `user_ok.json`, `error_401.json`, `error_403.json`, `error_429.json`). Minimum test matrix **per adapter** (each its own test, no combined mega-tests):
     1. `authenticate` success against `user_ok.json` → returns without exception.
     2. `authenticate` against `error_401.json` → `ForgeAuthenticationError`; against `error_403.json` → `ForgeInsufficientScopeError`; a network-level `httpx.ConnectError` (no response registered; `responses` raises ConnectionError → wrap accordingly) → `ForgeUnreachableError` carrying the instance URL.
     3. 429 fixture → `ForgeRateLimitedError` with the fixture's `Retry-After` value, and the no-header spouse-case → 60s default.
     4. `list_pull_requests` happy path maps every field including the provider's state vocabulary → normalized `open|merged|closed` (assert the two or three provider-native states that map onto each normalized one — e.g. a `DECLINED` Bitbucket PR and a `closed` GitHub PR both yield `state == "closed"`).
     5. `list_pull_requests` pagination: two `responses`-registered pages → concatenated result, in order. With the page cap set to 1 via the keyword, assert exactly one page is fetched (the cap actually truncates — an uncapped loop over a pathological fixture would hang the test, which is precisely why the cap exists).
     6. `create_pull_request` posts the right body shape for the provider (assert the request JSON via `responses.calls[0].request.body`) and maps the response.
     7. `get_ci_status` success/failure/pending fixtures map to the three normalized states; a 404 or empty-list fixture (repo has no CI at all) → `CIStatus(state="unknown", ...)` and **not** an exception.
     8. `list_issues` where supported: normalized open/closed mapping, same pagination rules.
     9. The `state` filter parameter (open/closed/all) reaches the query string correctly per provider.
     10. `submit_review`: one fixture or `responses`-asserted-request per action in that adapter's `supported_review_actions` (GitHub/Forgejo: `reviews` endpoint with the right event string — catch a Forgejo test that uses `APPROVE` instead of `APPROVED`; GitLab: approve+notes endpoints, plus a test that `request_changes` never reaches HTTP; Bitbucket: the three separate endpoints with the `content.raw` body shape) — and one 403 fixture asserting `ForgeInsufficientScopeError` with the review-scope hint.
   - **Review actions (§11 item 14, resolved: in-app review IS v1 scope):** every built-in adapter sets `ForgeCapability.REVIEWS` and implements `submit_review`; per-provider endpoint mappings are in the notes below. `supported_review_actions` defaults to all three normalized actions; GitLab narrows it to `{approve, comment}` (no first-class request-changes endpoint). The UI grays buttons from that set — capability-gated at render, never call-and-catch.
   - **Adapter-specific notes** (the deltas, not the full code):
      - `forge/adapters/github.py` — REST v3 (`api.github.com`; Enterprise `{instance_url}/api/v3`), `Authorization: Bearer`, combined-status endpoint for CI. Owner/repo in the URL path verbatim — no URL-encoding gymnastics needed for normal slugs; they come from `repo_forge_links` slugs which validated at link time. **`list_issues` trap**: GitHub's `GET /repos/{owner}/{repo}/issues` returns pull requests mixed in with issues — filter out every item carrying a `pull_request` key before mapping; missing this yields "issues" that are secretly PRs, and the Issues tab shows double entries. `submit_review` → `POST /repos/{o}/{r}/pulls/{n}/reviews` with `{"event": "APPROVE"|"REQUEST_CHANGES"|"COMMENT", "body": ...}` — GitHub matches the normalized vocabulary one-to-one, no narrowing.
     - `forge/adapters/gitlab.py` — REST v4, `PRIVATE-TOKEN` header, self-hosted `{instance_url}/api/v4`. PR↔MR vocabulary mapping is the whole point of the `PullRequest` model. CI: `GET /projects/{id}/pipelines?sha={ref}` newest-first, first entry's `status` maps (`success`/`failed`/`running|pending`/`canceled|skipped→unknown`-family — map `canceled`/`skipped` to `unknown`, NOT `failure`: a cancelled pipeline is not a red build and scaring the user over it is a false alarm). `submit_review` → approve is `POST /projects/{id}/merge_requests/{iid}/approve`, comment is `POST /projects/{id}/merge_requests/{iid}/notes` with `{"body": ...}`; GitLab has **no first-class request-changes action**, so this adapter overrides `supported_review_actions` to `{"approve", "comment"}` — the UI grays the button accordingly. Note the `/approve` endpoint rejects approving your *own* MR with 401; that surfaces as `ForgeAuthenticationError` which is misleading — catch the 401-body "You cannot approve" case and re-raise as `ForgeError` with the plain explanation instead.
      - `forge/adapters/forgejo.py` — `/api/v1/`, `Authorization: token {token}`. Build **third**, deliberately, per the risk register. Pagination `page`/`limit`+`X-Total-Count`. Its commit-status endpoint is `/repos/{owner}/{repo}/commits/{ref}/status` (Gitea-compatible combined status); a 404 there = unknown. `submit_review` → `POST /repos/{o}/{r}/pulls/{n}/reviews` with `{"event": "APPROVED"|"REQUEST_CHANGES"|"COMMENT", "body": ...}` — note the event vocabulary is `APPROVED` (past tense), not `APPROVE`; the adapter maps the normalized `'approve'` to it. **TLS (§11 item 13, resolved — per-account policy):** this adapter gets nothing TLS-specific in code; the policy lives in the account row (`tls_ca_bundle_path` / `tls_insecure`, §3.1) and is applied by the shared `_client` construction in step 2's `verify=`. A self-signed instance with neither set still surfaces as `ForgeUnreachableError` — that failure is now the *prompt* for the user to open the account's TLS settings, and the banner text says exactly that ("if this instance uses a self-signed certificate, set its CA bundle in the account settings"). Minimum supported server version: Gitea ≥ 1.20 / Forgejo ≥ 1.20 (the `/reviews` and combined-status endpoints used here are stable that far back); older instances are untested, not blocked — no version sniffing in the adapter.
     - `forge/adapters/bitbucket.py` — `api.bitbucket.org/2.0`, **HTTP Basic Auth via `httpx.BasicAuth(email, api_token)`** — account.username holds the email; if username is empty for a Bitbucket account, raise `ForgeAuthenticationError` immediately with "Bitbucket requires the Atlassian email as the username" — do not send an anonymous request and surface a generic 401. App Passwords are dead (§5 ban — do not implement). Pagination via `next` full-URL from the response body; PR state vocabulary `OPEN|MERGED|DECLINED|SUPERSEDED`; CI ("builds") `GET /repositories/{workspace}/{repo}/commit/{ref}/statuses` (paginated values list, state `SUCCESSFUL|FAILED|INPROGRESS|STOPPED` → success/failure/pending, STOPPED→unknown). `submit_review` → approve is `POST /repositories/{w}/{r}/pullrequests/{id}/approve`, request-changes is `POST .../request-changes`, comment is `POST .../pullrequests/{id}/comments` with `{"content": {"raw": body}}` — all three map, no narrowing.
6. Forge UI surface — the §3 files `ui/tabs/pr_list_tab.py`, `pr_detail_tab.py`, `issue_list_tab.py`, `issue_detail_tab.py` (new), plus shared widgets in `ui/forge_panel/` (state-badge and CI-icon widgets that render the normalized `state` strings from step 1). Rules that apply uniformly:
   - **Tab lifecycle**: register the four tab types with the Phase 1.5 tab system's existing registration mechanism — dedup key `(tab_type, repo_path)` for the two list tabs, `(tab_type, repo_path, entity_id)` for the detail tabs, exactly per Phase 1.5's dedup rule. No homegrown tab management.
   - **Link resolution on every list-tab open** (this is the seam where the whole phase's data flow starts): look up `storage.forge_accounts.get_link_for_remote(conn, repo_id, remote_name)` with `remote_name="origin"` first, falling back to the first remote from `engine.list_remotes` if origin is absent. Three outcomes: (a) no link → the tab shows an empty state with a "Link this repository…" button that launches step 7's link flow — not an error, not a silently empty list; (b) link → load the account via `get_account_full` (the normal route — this is adapter construction, allowed) and hand it to `registry.get_adapter_for_account`; (c) link exists but its account row is gone (deleted account) → empty state saying the linked account no longer exists, with a relink button — `repo_forge_links` rows cascade-delete with the account, so this should be dead code, but if it ever renders it's better than a crash.
   - **Threading, no exceptions**: every adapter call (list, create, CI, authenticate) runs via `ui.workers.run_in_background` (§4.8) with a `BusyOperationDialog` for the create-PR flow — the same dialog Phase 2/Phase 3 reuse, not a new one. One adapter instance per operation (step 2's no-thread-shared-client rule).
   - **No N+1 CI fetches**: the PR list renders title/author/state/branch-pair only — **no per-row CI call**. CI status is fetched once, for the opened PR, in `pr_detail_tab`. (This deliberately narrows an earlier draft that showed a per-row CI icon: one HTTP request per row per render is a rate-limit farm against `429`; the detail tab keeps the same information one click away.)
   - **Error routing is per exception class, once, in a shared helper in `ui/forge_panel/`** (all four tabs call it): `ForgeAuthenticationError` → inline banner "Stored token for {label} was rejected — re-enter it" launching step 7's token re-entry; `ForgeRateLimitedError` → banner "Rate limited, try again in {retry_after_seconds}s" with a disabled-until-then refresh button; `ForgeUnreachableError` → banner "Can't reach {instance_url} — check connection/VPN"; `ForgeInsufficientScopeError` → banner "Token for {label} lacks {scope_hint} — update its scopes at the provider, then refresh"; other `ForgeError` → generic banner with the (already token-free, truncated) message + Retry. None of these reach the generic crash path, and none log the token — messages built in step 2 carry no secret material by construction.
   - **Capability gating**: tab visibility follows `adapter.capabilities` (issues tab hidden when `ISSUES` unset), never call-and-catch-`NotImplementedError`.
   - **SRS NFRs that bind this code directly**: every user-visible string wrapped in `tr()` (§4 Localization row — English-only but structured from day one); full keyboard navigation for lists/details/dialogs and accessible names on icon-only buttons (CI icon, refresh button) per the Accessibility row — these are v1 gates (master checklist 7.2/7.4), not polish.
   - **Create-PR flow**: button on the PR list tab (capability-gated) → modal form (title, description, source branch defaulting to the repo's current branch, target branch defaulting to the remote's default branch; branch dropdowns from `engine.list_branches`) → submit in background (busy dialog) → on success open the new PR in `pr_detail_tab` (its `url` field also gets an "Open in browser" action — `QDesktopServices.openUrl`, same pattern the diagnostics deep-link uses). `ForgeInsufficientScopeError` here renders the `scope_hint` text directly — the user sees "needs `repo` scope" rather than an unexplained 403.
   - **Review actions** on `pr_detail_tab` (§4.3's `submit_review` — v1 scope, §11 item 14): three buttons — **Approve**, **Request changes**, **Comment** — gated on `ForgeCapability.REVIEWS in adapter.capabilities` AND the action being in `adapter.supported_review_actions` (a GitLab-linked repo renders Request-changes grayed with a tooltip "GitLab has no request-changes action", not missing-from-layout — the tab's layout stays stable across providers). All three open the same small confirm dialog with a `body` text field (empty body allowed for approve/request-changes, required for comment — the provider APIs all accept it on approve/reject; an empty comment is a UI-level mistake, not an API error to surface). Submit runs via `run_in_background`; on success, show a transient confirmation ("Review submitted") and refresh the PR detail. There's deliberately **no in-app review-thread viewer** in v1 — submitted bodies land on the provider; the "Open in browser" action covers seeing the conversation. (§4.3's `submit_review` docstring carries this "action surface only" boundary.)
7. Multi-account UI (FR-5.6/5.8/5.9). Two dialogs, one flow contract:
   - **Accounts manager** — `ui/dialogs/accounts_dialog.py` (create if Phase 3's remotes dialog didn't already establish `ui/dialogs/`; same placement rule as Phase 3 step 5). A list of all `forge_accounts` rows (label, provider, instance URL, username — **never the token, and never show the secret after entry**) plus Add / Edit label / Remove. **Nothing here requires removing an existing account to add another** — no uniqueness constraint blocks a second `github`-provider row (step 4's storage test proves this; FR-5.8 is the point). Multiple self-hosted instances of one provider (two Forgejo servers) are entered as two rows with different `instance_url`s (FR-5.6).
     - **Add flow**: fields = provider dropdown (the four, matching `provider_id` exactly), instance URL (free text, with sane per-provider placeholder text — `https://github.com` works for GitHub Cloud and an enterprise host for GHE, `https://gitlab.com`, `https://forgejo.example.org`; Bitbucket has **no editable instance field at all** — Cloud-only in v1, so picking Bitbucket in the provider dropdown pins the instance to the one fixed cloud value, shown read-only so users see what will be stored), label (free text, required — "work GitHub", "personal GitHub"), username (required for Bitbucket = Atlassian email; optional elsewhere — the Phase 3 helper's username backfill populates it on first use), token (password-echo field, required). **TLS group** (the §11 item-13 resolved policy), collapsed-advanced by default, for the editable-instance providers only: (a) a "Custom CA bundle (PEM)" file picker — chosen path lands in `tls_ca_bundle_path`; (b) a "Skip TLS certificate verification" checkbox that requires an inline warning read-and-acknowledge ("traffic to this instance will not be checked for tampering — only use this on networks you control") before it can be checked — this lands in `tls_insecure`; setting both is contradictory and the dialog rejects it ("pick a CA bundle or skip verification, not both"). **Validate before persisting**: construct the adapter from the not-yet-saved data (including the TLS choice — the `verify=` parameter is applied at `_client` construction, so the validation probe exercises exactly the TLS path the account will live with) and call `authenticate()` via `run_in_background` (never on the UI thread; a hanging keyring or VPN must not freeze the dialog) — success → `storage.forge_accounts.add_account(...)` (step 4's two-step insert+secret-store); failure → the §4.3.A exception maps to an inline message under the offending field (401/403 → token row, `ForgeUnreachableError` → instance URL row, with the self-signed-cert hint appended when the failing instance has no TLS override set) and **nothing is written**: not the row, not the secret. A save that half-completes (keyring dies between row and secret) is step 4's rollback path, already specified there.
     - **Remove flow**: confirm with a dialog that names the label and says what else goes away (the `repo_forge_links` rows cascade — "the N repos linked to this account will be unlinked"). Then `remove_account` per step 4 (row first, secret best-effort after).
     - **Edit**: label and username editable inline; the TLS group from the Add flow reappears here (same fields, same warning) since self-hosted instances get their CA bundles rotated in production life. Token replacement = "Edit label…" is deliberately **not** how you rotate a token; a separate "Replace token…" action re-runs the same validate-then-store flow against the existing row, updating the secret in place (`store_secret` with the existing key) — no new row, no re-linking.
   - **Link flow (FR-5.9's one-time picker)**, reachable from the forge tabs' empty state (step 6) and the Remotes dialog's account column. Given a repo+remote: parse the remote URL to `(host, owner, repo)` (the Phase 3 helper's URL parsing — extract it into a shared `core/remote_urls.py` function *this* phase and have both call sites use it; the helper's stdin parsing and the UI's remote parsing are the same two regexes and must not drift). Match `forge_accounts` rows by provider-host: enumerate `list_accounts()`, filter to accounts whose `instance_url`'s host equals the remote's host (GitHub.com accounts also match GHE? No — `github.com` hosts only match `instance_url=https://github.com` accounts; an Enterprise account on its own URL only matches remotes on that URL; this exact-match rule is what makes two same-provider accounts unambiguous rather than silently first-one-wins).
     - **Zero matches** → empty state: "no account configured for {host}" + button straight to the accounts manager.
     - **One match** → still a confirm ("Link `owner/repo` to {label}?" — one click, default action). Do not skip the confirmation: a wrongly-assumed account is worse than one click; FR-5.9 mandates the *prompt-once* behavior, and "once" includes the first time.
     - **Multiple matches** → the picker dialog listing the matching rows with label/username/instance columns; choosing one is the same outcome path. The picker says at the bottom why it's being asked: "this remote could use more than one configured account — Wrench will remember this choice for this repository and remote."
     - **Persisting the choice** (all three branches): `link_repo_to_account(conn, repo_id, account_id, remote_name, owner_slug, repo_slug)` — upsert semantics from step 4 — **and** `git config credential.useHttpPath true` scoped to this repo (§5 Phase 3 step 3: the git-level credential lookup depends on the path component; the helper's matching order reads `path` first, which only arrives when useHttpPath is on). Both writes belong in the same user action; a repo with the link row but the config unset silently degrades the multi-account guarantee (FR-4.5) to host-only matching.
     - **Re-linking** (change account for a repo) is the same dialog with the current choice pre-selected; the upsert overwrites — no delete-then-insert.
   - All strings wrapped in `tr()` (SRS §4 Localization row); both dialogs pass the keyboard-only walkthrough (SRS §4 Accessibility row — tab order through every field, Enter activates defaults, Escape cancels, accessible names on icon-only buttons); no token ever appears in logs — the diagnostics log (FR-9.2) records account *labels*, never secrets.
8. **Acceptance check** — three gates, in order; a phase is not done until all three pass:
   - **Automated**: `pytest tests/unit/storage/test_forge_accounts.py tests/integration/{github,gitlab,forgejo,bitbucket} -v` all green — the four adapters against `responses`-mocked fixtures in `tests/fixtures/forge_responses/{provider}/` (fixtures captured from real API docs/examples per step 5; **never hit real APIs in tests**), covering each adapter's full step-5 matrix — normalized state mappings, pagination concatenation *and* cap enforcement, mocked `429` asserting `ForgeRateLimitedError` with the parsed `retry_after_seconds`, mocked connect-failure asserting `ForgeUnreachableError` (not a raw `httpx` exception reaching surfaced code), and GitHub's issues-in-list filtering. Plus `pytest tests/unit/forge/test_registry.py`: the four adapters discoverable from a fresh `importlib` pass; constructing each from a full `ForgeAccount` yields a working instance; a forged duplicate `provider_id` raises. Run on a clean clone (the `entry_points` path behaves differently editable-installed vs. packaged — catch that here, not in Phase 6).
   - **End-to-end, per provider** (one real account each, then the multi-account case): add the account through the manager (validate-then-save works), link one repo, PR list loads, open one PR detail (CI status renders), create a throwaway PR and see it appear. Then the **flagship multi-account check**: two accounts on the same provider, two different local repos, each linked to a different account — push/pull on each uses the correct account's credentials (verify each repo's remote API calls land on the right account, not just "no error"), and the git-level `credential.useHttpPath` is set on both repos. Finally the **ambiguity-demonstration check**: both accounts share the same host (e.g. two `github.com` accounts, FR-5.8's whole point); linking a third repo shows the one-time picker, picks one, and a subsequent fetch on that repo uses the chosen account without re-prompting (FR-5.9).
   - **Failure-path QA** (do not skip — these are the dialogs hours-of-debugging turned into): revoke one account's token at the provider, trigger a forge tab load → the 401 banner offers re-entry, replace the token, retry → works; firewall-block one instance's host (`iptables` or a hosts-file blackhole) → `ForgeUnreachableError` banner with actionable text; paste a deliberately-under-scoped token (e.g. GitHub `public_repo` on a private repo) → 403 banner names the missing scope; revoke the Secret Service daemon (`killall gnome-keyring-daemon` on a GNOME session) mid-session → add-account fails cleanly with the no-row-orphan behavior from step 4, existing accounts that were already running keep working until the next secret read.
   - **Documentation gate**: §11 items 13 and 14 are resolved (per-account TLS policy; in-app review actions) — this gate is now a *confirmation* checklist: review the three TLS-policy UI texts (CA-bundle picker label, insecure-mode warning, self-signed failure hint) against what's written in step 7, and confirm the review action flows (approve/request-changes/comment on a test PR per provider, plus the GitLab grayed-button case) behaving as step 5's adapter notes describe — sign-off requires both, since these were the two items that reshaped this phase's scope.

### Phase 5 — LFS & Submodules
**Prerequisites:** Phase 4's acceptance check passed (all four forge adapters' integration tests green).
1. FR-6.1: `core/lfs.py` — on `open_repo`, check for a `.gitattributes` entry containing `filter=lfs` to detect LFS-tracked repos; wrap `git lfs pull` / `git lfs push` / `git lfs track <pattern>` via `run_git` (LFS is a real git subcommand once the `git-lfs` extension is installed, not a separate binary invocation — but the extension itself must be present on the system/in the Flatpak bundle, see §6.2). Before any LFS operation, run `run_git(["lfs", "version"])` and surface a clear, specific error ("Git LFS isn't installed") if that fails, rather than letting a missing-subcommand git error ("git: 'lfs' is not a git command") reach the user unexplained. In `get_status`/`get_diff` (§4's read path), LFS-tracked files that haven't been pulled show as small text pointer files at the git-object level — detect this (pointer files start with `version https://git-lfs.github.com/spec/v1`) and render them in the diff view as "LFS file, not downloaded" rather than showing the pointer file's literal text content as if it were the real file.
2. FR-6.2: `core/submodules.py` — `list_submodules(repo) -> list[Submodule]` and `submodule_status(repo, path) -> SubmoduleStatus` via `pygit2.Repository.submodules` (reads: path, url, current commit, whether initialized); `init_submodules(repo)` (`run_git(["submodule", "update", "--init", "--recursive"])`), `update_submodules(repo)` (`run_git(["submodule", "update", "--recursive"])`), `add_submodule(repo, url, path)` (`run_git(["submodule", "add", url, path])`) — writes go through `run_git`, consistent with the read/write split in §1, since submodule operations have the same "trust git's own tested behavior" rationale as merge/rebase. **Credential limitation**: a submodule is never itself a row in the `repos` table, so it has no `repo_forge_links` entry of its own — if a submodule's remote host matches multiple configured accounts, the credential helper's "exactly one account per host" fallback (§5 Phase 3 step 2) can't disambiguate for it the way it can for a top-level linked repo, and falls through to "not found" like any other ambiguous case. This is a known v1 gap, not a bug to chase down: surface it in documentation rather than building submodule-specific account linking, which the multi-account UI (§5 Phase 4 step 7) doesn't currently support at that granularity.
3. **Acceptance check**: unit tests against a fixture repo containing both a submodule and an LFS-tracked binary file (a small fixture image is enough — the point is exercising the pointer-file-detection path, not testing with a large file); manual QA on a real-world repo with both, confirming submodule status displays correctly uninitialized vs initialized, and an un-pulled LFS file renders as "not downloaded" rather than garbled pointer text.

### Phase 6 — Packaging Hardening & Flathub Submission
**Prerequisites:** Phases 1–5 complete — this phase hardens packaging, it doesn't add features.
- Finalize Flatpak permissions per §6.1's least-privilege list: audit `finish-args` in the manifest against what's actually used in code, remove anything left over from earlier exploratory testing, and confirm each remaining permission traces back to a specific, named feature (`--socket=ssh-auth` → SSH push/pull, `--talk-name=org.freedesktop.secrets` → credential storage, the document-portal folder picker → adding repos and choosing backup destinations). A permission nobody can point to a feature for gets removed, not left "just in case."
- AppImage build: bundle the Python interpreter, all dependencies from §2, and `git` + `git-lfs` binaries (statically linked or vendored) into the AppImage via **Briefcase** (Docker-based, glibc-compatible by construction — see §6.3 for why this replaced the earlier "`python-appimage` or PyInstaller" placeholder). Wire up update checking via `zsync`/AppImageUpdate so the app isn't a dead-end binary users have to manually redownload.
- Write and test the three build scripts from §6.3 (`packaging/flatpak/build-flatpak.sh`, `packaging/appimage/build-appimage.sh`, `packaging/build-all.sh`): run `packaging/build-all.sh all` on a clean checkout (no pre-existing `build-dir/`, `linux/`, or `dist/`) and confirm both a `.flatpak` bundle and a `.AppImage` land in `dist/` from that one command, with nonzero exit and a clear error message if `flatpak-builder`, `briefcase`, or `docker` is missing — a build script that fails silently or half-way is worse than no script.
- AppStream metainfo (`packaging/flatpak/io.github.uzair.Wrench.metainfo.xml`): app name/summary/description, at least 2–3 real screenshots (light and dark Plasma theme, showing the diff view and commit graph — Flathub's review process specifically checks for representative screenshots, not placeholder UI), the AGPL-3.0 `<project_license>` tag, and a `<releases>` block with at least a v1.0.0 entry once tagged. Desktop file (`io.github.uzair.Wrench.desktop`): correct `Exec=`/`Icon=`/`Categories=` (`Development;RevisionControl;`) fields — Flathub's automated checks reject manifests with mismatched app-id/desktop-file-id naming, so confirm the desktop file's basename matches the app-id exactly.
- **Acceptance check**: `flatpak-builder-lint manifest packaging/flatpak/io.github.uzair.Wrench.yaml` passes with zero errors (not just zero *fatal* errors — treat warnings as blocking too at this stage, since Flathub reviewers will raise anything the linter flags); AppImage runs on two distros without the Flatpak runtime present (e.g. a plain Debian and a plain Arch container, confirming the AppImage's bundled dependencies are actually sufficient and nothing was silently relying on a host library that happened to be present in the dev environment).

### Phase 7 — v1 Polish
**Prerequisites:** Phase 6's acceptance check passed (Flatpak passes `flatpak-builder-lint`, AppImage runs on two clean distro containers).
- i18n scaffolding audit: every user-facing string in `ui/` wrapped in `self.tr("...")` — confirmed via a grep-based check (`grep -rn '"' src/wrench/ui | grep -v '\.tr('`) whose output is reviewed manually line-by-line for stragglers, not assumed complete just because the grep ran. Common misses to check for specifically: strings built via f-strings (`self.tr()` needs the *template* wrapped, with `{}` placeholders, not the already-interpolated result), and strings in exception messages that surface directly in dialogs.
- Accessibility pass: keyboard navigation through every dialog and the main window — correct tab order (`setTabOrder` where Qt's default doesn't already match visual layout), sensible Enter/Escape behavior (Enter activates the default button, Escape closes non-destructive dialogs without confirmation but *does* prompt before closing anything mid-destructive-action). Screen reader labels (`setAccessibleName`) on every icon-only button (stage/unstage checkboxes, the sidebar's missing-repo indicator, toolbar icons) — anything conveyed only by an icon needs a text equivalent a screen reader can announce.
- Documentation: `README.md` gets real build/run instructions now that the tooling is finalized (badges for license/CI status, `pip install -e ".[dev]"` + `python -m wrench` quickstart, links to the Flathub/AppImage release once published). `CONTRIBUTING.md` specifically documents how to add a new forge adapter, pointing directly at §4.3 (the `ForgeAdapter` interface) and §4.4 (entry-points registration) — this file *is* the extension-point documentation promised by the plugin architecture, so it should be usable by someone who has read nothing else in this document.
- **Reconcile `dev/planning/` against what actually got built**: eight phases of real implementation will have deviated from this plan in small ways no amount of upfront design catches — a signature that changed shape, an edge case handled differently once it was actually hit, a dependency that got swapped. Before calling v1 done, do one pass updating `srs.md`/`implementation-plan.md` to match reality rather than leaving them as an increasingly-inaccurate historical record. This doesn't need to be exhaustive — the goal is that §4's interfaces and §5's phase descriptions are still trustworthy enough for the next person (including future-you) to read instead of re-deriving from the source.
- **Acceptance check**: a full manual keyboard-only walkthrough of every v1 M-priority flow (SRS §3) with the mouse physically disconnected or ignored — not just tabbing through once, but actually completing each flow (open a repo, stage a hunk, commit, create a branch, open a PR) using only keyboard input, to catch any control that's clickable but not reachable via Tab/Enter/Space.

### Phase 8 — v2 Backlog (not started until v1 ships)
**Prerequisites:** v1 shipped — every box in the Master Sequential Checklist (§12) through Phase 7 checked, and SRS §3's M-priority FRs all implemented. Do not start any Phase 8 item early, even opportunistically.
- Interactive drag-and-drop rebase (FR-2.4) — builds on the commit graph's lane-assignment rendering from §5 Phase 2 step 1, adding drag targets to reorder/squash commits visually; deliberately deferred because it needs the simplified v1 graph algorithm proven stable first.
- Revisit GPG signing UX pending upstream Flatpak portal support — currently blocked on the same `--socket=gpg-agent` limitations noted in the risk register (§9); worth re-checking Flatpak/xdg-desktop-portal release notes periodically rather than assuming the landscape hasn't moved.
- OAuth-based forge login, if there's real demand for it alongside the v1 PAT-only approach — would need its own account-disambiguation UX design (see the multi-account discussion in SRS §7, row 9) since OAuth's browser-session model doesn't map cleanly onto "which of my two accounts" the way PATs do.
- SourceForge adapter (SRS §7.1 — v2–v3 planned) — implement as `forge/adapters/sourceforge.py` with its own entry-point registration, deliberately exercising the same extension mechanism a genuine third-party package would use, so building it in-house also serves as a live correctness test of §4.4's plugin architecture before external contributors rely on it.

---

## 6. Packaging

### 6.1 Flatpak (primary, v1)

- **Runtime**: `org.kde.Platform//6.x` + `org.kde.Sdk//6.x`.
- **Python**: use the `org.freedesktop.Sdk.Extension.python3` SDK extension for a correctly-ABI-matched Python toolchain, then `pip install pygit2` as a prebuilt wheel — **confirmed (Aug 2026 search)**: pygit2's official wheels already bundle libgit2 statically (current release 1.19.3 ships `manylinux_2_28` wheels for x86_64/aarch64), so there is no need to build libgit2 from source as a separate Flatpak module. Only fall back to a from-source libgit2 module if an empirical Phase 0 check shows the runtime's glibc doesn't satisfy `manylinux_2_28`'s floor (unlikely — `org.kde.Platform//6.x` is materially newer). **Caveat that does need action in Phase 0**: Flathub builds run network-isolated, so `pip install` cannot reach PyPI at actual build time — pre-declare pygit2 (and every other pip dependency: PySide6, httpx, watchdog, secretstorage) as explicit `sources:` entries (URL + sha256) in the manifest, generated via the `flatpak-pip-generator` script from `flatpak-builder-tools` rather than hand-maintained.
- **Required permissions** (deliberately minimal — do not request more):
  - `--socket=ssh-auth` — SSH agent access (document known limitations with GPG-as-SSH-agent and hardware tokens).
  - `--talk-name=org.freedesktop.secrets` — Secret Service D-Bus access for credentials.
  - Filesystem access via the **document portal / folder picker only** — never `--filesystem=home`. When a user adds a repo, use `org.freedesktop.portal.FileChooser` folder-select mode, which grants persistent per-folder access that survives restarts. **This same mechanism covers backup/snapshot destinations (FR-8.1/8.2)** — the portal's picker dialog runs outside the sandbox and can browse the entire host filesystem including NAS/USB mounts under `/mnt`, `/media`, etc., so backup destinations need no additional permission beyond this bullet, confirmed decision, not an open item.
  - `--socket=gpg-agent` is **not requested in the default manifest**, confirmed decision. GPG signing is a documented, user-triggered opt-in (SRS §6.1): the README/in-app help tells users who want it to run `flatpak override --user --socket=gpg-agent io.github.uzair.Wrench` themselves — the same pattern other Flathub apps use for edge-case permissions (e.g. Joplin documents a similar `flatpak override --filesystem=host` step for removable-media sync rather than requesting it by default). Only move this into the default manifest if/when an in-app signing UI actually ships.
- **Explicitly avoid**: relying on the host's `git-credential-libsecret` binary — it lives outside the sandbox and won't be found. Implement Secret Service integration directly in-app instead (see `core/git_credential_helper.py`, §5 Phase 3).
- **App ID**: `io.github.uzair.Wrench` — confirmed convention for GitHub-hosted apps without a custom domain (see SRS §7).

**Manifest skeleton** (`packaging/flatpak/io.github.uzair.Wrench.yaml`) — **the dependency-installation step below is the part a first attempt most often gets wrong**, so it's shown in full rather than abbreviated:

```yaml
app-id: io.github.uzair.Wrench
runtime: org.kde.Platform
runtime-version: '6.7'   # confirm current KF6 runtime version at Phase 0 time
sdk: org.kde.Sdk
command: wrench
finish-args:
  - --socket=ssh-auth
  - --talk-name=org.freedesktop.secrets
  - --socket=fallback-x11
  - --socket=wayland
  - --share=ipc
  # fallback-x11/wayland/ipc are the baseline any GUI Flatpak app needs just to put a
  # window on screen — not application-specific, but listed here (not omitted) so this
  # permission list stays a complete, honest account of everything requested, not just
  # the Wrench-specific ones already covered above
  # deliberately absent: --filesystem=home, --share=network is added only
  # once Phase 3/4 need it, not granted speculatively in Phase 0
  # also deliberately absent: --device=dri — plain QWidgets (§2.4) doesn't need GPU
  # compositing the way a QML/OpenGL UI would; add it only if that ever changes
modules:
  # Generated by `flatpak-pip-generator`, NOT hand-written — regenerate this file whenever
  # pyproject.toml's [project.dependencies] changes, don't hand-edit it to add one package.
  #   flatpak-pip-generator --requirements-file=requirements.txt --output pypi-dependencies
  # This is the actual mechanism behind the "pre-declare pip sources" line above: Flathub's
  # build sandbox has no network access, so every wheel must be listed as a `sources:` entry
  # with its exact download URL and sha256 *ahead of time* — a plain `pip install X` inside
  # a build-commands step will simply fail to resolve, since there's no PyPI to reach.
  - pypi-dependencies.json   # generated file, included via Flatpak's module-file inclusion —
                              # NOT inlined here; see the generator's own output format
  - name: wrench
    buildsystem: simple
    build-commands:
      # --no-deps is correct HERE specifically: dependencies were already installed by the
      # pypi-dependencies module above. Using --no-deps on *that* module's install commands
      # (which flatpak-pip-generator writes for you) would be the actual bug to watch for.
      - pip3 install --prefix=/app --no-deps .
    sources:
      - type: dir
        path: ../../
```

**What the generated `pypi-dependencies.json` module actually contains** — one entry per package, each pinned to an exact version and hash (illustrative shape, not literal output):

```json
{
  "name": "pypi-dependencies",
  "buildsystem": "simple",
  "build-commands": [
    "pip3 install --prefix=/app --no-index --find-links=. PySide6 pygit2 httpx watchdog secretstorage platformdirs"
  ],
  "sources": [
    {
      "type": "file",
      "url": "https://files.pythonhosted.org/packages/.../PySide6-6.7.x-....whl",
      "sha256": "..."
    }
  ]
}
```

Run the generator once dependencies stabilize in Phase 0, commit the output, and re-run it (not hand-edit it) any time `pyproject.toml`'s dependency list changes — treat it the same as a lockfile.

### 6.2 AppImage (secondary, post-v1-core-stable)

- No sandboxing — full host access by default (different security model from Flatpak; keep credential/SSH-agent code path-agnostic between the two rather than assuming Flatpak's portal model everywhere).
- **Bundling scope, confirmed decision** (narrower than "bundle everything"):
  - **Bundle deliberately**: `git` core with working HTTPS support (curl/openssl linked in — use `linuxdeploy` to pull in the actual shared libs alongside the binary rather than chasing a fully-static build) and `git-lfs` (low risk — official releases are already near-standalone binaries built for exactly this kind of embedding).
  - **Rely on host, by design**: the `ssh` binary — git itself has no SSH implementation, it always shells out to `ssh`, and every Linux desktop has one; this fits AppImage's full-host-access model and needs no bundling.
  - **Non-issue regardless of packaging format**: credential helpers — Wrench never uses host credential helpers in either packaging format (it implements its own via `core/git_credential_helper.py`, §4.2), so there's no "missing host helper" risk to design around here.
- Bundle Python interpreter + PySide6 + pygit2 (same prebuilt wheel as the Flatpak path, §6.1) via **Briefcase** (BeeWare), not `python-appimage` or a hand-rolled PyInstaller build — see §6.3 for the concrete build script and the reasoning behind this choice over the alternatives.
- **Update mechanism**: integrate `zsync`/AppImageUpdate — AppImage has no built-in updater, and users won't manually re-download releases.

### 6.3 Unified build scripts (`packaging/build-all.sh` and friends)

**Tool choice for AppImage — Briefcase, not `python-appimage` or hand-rolled PyInstaller (confirmed, Aug 2026 research):** the naive approach — running PyInstaller yourself, manually constructing an AppDir, calling `appimagetool` — carries a specific, well-documented failure mode for exactly this stack: building on a dev machine with a newer glibc than your users' distros produces an AppImage that fails at runtime with `GLIBC_2.XX not found`, a problem PySide6 users specifically keep hitting. Briefcase avoids this by design: it builds AppImages **inside Docker**, targeting either a `manylinux` base (default `manylinux2014`) or `ubuntu:18.04` if unspecified, then uses `linuxdeploy` internally to assemble the actual AppImage — the same tool §6.2 already specified for bundling `git`, so this doesn't introduce a second, inconsistent toolchain. Requires Docker on the build machine (local or CI).

**pyproject.toml additions Briefcase needs** (alongside the `[project]` table from Phase 0 step 2, not replacing it):

```toml
[tool.briefcase]
project_name = "Wrench"
bundle = "io.github.uzair"
version = "0.1.0"

[tool.briefcase.app.wrench]
formal_name = "Wrench"
description = "A native Git client for GitHub, GitLab, Forgejo, and Bitbucket"
sources = ["src/wrench"]
requires = ["PySide6", "pygit2", "secretstorage", "platformdirs", "httpx", "watchdog"]

[tool.briefcase.app.wrench.linux]
system_requires = []   # add here if a Phase-1-5 dependency needs an apt package at build time

[tool.briefcase.app.wrench.linux.appimage]
manylinux = "manylinux2014"
```

**`packaging/appimage/build-appimage.sh`** — thin wrapper, not a reimplementation; Briefcase's own three-verb lifecycle (`create`/`build`/`package`) does the real work:

```bash
#!/usr/bin/env bash
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

command -v briefcase >/dev/null || { echo "briefcase not found — pip install -e '.[dev]' first"; exit 1; }
command -v docker >/dev/null || { echo "docker not found — required for Briefcase's glibc-compatible AppImage build"; exit 1; }

# `create` is idempotent-ish but errors if the linux/ dir already exists from a prior run;
# `update` regenerates it from the current pyproject.toml without a full re-scaffold
if [ -d "linux" ]; then
  briefcase update linux appimage
else
  briefcase create linux appimage
fi

briefcase build linux appimage
briefcase package linux appimage

mkdir -p dist
find linux/appimage -maxdepth 1 -name "*.AppImage" -exec cp {} dist/ \;
echo "AppImage written to dist/"
```

**`packaging/flatpak/build-flatpak.sh`** — operationalizes the manual commands already given in §0.3, but produces a distributable single-file bundle (via `flatpak build-bundle`) rather than just a local `--install`, since "generate build output" means an artifact file, not a side-effected local install:

```bash
#!/usr/bin/env bash
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

APP_ID="io.github.uzair.Wrench"
MANIFEST="packaging/flatpak/${APP_ID}.yaml"
VERSION=$(python3 -c "import tomllib; print(tomllib.load(open('pyproject.toml','rb'))['project']['version'])")

command -v flatpak-builder >/dev/null || { echo "flatpak-builder not found"; exit 1; }

flatpak-builder --force-clean --repo=build-dir/repo build-dir/build "$MANIFEST"

mkdir -p dist
flatpak build-bundle build-dir/repo "dist/Wrench-${VERSION}.flatpak" "$APP_ID" \
  --runtime-repo=https://dl.flathub.org/repo/flathub.flatpakrepo

echo "Flatpak bundle written to dist/Wrench-${VERSION}.flatpak"
```

**`packaging/build-all.sh`** — the single entry point; this is what a contributor (or CI) actually runs:

```bash
#!/usr/bin/env bash
# Usage: packaging/build-all.sh [flatpak|appimage|all]   (default: all)
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

TARGET="${1:-all}"
mkdir -p dist

case "$TARGET" in
  flatpak)  bash packaging/flatpak/build-flatpak.sh ;;
  appimage) bash packaging/appimage/build-appimage.sh ;;
  all)
    bash packaging/flatpak/build-flatpak.sh
    bash packaging/appimage/build-appimage.sh
    ;;
  *)
    echo "Usage: $0 [flatpak|appimage|all]" >&2
    exit 1
    ;;
esac

echo ""
echo "Build artifacts:"
ls -la dist/
```

Make all three executable (`chmod +x packaging/build-all.sh packaging/flatpak/build-flatpak.sh packaging/appimage/build-appimage.sh`) as part of committing them — a script that needs `bash script.sh` to work around a missing execute bit is a small but avoidable rough edge for whoever runs it next.

---

## 7. CI/CD Plan

Hosting is confirmed as **GitHub**, so CI is straightforward: **GitHub Actions**, hosted runners, no approval queue, `ubuntu-latest` covers the Flatpak/AppImage build environment without needing a self-hosted runner. This is simpler than the Codeberg dual-CI situation (Woodpecker vs. Forgejo Actions) that applied under the earlier Codeberg-hosting assumption — worth remembering if hosting ever migrates later, since that tradeoff would resurface.

**Pipeline stages** (`.github/workflows/ci.yml`):
1. Lint (`ruff`, `black --check`), plus a platform-abstraction guard: `grep -rn "secretstorage\|SSH_AUTH_SOCK\|XDG_" src/wrench --include="*.py" | grep -v -E "credentials/(backend|secret_service|__init__)\.py|core/(paths|ssh_agent)\.py"` must return no matches — a nonzero exit here means something bypassed §4.7's abstraction layer (see Risk Register, §9), fail the build rather than warn
2. Unit tests (`pytest`) — core git engine against throwaway fixture repos
3. Integration tests — forge adapters against mocked HTTP responses (never hit real APIs in CI)
4. Build Flatpak (validates manifest + permissions on every PR) — use `flatpak/flatpak-github-actions` for a ready-made build action
5. **Flatpak manifest lint** (`flatpak-builder-lint`) and **AppStream validation** (`appstreamcli validate packaging/flatpak/*.metainfo.xml`) — both promised in §8's Testing Strategy but easy to forget as an actual CI *step* rather than something run manually once before release; catches a malformed metainfo file or an unjustified permission on every PR, not just right before a Flathub submission when fixing it is more disruptive
6. Build AppImage via `packaging/appimage/build-appimage.sh` (§6.3, Briefcase-based) — once Phase 6 begins. No self-hosted runner needed for this either: `ubuntu-latest` ships Docker preinstalled, which is all Briefcase's Docker-based build requires.
7. On tag: publish the `.flatpak` and `.AppImage` artifacts as GitHub Release assets. **This is where CI's role actually ends** — it is *not* the same thing as Flathub distribution. The initial Flathub listing is a one-time, manual process (opening a PR against `flathub/flathub` with the manifest, going through human review); only *after* that initial acceptance does Flathub's own build infrastructure watch the repo and rebuild automatically on new tags. Don't design CI around automating a submission step that Flathub's own process doesn't actually let you automate.

**Workflow skeleton** (fill in as each stage becomes buildable in its phase — don't add stage 6 until Phase 6 begins; stages 5 and 7 are shown here in full even though they land later, so there's a concrete target rather than inventing the shape from scratch when that phase arrives):

```yaml
name: CI
on: [push, pull_request]
jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: '3.12' }
      - run: pip install ruff black
      - run: ruff check .
      - run: black --check .
      - name: Platform-abstraction guard (FR-11.1-11.3 — see Risk Register §9)
        run: |
          if grep -rn "secretstorage\|SSH_AUTH_SOCK\|XDG_" src/wrench --include="*.py" \
             | grep -v -E "credentials/(backend|secret_service|__init__)\.py|core/(paths|ssh_agent)\.py"; then
            echo "::error::Found a platform-specific reference outside the §4.7 abstraction layer"
            exit 1
          fi

  unit-tests:
    runs-on: ubuntu-latest
    needs: lint
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: '3.12' }
      - run: pip install -e .[dev]
      - run: pytest tests/unit -v

  integration-tests:
    runs-on: ubuntu-latest
    needs: lint
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: '3.12' }
      - run: pip install -e .[dev]
      - run: pytest tests/integration -v

  flatpak-build:
    runs-on: ubuntu-latest
    needs: [unit-tests, integration-tests]
    container: bilelmoussaoui/flatpak-github-actions:kde-6.7
    steps:
      - uses: actions/checkout@v4
      - uses: flatpak/flatpak-github-actions/flatpak-builder@v6
        with:
          bundle: wrench.flatpak
          manifest-path: packaging/flatpak/io.github.uzair.Wrench.yaml

  flatpak-lint-and-appstream:
    runs-on: ubuntu-latest
    needs: flatpak-build
    steps:
      - uses: actions/checkout@v4
      - run: pip install flatpak-builder-lint
      - run: flatpak-builder-lint manifest packaging/flatpak/io.github.uzair.Wrench.yaml
      - run: sudo apt-get install -y appstream
      - run: appstreamcli validate packaging/flatpak/io.github.uzair.Wrench.metainfo.xml

  appimage-build:   # add starting Phase 6 — not before, per §5 Phase 6
    runs-on: ubuntu-latest
    needs: [unit-tests, integration-tests]
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: '3.12' }
      - run: pip install -e .[dev]   # includes briefcase
      - run: bash packaging/appimage/build-appimage.sh
      - uses: actions/upload-artifact@v4
        with: { name: appimage, path: dist/*.AppImage }

  release:   # add starting Phase 6 — runs only on a version tag, publishes both artifacts
    runs-on: ubuntu-latest
    needs: [flatpak-lint-and-appstream, appimage-build]
    if: startsWith(github.ref, 'refs/tags/v')
    steps:
      - uses: actions/checkout@v4
      - uses: actions/download-artifact@v4
      - uses: softprops/action-gh-release@v2
        with:
          files: |
            wrench.flatpak
            appimage/*.AppImage
```

**Minor efficiency note, not a correctness issue**: none of the jobs above cache pip downloads (`actions/setup-python`'s built-in `cache: pip` option, or `actions/cache` keyed on `pyproject.toml`'s hash) — worth adding once CI run time becomes annoying rather than up front, since it doesn't affect correctness and GitHub Actions is already free for this public repo (§7's cost note).

**Cost note**: GitHub Actions is free for public repositories on standard runners, which matters given the budget constraint driving the GitHub choice — no CI spend expected as long as the repo stays public.

---

## 8. Testing Strategy

- **Unit**: git engine wrapper functions against real throwaway repos created in temp dirs per test (not mocked — git behavior is too subtle to mock reliably). Core fixture (`tests/fixtures/git_repos.py`):
  ```python
  import pygit2, pytest


  @pytest.fixture
  def empty_repo(tmp_path):
      repo = pygit2.init_repository(str(tmp_path))
      return repo


  @pytest.fixture
  def repo_with_commit(empty_repo, tmp_path):
      (tmp_path / "README.md").write_text("hello")
      # ... stage + commit via pygit2 index API, return (repo, first_commit_sha)
  ```
  Every `core/` module gets a matching `tests/unit/core/test_<module>.py`.
- **Integration**: forge adapters tested against recorded/mocked API responses (`responses` library) — one fixture set per provider (GitHub/GitLab/Forgejo/Bitbucket) since their API shapes differ. Pattern per adapter test file:
  ```python
  import responses
  from wrench.forge.adapters.github import GitHubAdapter


  @responses.activate
  def test_list_pull_requests():
      responses.add(
          responses.GET,
          "https://api.github.com/repos/owner/repo/pulls",
          json=load_fixture("github/list_prs.json"),
          status=200,
      )
      adapter = GitHubAdapter()
      prs = adapter.list_pull_requests("owner", "repo")
      assert len(prs) == 2
      assert prs[0].title == "..."
  ```
- **UI**: `pytest-qt` for widget-level tests (e.g. `qtbot.mouseClick` on the commit button asserts `core.engine.commit` was called with the message from the text field — mock `core.engine` at the boundary rather than running real git in UI tests); manual QA pass per release for Flatpak sandbox permission edge cases (SSH agent variants, credential storage across KWallet/GNOME Keyring).
- **Packaging**: automated Flatpak manifest linting (`flatpak-builder-lint`) in CI to catch appid/permission issues before Flathub review, not during it.

### 8.1 Edge Case Reference

Every row below is detailed in full where cited — this table exists so none of them get forgotten mid-implementation, not to duplicate the detail. Treat an unchecked row as an incomplete phase, even if the phase's stated acceptance check otherwise passes.

| Area | Edge case | Where it's actually handled |
|---|---|---|
| Git state | Empty repo (zero commits, "unborn" branch) | §5 Phase 1 step 1 — `repo.head_is_unborn` guard |
| Git state | Detached HEAD | §4.1 `RepoStatus.is_detached`; §5 Phase 1 step 1 |
| Staging | Binary file passed to hunk/line staging | §5 Phase 1 step 6 — `BinaryFileStagingError` |
| Staging | Pure addition / pure deletion hunks | §5 Phase 1 step 6 |
| Staging | Mode-only change (e.g. `chmod +x`) | §5 Phase 1 step 6 — routes to `stage_file` |
| Staging | Missing trailing newline | §5 Phase 1 step 6 — `\ No newline at end of file` marker |
| Filesystem watching | Editor saves via write-temp-then-rename (vim, JetBrains, others) | §5 Phase 1 step 7 — `on_moved`, not just `on_modified` |
| Filesystem watching | inotify watch limit exceeded | §5 Phase 1 step 8, polling fallback |
| Locking | Stale `.git/index.lock` after a crash | §5 Phase 1 step 9 |
| Storage | SQLite file corruption | §5 Phase 1 step 4 — detect, back up, recreate |
| Storage | Concurrent access from background threads | §4.8; §5 Phase 1 step 4 — single `threading.Lock()` |
| Snapshots | Submodule state not reliably captured | §5 Phase 1 step 11 — documented git limitation, not a bug to fix |
| Snapshots | Two triggers firing near-simultaneously | §5 Phase 1 step 11 — atomic check-then-insert under the same lock |
| Snapshots | Restoring must not move the current branch | §4.6 — `read-tree --reset -u`, never `reset --hard` |
| UI responsiveness | Long-running clone/push/pull/merge/rebase freezing the window | §4.8 — `ui.workers.run_in_background`, mandatory for these five |
| UI responsiveness | Cancelling a clone | §4.8, §5 Phase 3 step 3 — temp-dir-then-move, never partial at `dest` |
| Credentials | Two accounts sharing one host (e.g. two `github.com` accounts) | §5 Phase 3 step 2 — host+path disambiguation |
| Credentials | No Secret Service provider reachable at all | §4.5/§4.7 — context-specific `unavailable_help_text()` |
| Credentials | Locked keyring collection | §4.5 — `collection.unlock()` |
| Forge APIs | Rate limiting (`429`) | §5 Phase 4 step 2 — shared `_request()` helper |
| Forge APIs | Offline / connection failure | §5 Phase 4 step 2 — `ForgeUnreachableError` |
| Forge APIs | Expired token (`401`) vs. insufficient scope (`403`) | §5 Phase 4 step 2 — distinct exceptions, distinct guidance |
| Forge APIs | Pagination shape differs per provider (`Link` header vs. `page`/`limit` vs. full-URL-in-body) | §5 Phase 4 step 5, per adapter |
| Forge APIs | GitHub's `/issues` endpoint returns pull requests mixed into the results | §5 Phase 4 step 5 — the GitHub adapter filters out `pull_request`-keyed items |
| Multi-account | Ambiguous host match, no explicit link | §5 Phase 3 step 2 — falls through to "not found," never guesses |
| Submodules | Not a `repos` row, so multi-account disambiguation can't target it specifically | §5 Phase 5 step 2 — documented v1 gap, not solved |
| Packaging | Flatpak build sandbox has no network access — plain `pip install` in a build step fails | §6.1 — `flatpak-pip-generator`, regenerated whenever dependencies change, never hand-edited |
| Packaging | Flathub distribution isn't something CI can automate end-to-end | §7 stage 7 — initial listing is a one-time manual PR + human review; only later updates auto-build |
| Locale | Git output parsing matches English strings ("Already up to date", "rejected") and silently stops matching for users with localized git | §4.2 — `LC_ALL=C` in `run_git`'s env; stderr/stdout decoded with `errors="replace"` |
| Git state | Merge fully resolved but not yet committed — `has_conflicts` is already false while the merge is still open, and a banner keyed on conflicts alone vanishes early | §4.1 `merge_in_progress`/`rebase_in_progress`; §5 Phase 2 step 3 |
| Merge/rebase | "Ours"/"theirs" stage entries invert during a rebase — resolving with merge-mode labels taught to the user resolves conflicts backwards | §5 Phase 2 step 4 — `mode`-aware pane labels in the merge dialog |
| Merge tool | User stages a file that still contains `<<<<<<<`/`>>>>>>>` markers | §5 Phase 2 step 4 — rescan for markers, refuse to stage |
| Snapshots | Restoring a snapshot (or reflog `reset --hard`) while a merge/rebase is open scrambles index/conflict state | §5 Phase 2 step 6 — `RepoBusyError` + disabled Restore |
| History | `LogFilter.path` silently ignored (Phase 1 shipped it as a no-op) | §5 Phase 2 step 2c — implemented plus regression test |
| History | Lane indices drift when commits arrive in pagination batches | §5 Phase 2 step 1c — full-window recompute per batch, never incremental state |
| History | HEAD-only log walk can never draw a multi-branch graph (FR-2.2) | §5 Phase 2 step 1a — `all_refs=True` walk |

---

## 9. Risk Register

| Risk | Impact | Mitigation |
|---|---|---|
| SSH agent access breaks under Flatpak for some auth setups (GPG-as-agent, hardware keys) | High — core workflow blocker for affected users | Document limitations explicitly in-app rather than silently failing; prioritize the common case (plain ssh-agent) for v1 |
| `pygit2`/libgit2 merge or rebase edge cases diverge from real git behavior | Medium — data-integrity risk | Write path uses git CLI subprocess, not libgit2, specifically to avoid this |
| Flathub review pushback on filesystem permissions | Medium — delays release | Use document portal from day one, never request `--filesystem=home` |
| Credential helper mismatch (host binary not found in sandbox) | High — breaks auth silently | Implement Secret Service integration natively (`core/git_credential_helper.py`), don't shell out to host credential helpers |
| Forgejo/Bitbucket API divergence from GitHub/GitLab shapes causes leaky abstractions | Medium — technical debt | Build the capability-based provider interface (FR-5.1) and entry-points registration (FR-5.7) before any single adapter; four confirmed backends validate the interface's generality before v1 ships |
| GitHub Actions minute limits if repo ever goes private | Low — CI reliability | Public repo keeps Actions free; revisit only if visibility changes |
| inotify watch limits exceeded on large repos/monorepos | Low — degraded UX, not data loss | Detect limit, fall back to debounced polling with a visible warning |
| Hunk/line-level staging via `git apply --cached` (§5 Phase 1, item 6) is a documented exception to the read/write split and could drift out of sync with the rest of write_ops.py conventions | Low — maintainability | Called out explicitly in code comments and in this doc so future contributors don't "fix" it into a pygit2-only path that then breaks on complex hunks |
| Multi-account credential resolution silently picks the wrong account, or none, when `path` isn't sent by git (`credential.useHttpPath` misconfigured or unset on an older-linked repo) | Medium — auth failures or, worse, pushing as the wrong identity | Ambiguous cases explicitly fall through to "not found" rather than guessing (§5 Phase 3); never silently pick an account when more than one could match |
| Rolling snapshots via `git stash create` interact oddly with an in-progress conflicted merge/rebase state (the command can behave unexpectedly mid-conflict) | Low-Medium — could produce a misleading or failed snapshot at exactly the moment it's most wanted | `pre_risky_op` snapshots are taken *before* starting merge/rebase, not during; document that a snapshot isn't attempted while `RepoStatus.has_conflicts` is true, and surface that clearly rather than failing silently |
| Untracked-file archive storage grows unexpectedly on a repo with many large, frequently-changing untracked files (e.g. build output directories not yet gitignored) | Low — disk usage, not data loss | Per-file and total size caps (`snapshot_settings`) bound this by default; recommend `.gitignore` hygiene in onboarding docs rather than trying to solve it purely in code |
| AppImage build now depends on Docker (Briefcase's mechanism for glibc-compatible builds, §6.3) — a contributor without Docker installed can't produce an AppImage locally | Low — inconvenience, not a blocker | Flatpak-only local development is still fully supported (§0.2); `build-appimage.sh` fails with a clear, actionable message rather than a cryptic error when Docker is absent; CI always has Docker available regardless |
| A future contributor bypasses `credentials/backend.py`/`core/paths.py`/`core/ssh_agent.py` and calls `secretstorage`, an XDG env var, or `SSH_AUTH_SOCK` directly somewhere new — silently reintroducing the coupling §4.7/FR-11.1–11.3 exist to prevent | Medium — invisible today, expensive the day a second platform is attempted | Add a lint rule (`ruff` custom rule or a simple `grep`-based CI check) that fails the build if `secretstorage`, `SSH_AUTH_SOCK`, or `XDG_` appear outside the three files that are allowed to reference them |
| A long-running operation (clone/push/pull/merge/rebase) gets called synchronously from a UI slot instead of through `ui.workers.run_in_background` (§4.8) — the window freezes, but only on a slow connection or large repo, so it can pass casual testing on a fast local network and ship broken | Medium — invisible in a quick demo, a real bug for anyone with a non-trivial repo | Every UI call site for these five operations should be code-reviewed against the §8.1 Edge Case Reference row for this specifically; consider a CI check that greps `ui/` for direct `core.engine.(clone_repo|push|pull|fetch|merge|rebase)` calls not wrapped in `run_in_background` |
| A QThread created by `run_in_background` (§4.8) gets garbage-collected while still running, because the caller didn't keep a reference to it | Medium — PySide6 crashes silently/inconsistently in this case rather than raising a clear Python exception, making it a hard bug to diagnose after the fact | Document this explicitly at the one place threads are created (§4.8's docstring already does); store the returned `QThread` on the widget instance (`self._active_thread`), never as a bare local variable |

---

## 10. Definition of Done for v1

- [ ] All **M**-priority FRs from SRS §3 implemented and tested
- [ ] Flatpak builds, passes `flatpak-builder-lint`, installable from Flathub
- [ ] AppImage builds and runs on at least two distros without the Flatpak runtime present
- [ ] No credentials ever touch disk in plaintext
- [ ] SSH agent auth works for the plain-agent case; limitations documented for GPG-agent/hardware-key cases
- [ ] All four forge adapters (GitHub, GitLab, Forgejo/Gitea, Bitbucket Cloud) support PR/MR create+review+CI-status
- [ ] At least two accounts on the same provider can be configured simultaneously, each correctly resolved per repo via the credential helper's account disambiguation
- [ ] LFS and submodules functional
- [ ] Reflog-based recovery accessible from UI (no data-loss dead-ends)
- [ ] Rolling snapshots fire on all four configured triggers, respect the configured retention policy (manual snapshots surviving auto-pruning bursts), and restore without moving the current branch's HEAD
- [ ] No KDE-Frameworks-specific API used anywhere in `src/wrench`; `secretstorage`/`SSH_AUTH_SOCK`/`XDG_` references exist only inside the three §4.7 files (CI-enforced, §7)

---

## 11. Open Decisions Log

Cross-references SRS §7.
1. ~~Confirm source host~~ — ✅ Resolved: GitHub.
2. ~~Confirm GitHub username/namespace for App ID~~ — ✅ Resolved: `io.github.uzair.Wrench`. No remaining blockers before Phase 0.
3. ~~Confirm Qt/KF minimum version~~ — ✅ Resolved, then revised: Qt 6.6+ (PySide6), **no KDE Frameworks (KF6) dependency** — see SRS §3.12/Assumptions Log #3, #15.
4. ~~Confirm v1 forge backend set~~ — ✅ Resolved: GitHub, GitLab, Forgejo/Gitea, Bitbucket Cloud, via capability-based + entry-points adapter architecture. Extension roadmap (SourceForge v2–v3; Radicle optional/community) tracked in SRS §7.1, non-blocking for v1.
5. ~~Confirm Bitbucket Cloud auth mechanism~~ — ✅ Resolved (Aug 2026): API tokens via HTTP Basic Auth (email + token), not App Passwords (deprecated 2025, disabled June 9 2026). See §5 Phase 4, item 5.
6. ~~Confirm pygit2 packaging route for Flatpak~~ — ✅ Resolved (Aug 2026): prebuilt wheel via `org.freedesktop.Sdk.Extension.python3`, no from-source libgit2 module needed; sources must be pre-declared for network-isolated Flathub builds (§6.1, Phase 0 item 7).
7. ~~Confirm AppImage git-bundling scope~~ — ✅ Resolved: bundle `git` + `git-lfs` deliberately; rely on host `ssh`; credential helpers are a non-issue in both packaging formats since Wrench never uses host helpers (§6.2).
8. ~~Confirm backup destination (FR-8.1/8.2) permission needs~~ — ✅ Resolved: no additional Flatpak permission required — reuses the same document-portal folder picker already used for adding repos (§6.1).
9. ~~Confirm multi-account auth method~~ — ✅ Resolved: PAT-only, no OAuth in v1 (SRS §7, row 9).
10. ~~Confirm snapshot storage/trigger/retention design~~ — ✅ Resolved: hybrid storage (`git stash create` + capped untracked archive), all four triggers enabled by default and independently configurable, count+age retention with manual-snapshot protection (SRS §7, rows 11–14; full algorithm in §4.6). FR-1.11 reclassified from v2 to v1 as a consequence.
11. **Open**: default values for `untracked_per_file_cap_mb` (50) and `untracked_total_cap_mb` (500) in `snapshot_settings` are reasonable starting points, not empirically validated — revisit after real-world use on a repo with substantial untracked build artifacts.
12. **Open, tracked in SRS §6.1/§7**: SSH agent compatibility across GPG-as-agent and hardware-key setups — narrower risk than originally scoped (protocol forwarding is agent-agnostic; real risk is env-var propagation at launch and untested hardware-key paths), but not empirically validated yet. Beta-cycle validation task, not a Phase 3 blocker.
13. ~~Self-hosted Forgejo/Gitea TLS handling (self-signed certs) and minimum supported API version~~ — ✅ **Resolved**: per-account TLS policy stored on the account row — `tls_ca_bundle_path` (verify against a user-supplied PEM) and `tls_insecure` (explicit, warning-gated opt-in to skip verification); default remains system trust store. The accounts dialog's TLS group (§5 Phase 4 step 7) exposes both; the adapters never special-case TLS — the policy reaches the `httpx.Client` at construction time via `verify=` (§5 Phase 4 step 2). Minimum supported server version: Gitea/Forgejo ≥ 1.20 (the endpoints §5 Phase 4 step 5 uses are stable that far back); older versions are untested, not blocked — no version sniffing.
14. ~~SRS FR-5.2–5.5 "PR create/view/**review**" vs §4.3's interface with no review methods~~ — ✅ **Resolved**: in-app review actions ARE v1 scope. §4.3 gained `submit_review(action: 'approve'|'request_changes'|'comment', body)` plus a `supported_review_actions` property for provider gaps (GitLab lacks a first-class request-changes action — the UI grays that button rather than erroring). Reading review threads stays out of app scope for v1 (the "Open in browser" action covers reading them); the method is the action surface only.

---

## 12. Master Sequential Checklist

Flattened, in strict execution order, across every phase — the literal path through the project. Check off top to bottom, never out of order. Each line is short-form on purpose, so it tracks real progress rather than duplicating the detail above; follow the cross-referenced phase step for the full algorithm/rationale before implementing anything non-trivial.

**Phase 0 — Project Setup** *(prerequisites: none)*
- [ ] 0.1 `git init`; add `LICENSE` (AGPL-3.0), `README.md` stub, `dev/planning/` (this SRS + plan, tracked) + `dev/scratch/` (gitignored) + `dev/README.md`, and `.gitignore` per §5 Phase 0 step 1
- [ ] 0.2 `pyproject.toml`: metadata, deps, dev-deps, entry-points section (§4.4)
- [ ] 0.3 `ruff`/`black` config
- [ ] 0.4 `.pre-commit-config.yaml`
- [ ] 0.5 Full `src/wrench/` skeleton from §3 (including `credentials/backend.py`, `core/paths.py`, `core/ssh_agent.py` — the platform-abstraction seams, §4.7), stub modules with FR-referencing docstrings
- [ ] 0.6 Minimal Flatpak manifest (empty window)
- [ ] 0.7 Pinned pip sources via `flatpak-pip-generator`, added to manifest
- [ ] 0.8 **CHECK**: `flatpak-builder` succeeds network-isolated; app launches an empty window

**Phase 1 — Core Local Git Engine + MVP UI** *(prerequisites: 0.8 checked)*
- [ ] 1.1 `core/read_ops.py`: status/diff/log/blame + unit tests
- [ ] 1.2 `core/write_ops.py`: `run_git()` + commit/branch/stash ops
- [ ] 1.3 `core/identity.py`: identity check/prompt
- [ ] 1.4 `storage/schema.sql` + `db.py` + `repo_registry.py`
- [ ] 1.5 `core/engine.py`: façade wiring
- [ ] 1.6 Hunk/line staging — use the exact patch-construction algorithm in §5 Phase 1 step 6, not an improvised one
- [ ] 1.7 `watcher/inotify_watcher.py`: single-shot-`QTimer` debounce per §5 Phase 1 step 7
- [ ] 1.8 `watcher/polling_fallback.py`: inotify-limit fallback
- [ ] 1.9 `core/lock_recovery.py`: mtime-only stale-lock algorithm per §5 Phase 1 step 9 — no PID checks
- [ ] 1.10 `core/reflog.py`: reflog read + restore-to-ref
- [ ] 1.11 `core/snapshots.py` + `storage/snapshots.py`: capture/prune per §4.6; wire `commit` and `manual` triggers now, plus `delete_branch` as a `pre_risky_op` point
- [ ] 1.12 `ui/main_window.py` + `ui/sidebar/` + `ui/diff_view/` (default tab) + `ui/workers.py` (§4.8 — needed starting Phase 3, scaffold now)
- [ ] 1.13 **CHECK**: `pytest tests/unit/core tests/unit/storage -v` green; manual QA per §5 Phase 1 acceptance check, including a snapshot appearing after commit and after manual "snapshot now"

**Phase 1.5 — UI Shell Overhaul** *(prerequisites: 1.13 checked)*
- [x] 1.5.1 `ui/main_window.py` rewrite: `QMenuBar` + menu structure (File/Edit/View/Help), window geometry persistence, quit guards (unsaved commit msg, background ops)
- [x] 1.5.2 `ui/tabs/tab_bar.py` [NEW]: custom tab widget with vertical/horizontal toggle, hybrid model (singleton category tabs + dynamic detail tabs), per-repo dedup, pinned Changes tab, closable others, `+` button, `Ctrl+1/2/3` keyboard shortcuts, tab persistence
- [x] 1.5.3 `ui/tabs/changes_tab.py` [NEW] + `ui/widgets/branch_switcher.py` [NEW] — repo selector (flush `QComboBox`, zero-repos state, missing-repo dialog, auto-select MRU) + branch indicator/switcher (`🌿 main ▾`, branch popup list, stash & switch prompt, create/rename/delete)
- [x] 1.5.4 Changes tab — unified file list: single `QListWidget` with checkboxes, tri-state select-all, right-click context menu (Stage/Unstage/Discard/Open/Copy Path), edge cases (refresh preserves state, long path truncation, count badge)
- [x] 1.5.5 Changes tab — commit section: account icon, commit message + description fields, amend toggle (pre-fills from last commit, hidden on unborn), commit button ("Commit to {branch}"), edge cases (detached HEAD, unborn, merge conflict banner, per-repo draft save)
- [x] 1.5.6 Changes tab — diff view: re-parent existing `DiffView` into new layout, binary file detection ("Binary file changed"), empty states (no changes + quote, no selection)
- [x] 1.5.7 Staging logic bridge: commit flow = unstage_all → stage checked → commit → refresh
- [x] 1.5.8 `ui/tabs/history_tab.py` [NEW] — skeleton: search/filter bar (visible but non-functional), graph placeholder widget (swappable in Phase 2), detail panel slot (hidden), empty states, `repo_changed` signal handling
- [x] 1.5.9 Sidebar deprecation: remove `ui/sidebar/`, remove `QSplitter`, update imports/tests
- [x] 1.5.10 Tab-system wiring in `main_window.py`: thin shell, Changes tab pinned at index 0, History tab at index 1, `repo_changed` signal propagation
- [x] 1.5.11 Theme/style: inherit default Qt palette, scoped borderless stylesheet for repo dropdown only
- [x] 1.5.12 Test updates: remove sidebar tests, add `TabBar`/`ChangesTab`/`HistoryTab` widget tests
- [x] 1.5.13 **CHECK**: `pytest tests/ -v` all green; manual QA — tab toggle, repo dropdown, tri-state checkboxes, amend, History placeholder, repo switch refreshes all tabs, geometry/tab persistence, quit guard dialog

**Phase 2 — Commit Graph & Merge Tooling** *(prerequisites: 1.5.13 checked)*
- [x] 2.1 `ui/commit_graph/`: lane-assignment rules R1–R5 + ten-color `GRAPH_COLORS` per §5 Phase 2 step 1 (not a full DAG-layout attempt); `get_log(all_refs=True)` walk; `get_ref_labels`; accessible `QTreeView` fallback; placeholder swap + detail panel wiring in `history_tab`
- [x] 2.2 Log search/filter: client-side `matches_filter` highlight/dim predicate per §5 Phase 2 step 2 — **and** the `filter.path` implementation in `read_ops.get_log` (Phase 1 shipped it as a silent no-op)
- [x] 2.3 `core.engine.merge()`: FF/3-way/conflict detection + `DirtyTreeError` precheck + `merge_in_progress` state + `merge_abort()` (§5 Phase 2 step 3; relies on §4.2's `LC_ALL=C`)
- [x] 2.4 `ui/merge_tool/`: 3-pane conflict resolution with `mode="merge"|"rebase"` pane labeling, marker rescan before staging, completion handed back to the Changes tab via `.git/MERGE_MSG` prefill
- [x] 2.5 `core.engine.rebase()`: non-interactive; `rebase_continue()`/`rebase_abort()` façade; conflict loop reuses the merge tool in rebase mode
- [x] 2.6 Complete snapshot trigger wiring: `pre_risky_op` at engine level in `merge()`/`rebase()`; per-repo `timer` `QTimer` in `main_window` recreated on `repo_changed`; `RepoBusyError` guard on restore; panel per ui-planning §6.4 in `ui/snapshots_panel/__init__.py`
- [x] 2.7 **CHECK**: `pytest -v` green including merge/rebase/snapshot/graph-layout/path-filter/`LC_ALL` cases per §5 Phase 2 step 7 (restoring a snapshot doesn't move `repo.head.target`; restore mid-merge raises `RepoBusyError`); manual QA per the same step's list


**Phase 3 — Remote Operations** *(prerequisites: 2.7 checked)*
- [x] 3.0 Step 0 reconciliation: verify scaffolded seams exist (`git-credential-wrench` script entry, credential factory, workers progress signal); note engine stubs being *replaced*, not added beside
- [x] 3.1 `credentials/secret_service.py` filled in per §4.5 (backend ABC + factory already scaffolded — verify only); tests (a)–(j) green incl. DB-locked retry and context-specific `unavailable_help_text`
- [x] 3.2 `core/git_credential_helper.py`: exact `get`/`store`/`erase` protocol per §5 Phase 3 step 2 — split-once stdin parse, http(s)-only, host→link→fallback disambiguation ("not found," never guess), read-only WAL DB access with locked-retry, empty-stdout-exit-0 failure rule, per-`open_repo` + clone + `add_remote` credential config write (`credential.helper=wrench`, `credential.useHttpPath=true`); tests (a)–(l) green
- [x] 3.3 `core/write_ops.py` + `core/engine.py`: `run_git_streaming` sibling (dual-pipe drain, `\r`-fragment split, terminate→kill cancel, timeout→`CLITimeoutError`); `_parse_progress`; classification table (`PushRejectedError`/`MergeRequiredError`/`AuthFailedError`/`AuthRequiredError`); `push` (`--force-with-lease` only for force), `pull` (`--ff-only`), `fetch` (`--prune` + `remote_last_fetch.*` settings), `clone_repo` rewrite (temp-dir-then-move, `CloneAbortedError`, config write into fresh clone); workers.py percent adapter; tests 3f(1)–(7) green; all four ops only ever called via `run_in_background` from UI
- [x] 3.4 Flatpak manifest has `--socket=ssh-auth`; `_git_env()` passes `SSH_AUTH_SOCK` via `core.ssh_agent.get_ssh_auth_socket()` only when set, unmodified; tests green
- [x] 3.5 `list_remotes` (no network in the list call) / `add_remote` (validate → dup-check → config → add → background probe) / `remove_remote` / `set_remote_url`; `ui/dialogs/remotes_dialog.py` + Repository menu (Fetch/Pull/Push/Remotes) wired through `run_in_background` + Phase 2 busy dialog, error routing per §5 Phase 3 step 5
- [x] 3.6 **CHECK**: full §5 Phase 3 step 6 list executed — pytest green; real HTTPS push/pull/fetch with helper-supplied credentials verified via `GIT_TRACE=1`; strace shows zero plaintext credential files; two-account same-host → linked-account-wins, unlinked-ambiguous → fails closed; rejection dialogs (push-rejected / merge-required / auth) shown correctly; mid-clone cancel leaves no directory; SSH plain-agent works; Remotes dialog round-trips

**Phase 4 — Forge Integration Layer** *(prerequisites: 3.6 checked)*
- [ ] 4.1 `forge/models.py`: dataclasses + normalized state strings; `forge/exceptions.py`: the §4.3.A six-class hierarchy (lives in `forge/`, not `core/` — no new core→forge imports)
- [ ] 4.2 `forge/capability.py`: `ForgeCapability` + `ForgeAdapter` ABC — account bound in `__init__`, argument-less `authenticate()`, shared `_request()` (timeouts, 401/403/429→exception map) + `_paged_get` (10-page cap)
- [ ] 4.3 `forge/registry.py`: entry-points discovery (already in `pyproject.toml` — verify, don't re-add), cached discovery, `cls(account)` construction, loud duplicate-provider failure
- [ ] 4.4 `storage/forge_accounts.py`: full CRUD — two-step `add_account` (placeholder key → final key → `store_secret`, row-rollback on secret-store failure), `get_account_full`, `link_repo_to_account` upsert, `get_link_for_remote`, `get_remote_slug`, `remove_account`
- [ ] 4.5 `forge/adapters/github.py` — build first; `/issues`-returns-PRs filter
- [ ] 4.6 `forge/adapters/gitlab.py`
- [ ] 4.7 `forge/adapters/forgejo.py` — build third, deliberately; TLS is per-account policy via `verify=` (§3.1 columns), not adapter code; min supported server Gitea/Forgejo ≥ 1.20
- [ ] 4.8 `forge/adapters/bitbucket.py` — API-token Basic Auth (email+token); do **not** implement App Passwords (dead since June 2026)
- [ ] 4.9 Forge UI: the four §3 tab files + shared `ui/forge_panel/` widgets — all adapter HTTP via `run_in_background`, no N+1 CI in lists, per-class error banners, capability gating (no call-and-catch), review actions gated on `ForgeCapability.REVIEWS` + `supported_review_actions`, `tr()` + full keyboard operation
- [ ] 4.10 Accounts manager + link flow (FR-5.6/5.8/5.9): validate-before-save via background `authenticate()`; advanced TLS group (custom CA bundle / warning-gated insecure mode) on editable-instance providers; one-time picker on ambiguous host match, always confirmed, never re-prompted; linking upserts `repo_forge_links` **and** sets `credential.useHttpPath`
- [ ] 4.11 **CHECK**: unit + adapter-integration tests green on a **clean clone** (entry-points behave differently editable-installed); real-account QA per provider, plus the two-accounts-same-host case with the picker, plus failure-path QA (401 re-entry, 429 banner, unreachable banner, keyring-down add); documentation-gate checklist — TLS-policy texts reviewed, review actions QA'd on a test PR per provider (§11 items 13, 14 resolved)

**Phase 5 — LFS & Submodules** *(prerequisites: 4.11 checked)*
- [ ] 5.1 `core/lfs.py`
- [ ] 5.2 `core/submodules.py`
- [ ] 5.3 **CHECK**: fixture-repo unit tests (submodule + LFS file) + manual QA on a real repo with both

**Phase 6 — Packaging Hardening & Flathub Submission** *(prerequisites: 5.3 checked)*
- [ ] 6.1 Finalize Flatpak permissions (least privilege, §6.1)
- [ ] 6.2 AppImage build via Briefcase (§6.2/§6.3) — not `python-appimage`/PyInstaller
- [ ] 6.3 AppStream metainfo, screenshots, desktop file
- [ ] 6.4 Write + test `packaging/build-all.sh` and its two sub-scripts (§6.3): clean checkout, run `build-all.sh all`, confirm both artifacts land in `dist/`
- [ ] 6.5 **CHECK**: `flatpak-builder-lint` zero errors; AppImage runs on two clean distro containers (e.g. plain Debian, plain Arch); `build-all.sh` exits nonzero with a clear message if a required tool is missing

**Phase 7 — v1 Polish** *(prerequisites: 6.5 checked)*
- [ ] 7.1 i18n audit — grep-verified, not assumed complete
- [ ] 7.2 Accessibility pass (keyboard nav, screen reader labels)
- [ ] 7.3 `README.md` + `CONTRIBUTING.md` + reconcile `dev/planning/` docs against actual v1 implementation
- [ ] 7.4 **CHECK**: full keyboard-only manual walkthrough of every M-priority flow (SRS §3), mouse disabled

**v1 ships here.** Confirm every box above is checked, and every M-priority FR in SRS §3 is implemented, before touching anything below.

**Phase 8 — v2 Backlog** *(prerequisites: v1 shipped — do not start early, even opportunistically)*
- [ ] 8.1 Interactive drag-and-drop rebase (FR-2.4)
- [ ] 8.2 GPG signing UX (pending upstream Flatpak portal support)
- [ ] 8.3 OAuth-based forge login, if there's real demand beyond v1's PAT-only approach
- [ ] 8.4 SourceForge adapter (also serves as a live test of the third-party extension mechanism)
