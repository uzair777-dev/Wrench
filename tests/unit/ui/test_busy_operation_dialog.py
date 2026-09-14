"""Unit tests for GitOperationWorker progress reconciliation and BusyOperationDialog."""

import threading

from PySide6.QtWidgets import QApplication

from wrench.ui.recovery.busy_dialog import BusyOperationDialog
from wrench.ui.workers import GitOperationWorker


def _ensure_qapp():
    if not QApplication.instance():
        return QApplication([])
    return QApplication.instance()


class TestGitOperationWorkerProgress:
    def test_worker_progress_adapter_handles_two_args(self, qtbot):
        def op(progress_cb=None):
            if progress_cb:
                progress_cb(42, "Counting objects")
            return "done"

        worker = GitOperationWorker(op)
        progress_values = []
        worker.progress.connect(progress_values.append)

        worker.run()
        assert progress_values == [42]

    def test_worker_cancel_event_injected(self):
        received_event = None

        def op(cancel_event=None):
            nonlocal received_event
            received_event = cancel_event

        my_cancel = threading.Event()
        worker = GitOperationWorker(op, cancel_event=my_cancel)
        worker.run()

        assert received_event is my_cancel


class TestBusyOperationDialog:
    def test_dialog_indeterminate_and_determinate(self):
        _ensure_qapp()
        dlg = BusyOperationDialog("Clone", "Cloning repository...")
        assert dlg.windowTitle() == "Clone"
        assert dlg.progress_bar.maximum() == 0  # Indeterminate

        dlg.set_progress(50)
        assert dlg.progress_bar.maximum() == 100
        assert dlg.progress_bar.value() == 50

        dlg.set_progress(0)
        assert dlg.progress_bar.maximum() == 0

        dlg.close()

    def test_dialog_cancel_triggers_event(self):
        _ensure_qapp()
        cancel_event = threading.Event()
        dlg = BusyOperationDialog("Push", "Pushing to remote...", cancel_event=cancel_event)

        assert not cancel_event.is_set()
        dlg.cancel_btn.click()

        assert cancel_event.is_set()
        assert "cancelling" in dlg.status_lbl.text().lower()
        assert not dlg.cancel_btn.isEnabled()

        dlg.close()
