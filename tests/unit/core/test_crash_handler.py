"""Unit tests for core.crash_handler."""

from unittest.mock import MagicMock, patch

from wrench.core import crash_handler


def test_save_emergency_session(tmp_path):
    with patch("wrench.core.crash_handler.data_dir", return_value=tmp_path):
        session_file = crash_handler.save_emergency_session(
            RuntimeError("boom"), "traceback text", repo_path="/path/to/repo"
        )
        assert session_file.exists()
        content = session_file.read_text()
        assert "boom" in content
        assert "/path/to/repo" in content


def test_global_excepthook_takes_snapshot(tmp_path):
    mock_window = MagicMock()
    mock_window._current_repo = MagicMock()
    mock_window._conn = MagicMock()
    crash_handler.set_active_window(mock_window)

    with (
        patch("wrench.core.crash_handler.data_dir", return_value=tmp_path),
        patch("wrench.core.snapshots.take_snapshot") as mock_snap,
        patch("wrench.core.recovery.classifier.diagnose_error"),
        patch("wrench.ui.recovery.recovery_dialog.RecoveryDialog"),
        patch("PySide6.QtWidgets.QApplication.instance", return_value=None),
        patch("sys.__excepthook__"),
    ):
        try:
            raise ValueError("Test error")
        except ValueError as exc:
            crash_handler._global_excepthook(type(exc), exc, exc.__traceback__)

        mock_snap.assert_called_once_with(
            mock_window._current_repo,
            "emergency_crash",
            label="Emergency Snapshot before Crash Recovery",
            conn=mock_window._conn,
        )
