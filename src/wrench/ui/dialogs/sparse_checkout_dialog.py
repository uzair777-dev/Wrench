"""Sparse-Checkout Cone Mode Directory Manager Dialog (§6.20, FR-1.18)."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import shiboken6
from PySide6.QtCore import (
    QEvent,
    QObject,
    QRunnable,
    Qt,
    QThreadPool,
    Signal,
    Slot,
)
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from wrench.core import engine
from wrench.core.engine import SparseCheckoutState, TreeDirectoryEntry
from wrench.storage.settings_registry import SettingsRegistry, peek_settings_registry
from wrench.ui.theme import (
    PRIMARY_BUTTON_STYLES,
    SECONDARY_TEXT,
    get_banner_style,
    is_dark_theme,
)
from wrench.ui.widgets.cli_preview_bar import CliCommandPreviewBar

logger = logging.getLogger(__name__)

_ROLE_REL_PATH = Qt.ItemDataRole.UserRole
_ROLE_LOADED = Qt.ItemDataRole.UserRole + 1
_PLACEHOLDER_MARKER = "__wrench_placeholder__"


class _SparseDialogSignals(QObject):
    """Queued signal bridge from background QThreadPool tasks to SparseCheckoutDialog."""

    expand_ready = Signal(int, str, object)  # (generation_id, parent_rel_path, entries)
    expand_failed = Signal(int, str, str)  # (generation_id, parent_rel_path, err_msg)
    apply_succeeded = Signal(int, bool)  # (generation_id, disabled)
    apply_failed = Signal(int, str)  # (generation_id, err_msg)


class _TreeExpandWorker(QRunnable):
    """Loads immediate child directories for an expanded tree node on QThreadPool."""

    def __init__(
        self,
        *,
        generation_id: int,
        repo_path: Path,
        parent_rel_path: str,
        signals: _SparseDialogSignals,
    ) -> None:
        super().__init__()
        self._generation_id = generation_id
        self._repo_path = repo_path
        self._parent_rel_path = parent_rel_path
        self._signals = signals
        self.setAutoDelete(True)

    def run(self) -> None:
        try:
            entries = engine.list_tree_subdirectories(
                self._repo_path,
                parent_rel_path=self._parent_rel_path,
            )
            if shiboken6.isValid(self._signals):
                self._signals.expand_ready.emit(self._generation_id, self._parent_rel_path, entries)
        except Exception as exc:
            logger.exception(
                "Failed loading subdirectories for '%s': %s", self._parent_rel_path, exc
            )
            if shiboken6.isValid(self._signals):
                self._signals.expand_failed.emit(
                    self._generation_id,
                    self._parent_rel_path,
                    engine.redact_secrets(str(exc)),
                )


class _ApplySparseWorker(QRunnable):
    """Applies or disables cone-mode sparse-checkout directories off the GUI thread."""

    def __init__(
        self,
        *,
        generation_id: int,
        repo_path: Path,
        directories: list[str],
        disable: bool,
        signals: _SparseDialogSignals,
    ) -> None:
        super().__init__()
        self._generation_id = generation_id
        self._repo_path = repo_path
        self._directories = directories
        self._disable = disable
        self._signals = signals
        self.setAutoDelete(True)

    def run(self) -> None:
        try:
            if self._disable:
                engine.disable_sparse_checkout(self._repo_path)
            else:
                engine.set_sparse_directories(self._repo_path, self._directories, cone=True)
            if shiboken6.isValid(self._signals):
                self._signals.apply_succeeded.emit(self._generation_id, self._disable)
        except Exception as exc:
            logger.warning("Sparse-checkout operation failed: %s", exc)
            if shiboken6.isValid(self._signals):
                stderr = getattr(exc, "stderr", None) or str(exc)
                self._signals.apply_failed.emit(
                    self._generation_id,
                    engine.redact_secrets(str(stderr)),
                )


class SparseCheckoutDialog(QDialog):
    """Interactive Cone-Mode sparse-checkout manager with lazy single-level tree loading."""

    sparse_checkout_changed = Signal()
    apply_failed = Signal(str)

    def __init__(
        self,
        repo_path: Path | str,
        parent: QWidget | None = None,
        *,
        settings_registry: SettingsRegistry | None = None,
    ) -> None:
        super().__init__(parent)
        self._repo_path = Path(repo_path)
        self._registry: SettingsRegistry | None = settings_registry
        self._connected_registry: SettingsRegistry | None = None

        self._tree_generation: int = 0
        self._apply_generation: int = 0
        self._last_failed_mode: str = "apply"  # 'apply' | 'disable'
        self._is_busy: bool = False
        self._is_unborn: bool = False
        self._populating_tree: bool = False
        self._applying_theme: bool = False
        self._pending_worker_signals: set[_SparseDialogSignals] = set()
        self._selected_dirs: set[str] = set()
        self._item_by_path: dict[str, QTreeWidgetItem] = {}
        self._state = SparseCheckoutState(
            enabled=False,
            cone_mode=True,
            directories=(),
            partial_filter=None,
        )

        self.setWindowTitle(self.tr("Sparse-Checkout (Cone Mode)"))
        self.setMinimumSize(580, 500)
        self.resize(640, 560)

        self._init_ui()
        self._apply_theme()
        self._ensure_registry_connection()
        self._load_initial_state()
        self.destroyed.connect(self._disconnect_registry)

    def _init_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(10)

        # Header row
        header = QHBoxLayout()
        header.setSpacing(8)

        self.title_label = QLabel(self.tr("Sparse-Checkout (Cone Mode)"), self)
        self.title_label.setStyleSheet("font-size: 15px; font-weight: bold;")
        header.addWidget(self.title_label)

        self.status_pill = QLabel(self.tr("Disabled"), self)
        header.addWidget(self.status_pill)
        header.addStretch()

        self.disable_btn = QPushButton(self.tr("Disable Sparse-Checkout"), self)
        self.disable_btn.clicked.connect(self._on_disable_clicked)
        header.addWidget(self.disable_btn)

        self.settings_btn = QToolButton(self)
        self.settings_btn.setText("⚙")
        self.settings_btn.setToolTip(self.tr("Open Sparse-Checkout Preferences"))
        self.settings_btn.clicked.connect(self._on_open_settings_clicked)
        header.addWidget(self.settings_btn)

        root.addLayout(header)

        # Inline non-modal error banner (lock contention / command failure)
        self.error_banner = QFrame(self)
        self.error_banner.setFrameShape(QFrame.Shape.StyledPanel)
        self.error_banner.setVisible(False)
        err_layout = QHBoxLayout(self.error_banner)
        err_layout.setContentsMargins(8, 6, 8, 6)
        err_layout.setSpacing(8)

        self.error_label = QLabel(self.error_banner)
        self.error_label.setWordWrap(True)
        err_layout.addWidget(self.error_label, 1)

        self.retry_btn = QPushButton(self.tr("Retry"), self.error_banner)
        self.retry_btn.setVisible(False)
        self.retry_btn.clicked.connect(self._on_retry_clicked)
        err_layout.addWidget(self.retry_btn)

        root.addWidget(self.error_banner)

        # Inline unborn-HEAD warning banner
        self.unborn_banner = QFrame(self)
        self.unborn_banner.setFrameShape(QFrame.Shape.StyledPanel)
        self.unborn_banner.setVisible(False)
        unborn_layout = QHBoxLayout(self.unborn_banner)
        unborn_layout.setContentsMargins(8, 6, 8, 6)
        self.unborn_label = QLabel(
            self.tr(
                "Repository has an unborn HEAD (no commits yet). "
                "Create a commit before configuring sparse-checkout directories."
            ),
            self.unborn_banner,
        )
        self.unborn_label.setWordWrap(True)
        unborn_layout.addWidget(self.unborn_label)
        root.addWidget(self.unborn_banner)

        # Search filter box
        self.filter_edit = QLineEdit(self)
        self.filter_edit.setPlaceholderText(self.tr("Filter directories…"))
        self.filter_edit.setClearButtonEnabled(True)
        self.filter_edit.textChanged.connect(self._on_filter_text_changed)
        root.addWidget(self.filter_edit)

        # Directory tree (depth-1 populated initially; uniform row heights for virtual scroll)
        self.dir_tree = QTreeWidget(self)
        self.dir_tree.setHeaderLabels([self.tr("Directory")])
        self.dir_tree.setUniformRowHeights(True)
        self.dir_tree.setRootIsDecorated(True)
        self.dir_tree.itemExpanded.connect(self._on_item_expanded)
        self.dir_tree.itemChanged.connect(self._on_item_changed)
        root.addWidget(self.dir_tree, 1)

        # Summary label
        self.selection_summary_label = QLabel("", self)
        root.addWidget(self.selection_summary_label)

        # Equivalent CLI Preview Footer
        self.preview_bar = CliCommandPreviewBar(
            self,
            settings_registry=self._registry,
            repo_path=self._repo_path,
        )
        root.addWidget(self.preview_bar)

        # Footer controls
        footer = QHBoxLayout()
        footer.setSpacing(8)

        self.busy_label = QLabel("", self)
        footer.addWidget(self.busy_label, 1)

        self.cancel_btn = QPushButton(self.tr("Cancel"), self)
        self.cancel_btn.clicked.connect(self.reject)
        footer.addWidget(self.cancel_btn)

        self.apply_btn = QPushButton(self.tr("Apply Directories"), self)
        self.apply_btn.clicked.connect(self._on_apply_clicked)
        footer.addWidget(self.apply_btn)

        root.addLayout(footer)

    def _apply_theme(self) -> None:
        if self._applying_theme:
            return
        self._applying_theme = True
        try:
            is_dark = is_dark_theme(self)
            err_style = get_banner_style("error", is_dark)
            self.error_banner.setStyleSheet(
                f"QFrame {{ background-color: {err_style['bg']}; "
                f"border: 1px solid {err_style['border']}; border-radius: 4px; }}"
            )
            self.error_label.setStyleSheet(
                f"color: {err_style['fg']}; font-weight: bold; "
                "border: none; background: transparent;"
            )

            warn_style = get_banner_style("warning", is_dark)
            self.unborn_banner.setStyleSheet(
                f"QFrame {{ background-color: {warn_style['bg']}; "
                f"border: 1px solid {warn_style['border']}; border-radius: 4px; }}"
            )
            self.unborn_label.setStyleSheet(
                f"color: {warn_style['fg']}; font-weight: bold; "
                "border: none; background: transparent;"
            )

            muted = SECONDARY_TEXT["dark" if is_dark else "light"]
            self.selection_summary_label.setStyleSheet(f"color: {muted}; font-size: 12px;")
            self.busy_label.setStyleSheet(f"color: {muted}; font-size: 12px;")

            if not is_dark:
                self.apply_btn.setStyleSheet(PRIMARY_BUTTON_STYLES["light"])
            else:
                self.apply_btn.setStyleSheet("")

            self._refresh_status_pill()
        finally:
            self._applying_theme = False

    def _refresh_status_pill(self) -> None:
        is_dark = is_dark_theme(self)
        if self._state.enabled:
            style = get_banner_style("success", is_dark)
            n = len(self._state.directories)
            text = self.tr(f"Active: {n} dir{'s' if n != 1 else ''}")
            if self._state.partial_filter:
                text += f" ({self._state.partial_filter})"
        else:
            style = get_banner_style("info", is_dark)
            text = self.tr("Disabled")
        self.status_pill.setText(text)
        self.status_pill.setStyleSheet(
            f"background-color: {style['bg']}; color: {style['fg']}; "
            f"border: 1px solid {style['border']}; border-radius: 10px; "
            f"padding: 2px 8px; font-size: 11px; font-weight: bold;"
        )

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() in (
            QEvent.Type.PaletteChange,
            QEvent.Type.ApplicationPaletteChange,
            QEvent.Type.ThemeChange,
        ):
            self._apply_theme()

    def closeEvent(self, event) -> None:
        self._disconnect_registry()
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

    @Slot(str, object, object)
    def _on_setting_changed(self, key: str, _value: Any, _repo_path: Any) -> None:
        if not shiboken6.isValid(self):
            return
        if key == "monorepo.sparse_checkout_ui.enabled":
            reg = self._registry or peek_settings_registry()
            if reg is not None and not reg.is_enabled(key, str(self._repo_path)):
                self.reject()

    def _load_initial_state(self) -> None:
        self._tree_generation += 1
        try:
            self._state = engine.get_sparse_checkout_state(self._repo_path)
            self._is_unborn = engine.is_unborn_repo(self._repo_path)
        except Exception as exc:
            logger.exception("Failed inspecting repository sparse state: %s", exc)
            self._show_error(engine.redact_secrets(str(exc)), retryable=False)
            self._is_unborn = True

        self._selected_dirs = set(self._state.directories)
        self._refresh_status_pill()
        self.disable_btn.setEnabled(self._state.enabled and not self._is_unborn)
        self.unborn_banner.setVisible(self._is_unborn)
        self.apply_btn.setEnabled(not self._is_unborn)
        self.dir_tree.setEnabled(not self._is_unborn)

        self.dir_tree.clear()
        self._item_by_path.clear()
        if not self._is_unborn:
            try:
                root_entries = engine.list_tree_subdirectories(self._repo_path, parent_rel_path="")
                self._populate_children(parent_item=None, entries=root_entries)
            except Exception as exc:
                logger.exception("Failed listing root directories: %s", exc)
                self._show_error(engine.redact_secrets(str(exc)), retryable=False)

        self._update_summary_and_preview()

    def _populate_children(
        self,
        *,
        parent_item: QTreeWidgetItem | None,
        entries: list[TreeDirectoryEntry],
    ) -> None:
        self._populating_tree = True
        try:
            for entry in entries:
                item = QTreeWidgetItem(parent_item or self.dir_tree)
                item.setText(0, entry.name)
                item.setData(0, _ROLE_REL_PATH, entry.rel_path)
                item.setData(0, _ROLE_LOADED, not entry.has_children)
                item.setFlags(
                    item.flags()
                    | Qt.ItemFlag.ItemIsUserCheckable
                    | Qt.ItemFlag.ItemIsEnabled
                    | Qt.ItemFlag.ItemIsSelectable
                )
                is_checked = entry.is_selected or (entry.rel_path in self._selected_dirs)
                item.setCheckState(
                    0,
                    Qt.CheckState.Checked if is_checked else Qt.CheckState.Unchecked,
                )
                if entry.has_children:
                    placeholder = QTreeWidgetItem(item)
                    placeholder.setText(0, self.tr("Loading…"))
                    placeholder.setData(0, _ROLE_REL_PATH, _PLACEHOLDER_MARKER)
                    placeholder.setFlags(Qt.ItemFlag.NoItemFlags)
                self._item_by_path[entry.rel_path] = item
        finally:
            self._populating_tree = False

        # Re-apply active search filter if user typed one
        if self.filter_edit.text().strip():
            self._on_filter_text_changed(self.filter_edit.text())

    def _on_item_expanded(self, item: QTreeWidgetItem) -> None:
        if self._populating_tree or self._is_unborn:
            return
        rel_path = item.data(0, _ROLE_REL_PATH)
        loaded = bool(item.data(0, _ROLE_LOADED))
        if not rel_path or rel_path == _PLACEHOLDER_MARKER or loaded:
            return

        item.setData(0, _ROLE_LOADED, True)
        gen_id = self._tree_generation

        signals = _SparseDialogSignals(None)
        self._pending_worker_signals.add(signals)
        signals.expand_ready.connect(self._on_expand_ready, Qt.ConnectionType.QueuedConnection)
        signals.expand_failed.connect(self._on_expand_failed, Qt.ConnectionType.QueuedConnection)

        worker = _TreeExpandWorker(
            generation_id=gen_id,
            repo_path=self._repo_path,
            parent_rel_path=str(rel_path),
            signals=signals,
        )
        QThreadPool.globalInstance().start(worker)

    @Slot(int, str, object)
    def _on_expand_ready(
        self,
        generation_id: int,
        parent_rel_path: str,
        entries: list[TreeDirectoryEntry],
    ) -> None:
        sender_obj = self.sender()
        if isinstance(sender_obj, _SparseDialogSignals):
            self._pending_worker_signals.discard(sender_obj)
        if not shiboken6.isValid(self) or generation_id != self._tree_generation:
            return
        parent_item = self._item_by_path.get(parent_rel_path)
        if parent_item is None:
            return
        # Remove loading placeholder children cleanly
        while parent_item.childCount() > 0:
            child = parent_item.child(0)
            if child is not None:
                c_path = child.data(0, _ROLE_REL_PATH)
                if isinstance(c_path, str) and c_path != _PLACEHOLDER_MARKER:
                    self._item_by_path.pop(c_path, None)
            parent_item.takeChild(0)

        self._populate_children(parent_item=parent_item, entries=entries)
        self._update_summary_and_preview()

    @Slot(int, str, str)
    def _on_expand_failed(
        self,
        generation_id: int,
        parent_rel_path: str,
        err_msg: str,
    ) -> None:
        sender_obj = self.sender()
        if isinstance(sender_obj, _SparseDialogSignals):
            self._pending_worker_signals.discard(sender_obj)
        if not shiboken6.isValid(self) or generation_id != self._tree_generation:
            return
        parent_item = self._item_by_path.get(parent_rel_path)
        if parent_item is not None:
            parent_item.setData(0, _ROLE_LOADED, False)
        self._show_error(err_msg, retryable=False)

    def _on_item_changed(self, item: QTreeWidgetItem, column: int) -> None:
        if self._populating_tree or column != 0:
            return
        rel_path = item.data(0, _ROLE_REL_PATH)
        if not rel_path or rel_path == _PLACEHOLDER_MARKER:
            return
        if item.checkState(0) == Qt.CheckState.Checked:
            self._selected_dirs.add(str(rel_path))
        else:
            self._selected_dirs.discard(str(rel_path))
        self._update_summary_and_preview()

    def _on_filter_text_changed(self, text: str) -> None:
        query = text.strip().lower()

        def _apply_filter(item: QTreeWidgetItem) -> bool:
            rel_path = str(item.data(0, _ROLE_REL_PATH) or "")
            if rel_path == _PLACEHOLDER_MARKER:
                return False
            self_match = not query or query in rel_path.lower() or query in item.text(0).lower()
            child_match = False
            for idx in range(item.childCount()):
                child = item.child(idx)
                if child is not None and _apply_filter(child):
                    child_match = True
            visible = self_match or child_match
            item.setHidden(not visible)
            return visible

        for i in range(self.dir_tree.topLevelItemCount()):
            top_item = self.dir_tree.topLevelItem(i)
            if top_item is not None:
                _apply_filter(top_item)

    def selected_directories(self) -> list[str]:
        """Return deterministically sorted repository-relative directories currently checked."""
        return sorted(self._selected_dirs)

    def _update_summary_and_preview(self) -> None:
        dirs = self.selected_directories()
        count = len(dirs)
        self.selection_summary_label.setText(
            self.tr(
                f"Selected: {count} director{'ies' if count != 1 else 'y'} "
                "(cone mode keeps top-level files checked out)"
            )
        )
        args = ["sparse-checkout", "set", "--cone", "--", *dirs]
        self.preview_bar.set_command(args)

    def _set_busy(self, busy: bool, text: str = "") -> None:
        self._is_busy = busy
        self.busy_label.setText(text if busy else "")
        self.apply_btn.setEnabled(not busy and not self._is_unborn)
        self.disable_btn.setEnabled(not busy and self._state.enabled and not self._is_unborn)
        self.dir_tree.setEnabled(not busy and not self._is_unborn)
        self.cancel_btn.setEnabled(not busy)

    def _show_error(self, message: str, *, retryable: bool) -> None:
        clean = engine.redact_secrets(message.strip())
        self.error_label.setText(clean)
        self.retry_btn.setVisible(retryable)
        self.error_banner.setVisible(True)

    def _hide_error(self) -> None:
        self.error_banner.setVisible(False)
        self.retry_btn.setVisible(False)

    def _on_apply_clicked(self) -> None:
        if self._is_busy or self._is_unborn:
            return
        self._last_failed_mode = "apply"
        self._hide_error()
        dirs = self.selected_directories()
        self._start_apply_worker(directories=dirs, disable=False)

    def _on_disable_clicked(self) -> None:
        if self._is_busy or self._is_unborn:
            return
        self._last_failed_mode = "disable"
        self._hide_error()
        self.preview_bar.set_command(["sparse-checkout", "disable"])
        self._start_apply_worker(directories=[], disable=True)

    def _on_retry_clicked(self) -> None:
        if self._last_failed_mode == "disable":
            self._on_disable_clicked()
        else:
            self._on_apply_clicked()

    def _start_apply_worker(self, *, directories: list[str], disable: bool) -> None:
        self._apply_generation += 1
        gen_id = self._apply_generation
        self._set_busy(
            True,
            (
                self.tr("Disabling sparse-checkout…")
                if disable
                else self.tr("Updating sparse-checkout working tree…")
            ),
        )

        signals = _SparseDialogSignals(None)
        self._pending_worker_signals.add(signals)
        signals.apply_succeeded.connect(
            self._on_apply_succeeded,
            Qt.ConnectionType.QueuedConnection,
        )
        signals.apply_failed.connect(self._on_apply_failed, Qt.ConnectionType.QueuedConnection)

        worker = _ApplySparseWorker(
            generation_id=gen_id,
            repo_path=self._repo_path,
            directories=directories,
            disable=disable,
            signals=signals,
        )
        QThreadPool.globalInstance().start(worker)

    @Slot(int, bool)
    def _on_apply_succeeded(self, generation_id: int, _disabled: bool) -> None:
        sender_obj = self.sender()
        if isinstance(sender_obj, _SparseDialogSignals):
            self._pending_worker_signals.discard(sender_obj)
        if not shiboken6.isValid(self) or generation_id != self._apply_generation:
            return
        self._set_busy(False)
        self.sparse_checkout_changed.emit()
        self.accept()

    @Slot(int, str)
    def _on_apply_failed(self, generation_id: int, err_msg: str) -> None:
        sender_obj = self.sender()
        if isinstance(sender_obj, _SparseDialogSignals):
            self._pending_worker_signals.discard(sender_obj)
        if not shiboken6.isValid(self) or generation_id != self._apply_generation:
            return
        self._set_busy(False)
        self._update_summary_and_preview()

        lower = err_msg.lower()
        is_locked = ".lock" in lower or "file exists" in lower or "another git process" in lower
        if is_locked:
            lock_hint = self.tr(
                "Repository index or config is locked by another Git process "
                "(.git/index.lock). Wait for it to finish or remove the stale lock, "
                "then click Retry."
            )
            display_msg = f"{lock_hint}\n{err_msg}"
        else:
            display_msg = err_msg

        self._show_error(display_msg, retryable=is_locked)
        self.apply_failed.emit(display_msg)

    def _on_open_settings_clicked(self) -> None:
        p = self.parent()
        while p is not None:
            opener = getattr(p, "open_settings_at_category", None)
            if callable(opener):
                opener("Worktrees & Submodules", "monorepo.sparse_checkout_ui.enabled")
                return
            p = p.parent()
