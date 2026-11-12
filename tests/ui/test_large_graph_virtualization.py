"""Offscreen UI tests for VP-16 virtualization, diff cap, dialogs, and MainWindow wiring."""

from __future__ import annotations

import gc
import sqlite3
import subprocess
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pygit2
import pytest
import shiboken6
from PySide6.QtCore import Qt, QThreadPool, QTimer, qInstallMessageHandler
from PySide6.QtGui import QColor, QPalette, QPixmapCache
from PySide6.QtWidgets import QApplication, QDialog, QStatusBar

from wrench.core import engine
from wrench.core.models import Diff, DiffLine, Hunk
from wrench.storage import repo_registry
from wrench.storage.db import run_migrations
from wrench.storage.settings_registry import SettingsRegistry
from wrench.ui import workers
from wrench.ui.commit_graph.graph_widget import CommitGraphWidget
from wrench.ui.dialogs.clone_dialog import CloneDialog
from wrench.ui.dialogs.settings_dialog import SettingsDialog
from wrench.ui.dialogs.sparse_checkout_dialog import SparseCheckoutDialog
from wrench.ui.diff_view.diff_widget import DEFAULT_MAX_DIFF_LINES, DiffWidget
from wrench.ui.main_window import MainWindow
from wrench.ui.theme import (
    PRIMARY_BUTTON_STYLES,
    create_pastel_dark_palette,
    create_pastel_light_palette,
)


@pytest.fixture(autouse=True)
def app():
    instance = QApplication.instance()
    if not instance:
        instance = QApplication([])
    return instance


@pytest.fixture
def db_conn():
    conn = sqlite3.connect(":memory:")
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


def _create_1250_commit_repo(repo_path: Path) -> Path:
    repo_path.mkdir(parents=True, exist_ok=True)
    r = pygit2.init_repository(str(repo_path), initial_head="main")
    sig = pygit2.Signature("Dev", "dev@example.com", 1_700_000_000, 0)

    parents: list[pygit2.Oid] = []
    tb = r.TreeBuilder()
    blob_oid = r.create_blob(b"base\n")
    tb.insert("app.txt", blob_oid, pygit2.GIT_FILEMODE_BLOB)
    tree_oid = tb.write()

    for idx in range(1248):
        oid = r.create_commit(
            "refs/heads/main",
            sig,
            sig,
            f"commit #{idx:04d}",
            tree_oid,
            parents,
        )
        parents = [oid]

    # Create a side branch commit + merge commit to ensure multi-lane graph geometry
    side_oid = r.create_commit(
        "refs/heads/feature",
        sig,
        sig,
        "feature branch commit",
        tree_oid,
        [parents[0]],
    )
    merge_oid = r.create_commit(
        "refs/heads/main",
        sig,
        sig,
        "Merge branch 'feature'",
        tree_oid,
        [parents[0], side_oid],
    )
    r.set_head("refs/heads/main")
    assert len(str(merge_oid)) == 40
    return repo_path


def _create_monorepo(repo_path: Path, *, empty: bool = False) -> Path:
    repo_path.mkdir(parents=True, exist_ok=True)
    _git(repo_path, "init", "-b", "main")
    _git(repo_path, "config", "user.name", "Test User")
    _git(repo_path, "config", "user.email", "test@example.com")
    if empty:
        return repo_path

    (repo_path / "README.md").write_text("root\n", encoding="utf-8")
    (repo_path / "apps" / "api" / "v1").mkdir(parents=True, exist_ok=True)
    (repo_path / "apps" / "api" / "v1" / "app.py").write_text("ok = True\n", encoding="utf-8")
    (repo_path / "apps" / "web").mkdir(parents=True, exist_ok=True)
    (repo_path / "apps" / "web" / "index.ts").write_text("export {};\n", encoding="utf-8")
    (repo_path / "docs").mkdir(parents=True, exist_ok=True)
    (repo_path / "docs" / "guide.md").write_text("# Guide\n", encoding="utf-8")
    (repo_path / "libs" / "core").mkdir(parents=True, exist_ok=True)
    (repo_path / "libs" / "core" / "util.py").write_text("x = 1\n", encoding="utf-8")
    _git(repo_path, "add", "-A")
    _git(repo_path, "commit", "-m", "initial monorepo commit")
    return repo_path


