import sqlite3
from unittest.mock import MagicMock, patch

import pytest
from PySide6.QtWidgets import QApplication

from wrench.storage.db import run_migrations
from wrench.ui.dialogs.settings_dialog import RepositoriesPage
from wrench.ui.main_window import MainWindow


@pytest.fixture
def db_conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    run_migrations(conn)
    yield conn
    conn.close()


def test_repositories_page_network_group_elements(qapp: QApplication, db_conn):
    win = MainWindow(conn=db_conn)
    page = RepositoriesPage(win)
    assert hasattr(page, "spin_post_buffer")
    assert hasattr(page, "combo_http_version")
    assert hasattr(page, "combo_network_scope")
    assert hasattr(page, "btn_apply_network")
    assert page.spin_post_buffer.suffix() == " MB"
    win.close()


def test_repositories_page_network_load_and_save(qapp: QApplication, db_conn):
    win = MainWindow(conn=db_conn)
    fake_repo = MagicMock()
    fake_repo.path = "/fake/repo"
    win._current_repo = fake_repo

    page = RepositoriesPage(win)

    with (
        patch("wrench.core.engine.get_http_post_buffer") as mock_get_buf,
        patch("wrench.core.engine.get_http_version") as mock_get_ver,
        patch("wrench.core.engine.set_http_post_buffer") as mock_set_buf,
        patch("wrench.core.engine.set_http_version") as mock_set_ver,
    ):
        mock_get_buf.return_value = 524288000  # 500 MB
        mock_get_ver.return_value = "HTTP/1.1"

        page.load()
        assert page.spin_post_buffer.value() == 500
        assert page.combo_http_version.currentData() == "HTTP/1.1"

        # Change buffer to 1024 MB and click apply
        page.spin_post_buffer.setValue(1024)
        page._on_apply_network_settings()

        mock_set_buf.assert_called_once_with(fake_repo, 1024 * 1024 * 1024, scope="local")
        mock_set_ver.assert_called_once_with(fake_repo, "HTTP/1.1", scope="local")
        assert "1024 MB" in page.network_status_label.text()
    win.close()
