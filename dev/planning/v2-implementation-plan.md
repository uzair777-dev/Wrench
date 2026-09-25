# Wrench v2 Implementation Plan

**Scope source:** `srs.md` §3 rows marked **D (v2)** (FR-1.13–1.16, FR-2.4–2.6, FR-3.4–3.5, FR-5.10–5.12, FR-6.3–6.4, FR-12.1), plus the one S-priority post-v1 refinement that previously had no committed home — FR-8.5 (scheduled/automatic backups; SRS §3.9 marks it "S (post-v1 refinement, not blocking)"; it lands here as VP-14), plus the four carry-overs from `implementation-plan.md` §5 Phase 8 (VP-15a–d). That document's Phase 8 section is now a stub pointing here — this file is authoritative for v2.

**Structure conventions are inherited from v1's plan** (`implementation-plan.md` §0): strict phase order, each phase independently shippable, every phase has a **Step 0 — repo-state reconciliation** (verified against the tree *at v1 completion*, not against this document's assumptions — v1 reality wins everywhere they disagree), numbered steps, an explicit acceptance check, and per-phase executor guardrails. §0.5 of the v1 plan (executor failure-mode guardrails) applies verbatim to every phase below: read referenced interfaces before coding, never invent paths/symbols/deps, stubs aren't completion, never weaken tests to pass, run gates per-step, no drive-by edits. Every phase below therefore carries the full v1 phase shape: a **Prerequisites** line naming the exact predecessor gate, a **Step 0** repo-state reconciliation, numbered steps with completion gates where testable, a per-phase **Executor guardrails** block, and an explicit **acceptance check**; the Master Sequential Checklist at the end mirrors every phase as VP-N.M boxes.

**Precondition for all phases:** v1 shipped — v1's §12 checklist complete through Phase 7, SRS §3 M-priority FRs implemented, Flatpak + AppImage published.

---

## VP-1 — Cherry-pick & Revert (FR-3.4)

**Why first:** highest user-expectation-per-effort in the whole v2 set; v1's write_ops conflict plumbing and RecoveryDialog do most of the work.

**Prerequisites:** the global precondition (v1 shipped) — VP-1 is the v2 entry phase; no v2 phase precedes it.

**Executor guardrails:**
1. Read the shipped `core/write_ops.py` and its façade surface in `core/engine.py` first; extend those real signatures — never grow a parallel API for the same verbs.
2. `RepoStatus`'s new `cherry_pick_in_progress`/`revert_in_progress` fields are populated on every read path, per v1 §4.1's no-silent-no-op-fields rule; a half-populated dataclass is a step-1 failure, not a paper-over-later.
3. Step 4's hookup reuses the exact risk-trigger call sites merge/rebase already use — find them by name in the shipped code before editing; no second trigger plumbing.
4. Gates: step 1 green ⇨ the new arg-shape and state-field cases pass in the write_ops test module under `tests/unit/core/`; step 3 green ⇨ a conflict round-trip drives the real v1 conflict flow end-to-end (the `test_merge.py`/`test_rebase.py` conflict-loop pattern from Phase 2's acceptance, new operation); v1's existing suite stays green, unmodified.

**Step 0 — reconciliation:** confirm `ui/commit_graph/` has (or needs) a context menu; v1's `RepoStatus` has `merge_in_progress`/`rebase_in_progress` but **no** cherry-pick/revert state — step 1 adds them; v1's snapshot "before risky operations" trigger (FR-10.2) is the hook point for step 4.

1. `core/write_ops.py` + façade: `cherry_pick(repo, sha, *, mainline_parent: int | None = None)` → `run_git(repo.path, ["cherry-pick"] + (["-m", str(mainline_parent)] if mainline_parent else []) + [sha])`; `revert_commit(repo, sha, *, mainline_parent=None)` likewise. Non-zero exit is conflict state, NOT an exception — detect via `pygit2.Repository(repo.path).lookup_reference("CHERRY_PICK_HEAD")` / v1's `RepoStatus` pattern: add `cherry_pick_in_progress` / `revert_in_progress` boolean fields with safe defaults (additive dataclass fields, never signature breakage; v1 §4.1's "no silent no-op fields" rule applies — they must be populated on every read path).
2. Merge-commit guard: if the target commit has >1 parent and no `mainline_parent`, the UI opens a picker ("This is a merge — replay onto which parent's side?") listing each parent with its branch context. Never silently default to parent 1.
3. UI: commit-graph context menu gains "Cherry-pick onto current branch" and "Revert this commit". Conflict outcome routes through the v1 conflict flow: banner in Changes tab (`{op}_in_progress`), MergeDialog for resolution, `--continue`/`--abort` buttons reusing the rebase banner's wiring.
4. Register both operations with the snapshot risk-trigger call site (same place merge/rebase hook in) — a cherry-pick gone wrong is exactly what FR-10.1 exists for.

**Acceptance check:** unit tests for arg shapes (plain, `-m 2`, revert), conflict→resolve→continue, conflict→abort cleanups; manual QA on a fixture repo: pick a normal commit, pick a merge commit (parent picker appears), revert a commit, force a conflict and complete it via the merge tool.

## VP-2 — Tag Management (FR-1.13)

**Prerequisites:** VP-1's acceptance check passed (VP-1.4 checked).

**Executor guardrails:**
1. `TagInfo` is a new façade return type — declare it beside the ref types the graph already consumes and route it through `core/engine.py`; the UI keeps importing only the façade (v1 §4.1 rule).
2. Push targeting reuses `_get_default_remote()` exactly; rejection handling reuses Phase 3's push error translation (`PushRejectedError`) — no bespoke push path in this phase.
3. Step 2's duplicate guard runs before git is spawned; git's own "already exists" output never reaches the UI on that path.
4. Gate: step 1 green ⇨ `tests/unit/core/` covers all three arg shapes plus the duplicate-name raise; ref-label refresh is asserted against the graph's existing label model, not eyeball-only.