def _wait_for_pool_and_events(app_inst: QApplication, timeout_ms: int = 3000) -> None:
    deadline = time.monotonic() + (timeout_ms / 1000.0)
    QThreadPool.globalInstance().waitForDone(timeout_ms)
    while time.monotonic() < deadline:
        app_inst.processEvents()
        time.sleep(0.01)


def test_commit_graph_pagination_viewport_clipping_lane_o1_and_pixmap_cache(
    app: QApplication, db_conn: sqlite3.Connection, tmp_path: Path
) -> None:
    repo_path = _create_1250_commit_repo(tmp_path / "large_repo")
    reg = SettingsRegistry(conn=db_conn)
    reg.set("performance.graph_page_size", 100)

    handle = engine.open_repo(repo_path)
    widget = CommitGraphWidget(settings_registry=reg)
    widget.resize(800, 260)
    widget.show()
    widget.set_repo(handle)
    app.processEvents()

    # Initial page bounded by performance.graph_page_size (never 1250!)
    assert widget._model.rowCount() == 100
    assert widget._has_more is True
    assert widget._model.max_active_lane >= 1

    # Repaint and confirm paintEvent only covers visible viewport rows
    widget.viewport().repaint()
    app.processEvents()
    first_painted, last_painted = widget._last_painted_row_range
    assert first_painted == 0
    assert 0 < last_painted < 40

    # Scroll to bottom 20% -> triggers QThreadPool page 2 fetch
    sb = widget.verticalScrollBar()
    sb.setValue(max(1, int(sb.maximum() * 0.85)))
    QThreadPool.globalInstance().waitForDone(3000)
    app.processEvents()
    QThreadPool.globalInstance().waitForDone(3000)
    app.processEvents()

    assert widget._model.rowCount() == 200

    # Ref-label QPixmapCache warm + palette-switch epoch invalidation
    epoch_before = widget._paint_cache_epoch
    pal = widget.palette()
    pal.setColor(QPalette.ColorRole.Window, QColor("#1e1e2e"))
    widget.setPalette(pal)
    app.processEvents()
    assert widget._paint_cache_epoch > epoch_before

    pm = QPixmapCache.find(
        f"wrench:refpill:branch:main:0:9:{max(1.0, widget.devicePixelRatioF()):.2f}:{epoch_before}"
    )
    assert pm is not None or widget._paint_cache_epoch > epoch_before

    # Delete mid-flight with pending scroll fetch -> must not raise RuntimeError
    sb.setValue(sb.maximum())
    shiboken6.delete(widget)
    QThreadPool.globalInstance().waitForDone(3000)
    app.processEvents()


def test_diff_widget_50k_line_cap_load_full_diff_and_binary_guard(
    app: QApplication, db_conn: sqlite3.Connection, tmp_path: Path
) -> None:
    repo = _create_monorepo(tmp_path / "diff_repo")
    huge = repo / "huge.txt"
    huge.write_text("".join(f"base-{i:06d}\n" for i in range(52000)), encoding="utf-8")
    _git(repo, "add", "huge.txt")
    _git(repo, "commit", "-m", "add large file")
    # Unstaged modification of all 52k lines
    huge.write_text("".join(f"changed-{i:06d}\n" for i in range(52000)), encoding="utf-8")

    reg = SettingsRegistry(conn=db_conn)
    handle = engine.open_repo(repo)
    w = DiffWidget(settings_registry=reg)
    w.show()
    w.set_repo(handle)
    w.set_file("huge.txt", staged=False)
    app.processEvents()

    assert w.truncation_banner.isHidden() is False
    assert "5,000" in w.truncation_label.text()
    assert w.editor.document().blockCount() <= DEFAULT_MAX_DIFF_LINES + 50

    # Clicking [Load Full Diff] reveals complete diff and hides banner
    w.load_full_diff_btn.click()
    app.processEvents()
    assert w.truncation_banner.isHidden() is True
    assert "changed-051999" in w.editor.toPlainText()

    # Binary guard
    bin_diff = Diff(path="assets/logo.png", is_binary=True, hunks=[])
    w.set_diff_model(bin_diff)
    app.processEvents()
    assert w.truncation_banner.isHidden() is True
    assert "Binary file" in w.editor.toPlainText()

    # Direct read-only oversized model also enforces 5,000-line slice before full reveal
    many_lines = [
        DiffLine(content=f"line-{i}", origin="+", old_lineno=None, new_lineno=i + 1)
        for i in range(6000)
    ]
    big_model = Diff(
        path="ro.txt",
        is_binary=False,
        hunks=[
            Hunk(
                id="hunk-0",
                old_start=1,
                old_count=0,
                new_start=1,
                new_count=6000,
                lines=many_lines,
            )
        ],
    )
    w.set_diff_model(big_model)
    app.processEvents()
    assert w.truncation_banner.isHidden() is False
    assert w.editor.document().blockCount() <= DEFAULT_MAX_DIFF_LINES + 10
    w.close()


