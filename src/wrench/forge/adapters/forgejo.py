"""FR-5.4: Forgejo/Gitea adapter."""

from ..capability import ForgeAdapter, ForgeCapability
from ..models import CIStatus, ForgeAccount, PullRequest


class ForgejoAdapter(ForgeAdapter):
    provider_id = "forgejo"

    @property
    def capabilities(self) -> ForgeCapability:
        return (
            ForgeCapability.PULL_REQUESTS
            | ForgeCapability.ISSUES
            | ForgeCapability.CI_STATUS
            | ForgeCapability.ISSUE_LINKING
        )

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