**Step 0:** v1's commit graph already renders tag `RefLabel`s (Phase 2); read_ops' ref-walk includes tags — there is **no** create/delete/push surface. `_get_default_remote()` exists for push targeting.

1. Façade: `list_tags(repo) -> list[TagInfo]` (pygit2 refs — name, target sha, annotated flag, message), `create_tag(repo, name, *, message: str | None = None, target: str = "HEAD")` (`run_git` — `["tag", name, target]` or `["tag", "-a", name, target, "-m", message]`; annotated when message present, lightweight otherwise), `delete_tag(repo, name)` (`["tag", "-d", name]`), `push_tag(repo, remote, name)` (`["push", remote, f"refs/tags/{name}"]` → v1's push error translation applies, incl. `PushRejectedError`).
2. Guard: `create_tag` checks `list_tags` for a name collision and raises a typed `RemoteExistsError`-style local error *before* invoking git — git's own "already exists" string never reaches the user raw.
3. UI: commit-graph context menu "Create Tag…" dialog (name, optional message → annotated, explanatory label of the difference), tag ref-label context menu "Delete Tag…" (confirm dialog; note remote deletion stays manual via push flow), post-create prompt "Push to {default remote}?". 

**Acceptance check:** unit tests for arg shapes + duplicate guard; manual: create lightweight + annotated, push, delete; verify the graph's ref-labels refresh without restart.

## VP-3 — Blame View (FR-2.5)

**Prerequisites:** VP-2's acceptance check passed (VP-2.4 checked).

**Executor guardrails:**
1. `blame()` is additive: the optional `newest_commit` keyword only — every v1 caller observes byte-identical behavior; regression-pin that.
2. This is a presentation phase: no other engine read function moves; gutter author colors read the commit graph's lane palette as shipped — no second palette.
3. The 10k-line render budget is measured on a real fixture and recorded (asserted in test or noted in the acceptance log) — never asserted by intuition.
4. Gate: `tests/unit/ui/` renders the ≥3-author fixture; gutter keyboard traversal is part of this phase's acceptance, per Phase 7's a11y contract extending here.

**Step 0:** `engine.blame()` already returns `list[BlameLine]` (v1 §4.1) — this phase is pure presentation plus one read-path extension; do NOT touch the engine's other read functions.

1. Read extension: `blame(repo, path, newest_commit: str | None = None)` gains an optional ceiling ref (default = working-tree state; pass a sha for "blame at this commit" from history). pygit2 supports this natively (`blame(..., newest_commit=...)`).
2. UI: read-only file view with a blame gutter (author + short sha + relative date per line, color-graded by commit age — reuse the commit-graph lane palette for author colors). Entry points: History-tab detail panel "Blame at this commit" button; Changes-tab file context menu "Blame". Clicking a gutter entry focuses that commit in the graph.
3. Documented v2.0 limit: no rename-following (`-M`/`-C`) — note it in the UI help text; adding it is a v2.x refinement.

**Acceptance check:** unit test on a fixture file with ≥3 known authors; a 10k-line file renders within the v1 NFR refresh budget (measure, don't assume); keyboard navigation through the gutter works (Phase 7 a11y contract extends here).

## VP-4 — Pickaxe Search (FR-2.6)

**Prerequisites:** VP-3's acceptance check passed (VP-3.3 checked).

**Executor guardrails:**
1. The `-S{term}` argument is exactly one argv element in `run_git`'s list — no string interpolation into a shell, ever (v1's subprocess convention).
2. Cancellation/timeout machinery is clone/fetch's from v1 §4.8 — same kill path, same `cancel_event` shape; this phase introduces no new threading primitives.
3. The existing 300 ms-debounced filter bar is *extended* with a mode, not rebuilt, and switching modes must not drop the other active filters.
4. Gate: fixture repo where the term appears and later disappears — both commits found; mid-search cancellation asserted; the binary-exclusion note is present in the help text.

**Step 0:** History tab's filter bar (author/message/path/date) exists with 300 ms debounce; `get_log` paginates in 100-commit batches.

1. Implementation decision (explicit, with rationale): use `run_git(repo.path, ["log", f"-S{term}", "--format=..."])` rather than pygit2 — pygit2's pickaxe support is limited and this is the documented v1 pattern of subprocess-for-what-libgit2-doesn't-do-well (v1 §1). Route through the same cancellation/timeout machinery as clone/fetch.
2. UI: filter bar gains a "content" search mode (dropdown: Message / Author / Path / Content); results use the existing pagination contract. Binary-file matches are excluded by `-S` semantics — surface "binary matches not searched" in help text.
3. Empty-result state: "No commits found touching that text" — a state, not an error.

**Acceptance check:** fixture repo with a known string introduced then removed — both commits found; query cancellation works mid-search on a large fixture; filter-mode switch preserves other filters.

## VP-5 — Shallow & Partial Clone (FR-1.16)

**Prerequisites:** VP-4's acceptance check passed (VP-4.3 checked).

**Executor guardrails:**
1. `clone_repo`'s change is additive-keywords-only with `None` defaults; every v1 caller passes neither keyword and observes byte-identical argv **against the post-Phase-4.1 baseline** — that baseline now includes the `-c credential.helper=wrench -c credential.useHttpPath=true` pairs in front of `clone` (v1 §5 Phase 4.1 step 2); the regression pin covers the full arg list including those flags.
2. `fetch --unshallow` routes through Phase 3's fetch machinery (progress/cancel/credential path), never a bespoke subprocess.
3. "Persistent dismissible" banner semantics, pinned here: it reappears on every open while the repo is shallow; dismissal is per-session, never a persisted never-show flag (surfacing the restriction is the point).
4. Gate: shallow fixture — log stops at the boundary, banner shows, unshallow completes history; a `--filter=blob:none` fixture clone stays fully usable in the Changes tab.

**Step 0:** `clone_repo(url, dest, *, recursive, progress_cb, cancel_event)` per v1 §4.1; clone dialog per ui-planning §6.2.

1. Signature is **additive-keywords-only**: `clone_repo(..., depth: int | None = None, filter_spec: str | None = None)` — defaults preserve exact v1 behavior. Pass `--depth N` / `--filter=blob:none` through to the clone invocation.
2. UI: clone dialog gains a collapsed "Advanced options" section (depth spinbox, 0/empty = full clone; "blob-less partial clone" checkbox, one-line explanation each). Never default these on.
3. Honest degraded states (a shallow clone is a real restriction — v1's "surface, don't hide" rule applies): History tab shows a persistent dismissible banner on shallow repos ("Shallow clone — history truncated; Fetch ▾ → Unshallow to load everything"); blame with a shallow ceiling notes truncation; `fetch --unshallow` action in the Repository menu.

**Acceptance check:** fixture: shallow clone of a fixture repo — log stops at the boundary, banner shows, unshallow completes the history; partial clone completes and lazily fetches on demand without user-visible breakage in the Changes tab.

## VP-6 — Worktree Management (FR-1.15)

**Prerequisites:** VP-5's acceptance check passed (VP-5.4 checked).

**Executor guardrails:**
1. The porcelain parser tolerates forward-compat change — known keys parsed, unknown keys/lines within a stanza ignored, never a crash on newer git output; fixture-cover this.
2. Removing a `locked` worktree requires force plus a confirmation whose text names the locked state; `prunable` is reported in the UI, never acted on silently.
3. The registry rule in step 3 is load-bearing: adding a worktree never writes a `repos` row implicitly, and removing one never deletes a registry row for a path still valid — warn in both directions instead.
4. Gates: parser fixtures (locked, prunable, detached-HEAD stanza); the dialog flow exercised in `tests/unit/ui/`; manual pass = add worktree on a new branch, commit from it, remove it, prune after manually deleting its directory.

**Step 0:** Phase 4.5's discovery detects `.git`-file worktrees (they register as independent repos — that behavior is retained; this phase manages them *from the parent repo's* perspective).

1. Façade: `list_worktrees(repo) -> list[WorktreeInfo]` via `run_git(repo.path, ["worktree", "list", "--porcelain"])` with a strict parser (blank-line-separated stanzas: `worktree`, `HEAD`, `branch`, `locked`, `prunable` keys); `add_worktree(repo, path, *, branch: str | None = None)` (`["worktree", "add", path]` or `["worktree", "add", "-b", branch, path]`); `remove_worktree(repo, path, *, force=False)`; `prune_worktrees(repo)`. Writes through `run_git` per v1's write split.
2. UI: Repository ▸ Worktrees… dialog — rows (path, branch, locked), Add (folder picker + optional new-branch field), Remove (confirm; refuse dirty worktree without force + explicit warning), Prune. Keyboard-complete and `tr()`-wrapped per the a11y contract.
3. Registry interaction rule (declare it, don't improvise): worktrees are NOT auto-registered into the v1 `repos` table from this dialog — the user opts in via the normal Open flow; removal never touches a registry row for a path still registered (warn instead).

**Acceptance check:** porcelain-parsing fixtures (incl. locked + prunable stanzas); manual: add worktree on a new branch, commit from it, remove it, prune after manual deletion of the directory.

## VP-7 — Batch Fetch/Pull & Workspace Grouping (FR-1.14)

**Prerequisites:** VP-6's acceptance check passed (VP-6.4 checked).

**Executor guardrails:**
1. Step 0's migration runner (`PRAGMA user_version` + idempotent steps at startup) becomes the standing convention from this phase on; read v1's `storage/schema.sql`/`storage/db.py` first, and v1's SQLite/threading rule (single module-level lock, `check_same_thread=False`) applies unchanged on the migration path.
2. Existing rows migrate to `workspace IS NULL`, surfaced as "ungrouped" — never the empty string, never a lossy backfill.
3. The batch pool runs at cap-3 through v1 §4.8's machinery; per-repo failures collect into the summary and never abort the batch; credential prompts surface per repo, never process-global.
4. Gate: migration test (pre-migration schema DB → migrated, rows intact); batch over three `file://` fixture remotes with one dead — the summary itemizes the failure and the other two succeed.

**Step 0:** **first verify the storage migration story** — v1 §3.1 already specifies the convention (`PRAGMA user_version` + `storage/migrations/schema_v{N}.sql` applied via `run_migrations` at startup), and Phase 4 already exercised a real v1→v2 migration for the `forge_accounts` TLS columns (phase-4.md test list). Confirm `storage/migrations/` exists and extends cleanly; only if it's missing does this phase introduce the pattern per v1 §3.1 verbatim, documenting it then as the standing convention. The Changes-tab selector and `repo_registry` API are v1-known; batch ops reuse Phase 3's push/pull/fetch façade.

1. Schema: nullable `repos.workspace TEXT` column via the migration runner (no new table — one denormalized column beats a join at this scale; revisit only if workspaces gain their own settings).
2. Batch engine: `fetch_all(workspace: str | None = None)` / same for pull — sequential-with-cap-3 worker pool via §4.8's machinery (network ops; never parallel-unbounded: credential prompts and keyring contention are real). Per-repo results collected into a summary (ok / up-to-date / error with typed exception) — one failing repo never aborts the batch; the summary dialog shows per-repo status and offers Retry for failures.
3. UI: File menu "Fetch All" / "Pull All"; the Changes-tab repo selector gains workspace filter chips ("All", group names); workspace assignment lives in a repo's context menu ("Move to workspace ▸ …").

**Acceptance check:** migration test (v1 schema DB → migrated, data intact); batch over 3 fixture `file://` remotes incl. one unreachable — summary lists the failure and the other two succeed; group filtering round-trips through session state.

## VP-8 — Review Threads & Inline Comments (FR-5.10)

**Prerequisites:** VP-7's acceptance check passed (VP-7.4 checked).

**Executor guardrails:**
1. Endpoint-map discipline is v1 Phase 4 step 5's: every endpoint row cites its doc URL in a comment and owns at least one JSON fixture under `tests/fixtures/forge_responses/`; a row without a fixture means the step is not done.
2. The per-provider resolve-capability claims of step 1 are written into this doc before coding and match what the adapters declare — "capable" only where verified in provider docs, never call-and-catch.
3. N+1 is structural: one paged call per PR. Reacting to a slow thread panel by adding more requests is forbidden — the step gets reworked instead.
4. Gate: the fixture matrix is green in the `tests/unit/forge/` layout v1 Phase 4 established; the UI hides Resolve strictly by capability flag (never disabled-and-hopeful).

**Step 0:** v1 Phase 4 ships review *actions* (`submit_review`, `supported_review_actions`, `ForgeCapability.REVIEWS`) and PR detail tabs; thread viewing was deliberately deferred. `_request`/`_paged_get` and the error taxonomy are reused unchanged — all HTTP via `run_in_background` (v1 §4.8).

1. Capability + models: new `ForgeCapability.REVIEW_THREADS`; `forge/models.py` gains `ReviewComment` (author, body, created_at, path: str | None, line: int | None, in_reply_to) and `ReviewThread` (id, comments list, resolved: bool | None). Adapter methods: `list_review_threads(pr)`, `reply_to_thread(thread_id, body)`, `resolve_thread(thread_id)` (raises `ForgeCapabilityError` where unsupported — GitHub REST lacks resolve; GitLab supports it; document per adapter exactly).
2. Endpoint map (scrape from docs, fixture from example payloads, comment source URLs — v1 Phase 4 guardrail): GitHub `GET/POST /repos/{o}/{r}/pulls/{n}/comments`; GitLab `GET /projects/{id}/merge_requests/{n}/discussions` (+ `PUT .../discussions/{d}?resolved=`); Forgejo `/repos/{o}/{r}/pulls/{n}/comments`; Bitbucket `/pullrequests/{n}/comments` with inline anchor fields.
3. UI: PR detail tab gains a Review Threads section (thread list, reply box per thread); when the detail tab's diff view is open, inline comments render as gutter badges on the matching path+line. Resolve toggle only where declared capable.

**Acceptance check:** fixture-JSON matrix per provider in the Phase-4 step-5 style; N+1 rule holds (threads load in one paged call per PR); capability-gated UI hides Resolve on providers lacking it.

## VP-9 — CI Run Details (FR-5.11)

**Prerequisites:** VP-8's acceptance check passed (VP-8.4 checked).

**Executor guardrails:**
1. The normalized state vocab (`success`/`failure`/`pending`/`unknown`) is read from the shipped `forge/models.py` and reused unchanged — no new state adjectives in this phase.
2. Forgejo Actions coverage is recorded per endpoint actually verified, not per marketing page; where an endpoint doesn't exist, the adapter returns an empty list and the UI shows "CI details unavailable for this provider" — never call-and-500.
3. The no-log-viewer cut (step 2) is enforced in review: any log-fetching plumbing found in the diff means scope crept and gets removed.
4. Gate: per-provider fixture JSON in `tests/fixtures/forge_responses/`; the expanded section issues ≤2 paged requests for a 50-check PR.

**Step 0 — reconciliation:** v1 Phase 4 ships the PR detail tab with a CI summary row (state icon + Open-in-browser) and the normalized state vocab in `forge/models.py`; the four adapters' state-mapping tables live beside it. All of that is read first — this phase deepens that section in place; nothing touches the v1 summary row's existing render path.

1. Models: `CIRun(name, state, url, logs_url: str | None)`; adapter method `list_ci_runs(pr)`. Endpoints: GitHub `/check-runs`, GitLab `/pipelines` → `/jobs`, Forgejo Actions (limited surface — document degradation), Bitbucket `/pipelines`. Reuse Phase 4's state normalization vocab (`success`/`failure`/`pending`/`unknown`).
2. UI: PR detail's CI section becomes an expandable check list; name + state icon + Open-in-browser deep link. **No in-app log viewer in v2.0** — deliberate scope cut, recorded here so nobody builds it casually.

**Acceptance check:** per-provider fixture-JSON matrix in the Phase-4 step-5 style (GitHub check-runs, GitLab pipeline→jobs, Forgejo Actions with its documented-degradation note, Bitbucket pipelines); expansion renders in ≤2 paged requests; the v1 summary row renders identically while the section is collapsed — v1 behavior is the default view.

## VP-10 — Forge Notifications (FR-5.12)

**Prerequisites:** VP-9's acceptance check passed (VP-9.3 checked).

**Executor guardrails:**
1. Bitbucket's absence is a declared capability gap with the UI hidden for that account — never a stub that raises at click time; the capability table says so explicitly.
2. Polling uses v1 §4.8's background machinery, and the interval persists via the v1 settings store (`storage/settings.py` get/set over `app_settings`); there is no daemon story in v2.0 — poll only while the app is open.
3. The de-duplication key is (account id, provider thread id); a multi-account user never sees the same notification twice because two accounts share a host.
4. Gate: per-provider fixtures green; capability-absence hides the bell for that account; interval honored including never-when-closed (the test asserts no worker is scheduled after the window closes).

**Step 0 — reconciliation:** v1 has no notification module and no bell UI — this phase creates both (model + per-adapter `list_notifications` beside the Phase-4 adapter files; UI anchored on Phase 1.5's tab-strip header, `ui/tabs/tab_bar.py`). What exists and is reused unchanged: Phase 4's account rows and validate-before-save flow, the FR-5.9 account-disambiguation picker, and `ui/workers.py`'s background-run patterns. The interval/enable keys are global-plus-per-account under the namespaced-key convention (`account.{account_id}.*`), matching Phase 3's `repo.{repo_id}.*` precedent.

1. `ForgeCapability.NOTIFICATIONS`; `list_notifications()`: GitHub `/notifications`, GitLab `/todos`, Forgejo `/notifications`. **Bitbucket Cloud has no public notifications API** — the adapter declares the capability absent; that's an honest gap, not a defect to paper over. Poll interval: user setting, default 5 min while open, never when closed, disable-able per account.
2. UI: bell icon + unread badge in the tab-strip header; dialog lists notifications (repo, subject, reason, age) with "mark read" and Open-in-browser.

**Acceptance check:** fixture-JSON matrix per capable provider (GitHub/GitLab/Forgejo); Bitbucket declared incapable with its UI hidden; two fixture accounts sharing a host produce no duplicate rows; an interval change takes effect without restart; closing the window schedules no further polls (test-asserted).

## VP-11 — LFS Locking + Image Diff (FR-6.3, FR-6.4)

**Prerequisites:** VP-10's acceptance check passed (VP-10.4 checked).

**Executor guardrails:**
1. Lock/unlock/locks go through Phase 5's shipped `core/lfs.py` — same `_require_lfs` gate, same `run_git` path; absent git-lfs yields v1's `LfsUnavailableError`, not a new exception family.
2. Image decoding is `QPixmap`-only — no Pillow, no new dependency for any reason ("don't add unlisted deps" is a standing rule); supported formats are exactly what Qt ships.
3. The 50 MP cap is enforced on decoded dimensions before any scaled copy is made; the fallback is a visible label, never a silent empty pane.
4. Gates: argv-shaped unit tests with `run_git` mocked (lock/unlock including force, `locks --json` parsed against fixture payloads); image diff renders fixture images and rejects a synthetic >50 MP case with the fallback text.

**Step 0 — reconciliation:** Phase 5's LFS surface (`lfs_available`/`_require_lfs`/`lfs_files`/`is_lfs_pointer`/`parse_lfs_pointer`/track/pull/push) and the Changes-tab badge family from ui-planning §6.3 exist; the diff view (`ui/diff_view/`) renders text only. Read the shipped `core/lfs.py` and §6.3's badge spec first — the badge set grows by exactly one (lock icon), and step 2's context menu extends the existing LFS-row menu rather than forking a second one.

1. `core/lfs.py` + façade: `lfs_lock(repo, path)`, `lfs_unlock(repo, path, *, force=False)`, `lfs_locks(repo)` — wrappers over `git lfs lock(s)` via `run_git`. Servers without lock support fail loudly from git-lfs itself; surface that stderr verbatim (typed wrapper) rather than translating into a vague error.
2. UI: Changes-tab context menu on LFS-tracked rows gets Lock/Unlock; the §6.3 badge family gains a lock icon with accessible name.
3. Image diff: side-by-side `QPixmap` panes in the diff view for image files (before = HEAD blob, after = worktree); downscale to viewport; hard cap at 50 MP decoded size with a "too large to preview" fallback — never OOM over a diff pane.

**Acceptance check:** `run_git`-mocked unit tests for the lock/unlock/locks argv and the `--json` parse; a lockless server's stderr surfacing verbatim in its typed wrapper; Changes-tab Lock/Unlock reachable by keyboard with accessible names; fixture images render side-by-side within v1's NFR refresh budget; a >50 MP image shows the fallback, never a crash or a hang.

## VP-12 — Patch Workflows (FR-3.5)

**Prerequisites:** VP-11's acceptance check passed (VP-11.4 checked).

**Executor guardrails:**
1. `format-patch` output paths come from the document-portal folder picker (v1 §5's pattern) — never a hardcoded home path, under any packaging mode.
2. `apply_patch(use_am=True)`'s fallback to plain `git apply` + a staged result on malformed series is declared in the UI, not silent.
3. The dirty-tree guard is Phase 1.5's Stash & Switch-style triad reused as a component, not re-authored.
4. Gate: A→B round-trip fixture test; dirty-tree refusal + stash path exercised in `tests/unit/ui/`; a multi-selected range preserves the graph's topological order in the generated series.

**Step 0 — reconciliation:** v1 Phase 2's commit graph operates on single-commit selection + context menus (VP-1/VP-2 add more items) — multi-select does not exist until this phase and is part of step 2, not assumed; `core/write_ops.py` hosts the subprocess writes; the branch-switcher's dirty-tree triad (Phase 1.5) is the prompt-reuse source.

1. Façade: `format_patch(repo, range_spec, out_dir)` (`["format-patch", "-o", out_dir, range_spec]`); `apply_patch(repo, path, *, use_am=True)`. Dirty-tree guard before `am`: reuse Phase 1.5's "Stash & Switch"-style prompt triad.
2. UI: commit-graph multi-select context "Create patch series…" (folder picker via the document portal); File ▸ "Apply patch/mbox…".

**Acceptance check:** round-trip fixture (a series generated from repo A applies cleanly to repo B); dirty-tree refusal + stash path exercised.

## VP-13 — Custom User Actions (FR-12.1)

**Prerequisites:** VP-12's acceptance check passed (VP-12.3 checked).

**Executor guardrails:**
1. Commands are executed via `shlex.split` + argv exec — `shell=True` never appears in this phase; the trust notice in step 2 states the runner shape honestly.
2. The environment contract is exactly the three variables SRS FR-12.1 names, and only variables with real values are exported (a repo-scope action exports `WRENCH_REPO_PATH` alone) — empty-string exports are a bug.
3. The 30 s timeout kills the process and reports "killed (timeout)" in the output dialog; there is no run-forever mode in v2.0.
4. Gate: CRUD + env-construction + quoted-argument + timeout-kill unit tests (fixture command: `sleep`); settings round-trip through `app_settings`.

**Step 0 — reconciliation:** v1 DOES ship a settings dialog — `ui/dialogs/settings_dialog.py` (Phase 4.3, ui-planning §6.11) with its `SettingsPage` base class and instant-apply contract — so this phase ADDS a "Custom Actions" page to that existing dialog and never introduces a parallel one-off settings surface. (Historical note: an earlier revision of this Step 0 assumed v1 had no settings dialog at all — corrected when Phase 4.3 landed one.) Persistence reuse is confirmed real: `storage/settings.py` exposes `get_setting`/`set_setting` over `app_settings` with the namespaced-key convention (Phase 3's `repo.{repo_id}.remote_last_fetch.*` precedent); `custom.actions` is a *global* key because actions are user-global, not per-repo.

1. Storage: JSON list in `app_settings` (`custom.actions`): `{name, scope: repo|commit|file, command, confirm: bool}`.
2. Runner: subprocess, `cwd=repo`, env `WRENCH_REPO_PATH`/`WRENCH_SELECTED_SHA`/`WRENCH_SELECTED_FILE`, 30 s kill timeout, captured output shown in a dialog. Trust model stated in the UI once: "actions run with your account's full permissions — author them as you would a shell script."
3. UI: the v1 settings dialog (`ui/dialogs/settings_dialog.py`, Phase 4.3) gains a **Custom Actions** page — add/edit/remove rows following ui-planning §6.11's instant-apply contract (writes on change, no Apply button); context-menu group "Custom ▸ {name}" per scope, keyboard-reachable like every other menu.

**Acceptance check:** the step-4 gates green; one repo-scope and one commit-scope action run end-to-end with the captured-output dialog verified; the trust notice renders once, dismissibly, before the first run.

## VP-14 — Scheduled Backups (FR-8.5)

**Why here:** the lone S-priority post-v1 refinement; it rides entirely on machinery v1 has already proven in the field (the §3.9 backup engine, FR-10.2's timer wiring), so it belongs after every user-facing gap above and before the big-ticket carry-overs.

**Prerequisites:** VP-13's acceptance check passed (VP-13.4 checked).

**Executor guardrails:**
1. `core/backup.py` and v1's FR-10.2 timer wiring (a per-repo `QTimer` owned by `main_window`, recreated on repo change) are read first. Scheduling runs on **one app-level timer** sweeping registered repos — never a thread or `QTimer` per repo.
2. Persistence follows the v1 namespaced-key convention over `app_settings` via `storage/settings.py` (`set_setting(conn, f"repo.{repo_id}.backup_schedule", json)`), matching Phase 3's `remote_last_fetch` precedent — no new tables, no schema change: one JSON value per repo.
3. The "on commit" trigger subscribes at the same engine call site FR-10.2's commit trigger uses; if that call site can't safely host a second subscriber, the step adds a minimal engine hook — it never monkey-patches.
4. Gates: step 2 green ⇨ scheduler unit tests with an injected fake clock; step 3 green ⇨ a destination-vanishes fixture test asserting `last_run_ok: false` plus exactly one warning.

**Step 0 — reconciliation:** verify at pickup: (a) `core/backup.py`'s shipped entry-point name and result type (§3.9's backup/restore pair); (b) the FR-10.2 timer's lifecycle owner and whether an app-level timer exists to piggyback on; (c) `app_settings` namespaced get/set in `storage/settings.py` (confirmed in the v1 tree); (d) no scheduler and no "last-run" record exist anywhere in v1 — this phase introduces both.

1. Model + storage: per-repo schedule in `app_settings` under `repo.{repo_id}.backup_schedule` = JSON `{enabled, interval_hours: int | null, on_commit: bool, destination, last_run_at: str | null, last_run_ok: bool | null}`; ISO-8601 UTC timestamps, per Phase 3's fetch-timestamp convention.
2. Scheduler: one app-level `QTimer` (minute-granularity, coalesced ticks) owned where the v1 snapshot timers are owned; on each tick, due repos run the §3.9 backup entry point through §4.8's background machinery with progress surfaced. Missed-window policy, decided here rather than left to taste: if the app was closed past a due time, the backup runs **once at next launch** — never a catch-up burst per skipped interval.
3. Failure semantics: an unavailable or vanished destination records `last_run_ok: false` plus the error, surfaces as one non-modal status-bar warning per run (never a dialog storm — a NAS asleep overnight must not stack eight warnings), and retries only on the next scheduled tick. A backup is recorded complete only when the §3.9 engine's own success criteria pass — a partially copied snapshot never masquerades as done.
4. UI: v1's snapshots panel (`ui/snapshots_panel/`, confirmed in the shipped tree) gains a collapsible "Scheduled backup" section: enable toggle, interval spinbox (hours, minimum 1), "On every commit" checkbox, destination row with the document-portal folder picker, and a read-only "Last run: {relative time} — ok / failed" line. All `tr()`-wrapped; every control keyboard-reachable.

**Acceptance check:** injected-fake-clock unit tests covering due/overdue/neither, once-at-next-launch after a missed window, failed copy ⇒ `last_run_ok: false` with exactly one warning, and the on-commit trigger firing through the real engine hook; manual QA: a 1-hour schedule onto a USB mount — unplug the drive (single warning, honest last-run state), replug, next tick completes.

## VP-15 — Phase 8 Carry-overs (big-ticket, last)

- **VP-15a Interactive drag-and-drop rebase (FR-2.4):** drag targets on commit-graph lanes; implementation = generated todo list + `GIT_SEQUENCE_EDITOR` pointing at a script that writes it (never interactive shell hand-off); conflicts route to v1's Phase 2 machinery; the risk-trigger snapshot fires before starting.
- **VP-15b GPG signing UX:** still gated on the portal landscape (v1 §6.1 documented the `flatpak override --socket=gpg-agent` pattern); when picked up: per-repo `--local commit.gpgsign` toggle + key picker from `gpg --list-secret-keys`, with a detected-and-guided flow when the socket isn't available.
- **VP-15c OAuth login:** per-provider OAuth app/device flows; account disambiguation reuses v1's FR-5.9 picker; secrets through the same `CredentialBackend`.
- **VP-15d SourceForge adapter:** Allura REST API adapter as a **separately installable package** — the live end-to-end proof of v1 §3.6's entry-points architecture for genuine third parties.

**Structure note:** each carry-over gains the full phase shape at pickup time — Step 0, executor guardrails, per-step gates, acceptance check, and checklist boxes added to this file then and only then. Their stub form here is deliberate scope control, not an invitation to start early.

---

## V2 Edge Case Reference (extends v1 §8.1)

| Area | Edge case | Where it's handled |
|---|---|---|
| Cherry-pick/revert | Target is a merge commit (needs `-m`) | VP-1 step 2 — parent picker, never silent |
| Cherry-pick | Conflict mid-pick | VP-1 steps 1/3 — `CHERRY_PICK_HEAD` state → v1 conflict flow |
| Tags | Duplicate tag name | VP-2 step 2 — typed local error before invoking git |
| Blame | Huge files | VP-3 step 3 — rendering budget measured, not assumed |
| Pickaxe | Binary content matches | VP-4 step 2 — `-S` skips binaries; surfaced in help text |
| Shallow clone | Blame/log silently truncated deep-history results | VP-5 step 3 — persistent banner + explicit Unshallow |
| Worktrees | Removing a worktree path still registered in `repos` | VP-6 step 3 — warn, never silently unregister |
| Batch ops | One repo's auth failure in a 20-repo pull | VP-7 step 2 — per-repo results, batch never aborts |
| Forge | Provider lacks thread-resolve / notifications / jobs API | VP-8/9/10 — capability flags; absent capability = hidden UI, never a call-and-catch |
| LFS locks | Server without lock support | VP-11 step 1 — git-lfs stderr surfaced verbatim in a typed wrapper |
| Image diff | Huge image files | VP-11 step 3 — 50 MP decode cap + fallback text |
| Patches | `am` on a dirty tree | VP-12 step 1 — stash-prompt triad, never force |
| Custom actions | User script hangs | VP-13 step 2 — 30 s timeout + kill |
| Tags | Push rejected by the remote (tag name already exists upstream) | VP-2 step 3 — Phase 3's `PushRejectedError` translation carries the reason; force-push is never offered silently |
| Batch ops | A registered repo's path moved between listing and execution | VP-7 step 2 — the repo is itemized in the summary as failed/unreachable; the registry row is never auto-mutated by a batch run (the absence may be a transient unmount) |
| Scheduled backup | Destination offline/unmounted when a run comes due | VP-14 step 3 — run skipped with `last_run_ok: false` + one non-modal warning; retry only on the next tick; a partial copy is never recorded as success |
| Notifications | Same thread visible via two configured accounts sharing a host | VP-10 guardrail 3 — de-dup key is (account id, thread id); badges count per account, never double-counted |
| Partial clone | Promisor/blob fetch fails while offline mid-blame/diff | VP-5 step 3 — git's promisor error surfaces verbatim with the partial-clone context named; no retry loop, no silent empty diff |
| Interactive rebase | Conflict mid-sequence | VP-15a — v1 Phase 2 machinery; risk-snapshot taken first |

---

## V2 Master Sequential Checklist

**Phase VP-1 — Cherry-pick & Revert** *(prerequisite: v1 shipped)*
- [ ] VP-1.1 façade ops + `*_in_progress` status fields
- [ ] VP-1.2 merge-commit parent picker
- [ ] VP-1.3 graph context actions + conflict routing + snapshot trigger hookup
- [ ] VP-1.4 **CHECK**: conflict round-trip tests; manual pick/revert/merge-pick QA

**Phase VP-2 — Tag Management** *(prerequisite: VP-1.4 checked)*
- [ ] VP-2.1 façade `list_tags`/`create_tag`/`delete_tag`/`push_tag` + `TagInfo` through `core/engine.py`
- [ ] VP-2.2 duplicate-name typed guard firing before git is spawned
- [ ] VP-2.3 create dialog + ref-label delete menu + post-create push prompt; labels refresh without restart
- [ ] VP-2.4 **CHECK**: arg-shape + duplicate tests green; manual lightweight/annotated/push/delete pass

**Phase VP-3 — Blame View** *(prerequisite: VP-2.4 checked)*
- [ ] VP-3.1 `blame(newest_commit=)` additive extension; v1 callers byte-identical
- [ ] VP-3.2 read-only blame view + age-graded gutter (lane-palette reuse) + both entry points + gutter→graph focus
- [ ] VP-3.3 **CHECK**: ≥3-author fixture test; 10k-line render budget measured; gutter keyboard traversal verified

**Phase VP-4 — Pickaxe Search** *(prerequisite: VP-3.3 checked)*
- [ ] VP-4.1 `-S` search via `run_git` on §4.8's cancellation/timeout machinery (single argv element)
- [ ] VP-4.2 filter-bar Content mode + empty state + binary-exclusion help text
- [ ] VP-4.3 **CHECK**: introduce/remove fixture found; mid-search cancellation; mode switch preserves filters

**Phase VP-5 — Shallow/Partial Clone** *(prerequisite: VP-4.3 checked)*
- [ ] VP-5.1 additive `depth`/`filter_spec` keywords; v1 callers byte-identical
- [ ] VP-5.2 clone-dialog Advanced options (never default-on)
- [ ] VP-5.3 per-session-dismissible shallow banner + Unshallow action + blame truncation note
- [ ] VP-5.4 **CHECK**: shallow-fixture boundary + banner + unshallow; partial clone lazy fetch QA

**Phase VP-6 — Worktrees** *(prerequisite: VP-5.4 checked)*
- [ ] VP-6.1 façade list/add/remove/prune + forward-tolerant strict porcelain parser
- [ ] VP-6.2 Worktrees dialog; dirty refusal without force + explicit locked-state warning
- [ ] VP-6.3 registry non-interference: no implicit register on add, no silent unregister on remove
- [ ] VP-6.4 **CHECK**: locked/prunable/detached fixtures; manual add/commit/remove/prune pass

**Phase VP-7 — Batch Fetch/Pull & Workspaces** *(prerequisite: VP-6.4 checked)*
- [ ] VP-7.1 schema-migration runner (`PRAGMA user_version` + idempotent steps) lands the standing convention
- [ ] VP-7.2 `repos.workspace` column; existing rows → NULL = ungrouped, never lossy
- [ ] VP-7.3 cap-3 batch engine through §4.8 machinery + per-repo summary with retry; chips + Move-to-workspace menu
- [ ] VP-7.4 **CHECK**: migration test with data intact; three-`file://`-remote batch with one dead; chips round-trip session state

**Phase VP-8 — Review Threads & Inline Comments** *(prerequisite: VP-7.4 checked)*
- [ ] VP-8.1 `REVIEW_THREADS` capability + `ReviewComment`/`ReviewThread` models + per-provider resolve truth table
- [ ] VP-8.2 endpoint map with cited doc URLs + `tests/fixtures/forge_responses/` JSON per row
- [ ] VP-8.3 thread section + inline gutter badges + resolve strictly capability-gated
- [ ] VP-8.4 **CHECK**: per-provider fixture matrix green; one paged call per PR; Resolve hidden where incapable

**Phase VP-9 — CI Run Details** *(prerequisite: VP-8.4 checked)*
- [ ] VP-9.1 `CIRun` model + `list_ci_runs` per provider (Forgejo degradation documented per verified endpoint)
- [ ] VP-9.2 expandable check list + deep links; no in-app log viewer
- [ ] VP-9.3 **CHECK**: per-provider fixtures; ≤2 paged requests on 50 checks; v1 summary row unchanged when collapsed

**Phase VP-10 — Forge Notifications** *(prerequisite: VP-9.3 checked)*
- [ ] VP-10.1 `NOTIFICATIONS` capability + per-provider `list_notifications`; Bitbucket honestly absent
- [ ] VP-10.2 poll engine: settable interval (default 5 min), never-when-closed, per-account disable
- [ ] VP-10.3 bell + unread badge + dialog (mark read, Open-in-browser); per-(account, thread) de-dup
- [ ] VP-10.4 **CHECK**: capability absence hides UI; interval honored live; no polls scheduled after close (test-asserted)

**Phase VP-11 — LFS Locks + Image Diff** *(prerequisite: VP-10.4 checked)*
- [ ] VP-11.1 `lfs_lock`/`lfs_unlock`/`lfs_locks` via `run_git` + `_require_lfs`; lockless-server stderr surfaced verbatim, typed
- [ ] VP-11.2 Changes-tab Lock/Unlock + lock badge with accessible name
- [ ] VP-11.3 side-by-side `QPixmap` image diff; 50 MP decode cap + fallback label; no new deps
- [ ] VP-11.4 **CHECK**: argv/JSON-parse unit tests; fixture images render in budget; oversize refusal

**Phase VP-12 — Patch Workflows** *(prerequisite: VP-11.4 checked)*
- [ ] VP-12.1 `format_patch`/`apply_patch` façade; dirty-tree stash-prompt triad before `am`; portal picker for output
- [ ] VP-12.2 graph multi-select "Create patch series…" + File ▸ "Apply patch/mbox…"
- [ ] VP-12.3 **CHECK**: repo-A→repo-B round-trip; dirty refusal + stash path; series in topological order

**Phase VP-13 — Custom Actions** *(prerequisite: VP-12.3 checked)*
- [ ] VP-13.1 `custom.actions` CRUD in `app_settings` + the Custom Actions page in v1's Phase-4.3 settings dialog (§6.11 instant-apply contract)
- [ ] VP-13.2 runner: `shlex.split` argv exec, scoped env contract, 30 s kill, captured-output dialog
- [ ] VP-13.3 per-scope "Custom ▸ {name}" menu group + one-time trust notice
- [ ] VP-13.4 **CHECK**: CRUD/env/quoted-arg/timeout-kill tests; repo- and commit-scope actions end-to-end

**Phase VP-14 — Scheduled Backups** *(prerequisite: VP-13.4 checked)*
- [ ] VP-14.1 per-repo schedule record in `app_settings` (namespaced key, ISO-8601 UTC)
- [ ] VP-14.2 single app-level scheduler timer; missed-window = once-at-next-launch, no catch-up burst
- [ ] VP-14.3 failure honesty: `last_run_ok`, one non-modal warning per run, no partial-copy success
- [ ] VP-14.4 snapshots-panel "Scheduled backup" section (portal picker, interval, on-commit, last-run line)
- [ ] VP-14.5 **CHECK**: fake-clock scheduler tests; unplug/replug QA pass

**Phase VP-15 — Carry-overs** (last, in order): 15a drag-and-drop rebase → 15b GPG UX (only if the portal landscape moved) → 15c OAuth → 15d SourceForge adapter. Each gains its full stepwise section + boxes in this file at pickup time — not before.