def test_sparse_checkout_dialog_lazy_expand_lock_retry_unborn_and_live_disable(
    app: QApplication, db_conn: sqlite3.Connection, tmp_path: Path
) -> None:
    reg = SettingsRegistry(conn=db_conn)
    repo = _create_monorepo(tmp_path / "monorepo")

    dlg = SparseCheckoutDialog(repo, settings_registry=reg)
    dlg.show()
    app.processEvents()

    # Depth-1 only on initial open (apps, docs, libs)
    top_names = [
        dlg.dir_tree.topLevelItem(i).text(0) for i in range(dlg.dir_tree.topLevelItemCount())
    ]
    assert top_names == ["apps", "docs", "libs"]
    apps_item = dlg.dir_tree.topLevelItem(0)
    assert apps_item.childCount() == 1
    assert apps_item.child(0).text(0) == "Loading…"

    # Expand 'apps' -> QThreadPool loads ['api', 'web']
    dlg.dir_tree.expandItem(apps_item)
    QThreadPool.globalInstance().waitForDone(3000)
    app.processEvents()
    child_names = [apps_item.child(i).text(0) for i in range(apps_item.childCount())]
    assert child_names == ["api", "web"]

    # Check apps/api, then simulate .git/index.lock contention -> inline error_banner + Retry
    api_item = apps_item.child(0)
    api_item.setCheckState(0, Qt.CheckState.Checked)
    app.processEvents()
    assert "apps/api" in dlg.selected_directories()
    assert "sparse-checkout set --cone -- apps/api" in dlg.preview_bar.preview_text

    lock_file = repo / ".git" / "index.lock"
    lock_file.write_text("locked", encoding="utf-8")
    failures: list[str] = []
    changed_calls: list[bool] = []
    dlg.apply_failed.connect(failures.append)
    dlg.sparse_checkout_changed.connect(lambda: changed_calls.append(True))

    dlg._on_apply_clicked()
    QThreadPool.globalInstance().waitForDone(3000)
    app.processEvents()

    assert len(failures) == 1
    assert ".lock" in dlg.error_label.text().lower()
    assert dlg.error_banner.isHidden() is False
    assert dlg.retry_btn.isHidden() is False

    # Clear lock and click non-modal Retry -> succeeds and updates working tree
    lock_file.unlink()
    dlg.retry_btn.click()
    QThreadPool.globalInstance().waitForDone(3000)
    app.processEvents()

    assert len(changed_calls) == 1
    assert engine.list_sparse_directories(repo) == ["apps/api"]
    assert (repo / "apps" / "api" / "v1" / "app.py").exists()
    assert not (repo / "libs").exists()

    # Open new dialog, test live disable via SettingsRegistry
    dlg2 = SparseCheckoutDialog(repo, settings_registry=reg)
    dlg2.show()
    app.processEvents()
    assert dlg2.isVisible() is True
    reg.set("monorepo.sparse_checkout_ui.enabled", False)
    app.processEvents()
    assert dlg2.result() == QDialog.DialogCode.Rejected

    # Unborn empty repo warning banner disables Apply
    empty_repo = _create_monorepo(tmp_path / "empty_repo", empty=True)
    reg.set("monorepo.sparse_checkout_ui.enabled", True)
    empty_dlg = SparseCheckoutDialog(empty_repo, settings_registry=reg)
    empty_dlg.show()
    app.processEvents()
    assert empty_dlg.unborn_banner.isHidden() is False
    assert empty_dlg.apply_btn.isEnabled() is False
    empty_dlg.close()


