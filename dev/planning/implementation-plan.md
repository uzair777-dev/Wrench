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
│   │   └── snapshots_panel.py      # FR-10.6: browse/restore rolling snapshots (ui-planning §6.4)
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
class Remote:
    name: str
    url: str

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
def clone_repo(url: str, dest: Path, *, progress_cb=None) -> None: ...
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

def push(repo: "RepoHandle", remote: str, branch: str, *, force: bool = False) -> None: ...
def pull(repo: "RepoHandle", remote: str, branch: str) -> None: ...
def fetch(repo: "RepoHandle", remote: str) -> None: ...

def merge(repo: "RepoHandle", source_branch: str) -> "MergeResult": ...
def rebase(repo: "RepoHandle", onto: str) -> "RebaseResult": ...
```

`RepoHandle` wraps a `pygit2.Repository` for reads and the repo's filesystem `Path` for subprocess calls. It is created once per opened repo and cached by `ui/main_window.py`; never re-open a repo per operation.

**Where implementation lives vs. what UI calls**: `core/read_ops.py` and `core/write_ops.py` (§5 Phase 1, steps 1–2) contain the actual `pygit2`/subprocess logic; `core/engine.py` re-exports every one of these as a thin façade function (e.g. `engine.get_log = read_ops.get_log`, or a one-line wrapper if error-translation is needed per step 5 below). UI code calls `core.engine.get_log(...)`, `core.engine.get_diff(...)`, etc. — **never** `core.read_ops.get_log(...)` directly, per §1's one-directional dependency rule. This applies uniformly to every function above, including the read-path ones.

### 4.2 `core/write_ops.py` (subprocess wrapper conventions)

- All `git` invocations go through one helper: `run_git(repo_path: Path, args: list[str], *, timeout: int = 30) -> subprocess.CompletedProcess`. This is the single place that sets `cwd`, environment (notably `GIT_TERMINAL_PROMPT=0` so git never blocks waiting for interactive credential input — credential negotiation happens via the credential helper below instead), and timeout.
- Credential negotiation: configure a custom `credential.helper` pointing at a small internal script (`core/git_credential_helper.py`, invoked as `git credential-wrench`) that reads/writes via `credentials/secret_service.py` instead of any host credential helper (per SRS constraint — never shell out to `git-credential-libsecret` on the host).
- **Multi-account (FR-4.5)**: also set `credential.useHttpPath = true` in the same repo-local config write — by default git does *not* send the URL path to credential helpers, only protocol+host, which is fine for a single account per host but ambiguous the moment a second account on the same host exists. With `useHttpPath` on, the helper receives enough to disambiguate by repo, not just host (exact matching logic in §5 Phase 3).
- Every `write_ops.py` function must raise a typed exception (`core/exceptions.py`) on non-zero exit, with the raw stderr attached, so the UI layer can show a real error instead of a generic failure.

### 4.3 `forge/capability.py` (the abstraction FR-5.1/5.7 depend on)

`forge/models.py` first — every adapter maps its provider's own response shape onto these, so nothing provider-specific ever reaches `ui/forge_panel/`:

```python
from dataclasses import dataclass

@dataclass
class PullRequest:
    id: str                # provider's native ID as a string — GitHub's are ints, GitLab/Forgejo
                            # vary, normalize to str here so callers never branch on adapter identity
    title: str
    description: str
    source_branch: str
    target_branch: str
    state: str              # normalized: 'open' | 'merged' | 'closed' — each adapter maps its own
                             # vocabulary onto this set (e.g. GitLab's 'opened' → 'open') internally
    url: str
    author: str
    created_at: str          # ISO 8601

@dataclass
class Issue:
    id: str
    title: str
    description: str
    state: str                # normalized: 'open' | 'closed'
    url: str
    author: str
    created_at: str

@dataclass
class CIStatus:
    state: str                 # normalized: 'success' | 'failure' | 'pending' | 'unknown' — the
                                # 'unknown' value matters: it's the correct result when a ref has no
                                # CI configured at all, which must render differently in the UI than
                                # 'pending' (CI configured but still running)
    url: str | None             # link to the CI provider's own detail page, when available
    description: str | None      # short human-readable status text, e.g. "3/3 checks passed"

@dataclass
class ForgeAccount:
    id: int
    provider: str                 # 'github' | 'gitlab' | 'forgejo' | 'bitbucket'
    instance_url: str
    label: str
    username: str | None
    secret_service_key: str        # unlike ForgeAccountRecord (§3.1) — this full ForgeAccount type,
                                    # with the key included, is only ever passed to adapter.authenticate()
                                    # and secret_service.py, never to UI code
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

