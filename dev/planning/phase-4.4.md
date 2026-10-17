# Phase 4.4 Summary: Forge Avatars (FR-5.14)

**Status:** Completed  
**Associated SRS Requirements:** FR-5.14, NFR Usability, NFR Accessibility, NFR Maintainability, NFR Performance  
**Associated Planning Documents:** [`implementation-plan.md`](file:///home/uzair/Projects/wrench/dev/planning/implementation-plan.md), [`srs.md`](file:///home/uzair/Projects/wrench/dev/planning/srs.md), [`ui-planning.md`](file:///home/uzair/Projects/wrench/dev/planning/ui-planning.md)  

---

## 1. Overview & Objectives

Phase 4.4 implemented visual identity across the application by introducing asynchronous, cached user avatars for forge pull requests, issues, accounts, and commit authors:

1. **System Cache Directory Resolution (`src/wrench/core/paths.py`)**:
   - Implemented `cache_dir()` using `platformdirs.user_cache_dir("wrench", "wrench")` with graceful fallback to `~/.cache/wrench`.
   - Guaranteed automatic directory creation on demand.

2. **Domain Model Extensions (`src/wrench/forge/models.py`)**:
   - Added `author_avatar_url: str | None = None` as a trailing field to `PullRequest` and `Issue` dataclasses.
   - Preserved 100% backward compatibility with all existing positional and keyword constructor call sites.

3. **Multi-Adapter Avatar URL Extraction (`src/wrench/forge/adapters/`)**:
   - Extended all 4 forge adapters (`GitHubAdapter`, `GitLabAdapter`, `ForgejoAdapter`, `BitbucketAdapter`) to extract author avatar URLs from native API payloads:
     - **GitHub**: `user.avatar_url` (issues & PRs).
     - **GitLab**: `author.avatar_url` (issues & merge requests).
     - **Forgejo**: `user.avatar_url` (issues & pull requests).
     - **Bitbucket**: `author.links.avatar.href` (issues & pull requests).
   - Added `get_avatar_url(account, token)` capability method to all adapters, retrieving the authenticated user's avatar URL.

4. **Accessible Avatar Semantic Tokens (`src/wrench/ui/theme.py`)**:
   - Added `AVATAR_BG_COLORS` token dictionary containing 6 dark and 6 light accessible background colors (Catppuccin-derived).
   - Added `get_avatar_bg_color(username: str, mode: str = "dark") -> str` providing deterministic, hash-based color selection.
   - Verified that white text (`#FFFFFF`) against all 12 avatar background colors satisfies WCAG 2.1 AAA/AA contrast ($\ge 4.5:1$).
   - Enforced zero hardcoded hex literals outside `theme.py` via automated gate tests.

5. **Asynchronous Non-Blocking Avatar Architecture (`src/wrench/ui/widgets/avatar.py`)**:
   - Implemented `AvatarLoader(QObject)` singleton:
     - **In-Memory Cache**: `_mem_cache[url] = (QPixmap, mtime)` for instantaneous repeated access.
     - **Disk Cache**: SHA-256 hashed filenames in `cache_dir() / "avatars"` with a 7-day TTL.
     - **In-Flight Deduplication**: Coalesces concurrent requests for identical URLs onto single network fetches.
     - **Background Threading**: All network downloads and disk reads execute on background worker threads; pixmap decoding and rendering occur safely on the Qt GUI thread.
     - **Silent Failure & Airplane Mode**: Network timeouts, 404s, or corrupt disk cache files fail silently without error popups or logs, cleanly falling back to initials.
   - Implemented `AvatarWidget(QWidget)`:
     - Renders circular avatars with smooth anti-aliased clipping.
     - Displays two-letter username initials fallback immediately on instantiation, smoothly swapping to loaded pixmaps upon download.
     - Supports 24px, 40px, and 64px standard size buckets.

6. **UI Integrations Across Application Surfaces**:
   - **PR & Issue List Tabs** (`pr_list_tab.py`, `issue_list_tab.py`): Render 24px avatar icons or colored initials badges directly in the "Author" table column.
   - **PR & Issue Detail Tabs** (`pr_detail_tab.py`, `issue_detail_tab.py`): Render 40px `AvatarWidget` in the detail headers beside the author and issue/PR title.
   - **Commit Box** (`changes_tab.py`): Shows 24px linked account avatar on the Account split-button. Persists `account.{id}.avatar_url` during forge linking (`link_dialog.py`).
   - **Commit Detail Panel** (`detail_panel.py`): Displays 24px commit author avatar resolved via Gravatar (SHA-256/MD5 hash of author email), strictly gated behind the default-OFF `ui.avatars_gravatar` setting.
   - **Settings Dialog** (`settings_dialog.py`): Added privacy-conscious "Enable Gravatar avatars for commit authors" toggle on `AppearancePage` with a clear privacy explanation tooltip.

---

## 2. Architecture & Implementation Details

### Data Flow Diagram

```
                 +------------------------------------------------+
                 |            UI Widget Request                   |
                 | (PR List, Detail Header, Commit Box, Detail)   |
                 +------------------------------------------------+
                                         |
                                         v
                         +-------------------------------+
                         |   AvatarWidget.set_avatar()   |
                         |  (renders initials fallback)  |
                         +-------------------------------+
                                         |
                                         v
                        +---------------------------------+
                        |    AvatarLoader.load_avatar()   |
                        +---------------------------------+
                                    /         \
                      Memory Hit   /           \  Memory Miss
                                  v             v
                     +---------------+   +-----------------------------+
                     | Return Pixmap |   | Check SHA-256 Disk Cache    |
                     |  immediately  |   +-----------------------------+
                     +---------------+            /              \
                                      Valid File /                \ Stale / Missing
                                                v                  v
                                    +---------------+   +-------------------------+
                                    | Load from Disk|   | Coalesce In-Flight Req  |
                                    | (mtime < 7d)  |   +-------------------------+
                                    +---------------+                |
                                                          Background Worker Thread
                                                                     |
                                                        +-------------------------+
                                                        | urllib.request.urlopen  |
                                                        | (5s timeout, silent err)|
                                                        +-------------------------+
                                                                     |
                                                        +-------------------------+
                                                        | Write to Disk Cache     |
                                                        | Emit avatar_loaded      |
                                                        +-------------------------+
                                                                     |
                                                        +-------------------------+
                                                        | GUI Thread Decode       |
                                                        | Repaint AvatarWidget    |
                                                        +-------------------------+
```

### Component Breakdown

| Component | Path | Key Responsibilities |
|---|---|---|
| Cache Paths | `src/wrench/core/paths.py` | `cache_dir()` resolution via `platformdirs` with `~/.cache/wrench` fallback |
| Forge Models | `src/wrench/forge/models.py` | Trailing `author_avatar_url` on `PullRequest` and `Issue` |
| GitHub Adapter | `src/wrench/forge/adapters/github.py` | Map `user.avatar_url`; implement `get_avatar_url` |
| GitLab Adapter | `src/wrench/forge/adapters/gitlab.py` | Map `author.avatar_url`; implement `get_avatar_url` |
| Forgejo Adapter | `src/wrench/forge/adapters/forgejo.py` | Map `user.avatar_url`; implement `get_avatar_url` |
| Bitbucket Adapter | `src/wrench/forge/adapters/bitbucket.py` | Map `author.links.avatar.href`; implement `get_avatar_url` |
| Theme Tokens | `src/wrench/ui/theme.py` | `AVATAR_BG_COLORS`, `get_avatar_bg_color()`, WCAG-compliant palettes |
| Avatar Loader & Widget | `src/wrench/ui/widgets/avatar.py` | `AvatarLoader` singleton, `AvatarWidget` circular painter, disk/memory caches |
| Settings Dialog | `src/wrench/ui/dialogs/settings_dialog.py` | Gravatar privacy opt-in toggle on `AppearancePage` |
| PR / Issue Lists | `src/wrench/ui/tabs/pr_list_tab.py`, `issue_list_tab.py` | 24px `AvatarWidget` decoration in table rows |
| PR / Issue Details | `src/wrench/ui/tabs/pr_detail_tab.py`, `issue_detail_tab.py` | 40px `AvatarWidget` in header view |
| Changes Tab | `src/wrench/ui/tabs/changes_tab.py`, `link_dialog.py` | Commit-box account button avatar; `account.{id}.avatar_url` DB persistence |
| Commit Detail Panel | `src/wrench/ui/commit_graph/detail_panel.py` | 24px commit author avatar with Gravatar hashing behind `ui.avatars_gravatar` |

---

## 3. Test Matrix & Verification

### Unit & Integration Tests

- **`tests/unit/core/test_paths.py`**:
  - `test_cache_dir_returns_path`: Resolves to a valid `Path` and creates directory. **PASS**.
  - `test_cache_dir_fallback_on_error`: Gracefully falls back when platformdirs raises an exception. **PASS**.
- **`tests/unit/forge/test_models.py`**:
  - `test_pull_request_backward_compatible_constructor`: Instantiates without `author_avatar_url` (defaults to `None`). **PASS**.
  - `test_issue_backward_compatible_constructor`: Instantiates without `author_avatar_url` (defaults to `None`). **PASS**.
  - `test_models_with_avatar_url`: Instantiates with explicit `author_avatar_url`. **PASS**.
- **`tests/integration/forge/test_extended_adapters.py`**:
  - `test_github_adapter_maps_avatar_urls`: Parses PR and issue fixtures with `avatar_url`. **PASS**.
  - `test_gitlab_adapter_maps_avatar_urls`: Parses MR and issue fixtures with `avatar_url`. **PASS**.
  - `test_forgejo_adapter_maps_avatar_urls`: Parses PR and issue fixtures with `avatar_url`. **PASS**.
  - `test_bitbucket_adapter_maps_avatar_urls`: Parses PR and issue fixtures with `links.avatar.href`. **PASS**.
  - `test_get_avatar_url_all_adapters`: Capability method returns avatar URL from user payload across all 4 adapters. **PASS**.
- **`tests/unit/ui/test_theme_tokens.py` & `tests/unit/ui/test_theme_contrast.py`**:
  - `test_no_hardcoded_hex_colors_outside_theme`: 0 hex literals outside `src/wrench/ui/theme.py`. **PASS (0 violations)**.
  - `test_avatar_bg_colors_contrast`: White text on all 12 avatar background colors $\ge 4.5:1$ contrast ratio. **PASS**.
  - `test_get_avatar_bg_color_deterministic`: Returns identical color for same username and valid hex. **PASS**.
- **`tests/unit/ui/test_avatar.py`**:
  - `test_avatar_widget_initials_rendering`: Generates initials ("JD" from "John Doe", "UN" from "user", "?" from empty). **PASS**.
  - `test_avatar_loader_disk_and_memory_caching`: Writes SHA-256 disk cache file, reads from memory cache on second call. **PASS**.
  - `test_avatar_loader_ttl_expiry`: Refetches image from network when disk file exceeds 7-day TTL. **PASS**.
  - `test_avatar_loader_in_flight_dedup`: Only makes 1 network request when multiple widgets request same URL simultaneously. **PASS**.
  - `test_avatar_loader_network_error_silent`: 404 or connection error handled cleanly without raising exception or crashing. **PASS**.
  - `test_avatar_loader_corrupt_file_silent`: Corrupt image bytes on disk cleaned up and reloaded without crash. **PASS**.
- **`tests/ui/test_settings_dialog.py`**:
  - `test_appearance_page_gravatar_toggle`: Toggling Gravatar checkbox updates `ui.avatars_gravatar` setting in database and fires signal. **PASS**.
- **`tests/ui/test_forge_tabs.py`**:
  - `test_pr_list_tab_author_avatar`: Verifies table model exposes avatar decoration. **PASS**.
  - `test_pr_detail_tab_avatar_widget`: Asserts 40px AvatarWidget present in header and receives URL. **PASS**.
  - `test_issue_list_and_detail_avatar`: Asserts issue list and detail render avatar widgets. **PASS**.
- **`tests/unit/ui/test_changes_tab.py`**:
  - `test_commit_box_account_avatar`: Split button updates icon when linked account has `avatar_url`. **PASS**.
- **`tests/unit/ui/test_history_tab.py`**:
  - `test_commit_detail_panel_gravatar_disabled_by_default`: Zero gravatar requests when `ui.avatars_gravatar` is False (default). **PASS**.
  - `test_commit_detail_panel_gravatar_enabled`: Author email MD5 hashed and avatar requested when setting is enabled. **PASS**.

### Full Test Suite & Code Quality Results

- **Test Suite**: `./bin/wrench-test -q`
  - **496 passed in 29.83s, 0 failures**.
- **Linter**: `./bin/wrench-lint`
  - `ruff`: **Passed (0 warnings or errors)**.
  - `black --check`: **Passed (161 files checked, 0 reformats needed)**.
- **Theme Gate**:
  - `pytest tests/unit/ui/test_theme_tokens.py tests/unit/ui/test_theme_contrast.py`: **Passed (100% compliant)**.
