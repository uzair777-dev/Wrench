-- schema version 2
PRAGMA user_version = 2;

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
    username        TEXT,
    tls_ca_bundle_path TEXT,                   -- custom PEM bundle path
    tls_insecure       INTEGER NOT NULL DEFAULT 0, -- 1 = skip verification
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
