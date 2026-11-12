"""Reusable CLI command preview footer widget (§5.3, SEC-3)."""

from __future__ import annotations

import logging
import shlex
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import shiboken6
from PySide6.QtCore import QEvent, Qt, QTimer, Slot
from PySide6.QtGui import QFont, QGuiApplication
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QToolButton, QWidget

from wrench.core import engine
from wrench.storage.settings_registry import SettingsRegistry, peek_settings_registry
from wrench.ui.theme import (
    CLI_PREVIEW_STYLES,
    SECONDARY_TEXT,
    get_icon_button_style,
    is_dark_theme,
)

logger = logging.getLogger(__name__)


class CliCommandPreviewBar(QFrame):
    """Collapsible footer displaying a secret-redacted equivalent git command."""

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        settings_registry: SettingsRegistry | None = None,
        repo_path: Path | str | None = None,
    ) -> None:
        super().__init__(parent)
        self._registry: SettingsRegistry | None = settings_registry
        self._connected_registry: SettingsRegistry | None = None
        self._repo_path: str | None = str(repo_path) if repo_path else None
        self._redacted_command: str = ""
        self._applying_theme: bool = False
        self._copy_reset_timer = QTimer(self)
        self._copy_reset_timer.setSingleShot(True)
        self._copy_reset_timer.timeout.connect(self._restore_copy_label)

        self._init_ui()
        self._apply_theme()
        self._ensure_registry_connection()
        self._refresh_visibility()

    def _init_ui(self) -> None:
        self.setFrameShape(QFrame.Shape.StyledPanel)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 5, 8, 5)
        layout.setSpacing(8)

        self.prefix_label = QLabel("$", self)
        mono_bold = QFont("Monospace", 9)
        mono_bold.setBold(True)
        self.prefix_label.setFont(mono_bold)
        layout.addWidget(self.prefix_label)

        self.command_label = QLabel("", self)
        self.command_label.setFont(QFont("Monospace", 9))
        self.command_label.setWordWrap(True)
        self.command_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.command_label, 1)

        self.copy_btn = QToolButton(self)
        self.copy_btn.setText(self.tr("Copy"))
        self.copy_btn.setToolTip(self.tr("Copy equivalent Git command to clipboard"))
        self.copy_btn.clicked.connect(self._on_copy_clicked)
        layout.addWidget(self.copy_btn)

    def _apply_theme(self) -> None:
        if self._applying_theme:
            return
        self._applying_theme = True
        try:
            mode = "dark" if is_dark_theme(self) else "light"
            palette = CLI_PREVIEW_STYLES[mode]
            bg = palette["bg"]
            border = palette["border"]
            fg = palette["fg"]
            muted = SECONDARY_TEXT[mode]
            self.setStyleSheet(
                f"CliCommandPreviewBar {{ background-color: {bg}; border: 1px solid {border}; "
                f"border-radius: 4px; }}"
            )
            self.prefix_label.setStyleSheet(
                f"color: {muted}; border: none; background: transparent;"
            )
            self.command_label.setStyleSheet(f"color: {fg}; border: none; background: transparent;")
            self.copy_btn.setStyleSheet(get_icon_button_style(mode == "dark"))
        finally:
            self._applying_theme = False

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() in (
            QEvent.Type.PaletteChange,
            QEvent.Type.ApplicationPaletteChange,
            QEvent.Type.ThemeChange,
        ):
            self._apply_theme()

    def _cleanup(self) -> None:
        if hasattr(self, "_copy_reset_timer") and shiboken6.isValid(self._copy_reset_timer):
            self._copy_reset_timer.stop()
        self._disconnect_registry()

    def closeEvent(self, event) -> None:
        self._cleanup()
        super().closeEvent(event)

    def _ensure_registry_connection(self) -> None:
        reg = self._registry or peek_settings_registry()
        if reg is self._connected_registry:
            return
        self._disconnect_registry()
        if reg is not None:
            reg.setting_changed.connect(
                self._on_setting_changed, Qt.ConnectionType.QueuedConnection
            )
            self._connected_registry = reg

    def _disconnect_registry(self, *_) -> None:
        reg = self._connected_registry
        if reg is None:
            return
        try:
            reg.setting_changed.disconnect(self._on_setting_changed)
        except RuntimeError, TypeError:
            pass
        self._connected_registry = None

    @Slot(str, object)
    @Slot(str, object, object)
    def _on_setting_changed(self, key: str, _value: Any, _repo_path: Any = None) -> None:
        if not shiboken6.isValid(self):
            return
        if key == "ui.show_cli_preview_in_dialogs":
            self._refresh_visibility()

    def set_settings_registry(self, registry: SettingsRegistry | None) -> None:
        """Bind or replace the SettingsRegistry instance driving visibility."""
        self._registry = registry
        self._ensure_registry_connection()
        self._refresh_visibility()

    def set_repo_path(self, repo_path: Path | str | None) -> None:
        """Update active repository scope for per-repo preview overrides."""
        self._repo_path = str(repo_path) if repo_path else None
        self._refresh_visibility()

    def set_command(self, command: str | Sequence[str]) -> None:
        """Format and redact a CLI invocation or list of git arguments."""
        if isinstance(command, str):
            raw = command.strip()
        else:
            parts = [str(part) for part in command if str(part) != ""]
            if parts and parts[0] != "git":
                parts = ["git", *parts]
            raw = shlex.join(parts)

        self._redacted_command = engine.redact_secrets(raw) if raw else ""
        self.command_label.setText(self._redacted_command)
        self.copy_btn.setEnabled(bool(self._redacted_command))
        self._ensure_registry_connection()
        self._refresh_visibility()

    @property
    def preview_text(self) -> str:
        """Return the currently displayed redacted CLI command text."""
        return self._redacted_command

    def _is_preview_enabled(self) -> bool:
        reg = self._registry or peek_settings_registry()
        if reg is None:
            return True
        return reg.is_enabled("ui.show_cli_preview_in_dialogs", self._repo_path)

    def _refresh_visibility(self) -> None:
        enabled = self._is_preview_enabled()
        self.setVisible(enabled and bool(self._redacted_command))

    def _on_copy_clicked(self) -> None:
        if not self._redacted_command:
            return
        cb = QGuiApplication.clipboard()
        if cb is not None:
            cb.setText(self._redacted_command)
        self.copy_btn.setText(self.tr("Copied ✓"))
        self._copy_reset_timer.start(1500)

    @Slot()
    def _restore_copy_label(self) -> None:
        if shiboken6.isValid(self) and shiboken6.isValid(self.copy_btn):
            self.copy_btn.setText(self.tr("Copy"))