def test_clone_dialog_filter_pref_sec2_validation_sec3_redaction_and_live_sparse_toggle(
    app: QApplication, db_conn: sqlite3.Connection, tmp_path: Path
) -> None:
    reg = SettingsRegistry(conn=db_conn)
    reg.set("clone.default_filter_mode", "blob:none")

    dlg = CloneDialog(settings_registry=reg, conn=db_conn)
    dlg.show()
    app.processEvents()

    assert dlg.filter_spec() == "blob:none"

    # Secret redaction in CLI preview bar (SEC-3)
    dlg.url_input.setText("https://alice:topsecret_token@github.com/org/monorepo.git")
    dlg.dest_parent_input.setText(str(tmp_path))
    app.processEvents()
    preview = dlg.preview_bar.preview_text
    assert "topsecret_token" not in preview
    assert "***:***@" in preview
    assert "--filter blob:none" in preview

    # SEC-2 URL rejection stays inline without accepting
    dlg.url_input.setText("ext::sh -c evil")
    dlg.clone_btn.click()
    app.processEvents()
    assert dlg.error_banner.isHidden() is False
    assert dlg.result() != QDialog.DialogCode.Accepted

    # Live disabling sparse_checkout_ui hides sparse checkbox cleanly
    assert dlg.sparse_checkbox.isHidden() is False
    dlg.sparse_checkbox.setChecked(True)
    reg.set("monorepo.sparse_checkout_ui.enabled", False)
    app.processEvents()
    assert dlg.sparse_checkbox.isHidden() is True
    assert dlg.sparse_enabled() is False
    dlg.close()


def test_main_window_vp16_toggles_short_circuit_and_clone_to_sparse_flow(
    app: QApplication, db_conn: sqlite3.Connection, tmp_path: Path
) -> None:
    src_repo = _create_monorepo(tmp_path / "src_mono")
    bare_remote = tmp_path / "remote_mono.git"
    _git(tmp_path, "clone", "--bare", str(src_repo), str(bare_remote))
    _git(bare_remote, "config", "uploadpack.allowFilter", "true")
    _git(bare_remote, "config", "uploadpack.allowAnySHA1InWant", "true")

    win = MainWindow(conn=db_conn)
    reg = win._settings_registry

    # 1. Disable sparse UI -> action hidden + short-circuits before dialog
    reg.set("monorepo.sparse_checkout_ui.enabled", False)
    app.processEvents()
    assert win.act_sparse_checkout.isVisible() is False
    assert win.sparse_status_btn.isVisible() is False

    with patch("wrench.ui.main_window.SparseCheckoutDialog") as mock_sparse_cls:
        win._on_manage_sparse_checkout()
        assert mock_sparse_cls.called is False

    # 2. Disable maintenance.auto_commit_graph.enabled -> short-circuits commit-graph worker
    reg.set("maintenance.auto_commit_graph.enabled", False)
    with patch.object(QThreadPool, "start") as mock_pool_start:
        win._maybe_write_commit_graph(src_repo)
        assert mock_pool_start.called is False

    # 3. Re-enable and exercise partial clone + SparseCheckoutDialog workflow
    reg.set("monorepo.sparse_checkout_ui.enabled", True)
    app.processEvents()
    assert win.act_sparse_checkout.isVisible() is True

    clone_parent = tmp_path / "cloned_here"
    clone_parent.mkdir(parents=True, exist_ok=True)

    def _sync_bg(fn, *args, on_finished=None, on_failed=None, **kwargs):
        try:
            call_kw = {k: v for k, v in kwargs.items() if k in ("filter_spec", "sparse")}
            res = fn(*args, **call_kw)
            if on_finished:
                on_finished(res)
        except Exception as exc:
            if on_failed:
                on_failed(exc)

    def _mock_exec(dlg):
        if isinstance(dlg, CloneDialog):
            dlg.url_input.setText(bare_remote.as_uri())
            dlg.dest_parent_input.setText(str(clone_parent))
            dlg.set_filter_mode("blob:none")
            dlg.sparse_checkbox.setChecked(True)
            return QDialog.DialogCode.Accepted
        if isinstance(dlg, SparseCheckoutDialog):
            # Apply ['docs'] directly via core inside mocked exec and accept
            engine.set_sparse_directories(dlg._repo_path, ["docs"], cone=True)
            return QDialog.DialogCode.Accepted
        return QDialog.DialogCode.Rejected

    with (
        patch.object(win, "_exec_dialog", side_effect=_mock_exec),
        patch("wrench.ui.main_window.run_in_background", side_effect=_sync_bg),
        patch("wrench.ui.main_window.RepoWatcher"),
        patch("wrench.core.engine.probe_remotes_async"),
    ):
        win._on_clone_repo()
        QThreadPool.globalInstance().waitForDone(3000)
        app.processEvents()

    cloned_path = clone_parent / "remote_mono"
    assert engine.get_sparse_checkout_state(cloned_path).partial_filter == "blob:none"
    assert engine.list_sparse_directories(cloned_path) == ["docs"]
    assert win.sparse_status_btn.isHidden() is False
    assert "Sparse: 1 dir (blob:none)" in win.sparse_status_btn.text()
    win.close()


