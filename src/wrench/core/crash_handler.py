"""Global crash handler and emergency session state preserver."""

from __future__ import annotations

import json
import logging
import sys
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any

from wrench.core.paths import data_dir
from wrench.core.recovery.classifier import diagnose_error

logger = logging.getLogger(__name__)

_installed = False
_active_window = None


def set_active_window(window: Any) -> None:
    """Register the active QMainWindow instance for emergency draft saving."""
    global _active_window
    _active_window = window


def save_emergency_session(
    error: Exception | str,
    tb_str: str,
    repo_path: str | None = None,
) -> Path:
    """Save uncommitted session state to emergency_session.json."""
    timestamp = datetime.now().isoformat()
    session_file = data_dir() / "emergency_session.json"
    session_file.parent.mkdir(parents=True, exist_ok=True)

    data = {
        "timestamp": timestamp,
        "error": str(error),
        "traceback": tb_str,
        "repo_path": repo_path or "",
        "commit_summary": "",
        "commit_description": "",
    }

    if _active_window and hasattr(_active_window, "changes_tab"):
        try:
            tab = _active_window.changes_tab
            data["commit_summary"] = tab.summary_input.text()
            data["commit_description"] = tab.desc_input.toPlainText()
        except Exception:
            pass

    try:
        session_file.write_text(json.dumps(data, indent=2), encoding="utf-8")
        logger.warning("Emergency session state saved to: %s", session_file)
    except Exception as e:
        logger.error("Failed to write emergency session file: %s", e)

    return session_file


def _global_excepthook(exc_type, exc_value, exc_tb) -> None:
    """Top-level exception catcher."""
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_tb)
        return

    tb_lines = traceback.format_exception(exc_type, exc_value, exc_tb)
    tb_str = "".join(tb_lines)
    logger.critical("Unhandled exception caught by Crash Handler:\n%s", tb_str)

    repo_path = None
    if _active_window and hasattr(_active_window, "_current_repo"):
        repo_path = str(_active_window._current_repo.path) if _active_window._current_repo else None

    # 1. Emergency session dump
    save_emergency_session(exc_value, tb_str, repo_path=repo_path)

    # 2. Emergency Snapshot
    if _active_window and getattr(_active_window, "_current_repo", None):
        try:
            from wrench.core import snapshots

            snapshots.take_snapshot(
                _active_window._current_repo,
                reason="emergency_crash",
                label="Emergency Snapshot before Crash Recovery",
                conn=getattr(_active_window, "db_conn", None),
            )
        except Exception as snap_err:
            logger.debug("Could not take emergency crash snapshot: %s", snap_err)

    # 3. Present UI Recovery Dialog if GUI application is active
    try:
        from PySide6.QtWidgets import QApplication

        from wrench.ui.recovery.recovery_dialog import RecoveryDialog

        if QApplication.instance() and _active_window:
            report = diagnose_error(
                exc_value,
                repo_path=repo_path,
                stderr=tb_str,
            )
            dialog = RecoveryDialog(report, repo_path=repo_path, parent=_active_window)
            dialog.exec()
            return
    except Exception as ui_err:
        logger.error("Failed to launch UI RecoveryDialog during crash: %s", ui_err)

    sys.__excepthook__(exc_type, exc_value, exc_tb)


def install_crash_handler(window: Any = None) -> None:
    """Install the global exception hook."""
    global _installed, _active_window
    if window:
        _active_window = window
    if not _installed:
        sys.excepthook = _global_excepthook
        _installed = True
        logger.info("Wrench Crash Handler and Session Preserver installed.")