class ForgeAdapter(ABC):
    """One instance per configured forge_account row."""

    provider_id: str  # e.g. 'github' — must match storage.forge_accounts.provider

    @property
    @abstractmethod
    def capabilities(self) -> ForgeCapability: ...

    @abstractmethod
    def authenticate(self, account: ForgeAccount) -> None:
        """Validate stored credentials against the API; raise ForgeAuthError on failure."""

    @abstractmethod
    def list_pull_requests(self, owner: str, repo: str) -> list[PullRequest]: ...

    @abstractmethod
    def create_pull_request(self, owner: str, repo: str, *, title: str,
                             source_branch: str, target_branch: str,
                             description: str = "") -> PullRequest: ...

    @abstractmethod
    def get_ci_status(self, owner: str, repo: str, ref: str) -> CIStatus: ...

    # Optional capabilities — default to NotImplementedError, only override if
    # `ForgeCapability.ISSUES in self.capabilities`
    def list_issues(self, owner: str, repo: str) -> list[Issue]:
        raise NotImplementedError(f"{self.provider_id} does not support issues")
```

Every adapter (`forge/adapters/*.py`) subclasses `ForgeAdapter`. UI code must check `adapter.capabilities` before showing a feature (e.g. don't render an "Issues" tab if `ForgeCapability.ISSUES` isn't set) rather than calling the method and catching `NotImplementedError`.

### 4.4 `forge/registry.py` (entry-points discovery, FR-5.7)

```python
from importlib.metadata import entry_points
from .capability import ForgeAdapter

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
    return cls()
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
                collection.unlock()   # typically triggers the OS's own keyring-unlock
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
            return item.get_secret().decode("utf-8")   # first match; keys are unique by construction
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
    trigger_type: str        # 'commit' | 'timer' | 'pre_risky_op' | 'manual'
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
    untracked_capture_mode: str   # 'none' | 'capped' | 'unlimited'
    untracked_per_file_cap_mb: int
    untracked_total_cap_mb: int

def take_snapshot(repo: "RepoHandle", trigger_type: str, *, label: str | None = None) -> Snapshot | None: ...
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
    return "bare"   # plain `pip install` / running from source, not packaged at all

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

def state_dir() -> "Path":       # used by FR-9.2's log file
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
    finished = Signal(object)      # emits the function's return value on success
    failed = Signal(Exception)     # emits the exception on failure — connect this to
                                     # the same error-dialog code core.engine's typed
                                     # exceptions (§5 Phase 1 step 5) already feed
    progress = Signal(int)         # 0-100; only emitted by clone/push/pull/fetch

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


def run_in_background(fn, *args, on_finished=None, on_failed=None, on_progress=None, **kwargs) -> QThread:
    """Standard call pattern. Returns the QThread — the caller MUST keep a reference
    to it (e.g. as self._active_thread on the widget) for as long as it might be
    running. A QThread that gets garbage-collected mid-run is a real, silently-crashing
    bug in PySide6, not a theoretical one — this is the single most common way a first
    attempt at this pattern breaks."""
    thread = QThread()
    worker = GitOperationWorker(fn, *args, **kwargs)
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    if on_finished: worker.finished.connect(on_finished)
    if on_failed: worker.failed.connect(on_failed)
    if on_progress: worker.progress.connect(on_progress)
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
   - Create a custom `TabContainer` and `TabButton` widget providing full styling control and dynamic tab lifecycle.
   - Dynamic tab model (§2.1): All tabs (Changes, History, PRs, Issues, detail tabs) are dynamic and closable by default, with right-click context pinning (`Pin Tab` / `Unpin Tab`). Pinned tabs show a `📌` badge, hide the `×` button, and are protected from accidental removal.
   - Per-repo deduplication rule (§2.1, §2.8): tab identity is `(tab_type, repo_path, entity_id)`. Opening an existing entity focuses that tab instead of opening a duplicate.
   - Vertical tab mode (default): tab buttons stacked vertically on the left edge, content area to the right. Horizontal mode: tab buttons across the top. Toggled via View → Tab Position menu, persisted to `ui.session_state`.
   - Trailing `+` button dropdown adds available category tabs ("Changes", "History", "Pull Requests", "Issues").
   - Keyboard: `Ctrl+1/2/3…` switches by position.
   - Tab persistence: serialize full tab list, order, pin state, and active index to `ui.session_state`.
   - API: `add_tab(...)`, `remove_tab(index)`, `pin_tab(index)`, `unpin_tab(index)`, `serialize_tabs()`, signals `current_changed(int)`, `tab_closed(int)`, `orientation_changed(Orientation)`.

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
1. `ui/commit_graph/`: FR-2.2 — render commits from `core.engine.get_log()` (paginated, not loading full history eagerly — see NFR performance target; the underlying implementation is `core/read_ops.py`, but per §4.1's façade rule the UI only ever calls the `core.engine` re-export). **Simplified v1 lane-assignment algorithm** (deliberately *not* a full min-crossing DAG layout — that's a hard graph problem, out of scope for v1 by design, not by oversight; matches the SRS's "simple yet colorful" requirement rather than over-building):
   a. Walk commits in topological + date order (pygit2's `GIT_SORT_TOPOLOGICAL | GIT_SORT_TIME`, which `get_log` should expose).
   b. Maintain a list of "active lanes," each holding the commit sha it currently expects next.
   c. For each commit: if its sha matches an active lane's expectation, place it in that lane, then set that lane's expectation to this commit's first parent; open one new lane for each *additional* parent (merge commits), or close the lane if this commit has no parents (a root).
   d. If a commit's sha matches no active lane's expectation, open a new lane for it — this happens at every branch tip.
   e. Assign each lane a persistent color from a fixed ~8-color palette, chosen once when the lane opens and kept for its lifetime, so a lane doesn't change color as it's drawn.
   f. This is O(n) in commit count and produces a readable, if not perfectly minimal-crossing, graph.
   Unit test: a fixture repo with one merge commit (two parents) — assert the algorithm opens exactly 2 lanes at the merge point and both converge back to 1 lane before it.
2. FR-2.3: search/filter over the log (ref: `ui-planning.md` §4.6). Filter params (`author`, `message_substring`, `date_from`, `date_to`, `path`) become a `LogFilter` dataclass passed into `get_log(repo, filter: LogFilter | None = None)`; matching is plain case-insensitive substring search, not regex — regex support is a plausible v2 nicety, not a v1 requirement. UI: a search bar above the commit graph with search input, author filter, path/file picker, and date-range popup that composes into one `LogFilter` per query, re-run debounced (reuse the same single-shot-`QTimer` pattern as §5 Phase 1 step 7, 300ms) rather than on every keystroke. Matching commits are highlighted and non-matching dimmed per `ui-planning.md` §4.6.
3. `core/engine.py::merge()`: FR-3.1 — `run_git(["merge", source_branch])`. Distinguish outcomes from git's exit code and output: exit 0 with "Already up to date" in stdout → `MergeResult(status="up_to_date")`; exit 0 otherwise → `MergeResult(status="merged", commit_sha=...)` (fast-forward or clean 3-way, both fine to treat the same way from the UI's perspective); nonzero exit with `<<<<<<<` conflict markers present in the working tree → `MergeResult(status="conflict", conflicted_files=[...])`, read via `repo.index.conflicts`, **not raised as an exception** — a merge conflict is an expected, routine outcome the UI should route into the merge tool, not an error state.
4. `ui/merge_tool/`: FR-3.2 (ref: `ui-planning.md` §6.6) — `ui/merge_tool/merge_dialog.py`: 3-pane top layout (Ours / Base / Theirs synchronized diff panes) + editable Result pane at the bottom. For each entry in `repo.index.conflicts` (which yields `(ancestor, ours, theirs)` `IndexEntry` tuples, any of which may be `None` for add/delete conflicts), read the corresponding blob content via `repo[entry.id].data` to populate the top panes. Provide conflict hunk navigation (`◀ Prev Conflict` / `Next Conflict ▶`, "Conflict N of Total") and per-hunk resolution actions: "Accept Current (Ours)", "Accept Incoming (Theirs)", "Accept Both (Ours ➔ Theirs)", "Accept Both (Theirs ➔ Ours)", and direct manual editing in the Result pane. On "Mark Resolved & Next", write the result pane's content to the working-tree file, call `stage_file`, and advance. Track remaining-vs-resolved count. Binary conflicts show "keep ours / keep theirs / keep both". Abort button calls `engine.merge_abort()`.
5. `core/engine.py::rebase()`: FR-3.3, deliberately **non-interactive only** in v1 (no commit reordering/squashing UI — that's part of FR-2.4's drag-and-drop rebase, explicitly deferred to v2). `run_git(["rebase", onto])`; conflicts follow the same detection pattern as `merge()` above, reusing the merge tool UI, with one difference the UI must handle: a multi-commit rebase can conflict repeatedly, once per replayed commit, so after each conflict is resolved and staged, call `run_git(["rebase", "--continue"])` rather than assuming one resolution finishes the whole operation — loop until git reports the rebase complete or the user aborts via `run_git(["rebase", "--abort"])`.
6. Complete snapshot trigger wiring (FR-10.2): call `snapshots.take_snapshot(repo, "pre_risky_op")` at the start of `merge()` and `rebase()` (added above), and add the per-repo `QTimer`-driven `timer` trigger (§4.6) now that a natural place to own its lifecycle — the open repo's main window — exists. `ui/snapshots_panel/`: minimal v1 view listing snapshots (timestamp, trigger type, label) with a restore action calling `snapshots.restore_snapshot`.
7. **Acceptance check**: `pytest tests/unit/core/test_merge.py tests/unit/core/test_rebase.py tests/unit/core/test_snapshots.py -v` green (snapshot tests assert a `pre_risky_op` snapshot exists before a rebase/merge, and that restoring it via `read-tree --reset -u` doesn't move the branch ref — check `repo.head.target` is unchanged after restore); manual QA — merge two branches with a real conflict, resolve via the UI, confirm the resulting commit is correct via `git log`; separately, make an uncommitted change, wait for a timer-triggered snapshot, restore it, confirm the change reappears and the branch/HEAD didn't move.

### Phase 3 — Remote Operations
**Prerequisites:** Phase 2's acceptance check passed (commit graph, merge, non-interactive rebase, and the built-in merge tool all working).
1. `credentials/backend.py`: implement the `CredentialBackend` ABC and `CredentialBackendUnavailableError` exactly as in §4.7 — this is new in this phase, but its shape was already fixed back in Phase 0's skeleton step, so this is filling in an interface, not designing one. `credentials/secret_service.py`: implement `SecretServiceBackend` (shared D-Bus logic per §4.5 — `store_secret`/`get_secret`/`delete_secret` via `secretstorage`'s `search_items`/`create_item`/`delete` against the default collection, handling the locked-collection case) plus its two thin subclasses `FlatpakSecretServiceBackend` and `AppImageSecretServiceBackend`, which only override `unavailable_help_text()`. `credentials/__init__.py`: implement `get_backend()` and `_detect_packaging_context()` per §4.7's corrected factory — do not reintroduce a bare `sys.platform` check as the sole dispatch, since that cannot distinguish Flatpak/AppImage/bare contexts at all. Unit test with a mocked D-Bus session (patch `secretstorage.dbus_init`/`get_default_collection`) so the suite doesn't need a real keyring in CI; an optional integration test can exercise a real Secret Service when available, skipped gracefully (`pytest.mark.skipif`) otherwise. Also test `_detect_packaging_context()` directly against all three cases (monkeypatch `os.environ`/`os.path.exists`), and test that `get_backend()` returns the right subclass for each; separately, monkeypatch `sys.platform` to something unsupported and assert `get_backend()` raises `NotImplementedError` rather than silently returning a Linux backend.
2. `core/git_credential_helper.py`: implements the `git credential-wrench` command git invokes as an external credential helper. **Git's protocol, exact (easy to get subtly wrong if improvised):**
   - Git invokes this script with exactly one argument: `get`, `store`, or `erase`.
   - Git writes `key=value` lines to the script's **stdin**, one per line (typical keys: `protocol`, `host`, `path`, `username`; `store`/`erase` also include `password`), terminated by a blank line or EOF.
   - `get`: read stdin into a dict. **Account disambiguation (FR-4.5/FR-5.8) — exact matching order:** (1) if `path` is present (requires `credential.useHttpPath = true`, set below), look up the specific `repo_forge_links` row for this repo+remote, get its `forge_account_id`, and use that account's secret directly — this is the common case once a repo is explicitly linked to an account. (2) If no `path` or no matching link row, fall back to matching `forge_accounts` by `host` alone — but only if **exactly one** account exists for that host; if zero, fall through to "not found" below; if more than one (ambiguous — two accounts, no explicit link), also fall through to "not found" rather than guessing, and let the resulting push/pull failure prompt the user to link the repo to a specific account. Once the right `forge_account.secret_service_key` is identified, resolve it via `credentials.get_backend().get_secret(key)` — never `secret_service.get_secret(...)` directly, per §4.7. If a secret was resolved, write `username=...` and `password=...` lines to **stdout** (not stderr) and exit 0. If not found, print nothing and exit 0 — git falls through to prompting, which is otherwise disabled via `GIT_TERMINAL_PROMPT=0` (§4.2), so in normal use this should surface as a clear push/pull failure rather than a hang.
   - `store`: read the same `key=value` stdin format (now including `password`), call `credentials.get_backend().store_secret(...)`, exit 0, no stdout expected.
   - `erase`: read stdin (no password expected), call `credentials.get_backend().delete_secret(...)`, exit 0.
   - This must be a real, separately-invocable entry point, because git calls it as a subprocess, not a Python import: add `git-credential-wrench = "wrench.core.git_credential_helper:main"` under `[project.scripts]` in `pyproject.toml`, so `pip install -e .` puts `git-credential-wrench` on `PATH` inside the venv/Flatpak sandbox.
   - Configure both `credential.helper` and `credential.useHttpPath = true` via `run_git`'s environment or a repo-local `.git/config` write on `open_repo`, never the user's global git config. **This only applies to HTTPS remotes** — SSH remotes don't invoke git's credential-helper mechanism at all, which is consistent with multi-account SSH identity being explicitly out of v1 scope (SRS §7).
   Unit test: call `main()` directly with a mocked stdin — a `get` case against a pre-seeded fake secret, a `store` case followed by confirming `credentials.get_backend().get_secret(...)` returns what was stored, and a **two-account-same-host** case: seed two `forge_accounts` rows both with `instance_url = https://github.com`, link one specific repo to one of them via `repo_forge_links`, and assert `get` with that repo's `path` resolves the linked account's secret, not the other one's.
3. `core/write_ops.py`: `push`, `pull`, `fetch` — wire to `run_git(["push"/"pull"/"fetch", "--progress", ...])`; git writes progress to **stderr** as lines like `Writing objects: 45% (9/20)`, so parse each stderr line with a regex (`r"(\d+)%"`) as it streams — don't wait for the process to exit and parse afterward, that defeats the purpose of a progress bar — and emit a Qt signal (`push_progress = Signal(int)`) the UI's `QProgressBar` connects to. On completion, check for "rejected" in stderr on a nonzero exit and raise a specific `PushRejectedError` rather than a generic failure, so the UI can suggest a pull/rebase instead of just showing "push failed." **`clone_repo` belongs here too** — it has a signature in §4.1 and a threading/cancellation design in §4.8, but no implementation step existed for it until now: `run_git(["clone", "--progress", url, str(temp_dir)])` into a `tempfile.mkdtemp()` location (never directly into `dest`), parsing progress the same stderr-regex way as push/pull/fetch above; on success, `shutil.move(temp_dir, dest)`; on failure or cancellation, `shutil.rmtree(temp_dir, ignore_errors=True)` and leave `dest` untouched — it should never exist as a partial directory. **Every one of push/pull/fetch/clone is called from the UI exclusively through `ui.workers.run_in_background` (§4.8), never as a direct synchronous call from a button's slot** — this is the phase where that pattern first matters in practice, since Phases 1–2's operations were fast enough that its absence wasn't yet visibly broken.
4. SSH agent (FR-4.2/FR-11.3): confirm `SSH_AUTH_SOCK` is passed through in the Flatpak manifest (`--socket=ssh-auth`, already in §6.1 of this doc). `run_git`'s subprocess environment reads the socket path via `core.ssh_agent.get_ssh_auth_socket()` (§4.7) — never `os.environ["SSH_AUTH_SOCK"]` inline — and passes it through unmodified; do not strip or override it.
5. FR-4.4: `storage` already supports multiple `repo_forge_links` rows per repo (different `remote_name` values). Add `core.engine.list_remotes(repo) -> list[Remote]` (wraps `pygit2.Repository.remotes`, returning `Remote(name, url)` pairs) and `add_remote(repo, name, url) -> None` (`repo.remotes.create(name, url)`); surface both in a small per-repo "Remotes" settings panel rather than a dedicated top-level tab — this is **S**-priority, not **M**-priority (SRS §3.4), so it shouldn't take prominent v1 UI real estate.
6. **Acceptance check**: manual QA against a real throwaway repo on GitHub (or a local bare repo over `ssh://` to a loopback test server) — push, pull, fetch all succeed with credentials coming only from Secret Service (confirm via `strace`/log inspection that no plaintext credential file is ever written); test with plain `ssh-agent` per SRS's documented v1 scope (GPG-agent/hardware-key cases documented as known-unsupported, not silently broken). Separately: clone a repo large enough to take a few seconds, confirm the UI stays responsive (window can still be moved/resized) during the clone, then cancel a clone mid-progress and confirm the destination path doesn't exist afterward — not a partial directory, nothing at all.

### Phase 4 — Forge Integration Layer
**Prerequisites:** Phase 3's acceptance check passed (push/pull/fetch working with Secret-Service-backed credentials, at least over plain ssh-agent and HTTPS).
1. `forge/models.py`: implement the dataclasses (`PullRequest`, `Issue`, `CIStatus`, `ForgeAccount`) referenced in §4.3 — fields are the provider-agnostic superset the UI needs (e.g. `PullRequest(id, title, source_branch, target_branch, state, url, author, created_at)`), not a copy of any single provider's response shape. `state` is normalized to a small fixed set (`"open" | "merged" | "closed"`) that every adapter maps its own vocabulary onto — e.g. GitLab's `"opened"` becomes `"open"` inside `gitlab.py`, not leaked through to the UI as provider-specific strings.
2. `forge/capability.py`: implement `ForgeCapability` and `ForgeAdapter` exactly as in §4.3 — this file should need no changes once Phase 4 starts writing adapters; if an adapter's needs don't fit the existing interface, that's a signal to revisit §4.3 deliberately, not to bolt on a one-off adapter-specific method. **Add a shared, protected HTTP helper on `ForgeAdapter` itself** (`self._request(method, url, **kwargs)`, wrapping `httpx`) that every one of the four adapters calls instead of using `httpx` directly — this is deliberate, not incidental: rate-limit handling, offline detection, and auth-failure translation are identical logic that four independently-written adapters would otherwise each get slightly wrong in their own way. Exactly once, here:
   - **Rate limiting**: on a `429` response, read `Retry-After` (GitHub/GitLab send this; if absent, default to a flat 60s) and raise a typed `ForgeRateLimitedError(retry_after_seconds=...)` rather than retrying silently in a loop — the UI surfaces this as "rate limited, try again in Ns," not a spinner that hangs indefinitely.
   - **Offline/unreachable**: catch `httpx.ConnectError` and `httpx.TimeoutException` specifically and re-raise as `ForgeUnreachableError` — a distinct, clear "can't reach {instance_url}, check your connection" message, not the same generic failure path as an auth or rate-limit error.
   - **Auth failures, distinguished**: a `401` means the stored credential is invalid/expired — raise `ForgeAuthenticationError` and prompt the user to re-enter the token. A `403` on an otherwise-valid credential usually means insufficient token scope (e.g. a read-only token trying to create a PR) — raise a distinct `ForgeInsufficientScopeError` with provider-specific guidance on which scope to add, since conflating these two into one generic "auth failed" message sends a user with a scope problem down the wrong troubleshooting path (re-entering the same token again and again).
3. `forge/registry.py`: implement `discover_adapters()`/`get_adapter_for_account()` exactly per §4.4; add the `[project.entry-points."wrench.forge_adapters"]` section to `pyproject.toml` in this same commit (not deferred) so registration is testable immediately rather than assumed to work.
4. `storage/forge_accounts.py`: CRUD for both `forge_accounts` and `repo_forge_links`:
   - `add_account(provider, instance_url, label, username, secret_service_key) -> int`: inserts a `forge_accounts` row, returns its `id`. No uniqueness constraint on `(provider, instance_url)` is enforced here deliberately — that's what makes multi-account (FR-5.8) possible at the storage layer with zero extra schema work.
   - `list_accounts(provider=None) -> list[ForgeAccountRecord]`: all accounts, optionally filtered to one provider — used by the account-picker UI in step 7.
   - `remove_account(account_id) -> None`: deletes the row (cascades to `repo_forge_links`) and calls `credentials.get_backend().delete_secret(account.secret_service_key)` — **not** `secret_service.delete_secret(...)` directly, which no longer exists as a flat function after §4.5/§4.7's redesign (it's a method on whichever backend `get_backend()` returns) and would also violate the "never bypass the abstraction" rule FR-11.1 exists to enforce. Do this in the same operation as the row delete, so removing an account never leaves an orphaned credential behind in the keyring.
   - `link_repo_to_account(repo_id, forge_account_id, remote_name, owner_slug, repo_slug) -> None`: upserts a `repo_forge_links` row (the table's primary key is `(repo_id, remote_name)`, so linking the same repo+remote again updates rather than duplicates).
   - `get_link_for_remote(repo_id, remote_name) -> RepoForgeLink | None`: the lookup the credential helper (§5 Phase 3 step 2) and the forge panel both depend on to resolve "which account applies here."
5. Adapter implementation order (build GitHub first — best-documented API, most available test fixtures — then reuse its test patterns for the rest):
   - `forge/adapters/github.py` — REST API v3 (`api.github.com`), auth via personal access token in an `Authorization: Bearer` header. `list_pull_requests(owner, repo)` → `GET /repos/{owner}/{repo}/pulls`; `create_pull_request(...)` → `POST /repos/{owner}/{repo}/pulls`; `get_ci_status(owner, repo, ref)` → `GET /repos/{owner}/{repo}/commits/{ref}/status` (GitHub's combined-status endpoint, which already aggregates multiple check runs into one summary state — use this rather than the lower-level check-runs endpoint, which would push aggregation logic into Wrench that GitHub already does for you). Handle pagination via the `Link` response header (`rel="next"`), not by assuming one page is everything.
   - `forge/adapters/gitlab.py` — REST API v4, auth via a `PRIVATE-TOKEN` header (not `Authorization: Bearer`, GitLab's convention differs from GitHub's here — easy to get wrong if copy-pasting from the GitHub adapter). Must support both `gitlab.com` and a self-hosted `instance_url` — never hardcode the `gitlab.com` host, always build request URLs from `account.instance_url`. `list_pull_requests` maps to GitLab's `/merge_requests` endpoint (GitLab's own term is "merge request," not "pull request" — this is exactly the kind of vocabulary the `PullRequest` dataclass in step 1 normalizes away). Pagination also uses a `Link` header, same shape as GitHub's — the one adapter where copying that logic verbatim is actually correct, not a trap.
   - `forge/adapters/forgejo.py` — Gitea-compatible API (`/api/v1/`), auth via token in an `Authorization: token {token}` header (a third distinct auth-header convention — GitHub, GitLab, and Forgejo each do this differently, which is exactly the kind of provider-specific detail the capability interface in §4.3 is meant to absorb so the UI never sees it). Must support an arbitrary self-hosted `instance_url` the same way GitLab's adapter does. Pagination is via `page`/`limit` query parameters and an `X-Total-Count` response header — **not** a `Link` header; reusing the GitHub/GitLab pagination helper unmodified here will silently stop after one page once a repo has enough PRs to need a second one. Build this one **third**, after GitHub and GitLab have already exercised the interface once each — per the risk register, Forgejo is the adapter most likely to reveal a leaky abstraction, and it's cheaper to find that with two working reference implementations already in hand than as the very first adapter built.
   - `forge/adapters/bitbucket.py` — Bitbucket Cloud REST API 2.0 (`api.bitbucket.org/2.0`). **Auth (confirmed via search, Aug 2026)**: HTTP Basic Auth with the user's Atlassian email as username and a scoped **API token** as password — the current primary supported method. Do *not* implement App Password auth: Atlassian deprecated app passwords in 2025 and disabled them permanently on June 9, 2026, so building against them would ship a dead auth path on day one. OAuth 2.0 (Authorization Code grant) remains supported and would only be the right choice if Wrench needed to act on behalf of other users rather than the signed-in user's own account — not needed for v1's per-account-token model, skip it. Store the API token via `secret_service.py` exactly like every other adapter's token (§4.5) — no special-casing needed, since Basic Auth with `email:token` is still just "a secret string" from `secret_service.py`'s point of view; construct the Basic Auth header inside `bitbucket.py` itself at call time. Pagination is yet a third distinct shape: a `next` field containing a **full URL** directly in the JSON response body — fetch that URL as-is for the next page rather than constructing one from a page number, since Bitbucket's own query parameters on that URL aren't part of any documented contract worth reconstructing by hand.
6. `ui/forge_panel/`: a tabbed sub-panel per open repo (PRs / Issues / CI), each tab rendering from `forge.models` dataclasses and gated on `adapter.capabilities` — check `ForgeCapability.ISSUES in adapter.capabilities` before even showing the Issues tab, don't show it and let clicking it fail. A PR list row shows title, state (color-coded via the normalized `state` field from step 1), author, and CI status icon; selecting one shows the description and a "create PR" button opens a form (title, description, source/target branch dropdowns populated from `list_branches`) that calls `adapter.create_pull_request(...)`.
7. Multi-account UI (FR-5.8/5.9): an "Add account" flow in settings that creates a new `forge_accounts` row (doesn't require the previous account for that provider to be removed — no uniqueness constraint blocks a second `github`-provider row). When linking a repo's remote to a forge (`repo_forge_links`), if the remote's host matches more than one configured account, show a one-time picker and persist the choice as that row — never prompt again for the same repo+remote. Also set `credential.useHttpPath` (§4.2/§5 Phase 3) when a link is created, since multi-account credential resolution depends on it.
8. **Acceptance check**: `pytest tests/integration/{github,gitlab,forgejo,bitbucket} -v` all green using `responses`-mocked HTTP fixtures in `tests/fixtures/forge_responses/` (one JSON fixture set per provider, captured from real API docs/examples — never hit real APIs in tests), including a mocked `429` for each adapter (asserts `ForgeRateLimitedError` with the right `retry_after_seconds`) and a mocked connection failure (asserts `ForgeUnreachableError`, not a raw `httpx` exception reaching the UI); manual QA — configure one real account per provider, list PRs, create a test PR, confirm CI status renders; separately, add a **second** account on the same provider (e.g. a second GitHub account), link two different local repos to the two different accounts, and confirm push/pull on each uses the correct account's credentials (verify via each account's own PR/API view, not just "it didn't error").

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
      responses.add(responses.GET,
          "https://api.github.com/repos/owner/repo/pulls",
          json=load_fixture("github/list_prs.json"), status=200)
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
| Multi-account | Ambiguous host match, no explicit link | §5 Phase 3 step 2 — falls through to "not found," never guesses |
| Submodules | Not a `repos` row, so multi-account disambiguation can't target it specifically | §5 Phase 5 step 2 — documented v1 gap, not solved |
| Packaging | Flatpak build sandbox has no network access — plain `pip install` in a build step fails | §6.1 — `flatpak-pip-generator`, regenerated whenever dependencies change, never hand-edited |
| Packaging | Flathub distribution isn't something CI can automate end-to-end | §7 stage 7 — initial listing is a one-time manual PR + human review; only later updates auto-build |

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
13. **Open, tracked in SRS §6.1**: self-hosted Forgejo/Gitea TLS handling (self-signed certs) and minimum supported API version — undecided, needs an explicit call before Phase 4's Forgejo adapter work closes out.

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
- [ ] 2.1 `ui/commit_graph/`: simplified lane-assignment algorithm per §5 Phase 2 step 1 — not a full DAG-layout attempt
- [ ] 2.2 Log search/filter (`LogFilter` dataclass)
- [ ] 2.3 `core.engine.merge()`: FF/3-way/conflict detection
- [ ] 2.4 `ui/merge_tool/`: 3-pane conflict resolution
- [ ] 2.5 `core.engine.rebase()`: non-interactive, reuses merge tool for conflicts
- [ ] 2.6 Complete snapshot trigger wiring: `pre_risky_op` calls in `merge()`/`rebase()`, the per-repo `timer` `QTimer`, and a minimal `ui/snapshots_panel/` (list + restore)
- [ ] 2.7 **CHECK**: merge/rebase/snapshot unit tests green (including: restoring a snapshot doesn't move `repo.head.target`); manual conflict-resolution QA plus a timer-triggered-snapshot restore QA pass

**Phase 3 — Remote Operations** *(prerequisites: 2.7 checked)*
- [ ] 3.1 `credentials/backend.py` (`CredentialBackend` ABC + `CredentialBackendUnavailableError`) + `credentials/secret_service.py` (shared `SecretServiceBackend` + `FlatpakSecretServiceBackend`/`AppImageSecretServiceBackend`) + `credentials/__init__.py` (`get_backend()` + `_detect_packaging_context()`) — §4.7
- [ ] 3.2 `core/git_credential_helper.py`: exact `get`/`store`/`erase` protocol per §5 Phase 3 step 2 + `[project.scripts]` entry, **including** `credential.useHttpPath` + host+path account disambiguation for multi-account (FR-4.5)
- [ ] 3.3 `core/write_ops.py`: push/pull/fetch/clone with progress parsing, all dispatched via `ui.workers.run_in_background`
- [ ] 3.4 `core/ssh_agent.py` + confirm `SSH_AUTH_SOCK` passthrough, unmodified
- [ ] 3.5 `list_remotes`/`add_remote` (FR-4.4)
- [ ] 3.6 **CHECK**: real push/pull/fetch QA; confirm no plaintext credentials are ever written (inspect via `strace`/logs)

**Phase 4 — Forge Integration Layer** *(prerequisites: 3.6 checked)*
- [ ] 4.1 `forge/models.py`: provider-agnostic dataclasses
- [ ] 4.2 `forge/capability.py`: `ForgeCapability` + `ForgeAdapter` ABC
- [ ] 4.3 `forge/registry.py`: entry-points discovery + `pyproject.toml` section
- [ ] 4.4 `storage/forge_accounts.py`: CRUD
- [ ] 4.5 `forge/adapters/github.py` — build first
- [ ] 4.6 `forge/adapters/gitlab.py`
- [ ] 4.7 `forge/adapters/forgejo.py` — build third, deliberately (most likely to reveal leaky abstractions)
- [ ] 4.8 `forge/adapters/bitbucket.py` — API-token Basic Auth; do **not** implement App Passwords (dead since June 2026)
- [ ] 4.9 `ui/forge_panel/`: capability-gated rendering — check `adapter.capabilities` before showing a feature, never call-and-catch `NotImplementedError`
- [ ] 4.10 Multi-account UI (FR-5.8/5.9): "Add account" flow (no uniqueness constraint blocks a second account per provider); one-time account picker on ambiguous repo-link, persisted to `repo_forge_links`
- [ ] 4.11 **CHECK**: all four adapters' integration tests green against mocked fixtures; manual QA with one real account per provider, plus a second same-provider account linked to a different repo, confirming each uses its own credentials

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