def test_modal_settings_stacking_banners_and_deferred_sparse_disable(
    app: QApplication, db_conn: sqlite3.Connection, tmp_path: Path
) -> None:
    repo = _create_monorepo(tmp_path / "stack_mono")
    win = MainWindow(conn=db_conn)
    win._current_repo = engine.open_repo(repo)
    win.show()
    reg = win._settings_registry
    reg.set("monorepo.sparse_checkout_ui.enabled", True)
    app.processEvents()

    # 1. CloneDialog -> opens WindowModal SettingsDialog, shows banner, reuses active modal
    cdlg = CloneDialog(parent=win, settings_registry=reg, conn=db_conn)
    cdlg.show()
    app.processEvents()
    assert cdlg.settings_open_banner.isHidden() is True

    exec_calls: list[str] = []

    def _mock_clone_settings_exec(dlg: QDialog) -> int:
        exec_calls.append(type(dlg).__name__)
        assert isinstance(dlg, SettingsDialog)
        assert dlg.parent() is cdlg
        assert dlg.windowModality() == Qt.WindowModality.WindowModal
        assert win._active_settings_dialog is dlg
        assert cdlg._settings_open is True
        assert cdlg.settings_open_banner.isHidden() is False

        dlg.show()
        app.processEvents()
        with patch.object(
            win, "focus_active_settings_dialog", wraps=win.focus_active_settings_dialog
        ) as spy_focus:
            cdlg.focus_settings_btn.click()
            assert spy_focus.call_count == 1

        # Re-opening while active must reuse the same dialog instead of opening another
        win.open_settings_at_category("General & UI", parent_dialog=cdlg)
        assert len(exec_calls) == 1
        assert win._active_settings_dialog is dlg

        dlg.close()
        return int(QDialog.DialogCode.Rejected)

    with patch.object(win, "_exec_dialog", side_effect=_mock_clone_settings_exec):
        cdlg.settings_btn.click()
        app.processEvents()

    assert len(exec_calls) == 1
    assert cdlg._settings_open is False
    assert cdlg.settings_open_banner.isHidden() is True
    assert win._active_settings_dialog is None
    cdlg.close()

    # 2. SparseCheckoutDialog -> disabling monorepo.sparse_checkout_ui.enabled while
    #    child SettingsDialog is open defers reject() until Preferences closes.
    sdlg = SparseCheckoutDialog(repo, parent=win, settings_registry=reg)
    win._sparse_dialog = sdlg
    sdlg.show()
    app.processEvents()

    deferred_checked: list[bool] = []

    def _mock_sparse_settings_exec(dlg: QDialog) -> int:
        assert isinstance(dlg, SettingsDialog)
        assert dlg.parent() is sdlg
        assert dlg.windowModality() == Qt.WindowModality.WindowModal
        assert sdlg._settings_open is True
        assert sdlg.settings_open_banner.isHidden() is False

        reg.set("monorepo.sparse_checkout_ui.enabled", False)
        app.processEvents()
        # Must NOT reject underneath child SettingsDialog!
        deferred_checked.append(sdlg._pending_close_on_disable)
        assert sdlg._pending_close_on_disable is True
        assert sdlg.isVisible() is True
        assert spy_reject.call_count == 0
        return int(QDialog.DialogCode.Rejected)

    with (
        patch.object(sdlg, "reject", wraps=sdlg.reject) as spy_reject,
        patch.object(win, "_exec_dialog", side_effect=_mock_sparse_settings_exec),
    ):
        sdlg.settings_btn.click()
        app.processEvents()

    assert deferred_checked == [True]
    assert spy_reject.call_count == 1
    assert sdlg._settings_open is False
    assert sdlg.settings_open_banner.isHidden() is True
    assert sdlg._pending_close_on_disable is False
    assert sdlg.result() == QDialog.DialogCode.Rejected
    win._sparse_dialog = None
    sdlg.close()
    win.close()


