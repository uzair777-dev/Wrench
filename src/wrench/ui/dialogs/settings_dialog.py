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
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from wrench.storage import settings
from wrench.ui.theme import (
    GRAPH_LANES,
    is_dark_theme,
)

if TYPE_CHECKING:
    from wrench.ui.main_window import MainWindow

logger = logging.getLogger(__name__)


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
        self.preview_strip.update()

    def _on_theme_changed(self, button_id: int) -> None:
        mode_map = {0: "auto", 1: "light", 2: "dark"}
        mode = mode_map.get(button_id, "auto")
        self.main_window._set_theme(mode)
        self.preview_strip.update()


class TokenPreviewStrip(QWidget):
    """Paints a live sample of graph lane colors."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(36)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        is_dark = is_dark_theme(self.palette())
        lanes = GRAPH_LANES["dark" if is_dark else "light"]

        chip_size = 20
        spacing = 8
        x = 4
        y = (self.height() - chip_size) // 2

        for hex_color in lanes[:8]:
            painter.setBrush(QColor(hex_color))
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(x, y, chip_size, chip_size, 4, 4)
            x += chip_size + spacing


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

        layout.addStretch()

    def load(self) -> None:
        enabled = self.main_window._is_auto_fetch_enabled()
        self.chk_auto_fetch.blockSignals(True)
        self.chk_auto_fetch.setChecked(enabled)
        self.chk_auto_fetch.blockSignals(False)

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
        layout.addWidget(self.controls_widget)

        # Connect instant-apply changes
        self.chk_on_commit.toggled.connect(self._save_settings)
        self.chk_on_timer.toggled.connect(self._save_settings)
        self.chk_on_risky.toggled.connect(self._save_settings)
        self.spin_timer_min.valueChanged.connect(self._save_settings)
        self.spin_max_count.valueChanged.connect(self._save_settings)
        self.spin_max_age.valueChanged.connect(self._save_settings)

        layout.addStretch()

    def _get_active_repo(self):
        return getattr(self.main_window, "_current_repo", None)

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

    def _save_settings(self) -> None:
        repo = self._get_active_repo()
        if not repo:
            return
        try:
            from wrench.core import snapshots

            cfg = snapshots.get_snapshot_settings(repo, conn=self.main_window._conn)
            settings_obj = snapshots.SnapshotSettings(
                trigger_on_commit=self.chk_on_commit.isChecked(),
                trigger_on_timer=self.chk_on_timer.isChecked(),
                timer_interval_minutes=self.spin_timer_min.value(),
                trigger_before_risky_op=self.chk_on_risky.isChecked(),
                max_count=self.spin_max_count.value(),
                max_age_days=self.spin_max_age.value() if self.spin_max_age.value() > 0 else None,
                untracked_capture_mode=cfg.untracked_capture_mode,
                untracked_per_file_cap_mb=cfg.untracked_per_file_cap_mb,
                untracked_total_cap_mb=cfg.untracked_total_cap_mb,
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
    """Modular modal settings dialog with instantaneous application of preferences."""

    def __init__(self, main_window: MainWindow, parent: QWidget | None = None) -> None:
        super().__init__(parent or main_window)
        self.main_window = main_window
        self.setWindowTitle(self.tr("Preferences"))
        self.setMinimumSize(640, 480)
        self.setAttribute(Qt.WA_DeleteOnClose, False)

        self._init_ui()

    def _init_ui(self) -> None:
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

    @property
    def pages(self) -> list[SettingsPage]:
        """Returns the list of instantiated settings pages."""
        return self._pages

    def showEvent(self, event) -> None:
        """Reloads all pages to synchronize controls with current application state."""
        super().showEvent(event)
        for page in self._pages:
            page.load()
