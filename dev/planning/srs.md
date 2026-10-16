# **Software Requirements Specification — Wrench**

**Version:** 0.6 (v2 Complete Specification: Diff Virtualization, Multi-Hosting Mirror DAG, 5-Stage Mirror Resolution, Phased Pipeline & Zero-Shortcut Security) **Status:** Living document, updated across multiple requirements/design sessions and expanded for v2 with community-validated feature requests from peer Git clients, a strict **Total User Configurability & Zero-Impact Feature Toggle** mandate, Delta-Only Settings Undo/Redo, and rich cross-component UI/UX enhancements.  
**Companion documents — the SRS is the what/why; it does not stand alone:**

> * [implementation-plan.md](https://github.com/uzair777-dev/Wrench/blob/master/dev/planning/implementation-plan.md) — the how for v1: every M/S FR row below is implemented by exactly one phase in its §5 (traceable through §12's master checklist).  
> * [ui-planning.md](https://github.com/uzair777-dev/Wrench/blob/master/dev/planning/ui-planning.md) — the authoritative UI/UX and widget optimization specification (§1–§8). Every UI surface, lazy-loading rule (OPT-1), debounced auto-save rule (OPT-2), delta-only settings undo rule (OPT-3), and component layout lives there. **Coding models MUST open the cited ui-planning.md §x.y section before implementing any requirement.**  
> * [v2-implementation-plan.md](https://github.com/uzair777-dev/Wrench/blob/master/dev/planning/v2-implementation-plan.md) — the committed home of every **D (v2)** row (phases VP-0..VP-25), written as a deterministic, zero-ambiguity execution spec with per-phase optimization checklists.  
> * [../ARCHITECTURE.md](https://github.com/uzair777-dev/Wrench/blob/master/ARCHITECTURE.md) (repo root) — the as-built description of what exists today; when it and this SRS disagree, the code wins and the SRS gets reconciled.

Documents reference each other by section number (§x.y) — those references are normative links: open the referenced section when tracing anything.

## **1\. Introduction**

### **1.1 Purpose**

[Wrench](https://github.com/uzair777-dev/Wrench) is a free and open-source, native Linux desktop Git client targeting feature parity with GitHub Desktop (simplicity, PR-centric workflow), GitKraken (visual branch graph, forge integrations), Sublime Merge (speed, line history, worktrees), and Lazygit/GitButler (stacked branches, interactive bisect, granular staging), built with Qt/PySide6. It targets KDE Plasma users first, and works equally well on GNOME and other desktop environments via Flatpak.

### **1.2 Scope & Core Product Philosophy: We Do Not Forget the User**

Wrench manages local Git repositories end-to-end: repository creation/cloning, staging and committing, branching and merging, remote synchronization over SSH/HTTPS, and forge-native collaboration (pull/merge requests, issues, CI status) across GitHub, GitLab, Forgejo/Gitea, Bitbucket Cloud, and SourceForge (v2).  
**Total User Sovereignty, Mistake-Proof Undo & Zero-Impact Feature Toggleability:** Every single part of Wrench — whether already implemented in v1 or scheduled for v2 and beyond — **must be tweakable and toggleable from the Settings / Preferences menu (ui-planning.md §6.11)**:

> 1. **UI Unmounting / Hiding:** When a feature is disabled in Settings, its tabs, sidebar sections, toolbar buttons, context-menu entries, gutter overlays, and status badges are immediately hidden (setVisible(False) or unmounted) without leaving dead space or requiring an application restart.  
> 2. **Backend Short-Circuiting (Zero Overhead):** When a feature is disabled, its background workers, timers, inotify watchers, subprocess calls, pygit2 computations, and network httpx requests are completely bypassed at the core.engine / forge.registry entry point before any CPU, I/O, or memory cost is incurred.  
> 3. **Auto-Save with Delta-Only Settings Undo/Redo (FR-8.12, ui-planning.md §5.5 OPT-2/OPT-3):** Settings auto-save with a 150ms debounce and record **only the changed key delta (key, old\_val, new\_val)** into a bounded ring buffer (settings\_undo\_log), giving users instant Ctrl+Z / Ctrl+Y and out-of-order history revert inside Settings if they make a mistake.

### **1.3 Definitions**

| Term | Meaning |
| :---- | :---- |
| **Forge** | A Git hosting platform (GitHub, GitLab, Forgejo/Gitea, Bitbucket, SourceForge) |
| **Settings Registry** | Centralized typed configuration, feature-gate, and delta-undo manager (src/wrench/storage/settings\_registry.py) |
| **Delta Settings Snapshot** | A lightweight record storing only (key, old\_value\_json, new\_value\_json, repo\_path) whenever a setting changes, enabling instant Ctrl+Z undo without copying the full settings table |
| **Zero-Impact Disable** | Guarantee that disabling a feature in Settings both hides its UI surfaces and short-circuits its background threads/queries so it consumes zero CPU/network/RAM |
| **Stacked Branches** | A chain of dependent feature branches where rebasing or amending an earlier branch automatically updates downstream branches via git rebase \--update-refs |

### **1.4 Confirmed Decisions**

> * ✅ **Source hosting platform**: **GitHub** ([uzair777-dev/Wrench](hhtps://github.com/uzair777-dev/Wrench)).  
> * ✅ **v1 forge backend set**: **GitHub, GitLab, Forgejo/Gitea, and Bitbucket Cloud** (plus **SourceForge** in v2 VP-9).  
> * ✅ **v2 Git CLI floor remains Git 2.38+**: Natively supports git rebase \--update-refs, git stash push \--staged, and gpg.format \= ssh.  
> * ✅ **Universal Settings, Lazy UI & Delta-Undo Mandate (DEC-5, DEC-6)**: Every v1/v2 feature and UI enhancement is registered in SettingsRegistry, lazy-loaded on first view (OPT-1), auto-saved with 150ms debounce (OPT-2), and protected by Delta-Only Settings Undo (OPT-3).

## **2\. Overall Description**

### **2.1 User Personas**

> * **The Visual Developer (Primary):** Wants a clean graph, clear staging, visual conflict resolution, CLI command previews, and 1-click Undo toasts.  
> * **The Minimalist / Classic Linux User:** Wants a fast local Git GUI and uses the 1-click **"Minimalist Local-Only Mode"** preset in Settings to turn off forge polling, CI badges, system tray, and advanced panels with zero background overhead.  
> * **The Linux Power User & Monorepo Contributor:** Demands \<250MB RSS, 60fps scrolling on 100k+ commits, worktrees, stacked PRs, interactive bisect, SSH signing, Vim keys, and a Ctrl+K Command Palette.

### **2.2 Operating Environment**

> * Linux (x86\_64, aarch64), Flatpak (primary), AppImage (secondary), Arch AUR / Debian .deb / Fedora RPM (VP-15).  
> * Python 3.11+, PySide6 (Qt 6.8+), pygit2, system git CLI (2.38+), httpx, secretstorage, watchdog, SQLite (WAL mode).

### **2.3 User Interfaces (ui-planning.md §1–§6)**

> * Native Qt 6 GUI styled dynamically via system palette/KStyle.  
> * Searchable, lazy-loaded **Modular Settings Center (Ctrl+,, ui-planning.md §6.11)** with Delta-Only Undo/Redo (Ctrl+Z), "Show Only Modified" filter, Live Mini-Preview cards, ★ Quick-Settings pinning, and ⚙ contextual jump icons on every panel header.

## **3\. Functional Requirements**

### **3.1 Repository Lifecycle Management (FR-1.x)**

| ID | Priority | Requirement Description | UI Spec & Settings Toggle / Tweaks |
| :---- | :---- | :---- | :---- |
| **FR-1.1–1.12** | **M / S** | Core repository lifecycle: Clone, Init, Open, Recent Repos, Multi-Repo Discovery, Pre-Op Safety Stash, Bare Repo guard. | ui-planning.md §1–§2, §6.2, §6.10. Keys: repo.recent\_max\_count, repo.auto\_discovery.enabled, safety.pre\_op\_snapshot.enabled (VP-0). |
| **FR-1.13** | **D (v2)** | **Git Worktrees UI & Lifecycle Manager:** Create, list, open in tab, lock/unlock, and prune linked worktrees (git worktree), showing full path on hover ([GitHub Desktop \#19307](https://github.com/desktop/desktop/issues/19307), [Sublime Merge \#757](https://github.com/sublimehq/sublime_merge/issues/757)). | ui-planning.md §6.17. Key: worktrees.enabled (VP-3). |
| **FR-1.14** | **D (v2)** | **Git Submodules Management:** Initialize, recursive update, sync, and dirty-submodule sidebar badges. | ui-planning.md §6.3. Keys: submodules.enabled, submodules.auto\_recurse\_on\_pull, submodules.dirty\_badge.enabled (VP-4). |
| **FR-1.15** | **D (v2)** | **Workspace Session Persistence:** Save/restore named multi-tab repo & worktree sessions ([Sublime Merge \#789](https://github.com/sublimehq/sublime_merge/issues/789)). | ui-planning.md §1.2. Keys: workspace.restore\_session\_on\_startup, workspace.named\_sessions.enabled (VP-3). |
| **FR-1.16** | **D (v2)** | **Background Git Maintenance Runner:** Scheduled/manual git maintenance run (commit-graph write, prefetch, gc). | ui-planning.md §1.2. Keys: maintenance.auto\_commit\_graph.enabled, maintenance.auto\_run.enabled (VP-14/VP-16). |
| **FR-1.17** | **D (v2)** | **Worktree Path Templates, Cross-Worktree Cherry-Pick & Bare-Hub Mode:** Configurable path templates ([GitHub Desktop \#22308](https://github.com/desktop/desktop/issues/22308)), cross-worktree cherry-pick ([\#22714](https://github.com/desktop/desktop/issues/22714)), and Bare Repo Worktree Hub ([Lazygit \#3100](https://github.com/jesseduffield/lazygit/issues/3100), [\#5469](https://github.com/jesseduffield/lazygit/issues/5469)). | ui-planning.md §6.17. Keys: worktrees.path\_template, worktrees.cross\_cherry\_pick.enabled, worktrees.bare\_hub.enabled (VP-3). |
| **FR-1.18** | **D (v2)** | **Partial Clone (--filter=blob:none) & Sparse-Checkout Directory Picker:** Blobless/treeless clone options and cone-mode folder checklist ([GitHub Desktop \#17901](https://github.com/desktop/desktop/issues/17901)). | ui-planning.md §6.2, §6.20. Keys: monorepo.sparse\_checkout\_ui.enabled, clone.default\_filter\_mode (VP-16). |

### **3.2 Staging, Hooks, Signing & Commit Workflow (FR-2.x)**

| ID | Priority | Requirement Description | UI Spec & Settings Toggle / Tweaks |
| :---- | :---- | :---- | :---- |
| **FR-2.1–2.3** | **M** | File, hunk, and line staging/unstaging, commit creation, and commit amending. | ui-planning.md §3.1. Keys: staging.line\_staging.enabled, commit.subject\_max\_length\_guide, commit.body\_wrap\_column (VP-0). |
| **FR-2.4** | **D (v2)** | **Undo Last Commit, Global Action Undo Toast & Visual Reset Picker:** 1-click Undo Toast (Ctrl+Z), visual \--soft/--mixed/--hard file-impact preview ([HN Reset UX \#45878578](https://news.ycombinator.com/item?id%3D45878578), [GitHub Desktop \#17901](https://github.com/desktop/desktop/issues/17901)), and CLI dry-run preview bar. | ui-planning.md §1.4, §5.3, §6.15. Keys: ui.undo\_toast.enabled, reset.show\_visual\_preview\_dialog, ui.show\_cli\_preview\_in\_dialogs (VP-0, VP-1). |
| **FR-2.5–2.6** | **D (v2)** | **Commit Templates & Co-Author Autocomplete UI:** Load commit.template and provide Co-authored-by: contributor pill completer. | ui-planning.md §3.1. Keys: commit.templates.enabled, commit.coauthors\_ui.enabled (VP-5). |
| **FR-2.7–2.8** | **D (v2)** | **Git Hook Runner, Login-Shell PATH Hydration & \--no-verify Bypass:** Hydrate user shell PATH (nvm, pyenv, mise), support core.hooksPath, stream output into a 5,000-line ring-buffer drawer (OPT-5), and provide \--no-verify controls ([GitHub Desktop \#11802](https://github.com/desktop/desktop/issues/11802), [\#17385](https://github.com/desktop/desktop/issues/17385), [\#20756](https://github.com/desktop/desktop/issues/20756), [\#21317](https://github.com/desktop/desktop/issues/21317)). | ui-planning.md §3.1. Keys: hooks.enabled, hooks.hydrate\_login\_shell\_path, hooks.stream\_output\_drawer.enabled, hooks.show\_bypass\_checkbox\_in\_ui (VP-17). |
| **FR-2.9–2.10** | **D (v2)** | **GPG & SSH Commit/Tag Signing (gpg.format \= ssh) \+ Askpass & Graph Badges:** Sign commits/tags, prompt for passphrases via Qt modal ([GitHub Desktop \#15302](https://github.com/desktop/desktop/issues/15302), [\#16569](https://github.com/desktop/desktop/issues/16569), [\#17309](https://github.com/desktop/desktop/issues/17309)), and batch-verify \[✓ Verified\] badges on CommitGraphWidget. | ui-planning.md §4.2, §6.5. Keys: signing.enabled, signing.format, signing.gui\_askpass\_fallback.enabled, signing.verify\_badges\_in\_graph.enabled (VP-18). |

### **3.3 Branch, Stacked Workflows & History Graph (FR-3.x)**

| ID | Priority | Requirement Description | UI Spec & Settings Toggle / Tweaks |
| :---- | :---- | :---- | :---- |
| **FR-3.1–3.3** | **M** | Visual DAG commit graph, branch ops, merge, rebase, plus **Hover X-Ray Commit/Branch Preview Cards** in v2. | ui-planning.md §4.2. Keys: graph.show\_lanes, graph.lane\_width\_px, graph.row\_height\_px, graph.hover\_xray\_card.enabled (VP-0, VP-18). |
| **FR-3.4** | **D (v2)** | **Multi-Commit Cherry-Pick & Revert:** Multi-row selection cherry-pick/revert with \--no-commit and sequencer conflict banner ([GitHub Desktop \#3579](https://github.com/desktop/desktop/issues/3579)). | ui-planning.md §4.1. Keys: graph.cherry\_pick\_revert.enabled, graph.cherry\_pick\_revert.default\_no\_commit (VP-1). |
| **FR-3.5** | **D (v2)** | **Visual Interactive Rebase & Drag-to-Reorder:** Drag-and-drop git rebase \-i modal with inline message editor. | ui-planning.md §6.16. Keys: rebase.interactive\_ui.enabled, rebase.autostash, rebase.autosquash (VP-2). |
| **FR-3.6** | **D (v2)** | **Interactive git bisect Wizard & Automated bisect run:** Visual bisect overlay on CommitGraphWidget, step counter, and automated script runner ([Lazygit \#1542](https://github.com/jesseduffield/lazygit/issues/1542), [\#5575](https://github.com/jesseduffield/lazygit/issues/5575)). | ui-planning.md §6.21. Keys: bisect.ui.enabled, bisect.auto\_snapshot\_before\_start (VP-19). |
| **FR-3.7–3.8** | **D (v2)** | **Stacked Branches (--update-refs) & Hunk-to-Commit Routing:** Cascade rebases across stacked branches ([Lazygit \#2527](https://github.com/jesseduffield/lazygit/issues/2527), [\#4817](https://github.com/jesseduffield/lazygit/issues/4817), [\#4852](https://github.com/jesseduffield/lazygit/issues/4852)) and route selected diff hunks into any earlier commit via \--fixup \+ \--autosquash ([GitButler \#2513](https://github.com/gitbutlerapp/gitbutler/issues/2513)). | ui-planning.md §6.22. Keys: stacks.enabled, stacks.auto\_update\_refs\_on\_amend, stacks.hunk\_routing\_ui.enabled (VP-20). |
| **FR-3.9** | **D (v2)** | **Patch-Series Export & Mailbox Apply (format-patch / am):** Export .patch series and apply mailboxes with \--3way. | ui-planning.md §1.2. Keys: patches.ui.enabled, patches.am\_three\_way\_by\_default (VP-23). |

### **3.4–3.7 Remotes, LFS, Multi-Forge, Plugins & File Watcher (FR-4.x–FR-7.x)**

> * **FR-4.5 (LFS Lock & Pattern Manager — VP-12, ui-planning.md §6.3):** Controlled by lfs.enabled ([Sublime Merge Forum \#54016](https://forum.sublimetext.com/t/lfs-support/54016)).  
> * **FR-4.6 (Multi-Hosting Mirror Sync & Push-All-Mirrors Orchestrator — VP-25, ui-planning.md §6.26):** Group multiple remotes as mirrors of the same repository, view a live Mirror Sync Matrix (Synced, Ahead ↑N, Behind ↓M, Diverged, Offline), sync individual lagging mirrors in 1 click, or push to all mirror remotes concurrently in parallel (mirrors.push\_all\_mirrors\_by\_default, mirrors.max\_parallel\_probes).  
> * **FR-4.7 (5-Stage Zero-Latency Mirror Resolution Engine — VP-25, ui-planning.md §5.5 OPT-7):** Resolve mirror equivalence and sync state across hosting sites with zero UI blocking via: (1) \< 10µs pre-compiled URL canonicalization, (2) \< 0.5ms local .git/packed-refs \+ .git/refs/remotes/ blake2b digest lookup in SQLite mirror\_resolution\_cache, (3) O(1) root-commit OID fingerprinting (git rev-list \--max-parents=0) to verify true mirror lineage regardless of repo renaming, (4) parallel bounded git ls-remote \--heads \--tags \--refs \+ HTTP/2 httpx multiplexing (ThreadPoolExecutor(max\_workers=4), 4s timeout), and (5) a 120s per-host circuit breaker for unreachable/VPN mirrors.  
> * **FR-5.10–5.13 (Inline PR Code Review, Issues Tab, Multi-Account Routing & Live CI Logs — VP-6..VP-8, ui-planning.md §6.18–§6.19):** Controlled by forge.enabled, forge.pr\_inline\_comments.enabled, forge.ci\_log\_streaming.enabled, forge.issues\_tab.enabled, credentials.multi\_account\_rules.enabled ([Lazygit \#3639](https://github.com/jesseduffield/lazygit/issues/3639), [\#5833](https://github.com/jesseduffield/lazygit/issues/5833)).  
> * **FR-6.3–6.4 (Custom Forge Domains & SourceForge Adapter — VP-9, ui-planning.md §6.11):** Controlled by forge.sourceforge.enabled.  
> * **FR-7.4 (Adaptive Monorepo Watcher Fallback — VP-16):** Automatically switches to .git/ metadata watching on ENOSPC when watcher.monorepo\_adaptive\_fallback.enabled is True ([GitButler \#5407](https://github.com/gitbutlerapp/gitbutler/issues/5407)).

### **3.8 Universal Settings Registry, Delta Undo, Diff UX, Backups, Rerere & Custom Actions (FR-8.x)**

| ID | Priority | Requirement Description | UI Spec & Settings Toggle / Tweaks |
| :---- | :---- | :---- | :---- |
| **FR-8.3–8.4** | **D (v2)** | **External Diff/Merge Tools & Enhanced Diff Viewer UX:** External tool launchers plus **Split/Unified Diff Toggle (Ctrl+D)**, **Interactive Diff Minimap Scrubber**, **Sticky Function Header**, **Alt+W Whitespace Peek**, intra-line word diffing, and \--color-moved highlighting. | ui-planning.md §3.2. Keys: diff.view\_mode, diff.minimap.enabled, diff.sticky\_function\_header.enabled, diff.intraline\_word\_diff.enabled, diff.color\_moved.enabled, diff.external\_tool.enabled (VP-10). |
| **FR-8.5** | **D (v2)** | **Scheduled Safety Stash & Backup Manager:** Periodic background git stash create snapshots and visual restore browser. | ui-planning.md §6.4. Keys: safety.scheduled\_backups.enabled, safety.scheduled\_interval\_minutes (VP-14). |
| **FR-8.6** | **D (v2)** | **Conflict Resolution Memory (git rerere) Manager:** Auto-apply recorded conflict resolutions in 3-way merge tool with a 1-click Forget Recorded Resolution button ([Sublime Merge \#814](https://forum.sublimetext.com/t/git-rerere-ui/54803)). | ui-planning.md §6.6. Key: merge.rerere\_ui.enabled (VP-23). |
| **FR-8.7** | **D (v2)** | **User-Defined Custom Actions & Fuzzy Command Palette (Ctrl+K):** Context-aware custom commands ([Lazygit \#3930](https://github.com/jesseduffield/lazygit/issues/3930)) and Ctrl+K palette indexing actions, branches, and inline setting toggles. | ui-planning.md §6.24. Keys: ui.command\_palette.enabled, custom\_actions.enabled (VP-23). |
| **FR-8.8–8.11** | **D (v2)** | **Centralized SettingsRegistry, Zero-Impact Disabling, Searchable Lazy-Loaded SettingsDialog & JSON Portability:** Every v1/v2 feature registered in settings\_registry.py, lazy-loaded category pages (OPT-1), 150ms debounced auto-save (OPT-2), "Modified Only" filter, Live Mini-Preview cards, ★ Quick-Settings Pinning, and ⚙ jump buttons. | ui-planning.md §1.3, §5.5, §6.11 (VP-0). |
| **FR-8.12** | **D (v2)** | **Delta-Only Settings Snapshot & Multi-Step Undo/Redo (Ctrl+Z / Ctrl+Y):** Record only changed setting deltas (key, old\_val, new\_val, repo\_path, timestamp) into a 100-entry SQLite ring buffer (settings\_undo\_log) so users can undo/redo setting tweaks via Ctrl+Z or revert any specific change from the Settings History popover. | ui-planning.md §5.5 OPT-3, §6.11 (VP-0). |
| **FR-8.13** | **D (v2)** | **2-Tier Progressive Help System (Contextual Beginner Hover Cards \+ Searchable Offline Help & Git Guide F1):** Combine rich hover tooltips on complex Git/UI elements (showing a plain-English 2-line explanation, the equivalent git CLI flag, a Read Full Guide (F1) → deep-link, and a Switch to Compact Tooltips button) with a lazy-loaded, searchable in-app Help & Git Concept Encyclopedia (F1). Fully controllable via help.tooltip\_mode ("beginner\_rich", "compact\_shortcut\_only", "off"). | ui-planning.md §5.6, §6.25 (VP-0). |
| **FR-8.14** | **D (v2)** | **Zero-Copy Virtualized Diff Viewer Engine (DiffLineModel & OPT-8):** Replace heavy QTextDocument full-file DOM population with a flat array('I') byte-offset patch indexer (\< 3ms for 50,000 lines) backing a QAbstractListModel \+ QListView(uniformItemSizes=True) viewport painter, paired with a 512-entry LRU cache for visible intra-line word-diff/syntax spans, collapsible \+N unchanged lines context dividers, and a 35ms rapid file-switch coalescing timer. | ui-planning.md §3.3, §3.4, §5.5 OPT-8. Keys: diff.virtualized\_renderer.enabled, diff.lru\_cache\_lines, diff.coalesce\_switch\_ms, diff.fold\_unchanged\_context.enabled (VP-10). |

### **3.9–3.12 Search, Blame, Line History, Stash, Performance & Desktop Integration (FR-9.x–FR-12.x)**

> * **FR-9.1–9.5 (Pickaxe Search, Reflog Inspector, Blame Gutter & git log \-L Line History — VP-11, VP-21, ui-planning.md §6.7, §6.23):** Controlled by search.pickaxe\_enabled, reflog.inspector\_ui.enabled, blame.ui.enabled, blame.use\_ignore\_revs\_file, and line\_history.ui.enabled ([GitHub Desktop \#9580](https://github.com/desktop/desktop/issues/9580), [git-cola \#953](https://github.com/git-cola/git-cola/issues/953), [Sublime Merge \#1098](https://github.com/sublimehq/sublime_merge/issues/1098), [Forum \#39746](https://forum.sublimetext.com/t/feature-request-line-history/39746)).  


> * **FR-10.5–10.6 (Granular Stash Modes \--staged/--keep-index, Explicit refs/stash@{n} & \--skip-worktree Panel — VP-22, ui-planning.md §3.1):** Controlled by stash.granular\_modes.enabled and staging.skip\_worktree\_ui.enabled ([Lazygit \#458](https://github.com/jesseduffield/lazygit/issues/458), [\#3380](hhtps://github.com/jesseduffield/lazygit/issues/3380), [Sublime Merge \#945](hhtps://github.com/sublimehq/sublime_merge/issues/945)).  
> * **FR-11.3 & FR-12.1–12.4 (100k+ Commit Graph Virtualization, System Tray & Distro Packaging — VP-13, VP-15, VP-16):** Controlled by performance.graph\_page\_size, desktop.system\_tray.enabled, and credentials.backend\_mode.

## **4\. Non-Functional Requirements (NFRs)**

> * **NFR-1 (Performance & Lazy Allocation):** Repo load \< 500ms (10k commits) and \< 1.5s (100k+ commits); 60fps scrolling via viewport clipping and QPixmapCache; lazy instantiation of unselected tabs and Settings category pages (OPT-1); \< 250MB RSS baseline (\< 140MB RSS in Minimalist Local-Only Mode).  
> * **NFR-2 (Reliability & Non-Destructive Safety):** Every destructive Git write is preceded by a git stash create safety snapshot (core/snapshots.py) and surfaces an immediate \[Undo (Ctrl+Z)\] toast (ui-planning.md §1.4).  
> * **NFR-3 (Security):** Secrets stored exclusively in D-Bus Secret Service, XDG Secret Portal, or ephemeral memory (NFR-3).  
> * **NFR-4 (Usability):** Full keyboard navigation, F11 Zen Mode, Ctrl+K Command Palette, and CliCommandPreviewBar on all action dialogs.  
> * **NFR-5 (Total Configurability, Auto-Save & Delta Settings Undo):** Every feature in v1 and v2 is toggleable at runtime with zero residual overhead when disabled, auto-saves with a 150ms debounce (OPT-2), and records delta-only snapshots (OPT-3) for instant Settings Undo/Redo.  
> * **NFR-6 (Zero-Shortcut Security & Optimization Enforcement — SEC-1..SEC-7 & OPT-1..OPT-8):** Coding executors MUST NOT trade away security or performance optimizations to shorten development time. Every phase is gated by an automated static/AST verification suite (tests/meta/test\_no\_shortcuts\_guard.py) enforcing: (SEC-1) shell=False and mandatory \-- end-of-options delimiters before refs/paths to block Git argument injection; (SEC-2) strict URL scheme allowlisting (https\://, ssh://, git@) and SSRF loopback blocking on mirror/forge URLs; (SEC-3) automatic token/credential redaction in all logs and UI drawers; (SEC-4) 0o600 permissions on temporary askpass/rebase files; (SEC-5) 100% parameterized SQLite queries (? placeholders only); (SEC-6) allowlist-validated wrench:// help URIs; and (SEC-7) zero TODO/pass/NotImplementedError stubs.

## **5\. System Architecture Overview (ARCHITECTURE.md)**

Strict 3-tier one-directional data flow: UI Layer (src/wrench/ui) \-\> Façade Layer (core.engine / forge.registry / storage.settings\_registry) \-\> Backends (pygit2 / git CLI / httpx / secretstorage / SQLite WAL).

## **6\. Open Items & Future Scope**

> * Community .ts translations, optional Gerrit/Radicle entry-point plugins, and optional tree-sitter structural diffing post-v2.

## **7\. Assumptions & Decisions Log**

> * **DEC-1..DEC-4:** Hybrid pygit2 reads \+ git CLI writes; native git rebase \--update-refs for stacks ([GitButler \#5758](hhtps://github.com/gitbutlerapp/gitbutler/issues/5758)); login-shell PATH hydration for hooks ([GitHub Desktop \#17385](hhtps://github.com/desktop/desktop/issues/17385)); explicit refs/stash@{n} addressing ([Sublime Merge \#945](hhtps://github.com/sublimehq/sublime_merge/issues/945)).  
> * **DEC-5:** Universal SettingsRegistry with zero-impact UI hiding and backend short-circuiting.  
> * **DEC-6:** **Lazy Page Loading (OPT-1), 150ms Debounced Auto-Save (OPT-2), and Delta-Only Settings Undo Stack (OPT-3)** in SettingsRegistry \+ SettingsDialog so preferences feel instantaneous, never block the main thread, and allow 1-click Ctrl+Z recovery from accidental setting changes.  
> * **DEC-7:** **2-Tier Progressive Disclosure Help System (FR-8.13, VP-24):** Combine singleton contextual beginner hover cards (RichHelpTooltip) with a lazy-loaded, offline searchable HelpCenterDialog (F1).  
> * **DEC-8:** **5-Stage Mirror Resolution & Root-Commit Fingerprinting (FR-3.10, FR-4.6–4.7, VP-25, OPT-7):** Identify mirror repositories across GitHub, GitLab, Codeberg/Forgejo, Bitbucket, and SourceForge by comparing root-commit OIDs (git rev-list \--max-parents=0) cached alongside a local blake2b remote-ref digest in mirror\_resolution\_cache, resolving unchanged mirrors in \< 0.5ms and probing stale mirrors in parallel (ThreadPoolExecutor(max\_workers=4)) with a 120s per-host circuit breaker.  
> * **DEC-9:** **Virtualized Line-Indexed DiffWidget (FR-8.14, VP-10, OPT-8):** Index diffs as flat array('I') byte offsets into the raw patch buffer and render via QAbstractListModel \+ uniformItemSizes viewport painting with a 512-entry LRU cache for visible intra-line/syntax spans, eliminating QTextDocument freezes on massive diffs.