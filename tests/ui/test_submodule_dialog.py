"""UI tests for SubmoduleDialog."""

from pathlib import Path
from unittest.mock import patch

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox, QPushButton

from wrench.core.engine import init_repo, open_repo
from wrench.core.models import Submodule, SubmoduleStatus
from wrench.ui.dialogs.submodule_dialog import SubmoduleDialog


@pytest.fixture(autouse=True)
def app():
    instance = QApplication.instance()
    if not instance:
        instance = QApplication([])
    return instance


@pytest.fixture
def mock_repo(tmp_path: Path):
    repo_path = tmp_path / "ui_submodule_repo"
    repo_path.mkdir()
    init_repo(repo_path)
    return open_repo(repo_path)


def test_submodule_dialog_empty_repo(mock_repo):
    dialog = SubmoduleDialog(mock_repo)
    try:
        assert dialog.windowTitle() == "Submodules"
        assert dialog.table.rowCount() == 0
        assert dialog.table.columnCount() == 5
        assert dialog.table.horizontalHeaderItem(0).text() == "Path"
        assert dialog.table.horizontalHeaderItem(1).text() == "URL"
        assert dialog.table.horizontalHeaderItem(4).text() == "Actions"
        assert dialog.url_input.text() == ""
        assert dialog.path_input.text() == ""
    finally:
        dialog.close()


def test_submodule_dialog_with_items(mock_repo):
    fake_submodules = [
        Submodule(path="vendor/liba", url="https://github.com/ex/liba.git", initialized=True),
        Submodule(path="vendor/libb", url="https://github.com/ex/libb.git", initialized=False),
    ]

    def mock_status(repo, path):
        if path == "vendor/liba":
            return SubmoduleStatus(path=path, current_commit="1234567890abcdef", is_dirty=False)
        return SubmoduleStatus(path=path, current_commit="", is_dirty=False)

    with (
        patch("wrench.core.engine.list_submodules", return_value=fake_submodules),
        patch("wrench.core.engine.submodule_status", side_effect=mock_status),
    ):
        dialog = SubmoduleDialog(mock_repo)
        try:
            assert dialog.table.rowCount() == 2

            # Row 0: Initialized
            assert dialog.table.item(0, 0).text() == "vendor/liba"
            assert dialog.table.item(0, 1).text() == "https://github.com/ex/liba.git"
            assert dialog.table.item(0, 2).text() == "1234567"
            assert "Clean" in dialog.table.item(0, 3).text()

            # Row 1: Uninitialized
            assert dialog.table.item(1, 0).text() == "vendor/libb"
            assert "Uninitialized" in dialog.table.item(1, 3).text()

            # Verify action widgets exist
            widget0 = dialog.table.cellWidget(0, 4)
            assert widget0 is not None
            buttons0 = widget0.findChildren(QPushButton)
            assert len(buttons0) == 2
            # Lib A is initialized, so Init button should be disabled
            init_btn0 = next(b for b in buttons0 if b.text() == "Init")
            assert not init_btn0.isEnabled()

            widget1 = dialog.table.cellWidget(1, 4)
            buttons1 = widget1.findChildren(QPushButton)
            init_btn1 = next(b for b in buttons1 if b.text() == "Init")
            assert init_btn1.isEnabled()
        finally:
            dialog.close()


def test_submodule_dialog_actions(mock_repo):
    dialog = SubmoduleDialog(mock_repo)
    try:
        # Test Add validation when fields empty
        with patch.object(QMessageBox, "warning") as mock_warn:
            dialog._on_add_submodule()
            mock_warn.assert_called_once()

        # Test Add submodule success
        with (
            patch("wrench.core.engine.add_submodule") as mock_add,
            patch.object(dialog, "refresh") as mock_refresh,
        ):
            dialog.url_input.setText("https://github.com/example/tool.git")
            dialog.path_input.setText("tools/subtool")
            dialog._on_add_submodule()
            mock_add.assert_called_once_with(
                mock_repo,
                url="https://github.com/example/tool.git",
                path="tools/subtool",
            )
            mock_refresh.assert_called_once()
            assert dialog.url_input.text() == ""
            assert dialog.path_input.text() == ""

        # Test Update All
        with (
            patch("wrench.core.engine.update_submodules") as mock_update,
            patch.object(dialog, "refresh") as mock_refresh,
        ):
            dialog._on_update_all()
            mock_update.assert_called_once_with(mock_repo, recursive=True)
            mock_refresh.assert_called_once()
    finally:
        dialog.close()
