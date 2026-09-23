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

**Step 0:** `clone_repo(url, dest, *, recursive, progress_cb, cancel_event)` per v1 §4.1; clone dialog per ui-planning §6.2.

1. Signature is **additive-keywords-only**: `clone_repo(..., depth: int | None = None, filter_spec: str | None = None)` — defaults preserve exact v1 behavior. Pass `--depth N` / `--filter=blob:none` through to the clone invocation.
2. UI: clone dialog gains a collapsed "Advanced options" section (depth spinbox, 0/empty = full clone; "blob-less partial clone" checkbox, one-line explanation each). Never default these on.
3. Honest degraded states (a shallow clone is a real restriction — v1's "surface, don't hide" rule applies): History tab shows a persistent dismissible banner on shallow repos ("Shallow clone — history truncated; Fetch ▾ → Unshallow to load everything"); blame with a shallow ceiling notes truncation; `fetch --unshallow` action in the Repository menu.

**Acceptance check:** fixture: shallow clone of a fixture repo — log stops at the boundary, banner shows, unshallow completes the history; partial clone completes and lazily fetches on demand without user-visible breakage in the Changes tab.

## VP-6 — Worktree Management (FR-1.15)

**Step 0:** Phase 4.5's discovery detects `.git`-file worktrees (they register as independent repos — that behavior is retained; this phase manages them *from the parent repo's* perspective).

