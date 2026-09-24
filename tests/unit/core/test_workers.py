"""Unit tests for ui/workers.py — background QThread worker execution."""

import time

from PySide6.QtCore import QCoreApplication

from wrench.ui import workers


class TestWorkers:
    def test_run_in_background_success(self, qapp):
        results = []
        errors = []

        def slow_op(x, y):
            time.sleep(0.05)
            return x + y

        workers.run_in_background(
            slow_op,
            3,
            7,
            on_finished=results.append,
            on_failed=errors.append,
        )

        start = time.time()
        while not results and not errors and time.time() - start < 1.0:
            QCoreApplication.processEvents()
            time.sleep(0.01)

        assert results == [10]
        assert errors == []

    def test_run_in_background_failure(self, qapp):
        results = []
        errors = []

        def failing_op():
            raise ValueError("Test error")

        workers.run_in_background(
            failing_op,
            on_finished=results.append,
            on_failed=errors.append,
        )

        start = time.time()
        while not results and not errors and time.time() - start < 1.0:
            QCoreApplication.processEvents()
            time.sleep(0.01)

        assert results == []
        assert len(errors) == 1
        assert str(errors[0]) == "Test error"

    def test_run_in_background_concurrent_and_progress(self, qapp):
        progress_data = []
        finished_data = []

        def worker_op(worker_id: int, progress_cb=None):
            if progress_cb:
                progress_cb(50)
            time.sleep(0.02)
            if progress_cb:
                progress_cb(100)
            return f"done-{worker_id}"

        threads = []
        for i in range(5):
            t = workers.run_in_background(
                worker_op,
                i,
                on_progress=lambda p, wid=i: progress_data.append((wid, p)),
                on_finished=finished_data.append,
            )
            threads.append(t)

        start = time.time()
        while len(finished_data) < 5 and time.time() - start < 2.0:
            QCoreApplication.processEvents()
            time.sleep(0.01)

        assert len(finished_data) == 5
        assert set(finished_data) == {f"done-{i}" for i in range(5)}
        assert len(progress_data) >= 10
        for t in threads:
            assert t.wait(timeout=1.0) is True
            assert t.isRunning() is False
