"""Offscreen UI & MainWindow wiring tests for InteractiveRebaseDialog (VP-2, FR-3.5)."""

from __future__ import annotations

import sqlite3
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from PySide6.QtCore import QMimeData, QPointF, Qt, QThreadPool, QTimer
from PySide6.QtGui import QDropEvent
from PySide6.QtWidgets import QApplication, QComboBox, QDialog, QMenu

from wrench.core import engine
from wrench.core.models import RebaseTodoEntry
from wrench.storage.db import run_migrations
from wrench.storage.settings_registry import SettingsRegistry
from wrench.ui.commit_graph.graph_widget import CommitGraphWidget
from wrench.ui.dialogs.interactive_rebase_dialog import InteractiveRebaseDialog
from wrench.ui.dialogs.settings_dialog import SettingsDialog
from wrench.ui.main_window import MainWindow
from wrench.ui.theme import (
    PRIMARY_BUTTON_STYLES,
    REBASE_ACTION_COLORS,
    TREE_WIDGET_STYLES,
    create_pastel_dark_palette,
    create_pastel_light_palette,
    get_banner_style,
    is_dark_theme,
)


@pytest.fixture(autouse=True)
def app():
    instance = QApplication.instance()
    if not instance:
        instance = QApplication([])
    return instance


@pytest.fixture
def db_conn():
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    run_migrations(conn)
    yield conn
    conn.close()


def _git(cwd: Path, *args: str) -> str:
    res = subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=True,
    )
    return res.stdout.strip()


def _make_linear_repo(path: Path) -> tuple[Path, str, list[str]]:
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init", "-b", "main")
    _git(path, "config", "user.name", "Test Runner")
    _git(path, "config", "user.email", "runner@wrench.test")

    (path / "base.txt").write_text("base\n")
    _git(path, "add", "base.txt")
    _git(path, "commit", "-m", "Base commit")
    base_oid = _git(path, "rev-parse", "HEAD")

    oids: list[str] = []
    for idx, name in enumerate(("First feature", "Second feature", "Third feature"), start=1):
        (path / f"f{idx}.txt").write_text(f"content {idx}\n")
        _git(path, "add", f"f{idx}.txt")
        _git(path, "commit", "-m", name)
        oids.append(_git(path, "rev-parse", "HEAD"))

    return path, base_oid, oids


def _drain_workers(app: QApplication) -> None:
    assert QThreadPool.globalInstance().waitForDone(5000) is True
    app.processEvents()
    app.processEvents()


def test_dialog_loads_commits_and_cli_preview(
    app: QApplication, db_conn: sqlite3.Connection, tmp_path: Path
) -> None:
    repo_path, base_oid, _ = _make_linear_repo(tmp_path / "ui_load")
    reg = SettingsRegistry(db_conn)
    reg.set("rebase.autostash", True)
    reg.set("rebase.autosquash", False)

    # Switch to detached HEAD to verify detached summary label rendering cleanly.
    head_oid = _git(repo_path, "rev-parse", "HEAD")
    _git(repo_path, "checkout", "--detach", head_oid)

    dlg = InteractiveRebaseDialog(repo_path, base_oid, settings_registry=reg)
    try:
        _drain_workers(app)
        entries = dlg.planned_entries()
        assert [e.summary for e in entries] == [
            "First feature",
            "Second feature",
            "Third feature",
        ]
        assert dlg.todo_table.rowCount() == 3
        assert "detached HEAD" in dlg.summary_label.text()
        assert dlg.start_btn.isEnabled() is True
        assert dlg.validation_banner.isHidden() is True

        preview_txt = dlg.preview_bar.command_label.text()
        assert "rebase -i" in preview_txt
        assert "--autostash" in preview_txt
        assert "--autosquash" not in preview_txt
        assert f"-- {base_oid}" in preview_txt

        dlg.autosquash_cb.setChecked(True)
        app.processEvents()
        assert "--autosquash" in dlg.preview_bar.command_label.text()
    finally:
        dlg.close()


