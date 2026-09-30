"""Loading overlay widget for tab content areas.

Provides an inline spinner + label displayed over the TabContainer's
QStackedWidget during repository switching.  The overlay is a plain QWidget
parented to the stack so it automatically follows resizes.
"""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QPainter, QPen
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget


class SpinnerWidget(QWidget):
    """Lightweight animated spinner drawn with QPainter.

    Uses a 40 ms QTimer (~25 FPS) to rotate a partial arc.
    The timer stops automatically when the widget is hidden so
    zero CPU is consumed while invisible.
    """

    def __init__(self, parent: QWidget | None = None, size: int = 32):
        super().__init__(parent)
        self._angle = 0
        self._span = 270
        self._size = size
        self.setFixedSize(size, size)

        self._timer = QTimer(self)
        self._timer.setInterval(40)
        self._timer.timeout.connect(self._rotate)

    # ------------------------------------------------------------------
    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self._timer.start()

    def hideEvent(self, event) -> None:  # noqa: N802
        super().hideEvent(event)
        self._timer.stop()

    # ------------------------------------------------------------------
    def _rotate(self) -> None:
        self._angle = (self._angle + 10) % 360
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        pen = QPen(self.palette().highlight().color(), 3)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)

        margin = 4
        rect = QRectF(margin, margin, self._size - 2 * margin, self._size - 2 * margin)
        painter.drawArc(rect, self._angle * 16, self._span * 16)
        painter.end()


class TabLoadingOverlay(QWidget):
    """Full-area overlay displaying a spinner and message text.

    Intended to be positioned directly over a ``QStackedWidget`` to
    indicate an ongoing repository switch or data load.
    """

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("tab_loading_overlay")
        # Fill the entire parent with opaque background
        self.setAutoFillBackground(True)

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._spinner = SpinnerWidget(self, size=40)

        self._label = QLabel(self.tr("Loading…"), self)
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._label.setStyleSheet("font-size: 14px; color: palette(text);")

        row = QHBoxLayout()
        row.setAlignment(Qt.AlignmentFlag.AlignCenter)
        row.addWidget(self._spinner)
        layout.addLayout(row)
        layout.addWidget(self._label)

        self.hide()

    def show_loading(self, repo_name: str) -> None:
        """Display the overlay with *repo_name* in the message."""
        self._label.setText(self.tr(f"Loading {repo_name}…"))
        if self.parentWidget():
            self.setGeometry(self.parentWidget().rect())
        self.show()
        self.raise_()

    def hide_loading(self) -> None:
        """Hide the overlay and stop the spinner."""
        self.hide()