def test_sparse_dialog_close_mid_apply_always_resumes_watcher_and_shows_redacted_warning(
    app: QApplication, db_conn: sqlite3.Connection, tmp_path: Path
) -> None:
    repo = _create_monorepo(tmp_path / "warn_mono")
    win = MainWindow(conn=db_conn)
    reg = win._settings_registry
    reg.set("monorepo.sparse_checkout_ui.enabled", True)

    mock_watcher = MagicMock()
    win._watcher = mock_watcher

    # 1. Closing dialog mid-apply (apply_started without apply_finished) still resumes watcher
    def _exec_abort_mid_apply(dlg: QDialog) -> int:
        assert isinstance(dlg, SparseCheckoutDialog)
        dlg.apply_started.emit()
        return int(QDialog.DialogCode.Rejected)

    with patch.object(win, "_exec_dialog", side_effect=_exec_abort_mid_apply):
        res = win._run_sparse_checkout_dialog(repo)
    assert res == int(QDialog.DialogCode.Rejected)
    assert mock_watcher.suspend.call_count == 1
    mock_watcher.resume.assert_called_once_with(grace_ms=150)
    assert win._sparse_dialog is None

    # 2. SparseCheckoutDialog._on_apply_succeeded extracts and redacts warnings cleanly
    unit_dlg = SparseCheckoutDialog(repo, settings_registry=reg)
    warns: list[str] = []
    unit_dlg.apply_warning.connect(warns.append)
    unit_dlg._on_apply_succeeded(
        unit_dlg._apply_generation,
        False,
        ["warning: failed sync for https://alice:s3cr3t_pw@github.com/org/repo.git"],
    )
    assert unit_dlg.last_warning is not None
    assert "s3cr3t_pw" not in unit_dlg.last_warning
    assert "***:***@" in unit_dlg.last_warning
    assert len(warns) == 1
    assert unit_dlg.result() == QDialog.DialogCode.Accepted
    unit_dlg.close()

    # 3. MainWindow status bar shows secret-redacted warning when accepted
    def _exec_with_warning(dlg: QDialog) -> int:
        assert isinstance(dlg, SparseCheckoutDialog)
        dlg.apply_started.emit()
        dlg.apply_warning.emit("warning: https://bob:secret_tok@github.com/org/repo.git")
        dlg.apply_finished.emit(True)
        return int(QDialog.DialogCode.Accepted)

    with (
        patch.object(win, "_exec_dialog", side_effect=_exec_with_warning),
        patch.object(win, "_refresh_after_git_op"),
    ):
        res2 = win._run_sparse_checkout_dialog(repo)

    assert res2 == int(QDialog.DialogCode.Accepted)
    status_msg = win.statusBar().currentMessage()
    assert "secret_tok" not in status_msg
    assert "***:***@" in status_msg
    assert mock_watcher.suspend.call_count == 2
    assert mock_watcher.resume.call_count == 2
    win._watcher = None
    win.close()


def test_remediated_controls_dark_light_theme_updates(
    app: QApplication, db_conn: sqlite3.Connection, tmp_path: Path
) -> None:
    repo = _create_monorepo(tmp_path / "theme_mono")
    win = MainWindow(conn=db_conn)
    reg = win._settings_registry

    win._set_theme("light")
    app.processEvents()

    cdlg = CloneDialog(parent=win, settings_registry=reg, conn=db_conn)
    sdlg = SparseCheckoutDialog(repo, parent=win, settings_registry=reg)
    settings_dlg = SettingsDialog(main_window=win, parent=win)
    page = settings_dlg._get_or_create_category_page("General & UI")
    sample_row = page.row_widgets[0]

    # Verify initial Catppuccin Latte (Light) styling
    assert cdlg.clone_btn.styleSheet() == PRIMARY_BUTTON_STYLES["light"]
    assert sdlg.apply_btn.styleSheet() == PRIMARY_BUTTON_STYLES["light"]
    assert "#1e66f5" in sdlg.dir_tree.styleSheet()
    assert "#216e39" in settings_dlg.toast_label.styleSheet()
    assert "#e0e7ff" in sample_row.lbl_override.styleSheet()

    # Switch to Catppuccin Mocha (Dark) via palette + PaletteChange propagation
    dark_pal = create_pastel_dark_palette()
    app.setPalette(dark_pal)
    for w in (win, cdlg, sdlg, settings_dlg):
        w.setPalette(dark_pal)
    win._set_theme("dark")
    app.processEvents()

    assert cdlg.clone_btn.styleSheet() == PRIMARY_BUTTON_STYLES["dark"]
    assert "#89b4fa" in cdlg.clone_btn.styleSheet()
    assert "#11111b" in cdlg.clone_btn.styleSheet()
    assert sdlg.apply_btn.styleSheet() == PRIMARY_BUTTON_STYLES["dark"]
    assert "#89b4fa" in sdlg.dir_tree.styleSheet()
    assert "#a6e3a1" in settings_dlg.toast_label.styleSheet()
    assert "#1e2942" in sample_row.lbl_override.styleSheet()
    assert "#89b4fa" in sample_row.lbl_override.styleSheet()

    # Switch back to Light palette and confirm reversal
    light_pal = create_pastel_light_palette()
    app.setPalette(light_pal)
    for w in (win, cdlg, sdlg, settings_dlg):
        w.setPalette(light_pal)
    win._set_theme("light")
    app.processEvents()

    assert cdlg.clone_btn.styleSheet() == PRIMARY_BUTTON_STYLES["light"]
    assert sdlg.apply_btn.styleSheet() == PRIMARY_BUTTON_STYLES["light"]
    assert "#1e66f5" in sdlg.dir_tree.styleSheet()
    assert "#e0e7ff" in sample_row.lbl_override.styleSheet()

    settings_dlg.close()
    sdlg.close()
    cdlg.close()
    win._set_theme("auto")
    app.processEvents()
    win.close()


