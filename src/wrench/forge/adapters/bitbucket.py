"""FR-5.5: Bitbucket Cloud adapter."""

from typing import Any

import httpx

from wrench.forge.capability import ForgeAdapter, ForgeCapability
from wrench.forge.exceptions import ForgeAuthenticationError, ForgeError
from wrench.forge.models import CIStatus, Issue, PullRequest


class BitbucketAdapter(ForgeAdapter):
    provider_id = "bitbucket"

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
        return "https://api.bitbucket.org/2.0"

    def _auth_headers_and_auth(self) -> tuple[dict[str, str], httpx.Auth | None]:
        if not self.account.username or not self.account.username.strip():
            raise ForgeAuthenticationError(
                f"Bitbucket account '{self.account.label}' "
                "requires an Atlassian account email as username."
            )
        token = self._get_token()
        return {"Accept": "application/json"}, httpx.BasicAuth(self.account.username, token)

    def _get_scope_hint(self) -> str:
        return "needs 'pullrequest', 'issue', and 'repository' scopes on your Bitbucket API token"

    def authenticate(self) -> None:
        self._request("GET", "/user")

    def list_pull_requests(self, owner: str, repo: str, state: str = "open") -> list[PullRequest]:
        state_query_map = {
            "open": "state=OPEN",
            "merged": "state=MERGED",
            "closed": 'state="DECLINED" OR state="SUPERSEDED"',
            "all": 'state="OPEN" OR state="MERGED" OR state="DECLINED" OR state="SUPERSEDED"',
        }
        q = state_query_map.get(state, "state=OPEN")
        raw_items = self._paged_get(
            f"/repositories/{owner}/{repo}/pullrequests",
            params={"q": q, "pagelen": 50},
        )

        prs: list[PullRequest] = []
        for item in raw_items:
            raw_state = item.get("state", "OPEN")
            if raw_state == "OPEN":
                norm_state = "open"
            elif raw_state == "MERGED":
                norm_state = "merged"
            else:
                norm_state = "closed"

            prs.append(
                PullRequest(
                    id=str(item["id"]),
                    title=item.get("title", ""),
                    description=item.get("description") or "",
                    source_branch=item.get("source", {}).get("branch", {}).get("name", ""),
                    target_branch=item.get("destination", {}).get("branch", {}).get("name", ""),
                    state=norm_state,
                    url=item.get("links", {}).get("html", {}).get("href", ""),
                    author=item.get("author", {}).get("display_name", "")
                    or item.get("author", {}).get("nickname", ""),
                    created_at=item.get("created_on", ""),
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
            "source": {"branch": {"name": source_branch}},
            "destination": {"branch": {"name": target_branch}},
            "description": description,
        }
        resp = self._request("POST", f"/repositories/{owner}/{repo}/pullrequests", json=payload)
        item = resp.json()
        return PullRequest(
            id=str(item["id"]),
            title=item.get("title", ""),
            description=item.get("description") or "",
            source_branch=item.get("source", {}).get("branch", {}).get("name", ""),
            target_branch=item.get("destination", {}).get("branch", {}).get("name", ""),
            state="open",
            url=item.get("links", {}).get("html", {}).get("href", ""),
            author=item.get("author", {}).get("display_name", ""),
            created_at=item.get("created_on", ""),
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
        act = action.lower()
        if act == "approve":
            self._request("POST", f"/repositories/{owner}/{repo}/pullrequests/{number}/approve")
        elif act == "request_changes":
            self._request(
                "POST", f"/repositories/{owner}/{repo}/pullrequests/{number}/request-changes"
            )
        elif act == "comment":
            if not body.strip():
                raise ForgeError("Comment body cannot be blank.")
            self._request(
                "POST",
                f"/repositories/{owner}/{repo}/pullrequests/{number}/comments",
                json={"content": {"raw": body}},
            )

    def get_ci_status(self, owner: str, repo: str, ref: str) -> CIStatus:
        try:
            resp = self._request("GET", f"/repositories/{owner}/{repo}/commit/{ref}/statuses")
            data = resp.json()
            values = data.get("values", [])
            if not values:
                return CIStatus(state="unknown", url=None, description=None)

            # Check statuses: SUCCESSFUL, FAILED, INPROGRESS, STOPPED
            raw_states = [v.get("state") for v in values]
            state = "unknown"
            if any(s in ("FAILED", "STOPPED") for s in raw_states):
                state = "failure"
            elif any(s == "INPROGRESS" for s in raw_states):
                state = "pending"
            elif all(s == "SUCCESSFUL" for s in raw_states):
                state = "success"

            first = values[0]
            return CIStatus(
                state=state,
                url=first.get("url"),
                description=first.get("description") or f"Build: {state}",
            )
        except Exception:
            return CIStatus(state="unknown", url=None, description=None)

    def list_issues(self, owner: str, repo: str, state: str = "open") -> list[Issue]:
        state_query_map = {
            "open": 'state="new" OR state="open"',
            "closed": 'state="resolved" OR state="closed" OR state="on hold"',
            "all": "",
        }
        params: dict[str, Any] = {"pagelen": 50}
        q = state_query_map.get(state)
        if q:
            params["q"] = q

        raw_items = self._paged_get(f"/repositories/{owner}/{repo}/issues", params=params)

        issues: list[Issue] = []
        for item in raw_items:
            raw_state = item.get("state", "new")
            norm_state = "open" if raw_state in ("new", "open") else "closed"

            issues.append(
                Issue(
                    id=str(item["id"]),
                    title=item.get("title", ""),
                    description=(
                        item.get("content", {}).get("raw", "")
                        if isinstance(item.get("content"), dict)
                        else ""
                    ),
                    state=norm_state,
                    url=item.get("links", {}).get("html", {}).get("href", ""),
                    author=item.get("reporter", {}).get("display_name", "")
                    or item.get("reporter", {}).get("nickname", ""),
                    created_at=item.get("created_on", ""),
                )
            )
        return issues

    def get_pull_request(self, owner: str, repo: str, pr_id: str) -> PullRequest:
        resp = self._request("GET", f"/repositories/{owner}/{repo}/pullrequests/{pr_id}")
        item = resp.json()
        raw_state = item.get("state", "OPEN")
        if raw_state == "OPEN":
            norm_state = "open"
        elif raw_state == "MERGED":
            norm_state = "merged"
        else:
            norm_state = "closed"

        return PullRequest(
            id=str(item["id"]),
            title=item.get("title", ""),
            description=item.get("description") or "",
            source_branch=item.get("source", {}).get("branch", {}).get("name", ""),
            target_branch=item.get("destination", {}).get("branch", {}).get("name", ""),
            state=norm_state,
            url=item.get("links", {}).get("html", {}).get("href", ""),
            author=item.get("author", {}).get("display_name", "")
            or item.get("author", {}).get("nickname", ""),
            created_at=item.get("created_on", ""),
        )

    def get_issue(self, owner: str, repo: str, issue_id: str) -> Issue:
        resp = self._request("GET", f"/repositories/{owner}/{repo}/issues/{issue_id}")
        item = resp.json()
        raw_state = item.get("state", "new")
        norm_state = "open" if raw_state in ("new", "open") else "closed"

        return Issue(
            id=str(item["id"]),
            title=item.get("title", ""),
            description=(
                item.get("content", {}).get("raw", "")
                if isinstance(item.get("content"), dict)
                else ""
            ),
            state=norm_state,
            url=item.get("links", {}).get("html", {}).get("href", ""),
            author=item.get("reporter", {}).get("display_name", "")
            or item.get("reporter", {}).get("nickname", ""),
            created_at=item.get("created_on", ""),
        )
