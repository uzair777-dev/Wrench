from pathlib import Path

from PySide6.QtCore import Qt

from wrench.ui.dialogs.discover_repos_dialog import DiscoverReposDialog


def test_discover_repos_dialog_selection(qapp):
    repos = [Path("/repos/repo1"), Path("/repos/repo2"), Path("/repos/repo3")]
    dlg = DiscoverReposDialog(repos=repos, root_dir=Path("/repos"))
    dlg.show()

    assert dlg.repo_list.count() == 3
    # All items should be checked by default
    for i in range(3):
        item = dlg.repo_list.item(i)
        assert item.checkState() == Qt.CheckState.Checked

    assert dlg.selected_repositories() == repos

    # Deselect all
    dlg.btn_deselect_all.click()
    for i in range(3):
        assert dlg.repo_list.item(i).checkState() == Qt.CheckState.Unchecked
    assert dlg.selected_repositories() == []

    # Select all
    dlg.btn_select_all.click()
    for i in range(3):
        assert dlg.repo_list.item(i).checkState() == Qt.CheckState.Checked
    assert dlg.selected_repositories() == repos

    # Uncheck one item
    dlg.repo_list.item(1).setCheckState(Qt.CheckState.Unchecked)
    assert dlg.selected_repositories() == [Path("/repos/repo1"), Path("/repos/repo3")]

    dlg.close()


def test_discover_repos_dialog_empty_list(qapp):
    dlg = DiscoverReposDialog(repos=[], root_dir=Path("/empty"))
    dlg.show()
    assert dlg.repo_list.count() == 0
    assert dlg.selected_repositories() == []
    dlg.close()


def test_main_window_open_repo_branches_to_discovery(qtbot, monkeypatch, tmp_path):
    import sqlite3
    from unittest.mock import MagicMock

    from PySide6.QtWidgets import QDialog, QFileDialog

    from wrench.core.exceptions import WrenchRepoNotFoundError
    from wrench.storage import repo_registry
    from wrench.storage.db import run_migrations
    from wrench.ui.main_window import MainWindow

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    run_migrations(conn)

    mw = MainWindow(conn=conn)
    qtbot.addWidget(mw)
    mw.show()

    forest = tmp_path / "forest"
    forest.mkdir()
    r1 = forest / "repo1"
    r1.mkdir()
    r2 = forest / "repo2"
    r2.mkdir()
    discovered = [r1.resolve(), r2.resolve()]

    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *args, **kwargs: str(forest))

    def mock_open(path):
        if str(path) == str(forest):
            raise WrenchRepoNotFoundError("Not a git repository")
        mock_handle = MagicMock()
        mock_handle.path = Path(path)
        return mock_handle

    monkeypatch.setattr("wrench.core.engine.open_repo", mock_open)
    monkeypatch.setattr("wrench.core.engine.discover_repos", lambda *args, **kwargs: discovered)

    # Automatically accept dialog when it executes
    monkeypatch.setattr(DiscoverReposDialog, "exec", lambda self: QDialog.DialogCode.Accepted)
    monkeypatch.setattr(DiscoverReposDialog, "exec_", lambda self: QDialog.DialogCode.Accepted)

    mw._on_open_repo()
    qtbot.waitUntil(
        lambda: repo_registry.get_repo_by_path(conn, str(r1.resolve())) is not None,
        timeout=5000,
    )

    # Verify discovered repositories were added to registry
    assert repo_registry.get_repo_by_path(conn, str(r1.resolve())) is not None
    assert repo_registry.get_repo_by_path(conn, str(r2.resolve())) is not None
    mw.close()
    conn.close()


def test_main_window_open_repo_fast_path(qtbot, monkeypatch, tmp_path):
    import sqlite3
    from unittest.mock import MagicMock

    from PySide6.QtWidgets import QFileDialog

    from wrench.storage import repo_registry
    from wrench.storage.db import run_migrations
    from wrench.ui.main_window import MainWindow

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    run_migrations(conn)

    mw = MainWindow(conn=conn)
    qtbot.addWidget(mw)
    mw.show()

    mock_repo_path = tmp_path / "single_repo"
    mock_repo_path.mkdir()
    (mock_repo_path / ".git").mkdir()

    monkeypatch.setattr(
        QFileDialog, "getExistingDirectory", lambda *args, **kwargs: str(mock_repo_path)
    )
    monkeypatch.setattr("wrench.core.engine.open_repo", lambda path: MagicMock(path=Path(path)))
    discover_mock = MagicMock()
    monkeypatch.setattr("wrench.core.engine.discover_repos", discover_mock)

    mw._on_open_repo()

    # Fast path should succeed and never call discover_repos
    assert discover_mock.call_count == 0
    assert repo_registry.get_repo_by_path(conn, str(mock_repo_path.resolve())) is not None
    mw.close()
    conn.close()
