"""FR-5.5: Bitbucket adapter."""

from ..capability import ForgeAdapter, ForgeCapability
from ..models import CIStatus, ForgeAccount, PullRequest


class BitbucketAdapter(ForgeAdapter):
    provider_id = "bitbucket"

    @property
    def capabilities(self) -> ForgeCapability:
        return ForgeCapability.PULL_REQUESTS | ForgeCapability.ISSUES | ForgeCapability.CI_STATUS

    def authenticate(self, account: ForgeAccount) -> None:
        raise NotImplementedError

    def list_pull_requests(self, owner: str, repo: str) -> list[PullRequest]:
        raise NotImplementedError

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
        raise NotImplementedError

    def get_ci_status(self, owner: str, repo: str, ref: str) -> CIStatus:
        raise NotImplementedError
