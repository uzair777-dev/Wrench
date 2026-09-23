# Software Requirements Specification — Wrench

**Version:** 0.1 (draft)
**Status:** Living document, updated across multiple requirements/design sessions. The large majority of items are ✅ Confirmed (see §7's Assumptions & Decisions Log for the full history of what changed and why). Items with no committed direction yet are listed separately in §6.1, rather than scattered through the document as inline ⚠️ markers.

---

## 1. Introduction

### 1.1 Purpose
Wrench is a free and open-source, native Linux desktop Git client targeting feature parity with GitHub Desktop (simplicity, PR-centric workflow) and GitKraken (visual branch graph, forge integrations), built with Qt/PySide6. It targets KDE Plasma users first, and works equally well on GNOME and other desktop environments via Flatpak. "Plasma-first" here means target audience and visual polish, not a framework dependency — see §2.4/§3.12 for why the app uses plain Qt widgets rather than KDE Frameworks.

### 1.2 Scope
Wrench manages local Git repositories end-to-end: repository creation/cloning, staging and committing, branching and merging, remote synchronization over SSH/HTTPS, and forge-native collaboration (pull/merge requests, issues, CI status) across the **confirmed v1 backend set — GitHub, GitLab, Forgejo/Gitea (including self-hosted instances), and Bitbucket Cloud**. The forge integration layer is built as a **capability-based, entry-points plugin architecture** (adapters register themselves via Python packaging entry points against a shared capability interface) so additional backends can be added — by the project or the community — without redesigning the core app (see §3.6 and §7.1 for the full extension roadmap).

### 1.3 Definitions
| Term | Meaning |
|---|---|
| Forge | A Git hosting platform (GitHub, GitLab, Forgejo/Gitea, Bitbucket) |
| MR/PR | Merge Request (GitLab/Forgejo) / Pull Request (GitHub) — used interchangeably |
| Secret Service | freedesktop.org D-Bus API for credential storage (backed by GNOME Keyring or KWallet) |
| Portal | XDG Desktop Portal — sandboxed apps' mediated access to host resources |

### 1.4 Confirmed decisions and remaining open items
- ✅ **Source hosting platform**: **GitHub**, confirmed (cost consideration — free for public repos). App ID and CI plan below use GitHub. Since Wrench's core is host-agnostic by design (FR-5.1), migrating hosting later (e.g. to Codeberg) remains low-friction if desired.
- ✅ **GitHub username / project namespace**: confirmed — `uzair`. App ID is `io.github.uzair.Wrench`.
- ✅ **v1 forge backend set**: confirmed — **GitHub, GitLab, Forgejo/Gitea, and Bitbucket Cloud**. Built on a capability-based provider interface with adapters registered via Python entry points (see §3.6), so the confirmed set ships in v1 while additional backends can be added without core changes (see §7.1 Backend Extension Roadmap).
- ✅ **Localization scope for v1**: confirmed English-only for v1. UI strings wrapped for translation (Qt Linguist `tr()`) from initial implementation. Machine translation may be explored post-v1 to bootstrap additional languages before community/human translations arrive.
- ✅ **Target Qt version**: confirmed Qt 6.6+ (PySide6), **no KDE Frameworks (KF6) dependency** — plain Qt widgets only, revised for cross-platform portability (see §2.4, §3.12, Assumptions Log #3/#15). The Flatpak runtime is still `org.kde.Platform` (a packaging choice providing Qt libraries, unrelated to this — see §2.3).

---

## 2. Overall Description

### 2.1 Product Perspective
Wrench is a new, independent product — not a fork of an existing client. It competes directly with GitHub Desktop (ease of use) and GitKraken (visual power), while differentiating on: full FOSS licensing (AGPL-3.0), first-class Forgejo/self-hosted support, and a Plasma-friendly native Qt experience (plain widgets, no KDE-Frameworks dependency — see §2.4).

### 2.1.1 Competitive Landscape (market research)

| App | Native/Platform | License/Price | Forge integration | Notable strength | Notable gap |
|---|---|---|---|---|---|
| KDE's "Kommit" (formerly GitKlient) | Qt/KDE-native, Flatpak | GPL-3.0, free | None found | Dolphin file-manager overlay + context-menu integration | No PR/MR, no LFS/submodule UI — fairly basic |
| GitFourchette | Qt/Plasma-styled, Flatpak | Open source, free | Limited | Native-feeling Qt UI on Flathub | Smaller feature set than full forge-integrated clients |
| Gittyup (active continuation of GitAhead) | Qt/C++, Flathub | MIT, free | GitHub/GitLab/Bitbucket/Beanstalk account linking, no PR/MR workflow | Closest existing FOSS+Qt+Flatpak comparable to Wrench; original GitAhead is unmaintained, this fork keeps it alive | No PR/MR workflow at all, no multi-account, no undo/snapshot safety net, no Forgejo |
| GitKraken | Electron, cross-platform | Freemium ($5/mo Pro) | GitHub/GitLab/Bitbucket/Azure DevOps | Richest visual UX; commonly cited as the default full-featured Linux pick | Requires account creation — a recurring user complaint; not native, not Flatpak |
| GitButler | Tauri/Rust, cross-platform, on Flathub | Open source, free (beta) | GitHub-centric | Virtual branches (multiple branches applied to the working directory at once), unlimited undo, AI-assisted commits | Not Qt/KDE-native; forge support beyond GitHub unclear |
| SmartGit | Java/Swing, cross-platform | Free non-commercial / paid commercial | GitHub, GitLab, Bitbucket, Azure DevOps | Drag-and-drop rebase, SVN+Git support | Not native to any desktop environment |
| Sublime Merge | Custom, cross-platform | Proprietary, paid | None | Custom high-performance git reading library, built for very large repos | No forge/PR integration at all |
| git-cola | PyQt, cross-platform | GPL, free | Basic GitHub/Bitbucket | Lightweight, minimal footprint | Visually dated; no LFS/submodule GUI, no plugin architecture |
| Sourcetree | Electron, Mac/Windows only | Free | Bitbucket-native | Full git ops incl. submodules | Not available on Linux at all; criticized in recent reviews for feeling heavy on large repos |
| GitHub Desktop | Electron, Mac/Windows only | Free | GitHub only | Simple, approachable | Not available for Linux; single-forge; no multi-account support at all |
| Tower | Native, Mac/Windows only | Paid (one-time + subscription tiers) | GitHub/GitLab/Bitbucket/Azure DevOps | Cmd/Ctrl+Z "Undo" across most git actions — the closest existing analog to Wrench's rolling-snapshot safety net | Linear action-undo stack, not browsable point-in-time snapshots; doesn't capture untracked files; not on Linux at all |
| gitg | GTK, GNOME-native | GPL, free | None | GNOME HIG-native | Explicitly lacks a merge conflict resolver |

### 2.1.2 Positioning implications (from the research above)

- **No competitor combines** a native Qt experience on Linux + Flatpak-first distribution + multi-backend forge PR/MR support (GitHub/GitLab/Forgejo/Bitbucket) + an extensible adapter architecture. Competitors either hardcode a short forge list (GitKraken, SmartGit) or skip forge integration entirely (Sublime Merge, gitg, git-cola, KDE's own Kommit). This combination is Wrench's core differentiation, not a single feature.
- **Native architecture is a validated choice, not just an aesthetic preference** — recent reviews specifically call out Electron-based clients (Sourcetree, GitKraken) as feeling heavy on large repositories.
- **Mandatory account creation is a named, recurring complaint about the market leader (GitKraken)** — this motivates an explicit product principle: Wrench must never require its own account for local git functionality; forge accounts are opt-in and only needed when the user connects a specific forge. Codified as an explicit NFR (§4, Privacy row) rather than left implicit.
- **No competitor surveyed offers a first-class local backup/snapshot-to-NAS feature** (§3.9). This is a potential differentiator, but an unvalidated one — no competitor's existence proves demand for it either way.
- **Self-hosted Forgejo/Gitea support is rare among commercial competitors** — reinforces FR-5.4 as a differentiator for the self-hosting/homelab and small-team user class, not just a nice-to-have.
- **Entry-points/plugin-based forge extensibility (FR-5.7) appears to be unique** among the surveyed competitors — none of them expose a public adapter/plugin mechanism for adding new forges; they hardcode their supported list. A talking point for potential contributors, not just an internal architecture decision.
- **Multi-account support (FR-5.8/5.9) is a validated gap, not a hypothetical one.** GitHub Desktop doesn't support it at all. GitKraken does, via "Profiles," but only on a paid tier, and it's profile-switching (isolated settings/tabs per profile) rather than working across two accounts' repos side-by-side. A small cottage industry of standalone workaround tools (SSH-key switchers, browser extensions) exists purely to paper over this gap across the ecosystem — indirect evidence of demand. Wrench's free, per-repo account assignment, with no profile-switching required, is a real differentiator here.
- **The rolling-snapshot safety net (§3.11) has one analog in the surveyed market — Tower's "Undo"** — and it's mechanically different: a linear Cmd/Ctrl+Z action-undo stack, not a browsable list of point-in-time restore points, and it doesn't capture untracked files. Tower is also Mac/Windows-only and paid. As far as this research shows, **no Linux-available client currently offers anything like Wrench's snapshot system** — an unclaimed differentiator on this platform today, though worth re-checking periodically since this space can move quickly.

### 2.2 User Classes
- **Primary**: Linux desktop developers who want a GUI git client instead of pure CLI, across personal/local and forge-hosted projects.
- **Secondary**: Teams self-hosting Forgejo/Gitea who are underserved by GitHub Desktop and GitKraken's forge support.

### 2.3 Operating Environment
- Linux only for v1 — but architected for future portability; see §3.12 and §7.3. No non-Linux platform ships in v1.
- Primary distribution: Flatpak (Flathub), targeting `org.kde.Platform` runtime — a packaging/runtime choice (it provides Qt6 libraries and is the most complete Qt-providing runtime on Flathub), unrelated to §2.4's decision to avoid KDE-Frameworks *APIs* in application code. These operate at different layers and aren't in tension.
- Secondary distribution: AppImage.
- Desktop environment: KDE Plasma primary target; must remain functional (not necessarily pixel-native) on GNOME/others since Flatpak is DE-agnostic.

### 2.4 Constraints
- **License**: AGPL-3.0 for the whole project.
- **UI toolkit**: PySide6 (LGPL) — chosen over PyQt6 specifically to avoid GPL/commercial dual-license entanglement and to track upstream Qt releases via the officially maintained binding. **Plain Qt widgets only — no KDE-Frameworks-specific APIs** (KConfig, KXmlGui, KIO, or equivalent), even on Linux. This supersedes an earlier KF6 commitment (see §3.12, Assumptions Log #3): the trade is some native Plasma polish (no automatic KDE System Settings integration) for keeping a future Windows/macOS port additive rather than a rewrite.
- **Language**: Python 3.12+.

---

## 3. Functional Requirements

Priority key: **M** = Must have (v1), **S** = Should have (v1), **D** = Deferred (v2+)

### 3.1 Local Repository Management
| ID | Requirement | Priority |
|---|---|---|
| FR-1.1 | Create new local repository (`git init`) with identity check/prompt if `user.name`/`user.email` unset | M |
| FR-1.2 | Maintain a local registry of known repos (path, last branch, last opened) independent of filesystem scanning | M |
| FR-1.3 | Detect and gracefully handle a repo path that has moved/been deleted (offer relocate or remove-from-list) | M |
| FR-1.4 | Stage/unstage at file, hunk, and individual line level | M |
| FR-1.5 | Commit with message, amend, and identity override per-repo | M |
| FR-1.6 | Branch create/switch/rename/delete | M |
| FR-1.7 | Stash create/apply/drop, with named stashes | M |
| FR-1.8 | Live status updates via filesystem watching (not polling), with debounced-polling fallback when inotify watch limits are exceeded or on network filesystems | M |
| FR-1.9 | Detect and safely recover from stale `.git/index.lock` left by a crashed session | M |
| FR-1.10 | Standard git safety net: reflog-based recovery accessible from the UI (view reflog, restore to a prior ref state) — no custom undo/redo stack in v1 | M |
| FR-1.11 | GitButler-style undo/redo of recent git operations | **M — see §3.11** (reclassified from v2; bounded to the rolling snapshot window, not literally unlimited) |
| FR-1.12 | Point Wrench at a directory that contains many git repositories: discover all of them with a bounded, user-initiated scan and bulk-register the results into the FR-1.2 registry (which stays authoritative — no passive background crawling), making them all switchable from the repo selector | S |
| FR-1.13 | Tag management: create (lightweight and annotated), delete, and push tags from the UI — the commit graph already renders tag ref-labels, but no operation surface exists in v1 | **D (v2)** |
| FR-1.14 | Batch operations over the FR-1.12 registry: fetch/pull across all registered repos or a user-defined workspace group, with a per-repo result summary | **D (v2)** |
| FR-1.15 | Git worktree management: list, add, remove, and prune worktrees of a repository | **D (v2)** |
| FR-1.16 | Shallow and partial clone options (`--depth`, `--filter=blob:none`) in the clone flow, with degraded-history states surfaced honestly in the UI | **D (v2)** |

### 3.2 History & Diff Visualization
| ID | Requirement | Priority |
|---|---|---|
| FR-2.1 | Diff view as the default tab when a repo is opened, showing working tree/staged changes (GitHub Desktop-style) | M |
| FR-2.2 | Commit graph as a separate tab: simple, colorful multi-branch visualization | M |
| FR-2.3 | Commit log with search/filter (author, message, date range, path) | S |
| FR-2.4 | Interactive drag-and-drop rebase within the commit graph | **D (v2)** |
| FR-2.5 | Blame view: per-line author/commit attribution surfaced in the UI (the v1 engine already ships `blame()` — v2 adds the presentation surface) | **D (v2)** |
| FR-2.6 | Pickaxe search (`git log -S`): search history by content change, complementing FR-2.3's message/author/date/path filters | **D (v2)** |

### 3.3 Merge & Conflict Resolution
| ID | Requirement | Priority |
|---|---|---|
| FR-3.1 | Merge branches with automatic fast-forward/3-way merge as applicable | M |
| FR-3.2 | Built-in visual 3-way merge conflict resolution tool (not dependent on external tools) | M |
| FR-3.3 | Rebase (non-interactive in v1) | M |
| FR-3.4 | Cherry-pick and revert commits via commit-graph context actions, routed through the FR-3.1/3.2 conflict machinery when they produce conflicts | **D (v2)** |
| FR-3.5 | Patch workflows: generate (`format-patch`) and apply (`am`/`apply`) patch series, supporting email-based collaboration like Forgejo/sr.ht communities use | **D (v2)** |

### 3.4 Remote Operations
| ID | Requirement | Priority |
|---|---|---|
| FR-4.1 | Push/pull/fetch over SSH and HTTPS | M |
| FR-4.2 | SSH agent authentication support (`SSH_AUTH_SOCK` forwarding under Flatpak) | M |
| FR-4.3 | Credential storage via freedesktop Secret Service (D-Bus), portable across GNOME Keyring and KWallet backends — the Linux/BSD implementation of the `CredentialBackend` interface (FR-11.1) | M |
| FR-4.4 | Multiple remote support per repo (origin, upstream, etc.) | S |
| FR-4.5 | Git-level credential resolution disambiguates by account, not just by host — required once multiple accounts share a host (e.g. two `github.com` accounts); SSH-remote identity is explicitly out of scope (see §7 Assumptions) | M |

### 3.5 Forge Integration
| ID | Requirement | Priority |
|---|---|---|
| FR-5.1 | Provider-agnostic, capability-based forge abstraction layer (not GitHub-shaped-by-default) — defines the shared interface every adapter implements | M |
| FR-5.2 | GitHub integration: PR create/view/review, issue linking, CI status | M |
| FR-5.3 | GitLab integration: MR create/view/review, issue linking, CI/pipeline status | M |
| FR-5.4 | Forgejo/Gitea integration (including self-hosted instances, custom URLs): PR create/view/review, issue linking, CI status | M |
| FR-5.5 | Bitbucket Cloud integration: PR create/view/review, issue linking, CI/pipeline status | M |
| FR-5.6 | Per-repo forge **instance** configuration — support multiple self-hosted instances of the same forge type simultaneously (e.g. two different self-hosted Forgejo servers) | M |
| FR-5.7 | Entry-points-based adapter registration: adapters are discovered as plugins (Python packaging entry points) against the FR-5.1 capability interface, not hardcoded into core | M |
| FR-5.8 | Multiple **accounts** on the same forge/instance (e.g. two separate github.com accounts) — each stored as an independent account row; each repo+remote explicitly assigned to exactly one | M |
| FR-5.9 | Account selection UX: when a repo's remote host matches more than one configured account, prompt once and remember the choice per repo+remote (`repo_forge_links`) rather than prompting repeatedly | M |
| FR-5.10 | In-app review threads: view and reply to PR/MR review comments, including inline diff comments (v1 ships review *actions* only — approve/request-changes/comment — with thread viewing deferred to Open-in-browser) | **D (v2)** |
| FR-5.11 | CI run details: inspect individual check runs/jobs for a PR/MR (names, states, deep links; log viewing itself stays in the browser in v2.0) | **D (v2)** |
| FR-5.12 | Forge notifications: aggregate review requests, mentions, and subscription updates into an in-app inbox per configured account (capability-gated — not every provider exposes this) | **D (v2)** |

### 3.6 Backend Extension Architecture
The forge layer's extensibility rests on two mechanisms, both required for v1 (they're how the four confirmed backends themselves are implemented, not a v2 add-on):
- **Capability-based interface**: adapters declare which capabilities they support (PR/MR, issues, CI status, etc.) rather than a monolithic interface every backend must fully implement — accommodates backends with partial API surfaces.
- **Entry-points plugin registration**: adapters are discovered via Python packaging entry points (`wrench.forge_adapters` group or similar), so third-party or community adapters can be installed as separate packages without modifying Wrench core.

See §7.1 for the roadmap of additional backends this architecture is designed to support post-v1.

### 3.7 Large Files & Submodules
| ID | Requirement | Priority |
|---|---|---|
| FR-6.1 | Git LFS: track, pull, push large files transparently | M |
| FR-6.2 | Submodules: init, update, add, view status per submodule | M |
| FR-6.3 | Git LFS file locking: lock/unlock binary assets to prevent concurrent-editing conflicts (capability-gated — lock support varies by server/version) | **D (v2)** |
| FR-6.4 | Image diff: side-by-side visual comparison for image files, pairing naturally with LFS-tracked binaries | **D (v2)** |

### 3.8 Identity & Profiles
| ID | Requirement | Priority |
|---|---|---|
| FR-7.1 | Multiple author identity profiles, assignable per repository | S |

### 3.9 Local Backup & Snapshot
| ID | Requirement | Priority |
|---|---|---|
| FR-8.1 | Create a point-in-time backup/snapshot of a local repository (full history + refs) to a user-chosen destination path | M |
| FR-8.2 | Support external/removable destinations (USB drive, mounted NAS share) as backup targets — no special-casing beyond standard filesystem path selection via the document portal (§5) | M |
| FR-8.3 | Restore/recover a repository from a snapshot into a new or existing local path | M |
| FR-8.4 | Manual, on-demand backup for v1 (user-triggered from the UI, not scheduled/automatic) | M |
| FR-8.5 | Scheduled/automatic backups (e.g. on interval, on commit) | **S (post-v1 refinement, not blocking)** |

**Scope note**: this is single-user disaster recovery — a compact snapshot of *your own* repo history to a second location you control, not a shared/live copy others write into. It has no merge or conflict logic because there's exactly one writer (you) and one reader (your own restore, later). This is kept separate from §7.2 below, which is a different problem with different risks.

### 3.10 Diagnostics & Support
| ID | Requirement | Priority |
|---|---|---|
| FR-9.1 | In-app "Report a bug" action: opens a pre-filled GitHub Issues page (app version, OS/desktop environment) in the default browser; no automatic submission — user reviews and submits manually | M |
| FR-9.2 | Local, rotating log file at a known, user-discoverable path, with enough context on errors to be useful when attached to a bug report | M |

### 3.11 Local Rolling Snapshots (Safety Net)
| ID | Requirement | Priority |
|---|---|---|
| FR-10.1 | Automatic rolling local snapshots of repository state, independent of the on-demand NAS/USB backup in §3.9 | M |
| FR-10.2 | Configurable snapshot triggers, any combination enabled simultaneously: on every commit; on a timer while the app is open (interval configurable); before risky operations (rebase, merge, reset, branch delete); manual on-demand. All four ship enabled by default; each is independently toggleable | M |
| FR-10.3 | Hybrid storage: tracked/staged/unstaged content captured git-natively (deduplicated against the repo's own object store, no separate copy); untracked files captured as a compressed archive with a user-configurable size cap (sensible default cap present) — files exceeding the cap have their path and size recorded but content not copied | M |
| FR-10.4 | Configurable retention: user-adjustable snapshot count (default mid-range of the originally-discussed 20–30) combined with an optional age-based cutoff; pruning applies whichever limit is reached first | M |
| FR-10.5 | Manually-created (named) snapshots are pruned only after every automatically-triggered snapshot for that repo is already gone, and are exempt from the age-based cutoff — a snapshot the user explicitly named isn't silently evicted by a burst of automatic ones | M |
| FR-10.6 | Browse and restore: view the snapshot list (timestamp, trigger type, label if manual) and restore a repo's working tree + index to a selected snapshot, without rewriting the branch's commit history | M |
| FR-10.7 | Snapshots are per-repository — no cross-repo sharing or dedup expected in v1 | M |

**Scope note**: this reclassifies FR-1.11 from its original v2 deferral. With FR-10.2's trigger set enabled, the underlying mechanism (state capture before/around mutating operations) is what unlimited undo/redo needs, so FR-1.11 is now delivered through this system in v1 — with "unlimited" bounded to FR-10.4's rolling window rather than true unlimited retention. This is distinct from §3.9: §3.9 is a manual, occasional, off-repo, full-history copy for disaster recovery; §3.11 is a frequent, automatic, in-repo, bounded rolling safety net for "undo my last few actions." They solve different problems and neither replaces the other.

### 3.12 Cross-Platform Portability Architecture
| ID | Requirement | Priority |
|---|---|---|
| FR-11.1 | All credential storage goes through a `CredentialBackend` interface. v1 ships two concrete implementations, not one — `FlatpakSecretServiceBackend` and `AppImageSecretServiceBackend` — sharing identical D-Bus Secret Service logic (FR-4.3) and differing only in the remediation text shown when no provider is reachable, since the fix differs by packaging context (a missing Flatpak permission vs. no keyring daemon running at all). The interface itself must not leak Linux-specific types or assumptions into calling code | M |
| FR-11.2 | All application data/config/cache paths resolve through a single platform-neutral path-resolution layer, never a hardcoded XDG path inline — v1 only exercises the Linux resolution behavior, but every call site goes through this layer from day one | M |
| FR-11.3 | SSH agent socket access is isolated behind one narrow function/module — v1's implementation reads `$SSH_AUTH_SOCK` directly, but no other file in the codebase reads that environment variable | M |
| FR-11.4 | No KDE-Frameworks-specific APIs (KConfig, KXmlGui, KIO, or equivalent) anywhere in the codebase, even on Linux — plain PySide6/Qt widgets only, styled to look native-enough on Plasma without a framework dependency a future port would have to unwind | M |
| FR-11.5 | Packaging configuration (`[tool.briefcase]`) declares the shape for future Windows/macOS targets (present but inactive) so a future port's packaging step is "enable and test," not "design from scratch" | S |

**Scope note**: none of FR-11.1–11.5 ships a second platform — v1 remains Linux-only end to end, and nothing here is scheduled work beyond v1 itself. What they buy is that a future port (see §7.3) is additive behind existing seams rather than a rewrite of code that was never designed to be portable. This reverses an earlier decision: KDE Frameworks 6 (KF6) was originally committed for deeper Plasma integration (§2.4, Assumptions Log #3, now revised) — superseded here in favor of portability. The implementation plan confirms this reversal is cheap: no phase ever wires in KConfig/KXmlGui/KIO (settings already route through SQLite, not KDE config files), so this is a documentation correction plus a few narrow interface additions, not a redesign.

### 3.13 Extensibility & Automation
| ID | Requirement | Priority |
|---|---|---|
| FR-12.1 | Custom user actions: user-defined shell commands runnable on the selected repo/commit/file, surfaced in context menus (`WRENCH_REPO_PATH`/`WRENCH_SELECTED_SHA`/`WRENCH_SELECTED_FILE` environment contract; user-authored, no sandboxing promised) | **D (v2)** |

---

## 4. Non-Functional Requirements

| Category | Requirement |
|---|---|
| **Performance** | Status refresh on typical repos (<10k files) under 200ms; commit graph renders usably on repos with 100k+ commits (virtualized rendering, not full in-memory graph layout) |
| **Security** | No credentials stored in plaintext or app-local files; all secrets via Secret Service. Sandboxed permissions kept minimal (no `--filesystem=home`) |
| **Privacy** | No telemetry, analytics, or automated crash reporting by default; no Wrench-specific account ever required for local git functionality — forge accounts are opt-in and only needed when the user connects a specific forge. Error/crash reporting is user-initiated only, via GitHub Issues (see Diagnostics row below) — nothing is ever sent automatically. |
| **Diagnostics** | Maintain a local, rotating log file at a known path (`$XDG_STATE_HOME/wrench/wrench.log` or Flatpak-sandboxed equivalent) capturing errors and key operations with enough context to be useful in a bug report. Provide an in-app "Report a bug" action that opens the GitHub Issues page for the project (pre-filled with app version + OS/desktop info the user can review and edit before submitting — never auto-submitted). |
| **Accessibility** | Full keyboard navigation through every dialog and the main window (tab order, Enter/Escape behavior); screen-reader labels (accessible names) on icon-only buttons; verified via a keyboard-only walkthrough of every M-priority flow before v1 ships |
| **Portability** | Fully functional on both KDE Plasma and GNOME sessions when run as Flatpak. Architected per §3.12 so a future non-Linux port is additive, not a rewrite — not a v1 deliverable itself |
| **Reliability** | No data loss on app crash — git working tree/index integrity preserved; stale locks self-heal. Rolling snapshots (§3.11) are bounded by FR-10.4's retention policy, so disk usage from this feature has a predictable ceiling rather than growing unboundedly |
| **Licensing compliance** | All bundled dependencies verified compatible with AGPL-3.0 distribution (Aug 2026 check): PySide6 (LGPL — chosen for this reason, §2.4), pygit2/libgit2 (GPL-2.0-with-linking-exception — the exception exists specifically to permit linking from software under any license), httpx (BSD-3-Clause), watchdog (Apache-2.0), secretstorage (BSD). No GPL-2.0-only dependency without a linking exception is used. |
| **Localization** | UI strings wrapped for translation (Qt Linguist `tr()`) from initial implementation. English-only ships in v1; machine translation may be used post-v1 to bootstrap additional languages ahead of community translations |

---

## 5. External Interface Requirements

- **Local filesystem**: repo folders accessed via XDG Desktop Portal file chooser (folder-select mode) under Flatpak, granting persistent per-folder access — not broad home directory access.
- **GitHub REST/GraphQL API** — PR, issue, CI status data.
- **GitLab REST API** — MR, issue, pipeline data.
- **Forgejo/Gitea API** (Gitea-compatible, distinct from GitHub/GitLab shapes) — PR, issue, Actions status data.
- **Bitbucket Cloud REST API v2.0** — PR, issue, pipeline status data (FR-5.5).
- **Freedesktop Secret Service** (D-Bus `org.freedesktop.secrets`) — credential storage; the Linux/BSD `CredentialBackend` implementation (FR-11.1). Lookup keys now disambiguate by account (host **and** path), not host alone, to support FR-5.8/FR-4.5 multi-account — see implementation-plan.md §5 Phase 3 for the exact mechanism (`credential.useHttpPath`).
- **SSH agent socket** (`$SSH_AUTH_SOCK`) — via Flatpak `--socket=ssh-auth`.
- **libgit2** (via `pygit2`) and system **git** binary (subprocess, for push/rebase/merge edge cases and credential negotiation).
- **GitHub Issues** (project's own tracker) — opened via the default browser for user-initiated bug reports (FR-9.1); not an API integration, just a deep link, and not related to the FR-5.2 GitHub forge adapter used for users' own repos.

---

## 6. Out of Scope for v1 (confirmed deferrals)

- Interactive drag-and-drop rebase in the commit graph → v2
- OAuth-based login for forge accounts (v1 is token/PAT-only across all providers and all accounts) → v2, if there's demand
- The full v2 feature set — FR-1.13 (tag management), FR-1.14 (batch operations/workspaces), FR-1.15 (worktree management), FR-1.16 (shallow/partial clone), FR-2.5 (blame view), FR-2.6 (pickaxe search), FR-3.4 (cherry-pick/revert), FR-3.5 (patch workflows), FR-5.10 (review threads/inline comments), FR-5.11 (CI run details), FR-5.12 (forge notifications), FR-6.3 (LFS locking), FR-6.4 (image diff), FR-12.1 (custom actions) → v2; plus FR-8.5 (scheduled/automatic backups — S-priority in v1 per §3.9, committed to v2 as its refinement phase) → v2; all planned in `dev/planning/v2-implementation-plan.md`

---

## 6.1 Undecided / Unresolved Items (not committed deferrals)

Distinct from §6 above: these aren't scheduled for v2 either — they have no committed direction yet. Listed separately so "not in v1" doesn't get read as "planned for v2."

- **GPG commit signing UI** — still unresolved *whether/when* this ships; not blocking v1 since git CLI signing still works standalone via existing host config. The permission *delivery mechanism*, if/when it does ship, is now decided (implementation-plan.md §6.1): not requested in the default Flatpak manifest — documented as a user-triggered `flatpak override --socket=gpg-agent` step instead, the same pattern other Flathub apps use for edge-case permissions.
- **Windows/macOS support** — the *architecture* is now decided (§3.12: portable credential/paths/SSH-agent seams, no KDE-Frameworks dependency) so a future port is additive rather than a rewrite, but the ports themselves remain undecided, unscheduled, and not committed to either platform — see §7.3 for the distant-future roadmap and the macOS-vs-Windows tradeoff analysis.
- **Multi-user collaboration via shared local/NAS remotes** — see §7.2 for the full unresolved discussion; not part of v1 scope, no priority or horizon assigned.
- **SSH agent compatibility for GPG-as-agent and hardware-key (e.g. YubiKey) setups** — Flatpak's `--socket=ssh-auth` forwards the SSH-agent *protocol* regardless of what's listening on the other end, so this is likely less broken than initially assumed; the actual open risk is narrower (environment-variable propagation at app launch time) but hasn't been empirically validated. Tracked as a beta-cycle validation task, not a v1 blocker — plain `ssh-agent` is the only case guaranteed to work today.
- **Self-hosted Forgejo/Gitea: TLS and version handling** — two sub-decisions still needed before Phase 4's Forgejo adapter work closes out: (1) whether v1 supports only system-trusted TLS certificates, or also builds a self-signed-cert trust flow (fingerprint pinning, etc.); (2) what minimum Forgejo/Gitea API version is officially supported, rather than implicitly promising compatibility with any version ever released. A well-configured public instance (e.g. Codeberg) is expected to work regardless of how these resolve — the risk is concentrated in ad-hoc self-hosted setups (self-signed certs, unusual ports/path prefixes, older software versions).

---

## 7. Assumptions & Decisions Log (for your review)

| # | Item | Status | Chosen | Why |
|---|---|---|---|---|
| 1 | Source hosting | ✅ Confirmed | GitHub | Cost — free public repo hosting; migration later stays low-friction since the forge layer is provider-agnostic by design |
| 2 | App ID | ✅ Confirmed | `io.github.uzair.Wrench` | Flathub convention for GitHub-hosted apps without a custom domain (note: `com.github.` is reserved for GitHub's own apps) |
| 3 | Min Qt version / KDE Frameworks | ✅ Confirmed (revised) | Qt 6.6+ (PySide6), **no KDE Frameworks (KF6) dependency** — plain Qt widgets only | Originally committed to KF6 for deeper Plasma integration; revised in favor of cross-platform portability (§3.12) once a future Windows/macOS port was raised — checked against the concrete plan and confirmed cheap to change, since no phase ever actually wired in KConfig/KXmlGui/KIO |
| 4 | i18n scope | ✅ Confirmed | Structure now, English-only v1, machine translation considered post-v1 | Low cost to structure now; machine translation is a cheap way to bootstrap coverage before community translations arrive |
| 5 | GPG signing | Open | Not blocking v1 | Sandboxing support is unresolved upstream |
| 6 | v1 forge backend set | ✅ Confirmed | GitHub, GitLab, Forgejo/Gitea, Bitbucket Cloud | Covers the primary and self-hosted forges the target user classes actually use; built on capability-based + entry-points architecture so this set isn't a ceiling |
| 7 | Dependency license compatibility with AGPL-3.0 | ✅ Confirmed (Aug 2026, previously asserted but unverified — closed during a documentation audit) | PySide6 (LGPL), pygit2/libgit2 (GPL-2.0-with-linking-exception), httpx (BSD-3), watchdog (Apache-2.0), secretstorage (BSD) — all compatible | See §4 Licensing compliance row for detail |
| 8 | Telemetry/privacy default | ✅ Confirmed | No telemetry, no automated crash reporting, no Wrench account ever required. Crash/error reporting is user-initiated only, via GitHub Issues — not an automated pipeline. | Explicitly confirmed — the app maintains a local log file and offers an in-app link to open a pre-filled GitHub issue, but never transmits anything without the user actively choosing to file a report |
| 9 | Multi-account auth method | ✅ Confirmed | Personal access tokens only, no OAuth in v1 | Matches the existing Bitbucket precedent; PATs are also better UX for multi-account than OAuth, which has browser-session disambiguation problems when logging into a second account on the same provider |
| 10 | Multi-account SSH scope | ✅ Confirmed | Out of v1 scope — user manages their own SSH config/keys for SSH remotes | Consistent with the already-minimal "plain ssh-agent only" SSH scope; multi-account governs forge-API calls and HTTPS git auth only |
| 11 | Snapshot storage mechanism | ✅ Confirmed | Hybrid — tracked content via `git stash create` (git-native, deduplicated, no branch/HEAD mutation), untracked files via a compressed archive with a configurable size cap | Balances fidelity against the "lightweight" requirement, without inventing a competing object-storage format for tracked content git already handles well |
| 12 | Snapshot triggers | ✅ Confirmed | All four (on commit, on timer, before risky ops, manual), independently toggleable, shipped enabled by default | User explicitly requested full configurability rather than a single fixed trigger |
| 13 | Snapshot retention | ✅ Confirmed | User-configurable count (default mid-range of 20–30) plus an optional age cutoff; manual snapshots pruned last and exempt from the age cutoff | Protects deliberately-named checkpoints from being silently evicted by high-frequency automatic triggers |
| 14 | FR-1.11 (undo/redo) status | ✅ Confirmed | Reclassified from D (v2) to M (v1), delivered via §3.11's snapshot system, bounded rather than unlimited | The chosen trigger set (esp. "before risky operations" + "on every commit") already builds the infrastructure FR-1.11 needs — leaving the feature itself deferred would waste that work |
| 15 | Cross-platform architecture scope | ✅ Confirmed | Full treatment now (§3.12 + §7.3): mandatory v1 interfaces (`CredentialBackend`, path resolution, isolated SSH-agent access, no KDE-Frameworks APIs), actual Windows/macOS ports deferred indefinitely (V5/V6, distant future, unscheduled) | Requested explicitly — "architecture should be there" even though the platforms themselves are far out; cheap to do now, expensive to retrofit once KDE-Frameworks APIs or hardcoded XDG paths are load-bearing throughout the codebase |
| 16 | Which platform is technically closer | Informational, not a commitment | macOS is architecturally closer (POSIX subprocess/path behavior, near-identical SSH-agent model to Linux); Windows has no equivalent to macOS's mandatory $99/year Apple Developer Program notarization cost | Recorded for whenever this is actually revisited — deliberately not used to prioritize one platform's abstraction over the other in §3.12's interfaces |
| 17 | Credential backend split (v1, within Linux) | ✅ Confirmed (revised) | Two concrete `CredentialBackend` implementations, not one — `FlatpakSecretServiceBackend`/`AppImageSecretServiceBackend` — sharing identical D-Bus logic, differing only in unavailable-provider remediation text | Corrects a gap in the first version of FR-11.1: `sys.platform` alone can't distinguish Flatpak from AppImage from a bare `pip install` (all report the same value), so the original single-backend factory couldn't actually give context-appropriate error guidance. Detection now uses `FLATPAK_ID`/`.flatpak-info` and the `APPIMAGE` env var instead |
| 18 | v2 feature set | ✅ Confirmed | FR-1.13–1.16, FR-2.5–2.6, FR-3.4–3.5, FR-5.10–5.12, FR-6.3–6.4, FR-12.1 assigned D (v2), enumerated in §6, planned in `dev/planning/v2-implementation-plan.md` | Post-v1-scope review surfaced gaps users would perceive as incompleteness rather than novelty (cherry-pick/revert, tag management, blame view lead the set because their v1 engine machinery already exists); everything else is deepening or power-user surface |
| 19 | FR-8.5 (scheduled backups) v2 home | ✅ Confirmed | S-priority in v1 per §3.9, committed to v2 (VP-14 — Scheduled Backups) | It was the last marked deferral bucket with no planned home; the §3.9 backup engine and FR-10.2's timer machinery make it cheap to schedule honestly, and 'scheduled backups' deferred forever would read as a gap rather than as scope discipline |

### 7.1 Backend Extension Roadmap

The capability-based, entry-points adapter architecture (§3.6) means backends beyond the confirmed v1 set are an adapter-authoring exercise, not a core redesign. This roadmap is aspirational and unprioritized against the v1 milestone — nothing here blocks v1 ship.

| Backend | Target horizon | Notes |
|---|---|---|
| **SourceForge** | v2–v3 (planned) | Legacy but still-active hosting for a long tail of older/established FOSS projects; moved up from purely speculative given the userbase overlap with Wrench's FOSS-first audience. API shape TBD — SourceForge's Allura platform has its own REST API, distinct from GitHub/GitLab/Gitea-family shapes. |
| **Other self-hosted/enterprise forges** (e.g. Gerrit, generic Git-over-SSH-only remotes without forge features) | Unscheduled | Would likely map to a reduced-capability adapter (no PR/issue/CI surface) rather than a full adapter. |
| **Radicle** | Optional / community-contributed, no committed horizon | Fundamentally different trust/discovery model (peer-to-peer, no central forge server) rather than a REST-API-backed forge — a different integration shape than the capability interface was designed around, so it's deprioritized well below SourceForge and treated as something the plugin architecture *could* accommodate via a community adapter rather than a roadmap commitment from the core team. |

### 7.2 Unresolved: Multi-User Collaboration via Local/NAS Remotes (future, not v1)

Raised during requirements discussion, deliberately **not** scoped into v1 — recorded here so it isn't lost, and so a future revision starts from the shape of the idea already discussed rather than from scratch.

**The idea**: beyond single-user backup (§3.9), allow multiple people to collaborate on a repo via a shared local-network location (e.g. a NAS) instead of a hosted forge — useful for small teams/households without forge infrastructure.

**Why it's harder than it first looks, and why it's deferred rather than folded into §3.9**:
- Git is already distributed — every collaborator's clone has its own independent `main`. The naive risk isn't "how do we merge two mains," it's that naive designs (e.g. multiple people writing into one shared live working copy) risk lock contention and corruption. The safe pattern is a **bare repository** as the shared point, with each collaborator pushing/fetching from their own separate working copy — effectively a minimal self-hosted forge.
- Treating each contributor's history as a separate, namespaced remote-tracking branch (e.g. `alice/main`, `bob/main`) is exactly what git already does by design when you add someone else's copy as a named remote — this isn't new mechanism, it's UI/UX work to present it well.
- Namespacing prevents one person's push from silently overwriting another's history, but it does **not** eliminate merge conflicts on actual content — two people editing the same lines still produce a real conflict that must go through standard merge/conflict-resolution tooling (FR-3.1–3.3) when their branches are merged. Any future design must not imply "conflict-free."
- Open questions for a future revision: does this reuse FR-4.4's multi-remote support with a `file://`/mounted-share remote type, or need dedicated UI framing (e.g. a "shared workspace" concept layered on top of remotes)? How is presence/discovery of collaborators' branches surfaced? What's the failure mode if the NAS is offline mid-operation?

**Status**: unresolved, no priority assigned, not part of any current phase in the implementation plan. Revisit only after v1 ships and only if there's real demand — do not let this scope-creep into §3.9's backup work, which is deliberately kept simple (single writer, single reader, no merge logic).

### 7.3 Multi-Platform Roadmap (V5/V6, Distant Future)

Raised during requirements discussion as an explicit "the architecture should be there, even though the platforms are far out" request. Not scheduled, not prioritized against v1 or v2, recorded so a future revision starts from real analysis instead of a blank page. The mandatory groundwork this depends on is §3.12 (FR-11.1–11.5) — already in v1, not deferred.

| Platform | Target horizon | Technical distance from v1 | Notes |
|---|---|---|---|
| macOS | Unscheduled (V5/V6) | Closer — POSIX-based; subprocess, path, and lock-file behavior are near-identical to Linux; SSH agent access uses the same Unix-socket model, often Keychain-integrated already | Needs a Keychain-backed `CredentialBackend`. Distribution requires Apple Developer Program enrollment — **$99/year, mandatory** for notarization, no free/OSS exemption. A real recurring cost, not just engineering time. |
| Windows | Unscheduled (V5/V6) | Farther — different shell-quoting/subprocess conventions, different default line endings, SSH agent uses a named pipe rather than a Unix socket (different IPC code, not a path change) | Needs a Credential-Manager-backed `CredentialBackend`. No equivalent mandatory paid distribution gate — SmartScreen reputation is soft friction, not a hard cost. |

**Which one first?** Deliberately not decided. It's a real trade between less code (macOS) and less money (Windows) — see Assumptions Log #16. §3.12's interfaces don't favor either, by design.

**Packaging is already a non-issue**: Briefcase (adopted for AppImage, implementation-plan.md §6.3) natively supports Windows (MSI) and macOS (DMG/pkg) as build targets — enabling a second platform there is a config change (FR-11.5), not a new toolchain to adopt.

**Explicitly not decided, deferred to whenever this is actually picked up**: platform UI conventions (e.g. macOS menu bar placement), whether Flatpak/AppImage-specific assumptions elsewhere (sandboxed portal-based file access, in particular) need a non-sandboxed equivalent path on Windows/macOS, and code-signing/notarization mechanics beyond the cost noted above.
