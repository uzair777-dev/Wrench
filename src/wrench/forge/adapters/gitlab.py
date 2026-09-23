"""FR-5.3: GitLab adapter."""

from urllib.parse import quote

import httpx

from wrench.forge.capability import ForgeAdapter, ForgeCapability
from wrench.forge.exceptions import ForgeError
from wrench.forge.models import CIStatus, Issue, PullRequest


class GitLabAdapter(ForgeAdapter):
    provider_id = "gitlab"

    @property
    def capabilities(self) -> ForgeCapability:
        return (
            ForgeCapability.PULL_REQUESTS
            | ForgeCapability.ISSUES
            | ForgeCapability.CI_STATUS
            | ForgeCapability.ISSUE_LINKING
            | ForgeCapability.REVIEWS
        )

    @property
    def supported_review_actions(self) -> frozenset[str]:
        return frozenset({"approve", "comment"})

    def _get_base_url(self) -> str:
        instance = self.account.instance_url.rstrip("/")
        return f"{instance}/api/v4"

    def _auth_headers_and_auth(self) -> tuple[dict[str, str], httpx.Auth | None]:
        headers = {"PRIVATE-TOKEN": self._get_token()}
        return headers, None

    def _get_scope_hint(self) -> str:
        return "needs 'api' or 'read_api' scope"

    def _project_slug(self, owner: str, repo: str) -> str:
        return quote(f"{owner}/{repo}", safe="")

    def list_pull_requests(self, owner: str, repo: str, state: str = "open") -> list[PullRequest]:
        slug = self._project_slug(owner, repo)
        state_map = {"open": "opened", "merged": "merged", "closed": "closed", "all": "all"}
        query_state = state_map.get(state, "opened")

        raw_items = self._paged_get(
            f"/projects/{slug}/merge_requests",
            params={"state": query_state, "per_page": 50},
        )

        prs: list[PullRequest] = []
        for item in raw_items:
            raw_state = item.get("state", "opened")
            if raw_state == "opened":
                norm_state = "open"
            elif raw_state == "merged":
                norm_state = "merged"
            else:
                norm_state = "closed"

            if state != "all" and state != norm_state:
                continue

            prs.append(
                PullRequest(
                    id=str(item["iid"]),
                    title=item.get("title", ""),
                    description=item.get("description") or "",
                    source_branch=item.get("source_branch", ""),
                    target_branch=item.get("target_branch", ""),
                    state=norm_state,
                    url=item.get("web_url", ""),
                    author=item.get("author", {}).get("username", ""),
                    created_at=item.get("created_at", ""),
                )
            )
        return prs

    def create_pull_request(
        self,
        owner: str,
        repo: str,
        *,
        title: str,
        source_branch: str,
        target_branch: str,
        description: str = "",
    ) -> PullRequest:
        slug = self._project_slug(owner, repo)
        payload = {
            "title": title,
            "source_branch": source_branch,
            "target_branch": target_branch,
            "description": description,
        }
        resp = self._request("POST", f"/projects/{slug}/merge_requests", json=payload)
        item = resp.json()
        return PullRequest(
            id=str(item["iid"]),
            title=item.get("title", ""),
            description=item.get("description") or "",
            source_branch=item.get("source_branch", ""),
            target_branch=item.get("target_branch", ""),
            state="open",
            url=item.get("web_url", ""),
            author=item.get("author", {}).get("username", ""),
            created_at=item.get("created_at", ""),
        )

    def submit_review(
        self,
        owner: str,
        repo: str,
        number: int,
        *,
        action: str,  # 'approve' | 'comment'
        body: str = "",
    ) -> None:
        slug = self._project_slug(owner, repo)
        act = action.lower()

        if act == "request_changes":
            raise ForgeError("GitLab does not support requesting changes via API.")

        if act == "approve":
            try:
                self._request("POST", f"/projects/{slug}/merge_requests/{number}/approve")
            except Exception as e:
                # Intercept self-approval trap
                msg = str(e).lower()
                if "cannot approve" in msg or "own merge request" in msg:
                    raise ForgeError("You cannot approve your own merge request.") from e
                raise
        elif act == "comment":
            if not body.strip():
                raise ForgeError("Comment body cannot be blank.")
            self._request(
                "POST", f"/projects/{slug}/merge_requests/{number}/notes", json={"body": body}
            )

    def get_ci_status(self, owner: str, repo: str, ref: str) -> CIStatus:
        slug = self._project_slug(owner, repo)
        try:
            resp = self._request(
                "GET", f"/projects/{slug}/pipelines", params={"sha": ref, "per_page": 1}
            )
            pipelines = resp.json()
            if not pipelines or not isinstance(pipelines, list):
                return CIStatus(state="unknown", url=None, description=None)

            pipe = pipelines[0]
            raw_status = pipe.get("status", "unknown")
            state = "unknown"
            if raw_status in ("running", "pending"):
                state = "pending"
            elif raw_status == "success":
                state = "success"
            elif raw_status in ("failed", "canceled"):
                state = "failure"

            return CIStatus(
                state=state,
                url=pipe.get("web_url"),
                description=f"Pipeline #{pipe.get('id')}: {raw_status}",
            )
        except Exception:
            return CIStatus(state="unknown", url=None, description=None)

    def list_issues(self, owner: str, repo: str, state: str = "open") -> list[Issue]:
        slug = self._project_slug(owner, repo)
        state_map = {"open": "opened", "closed": "closed", "all": "all"}
        query_state = state_map.get(state, "opened")

        raw_items = self._paged_get(
            f"/projects/{slug}/issues",
            params={"state": query_state, "per_page": 50},
        )

        issues: list[Issue] = []
        for item in raw_items:
            raw_state = item.get("state", "opened")
            norm_state = "open" if raw_state == "opened" else "closed"
            if state != "all" and state != norm_state:
                continue

            issues.append(
                Issue(
                    id=str(item["iid"]),
                    title=item.get("title", ""),
                    description=item.get("description") or "",
                    state=norm_state,
                    url=item.get("web_url", ""),
                    author=item.get("author", {}).get("username", ""),
                    created_at=item.get("created_at", ""),
                )
            )
        return issues
