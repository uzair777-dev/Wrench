"""ForgeCapability enum and ForgeAdapter ABC."""

import logging
from abc import ABC, abstractmethod
from enum import Flag, auto
from typing import Any

import httpx

from wrench import credentials
from wrench.forge.exceptions import (
    ForgeAuthenticationError,
    ForgeError,
    ForgeInsufficientScopeError,
    ForgeRateLimitedError,
    ForgeUnreachableError,
)
from wrench.forge.models import CIStatus, ForgeAccount, Issue, PullRequest

logger = logging.getLogger(__name__)


class ForgeCapability(Flag):
    PULL_REQUESTS = auto()
    ISSUES = auto()
    CI_STATUS = auto()
    ISSUE_LINKING = auto()
    REVIEWS = auto()


class ForgeAdapter(ABC):
    """Abstract base class for forge provider adapters.

    One instance per background worker operation. Never shared across threads.
    """

    provider_id: str
    account: ForgeAccount

    def __init__(self, account: ForgeAccount) -> None:
        self.account = account
        self._cached_token: str | None = None

        # Resolve TLS policy
        verify: bool | str = True
        if account.tls_insecure:
            verify = False
            logger.warning(
                "TLS verification disabled for forge account '%s' (%s)",
                account.label,
                account.instance_url,
            )
        elif account.tls_ca_bundle_path:
            verify = account.tls_ca_bundle_path

        self._client = httpx.Client(
            base_url=self._get_base_url(),
            verify=verify,
            timeout=httpx.Timeout(connect=10.0, read=30.0, write=10.0, pool=10.0),
            limits=httpx.Limits(
                max_keepalive_connections=5, max_connections=10, keepalive_expiry=30.0
            ),
            follow_redirects=True,
        )

    def close(self) -> None:
        """Close the underlying HTTP client."""
        self._client.close()

    def __enter__(self) -> "ForgeAdapter":
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()

    @property
    @abstractmethod
    def capabilities(self) -> ForgeCapability: ...

    @property
    def supported_review_actions(self) -> frozenset[str]:
        """Subset of {'approve', 'request_changes', 'comment'} supported by this provider."""
        return frozenset({"approve", "request_changes", "comment"})

    @abstractmethod
    def _get_base_url(self) -> str: ...

    @abstractmethod
    def _auth_headers_and_auth(self) -> tuple[dict[str, str], httpx.Auth | None]: ...

    @abstractmethod
    def _get_scope_hint(self) -> str: ...

    def _get_token(self) -> str:
        if self._cached_token is None:
            backend = credentials.get_backend()
            secret = backend.get_secret(self.account.secret_service_key)
            if not secret:
                raise ForgeAuthenticationError(
                    f"No token found in credential store for account '{self.account.label}'"
                )
            self._cached_token = secret
        return self._cached_token

    def authenticate(self) -> None:
        """Validate stored credentials against provider identity endpoint."""
        self._request("GET", "/user")

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any = None,
    ) -> httpx.Response:
        """Centralized HTTP dispatcher with error mapping and secret token protection."""
        headers, auth = self._auth_headers_and_auth()
        try:
            resp = self._client.request(
                method, path, params=params, json=json, headers=headers, auth=auth
            )
        except (httpx.ConnectError, httpx.TimeoutException) as e:
            msg = str(e)
            if "SSL" in msg and not self.account.tls_insecure:
                msg += (
                    " (if using self-signed certs, configure custom CA bundle in account settings)"
                )
            raise ForgeUnreachableError(self.account.instance_url, msg) from e

        if resp.status_code in (400, 401) and "cannot approve" in resp.text.lower():
            raise ForgeError("You cannot approve your own merge request.")

        if resp.status_code == 401:
            raise ForgeAuthenticationError(
                f"{self.account.provider} token for '{self.account.label}' "
                "was rejected — expired or revoked"
            )
        if resp.status_code == 403:
            # Trap GitHub secondary rate limit disguised as 403
            if (
                resp.headers.get("x-ratelimit-remaining") == "0"
                or "rate limit" in resp.text.lower()
            ):
                reset_epoch = int(resp.headers.get("x-ratelimit-reset", "0"))
                import time

                diff = max(1, reset_epoch - int(time.time())) if reset_epoch > 0 else 60
                raise ForgeRateLimitedError(diff)

            raise ForgeInsufficientScopeError(
                f"{self.account.provider} token lacks required permissions",
                scope_hint=self._get_scope_hint(),
            )
        if resp.status_code == 429:
            retry_after = int(resp.headers.get("Retry-After", "60"))
            raise ForgeRateLimitedError(retry_after)
        if resp.status_code == 422:
            # Extract actionable validation message from provider payload
            msg = ""
            try:
                err_data = resp.json()
                if isinstance(err_data, dict):
                    msg = err_data.get("message") or ""
                    if "errors" in err_data and isinstance(err_data["errors"], list):
                        details = [
                            e.get("message", "")
                            for e in err_data["errors"]
                            if isinstance(e, dict) and e.get("message")
                        ]
                        if details:
                            msg += f": {', '.join(details)}"
            except (ValueError, KeyError):
                pass
            if not msg:
                msg = resp.text[:300]
            raise ForgeError(f"{self.account.provider} validation error: {msg}")
        if resp.status_code >= 400:
            raise ForgeError(
                f"{self.account.provider} API error {resp.status_code}: {resp.text[:300]}"
            )

        return resp

    def _paged_get(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        *,
        per_page: int = 50,
        max_pages: int = 10,
    ) -> list[dict[str, Any]]:
        """Paginated retrieval with a runaway guard capped at max_pages (default 10 / 500 items)."""
        all_items: list[dict[str, Any]] = []
        current_params = dict(params or {})
        current_page = 1
        current_path = path

        while current_page <= max_pages:
            resp = self._request("GET", current_path, params=current_params)
            data = resp.json()

            # Handle list root vs dict root (Bitbucket returns {'values': [...]})
            if isinstance(data, list):
                items = data
            elif isinstance(data, dict) and "values" in data:
                items = data["values"]
            else:
                break

            all_items.extend(items)

            # Check next page mechanism
            if isinstance(data, dict) and data.get("next"):
                # Bitbucket style: full next URL
                current_path = data["next"]
                current_params = {}
            elif "link" in resp.headers and 'rel="next"' in resp.headers["link"]:
                # GitHub / GitLab style RFC 5988 Link header
                links = resp.headers["link"].split(",")
                next_url = None
                for link in links:
                    if 'rel="next"' in link:
                        next_url = link.split(";")[0].strip("<> ")
                        break
                if not next_url:
                    break
                current_path = next_url
                current_params = {}
            elif len(items) >= per_page:
                # Page/limit fallback (Forgejo)
                current_page += 1
                current_params["page"] = current_page
                current_params["limit"] = per_page
            else:
                break

            current_page += 1

        return all_items

    @abstractmethod
    def list_pull_requests(
        self, owner: str, repo: str, state: str = "open"
    ) -> list[PullRequest]: ...

    @abstractmethod
    def create_pull_request(
        self,
        owner: str,
        repo: str,
        *,
        title: str,
        source_branch: str,
        target_branch: str,
        description: str = "",
    ) -> PullRequest: ...

    @abstractmethod
    def submit_review(
        self,
        owner: str,
        repo: str,
        number: int,
        *,
        action: str,  # 'approve' | 'request_changes' | 'comment'
        body: str = "",
    ) -> None: ...

    @abstractmethod
    def get_ci_status(self, owner: str, repo: str, ref: str) -> CIStatus: ...

    def list_issues(self, owner: str, repo: str, state: str = "open") -> list[Issue]:
        raise NotImplementedError(f"{self.provider_id} does not support issues")

    def get_pull_request(self, owner: str, repo: str, pr_id: str) -> PullRequest:
        """Fetch details for a single pull request by ID or number."""
        raise NotImplementedError(f"{self.provider_id} does not support get_pull_request")

    def get_issue(self, owner: str, repo: str, issue_id: str) -> Issue:
        """Fetch details for a single issue by ID or number."""
        raise NotImplementedError(f"{self.provider_id} does not support issues")
