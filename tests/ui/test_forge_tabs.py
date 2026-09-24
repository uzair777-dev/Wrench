"""UI tests for PR and Issue tabs (FR-5.1 - FR-5.9)."""

import sqlite3
from pathlib import Path
from unittest.mock import MagicMock, patch

import pygit2
import pytest
from PySide6.QtWidgets import QApplication

from wrench.forge.capability import ForgeAdapter, ForgeCapability
from wrench.forge.models import CIStatus, Issue, PullRequest
from wrench.storage import forge_accounts, repo_registry
from wrench.storage.db import run_migrations
from wrench.ui.tabs.issue_detail_tab import IssueDetailTab
from wrench.ui.tabs.issue_list_tab import IssueListTab
from wrench.ui.tabs.pr_detail_tab import PRDetailTab
from wrench.ui.tabs.pr_list_tab import PRListTab


@pytest.fixture(autouse=True)
def app():
    instance = QApplication.instance()
    if not instance:
        instance = QApplication([])
    return instance


@pytest.fixture
def db_conn(tmp_path: Path):
    db_file = tmp_path / "test_tabs.db"
    conn = sqlite3.connect(str(db_file))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    run_migrations(conn)
    yield conn
    conn.close()


@pytest.fixture
def repo_fixture(tmp_path: Path, db_conn):
    repo_path = tmp_path / "tab_repo"
    repo_path.mkdir()
    pygit2_repo = pygit2.init_repository(str(repo_path))

    sig = pygit2.Signature("Dev", "dev@example.com")
    tree = pygit2_repo.TreeBuilder().write()
    pygit2_repo.create_commit("HEAD", sig, sig, "Initial commit", tree, [])
    pygit2_repo.remotes.create("origin", "https://github.com/alice/project.git")

    repo_id = repo_registry.add_repo(db_conn, str(repo_path), "tab_repo")

    mock_backend = MagicMock()
    mock_backend.get_secret.return_value = "fake_token_123"
    with patch("wrench.credentials.get_backend", return_value=mock_backend):
        acc_id = forge_accounts.add_account(
            db_conn,
            provider="github",
            instance_url="https://github.com",
            label="Work GitHub",
            username="alice",
            token="ghp_token",
        )
        forge_accounts.link_repo_to_account(
            db_conn,
            repo_id=repo_id,
            forge_account_id=acc_id,
            remote_name="origin",
            owner_slug="alice",
            repo_slug="project",
        )

    return str(repo_path), acc_id, repo_id, db_file_path(db_conn)


def db_file_path(conn):
    cur = conn.cursor()
    cur.execute("PRAGMA database_list")
    return cur.fetchone()[2]


