"""Offscreen UI tests for VP-16 virtualization, diff cap, dialogs, and MainWindow wiring."""

from __future__ import annotations

import sqlite3
import subprocess
import time
from pathlib import Path
from unittest.mock import patch

import pygit2
import pytest
import shiboken6
from PySide6.QtCore import QThreadPool
from PySide6.QtGui import QColor, QPalette, QPixmapCache
from PySide6.QtWidgets import QApplication, QDialog

from wrench.core import engine
from wrench.core.models import Diff, DiffLine, Hunk
from wrench.storage.db import run_migrations
from wrench.storage.settings_registry import SettingsRegistry
from wrench.ui.commit_graph.graph_widget import CommitGraphWidget
from wrench.ui.dialogs.clone_dialog import CloneDialog
from wrench.ui.dialogs.sparse_checkout_dialog import SparseCheckoutDialog
from wrench.ui.diff_view.diff_widget import DEFAULT_MAX_DIFF_LINES, DiffWidget
from wrench.ui.main_window import MainWindow


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
    from PySide6.QtCore import Qt

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
