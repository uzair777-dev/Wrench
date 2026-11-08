"""Phase 4.6: Live activity feed + expandable history dock.

Model: ActivityLogModel — deque(maxlen=200), QObject with entry_added signal.
Widget: ActivityLogBar — one-line dock above the status bar, Ctrl+` expands.

History is in-memory only. The durable record is FR-9.2's rotating file.
"""

import time
from collections import deque
from dataclasses import dataclass, field

from PySide6.QtCore import QObject, Qt, Signal, Slot
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)


@dataclass
class LogEntry:
    text: str
    level: str  # 'info' | 'ok' | 'warn' | 'error'
    timestamp: float = field(default_factory=time.time)

    @property
    def time_str(self) -> str:
        return time.strftime("%H:%M:%S", time.localtime(self.timestamp))


class ActivityLogModel(QObject):
    """Thread-safe in-memory activity log buffer."""

    entry_added = Signal(object)

    def __init__(self, maxlen: int = 200, parent: QObject | None = None):
        super().__init__(parent)
        self._maxlen = maxlen
        self._entries: deque[LogEntry] = deque(maxlen=maxlen)

    @property
    def entries(self) -> list[LogEntry]:
        return list(self._entries)

    def post(self, text: str, level: str = "info") -> None:
        entry = LogEntry(text=text, level=level)
        self._entries.append(entry)
        self.entry_added.emit(entry)


class ActivityLogBar(QWidget):
    """One-line activity log strip, docked above the status bar.

    Shows the latest event with a level icon + elided text + timestamp.
    A chevron click or Ctrl+` expands an inline ~8-line scrollback.
    """

    def __init__(self, model: ActivityLogModel, parent: QWidget | None = None):
        super().__init__(parent)
        self._model = model
        self._expanded = False
        self._init_ui()
        self._model.entry_added.connect(self._on_entry_added)

    def _init_ui(self) -> None:
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(4, 2, 4, 2)
        main_layout.setSpacing(0)

        # ── Top row: icon + latest line + timestamp + chevron ──
        top_row = QHBoxLayout()
        top_row.setContentsMargins(2, 0, 2, 0)
        top_row.setSpacing(6)

        self.level_icon = QLabel("●", self)
        self.level_icon.setFixedWidth(14)
        self.level_icon.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        top_row.addWidget(self.level_icon)

        self.latest_label = QLabel(self.tr("Ready"), self)
        self.latest_label.setTextFormat(Qt.TextFormat.PlainText)
        self.latest_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.latest_label.setMinimumWidth(100)
        self.latest_label.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        top_row.addWidget(self.latest_label)

        self.time_label = QLabel("", self)
        self.time_label.setStyleSheet("color: palette(placeholder-text); font-size: 11px;")
        self.time_label.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        top_row.addWidget(self.time_label)

        self.chevron_btn = QPushButton("▾", self)
        self.chevron_btn.setFixedSize(20, 20)
        self.chevron_btn.setFlat(True)
        self.chevron_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.chevron_btn.setToolTip(self.tr("Toggle activity history (Ctrl+`)"))
        self.chevron_btn.clicked.connect(self._toggle_expanded)
        top_row.addWidget(self.chevron_btn)

        main_layout.addLayout(top_row)

        # ── Expandable scrollback pane ──
        self.scrollback = QPlainTextEdit(self)
        self.scrollback.setReadOnly(True)
        self.scrollback.setMaximumBlockCount(200)
        self.scrollback.setFixedHeight(160)  # ~8 monospace lines
        self.scrollback.setVisible(False)
        self.scrollback.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        font = self.scrollback.font()
        font.setFamily("monospace")
        self.scrollback.setFont(font)
        main_layout.addWidget(self.scrollback)

        # Keyboard shortcut: Ctrl+`
        self._toggle_shortcut = QShortcut(QKeySequence("Ctrl+`"), self)
        self._toggle_shortcut.activated.connect(self._toggle_expanded)

    @Slot(object)
    def _on_entry_added(self, entry: LogEntry) -> None:
        level_colors = {
            "info": "palette(text)",
            "ok": "palette(highlight)",
            "warn": "palette(link)",
            "error": "palette(link-visited)",
        }
        color = level_colors.get(entry.level, "palette(text)")
        self.level_icon.setStyleSheet(f"color: {color};")

        self.latest_label.setText(entry.text)
        self.time_label.setText(entry.time_str)

        self.scrollback.appendPlainText(f"[{entry.time_str}] {entry.text}")

    @Slot()
    def _toggle_expanded(self) -> None:
        self._expanded = not self._expanded
        self.scrollback.setVisible(self._expanded)
        self.chevron_btn.setText("▴" if self._expanded else "▾")
