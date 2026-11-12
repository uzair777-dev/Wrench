"""Unit tests for watcher package (inotify_watcher and polling_fallback)."""

import errno
import os
import sqlite3
import subprocess
import time
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QObject, Signal

import wrench.watcher.inotify_watcher as inotify_mod
from wrench.storage.db import run_migrations
from wrench.storage.settings_registry import SettingsRegistry
from wrench.watcher.inotify_watcher import RepoWatcher
from wrench.watcher.polling_fallback import PollingFallback


def _make_registry() -> SettingsRegistry:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    run_migrations(conn)
    return SettingsRegistry(conn=conn)


class _DummySignalObj(QObject):
    changed = Signal()


class TestRepoWatcher:
    def test_watcher_emits_on_file_change(self, tmp_path, qapp):
        repo_dir = tmp_path / "watch-repo"
        repo_dir.mkdir()
        (repo_dir / ".git").mkdir()

        watcher = RepoWatcher(repo_dir)
        events_received = []

        watcher.status_changed.connect(lambda: events_received.append(True))
        watcher.start()
        watcher.wait_until_ready()

        # Touch a file in the repo
        (repo_dir / "new.txt").write_text("hello\n")

        # Process Qt events and watchdog queue with timeout
        start = time.time()
        while not events_received and time.time() - start < 2.0:
            QCoreApplication.processEvents()
            time.sleep(0.05)

        watcher.stop()
        assert len(events_received) >= 1

    def test_enospc_triggers_git_dir_inotify_and_live_disable(self, tmp_path, qapp, monkeypatch):
        repo_dir = tmp_path / "monorepo"
        repo_dir.mkdir()
        git_dir = repo_dir / ".git"
        git_dir.mkdir()
        (git_dir / "refs").mkdir()
        (git_dir / "info").mkdir()

        scheduled_paths: list[tuple[str, bool]] = []
        RealObserver = inotify_mod.Observer

        class _FailTier1Observer:
            def __init__(self):
                self._inner = RealObserver()

            def schedule(self, handler, path, recursive=False):
                if Path(path) == repo_dir and recursive:
                    raise OSError(errno.ENOSPC, "inotify watch limit reached")
                scheduled_paths.append((path, recursive))
                return self._inner.schedule(handler, path, recursive=recursive)

            def start(self):
                self._inner.start()

            def stop(self):
                self._inner.stop()

            def join(self, timeout=None):
                self._inner.join(timeout=timeout)

        monkeypatch.setattr(inotify_mod, "Observer", _FailTier1Observer)

        reg = _make_registry()
        watcher = RepoWatcher(repo_dir, debounce_ms=60, settings_registry=reg)
        fallback_events: list[tuple[str, str]] = []
        watcher.adaptive_fallback_activated.connect(
            lambda mode, reason: fallback_events.append((mode, reason))
        )
        watcher.start()
        assert watcher.wait_until_ready(timeout=2.0)
        QCoreApplication.processEvents()

        assert watcher.status_info.mode == "git_dir_inotify"
        assert watcher.status_info.is_fallback is True
        assert any(p == str(git_dir) and rec is False for p, rec in scheduled_paths)
        assert ("git_dir_inotify", "inotify watch limit reached") in fallback_events or any(
            m == "git_dir_inotify" for m, _ in fallback_events
        )

        # Live toggle off stops observer cleanly without needing restart
        reg.set("watcher.inotify.enabled", False)
        start = time.time()
        while watcher.status_info.mode != "disabled" and time.time() - start < 1.0:
            QCoreApplication.processEvents()
            time.sleep(0.02)

        assert watcher.status_info.mode == "disabled"
        assert any(m == "disabled" for m, _ in fallback_events)
        watcher.stop()

    def test_emfile_and_adaptive_disabled_falls_back_to_polling(self, tmp_path, qapp, monkeypatch):
        repo_dir = tmp_path / "monorepo_poll"
        repo_dir.mkdir()
        (repo_dir / ".git").mkdir()

        class _AlwaysFailObserver:
            def schedule(self, handler, path, recursive=False):
                raise OSError(errno.EMFILE, "Too many open files")

            def start(self):
                pass

            def stop(self):
                pass

            def join(self, timeout=None):
                pass

        monkeypatch.setattr(inotify_mod, "Observer", _AlwaysFailObserver)

        reg = _make_registry()
        reg.set("watcher.monorepo_adaptive_fallback.enabled", False)
        watcher = RepoWatcher(repo_dir, settings_registry=reg)
        fallback_events: list[tuple[str, str]] = []
        watcher.adaptive_fallback_activated.connect(
            lambda mode, reason: fallback_events.append((mode, reason))
        )
        watcher.start()
        assert watcher.wait_until_ready(timeout=2.0)

        start = time.time()
        while watcher.status_info.mode != "polling" and time.time() - start < 1.0:
            QCoreApplication.processEvents()
            time.sleep(0.02)

        assert watcher.status_info.mode == "polling"
        assert watcher.status_info.is_fallback is True
        assert any(m == "polling" for m, _ in fallback_events)
        watcher.stop()

    def test_polling_fallback_resolves_linked_worktree_gitdir(self, tmp_path, qapp):
        main_repo = tmp_path / "main"
        main_repo.mkdir()
        subprocess.run(["git", "init", "-b", "main"], cwd=main_repo, check=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=main_repo, check=True)
        subprocess.run(["git", "config", "user.email", "t@e.com"], cwd=main_repo, check=True)
        (main_repo / "a.txt").write_text("hi\n")
        subprocess.run(["git", "add", "-A"], cwd=main_repo, check=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=main_repo, check=True)

        wt = tmp_path / "wt"
        subprocess.run(["git", "worktree", "add", "-b", "feat", str(wt)], cwd=main_repo, check=True)

        sig_obj = _DummySignalObj()
        hits = []
        sig_obj.changed.connect(lambda: hits.append(True))

        fb = PollingFallback(wt, sig_obj.changed, interval_ms=50)
        fb._check_changes()
        head_file = fb._git_dir / "HEAD"
        assert head_file.exists()

        time.sleep(0.05)
        head_file.write_text("ref: refs/heads/feat\n", encoding="utf-8")
        fb._check_changes()
        fb.stop()
        assert len(hits) == 1

    def test_watchdog_event_coalescing_and_suspend_resume(self, tmp_path, qapp):
        repo_dir = tmp_path / "coalesce-repo"
        repo_dir.mkdir()
        (repo_dir / ".git").mkdir()

        watcher = RepoWatcher(repo_dir, debounce_ms=60)
        hits: list[bool] = []
        watcher.status_changed.connect(lambda: hits.append(True))

        # 500 rapid bursts coalesce into 1 pending event -> 1 debounce emission
        for _ in range(500):
            watcher._on_watchdog_event()
        assert watcher._event_pending is True

        start = time.time()
        while time.time() - start < 0.25:
            QCoreApplication.processEvents()
            time.sleep(0.01)
        assert len(hits) == 1
        assert watcher._event_pending is False

        # suspend() -> 500 events -> resume(grace_ms=0) yields zero emissions
        hits.clear()
        watcher.suspend()
        for _ in range(500):
            watcher._on_watchdog_event()
        assert watcher._event_pending is False

        start = time.time()
        while time.time() - start < 0.15:
            QCoreApplication.processEvents()
            time.sleep(0.01)
        assert len(hits) == 0

        # Extra resume() clamps _suppress_depth strictly at 0
        watcher.resume(grace_ms=0)
        watcher.resume(grace_ms=0)
        assert watcher._suppress_depth == 0

        # Events emit again after resume
        watcher._on_watchdog_event()
        start = time.time()
        while not hits and time.time() - start < 0.5:
            QCoreApplication.processEvents()
            time.sleep(0.01)
        assert len(hits) == 1
        watcher.stop()

    def test_tier2_handler_and_polling_detect_config_and_worktree_updates(self, tmp_path, qapp):
        git_dir = tmp_path / "repo" / ".git"
        (git_dir / "info").mkdir(parents=True)
        cfg = git_dir / "config"
        cfg_wt = git_dir / "config.worktree"
        sparse_f = git_dir / "info" / "sparse-checkout"
        cfg.write_text("[core]\n", encoding="utf-8")
        cfg_wt.write_text("[core]\n\tsparseCheckout = true\n", encoding="utf-8")
        sparse_f.write_text("/*\n!/*/\n", encoding="utf-8")

        handler = inotify_mod._GitDirMetadataHandler(lambda: None, git_dir)
        assert handler._is_relevant(str(cfg)) is True
        assert handler._is_relevant(str(cfg_wt)) is True
        assert handler._is_relevant(str(sparse_f)) is True
        assert handler._is_relevant(str(git_dir / "index.lock")) is False
        assert handler._is_relevant(str(git_dir / "config.lock")) is False

        sig_obj = _DummySignalObj()
        hits: list[bool] = []
        sig_obj.changed.connect(lambda: hits.append(True))

        fb = PollingFallback(tmp_path / "repo", sig_obj.changed, interval_ms=50, git_dir=git_dir)
        fb._check_changes()
        assert len(hits) == 0

        # Bump config.worktree mtime -> detected cleanly
        t1 = cfg_wt.stat().st_mtime + 5.0
        cfg_wt.write_text("[core]\n\tsparseCheckout = false\n", encoding="utf-8")
        os.utime(cfg_wt, (t1, t1))
        fb._check_changes()
        assert len(hits) == 1

        # Bump config mtime -> detected cleanly
        t2 = cfg.stat().st_mtime + 5.0
        cfg.write_text("[core]\n[extensions]\n\tworktreeConfig = true\n", encoding="utf-8")
        os.utime(cfg, (t2, t2))
        fb._check_changes()
        fb.stop()
        assert len(hits) == 2

    def test_explicit_debounce_overrides_registry_while_default_tracks_registry(
        self, tmp_path, qapp
    ):
        repo_dir = tmp_path / "debounce-repo"
        repo_dir.mkdir()
        (repo_dir / ".git").mkdir()

        reg = _make_registry()
        reg.set("watcher.debounce_ms", 420)

        default_watcher = RepoWatcher(repo_dir, settings_registry=reg)
        explicit_watcher = RepoWatcher(repo_dir, debounce_ms=60, settings_registry=reg)
        try:
            assert default_watcher._debounce_timer.interval() == 420
            assert explicit_watcher._debounce_timer.interval() == 60
        finally:
            default_watcher.stop()
            explicit_watcher.stop()

    def test_watcher_ignores_commit_graph_housekeeping_paths(self, tmp_path, qapp):
        git_dir = tmp_path / "cg-repo" / ".git"
        (git_dir / "objects" / "info" / "commit-graphs").mkdir(parents=True)

        full_hits: list[bool] = []
        wd_handler = inotify_mod._WatchdogHandler(
            lambda: full_hits.append(True),
            git_dir=git_dir,
        )

        assert wd_handler._is_git_internal(str(git_dir / "objects" / "info" / "commit-graph"))
        assert wd_handler._is_git_internal(str(git_dir / "objects" / "info" / "commit-graph.lock"))
        assert wd_handler._is_git_internal(
            str(git_dir / "objects" / "info" / "commit-graphs" / "graph-abc.graph")
        )
        # REG-1 regression guard: tracked working-tree files with similar names MUST NOT be ignored
        assert not wd_handler._is_git_internal(str(tmp_path / "cg-repo" / "commit-graph.lock"))
        assert not wd_handler._is_git_internal(
            str(tmp_path / "cg-repo" / "src" / "objects" / "info" / "commit-graph")
        )
        assert not wd_handler._is_git_internal(str(tmp_path / "cg-repo" / "src" / "main.py"))

        # Linked worktree commondir commit-graph housekeeping must also be ignored
        common_dir = tmp_path / "main-repo" / ".git"
        (common_dir / "objects" / "info" / "commit-graphs").mkdir(parents=True)
        wt_git_dir = common_dir / "worktrees" / "wt1"
        wt_git_dir.mkdir(parents=True)
        (wt_git_dir / "commondir").write_text("../..\n", encoding="utf-8")

        tier2_handler = inotify_mod._GitDirMetadataHandler(
            lambda: None,
            git_dir,
            common_dir=common_dir,
        )
        assert not tier2_handler._is_relevant(str(git_dir / "objects" / "info" / "commit-graph"))
        assert not tier2_handler._is_relevant(
            str(git_dir / "objects" / "info" / "commit-graph.lock")
        )
        assert not tier2_handler._is_relevant(
            str(common_dir / "objects" / "info" / "commit-graph")
        )
        assert not tier2_handler._is_relevant(
            str(common_dir / "objects" / "info" / "commit-graph.lock")
        )
        assert not tier2_handler._is_relevant(
            str(common_dir / "objects" / "info" / "commit-graphs" / "graph-xyz.graph")
        )
        assert tier2_handler._is_relevant(str(git_dir / "HEAD"))