def test_reordering_actions_and_inline_message_editor(
    app: QApplication, db_conn: sqlite3.Connection, tmp_path: Path
) -> None:
    repo_path, base_oid, _ = _make_linear_repo(tmp_path / "ui_reorder")
    reg = SettingsRegistry(db_conn)

    dlg = InteractiveRebaseDialog(repo_path, base_oid, settings_registry=reg)
    try:
        _drain_workers(app)
        dlg.show()
        app.processEvents()

        # Reorder row 2 ("Third feature") up to row 0 via move_row and verify combo survival.
        dlg.move_row(2, 0)
        app.processEvents()
        assert [e.summary for e in dlg.planned_entries()] == [
            "Third feature",
            "First feature",
            "Second feature",
        ]
        assert isinstance(dlg.todo_table.cellWidget(0, 1), QComboBox)
        assert isinstance(dlg.todo_table.cellWidget(1, 1), QComboBox)
        assert isinstance(dlg.todo_table.cellWidget(2, 1), QComboBox)

        # Simulate Qt6 QDropEvent using QPointF position onto row 1.
        dlg.todo_table.selectRow(0)
        app.processEvents()
        row1_rect = dlg.todo_table.visualRect(dlg.todo_table.model().index(1, 0))
        drop_center = QPointF(row1_rect.center())
        mime = QMimeData()
        drop_evt = QDropEvent(
            drop_center,
            Qt.DropAction.MoveAction,
            mime,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        dlg.todo_table.dropEvent(drop_evt)
        app.processEvents()
        assert len(dlg.planned_entries()) == 3
        assert isinstance(dlg.todo_table.cellWidget(1, 1), QComboBox)

        # Selecting `reword` shows inline QPlainTextEdit and validates non-empty messages.
        dlg.set_row_action(0, "reword")
        app.processEvents()
        assert dlg.message_editor_container.isHidden() is False
        dlg.message_edit.setPlainText("Edited message line 1\n\nBody details")
        app.processEvents()
        assert dlg.planned_entries()[0].new_message == "Edited message line 1\n\nBody details"
        assert dlg.start_btn.isEnabled() is True

        # Empty reword message disables Start Rebase and shows validation banner.
        dlg.message_edit.setPlainText("   \n  ")
        app.processEvents()
        assert dlg.start_btn.isEnabled() is False
        assert dlg.validation_banner.isHidden() is False
        assert "cannot be empty" in dlg.validation_label.text()

        # Clearing squash message leaves new_message=None and remains valid on row 1.
        dlg.set_row_action(0, "pick")
        dlg.todo_table.selectRow(1)
        dlg.set_row_action(1, "squash")
        app.processEvents()
        assert dlg.message_editor_container.isHidden() is False
        assert dlg.planned_entries()[1].new_message is None
        assert dlg.start_btn.isEnabled() is True
    finally:
        dlg.close()


def test_first_row_squash_fixup_and_truncated_range_block_start(
    app: QApplication, db_conn: sqlite3.Connection, tmp_path: Path
) -> None:
    repo_path, base_oid, _ = _make_linear_repo(tmp_path / "ui_validate")
    reg = SettingsRegistry(db_conn)

    dlg = InteractiveRebaseDialog(repo_path, base_oid, settings_registry=reg)
    try:
        _drain_workers(app)
        dlg.set_row_action(0, "squash")
        app.processEvents()
        assert dlg.start_btn.isEnabled() is False
        assert dlg.validation_banner.isHidden() is False
        assert "first commit" in dlg.validation_label.text().lower()

        dlg.set_row_action(0, "fixup")
        app.processEvents()
        assert dlg.start_btn.isEnabled() is False

        dlg.set_row_action(0, "pick")
        app.processEvents()
        assert dlg.start_btn.isEnabled() is True
        assert dlg.validation_banner.isHidden() is True

        # Truncated range (> 1000 commits) must block execution loudly.
        dlg._on_commits_ready(
            dlg._load_generation,
            [
                RebaseTodoEntry(
                    action="pick",
                    oid="1" * 40,
                    short_oid="1" * 7,
                    summary="One",
                    author="Test Runner",
                )
            ],
            True,
            "main",
            base_oid[:7],
            False,
        )
        app.processEvents()
        assert dlg.start_btn.isEnabled() is False
        assert "1000" in dlg.validation_label.text()
    finally:
        dlg.close()


def test_start_rebase_worker_non_blocking_and_secret_redaction(
    app: QApplication, db_conn: sqlite3.Connection, tmp_path: Path
) -> None:
    repo_path, base_oid, _ = _make_linear_repo(tmp_path / "ui_exec")
    reg = SettingsRegistry(db_conn)

    dlg = InteractiveRebaseDialog(repo_path, base_oid, settings_registry=reg)
    try:
        _drain_workers(app)
        dlg.show()
        app.processEvents()

        # Swap 2nd and 3rd commits, fixup 2nd into 1st, reword 1st.
        dlg.set_row_action(0, "reword")
        dlg.message_edit.setPlainText("Combined first")
        dlg.set_row_action(1, "fixup")
        app.processEvents()

        started: list[bool] = []
        completed: list[object] = []
        dlg.rebase_started.connect(lambda: started.append(True))
        dlg.rebase_completed.connect(completed.append)

        dlg.start_btn.click()
        _drain_workers(app)

        assert started == [True]
        assert len(completed) == 1
        assert completed[0].status == "complete"
        assert dlg.result() == QDialog.DialogCode.Accepted
        log_lines = _git(repo_path, "log", "--format=%s", f"{base_oid}..HEAD").splitlines()
        assert log_lines == ["Third feature", "Combined first"]
    finally:
        dlg.close()

    # Secret redaction check when worker fails with token in stderr
    err_dlg = InteractiveRebaseDialog(repo_path, base_oid, settings_registry=reg)
    try:
        _drain_workers(app)
        err_dlg._on_rebase_failed(
            err_dlg._run_generation,
            "fatal: index.lock failed on https://alice:glpat-supersecret123@gitlab.com/org/repo.git",
            True,
        )
        app.processEvents()
        assert "glpat-supersecret123" not in err_dlg.validation_label.text()
        assert err_dlg.retry_btn.isHidden() is False
        assert err_dlg.validation_banner.isHidden() is False
    finally:
        err_dlg.close()


def test_feature_toggle_context_menu_mainwindow_and_themes(
    app: QApplication, db_conn: sqlite3.Connection, tmp_path: Path
) -> None:
    repo_path, base_oid, _ = _make_linear_repo(tmp_path / "ui_wiring")
    repo = engine.open_repo(repo_path)

    win = MainWindow(conn=db_conn)
    reg = win._settings_registry
    try:
        win._on_repo_changed(str(repo_path))
        app.processEvents()
        win.tab_container.set_current_index(1)  # History tab
        app.processEvents()
        _drain_workers(app)

        # 1. Context menu item visible when rebase.interactive_ui.enabled=True, hidden when False
        graph: CommitGraphWidget = win.history_tab.graph_widget
        if graph._model.rowCount() == 0:
            commits = engine.get_commits(repo, limit=10)
            graph.load_commits(repo, commits, {})
            app.processEvents()

        target_row = min(1, max(0, graph._model.rowCount() - 1))
        pos = graph.visualRect(graph._model.index(target_row, 0)).center()

        seen_labels_enabled: list[str] = []

        class _TriggerInteractiveMenu(QMenu):
            def exec(self, *_args, **_kwargs):
                chosen = None
                for act in self.actions():
                    if act.text():
                        seen_labels_enabled.append(act.text())
                    if "Interactive Rebase" in act.text() and chosen is None:
                        chosen = act
                return chosen

        with (
            patch("wrench.ui.commit_graph.graph_widget.QMenu", _TriggerInteractiveMenu),
            patch.object(
                win, "_exec_dialog", return_value=int(QDialog.DialogCode.Rejected)
            ) as spy_exec,
        ):
            reg.set("rebase.interactive_ui.enabled", True)
            app.processEvents()
            graph._show_context_menu(pos)
            assert any("Interactive Rebase" in lbl for lbl in seen_labels_enabled)
            assert spy_exec.call_count == 1
            assert isinstance(spy_exec.call_args[0][0], InteractiveRebaseDialog)

        seen_labels_disabled: list[str] = []

        class _InspectMenu(QMenu):
            def exec(self, *_args, **_kwargs):
                for act in self.actions():
                    if act.text():
                        seen_labels_disabled.append(act.text())
                return None

        with (
            patch("wrench.ui.commit_graph.graph_widget.QMenu", _InspectMenu),
            patch.object(
                win, "_exec_dialog", return_value=int(QDialog.DialogCode.Rejected)
            ) as spy_exec_off,
        ):
            reg.set("rebase.interactive_ui.enabled", False)
            app.processEvents()
            graph._show_context_menu(pos)
            assert not any("Interactive Rebase" in lbl for lbl in seen_labels_disabled)
            # Even direct signal emission must gate when toggle is disabled.
            win._on_history_interactive_rebase(base_oid)
            assert spy_exec_off.call_count == 0

        # 2. Watcher suspend/resume always balanced when MainWindow runs InteractiveRebaseDialog
        reg.set("rebase.interactive_ui.enabled", True)
        app.processEvents()
        if win._watcher is not None:
            win._watcher.stop()
        mock_watcher = MagicMock()
        win._watcher = mock_watcher

        def _exec_mid_abort(dlg: QDialog) -> int:
            assert isinstance(dlg, InteractiveRebaseDialog)
            dlg.rebase_started.emit()
            return int(QDialog.DialogCode.Rejected)

        with patch.object(win, "_exec_dialog", side_effect=_exec_mid_abort):
            res = win._run_interactive_rebase_dialog(repo, base_oid)
        assert res == int(QDialog.DialogCode.Rejected)
        assert mock_watcher.suspend.call_count == 1
        mock_watcher.resume.assert_called_once_with(grace_ms=150)
        assert win._interactive_rebase_dialog is None

        # Conflict outcome focuses Changes tab cleanly without blocking popups
        def _exec_conflict_finish(dlg: QDialog) -> int:
            assert isinstance(dlg, InteractiveRebaseDialog)
            dlg.rebase_started.emit()
            dlg.rebase_completed.emit(
                engine.RebaseResult(status="conflict", conflicted_files=["f2.txt"])
            )
            return int(QDialog.DialogCode.Accepted)

        with patch.object(win, "_exec_dialog", side_effect=_exec_conflict_finish):
            res_conf = win._run_interactive_rebase_dialog(repo, base_oid)
        assert res_conf == int(QDialog.DialogCode.Accepted)
        assert win.tab_container.current_index() == win.tab_container.find_tab("changes", "")
        assert "conflict" in win.status_label.text().lower()
        win._watcher = None

        # 3. Disabling toggle with open SettingsDialog defers reject() until close
        idlg = InteractiveRebaseDialog(repo_path, base_oid, parent=win, settings_registry=reg)
        win._interactive_rebase_dialog = idlg
        _drain_workers(app)
        idlg.show()
        app.processEvents()

        # Verify Catppuccin Light vs Dark styling switch cleanly on InteractiveRebaseDialog
        app.setPalette(create_pastel_light_palette())
        app.processEvents()
        assert idlg.start_btn.styleSheet() == PRIMARY_BUTTON_STYLES["light"]
        app.setPalette(create_pastel_dark_palette())
        app.processEvents()
        assert idlg.start_btn.styleSheet() == PRIMARY_BUTTON_STYLES["dark"]

        deferred_states: list[bool] = []

        def _mock_settings_exec(sdlg: QDialog) -> int:
            assert isinstance(sdlg, SettingsDialog)
            assert idlg._settings_open is True
            assert idlg.settings_open_banner.isHidden() is False
            reg.set("rebase.interactive_ui.enabled", False)
            app.processEvents()
            deferred_states.append(idlg._pending_close_on_disable)
            assert idlg._pending_close_on_disable is True
            return int(QDialog.DialogCode.Rejected)

        with (
            patch.object(idlg, "reject", wraps=idlg.reject) as spy_reject,
            patch.object(win, "_exec_dialog", side_effect=_mock_settings_exec),
        ):
            idlg.settings_btn.click()
            app.processEvents()

        assert deferred_states == [True]
        assert spy_reject.call_count == 1
        assert idlg.result() == QDialog.DialogCode.Rejected
        win._interactive_rebase_dialog = None
        idlg.close()
    finally:
        win.close()


def test_live_view_theme_switch_while_interactive_rebase_dialog_is_open(
    app: QApplication, db_conn: sqlite3.Connection, tmp_path: Path
) -> None:
    repo_path, base_oid, _ = _make_linear_repo(tmp_path / "ui_live_theme")
    repo = engine.open_repo(repo_path)
    win = MainWindow(conn=db_conn)
    orig_palette = app.palette()
    try:
        win._on_repo_changed(str(repo_path))
        win.act_theme_light.trigger()
        win.show()
        app.processEvents()

        observations: dict[str, object] = {}
        attempts = {"n": 0}

        def _drive_live_theme_switch() -> None:
            dlg = win._interactive_rebase_dialog
            attempts["n"] += 1
            if dlg is None or dlg._is_loading:
                if attempts["n"] >= 80:
                    if dlg is not None:
                        dlg.reject()
                    return
                QTimer.singleShot(25, _drive_live_theme_switch)
                return

            observations["modality"] = dlg.windowModality()
            # Trigger an invalid row tint in Light mode
            dlg.set_row_action(0, "squash")
            app.processEvents()
            observations["light_row_bg"] = dlg.todo_table.item(0, 2).background().color().name()
            observations["light_btn"] = dlg.start_btn.styleSheet()

            # Switch live to Dark via MainWindow View -> Theme while dialog is open
            win.act_theme_dark.trigger()
            app.processEvents()
            combo0 = dlg.todo_table.cellWidget(0, 1)
            observations["dark_dlg"] = is_dark_theme(dlg)
            observations["dark_btn"] = dlg.start_btn.styleSheet()
            observations["dark_table"] = dlg.todo_table.styleSheet()
            observations["dark_combo"] = (
                combo0.styleSheet() if isinstance(combo0, QComboBox) else ""
            )
            observations["dark_preview"] = dlg.preview_bar.styleSheet()
            observations["dark_row_bg"] = dlg.todo_table.item(0, 2).background().color().name()

            # Switch live back to Light via View -> Theme
            win.act_theme_light.trigger()
            app.processEvents()
            combo0_l = dlg.todo_table.cellWidget(0, 1)
            observations["back_light_dlg"] = is_dark_theme(dlg)
            observations["back_light_btn"] = dlg.start_btn.styleSheet()
            observations["back_light_combo"] = (
                combo0_l.styleSheet() if isinstance(combo0_l, QComboBox) else ""
            )
            item0 = dlg.todo_table.item(0, 2)
            observations["back_light_row_bg"] = item0.background().color().name()
            dlg.reject()

        QTimer.singleShot(25, _drive_live_theme_switch)
        res = win._run_interactive_rebase_dialog(repo, base_oid)

        assert res == int(QDialog.DialogCode.Rejected)
        assert observations["modality"] == Qt.WindowModality.NonModal
        assert observations["light_btn"] == PRIMARY_BUTTON_STYLES["light"]
        assert observations["dark_dlg"] is True
        assert observations["dark_btn"] == PRIMARY_BUTTON_STYLES["dark"]
        assert TREE_WIDGET_STYLES["dark"]["bg"] in str(observations["dark_table"])
        assert REBASE_ACTION_COLORS["dark"]["squash"] in str(observations["dark_combo"])
        assert "QComboBox QAbstractItemView" in str(observations["dark_combo"])
        assert str(observations["dark_row_bg"]).lower() == get_banner_style("error", True)["bg"]
        assert observations["back_light_dlg"] is False
        assert observations["back_light_btn"] == PRIMARY_BUTTON_STYLES["light"]
        assert REBASE_ACTION_COLORS["light"]["squash"] in str(observations["back_light_combo"])
        assert (
            str(observations["back_light_row_bg"]).lower()
            == get_banner_style("error", False)["bg"]
        )
    finally:
        win.close()
        app.setPalette(orig_palette)
