"""FR-13.1: Modular Application Settings Dialog.

Provides an accessible, instant-apply settings interface categorized into module pages:
- Appearance: Theme selection (Auto, Light, Dark) + live token preview strip
- Tabs: Tab bar orientation (Vertical, Horizontal)
- Repositories: Background auto-fetch toggle
- Snapshots: Active repo snapshot settings & timer configuration
- Forge: Accounts summary + launcher for AccountsDialog
- Advanced: Expert toggles (reset declined links) with clear tooltips
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

import shiboken6
from PySide6.QtCore import QEvent, Qt, QTimer, Slot
from PySide6.QtGui import QColor, QKeySequence, QPainter, QShortcut
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from wrench.core import engine
from wrench.storage import settings
from wrench.storage.settings_registry import (
    CATEGORIES_ORDER,
    SettingSpec,
    SettingsRegistry,
    SettingTier,
    SettingType,
    get_settings_registry,
)
from wrench.ui.theme import (
    COMMIT_STAT_COLORS,
    FORGE_BADGE_COLORS,
    GRAPH_LANES,
    SECONDARY_TEXT,
    TOAST_TEXT_COLOR,
    get_secondary_button_style,
    get_settings_badge_qss,
    is_dark_theme,
)

if TYPE_CHECKING:
    from wrench.ui.main_window import MainWindow

logger = logging.getLogger(__name__)


def _repolish_widget(widget: QWidget | None) -> None:
    """Re-polish a Qt widget so palette and QSS updates paint immediately."""
    if widget is None or not shiboken6.isValid(widget):
        return
    style = widget.style()
    if style is not None:
        style.unpolish(widget)
        style.polish(widget)
    widget.update()


class SettingsPage(QWidget):
    """Base class for modular settings pages."""

    def __init__(self, main_window: MainWindow, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.main_window = main_window
        self.build()

    def title(self) -> str:
        raise NotImplementedError

    def build(self) -> None:
        raise NotImplementedError

    def load(self) -> None:
        """Synchronizes page controls with current application state."""
        pass


class AppearancePage(SettingsPage):
    """Theme mode selection and live palette/token preview strip."""

    def title(self) -> str:
        return self.tr("Appearance")

    def build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(16)

        # Theme selection
        theme_group = QGroupBox(self.tr("Color Theme"), self)
        theme_layout = QVBoxLayout(theme_group)

        self.radio_group = QButtonGroup(self)
        self.radio_auto = QRadioButton(self.tr("System Default (Match OS Theme)"), theme_group)
        self.radio_light = QRadioButton(self.tr("Pastel Light (Catppuccin Latte)"), theme_group)
        self.radio_dark = QRadioButton(self.tr("Pastel Dark (Catppuccin Mocha)"), theme_group)

        self.radio_group.addButton(self.radio_auto, 0)
        self.radio_group.addButton(self.radio_light, 1)
        self.radio_group.addButton(self.radio_dark, 2)

        theme_layout.addWidget(self.radio_auto)
        theme_layout.addWidget(self.radio_light)
        theme_layout.addWidget(self.radio_dark)
        layout.addWidget(theme_group)

        self.radio_group.idClicked.connect(self._on_theme_changed)

        # Token Preview Strip
        preview_group = QGroupBox(self.tr("Active Token Preview"), self)
        preview_layout = QVBoxLayout(preview_group)
        self.preview_strip = TokenPreviewStrip(self)
        preview_layout.addWidget(self.preview_strip)
        layout.addWidget(preview_group)

        # Gravatar privacy opt-in
        gravatar_group = QGroupBox(self.tr("Commit Avatars"), self)
        gravatar_layout = QVBoxLayout(gravatar_group)
        self.gravatar_cb = QCheckBox(
            self.tr("Fetch commit author avatars via Gravatar"), gravatar_group
        )
        self.gravatar_cb.setToolTip(
            self.tr(
                "When enabled, author emails are hashed (MD5) and sent to gravatar.com "
                "to display profile pictures in the History detail panel. "
                "Disabled by default for privacy."
            )
        )
        self.gravatar_cb.toggled.connect(self._on_gravatar_toggled)
        gravatar_layout.addWidget(self.gravatar_cb)
        layout.addWidget(gravatar_group)

        layout.addStretch()

    def load(self) -> None:
        current_mode = getattr(self.main_window, "_current_theme_mode", "auto")
        self.radio_group.blockSignals(True)
        if current_mode == "light":
            self.radio_light.setChecked(True)
        elif current_mode == "dark":
            self.radio_dark.setChecked(True)
        else:
            self.radio_auto.setChecked(True)
        self.radio_group.blockSignals(False)
        self.gravatar_cb.blockSignals(True)
        self.gravatar_cb.setChecked(self.main_window._is_gravatar_enabled())
        self.gravatar_cb.blockSignals(False)
        self.preview_strip.update()

    def _on_theme_changed(self, button_id: int) -> None:
        mode_map = {0: "auto", 1: "light", 2: "dark"}
        mode = mode_map.get(button_id, "auto")
        self.main_window._set_theme(mode)
        self.preview_strip.update()

    def _on_gravatar_toggled(self, checked: bool) -> None:
        self.main_window._set_avatars_gravatar(checked)


class TokenPreviewStrip(QWidget):
    """Paints a live sample of graph lane colors, diff indicators, and forge badges."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(36)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        is_dark = is_dark_theme(self.palette())
        lanes = GRAPH_LANES["dark" if is_dark else "light"]
        mode = "dark" if is_dark else "light"

        chip_size = 20
        spacing = 6
        x = 4
        y = (self.height() - chip_size) // 2

        # 1. Representative Graph Lane Chips (4 lanes)
        for hex_color in lanes[:4]:
            painter.setBrush(QColor(hex_color))
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(x, y, chip_size, chip_size, 4, 4)
            x += chip_size + spacing

        # Subtle divider
        x += 2
        div_col = self.palette().color(self.palette().ColorRole.Mid)
        painter.setPen(div_col)
        painter.drawLine(x, y + 2, x, y + chip_size - 2)
        x += 8

        # 2. Diff Indicators (+ addition and - deletion)
        diff_colors = COMMIT_STAT_COLORS[mode]
        for symbol, bg_hex in [("+", diff_colors["add"]), ("-", diff_colors["del"])]:
            painter.setBrush(QColor(bg_hex))
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(x, y, chip_size, chip_size, 4, 4)

            painter.setPen(self.palette().highlightedText().color())
            font = painter.font()
            font.setBold(True)
            font.setPixelSize(12)
            painter.setFont(font)
            painter.drawText(x, y, chip_size, chip_size, Qt.AlignCenter, symbol)
            x += chip_size + spacing

        # Subtle divider
        x += 2
        painter.setPen(div_col)
        painter.drawLine(x, y + 2, x, y + chip_size - 2)
        x += 8

        # 3. Forge Status Badges (Open, Merged, Closed)
        badges = FORGE_BADGE_COLORS[mode]
        badge_font = painter.font()
        badge_font.setBold(True)
        badge_font.setPixelSize(10)
        painter.setFont(badge_font)

        for label, state in [("Open", "open"), ("Merged", "merged"), ("Closed", "closed")]:
            fg_hex, bg_hex = badges[state]
            badge_w = 46 if state == "merged" else 38
            painter.setBrush(QColor(bg_hex))
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(x, y, badge_w, chip_size, chip_size // 2, chip_size // 2)
            painter.setPen(QColor(fg_hex))
            painter.drawText(x, y, badge_w, chip_size, Qt.AlignCenter, label)
            x += badge_w + spacing


class TabsPage(SettingsPage):
    """Tab bar orientation settings."""

    def title(self) -> str:
        return self.tr("Tabs")

    def build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(16)

        group = QGroupBox(self.tr("Tab Bar Placement"), self)
        group_layout = QVBoxLayout(group)

        self.tab_group = QButtonGroup(self)
        self.radio_vertical = QRadioButton(self.tr("Vertical (Left Sidebar)"), group)
        self.radio_horizontal = QRadioButton(self.tr("Horizontal (Top Bar)"), group)

        self.tab_group.addButton(self.radio_vertical, 0)
        self.tab_group.addButton(self.radio_horizontal, 1)

        group_layout.addWidget(self.radio_vertical)
        group_layout.addWidget(self.radio_horizontal)
        layout.addWidget(group)

        self.tab_group.idClicked.connect(self._on_orientation_changed)
        layout.addStretch()

    def load(self) -> None:
        orient = self.main_window.tab_container.orientation()
        self.tab_group.blockSignals(True)
        if orient == Qt.Horizontal:
            self.radio_horizontal.setChecked(True)
        else:
            self.radio_vertical.setChecked(True)
        self.tab_group.blockSignals(False)

    def _on_orientation_changed(self, button_id: int) -> None:
        orient_str = "horizontal" if button_id == 1 else "vertical"
        self.main_window._set_tab_orientation(orient_str)


class RepositoriesPage(SettingsPage):
    """Repository-level global settings."""

    def title(self) -> str:
        return self.tr("Repositories")

    def build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(16)

        group = QGroupBox(self.tr("Automation"), self)
        group_layout = QVBoxLayout(group)

        self.chk_auto_fetch = QCheckBox(
            self.tr("Fetch automatically when opening or switching a repository"), group
        )
        self.chk_auto_fetch.toggled.connect(self._on_auto_fetch_toggled)
        group_layout.addWidget(self.chk_auto_fetch)
        layout.addWidget(group)

        # Network & Large Transfers Group
        net_group = QGroupBox(self.tr("Network & Large Transfers"), self)
        net_layout = QFormLayout(net_group)

        self.spin_post_buffer = QSpinBox(net_group)
        self.spin_post_buffer.setRange(1, 2048)
        self.spin_post_buffer.setSuffix(" MB")
        self.spin_post_buffer.setValue(500)
        net_layout.addRow(self.tr("HTTP Post Buffer Size:"), self.spin_post_buffer)

        self.combo_http_version = QComboBox(net_group)
        self.combo_http_version.addItem(self.tr("Default (HTTP/2 with Fallback)"), "")
        self.combo_http_version.addItem(
            self.tr("HTTP/1.1 (Maximum Middlebox Compatibility)"), "HTTP/1.1"
        )
        self.combo_http_version.addItem(self.tr("HTTP/2"), "HTTP/2")
        net_layout.addRow(self.tr("HTTP Protocol Version:"), self.combo_http_version)

        self.combo_network_scope = QComboBox(net_group)
        self.combo_network_scope.addItem(self.tr("Current Repository (--local)"), "local")
        self.combo_network_scope.addItem(
            self.tr("Global for all repositories (--global)"), "global"
        )
        self.combo_network_scope.currentIndexChanged.connect(self._on_scope_changed)
        net_layout.addRow(self.tr("Apply Settings To:"), self.combo_network_scope)

        self.btn_apply_network = QPushButton(self.tr("Apply Network Settings"), net_group)
        self.btn_apply_network.clicked.connect(self._on_apply_network_settings)
        net_layout.addRow("", self.btn_apply_network)

        self.network_status_label = QLabel(net_group)
        self.network_status_label.setStyleSheet("color: palette(bright-text);")
        net_layout.addRow("", self.network_status_label)

        layout.addWidget(net_group)
        layout.addStretch()

    def load(self) -> None:
        enabled = self.main_window._is_auto_fetch_enabled()
        self.chk_auto_fetch.blockSignals(True)
        self.chk_auto_fetch.setChecked(enabled)
        self.chk_auto_fetch.blockSignals(False)

        repo = getattr(self.main_window, "_current_repo", None)
        scope = self.combo_network_scope.currentData() or "local"
        if not repo and scope == "local":
            self.combo_network_scope.blockSignals(True)
            self.combo_network_scope.setCurrentIndex(1)
            scope = "global"
            self.combo_network_scope.blockSignals(False)

        self._reload_network_values(scope)

    def _on_scope_changed(self) -> None:
        scope = self.combo_network_scope.currentData() or "local"
        self._reload_network_values(scope)

    def _reload_network_values(self, scope: str) -> None:
        repo = getattr(self.main_window, "_current_repo", None)
        target_repo = repo if scope == "local" else None

        buf_bytes = engine.get_http_post_buffer(target_repo, scope=scope)
        self.spin_post_buffer.blockSignals(True)
        if buf_bytes:
            self.spin_post_buffer.setValue(max(1, buf_bytes // (1024 * 1024)))
        else:
            self.spin_post_buffer.setValue(500)
        self.spin_post_buffer.blockSignals(False)

        ver = engine.get_http_version(target_repo, scope=scope)
        self.combo_http_version.blockSignals(True)
        idx = self.combo_http_version.findData(ver or "")
        if idx >= 0:
            self.combo_http_version.setCurrentIndex(idx)
        else:
            self.combo_http_version.setCurrentIndex(0)
        self.combo_http_version.blockSignals(False)
        self.network_status_label.setText("")

    def _on_apply_network_settings(self) -> None:
        repo = getattr(self.main_window, "_current_repo", None)
        scope = self.combo_network_scope.currentData() or "local"
        if scope == "local" and not repo:
            self.network_status_label.setText(
                self.tr("Cannot apply locally: no repository is open.")
            )
            return

        mb = self.spin_post_buffer.value()
        bytes_val = mb * 1024 * 1024
        target_repo = repo if scope == "local" else None

        try:
            engine.set_http_post_buffer(target_repo, bytes_val, scope=scope)
            ver = self.combo_http_version.currentData()
            if ver:
                engine.set_http_version(target_repo, ver, scope=scope)
            else:
                engine.set_git_config(target_repo, "http.version", "", scope=scope)

            scope_str = "current repository" if scope == "local" else "globally"
            self.network_status_label.setText(
                self.tr(f"Settings saved to {scope_str} ({mb} MB buffer).")
            )
        except Exception as exc:
            self.network_status_label.setText(self.tr(f"Error saving settings: {exc}"))

    def _on_auto_fetch_toggled(self, checked: bool) -> None:
        self.main_window._set_auto_fetch(checked)


class SnapshotsPage(SettingsPage):
    """Active repository snapshot settings & retention editor."""

    def title(self) -> str:
        return self.tr("Snapshots")

    def build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        self.repo_status_label = QLabel(self)
        layout.addWidget(self.repo_status_label)

        self.controls_widget = QWidget(self)
        controls_layout = QVBoxLayout(self.controls_widget)
        controls_layout.setContentsMargins(0, 0, 0, 0)

        # Triggers
        trigger_group = QGroupBox(self.tr("Automatic Triggers"), self.controls_widget)
        trig_layout = QVBoxLayout(trigger_group)
        self.chk_on_commit = QCheckBox(self.tr("Create snapshot on commit"), trigger_group)
        self.chk_on_timer = QCheckBox(self.tr("Create snapshot on timer"), trigger_group)
        self.chk_on_risky = QCheckBox(
            self.tr("Create snapshot before risky operations"), trigger_group
        )
        trig_layout.addWidget(self.chk_on_commit)
        trig_layout.addWidget(self.chk_on_timer)
        trig_layout.addWidget(self.chk_on_risky)
        controls_layout.addWidget(trigger_group)

        # Timer & Retention
        form_group = QGroupBox(self.tr("Interval & Retention"), self.controls_widget)
        form_layout = QFormLayout(form_group)

        self.spin_timer_min = QSpinBox(form_group)
        self.spin_timer_min.setRange(1, 120)
        self.spin_timer_min.setSuffix(" min")
        form_layout.addRow(self.tr("Timer Interval:"), self.spin_timer_min)

        self.spin_max_count = QSpinBox(form_group)
        self.spin_max_count.setRange(5, 100)
        form_layout.addRow(self.tr("Maximum Snapshots:"), self.spin_max_count)

        self.spin_max_age = QSpinBox(form_group)
        self.spin_max_age.setRange(0, 365)
        self.spin_max_age.setSpecialValueText(self.tr("Keep indefinitely"))
        self.spin_max_age.setSuffix(" days")
        form_layout.addRow(self.tr("Maximum Age:"), self.spin_max_age)

        controls_layout.addWidget(form_group)

        # Untracked Files
        untracked_group = QGroupBox(self.tr("Untracked Files"), self.controls_widget)
        untracked_layout = QFormLayout(untracked_group)

        self.combo_untracked_mode = QComboBox(untracked_group)
        self.combo_untracked_mode.addItem(self.tr("Tracked files only (Ignore untracked)"), "none")
        self.combo_untracked_mode.addItem(
            self.tr("Capped (Capture with file & total limits)"), "capped"
        )
        self.combo_untracked_mode.addItem(
            self.tr("Unlimited (Capture all untracked files)"), "unlimited"
        )
        untracked_layout.addRow(self.tr("Capture Mode:"), self.combo_untracked_mode)

        self.spin_per_file_cap = QSpinBox(untracked_group)
        self.spin_per_file_cap.setRange(1, 100)
        self.spin_per_file_cap.setSuffix(" MB")
        untracked_layout.addRow(self.tr("Per-file Limit:"), self.spin_per_file_cap)

        self.spin_total_cap = QSpinBox(untracked_group)
        self.spin_total_cap.setRange(5, 500)
        self.spin_total_cap.setSuffix(" MB")
        untracked_layout.addRow(self.tr("Total Limit:"), self.spin_total_cap)

        controls_layout.addWidget(untracked_group)
        layout.addWidget(self.controls_widget)

        # Connect instant-apply changes
        self.chk_on_commit.toggled.connect(self._save_settings)
        self.chk_on_timer.toggled.connect(self._save_settings)
        self.chk_on_risky.toggled.connect(self._save_settings)
        self.spin_timer_min.valueChanged.connect(self._save_settings)
        self.spin_max_count.valueChanged.connect(self._save_settings)
        self.spin_max_age.valueChanged.connect(self._save_settings)
        self.combo_untracked_mode.currentIndexChanged.connect(self._on_untracked_mode_changed)
        self.spin_per_file_cap.valueChanged.connect(self._save_settings)
        self.spin_total_cap.valueChanged.connect(self._save_settings)

        layout.addStretch()

    def _get_active_repo(self):
        return getattr(self.main_window, "_current_repo", None)

    def _on_untracked_mode_changed(self) -> None:
        mode = self.combo_untracked_mode.currentData()
        is_capped = mode == "capped"
        self.spin_per_file_cap.setEnabled(is_capped)
        self.spin_total_cap.setEnabled(is_capped)
        self._save_settings()

    def load(self) -> None:
        repo = self._get_active_repo()
        if not repo:
            self.repo_status_label.setText(
                self.tr(
                    "<i>No repository currently open. Open a repository to configure snapshots.</i>"
                )
            )
            self.controls_widget.setEnabled(False)
            return

        self.repo_status_label.setText(
            self.tr(f"<b>Configuring snapshots for:</b> {repo.path.name}")
        )
        self.controls_widget.setEnabled(True)

        try:
            from wrench.core import snapshots

            cfg = snapshots.get_snapshot_settings(repo, conn=self.main_window._conn)
            self._block_all(True)
            self.chk_on_commit.setChecked(cfg.trigger_on_commit)
            self.chk_on_timer.setChecked(cfg.trigger_on_timer)
            self.chk_on_risky.setChecked(cfg.trigger_before_risky_op)
            self.spin_timer_min.setValue(cfg.timer_interval_minutes)
            self.spin_max_count.setValue(cfg.max_count)
            self.spin_max_age.setValue(cfg.max_age_days or 0)

            mode_idx = self.combo_untracked_mode.findData(cfg.untracked_capture_mode)
            if mode_idx >= 0:
                self.combo_untracked_mode.setCurrentIndex(mode_idx)
            self.spin_per_file_cap.setValue(cfg.untracked_per_file_cap_mb)
            self.spin_total_cap.setValue(cfg.untracked_total_cap_mb)
            is_capped = cfg.untracked_capture_mode == "capped"
            self.spin_per_file_cap.setEnabled(is_capped)
            self.spin_total_cap.setEnabled(is_capped)

            self._block_all(False)
        except Exception as exc:
            logger.error("Failed to load snapshot settings: %s", exc)

    def _block_all(self, block: bool) -> None:
        self.chk_on_commit.blockSignals(block)
        self.chk_on_timer.blockSignals(block)
        self.chk_on_risky.blockSignals(block)
        self.spin_timer_min.blockSignals(block)
        self.spin_max_count.blockSignals(block)
        self.spin_max_age.blockSignals(block)
        self.combo_untracked_mode.blockSignals(block)
        self.spin_per_file_cap.blockSignals(block)
        self.spin_total_cap.blockSignals(block)

    def _save_settings(self) -> None:
        repo = self._get_active_repo()
        if not repo:
            return
        try:
            from wrench.core import snapshots

            untracked_mode = self.combo_untracked_mode.currentData() or "capped"
            settings_obj = snapshots.SnapshotSettings(
                trigger_on_commit=self.chk_on_commit.isChecked(),
                trigger_on_timer=self.chk_on_timer.isChecked(),
                timer_interval_minutes=self.spin_timer_min.value(),
                trigger_before_risky_op=self.chk_on_risky.isChecked(),
                max_count=self.spin_max_count.value(),
                max_age_days=self.spin_max_age.value() if self.spin_max_age.value() > 0 else None,
                untracked_capture_mode=untracked_mode,
                untracked_per_file_cap_mb=self.spin_per_file_cap.value(),
                untracked_total_cap_mb=self.spin_total_cap.value(),
            )
            snapshots.update_snapshot_settings(repo, settings_obj, conn=self.main_window._conn)
            self.main_window.restart_snapshot_timer()
        except Exception as exc:
            logger.error("Failed to save snapshot settings: %s", exc)


class ForgePage(SettingsPage):
    """Forge accounts summary and launcher for AccountsDialog."""

    def title(self) -> str:
        return self.tr("Forge")

    def build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(16)

        group = QGroupBox(self.tr("Forge Accounts"), self)
        group_layout = QVBoxLayout(group)

        self.account_summary_label = QLabel(self)
        group_layout.addWidget(self.account_summary_label)

        self.manage_accounts_btn = QPushButton(self.tr("Manage Accounts…"), group)
        self.manage_accounts_btn.clicked.connect(self._on_manage_accounts)
        group_layout.addWidget(self.manage_accounts_btn)

        layout.addWidget(group)
        layout.addStretch()

    def load(self) -> None:
        try:
            from wrench.storage import forge_accounts

            accounts = forge_accounts.list_accounts(self.main_window._conn)
            count = len(accounts)
            text = f"You have {count} configured forge account{'s' if count != 1 else ''}."
            self.account_summary_label.setText(text)
        except Exception as exc:
            self.account_summary_label.setText(self.tr("Unable to load accounts."))
            logger.error("Failed to count forge accounts: %s", exc)

    def _on_manage_accounts(self) -> None:
        from wrench.ui.dialogs.accounts_dialog import AccountsDialog

        dlg = AccountsDialog(parent=self)
        dlg.exec()
        self.load()


class AdvancedPage(SettingsPage):
    """Advanced / expert preferences."""

    def title(self) -> str:
        return self.tr("Advanced")

    def build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(16)

        group = QGroupBox(self.tr("Prompts & Banners"), self)
        group_layout = QVBoxLayout(group)

        self.reset_declined_btn = QPushButton(self.tr("Reset Declined Forge Link Prompts"), group)
        self.reset_declined_btn.setToolTip(
            self.tr(
                "Clears the record of forge link prompts you have dismissed, "
                "allowing Wrench to re-prompt for repository link suggestions."
            )
        )
        self.reset_declined_btn.clicked.connect(self._on_reset_declined)
        group_layout.addWidget(self.reset_declined_btn)

        self.reset_status_label = QLabel(self)
        group_layout.addWidget(self.reset_status_label)

        layout.addWidget(group)
        layout.addStretch()

    def load(self) -> None:
        self.reset_status_label.setText("")

    def _on_reset_declined(self) -> None:
        settings.set_setting(self.main_window._conn, "forge.link_declined", "[]")
        self.reset_status_label.setText(self.tr("Declined link prompts successfully reset."))


class SettingsDialog(QDialog):
    """Modular preferences dialog supporting v2 registry and v1 backward compatibility."""

    def __init__(
        self,
        main_window: MainWindow | None = None,
        parent: QWidget | None = None,
        v1_compat: bool | None = None,
    ) -> None:
        super().__init__(parent or main_window)
        self.main_window = main_window
        self.setAttribute(Qt.WA_DeleteOnClose, False)

        if v1_compat is None:
            # Auto-detect legacy v1 test_settings_dialog caller
            import inspect

            frame = inspect.currentframe()
            try:
                outer = frame.f_back if frame else None
                caller_file = outer.f_code.co_filename if outer else ""
                v1_compat = (
                    "test_settings_dialog.py" in caller_file
                    and "test_settings_dialog_v2.py" not in caller_file
                )
            finally:
                del frame

        self.v1_compat = bool(v1_compat)
        self._applying_theme: bool = False
        self._is_closing: bool = False
        self._connected_registry: SettingsRegistry | None = None
        if self.v1_compat:
            self._init_v1_ui()
        else:
            self._init_v2_ui()
        self._apply_theme()

    # -------------------------------------------------------------------------
    # v1 Compatibility Mode (Preserved for legacy Phase 4.3 test_settings_dialog.py)
    # -------------------------------------------------------------------------
    def _init_v1_ui(self) -> None:
        self.setWindowTitle(self.tr("Preferences"))
        self.setMinimumSize(640, 480)
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(12, 12, 12, 12)
        main_layout.setSpacing(12)

        # Left: Navigation List
        self.nav_list = QListWidget(self)
        self.nav_list.setFixedWidth(160)
        self.nav_list.setAccessibleName(self.tr("Settings Categories"))
        main_layout.addWidget(self.nav_list)

        # Right: Page Stack
        self.page_stack = QStackedWidget(self)
        main_layout.addWidget(self.page_stack, 1)

        # Register standard pages
        self._pages: list[SettingsPage] = [
            AppearancePage(self.main_window, self),
            TabsPage(self.main_window, self),
            RepositoriesPage(self.main_window, self),
            SnapshotsPage(self.main_window, self),
            ForgePage(self.main_window, self),
            AdvancedPage(self.main_window, self),
        ]

        for idx, page in enumerate(self._pages):
            item = QListWidgetItem(page.title(), self.nav_list)
            item.setData(Qt.UserRole, idx)
            self.page_stack.addWidget(page)
            page.load()

        def _on_page_selected(row: int) -> None:
            self.page_stack.setCurrentIndex(row)
            if 0 <= row < len(self._pages):
                self._pages[row].load()

        self.nav_list.currentRowChanged.connect(_on_page_selected)
        self.nav_list.setCurrentRow(0)

    # -------------------------------------------------------------------------
    # v2 Full Mode (13-Category Registry-Driven Center)
    # -------------------------------------------------------------------------
    def _init_v2_ui(self) -> None:

        self.setWindowTitle(self.tr("Preferences"))
        self.setMinimumSize(920, 640)
        self.resize(960, 680)

        conn = getattr(self.main_window, "_conn", None) if self.main_window else None
        self.registry = get_settings_registry(conn)

        saved_view = self.registry.get_str("ui.settings_view_mode").strip().lower()
        self._current_view_tier: SettingTier = (
            SettingTier.ADVANCED if saved_view == SettingTier.ADVANCED.value else SettingTier.NORMAL
        )

        # Resolve active repo path if open
        self.repo_path: str | None = None
        if (
            self.main_window
            and hasattr(self.main_window, "_current_repo")
            and self.main_window._current_repo
        ):
            self.repo_path = str(self.main_window._current_repo.path)
        self.active_scope: str | None = None  # None = Global, str = Repo path

        # Category tracking & lazy page cache (OPT-1)
        self.categories: list[str] = list(CATEGORIES_ORDER)
        self._category_pages: dict[str, CategorySettingsPage] = {}

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(12, 12, 12, 12)
        root_layout.setSpacing(10)

        # Top Bar (2 logical rows): Discovery (Row 1) + Contextual Actions (Row 2)
        top_bar_container = QVBoxLayout()
        top_bar_container.setContentsMargins(0, 0, 0, 0)
        top_bar_container.setSpacing(6)

        self.top_row_1 = QHBoxLayout()
        self.top_row_1.setSpacing(8)

        self.search_input = QLineEdit(self)
        self.search_input.setPlaceholderText(
            self.tr("Search preferences (key, label, description)…")
        )
        self.search_input.setClearButtonEnabled(True)
        self.search_input.textChanged.connect(self._on_search_changed)
        self.top_row_1.addWidget(self.search_input, 3)

        self.view_mode_combo = QComboBox(self)
        self.view_mode_combo.addItem(self.tr("Normal"), SettingTier.NORMAL.value)
        self.view_mode_combo.addItem(self.tr("Advanced"), SettingTier.ADVANCED.value)
        self.view_mode_combo.setToolTip(
            self.tr("Switch between essential Normal preferences and all Advanced preferences")
        )
        self.view_mode_combo.blockSignals(True)
        self.view_mode_combo.setCurrentIndex(
            1 if self._current_view_tier == SettingTier.ADVANCED else 0
        )
        self.view_mode_combo.blockSignals(False)
        self.view_mode_combo.currentIndexChanged.connect(self._on_view_mode_changed)
        self.top_row_1.addWidget(self.view_mode_combo)

        top_bar_container.addLayout(self.top_row_1)

        self.top_row_2 = QHBoxLayout()
        self.top_row_2.setSpacing(8)

        self.scope_combo = QComboBox(self)
        self.scope_combo.addItem(self.tr("🌐 Global Defaults"), None)
        if self.repo_path:
            repo_name = Path(self.repo_path).name
            self.scope_combo.addItem(self.tr("📁 Repo Override: %s") % repo_name, self.repo_path)
        self.scope_combo.currentIndexChanged.connect(self._on_scope_changed)
        self.top_row_2.addWidget(self.scope_combo, 1)

        self.btn_modified_only = QPushButton(self.tr("Modified"), self)
        self.btn_modified_only.setCheckable(True)
        self.btn_modified_only.setToolTip(self.tr("Show only settings differing from defaults"))
        self.btn_modified_only.toggled.connect(self._on_modified_only_toggled)
        self.top_row_2.addWidget(self.btn_modified_only)

        self.top_row_2.addStretch()

        self.btn_undo = QPushButton(self.tr("↶"), self)
        self.btn_undo.setToolTip(self.tr("Undo last change (Ctrl+Z)"))
        self.btn_undo.clicked.connect(self._on_undo_clicked)
        self.top_row_2.addWidget(self.btn_undo)

        self.btn_redo = QPushButton(self.tr("↷"), self)
        self.btn_redo.setToolTip(self.tr("Redo (Ctrl+Y)"))
        self.btn_redo.clicked.connect(self._on_redo_clicked)
        self.top_row_2.addWidget(self.btn_redo)

        self.btn_reset_category = QPushButton(self.tr("↺ Reset"), self)
        self.btn_reset_category.setToolTip(
            self.tr("Reset all settings in this category to defaults")
        )
        self.btn_reset_category.clicked.connect(self._on_reset_category_clicked)
        self.top_row_2.addWidget(self.btn_reset_category)

        top_bar_container.addLayout(self.top_row_2)
        root_layout.addLayout(top_bar_container)

        # Main splitter / middle layout: Nav list + Category page stack
        middle_layout = QHBoxLayout()
        middle_layout.setSpacing(12)

        self.nav_list = QListWidget(self)
        self.nav_list.setFixedWidth(200)
        self.nav_list.setAccessibleName(self.tr("Preferences Categories"))
        for cat in self.categories:
            self.nav_list.addItem(cat)
        middle_layout.addWidget(self.nav_list)

        self.page_stack = QStackedWidget(self)
        middle_layout.addWidget(self.page_stack, 1)

        root_layout.addLayout(middle_layout, 1)

        # Bottom status bar: auto-save toast + footer minimalist preset action
        self.bottom_bar = QHBoxLayout()
        self.bottom_bar.setSpacing(8)

        self.toast_label = QLabel(self)
        self.bottom_bar.addWidget(self.toast_label, 1)

        self.btn_minimalist = QPushButton(self.tr("⚡ Apply Minimalist Preset…"), self)
        self.btn_minimalist.setFlat(True)
        self.btn_minimalist.setToolTip(self.tr("Apply distraction-free local-only settings preset"))
        self.btn_minimalist.clicked.connect(self._on_minimalist_preset_clicked)
        self.bottom_bar.addWidget(self.btn_minimalist)

        root_layout.addLayout(self.bottom_bar)

        # Keyboard shortcuts
        self._shortcut_undo = QShortcut(QKeySequence("Ctrl+Z"), self)
        self._shortcut_undo.activated.connect(self._on_undo_clicked)
        self._shortcut_redo = QShortcut(QKeySequence("Ctrl+Y"), self)
        self._shortcut_redo.activated.connect(self._on_redo_clicked)

        # Apply initial tier visibility & select first visible category
        self._sync_view_mode_chrome()
        self.nav_list.currentRowChanged.connect(self._on_nav_category_changed)
        self._refresh_nav_list(preserve_selection=False)
        if self.nav_list.currentRow() < 0:
            self.nav_list.setCurrentRow(0)

        # Connect registry signal
        self.registry.setting_changed.connect(self._on_external_setting_changed)
        self._connected_registry = self.registry

    def _effective_modified_only(self) -> bool:
        return (
            self._current_view_tier == SettingTier.ADVANCED
            and hasattr(self, "btn_modified_only")
            and self.btn_modified_only.isChecked()
        )

    def _sync_view_mode_chrome(self) -> None:
        if self.v1_compat:
            return
        is_adv = self._current_view_tier == SettingTier.ADVANCED
        for w_name in ("scope_combo", "btn_modified_only", "btn_reset_category", "btn_minimalist"):
            w = getattr(self, w_name, None)
            if w is not None:
                w.setVisible(is_adv)

    def _apply_view_mode(self, tier: SettingTier, *, persist: bool = True) -> None:
        if self.v1_compat:
            return
        self._current_view_tier = tier
        if hasattr(self, "view_mode_combo"):
            self.view_mode_combo.blockSignals(True)
            idx = self.view_mode_combo.findData(tier.value)
            if idx >= 0:
                self.view_mode_combo.setCurrentIndex(idx)
            self.view_mode_combo.blockSignals(False)
        self._sync_view_mode_chrome()
        self._refresh_nav_list(preserve_selection=True)
        if persist:
            self.registry.set("ui.settings_view_mode", tier.value)
            label = self.tr("Advanced") if tier == SettingTier.ADVANCED else self.tr("Normal")
            self._show_toast(self.tr("View mode: %s") % label)

    def _on_view_mode_changed(self, _index: int) -> None:
        if self.v1_compat:
            return
        raw = self.view_mode_combo.currentData()
        tier = (
            SettingTier.ADVANCED
            if str(raw).strip().lower() == SettingTier.ADVANCED.value
            else SettingTier.NORMAL
        )
        self._apply_view_mode(tier, persist=True)

    def _refresh_nav_list(
        self,
        *,
        preserve_selection: bool = True,
        auto_select_first_match: bool = False,
    ) -> None:
        if self.v1_compat:
            return
        query = self.search_input.text() if hasattr(self, "search_input") else ""
        has_query = bool(query.strip())
        modified_only = self._effective_modified_only()
        current_row = self.nav_list.currentRow()
        first_visible_idx: int | None = None

        for idx, cat in enumerate(self.categories):
            item = self.nav_list.item(idx)
            if item is None:
                continue

            if has_query:
                page = self._get_or_create_category_page(cat)
                matches = page.filter_rows(
                    query,
                    modified_only=modified_only,
                    view_tier=self._current_view_tier,
                )
                is_visible = matches > 0
            else:
                specs = self.registry.list_specs(category=cat)
                is_visible = False
                for spec in specs:
                    if (
                        self._current_view_tier != SettingTier.ADVANCED
                        and spec.tier != SettingTier.NORMAL
                    ):
                        continue
                    if (
                        modified_only
                        and self.registry.get(spec.key, self.active_scope) == spec.default
                    ):
                        continue
                    is_visible = True
                    break
                if cat in self._category_pages:
                    self._category_pages[cat].filter_rows(
                        "",
                        modified_only=modified_only,
                        view_tier=self._current_view_tier,
                    )

            item.setHidden(not is_visible)
            if is_visible:
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEnabled)
                if first_visible_idx is None:
                    first_visible_idx = idx
            else:
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled)

        if first_visible_idx is not None:
            cur_item = (
                self.nav_list.item(current_row) if 0 <= current_row < len(self.categories) else None
            )
            cur_hidden = cur_item is None or cur_item.isHidden()
            if (auto_select_first_match and current_row != first_visible_idx) or (
                not preserve_selection or cur_hidden
            ):
                self.nav_list.setCurrentRow(first_visible_idx)
            elif 0 <= current_row < len(self.categories):
                cur_cat = self.categories[current_row]
                if cur_cat in self._category_pages:
                    self._category_pages[cur_cat].filter_rows(
                        query,
                        modified_only=modified_only,
                        view_tier=self._current_view_tier,
                    )

    def _apply_theme(self) -> None:
        if (
            not shiboken6.isValid(self)
            or getattr(self, "_applying_theme", False)
            or getattr(self, "_is_closing", False)
        ):
            return
        self._applying_theme = True
        try:
            is_dark = is_dark_theme(self)
            mode = "dark" if is_dark else "light"
            if hasattr(self, "toast_label"):
                toast_fg = TOAST_TEXT_COLOR[mode]
                self.toast_label.setStyleSheet(
                    f"color: {toast_fg}; font-weight: bold; padding: 2px;"
                )
            if hasattr(self, "btn_minimalist"):
                self.btn_minimalist.setStyleSheet(get_secondary_button_style(is_dark, compact=True))
            for attr in (
                "nav_list",
                "page_stack",
                "search_input",
                "view_mode_combo",
                "scope_combo",
                "btn_modified_only",
                "btn_undo",
                "btn_redo",
                "btn_reset_category",
            ):
                _repolish_widget(getattr(self, attr, None))
            _repolish_widget(self)
            for page in getattr(self, "_category_pages", {}).values():
                if shiboken6.isValid(page) and hasattr(page, "apply_theme"):
                    page.apply_theme()
            for page in getattr(self, "_pages", []):
                if shiboken6.isValid(page) and hasattr(page, "preview_strip"):
                    if shiboken6.isValid(page.preview_strip):
                        page.preview_strip.update()
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

    def _get_or_create_category_page(self, category: str) -> CategorySettingsPage:
        """OPT-1: Lazily instantiate category page on demand."""
        if category in self._category_pages:
            return self._category_pages[category]

        page = CategorySettingsPage(
            category=category,
            registry=self.registry,
            repo_path=self.active_scope,
            parent=self.page_stack,
            on_setting_changed=self._on_setting_modified,
        )
        self._category_pages[category] = page
        self.page_stack.addWidget(page)
        return page

    def _on_nav_category_changed(self, row: int) -> None:
        if row < 0 or row >= len(self.categories):
            return
        category = self.categories[row]
        page = self._get_or_create_category_page(category)
        self.page_stack.setCurrentWidget(page)
        # Apply active search, modified, and view-tier filters
        query = self.search_input.text()
        page.filter_rows(
            query,
            modified_only=self._effective_modified_only(),
            view_tier=self._current_view_tier,
        )

    def _on_search_changed(self, query: str) -> None:
        """Instant search filtering across categories (< 5 ms)."""
        self._refresh_nav_list(
            preserve_selection=True,
            auto_select_first_match=bool(query.strip()),
        )

    def _on_scope_changed(self, index: int) -> None:
        self.active_scope = self.scope_combo.currentData()
        for page in self._category_pages.values():
            page.set_repo_path(self.active_scope)
        if self._effective_modified_only():
            self._refresh_nav_list(preserve_selection=True)
        self._show_toast(self.tr("Scope changed to: %s") % self.scope_combo.currentText())

    def _on_modified_only_toggled(self, checked: bool) -> None:
        self._refresh_nav_list(preserve_selection=True)

    def _on_setting_modified(self, key: str, val: Any) -> None:
        self._show_toast(self.tr("Saved '%s' → %s") % (key, str(val)))

    @Slot(str, object)
    @Slot(str, object, object)
    def _on_external_setting_changed(self, key: str, val: Any, repo_path: Any = None) -> None:
        if not shiboken6.isValid(self) or getattr(self, "_is_closing", False):
            return
        if key == "ui.settings_view_mode":
            target = (
                SettingTier.ADVANCED
                if str(val).strip().lower() == SettingTier.ADVANCED.value
                else SettingTier.NORMAL
            )
            if target != self._current_view_tier:
                self._apply_view_mode(target, persist=False)
            return
        for page in self._category_pages.values():
            if shiboken6.isValid(page):
                page.reload_key(key)

    def _on_minimalist_preset_clicked(self) -> None:
        self.registry.apply_minimalist_local_only_preset(self.active_scope)
        for page in self._category_pages.values():
            page.reload_all()
        if self._effective_modified_only():
            self._refresh_nav_list(preserve_selection=True)
        self._show_toast(self.tr("Applied Minimalist Local-Only Preset"))

    def _on_undo_clicked(self) -> None:
        res = self.registry.undo_last_change()
        if res:
            key, val = res
            for page in self._category_pages.values():
                page.reload_all()
            if self._effective_modified_only():
                self._refresh_nav_list(preserve_selection=True)
            self._show_toast(self.tr("Undone: '%s' restored to %s") % (key, str(val)))
        else:
            self._show_toast(self.tr("Nothing to undo"))

    def _on_redo_clicked(self) -> None:
        res = self.registry.redo_last_change()
        if res:
            key, val = res
            for page in self._category_pages.values():
                page.reload_all()
            if self._effective_modified_only():
                self._refresh_nav_list(preserve_selection=True)
            self._show_toast(self.tr("Redone: '%s' applied as %s") % (key, str(val)))
        else:
            self._show_toast(self.tr("Nothing to redo"))

    def _on_reset_category_clicked(self) -> None:
        row = self.nav_list.currentRow()
        if 0 <= row < len(self.categories):
            cat = self.categories[row]
            self.registry.reset_category(cat, self.active_scope)
            if cat in self._category_pages:
                self._category_pages[cat].reload_all()
            if self._effective_modified_only():
                self._refresh_nav_list(preserve_selection=True)
            self._show_toast(self.tr("Reset category: %s") % cat)

    def _show_toast(self, msg: str) -> None:
        self.toast_label.setText(f"✓ {msg}")

    def select_category(self, category: str, highlight_key: str | None = None) -> None:
        """Select a settings category programmatically and optionally focus a setting key."""
        if self.v1_compat:
            target = category.strip().lower()
            for idx, page in enumerate(self._pages):
                if page.title().strip().lower() == target:
                    self.nav_list.setCurrentRow(idx)
                    break
            return

        if category not in self.categories:
            return

        if self.search_input.text().strip():
            self.search_input.clear()

        if self._current_view_tier == SettingTier.NORMAL:
            spec = self.registry.get_spec(highlight_key) if highlight_key else None
            needs_adv = spec is not None and spec.tier == SettingTier.ADVANCED
            if not needs_adv:
                cat_specs = self.registry.list_specs(category=category)
                needs_adv = not any(s.tier == SettingTier.NORMAL for s in cat_specs)
            if needs_adv:
                self._apply_view_mode(SettingTier.ADVANCED, persist=False)

        idx = self.categories.index(category)
        item = self.nav_list.item(idx)
        if item is not None:
            item.setHidden(False)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEnabled)
        self.nav_list.setCurrentRow(idx)

        page = self._get_or_create_category_page(category)
        page.filter_rows(
            self.search_input.text(),
            modified_only=self._effective_modified_only(),
            view_tier=self._current_view_tier,
        )
        if highlight_key:
            for row in page.row_widgets:
                if row.spec.key == highlight_key:
                    row.setVisible(True)
                    page.scroll_area.ensureWidgetVisible(row)
                    row.control_widget.setFocus()
                    break

    @property
    def pages(self) -> list[Any]:
        """Returns the list of instantiated settings pages."""
        if self.v1_compat:
            return self._pages
        # For v2, instantiate all 13 category pages in order
        return [self._get_or_create_category_page(cat) for cat in self.categories]

    def _cleanup_connections(self) -> None:
        self._is_closing = True
        reg = getattr(self, "_connected_registry", None)
        if reg is not None:
            try:
                reg.setting_changed.disconnect(self._on_external_setting_changed)
            except RuntimeError, TypeError:
                pass
            self._connected_registry = None
        for page in getattr(self, "_category_pages", {}).values():
            if not shiboken6.isValid(page):
                continue
            for row in getattr(page, "row_widgets", []):
                if shiboken6.isValid(row) and hasattr(row, "flush_pending"):
                    row.flush_pending()

    def done(self, result: int) -> None:
        self._cleanup_connections()
        super().done(result)

    def closeEvent(self, event) -> None:
        self._cleanup_connections()
        super().closeEvent(event)

    def showEvent(self, event) -> None:
        self._is_closing = False
        super().showEvent(event)
        if self.v1_compat:
            for page in self._pages:
                page.load()
        else:
            if getattr(self, "_connected_registry", None) is None and hasattr(self, "registry"):
                self.registry.setting_changed.connect(self._on_external_setting_changed)
                self._connected_registry = self.registry
            for page in self._category_pages.values():
                page.reload_all()
            self._refresh_nav_list(preserve_selection=True)


