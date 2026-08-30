"""Unit tests for BusyDialog and RecoveryDialog UI components."""

from pathlib import Path

from PySide6.QtWidgets import QApplication

from wrench.core.recovery.classifier import ErrorCategory, diagnose_error
from wrench.core.recovery.process_guard import GuardResult
from wrench.ui.recovery.busy_dialog import BusyDialog
from wrench.ui.recovery.recovery_dialog import RecoveryDialog


def _ensure_qapp():
    if not QApplication.instance():
        return QApplication([])
    return QApplication.instance()


class TestRecoveryUI:
    def test_busy_dialog_initialization(self, tmp_path: Path):
        _ensure_qapp()
        guard = GuardResult(
            status="busy",
            lock_path=tmp_path / "index.lock",
            pid=1234,
            process_cmd="git pull origin main",
            age_seconds=2.0,
        )
        dlg = BusyDialog(tmp_path, guard)
        assert dlg.windowTitle() == "Repository Busy"
        assert dlg.guard_result.pid == 1234
        dlg.close()

    def test_recovery_dialog_renders_actions(self, tmp_path: Path):
        _ensure_qapp()
        report = diagnose_error("hook id: black failed", stderr="black failed")
        assert report.category == ErrorCategory.HOOK_FAILURE

        dlg = RecoveryDialog(report, repo_path=tmp_path)
        assert len(dlg.action_buttons) == len(report.actions)
        dlg.close()
