"""Tests for the activity log buffer + dock widget."""

import time

from wrench.ui.widgets.activity_log import ActivityLogBar, ActivityLogModel
from wrench.ui.workers import run_in_background, set_activity_log


class TestActivityLogModel:
    def test_post_appends_to_buffer(self):
        log = ActivityLogModel(maxlen=200)
        log.post("Operation started", level="info")
        assert len(log.entries) == 1
        assert log.entries[0].text == "Operation started"
        assert log.entries[0].level == "info"

    def test_buffer_cap_at_maxlen(self):
        log = ActivityLogModel(maxlen=5)
        for i in range(10):
            log.post(f"Event {i}")
        assert len(log.entries) == 5
        assert log.entries[0].text == "Event 5"  # oldest evicted

    def test_post_emits_signal(self, qtbot):
        log = ActivityLogModel(maxlen=200)
        with qtbot.waitSignal(log.entry_added, timeout=1000):
            log.post("test signal")

    def test_valid_levels(self):
        log = ActivityLogModel(maxlen=200)
        for level in ("info", "ok", "warn", "error"):
            log.post(f"level {level}", level=level)
        assert len(log.entries) == 4


class TestActivityLogBar:
    def test_bar_creates_without_crash(self, qapp):
        log = ActivityLogModel(maxlen=200)
        bar = ActivityLogBar(log)
        bar.show()
        assert bar.isVisible()
        bar.close()

    def test_latest_entry_displayed(self, qapp):
        log = ActivityLogModel(maxlen=200)
        bar = ActivityLogBar(log)
        bar.show()
        log.post("Hello from the log")
        assert "Hello from the log" in bar.latest_label.text()
        bar.close()

    def test_toggle_expanded(self, qapp):
        log = ActivityLogModel(maxlen=200)
        bar = ActivityLogBar(log)
        bar.show()
        assert not bar._expanded
        assert not bar.scrollback.isVisible()
        bar._toggle_expanded()
        assert bar._expanded
        assert bar.scrollback.isVisible()
        bar._toggle_expanded()
        assert not bar._expanded
        assert not bar.scrollback.isVisible()
        bar.close()

    def test_worker_auto_posts_to_activity_log(self, qapp, qtbot):
        log = ActivityLogModel(maxlen=200)
        set_activity_log(log)

        def worker_fn():
            time.sleep(0.05)
            return "done"

        thread = run_in_background(worker_fn, op_name="Dummy Worker")
        thread.join(timeout=2.0)

        # Allow queued Qt signals to dispatch
        qtbot.wait(100)

        texts = [entry.text for entry in log.entries]
        assert any("Started: Dummy Worker" in t for t in texts)
        assert any("Finished: Dummy Worker" in t for t in texts)
        set_activity_log(None)
