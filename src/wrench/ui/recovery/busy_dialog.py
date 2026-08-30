"""Dialog displayed when an external Git process is holding a repository lock."""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from wrench.core.recovery.process_guard import GuardResult, acquire_repo_guard, remove_lock

logger = logging.getLogger(__name__)


class BusyDialog(QDialog):
    """Non-blocking modal notifying user that another Git process is holding the repo lock."""

    lock_released = Signal()
    force_unlocked = Signal()

    def __init__(
        self,
        repo_path: Path | str,
        guard_result: GuardResult,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.repo_path = Path(repo_path)
        self.guard_result = guard_result
        self.setWindowTitle("Repository Busy")
        self.setMinimumWidth(480)
        self.setModal(True)

        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(500)
        self._poll_timer.timeout.connect(self._check_lock_status)

        self._elapsed_seconds = 0
        self._init_ui()
        self._poll_timer.start()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # Header with icon
        header_layout = QHBoxLayout()
        icon_lbl = QLabel("⏳", self)
        icon_lbl.setStyleSheet("font-size: 28px;")
        header_layout.addWidget(icon_lbl)

        title_layout = QVBoxLayout()
        title_lbl = QLabel("<b>Repository is Currently Busy</b>", self)
        title_lbl.setStyleSheet("font-size: 14px;")
        title_layout.addWidget(title_lbl)

        cmd = self.guard_result.process_cmd or "git operation"
        pid_text = f" (PID {self.guard_result.pid})" if self.guard_result.pid else ""
        proc_lbl = QLabel(
            f"Another Git process{pid_text} is accessing this repository:\n<b>{cmd}</b>",
            self,
        )
        proc_lbl.setWordWrap(True)
        title_layout.addWidget(proc_lbl)
        header_layout.addLayout(title_layout)
        layout.addLayout(header_layout)

        # Progress indicator
        self.status_lbl = QLabel("Waiting for lock to be released...", self)
        layout.addWidget(self.status_lbl)

        self.progress_bar = QProgressBar(self)
        self.progress_bar.setRange(0, 0)  # Indeterminate pulsing
        layout.addWidget(self.progress_bar)

        # Buttons
        btn_bar = QHBoxLayout()
        btn_bar.addStretch()

        self.force_btn = QPushButton("Force Release Lock", self)
        self.force_btn.setStyleSheet("color: #e74c3c;")
        # Enable force release if process is dead/stale or after waiting
        self.force_btn.clicked.connect(self._on_force_release)
        btn_bar.addWidget(self.force_btn)

        self.cancel_btn = QPushButton("Cancel", self)
        self.cancel_btn.clicked.connect(self.reject)
        btn_bar.addWidget(self.cancel_btn)

        layout.addLayout(btn_bar)

    def _check_lock_status(self) -> None:
        self._elapsed_seconds += 0.5
        res = acquire_repo_guard(self.repo_path, timeout=0.0)
        if res.status == "ready":
            self._poll_timer.stop()
            self.status_lbl.setText("Lock released! Proceeding...")
            self.lock_released.emit()
            self.accept()
        else:
            secs = int(self._elapsed_seconds)
            self.status_lbl.setText(f"Waiting for lock to be released... ({secs}s)")

    def _on_force_release(self) -> None:
        if self.guard_result.lock_path:
            remove_lock(self.guard_result.lock_path)
            self._poll_timer.stop()
            self.force_unlocked.emit()
            self.accept()

    def closeEvent(self, event) -> None:
        self._poll_timer.stop()
        super().closeEvent(event)