class DummyAdapter(ForgeAdapter):
    provider_id = "github"

    @property
    def capabilities(self) -> ForgeCapability:
        return ForgeCapability.PULL_REQUESTS | ForgeCapability.ISSUES | ForgeCapability.CI_STATUS

    def _get_base_url(self) -> str:
        return "https://api.github.com"

    def _auth_headers_and_auth(self):
        return {"Authorization": "Bearer token"}, None

    def _get_scope_hint(self) -> str:
        return "repo"

    def list_pull_requests(self, owner, repo, state="open"):
        return [
            PullRequest(
                id="101",
                title="Add feature A",
                description="Implements feature A",
                source_branch="feature-a",
                target_branch="main",
                state="open",
                url="https://github.com/alice/project/pull/101",
                author="bob",
                created_at="2026-09-20T10:00:00Z",
            ),
            PullRequest(
                id="102",
                title="Fix bug in B",
                description="Resolves bug",
                source_branch="fix-b",
                target_branch="main",
                state="closed",
                url="https://github.com/alice/project/pull/102",
                author="charlie",
                created_at="2026-09-21T11:00:00Z",
            ),
        ]

    def get_pull_request(self, owner, repo, pr_id):
        return PullRequest(
            id=str(pr_id),
            title="Add feature A",
            description="Detailed markdown description",
            source_branch="feature-a",
            target_branch="main",
            state="open",
            url=f"https://github.com/alice/project/pull/{pr_id}",
            author="bob",
            created_at="2026-09-20T10:00:00Z",
        )

    def create_pull_request(
        self, owner, repo, *, title, source_branch, target_branch, description=""
    ):
        return PullRequest(
            id="103",
            title=title,
            description=description,
            source_branch=source_branch,
            target_branch=target_branch,
            state="open",
            url=f"https://github.com/{owner}/{repo}/pull/103",
            author="tester",
            created_at="2026-09-23T12:00:00Z",
        )

    def submit_review(self, owner, repo, number, *, action, body=""):
        pass

    def get_ci_status(self, owner, repo, ref):
        return CIStatus(
            state="success",
            url="https://github.com/alice/project/actions/runs/1",
            description="4/4 checks passed",
        )

    def list_issues(self, owner, repo, state="open"):
        return [
            Issue(
                id="1",
                title="Crash on startup",
                description="App crashes when opened",
                state="open",
                url="https://github.com/alice/project/issues/1",
                author="dave",
                created_at="2026-09-19T09:00:00Z",
            ),
            Issue(
                id="2",
                title="Documentation typo",
                description="Typo on readme",
                state="closed",
                url="https://github.com/alice/project/issues/2",
                author="eve",
                created_at="2026-09-18T08:00:00Z",
            ),
        ]

    def get_issue(self, owner, repo, issue_id):
        return Issue(
            id=str(issue_id),
            title="Crash on startup",
            description="Full issue description with traceback",
            state="open",
            url=f"https://github.com/alice/project/issues/{issue_id}",
            author="dave",
            created_at="2026-09-19T09:00:00Z",
        )


def _sync_run_in_background(fn, *args, on_finished=None, on_failed=None, **kwargs):
    """Synchronous runner for run_in_background in tests."""
    try:
        res = fn(*args)
        if on_finished:
            on_finished(res)
    except Exception as exc:
        if on_failed:
            on_failed(exc)


class TestPRListTab:
    def test_unlinked_repo_shows_unlinked_state(self, tmp_path, db_conn, qtbot):
        unlinked_path = str(tmp_path / "unlinked")
        db_path = db_file_path(db_conn)

        with patch(
            "wrench.storage.db.get_connection", side_effect=lambda: sqlite3.connect(db_path)
        ):
            tab = PRListTab(unlinked_path)
            qtbot.addWidget(tab)
            tab.show()
            assert not tab.empty_widget.isHidden()
            assert tab.table_view.isHidden()
            assert "Not Linked" in tab.empty_title.text()

    def test_linked_repo_loads_prs_and_filters(self, repo_fixture, qtbot):
        repo_path, acc_id, repo_id, db_path = repo_fixture

        with (
            patch("wrench.storage.db.get_connection", side_effect=lambda: sqlite3.connect(db_path)),
            patch("wrench.forge.registry.get_adapter_class", return_value=DummyAdapter),
            patch(
                "wrench.ui.tabs.pr_list_tab.run_in_background", side_effect=_sync_run_in_background
            ),
        ):
            tab = PRListTab(repo_path)
            qtbot.addWidget(tab)
            tab.show()
            tab.load_prs(bypass_cache=True)

            assert not tab.table_view.isHidden()
            assert tab.table_model.rowCount() == 2

            # Filter items
            tab.table_model.filter_items("feature")
            assert tab.table_model.rowCount() == 1
            pr = tab.table_model.get_pr_at(0)
            assert pr.id == "101"

            # Clear filter
            tab.table_model.filter_items("")
            assert tab.table_model.rowCount() == 2

    def test_pr_list_swr_cache(self, repo_fixture, qtbot):
        repo_path, _, _, db_path = repo_fixture

        with (
            patch("wrench.storage.db.get_connection", side_effect=lambda: sqlite3.connect(db_path)),
            patch("wrench.forge.registry.get_adapter_class", return_value=DummyAdapter),
            patch(
                "wrench.ui.tabs.pr_list_tab.run_in_background", side_effect=_sync_run_in_background
            ) as mock_run,
        ):
            tab = PRListTab(repo_path)
            qtbot.addWidget(tab)
            tab.show()
            tab.load_prs(bypass_cache=True)
            initial_call_count = mock_run.call_count

            # Immediate second call should hit SWR cache (<60s)
            tab.load_prs(bypass_cache=False)
            assert mock_run.call_count == initial_call_count

    def test_pr_list_selection_emitted(self, repo_fixture, qtbot):
        repo_path, _, _, db_path = repo_fixture

        with (
            patch("wrench.storage.db.get_connection", side_effect=lambda: sqlite3.connect(db_path)),
            patch("wrench.forge.registry.get_adapter_class", return_value=DummyAdapter),
            patch(
                "wrench.ui.tabs.pr_list_tab.run_in_background", side_effect=_sync_run_in_background
            ),
        ):
            tab = PRListTab(repo_path)
            qtbot.addWidget(tab)
            tab.show()
            tab.load_prs(bypass_cache=True)

            with qtbot.waitSignal(tab.pr_selected, timeout=1000) as blocker:
                model_idx = tab.table_model.index(0, 0)
                tab._on_row_double_clicked(model_idx)

            assert blocker.args == [repo_path, "origin", "101"]


