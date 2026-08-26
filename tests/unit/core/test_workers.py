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