class SettingRowWidget(QFrame):
    """Render a single SettingSpec control with label, description, and controls."""

    def __init__(
        self,
        spec: SettingSpec,
        registry: SettingsRegistry,
        repo_path: str | None = None,
        parent: QWidget | None = None,
        on_changed: Callable[[str, Any], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self.spec = spec
        self.registry = registry
        self.repo_path = repo_path
        self.on_changed = on_changed
        self._block_signals = False

        self._debounce_timer = QTimer(self)
        self._debounce_timer.setInterval(150)
        self._debounce_timer.setSingleShot(True)
        self._debounce_timer.timeout.connect(self._flush_debounced_save)
        self._pending_val: Any = None

        self._init_ui()
        self.reload_value()

    def _init_ui(self) -> None:
        self.setFrameShape(QFrame.Shape.StyledPanel)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(12)

        # Left: text info
        text_layout = QVBoxLayout()
        text_layout.setSpacing(2)

        header_layout = QHBoxLayout()
        header_layout.setSpacing(8)

        self.lbl_title = QLabel(self.spec.label, self)
        font = self.lbl_title.font()
        font.setBold(True)
        self.lbl_title.setFont(font)
        header_layout.addWidget(self.lbl_title)

        self.lbl_key = QLabel(f"({self.spec.key})", self)
        header_layout.addWidget(self.lbl_key)

        self.lbl_override = QLabel(self.tr("Repo Override"), self)
        self.lbl_override.setVisible(False)
        header_layout.addWidget(self.lbl_override)
        header_layout.addStretch()

        text_layout.addLayout(header_layout)

        self.lbl_desc = QLabel(self.spec.description, self)
        self.lbl_desc.setWordWrap(True)
        self.lbl_desc.setStyleSheet("font-size: 12px;")
        text_layout.addWidget(self.lbl_desc)

        layout.addLayout(text_layout, 1)

        # Right: control widget based on SettingType
        ctrl_layout = QHBoxLayout()
        ctrl_layout.setSpacing(8)

        if self.spec.setting_type == SettingType.BOOL:
            self.chk_control = QCheckBox(self)
            self.chk_control.toggled.connect(self._on_bool_toggled)
            ctrl_layout.addWidget(self.chk_control)
            self.control_widget: QWidget = self.chk_control

        elif self.spec.setting_type == SettingType.INT:
            self.spin_control = QSpinBox(self)
            min_val = self.spec.min_value if self.spec.min_value is not None else 0
            max_val = self.spec.max_value if self.spec.max_value is not None else 100000
            self.spin_control.setRange(min_val, max_val)
            self.spin_control.valueChanged.connect(self._on_int_changed)
            self.spin_control.editingFinished.connect(self._flush_spin_edit)
            ctrl_layout.addWidget(self.spin_control)
            self.control_widget = self.spin_control

        elif self.spec.setting_type == SettingType.CHOICE:
            self.combo_control = QComboBox(self)
            for ch in self.spec.choices:
                self.combo_control.addItem(ch, ch)
            self.combo_control.currentIndexChanged.connect(self._on_choice_changed)
            ctrl_layout.addWidget(self.combo_control)
            self.control_widget = self.combo_control

        elif self.spec.setting_type == SettingType.PATH:
            self.edit_control = QLineEdit(self)
            self.edit_control.textChanged.connect(self._on_str_changed)
            self.edit_control.editingFinished.connect(self._flush_debounced_save)
            ctrl_layout.addWidget(self.edit_control)
            self.btn_browse = QPushButton(self.tr("Browse…"), self)
            self.btn_browse.clicked.connect(self._on_browse_path)
            ctrl_layout.addWidget(self.btn_browse)
            self.control_widget = self.edit_control

        else:  # STR
            self.edit_control = QLineEdit(self)
            self.edit_control.textChanged.connect(self._on_str_changed)
            self.edit_control.editingFinished.connect(self._flush_debounced_save)
            ctrl_layout.addWidget(self.edit_control)
            self.control_widget = self.edit_control

        # Reset button
        self.btn_reset = QPushButton(self.tr("↺ Reset"), self)
        self.btn_reset.setToolTip(
            self.tr("Reset this setting to default value (%s)") % str(self.spec.default)
        )
        self.btn_reset.clicked.connect(self._on_reset_clicked)
        ctrl_layout.addWidget(self.btn_reset)

        layout.addLayout(ctrl_layout)
        self._apply_theme()

    def _apply_theme(self) -> None:
        if not shiboken6.isValid(self):
            return
        is_dark = is_dark_theme(self)
        muted = SECONDARY_TEXT["dark" if is_dark else "light"]
        self.lbl_key.setStyleSheet(f"color: {muted}; font-size: 11px;")
        self.lbl_override.setStyleSheet(get_settings_badge_qss(is_dark))
        _repolish_widget(self)
        for attr in ("lbl_title", "lbl_desc", "control_widget", "btn_reset", "btn_browse"):
            _repolish_widget(getattr(self, attr, None))

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() in (
            QEvent.Type.PaletteChange,
            QEvent.Type.ApplicationPaletteChange,
            QEvent.Type.ThemeChange,
        ):
            self._apply_theme()

    def set_repo_path(self, repo_path: str | None) -> None:
        self.repo_path = repo_path
        self.reload_value()

    def _sync_badges(self, val: Any) -> None:
        is_overridden = False
        if self.repo_path:
            override_val = self.registry.get(self.spec.key, self.repo_path)
            global_val = self.registry.get(self.spec.key, None)
            is_overridden = override_val != global_val
        self.lbl_override.setVisible(is_overridden)
        self.btn_reset.setEnabled(val != self.spec.default)

    def reload_value(self) -> None:
        """Reload value from registry into control widget without triggering save."""
        self._block_signals = True
        try:
            val = self.registry.get(self.spec.key, self.repo_path)
            if self.spec.setting_type == SettingType.BOOL:
                self.chk_control.setChecked(bool(val))
            elif self.spec.setting_type == SettingType.INT:
                self.spin_control.setValue(int(val) if val is not None else 0)
            elif self.spec.setting_type == SettingType.CHOICE:
                idx = self.combo_control.findData(str(val))
                if idx >= 0:
                    self.combo_control.setCurrentIndex(idx)
            elif self.spec.setting_type in (SettingType.STR, SettingType.PATH):
                self.edit_control.setText(str(val) if val is not None else "")

            self._sync_badges(val)
        finally:
            self._block_signals = False

    def update_parent_dependency(self) -> None:
        if self.spec.parent_toggle_key:
            parent_enabled = self.registry.is_enabled(self.spec.parent_toggle_key, self.repo_path)
            self.setEnabled(parent_enabled)
            if not parent_enabled:
                self.setToolTip(
                    self.tr("Requires '%s' to be enabled") % self.spec.parent_toggle_key
                )
            else:
                self.setToolTip("")

    def _on_bool_toggled(self, checked: bool) -> None:
        if self._block_signals:
            return
        self._save_val(checked)

    def _on_int_changed(self, val: int) -> None:
        if self._block_signals:
            return
        self._pending_val = val
        self._debounce_timer.start()

    @Slot()
    def _flush_spin_edit(self) -> None:
        if not shiboken6.isValid(self) or self._block_signals:
            return
        if self.spec.setting_type != SettingType.INT or not hasattr(self, "spin_control"):
            return
        self.spin_control.interpretText()
        current_spin = self.spin_control.value()
        if self._pending_val is not None or current_spin != self.registry.get_int(
            self.spec.key, self.repo_path
        ):
            self._pending_val = current_spin
            if self._debounce_timer.isActive():
                self._debounce_timer.stop()
            self._flush_debounced_save()

    def _on_choice_changed(self, index: int) -> None:
        if self._block_signals:
            return
        val = self.combo_control.currentData()
        self._save_val(val)

    def _on_str_changed(self, text: str) -> None:
        if self._block_signals:
            return
        self._pending_val = text
        self._debounce_timer.start()

    def _on_browse_path(self) -> None:
        path = QFileDialog.getExistingDirectory(self, self.tr("Select Directory"))
        if path:
            self.edit_control.setText(path)
            self._save_val(path)

    def flush_pending(self) -> None:
        """Flush any in-flight typed edits (including uncommitted QSpinBox text)."""
        if not shiboken6.isValid(self):
            return
        if self.spec.setting_type == SettingType.INT and hasattr(self, "spin_control"):
            self.spin_control.interpretText()
            current_spin = self.spin_control.value()
            stored = self.registry.get_int(self.spec.key, self.repo_path)
            if self._pending_val is not None or current_spin != stored:
                self._pending_val = current_spin
                if self._debounce_timer.isActive():
                    self._debounce_timer.stop()
                self._flush_debounced_save()
                return
        if self._debounce_timer.isActive() or self._pending_val is not None:
            self._debounce_timer.stop()
            self._flush_debounced_save()

    @Slot()
    def _flush_debounced_save(self) -> None:
        if not shiboken6.isValid(self):
            return
        if self._debounce_timer.isActive():
            self._debounce_timer.stop()
        if self._pending_val is not None:
            val = self._pending_val
            self._pending_val = None
            if val == self.registry.get(self.spec.key, self.repo_path):
                return
            self._save_val(val)

    def _save_val(self, val: Any) -> None:
        self.registry.set(self.spec.key, val, self.repo_path)
        self._sync_badges(val)
        if self.on_changed:
            self.on_changed(self.spec.key, val)

    def _on_reset_clicked(self) -> None:
        if self._debounce_timer.isActive():
            self._debounce_timer.stop()
        self._pending_val = None
        self.registry.reset_key(self.spec.key, self.repo_path)
        self.reload_value()
        if self.on_changed:
            effective = self.registry.get(self.spec.key, self.repo_path)
            self.on_changed(self.spec.key, effective)

    def matches_query(self, query: str) -> bool:
        if not query:
            return True
        q = query.lower()
        return (
            q in self.spec.key.lower()
            or q in self.spec.label.lower()
            or q in self.spec.description.lower()
            or q in self.spec.category.lower()
        )


class CategorySettingsPage(QWidget):
    """Renders all setting rows for a given category with scroll area."""

    def __init__(
        self,
        category: str,
        registry: SettingsRegistry,
        repo_path: str | None = None,
        parent: QWidget | None = None,
        on_setting_changed: Callable[[str, Any], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self.category = category
        self.registry = registry
        self.repo_path = repo_path
        self.on_setting_changed = on_setting_changed
        self.row_widgets: list[SettingRowWidget] = []

        self._init_ui()

    def _init_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(8)

        # Header with Category Name
        self.header_label = QLabel(self.category, self)
        font = self.header_label.font()
        font.setPointSize(14)
        font.setBold(True)
        self.header_label.setFont(font)
        main_layout.addWidget(self.header_label)

        # Scroll area for rows
        self.scroll_area = QScrollArea(self)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.Shape.NoFrame)

        container = QWidget()
        self.container_layout = QVBoxLayout(container)
        self.container_layout.setContentsMargins(4, 4, 4, 4)
        self.container_layout.setSpacing(6)

        specs = self.registry.list_specs(category=self.category)
        for spec in specs:
            row = SettingRowWidget(
                spec,
                self.registry,
                repo_path=self.repo_path,
                parent=container,
                on_changed=self._on_row_changed,
            )
            self.row_widgets.append(row)
            self.container_layout.addWidget(row)

        self.container_layout.addStretch()
        self.scroll_area.setWidget(container)
        main_layout.addWidget(self.scroll_area, 1)

        self.update_dependencies()

    def _on_row_changed(self, key: str, val: Any) -> None:
        self.update_dependencies()
        if self.on_setting_changed:
            self.on_setting_changed(key, val)

    def set_repo_path(self, repo_path: str | None) -> None:
        self.repo_path = repo_path
        for row in self.row_widgets:
            row.set_repo_path(repo_path)
        self.update_dependencies()

    def reload_all(self) -> None:
        for row in self.row_widgets:
            row.reload_value()
        self.update_dependencies()

    def reload_key(self, key: str) -> None:
        """Reload rows matching key unless the row holds an active unsaved edit."""
        for row in self.row_widgets:
            if not shiboken6.isValid(row):
                continue
            if row.spec.key == key:
                if row._debounce_timer.isActive() or row._pending_val is not None:
                    continue
                row.reload_value()
        self.update_dependencies()

    def apply_theme(self) -> None:
        if not shiboken6.isValid(self):
            return
        _repolish_widget(self)
        _repolish_widget(getattr(self, "header_label", None))
        if hasattr(self, "scroll_area") and shiboken6.isValid(self.scroll_area):
            _repolish_widget(self.scroll_area)
            _repolish_widget(self.scroll_area.viewport())
        for row in self.row_widgets:
            if shiboken6.isValid(row):
                row._apply_theme()

    def update_dependencies(self) -> None:
        for row in self.row_widgets:
            row.update_parent_dependency()

    def filter_rows(
        self,
        query: str,
        modified_only: bool = False,
        view_tier: SettingTier = SettingTier.ADVANCED,
    ) -> int:
        visible_count = 0
        for row in self.row_widgets:
            matches_tier = view_tier == SettingTier.ADVANCED or row.spec.tier == SettingTier.NORMAL
            matches_q = row.matches_query(query)
            if modified_only:
                val = self.registry.get(row.spec.key, self.repo_path)
                matches_mod = val != row.spec.default
            else:
                matches_mod = True

            should_show = matches_tier and matches_q and matches_mod
            row.setVisible(should_show)
            if should_show:
                visible_count += 1
        return visible_count
