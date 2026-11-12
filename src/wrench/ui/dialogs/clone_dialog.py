"""Partial Clone Dialog with Filter Mode & Sparse-Checkout Options (§6.2, SEC-2/SEC-3)."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import shiboken6
from PySide6.QtCore import QEvent, Qt, Slot
from PySide6.QtWidgets import (
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
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from wrench.core import engine
from wrench.core.remote_urls import host_of_instance_url, parse_remote_url
from wrench.storage import forge_accounts
from wrench.storage.settings_registry import SettingsRegistry, peek_settings_registry
from wrench.ui.theme import (
    PRIMARY_BUTTON_STYLES,
    SECONDARY_TEXT,
    get_banner_style,
    get_icon_button_style,
    get_secondary_button_style,
    get_status_pill_style,
    is_dark_theme,
)
from wrench.ui.widgets.cli_preview_bar import CliCommandPreviewBar

logger = logging.getLogger(__name__)


class CloneDialog(QDialog):
    """Clone dialog with partial clone filters, sparse checkout, and account picker."""

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        settings_registry: SettingsRegistry | None = None,
        conn: Any = None,
        initial_url: str = "",
        initial_dest_parent: str = "",
    ) -> None:
        super().__init__(parent)
        self._registry: SettingsRegistry | None = settings_registry
        self._connected_registry: SettingsRegistry | None = None
        self._conn = conn
        self._matched_accounts: list[Any] = []
        self._applying_theme: bool = False
        self._settings_open: bool = False

        self.setWindowTitle(self.tr("Clone Git Repository"))
        self.setMinimumWidth(560)
        self.resize(620, 420)

        self._init_ui()
        self._apply_theme()
        self._ensure_registry_connection()
        self._apply_default_filter_from_registry()
        self._sync_sparse_option_visibility()

        if initial_url:
            self.url_input.setText(initial_url)
        if initial_dest_parent:
            self.dest_parent_input.setText(initial_dest_parent)

        self._refresh_account_candidates()
        self._update_resolved_dest_and_preview()

    def _init_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(10)

        # Header
        header = QHBoxLayout()
        title_label = QLabel(self.tr("Clone Git Repository"), self)
        title_label.setStyleSheet("font-size: 15px; font-weight: bold;")
        header.addWidget(title_label)
        header.addStretch()

        self.settings_btn = QToolButton(self)
        self.settings_btn.setText("⚙")
        self.settings_btn.setToolTip(self.tr("Open Partial-Clone & Remote Preferences"))
        self.settings_btn.clicked.connect(self._on_open_settings_clicked)
        header.addWidget(self.settings_btn)
        root.addLayout(header)

        # Inline non-modal Preferences-active banner
        self.settings_open_banner = QFrame(self)
        self.settings_open_banner.setFrameShape(QFrame.Shape.StyledPanel)
        self.settings_open_banner.setVisible(False)
        settings_banner_layout = QHBoxLayout(self.settings_open_banner)
        settings_banner_layout.setContentsMargins(8, 6, 8, 6)
        settings_banner_layout.setSpacing(8)
        self.settings_open_label = QLabel(
            self.tr("Preferences is currently open — close Preferences to continue here."),
            self.settings_open_banner,
        )
        self.settings_open_label.setWordWrap(True)
        settings_banner_layout.addWidget(self.settings_open_label, 1)
        self.focus_settings_btn = QPushButton(
            self.tr("Focus Preferences"), self.settings_open_banner
        )
        self.focus_settings_btn.clicked.connect(self._on_focus_settings_clicked)
        settings_banner_layout.addWidget(self.focus_settings_btn)
        root.addWidget(self.settings_open_banner)

        # Inline non-modal error banner
        self.error_banner = QFrame(self)
        self.error_banner.setFrameShape(QFrame.Shape.StyledPanel)
        self.error_banner.setVisible(False)
        err_layout = QHBoxLayout(self.error_banner)
        err_layout.setContentsMargins(8, 6, 8, 6)
        self.error_label = QLabel(self.error_banner)
        self.error_label.setWordWrap(True)
        err_layout.addWidget(self.error_label)
        root.addWidget(self.error_banner)

        # Form inputs
        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        form.setSpacing(8)

        self.url_input = QLineEdit(self)
        self.url_input.setPlaceholderText(
            self.tr("https://github.com/org/repo.git or git@github.com:org/repo.git")
        )
        self.url_input.textChanged.connect(self._on_inputs_changed)
        form.addRow(self.tr("Repository URL:"), self.url_input)

        dest_row = QHBoxLayout()
        dest_row.setSpacing(6)
        self.dest_parent_input = QLineEdit(self)
        self.dest_parent_input.setPlaceholderText(self.tr("Parent directory…"))
        self.dest_parent_input.textChanged.connect(self._on_inputs_changed)
        dest_row.addWidget(self.dest_parent_input, 1)

        self.browse_btn = QPushButton(self.tr("Browse…"), self)
        self.browse_btn.clicked.connect(self._on_browse_dest)
        dest_row.addWidget(self.browse_btn)
        form.addRow(self.tr("Clone Into:"), dest_row)

        self.resolved_dest_label = QLabel("", self)
        self.resolved_dest_label.setWordWrap(True)
        form.addRow(self.tr("Destination Path:"), self.resolved_dest_label)

        self.filter_combo = QComboBox(self)
        self.filter_combo.addItem(self.tr("Full Clone (All Objects)"), "none")
        self.filter_combo.addItem(
            self.tr("Blobless Partial Clone (--filter=blob:none — Recommended for Monorepos)"),
            "blob:none",
        )
        self.filter_combo.addItem(
            self.tr("Treeless Partial Clone (--filter=tree:0 — Ultra-Light)"),
            "tree:0",
        )
        self.filter_combo.currentIndexChanged.connect(self._update_resolved_dest_and_preview)
        form.addRow(self.tr("Partial Clone Filter:"), self.filter_combo)

        root.addLayout(form)

        # Inline multi-account disambiguation group (FR-5.9)
        self.account_group = QGroupBox(self.tr("Forge Account (Multiple Matches Found)"), self)
        self.account_group.setVisible(False)
        acc_layout = QVBoxLayout(self.account_group)
        acc_layout.setSpacing(4)
        self.account_hint_label = QLabel(
            self.tr("Select which stored forge account should authenticate and link this clone:"),
            self.account_group,
        )
        self.account_hint_label.setWordWrap(True)
        acc_layout.addWidget(self.account_hint_label)
        self.account_list = QListWidget(self.account_group)
        self.account_list.setAccessibleName(self.tr("Forge accounts"))
        self.account_list.setMaximumHeight(110)
        acc_layout.addWidget(self.account_list)
        root.addWidget(self.account_group)

        # Sparse-checkout toggle
        self.sparse_checkbox = QCheckBox(
            self.tr("Initialize Sparse-Checkout and pick directories after clone (--sparse)"),
            self,
        )
        self.sparse_checkbox.toggled.connect(self._update_resolved_dest_and_preview)
        root.addWidget(self.sparse_checkbox)

        # Equivalent CLI Command Preview Footer (§5.3, SEC-3)
        self.preview_bar = CliCommandPreviewBar(self, settings_registry=self._registry)
        root.addWidget(self.preview_bar)

        # Action footer
        footer = QHBoxLayout()
        footer.addStretch()

        self.cancel_btn = QPushButton(self.tr("Cancel"), self)
        self.cancel_btn.clicked.connect(self.reject)
        footer.addWidget(self.cancel_btn)

        self.clone_btn = QPushButton(self.tr("Clone Repository"), self)
        self.clone_btn.setDefault(True)
        self.clone_btn.clicked.connect(self._on_clone_clicked)
        footer.addWidget(self.clone_btn)

        root.addLayout(footer)

    def _apply_theme(self) -> None:
        if self._applying_theme:
            return
        self._applying_theme = True
        try:
            is_dark = is_dark_theme(self)
            mode = "dark" if is_dark else "light"
            err_style = get_banner_style("error", is_dark)
            self.error_banner.setStyleSheet(
                f"QFrame {{ background-color: {err_style['bg']}; "
                f"border: 1px solid {err_style['border']}; border-radius: 4px; }}"
            )
            self.error_label.setStyleSheet(
                f"color: {err_style['fg']}; font-weight: bold; "
                "border: none; background: transparent;"
            )

            info_style = get_status_pill_style("info", is_dark)
            self.settings_open_banner.setStyleSheet(
                f"QFrame {{ background-color: {info_style['bg']}; "
                f"border: 1px solid {info_style['border']}; border-radius: 4px; }}"
            )
            self.settings_open_label.setStyleSheet(
                f"color: {info_style['fg']}; font-weight: bold; "
                "border: none; background: transparent;"
            )
            self.focus_settings_btn.setStyleSheet(get_secondary_button_style(is_dark, compact=True))

            self._update_resolved_dest_label_style()
            self.clone_btn.setStyleSheet(PRIMARY_BUTTON_STYLES[mode])
            self.cancel_btn.setStyleSheet(get_secondary_button_style(is_dark))
            self.browse_btn.setStyleSheet(get_secondary_button_style(is_dark, compact=True))
            self.settings_btn.setStyleSheet(get_icon_button_style(is_dark))
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

    def _cleanup_connections(self) -> None:
        self._disconnect_registry()
        if hasattr(self, "preview_bar") and shiboken6.isValid(self.preview_bar):
            self.preview_bar._cleanup()

    def done(self, result: int) -> None:
        self._cleanup_connections()
        super().done(result)

    def closeEvent(self, event) -> None:
        self._cleanup_connections()
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
        if key == "clone.default_filter_mode":
            self._apply_default_filter_from_registry()
        elif key == "monorepo.sparse_checkout_ui.enabled":
            self._sync_sparse_option_visibility()

    def _apply_default_filter_from_registry(self) -> None:
        reg = self._registry or peek_settings_registry()
        if reg is None:
            return
        default_mode = str(reg.get("clone.default_filter_mode") or "none")
        self.set_filter_mode(default_mode)

    def _sync_sparse_option_visibility(self) -> None:
        reg = self._registry or peek_settings_registry()
        enabled = True if reg is None else reg.is_enabled("monorepo.sparse_checkout_ui.enabled")
        if not enabled:
            self.sparse_checkbox.setChecked(False)
        self.sparse_checkbox.setVisible(enabled)
        self._update_resolved_dest_and_preview()

    def set_filter_mode(self, mode: str) -> None:
        """Select filter option ('none', 'blob:none', or 'tree:0')."""
        idx = self.filter_combo.findData(mode)
        if idx >= 0:
            self.filter_combo.setCurrentIndex(idx)

    def clone_url(self) -> str:
        return self.url_input.text().strip()

    def dest_parent(self) -> str:
        return self.dest_parent_input.text().strip()

    def repo_name(self) -> str:
        clean_url = self.clone_url()
        if not clean_url:
            return "repository"
        base = clean_url.split("#", 1)[0].split("?", 1)[0].rstrip("/\\")
        if not base:
            return "repository"
        raw_name = base.rsplit("/", 1)[-1]
        if ":" in raw_name and "://" not in base:
            raw_name = raw_name.rsplit(":", 1)[-1]
        raw_name = raw_name.replace("\\", "/").rsplit("/", 1)[-1]
        raw_name = "".join(ch for ch in raw_name if ch >= " " and ch != "\x7f").strip()
        if raw_name.endswith(".git"):
            raw_name = raw_name[:-4]
        raw_name = raw_name.strip()
        if not raw_name or raw_name in (".", "..") or raw_name.startswith("-") or "/" in raw_name:
            return "repository"
        return raw_name

    def target_dest(self) -> str:
        parent_dir = self.dest_parent()
        if not parent_dir:
            return self.repo_name()
        return str(Path(parent_dir) / self.repo_name())

    def filter_spec(self) -> str:
        return str(self.filter_combo.currentData() or "none")

    def sparse_enabled(self) -> bool:
        return bool(not self.sparse_checkbox.isHidden() and self.sparse_checkbox.isChecked())

    def selected_account_id(self) -> int | None:
        if self.account_group.isHidden():
            return None
        current = self.account_list.currentItem()
        if current is None:
            return None
        val = current.data(Qt.ItemDataRole.UserRole)
        return int(val) if val is not None else None

    def _on_inputs_changed(self) -> None:
        self.error_banner.setVisible(False)
        self._refresh_account_candidates()
        self._update_resolved_dest_and_preview()

    def _refresh_account_candidates(self) -> None:
        clean_url = self.clone_url()
        self._matched_accounts = []
        self.account_list.clear()

        if self._conn is None or not clean_url:
            self.account_group.setVisible(False)
            return

        parts = parse_remote_url(clean_url)
        if not parts or parts.protocol not in ("https", "http") or not parts.host:
            self.account_group.setVisible(False)
            return

        try:
            all_accounts = forge_accounts.list_accounts(self._conn)
        except Exception as exc:
            logger.debug("Could not inspect forge accounts during clone setup: %s", exc)
            all_accounts = []

        candidates = [a for a in all_accounts if host_of_instance_url(a.instance_url) == parts.host]
        if len(candidates) < 2:
            self.account_group.setVisible(False)
            return

        self._matched_accounts = candidates
        for acc in candidates:
            item = QListWidgetItem(
                f"{acc.label} ({acc.provider} — {acc.username or 'no username'})"
            )
            item.setData(Qt.ItemDataRole.UserRole, acc.id)
            self.account_list.addItem(item)
        self.account_list.setCurrentRow(0)
        self.account_group.setVisible(True)

    def _update_resolved_dest_label_style(self) -> None:
        is_dark = is_dark_theme(self)
        muted = SECONDARY_TEXT["dark" if is_dark else "light"]
        if self.dest_parent():
            self.resolved_dest_label.setStyleSheet(f"color: {muted}; font-size: 12px;")
        else:
            self.resolved_dest_label.setStyleSheet(
                f"color: {muted}; font-size: 12px; font-style: italic;"
            )

    def _update_resolved_dest_and_preview(self) -> None:
        has_dest = bool(self.dest_parent())
        if has_dest:
            label_text = self.target_dest()
            preview_dest = label_text
        else:
            label_text = self.tr("Choose a folder above to set destination path")
            preview_dest = f"<destination>/{self.repo_name()}"

        self.resolved_dest_label.setText(label_text)
        self._update_resolved_dest_label_style()

        clean_url = self.clone_url() or "<url>"
        args: list[str] = ["clone", "--progress"]
        fspec = self.filter_spec()
        if fspec and fspec != "none":
            args.extend(["--filter", fspec])
        if self.sparse_enabled():
            args.append("--sparse")
        args.extend(["--", clean_url, preview_dest])
        self.preview_bar.set_command(args)

    def _on_browse_dest(self) -> None:
        chosen = QFileDialog.getExistingDirectory(
            self,
            self.tr("Select Destination Folder"),
            self.dest_parent() or str(Path.home()),
        )
        if chosen:
            self.dest_parent_input.setText(chosen)

    def _show_error(self, message: str) -> None:
        self.error_label.setText(engine.redact_secrets(message))
        self.error_banner.setVisible(True)

    def _on_clone_clicked(self) -> None:
        raw_url = self.url_input.text()
        try:
            clean_url = engine.validate_clone_url(raw_url)
        except ValueError as exc:
            self._show_error(str(exc))
            return

        if not self.dest_parent():
            self._show_error(self.tr("Please select a destination folder to clone into."))
            return

        try:
            parent_resolved = Path(self.dest_parent()).resolve()
            dest_resolved = (parent_resolved / self.repo_name()).resolve()
            if dest_resolved.parent != parent_resolved:
                self._show_error(self.tr("Invalid repository destination path."))
                return
        except OSError:
            self._show_error(self.tr("Invalid repository destination path."))
            return

        self.url_input.setText(clean_url)
        self.error_banner.setVisible(False)
        self.accept()

    def _on_focus_settings_clicked(self) -> None:
        p = self.parent()
        while p is not None:
            focuser = getattr(p, "focus_active_settings_dialog", None)
            if callable(focuser):
                focuser()
                return
            p = p.parent()

    def _on_open_settings_clicked(self) -> None:
        p = self.parent()
        while p is not None:
            opener = getattr(p, "open_settings_at_category", None)
            if callable(opener):
                self._settings_open = True
                self.settings_open_banner.setVisible(True)
                try:
                    try:
                        opener("Remotes & LFS", "clone.default_filter_mode", parent_dialog=self)
                    except TypeError:
                        opener("Remotes & LFS", "clone.default_filter_mode")
                finally:
                    self._settings_open = False
                    if shiboken6.isValid(self):
                        self.settings_open_banner.setVisible(False)
                return
            p = p.parent()
