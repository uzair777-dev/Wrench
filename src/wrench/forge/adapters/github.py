"""FR-5.2: GitHub adapter."""

from typing import Any
from urllib.parse import urlsplit

import httpx

from wrench.forge.capability import ForgeAdapter, ForgeCapability
from wrench.forge.models import CIStatus, Issue, PullRequest


class GitHubAdapter(ForgeAdapter):
    provider_id = "github"

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
        host = urlsplit(instance).netloc.lower() or instance.lower()
        if host == "github.com" or "github.com" in host:
            return "https://api.github.com"
        return f"{instance}/api/v3"

    def _auth_headers_and_auth(self) -> tuple[dict[str, str], httpx.Auth | None]:
        headers = {
            "Authorization": f"Bearer {self._get_token()}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        return headers, None

    def _get_scope_hint(self) -> str:
        return (
            "needs 'repo' scope for private repositories or 'public_repo' for public repositories"
        )

    def list_pull_requests(self, owner: str, repo: str, state: str = "open") -> list[PullRequest]:
        query_state = (
            "all" if state == "all" else ("closed" if state in ("merged", "closed") else "open")
        )
        raw_items = self._paged_get(
            f"/repos/{owner}/{repo}/pulls",
            params={"state": query_state, "per_page": 50},
        )

        prs: list[PullRequest] = []
        for item in raw_items:
            is_merged = item.get("merged_at") is not None
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
            "approve": "APPROVE",
            "request_changes": "REQUEST_CHANGES",
            "comment": "COMMENT",
        }
        event = action_map.get(action.lower(), "COMMENT")
        payload: dict[str, Any] = {"event": event}
        if body:
            payload["body"] = body
        self._request("POST", f"/repos/{owner}/{repo}/pulls/{number}/reviews", json=payload)

    def get_ci_status(self, owner: str, repo: str, ref: str) -> CIStatus:
        # Check combined commit status
        try:
            resp = self._request("GET", f"/repos/{owner}/{repo}/commits/{ref}/status")
            data = resp.json()
            if data.get("total_count", 0) > 0:
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
            pass

        # Check Check Runs
        try:
            resp = self._request("GET", f"/repos/{owner}/{repo}/commits/{ref}/check-runs")
            data = resp.json()
            runs = data.get("check_runs", [])
            if runs:
                # Any failure -> failure, any in_progress/queued -> pending, all success -> success
                conclusions = [r.get("conclusion") for r in runs]
                statuses = [r.get("status") for r in runs]

                if any(c in ("failure", "timed_out", "action_required") for c in conclusions):
                    state = "failure"
                elif any(s in ("queued", "in_progress") for s in statuses):
                    state = "pending"
                elif all(c == "success" for c in conclusions):
                    state = "success"
                else:
                    state = "unknown"

                url = runs[0].get("html_url")
                desc = f"{len(runs)} checks: {state}"
                return CIStatus(state=state, url=url, description=desc)
        except Exception:
            pass

        return CIStatus(state="unknown", url=None, description=None)

    def list_issues(self, owner: str, repo: str, state: str = "open") -> list[Issue]:
        query_state = "all" if state == "all" else state
        raw_items = self._paged_get(
            f"/repos/{owner}/{repo}/issues",
            params={"state": query_state, "per_page": 50},
        )

        issues: list[Issue] = []
        for item in raw_items:
            # Trap: GitHub mixes PRs in /issues endpoint
            if "pull_request" in item:
                continue

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
        norm_state = "merged" if is_merged else ("closed" if raw_state == "closed" else "open")

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