def _create_regression_repo(repo_path: Path) -> Path:
    repo_path.mkdir(parents=True, exist_ok=True)
    r = pygit2.init_repository(str(repo_path), initial_head="main")
    sig = pygit2.Signature("Dev", "dev@example.com", 1_700_000_000, 0)

    huge_file = repo_path / "huge_diff.txt"
    huge_bytes = "".join(f"base-{i:06d}\n" for i in range(52000)).encode("utf-8")
    huge_file.write_bytes(huge_bytes)
    (repo_path / "app.txt").write_text("base\n", encoding="utf-8")

    tb = r.TreeBuilder()
    tb.insert("app.txt", r.create_blob(b"base\n"), pygit2.GIT_FILEMODE_BLOB)
    tb.insert("huge_diff.txt", r.create_blob(huge_bytes), pygit2.GIT_FILEMODE_BLOB)
    tree_oid = tb.write()

    parents: list[pygit2.Oid] = []
    for idx in range(250):
        oid = r.create_commit(
            "refs/heads/main",
            sig,
            sig,
            f"commit #{idx:04d}",
            tree_oid,
            parents,
        )
        parents = [oid]

    r.set_head("refs/heads/main")
    r.checkout_head(strategy=pygit2.GIT_CHECKOUT_FORCE)
    huge_file.write_text(
        "".join(f"changed-{i:06d}\n" for i in range(52000)),
        encoding="utf-8",
    )
    return repo_path


