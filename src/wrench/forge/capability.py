"""ForgeCapability enum and ForgeAdapter ABC."""

from abc import ABC, abstractmethod
from enum import Flag, auto

from .models import CIStatus, ForgeAccount, Issue, PullRequest


class ForgeCapability(Flag):
    PULL_REQUESTS = auto()
    ISSUES = auto()
    CI_STATUS = auto()
    ISSUE_LINKING = auto()


class ForgeAdapter(ABC):
    """One instance per configured forge_account row."""

    provider_id: str

    @property
    @abstractmethod
    def capabilities(self) -> ForgeCapability: ...

    @abstractmethod
    def authenticate(self, account: ForgeAccount) -> None:
        """Validate stored credentials against the API; raise ForgeAuthError on failure."""

    @abstractmethod
    def list_pull_requests(self, owner: str, repo: str) -> list[PullRequest]: ...

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
    def get_ci_status(self, owner: str, repo: str, ref: str) -> CIStatus: ...

    def list_issues(self, owner: str, repo: str) -> list[Issue]:
        raise NotImplementedError(f"{self.provider_id} does not support issues")