1. Façade: `list_worktrees(repo) -> list[WorktreeInfo]` via `run_git(repo.path, ["worktree", "list", "--porcelain"])` with a strict parser (blank-line-separated stanzas: `worktree`, `HEAD`, `branch`, `locked`, `prunable` keys); `add_worktree(repo, path, *, branch: str | None = None)` (`["worktree", "add", path]` or `["worktree", "add", "-b", branch, path]`); `remove_worktree(repo, path, *, force=False)`; `prune_worktrees(repo)`. Writes through `run_git` per v1's write split.
2. UI: Repository ▸ Worktrees… dialog — rows (path, branch, locked), Add (folder picker + optional new-branch field), Remove (confirm; refuse dirty worktree without force + explicit warning), Prune. Keyboard-complete and `tr()`-wrapped per the a11y contract.
3. Registry interaction rule (declare it, don't improvise): worktrees are NOT auto-registered into the v1 `repos` table from this dialog — the user opts in via the normal Open flow; removal never touches a registry row for a path still registered (warn instead).

**Acceptance check:** porcelain-parsing fixtures (incl. locked + prunable stanzas); manual: add worktree on a new branch, commit from it, remove it, prune after manual deletion of the directory.

## VP-7 — Batch Fetch/Pull & Workspace Grouping (FR-1.14)

**Step 0:** **first verify the storage migration story** — if v1's `storage/` has no schema-version mechanism, this phase introduces the pattern (`PRAGMA user_version` + idempotent migration steps at startup) and documents it as the standing convention for all future schema changes. The Changes-tab selector and `repo_registry` API are v1-known; batch ops reuse Phase 3's push/pull/fetch façade.

1. Schema: nullable `repos.workspace TEXT` column via the migration runner (no new table — one denormalized column beats a join at this scale; revisit only if workspaces gain their own settings).
2. Batch engine: `fetch_all(workspace: str | None = None)` / same for pull — sequential-with-cap-3 worker pool via §4.8's machinery (network ops; never parallel-unbounded: credential prompts and keyring contention are real). Per-repo results collected into a summary (ok / up-to-date / error with typed exception) — one failing repo never aborts the batch; the summary dialog shows per-repo status and offers Retry for failures.
3. UI: File menu "Fetch All" / "Pull All"; the Changes-tab repo selector gains workspace filter chips ("All", group names); workspace assignment lives in a repo's context menu ("Move to workspace ▸ …").

**Acceptance check:** migration test (v1 schema DB → migrated, data intact); batch over 3 fixture `file://` remotes incl. one unreachable — summary lists the failure and the other two succeed; group filtering round-trips through session state.

## VP-8 — Review Threads & Inline Comments (FR-5.10)

**Step 0:** v1 Phase 4 ships review *actions* (`submit_review`, `supported_review_actions`, `ForgeCapability.REVIEWS`) and PR detail tabs; thread viewing was deliberately deferred. `_request`/`_paged_get` and the error taxonomy are reused unchanged — all HTTP via `run_in_background` (v1 §4.8).

1. Capability + models: new `ForgeCapability.REVIEW_THREADS`; `forge/models.py` gains `ReviewComment` (author, body, created_at, path: str | None, line: int | None, in_reply_to) and `ReviewThread` (id, comments list, resolved: bool | None). Adapter methods: `list_review_threads(pr)`, `reply_to_thread(thread_id, body)`, `resolve_thread(thread_id)` (raises `ForgeCapabilityError` where unsupported — GitHub REST lacks resolve; GitLab supports it; document per adapter exactly).
2. Endpoint map (scrape from docs, fixture from example payloads, comment source URLs — v1 Phase 4 guardrail): GitHub `GET/POST /repos/{o}/{r}/pulls/{n}/comments`; GitLab `GET /projects/{id}/merge_requests/{n}/discussions` (+ `PUT .../discussions/{d}?resolved=`); Forgejo `/repos/{o}/{r}/pulls/{n}/comments`; Bitbucket `/pullrequests/{n}/comments` with inline anchor fields.
3. UI: PR detail tab gains a Review Threads section (thread list, reply box per thread); when the detail tab's diff view is open, inline comments render as gutter badges on the matching path+line. Resolve toggle only where declared capable.

**Acceptance check:** fixture-JSON matrix per provider in the Phase-4 step-5 style; N+1 rule holds (threads load in one paged call per PR); capability-gated UI hides Resolve on providers lacking it.

## VP-9 — CI Run Details (FR-5.11)

1. Models: `CIRun(name, state, url, logs_url: str | None)`; adapter method `list_ci_runs(pr)`. Endpoints: GitHub `/check-runs`, GitLab `/pipelines` → `/jobs`, Forgejo Actions (limited surface — document degradation), Bitbucket `/pipelines`. Reuse Phase 4's state normalization vocab (`success`/`failure`/`pending`/`unknown`).
2. UI: PR detail's CI section becomes an expandable check list; name + state icon + Open-in-browser deep link. **No in-app log viewer in v2.0** — deliberate scope cut, recorded here so nobody builds it casually.

## VP-10 — Forge Notifications (FR-5.12)

1. `ForgeCapability.NOTIFICATIONS`; `list_notifications()`: GitHub `/notifications`, GitLab `/todos`, Forgejo `/notifications`. **Bitbucket Cloud has no public notifications API** — the adapter declares the capability absent; that's an honest gap, not a defect to paper over. Poll interval: user setting, default 5 min while open, never when closed, disable-able per account.
2. UI: bell icon + unread badge in the tab-strip header; dialog lists notifications (repo, subject, reason, age) with "mark read" and Open-in-browser.

## VP-11 — LFS Locking + Image Diff (FR-6.3, FR-6.4)

1. `core/lfs.py` + façade: `lfs_lock(repo, path)`, `lfs_unlock(repo, path, *, force=False)`, `lfs_locks(repo)` — wrappers over `git lfs lock(s)` via `run_git`. Servers without lock support fail loudly from git-lfs itself; surface that stderr verbatim (typed wrapper) rather than translating into a vague error.
2. UI: Changes-tab context menu on LFS-tracked rows gets Lock/Unlock; the §6.3 badge family gains a lock icon with accessible name.
3. Image diff: side-by-side `QPixmap` panes in the diff view for image files (before = HEAD blob, after = worktree); downscale to viewport; hard cap at 50 MP decoded size with a "too large to preview" fallback — never OOM over a diff pane.

## VP-12 — Patch Workflows (FR-3.5)

1. Façade: `format_patch(repo, range_spec, out_dir)` (`["format-patch", "-o", out_dir, range_spec]`); `apply_patch(repo, path, *, use_am=True)`. Dirty-tree guard before `am`: reuse Phase 1.5's "Stash & Switch"-style prompt triad.
2. UI: commit-graph multi-select context "Create patch series…" (folder picker via the document portal); File ▸ "Apply patch/mbox…".

**Acceptance check:** round-trip fixture (a series generated from repo A applies cleanly to repo B); dirty-tree refusal + stash path exercised.

## VP-13 — Custom User Actions (FR-12.1)

1. Storage: JSON list in `app_settings` (`custom.actions`): `{name, scope: repo|commit|file, command, confirm: bool}`.
2. Runner: subprocess, `cwd=repo`, env `WRENCH_REPO_PATH`/`WRENCH_SELECTED_SHA`/`WRENCH_SELECTED_FILE`, 30 s kill timeout, captured output shown in a dialog. Trust model stated in the UI once: "actions run with your account's full permissions — author them as you would a shell script."
3. UI: settings-dialog section to add/edit/remove; context-menu group "Custom ▸ {name}" per scope.

## VP-14 — Phase 8 Carry-overs (big-ticket, last)

- **VP-14a Interactive drag-and-drop rebase (FR-2.4):** drag targets on commit-graph lanes; implementation = generated todo list + `GIT_SEQUENCE_EDITOR` pointing at a script that writes it (never interactive shell hand-off); conflicts route to v1's Phase 2 machinery; the risk-trigger snapshot fires before starting.
- **VP-14b GPG signing UX:** still gated on the portal landscape (v1 §6.1 documented the `flatpak override --socket=gpg-agent` pattern); when picked up: per-repo `--local commit.gpgsign` toggle + key picker from `gpg --list-secret-keys`, with a detected-and-guided flow when the socket isn't available.
- **VP-14c OAuth login:** per-provider OAuth app/device flows; account disambiguation reuses v1's FR-5.9 picker; secrets through the same `CredentialBackend`.
- **VP-14d SourceForge adapter:** Allura REST API adapter as a **separately installable package** — the live end-to-end proof of v1 §3.6's entry-points architecture for genuine third parties.

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
| Interactive rebase | Conflict mid-sequence | VP-14a — v1 Phase 2 machinery; risk-snapshot taken first |

---

## V2 Master Sequential Checklist

**Phase VP-1 — Cherry-pick & Revert** *(prerequisite: v1 shipped)*
- [ ] VP-1.1 façade ops + `*_in_progress` status fields
- [ ] VP-1.2 merge-commit parent picker
- [ ] VP-1.3 graph context actions + conflict routing + snapshot trigger hookup
- [ ] VP-1.4 **CHECK**: conflict round-trip tests; manual pick/revert/merge-pick QA

**Phase VP-2 — Tags** · **Phase VP-3 — Blame** · **Phase VP-4 — Pickaxe** — each stepwise per its section above; box = that phase's acceptance check green.

**Phase VP-5 — Shallow/Partial Clone**: signature additive-only; degraded banner; unshallow path.

**VP-6 Worktrees** · **VP-7 Batch/Workspaces** (incl. schema-migration pattern landing) · **VP-8 Review Threads** · **VP-9 CI Details** · **VP-10 Notifications** · **VP-11 LFS Locks + Image Diff** · **VP-12 Patches** · **VP-13 Custom Actions** — same: per-phase acceptance check is the box.

**Phase VP-14 — Carry-overs** (last, in order): 14a drag-and-drop rebase → 14b GPG UX (only if portal landscape moved) → 14c OAuth → 14d SourceForge adapter.