class TestPRDetailTab:
    def test_pr_detail_loads_and_displays(self, repo_fixture, qtbot):
        repo_path, _, _, db_path = repo_fixture

        with (
            patch("wrench.storage.db.get_connection", side_effect=lambda: sqlite3.connect(db_path)),
            patch("wrench.forge.registry.get_adapter_class", return_value=DummyAdapter),
            patch(
                "wrench.ui.tabs.pr_detail_tab.run_in_background",
                side_effect=_sync_run_in_background,
            ),
        ):
            detail = PRDetailTab(repo_path, "origin", "101")
            qtbot.addWidget(detail)
            detail.show()

            assert "#101: Add feature A" in detail.title_label.text()
            assert detail.state_badge.text() == "Open"
            assert "origin · Github" in detail.remote_badge.text()
            assert "4/4 checks passed" in detail.ci_desc_label.text()
            assert "Detailed markdown description" in detail.desc_viewer.toPlainText()

            # Stale repo check
            detail.set_active_repository("/tmp/another_repo")
            assert not detail.stale_banner.isHidden()

            detail.set_active_repository(repo_path)
            assert detail.stale_banner.isHidden()


class TestIssueTabs:
    def test_issue_list_and_detail(self, repo_fixture, qtbot):
        repo_path, _, _, db_path = repo_fixture

        with (
            patch("wrench.storage.db.get_connection", side_effect=lambda: sqlite3.connect(db_path)),
            patch("wrench.forge.registry.get_adapter_class", return_value=DummyAdapter),
            patch(
                "wrench.ui.tabs.issue_list_tab.run_in_background",
                side_effect=_sync_run_in_background,
            ),
            patch(
                "wrench.ui.tabs.issue_detail_tab.run_in_background",
                side_effect=_sync_run_in_background,
            ),
        ):
            # 1. Issue List Tab
            tab = IssueListTab(repo_path)
            qtbot.addWidget(tab)
            tab.show()
            tab.load_issues(bypass_cache=True)

            assert not tab.table_view.isHidden()
            assert tab.table_model.rowCount() == 2

            tab.table_model.filter_items("Crash")
            assert tab.table_model.rowCount() == 1

            with qtbot.waitSignal(tab.issue_selected, timeout=1000) as blocker:
                model_idx = tab.table_model.index(0, 0)
                tab._on_row_double_clicked(model_idx)

            assert blocker.args == [repo_path, "origin", "1"]

            # 2. Issue Detail Tab
            detail = IssueDetailTab(repo_path, "origin", "1")
            qtbot.addWidget(detail)
            detail.show()
            assert "#1: Crash on startup" in detail.title_label.text()
            assert detail.state_badge.text() == "Open"
            assert "Full issue description" in detail.desc_viewer.toPlainText()
