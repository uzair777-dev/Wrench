"""Floating contextual help popover and toggle button."""

from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from wrench.ui.theme import is_dark_theme


class InfoPopover(QFrame):
    """Floating popover panel for contextual help text."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent, Qt.Popup | Qt.FramelessWindowHint)
        self.setMaximumWidth(360)
        self.setFrameShape(QFrame.StyledPanel)
        self.setFrameShadow(QFrame.Raised)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(6)

        header_layout = QHBoxLayout()
        header_layout.addStretch()
        self._close_btn = QToolButton(self)
        self._close_btn.setText("✕")
        self._close_btn.setFixedSize(18, 18)
        self._close_btn.setCursor(Qt.PointingHandCursor)
        self._close_btn.setStyleSheet(
            "QToolButton { border: none; font-size: 11px; "
            "font-weight: bold; background: transparent; }"
        )
        self._close_btn.clicked.connect(self.hide)
        header_layout.addWidget(self._close_btn)
        layout.addLayout(header_layout)

        self._label = QLabel(self)
        self._label.setWordWrap(True)
        self._label.setOpenExternalLinks(True)
        self._label.setTextFormat(Qt.RichText)
        layout.addWidget(self._label)

    def show_at(self, global_pos: QPoint, text: str) -> None:
        """Position the popover and show it with the given rich-text content."""
        self._label.setText(text)
        is_dark = is_dark_theme(self.palette())
        if is_dark:
            self.setStyleSheet(
                "InfoPopover { background-color: #313244; border: 1px solid #45475a; "
                "border-radius: 8px; } QLabel { color: #cdd6f4; font-size: 12px; } "
                "a { color: #89b4fa; text-decoration: underline; } "
                "QToolButton { color: #a6adc8; }"
            )
        else:
            self.setStyleSheet(
                "InfoPopover { background-color: #eff1f5; border: 1px solid #ccd0da; "
                "border-radius: 8px; } QLabel { color: #4c4f69; font-size: 12px; } "
                "a { color: #1e66f5; text-decoration: underline; } "
                "QToolButton { color: #7c7f93; }"
            )
        self.adjustSize()
        self.move(global_pos)
        self.show()


class InfoButton(QToolButton):
    """Small ℹ️ button that shows/hides an InfoPopover on click."""

    def __init__(self, tooltip_html: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setText("ℹ️")
        self.setAutoRaise(True)
        self.setFixedSize(24, 24)
        self.setCursor(Qt.WhatsThisCursor)
        self._tooltip_html = tooltip_html
        self._popover: InfoPopover | None = None
        self.clicked.connect(self._toggle_popover)

    def set_tooltip_html(self, html: str) -> None:
        """Update the popover content (e.g. when provider changes)."""
        self._tooltip_html = html
        if self._popover and self._popover.isVisible():
            self._popover._label.setText(html)
            self._popover.adjustSize()

    def _toggle_popover(self) -> None:
        if self._popover and self._popover.isVisible():
            self._popover.hide()
            return
        if not self._popover:
            self._popover = InfoPopover(self)
        pos = self.mapToGlobal(QPoint(0, self.height() + 4))
        self._popover.show_at(pos, self._tooltip_html)
