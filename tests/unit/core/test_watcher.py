"""Unit tests for watcher package (inotify_watcher and polling_fallback)."""

import time

from PySide6.QtCore import QCoreApplication

from wrench.watcher.inotify_watcher import RepoWatcher


class TestRepoWatcher:
    def test_watcher_emits_on_file_change(self, tmp_path, qapp):
        repo_dir = tmp_path / "watch-repo"
        repo_dir.mkdir()
        (repo_dir / ".git").mkdir()

        watcher = RepoWatcher(repo_dir)
        events_received = []

        watcher.status_changed.connect(lambda: events_received.append(True))
        watcher.start()

        # Touch a file in the repo
        (repo_dir / "new.txt").write_text("hello\n")

        # Process Qt events and watchdog queue with timeout
        start = time.time()
        while not events_received and time.time() - start < 2.0:
            QCoreApplication.processEvents()
            time.sleep(0.05)

        watcher.stop()
        assert len(events_received) >= 1
