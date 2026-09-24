"""FR-5.4: Forgejo / Gitea adapter."""

from typing import Any

import httpx

from wrench.forge.capability import ForgeAdapter, ForgeCapability
from wrench.forge.models import CIStatus, Issue, PullRequest


class ForgejoAdapter(ForgeAdapter):
    provider_id = "forgejo"

    @property
    def capabilities(self) -> ForgeCapability:
        return (
            ForgeCapability.PULL_REQUESTS
            | ForgeCapability.ISSUES
            | ForgeCapability.CI_STATUS
            | ForgeCapability.ISSUE_LINKING
            | ForgeCapability.REVIEWS
        )

    def _get_base_url(self) -> str:
        instance = self.account.instance_url.rstrip("/")
        return f"{instance}/api/v1"

    def _auth_headers_and_auth(self) -> tuple[dict[str, str], httpx.Auth | None]:
        headers = {
            "Authorization": f"token {self._get_token()}",
            "Accept": "application/json",
        }
        return headers, None

    def _get_scope_hint(self) -> str:
        return "needs 'repo' or 'issue' token permissions"

    def list_pull_requests(self, owner: str, repo: str, state: str = "open") -> list[PullRequest]:
        query_state = (
            "all" if state == "all" else ("closed" if state in ("merged", "closed") else "open")
        )
        raw_items = self._paged_get(
            f"/repos/{owner}/{repo}/pulls",
            params={"state": query_state, "limit": 50},
        )

        prs: list[PullRequest] = []
        for item in raw_items:
            is_merged = item.get("merged") is True or item.get("merged_at") is not None
            raw_state = item.get("state", "open")
            if is_merged:
                norm_state = "merged"
            elif raw_state == "closed":
                norm_state = "closed"
            else:
                norm_state = "open"

            if state != "all" and state != norm_state:
                continue

            prs.append(
                PullRequest(
                    id=str(item["number"]),
                    title=item.get("title", ""),
                    description=item.get("body") or "",
                    source_branch=item.get("head", {}).get("ref", ""),
                    target_branch=item.get("base", {}).get("ref", ""),
                    state=norm_state,
                    url=item.get("html_url", ""),
                    author=item.get("user", {}).get("login", ""),
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
        payload = {
            "title": title,
            "head": source_branch,
            "base": target_branch,
            "body": description,
        }
        resp = self._request("POST", f"/repos/{owner}/{repo}/pulls", json=payload)
        item = resp.json()
        return PullRequest(
            id=str(item["number"]),
            title=item.get("title", ""),
            description=item.get("body") or "",
            source_branch=item.get("head", {}).get("ref", ""),
            target_branch=item.get("base", {}).get("ref", ""),
            state="open",
            url=item.get("html_url", ""),
            author=item.get("user", {}).get("login", ""),
            created_at=item.get("created_at", ""),
        )

    def submit_review(
        self,
        owner: str,
        repo: str,
        number: int,
        *,
        action: str,  # 'approve' | 'request_changes' | 'comment'
        body: str = "",
    ) -> None:
        action_map = {
            "approve": "APPROVED",  # Trap: Forgejo/Gitea uses past tense APPROVED!
            "request_changes": "REQUEST_CHANGES",
            "comment": "COMMENT",
        }
        event = action_map.get(action.lower(), "COMMENT")
        payload: dict[str, Any] = {"event": event}
        if body:
            payload["body"] = body
        self._request("POST", f"/repos/{owner}/{repo}/pulls/{number}/reviews", json=payload)

    def get_ci_status(self, owner: str, repo: str, ref: str) -> CIStatus:
        try:
            resp = self._request("GET", f"/repos/{owner}/{repo}/commits/{ref}/status")
            data = resp.json()
            raw_state = data.get("state", "unknown")
            state = "unknown"
            if raw_state == "success":
                state = "success"
            elif raw_state in ("failure", "error"):
                state = "failure"
            elif raw_state == "pending":
                state = "pending"

            statuses = data.get("statuses", [])
            target_url = statuses[0].get("target_url") if statuses else None
            desc = statuses[0].get("description") if statuses else None
            return CIStatus(state=state, url=target_url, description=desc)
        except Exception:
            return CIStatus(state="unknown", url=None, description=None)

    def list_issues(self, owner: str, repo: str, state: str = "open") -> list[Issue]:
        query_state = "all" if state == "all" else state
        raw_items = self._paged_get(
            f"/repos/{owner}/{repo}/issues",
            params={"type": "issues", "state": query_state, "limit": 50},
        )

        issues: list[Issue] = []
        for item in raw_items:
            issues.append(
                Issue(
                    id=str(item["number"]),
                    title=item.get("title", ""),
                    description=item.get("body") or "",
                    state=item.get("state", "open"),
                    url=item.get("html_url", ""),
                    author=item.get("user", {}).get("login", ""),
                    created_at=item.get("created_at", ""),
                )
            )
        return issues

    def get_pull_request(self, owner: str, repo: str, pr_id: str) -> PullRequest:
        resp = self._request("GET", f"/repos/{owner}/{repo}/pulls/{pr_id}")
        item = resp.json()
        is_merged = item.get("merged_at") is not None
        raw_state = item.get("state", "open")
        if is_merged:
            norm_state = "merged"
        elif raw_state == "closed":
            norm_state = "closed"
        else:
            norm_state = "open"

        return PullRequest(
            id=str(item["number"]),
            title=item.get("title", ""),
            description=item.get("body") or "",
            source_branch=item.get("head", {}).get("ref", ""),
            target_branch=item.get("base", {}).get("ref", ""),
            state=norm_state,
            url=item.get("html_url", ""),
            author=item.get("user", {}).get("login", ""),
            created_at=item.get("created_at", ""),
        )

    def get_issue(self, owner: str, repo: str, issue_id: str) -> Issue:
        resp = self._request("GET", f"/repos/{owner}/{repo}/issues/{issue_id}")
        item = resp.json()
        return Issue(
            id=str(item["number"]),
            title=item.get("title", ""),
            description=item.get("body") or "",
            state=item.get("state", "open"),
            url=item.get("html_url", ""),
            author=item.get("user", {}).get("login", ""),
            created_at=item.get("created_at", ""),
        )