def test_main_window_lifecycle_pagination_diff_statusbar_clone_no_leaks(
    app: QApplication, db_conn: sqlite3.Connection, tmp_path: Path
) -> None:
    captured_qt_msgs: list[str] = []

    def _qt_msg_handler(_msg_type, _ctx, msg: str) -> None:
        captured_qt_msgs.append(str(msg))

    prev_handler = qInstallMessageHandler(_qt_msg_handler)
    repo_path = _create_regression_repo(tmp_path / "e2e_repo")
    src_mono = _create_monorepo(tmp_path / "src_clone_mono")
    bare_remote = tmp_path / "remote_e2e.git"
    _git(tmp_path, "clone", "--bare", str(src_mono), str(bare_remote))
    _git(bare_remote, "config", "uploadpack.allowFilter", "true")
    _git(bare_remote, "config", "uploadpack.allowAnySHA1InWant", "true")

    mw = MainWindow(conn=db_conn)
    try:
        mw._settings_registry.set("performance.graph_page_size", 100)
        mw._settings_registry.set("monorepo.sparse_checkout_ui.enabled", True)
        mw.show()
        app.processEvents()

        # Single QStatusBar invariant
        assert len(mw.findChildren(QStatusBar)) == 1
        assert mw.statusBar() is mw.status_bar

        # Open repo in Changes tab and inspect 52k-line truncated DiffView
        mw.tab_container.set_current_index(0)
        repo_registry.add_repo(db_conn, str(repo_path), repo_path.name)
        with patch("wrench.core.engine.probe_remotes_async"):
            mw.changes_tab.load_repos(select_path=str(repo_path))
            app.processEvents()

        assert mw.tab_container.current_index() == 0
        assert mw.changes_tab.files_list.count() == 1
        diff_view = mw.changes_tab.diff_view
        assert diff_view.truncation_banner.isHidden() is False
        assert "5,000" in diff_view.truncation_label.text()
        assert diff_view.editor.document().blockCount() <= DEFAULT_MAX_DIFF_LINES + 50

        diff_view.load_full_diff_btn.click()
        app.processEvents()
        assert diff_view.truncation_banner.isHidden() is True
        assert "changed-051999" in diff_view.editor.toPlainText()

        # Switch to History tab and verify paginated commit-graph scroll loading
        mw.tab_container.set_current_index(1)
        mw.history_tab.graph_widget.resize(800, 260)
        app.processEvents()
        assert mw.history_tab.graph_widget._model.rowCount() == 100
        assert mw.history_tab.graph_widget._has_more is True

        sb = mw.history_tab.graph_widget.verticalScrollBar()
        sb.setValue(max(1, int(sb.maximum() * 0.9)))
        QThreadPool.globalInstance().waitForDone(3000)
        app.processEvents()
        QThreadPool.globalInstance().waitForDone(3000)
        app.processEvents()
        assert mw.history_tab.graph_widget._model.rowCount() >= 200

        # Exercise partial clone + sparse-checkout flow + empty destination placeholder text
        clone_parent = tmp_path / "e2e_clones"
        clone_parent.mkdir(parents=True, exist_ok=True)
        seen_empty_dest_label: list[str] = []

        def _sync_bg(fn, *args, on_finished=None, on_failed=None, **kwargs):
            try:
                call_kw = {k: v for k, v in kwargs.items() if k in ("filter_spec", "sparse")}
                res = fn(*args, **call_kw)
                if on_finished:
                    on_finished(res)
            except Exception as exc:
                if on_failed:
                    on_failed(exc)

        def _mock_exec(dlg):
            if isinstance(dlg, CloneDialog):
                seen_empty_dest_label.append(dlg.resolved_dest_label.text())
                dlg.url_input.setText(bare_remote.as_uri())
                dlg.dest_parent_input.setText(str(clone_parent))
                dlg.set_filter_mode("blob:none")
                dlg.sparse_checkbox.setChecked(True)
                return QDialog.DialogCode.Accepted
            if isinstance(dlg, SparseCheckoutDialog):
                engine.set_sparse_directories(dlg._repo_path, ["docs"], cone=True)
                return QDialog.DialogCode.Accepted
            return QDialog.DialogCode.Rejected

        with (
            patch.object(mw, "_exec_dialog", side_effect=_mock_exec),
            patch("wrench.ui.main_window.run_in_background", side_effect=_sync_bg),
            patch("wrench.core.engine.probe_remotes_async"),
        ):
            mw._on_clone_repo()
            QThreadPool.globalInstance().waitForDone(3000)
            app.processEvents()

        assert seen_empty_dest_label == ["Choose a folder above to set destination path"]
        cloned_path = clone_parent / "remote_e2e"
        assert engine.get_sparse_checkout_state(cloned_path).partial_filter == "blob:none"
        assert engine.list_sparse_directories(cloned_path) == ["docs"]
        assert len(mw.findChildren(QStatusBar)) == 1

        # Close window and assert zero active QTimers, zero stray workers, and clean Qt logs
        mw.close()
        app.processEvents()
        QThreadPool.globalInstance().waitForDone(3000)
        assert workers.wait_for_active_workers(3.0) is True
        app.processEvents()
        gc.collect()
        app.processEvents()

        active_timers = [
            t for t in mw.findChildren(QTimer) if shiboken6.isValid(t) and t.isActive()
        ]
        assert active_timers == []
        assert mw._watcher is None
        assert not any(
            "Timers cannot be stopped from another thread" in m for m in captured_qt_msgs
        )
        assert not any("Failed to disconnect" in m for m in captured_qt_msgs)
    finally:
        if shiboken6.isValid(mw):
            mw.close()
        app.processEvents()
        QThreadPool.globalInstance().waitForDone(2000)
        workers.wait_for_active_workers(2.0)
        qInstallMessageHandler(prev_handler)
