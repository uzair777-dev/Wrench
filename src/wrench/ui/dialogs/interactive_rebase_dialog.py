"""Visual Interactive Rebase & Drag-to-Reorder Dialog (ui-planning.md §6.16, VP-2, FR-3.5)."""

from __future__ import annotations

import logging
import weakref
from dataclasses import replace
from pathlib import Path
from typing import Any

import shiboken6
from PySide6.QtCore import (
    QCoreApplication,
    QEvent,
    QObject,
    QRunnable,
    Qt,
    QThreadPool,
    Signal,
    Slot,
)
from PySide6.QtGui import QColor, QDropEvent, QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from wrench.core import engine
from wrench.core.engine import (
    RebaseResult,
    RebaseTodoEntry,
    RepoHandle,
)
from wrench.storage.settings_registry import SettingsRegistry, peek_settings_registry
from wrench.ui.theme import (
    PRIMARY_BUTTON_STYLES,
    REBASE_ACTION_COLORS,
    SECONDARY_TEXT,
    TREE_WIDGET_STYLES,
    get_banner_style,
    get_icon_button_style,
    get_secondary_button_style,
    is_dark_theme,
    repolish_widget,
)
from wrench.ui.widgets.cli_preview_bar import CliCommandPreviewBar

logger = logging.getLogger(__name__)

_REBASE_ACTIONS: tuple[str, ...] = ("pick", "reword", "edit", "squash", "fixup", "drop")


class _RebaseDialogDispatcher(QObject):
    """Application-lifetime queued dispatcher routing interactive rebase worker callbacks."""

    commits_ready = Signal(object, int, object, bool, str, str, bool)
    commits_failed = Signal(object, int, str)
    rebase_succeeded = Signal(object, int, object)
    rebase_failed = Signal(object, int, str, bool)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.commits_ready.connect(self._deliver_commits_ready, Qt.ConnectionType.QueuedConnection)
        self.commits_failed.connect(
            self._deliver_commits_failed, Qt.ConnectionType.QueuedConnection
        )
        self.rebase_succeeded.connect(
            self._deliver_rebase_succeeded, Qt.ConnectionType.QueuedConnection
        )
        self.rebase_failed.connect(self._deliver_rebase_failed, Qt.ConnectionType.QueuedConnection)

    @Slot(object, int, object, bool, str, str, bool)
    def _deliver_commits_ready(
        self,
        dlg_ref: Any,
        generation_id: int,
        entries: Any,
        is_truncated: bool,
        head_label: str,
        base_label: str,
        is_detached: bool,
    ) -> None:
        dlg = dlg_ref() if callable(dlg_ref) else None
        if dlg is not None and shiboken6.isValid(dlg):
            dlg._on_commits_ready(
                generation_id,
                entries,
                is_truncated,
                head_label,
                base_label,
                is_detached,
            )

    @Slot(object, int, str)
    def _deliver_commits_failed(self, dlg_ref: Any, generation_id: int, err_msg: str) -> None:
        dlg = dlg_ref() if callable(dlg_ref) else None
        if dlg is not None and shiboken6.isValid(dlg):
            dlg._on_commits_failed(generation_id, err_msg)

    @Slot(object, int, object)
    def _deliver_rebase_succeeded(
        self,
        dlg_ref: Any,
        generation_id: int,
        result: Any,
    ) -> None:
        dlg = dlg_ref() if callable(dlg_ref) else None
        if dlg is not None and shiboken6.isValid(dlg):
            dlg._on_rebase_succeeded(generation_id, result)

    @Slot(object, int, str, bool)
    def _deliver_rebase_failed(
        self,
        dlg_ref: Any,
        generation_id: int,
        err_msg: str,
        retryable: bool,
    ) -> None:
        dlg = dlg_ref() if callable(dlg_ref) else None
        if dlg is not None and shiboken6.isValid(dlg):
            dlg._on_rebase_failed(generation_id, err_msg, retryable)


_rebase_dialog_dispatcher: _RebaseDialogDispatcher | None = None


def _get_rebase_dispatcher() -> _RebaseDialogDispatcher:
    global _rebase_dialog_dispatcher
    if _rebase_dialog_dispatcher is None or not shiboken6.isValid(_rebase_dialog_dispatcher):
        _rebase_dialog_dispatcher = _RebaseDialogDispatcher(parent=QCoreApplication.instance())
    return _rebase_dialog_dispatcher


class _LoadCommitsWorker(QRunnable):
    """Loads `base_oid..HEAD` commit entries on QThreadPool without subprocesses."""

    def __init__(
        self,
        *,
        generation_id: int,
        repo_path: Path,
        base_oid: str,
        dialog_ref: weakref.ref[InteractiveRebaseDialog],
        dispatcher: _RebaseDialogDispatcher,
    ) -> None:
        super().__init__()
        self._generation_id = generation_id
        self._repo_path = repo_path
        self._base_oid = base_oid
        self._dialog_ref = dialog_ref
        self._dispatcher = dispatcher
        self.setAutoDelete(True)

    def run(self) -> None:
        if self._dialog_ref() is None:
            return
        try:
            entries, is_truncated = engine.list_commits_for_interactive_rebase_checked(
                self._repo_path,
                self._base_oid,
            )
            head_label, base_label, is_detached = engine.get_interactive_rebase_target_label(
                self._repo_path,
                self._base_oid,
            )
            if self._dialog_ref() is not None and shiboken6.isValid(self._dispatcher):
                self._dispatcher.commits_ready.emit(
                    self._dialog_ref,
                    self._generation_id,
                    entries,
                    is_truncated,
                    head_label,
                    base_label,
                    is_detached,
                )
        except Exception as exc:
            logger.exception("Failed loading commits for interactive rebase: %s", exc)
            if self._dialog_ref() is not None and shiboken6.isValid(self._dispatcher):
                self._dispatcher.commits_failed.emit(
                    self._dialog_ref,
                    self._generation_id,
                    engine.redact_secrets(str(exc)),
                )


class _RunInteractiveRebaseWorker(QRunnable):
    """Runs `engine.interactive_rebase` off the GUI thread when user clicks Start Rebase."""

    def __init__(
        self,
        *,
        generation_id: int,
        repo_path: Path,
        base_oid: str,
        entries: list[RebaseTodoEntry],
        autostash: bool,
        autosquash: bool,
        dialog_ref: weakref.ref[InteractiveRebaseDialog],
        dispatcher: _RebaseDialogDispatcher,
    ) -> None:
        super().__init__()
        self._generation_id = generation_id
        self._repo_path = repo_path
        self._base_oid = base_oid
        self._entries = entries
        self._autostash = autostash
        self._autosquash = autosquash
        self._dialog_ref = dialog_ref
        self._dispatcher = dispatcher
        self.setAutoDelete(True)

    def run(self) -> None:
        if self._dialog_ref() is None:
            return
        try:
            worker_repo = engine.open_repo(self._repo_path, configure_credentials=False)
            res = engine.interactive_rebase(
                worker_repo,
                self._base_oid,
                self._entries,
                autostash=self._autostash,
                autosquash=self._autosquash,
                conn=None,
            )
            if self._dialog_ref() is not None and shiboken6.isValid(self._dispatcher):
                self._dispatcher.rebase_succeeded.emit(
                    self._dialog_ref,
                    self._generation_id,
                    res,
                )
        except Exception as exc:
            logger.warning("Interactive rebase failed: %s", exc)
            if self._dialog_ref() is not None and shiboken6.isValid(self._dispatcher):
                stderr = getattr(exc, "stderr", None) or str(exc)
                msg = engine.redact_secrets(str(stderr))
                lower = msg.lower()
                is_locked = (
                    ".lock" in lower
                    or "index.lock" in lower
                    or "another git process" in lower
                )
                self._dispatcher.rebase_failed.emit(
                    self._dialog_ref,
                    self._generation_id,
                    msg,
                    is_locked,
                )


class _RebaseTodoTableWidget(QTableWidget):
    """QTableWidget supporting deterministic internal row drag-and-drop reordering."""

    row_move_requested = Signal(int, int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(0, 5, parent)
        self.setHorizontalHeaderLabels(
            [self.tr("≡"), self.tr("Action"), self.tr("SHA"), self.tr("Summary"), self.tr("Author")]
        )
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropOverwriteMode(False)
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setAlternatingRowColors(True)
        self.verticalHeader().setVisible(False)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)

        header = self.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        header.resizeSection(0, 32)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        header.resizeSection(1, 118)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        header.resizeSection(2, 86)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)

    def dropEvent(self, event: QDropEvent) -> None:
        selected_rows = self.selectionModel().selectedRows()
        source_row = selected_rows[0].row() if selected_rows else self.currentRow()
        if source_row < 0 or self.rowCount() <= 1:
            event.ignore()
            return

        drop_point = event.position().toPoint()
        target_index = self.indexAt(drop_point)
        if target_index.isValid():
            dest_row = target_index.row()
            if self.dropIndicatorPosition() == QAbstractItemView.DropIndicatorPosition.BelowItem:
                dest_row += 1
            if source_row < dest_row:
                dest_row -= 1
        else:
            dest_row = self.rowCount() - 1

        dest_row = max(0, min(dest_row, self.rowCount() - 1))
        event.setDropAction(Qt.DropAction.MoveAction)
        event.accept()
        if dest_row != source_row:
            self.row_move_requested.emit(source_row, dest_row)


class InteractiveRebaseDialog(QDialog):
    """Graphical Interactive Rebase dialog with drag-to-reorder and inline message editor."""

    rebase_started = Signal()
    rebase_completed = Signal(object)  # RebaseResult
    rebase_failed = Signal(str)

    def __init__(
        self,
        repo: RepoHandle | Path | str,
        base_oid: str,
        parent: QWidget | None = None,
        *,
        settings_registry: SettingsRegistry | None = None,
    ) -> None:
        super().__init__(parent)
        self._repo: RepoHandle = (
            repo if isinstance(repo, RepoHandle) else engine.open_repo(repo)
        )
        self._repo_path: Path = Path(self._repo.path)
        self._base_oid: str = base_oid
        self._registry: SettingsRegistry | None = settings_registry
        self._connected_registry: SettingsRegistry | None = None

        self._entries: list[RebaseTodoEntry] = []
        self._is_truncated: bool = False
        self._head_label: str = "HEAD"
        self._base_label: str = base_oid[:7]
        self._is_detached: bool = False
        self._is_loading: bool = True
        self._is_busy: bool = False
        self._applying_theme: bool = False
        self._syncing_editor: bool = False
        self._settings_open: bool = False
        self._pending_close_on_disable: bool = False
        self._load_generation: int = 0
        self._run_generation: int = 0
        self._active_editor_oid: str | None = None
        self._invalid_rows: list[int] = []
        self.last_result: RebaseResult | None = None

        self.setWindowTitle(self.tr("Interactive Rebase"))
        self.setMinimumSize(680, 520)
        self.resize(780, 580)

        self._init_ui()
        self._load_checkbox_defaults()
        self._apply_theme()
        self._ensure_registry_connection()
        self._update_cli_preview()
        self._start_load_commits()

    def _init_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(10)

        # Header summary & options bar
        header = QHBoxLayout()
        header.setSpacing(10)

        self.summary_label = QLabel(
            self.tr(f"Loading commits onto {self._base_oid[:7]}…"),
            self,
        )
        self.summary_label.setStyleSheet("font-size: 13px; font-weight: bold;")
        header.addWidget(self.summary_label, 1)

        self.autostash_cb = QCheckBox(self.tr("Autostash (--autostash)"), self)
        self.autostash_cb.toggled.connect(self._update_cli_preview)
        header.addWidget(self.autostash_cb)

        self.autosquash_cb = QCheckBox(self.tr("Autosquash (--autosquash)"), self)
        self.autosquash_cb.toggled.connect(self._update_cli_preview)
        header.addWidget(self.autosquash_cb)

        self.settings_btn = QToolButton(self)
        self.settings_btn.setText("⚙")
        self.settings_btn.setToolTip(self.tr("Open Interactive Rebase Preferences"))
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

        # Inline validation / lock error banner
        self.validation_banner = QFrame(self)
        self.validation_banner.setFrameShape(QFrame.Shape.StyledPanel)
        self.validation_banner.setVisible(False)
        val_layout = QHBoxLayout(self.validation_banner)
        val_layout.setContentsMargins(8, 6, 8, 6)
        val_layout.setSpacing(8)
        self.validation_label = QLabel("", self.validation_banner)
        self.validation_label.setWordWrap(True)
        val_layout.addWidget(self.validation_label, 1)
        self.retry_btn = QPushButton(self.tr("Retry"), self.validation_banner)
        self.retry_btn.setVisible(False)
        self.retry_btn.clicked.connect(self._on_start_clicked)
        val_layout.addWidget(self.retry_btn)
        root.addWidget(self.validation_banner)

        # Todo table
        self.todo_table = _RebaseTodoTableWidget(self)
        self.todo_table.row_move_requested.connect(self.move_row)
        self.todo_table.itemSelectionChanged.connect(self._on_selection_changed)
        root.addWidget(self.todo_table, 1)

        # Inline commit message editor for reword / squash
        self.message_editor_container = QFrame(self)
        self.message_editor_container.setFrameShape(QFrame.Shape.StyledPanel)
        self.message_editor_container.setVisible(False)
        editor_layout = QVBoxLayout(self.message_editor_container)
        editor_layout.setContentsMargins(8, 8, 8, 8)
        editor_layout.setSpacing(6)

        self.message_editor_header = QLabel(
            self.tr("Commit message:"), self.message_editor_container
        )
        self.message_editor_header.setStyleSheet("font-weight: bold;")
        editor_layout.addWidget(self.message_editor_header)

        self.message_edit = QPlainTextEdit(self.message_editor_container)
        self.message_edit.setPlaceholderText(
            self.tr(
                "Enter commit message override (leave empty on squash to keep combined message)"
            )
        )
        self.message_edit.setMaximumHeight(110)
        self.message_edit.textChanged.connect(self._on_message_text_changed)
        editor_layout.addWidget(self.message_edit)
        root.addWidget(self.message_editor_container)

        # Live CLI Preview Bar (§5.3)
        self.preview_bar = CliCommandPreviewBar(
            self,
            settings_registry=self._effective_registry(),
            repo_path=self._repo_path,
        )
        root.addWidget(self.preview_bar)

        # Footer controls
        footer = QHBoxLayout()
        footer.setSpacing(8)

        self.status_label = QLabel(self.tr("Loading commits…"), self)
        footer.addWidget(self.status_label, 1)

        self.move_up_btn = QPushButton(self.tr("↑ Move Up"), self)
        self.move_up_btn.clicked.connect(self._on_move_up_clicked)
        footer.addWidget(self.move_up_btn)

        self.move_down_btn = QPushButton(self.tr("↓ Move Down"), self)
        self.move_down_btn.clicked.connect(self._on_move_down_clicked)
        footer.addWidget(self.move_down_btn)

        self.cancel_btn = QPushButton(self.tr("Cancel"), self)
        self.cancel_btn.clicked.connect(self.reject)
        footer.addWidget(self.cancel_btn)

        self.start_btn = QPushButton(self.tr("Start Rebase"), self)
        self.start_btn.setEnabled(False)
        self.start_btn.clicked.connect(self._on_start_clicked)
        footer.addWidget(self.start_btn)

        root.addLayout(footer)

    def _effective_registry(self) -> SettingsRegistry | None:
        return self._registry or peek_settings_registry()

    def _load_checkbox_defaults(self) -> None:
        reg = self._effective_registry()
        repo_str = str(self._repo_path)
        autostash = reg.get_bool("rebase.autostash", repo_str) if reg is not None else True
        autosquash = reg.get_bool("rebase.autosquash", repo_str) if reg is not None else True
        self.autostash_cb.setChecked(autostash)
        self.autosquash_cb.setChecked(autosquash)

    def _apply_theme(self) -> None:
        if self._applying_theme:
            return
        self._applying_theme = True
        try:
            dark = is_dark_theme(self)
            mode = "dark" if dark else "light"
            t = TREE_WIDGET_STYLES[mode]
            self.todo_table.setStyleSheet(
                f"QTableWidget {{ background-color: {t['bg']}; "
                f"alternate-background-color: {t['alt_bg']}; "
                f"color: {t['fg']}; border: 1px solid {t['border']}; border-radius: 4px; "
                f"gridline-color: {t['border']}; }} "
                f"QTableWidget::item:selected {{ background-color: {t['selected_bg']}; "
                f"color: {t['selected_fg']}; }} "
                f"QHeaderView::section {{ background-color: {t['header_bg']}; "
                f"color: {t['header_fg']}; "
                f"border: none; border-bottom: 1px solid {t['border']}; padding: 4px 6px; }}"
            )
            self.status_label.setStyleSheet(f"color: {SECONDARY_TEXT[mode]};")
            self.settings_btn.setStyleSheet(get_icon_button_style(dark))
            self.move_up_btn.setStyleSheet(get_secondary_button_style(dark, compact=True))
            self.move_down_btn.setStyleSheet(get_secondary_button_style(dark, compact=True))
            self.cancel_btn.setStyleSheet(get_secondary_button_style(dark))
            self.start_btn.setStyleSheet(PRIMARY_BUTTON_STYLES[mode])

            info_style = get_banner_style("info", dark)
            self.settings_open_banner.setStyleSheet(
                f"QFrame {{ background-color: {info_style['bg']}; "
                f"border: 1px solid {info_style['border']}; border-radius: 4px; }}"
            )
            self.settings_open_label.setStyleSheet(
                f"color: {info_style['fg']}; border: none; background: transparent;"
            )
            self.focus_settings_btn.setStyleSheet(get_secondary_button_style(dark, compact=True))

            err_style = get_banner_style("error", dark)
            self.validation_banner.setStyleSheet(
                f"QFrame {{ background-color: {err_style['bg']}; "
                f"border: 1px solid {err_style['border']}; border-radius: 4px; }}"
            )
            self.validation_label.setStyleSheet(
                f"color: {err_style['fg']}; border: none; background: transparent;"
            )
            self.retry_btn.setStyleSheet(get_secondary_button_style(dark, compact=True))

            self.message_editor_container.setStyleSheet(
                f"QFrame {{ background-color: {t['header_bg']}; "
                f"border: 1px solid {t['border']}; border-radius: 4px; }}"
            )
            self._style_all_action_combos()
            if hasattr(self, "preview_bar") and shiboken6.isValid(self.preview_bar):
                self.preview_bar._apply_theme()
            for row in list(getattr(self, "_invalid_rows", [])):
                if 0 <= row < self.todo_table.rowCount():
                    self._highlight_invalid_row(row)
            widgets_to_repolish: list[QWidget | None] = [
                self,
                getattr(self, "summary_label", None),
                getattr(self, "autostash_cb", None),
                getattr(self, "autosquash_cb", None),
                getattr(self, "settings_btn", None),
                getattr(self, "settings_open_banner", None),
                getattr(self, "settings_open_label", None),
                getattr(self, "focus_settings_btn", None),
                getattr(self, "validation_banner", None),
                getattr(self, "validation_label", None),
                getattr(self, "retry_btn", None),
                getattr(self, "todo_table", None),
                self.todo_table.viewport() if hasattr(self, "todo_table") else None,
                self.todo_table.horizontalHeader() if hasattr(self, "todo_table") else None,
                getattr(self, "message_editor_container", None),
                getattr(self, "message_editor_header", None),
                getattr(self, "message_edit", None),
                self.message_edit.viewport() if hasattr(self, "message_edit") else None,
                getattr(self, "status_label", None),
                getattr(self, "move_up_btn", None),
                getattr(self, "move_down_btn", None),
                getattr(self, "cancel_btn", None),
                getattr(self, "start_btn", None),
            ]
            for w in widgets_to_repolish:
                repolish_widget(w)
        finally:
            self._applying_theme = False

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() in (
            QEvent.Type.PaletteChange,
            QEvent.Type.ApplicationPaletteChange,
            QEvent.Type.ThemeChange,
            QEvent.Type.StyleChange,
        ):
            self._apply_theme()

    def _ensure_registry_connection(self) -> None:
        reg = self._effective_registry()
        if reg is self._connected_registry:
            return
        self._disconnect_registry()
        if reg is not None:
            reg.setting_changed.connect(
                self._on_setting_changed, Qt.ConnectionType.QueuedConnection
            )
            self._connected_registry = reg
            self.preview_bar.set_settings_registry(reg)

    def _disconnect_registry(self) -> None:
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
    def _on_setting_changed(self, key: str, _value: Any, repo_path: Any = None) -> None:
        if not shiboken6.isValid(self):
            return
        active_repo = str(self._repo_path)
        if repo_path is not None and str(repo_path) != active_repo:
            return
        if key == "rebase.interactive_ui.enabled":
            reg = self._effective_registry()
            if reg is not None and not reg.is_enabled("rebase.interactive_ui.enabled", active_repo):
                self._load_generation += 1
                self._run_generation += 1
                if self._settings_open:
                    self._pending_close_on_disable = True
                else:
                    self.reject()

    def closeEvent(self, event) -> None:
        self._load_generation += 1
        self._run_generation += 1
        self._disconnect_registry()
        if hasattr(self, "preview_bar") and shiboken6.isValid(self.preview_bar):
            self.preview_bar.close()
        super().closeEvent(event)

    def _start_load_commits(self) -> None:
        self._load_generation += 1
        self._is_loading = True
        self._update_controls_enabled()
        worker = _LoadCommitsWorker(
            generation_id=self._load_generation,
            repo_path=self._repo_path,
            base_oid=self._base_oid,
            dialog_ref=weakref.ref(self),
            dispatcher=_get_rebase_dispatcher(),
        )
        QThreadPool.globalInstance().start(worker)

    @Slot(int, object, bool, str, str, bool)
    def _on_commits_ready(
        self,
        generation_id: int,
        entries: Any,
        is_truncated: bool,
        head_label: str,
        base_label: str,
        is_detached: bool,
    ) -> None:
        if not shiboken6.isValid(self) or generation_id != self._load_generation:
            return
        self._is_loading = False
        self._entries = list(entries) if isinstance(entries, (list, tuple)) else []
        self._is_truncated = bool(is_truncated)
        self._head_label = head_label or "HEAD"
        self._base_label = base_label or self._base_oid[:7]
        self._is_detached = bool(is_detached)

        count = len(self._entries)
        head_note = f" ({self._head_label})" if self._head_label else ""
        self.summary_label.setText(
            self.tr(
                f"Rebasing {count} commit{'s' if count != 1 else ''}{head_note} "
                f"onto {self._base_label} ({self._base_oid[:7]})"
            )
        )
        self.status_label.setText(
            self.tr(
                f"Loaded {count} commit{'s' if count != 1 else ''}. Drag rows or choose actions."
            )
        )
        self._rebuild_table(selected_row=0 if self._entries else -1)
        self._validate_and_update_state()

    @Slot(int, str)
    def _on_commits_failed(self, generation_id: int, err_msg: str) -> None:
        if not shiboken6.isValid(self) or generation_id != self._load_generation:
            return
        self._is_loading = False
        self._entries = []
        self._rebuild_table(selected_row=-1)
        self.status_label.setText(self.tr("Unable to load commits."))
        self._show_banner_error(err_msg, retryable=False)
        self._update_controls_enabled()

    def _rebuild_table(self, *, selected_row: int = -1) -> None:
        self.todo_table.blockSignals(True)
        try:
            for old_row in range(self.todo_table.rowCount()):
                for old_col in range(self.todo_table.columnCount()):
                    old_widget = self.todo_table.cellWidget(old_row, old_col)
                    if old_widget is not None:
                        self.todo_table.removeCellWidget(old_row, old_col)
                        old_widget.setParent(None)
                        old_widget.deleteLater()
            self.todo_table.clearContents()
            self.todo_table.setRowCount(len(self._entries))
            mono = QFont("Monospace", 9)
            for row_idx, entry in enumerate(self._entries):
                handle_item = QTableWidgetItem("≡")
                handle_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                handle_item.setData(Qt.ItemDataRole.UserRole, entry.oid)
                self.todo_table.setItem(row_idx, 0, handle_item)

                combo = QComboBox(self.todo_table)
                combo.addItems(list(_REBASE_ACTIONS))
                idx = combo.findText(entry.action)
                combo.setCurrentIndex(idx if idx >= 0 else 0)
                combo.currentTextChanged.connect(
                    lambda new_action, oid=entry.oid: self._on_row_action_changed(oid, new_action)
                )
                self._apply_combo_style(combo, entry.action)
                self.todo_table.setCellWidget(row_idx, 1, combo)

                sha_item = QTableWidgetItem(entry.short_oid)
                sha_item.setFont(mono)
                self.todo_table.setItem(row_idx, 2, sha_item)

                summary_item = QTableWidgetItem(entry.summary)
                self.todo_table.setItem(row_idx, 3, summary_item)

                author_item = QTableWidgetItem(entry.author)
                self.todo_table.setItem(row_idx, 4, author_item)

            if 0 <= selected_row < len(self._entries):
                self.todo_table.selectRow(selected_row)
        finally:
            self.todo_table.blockSignals(False)

        self._sync_message_editor_for_selection()

    def _apply_combo_style(self, combo: QComboBox, action: str) -> None:
        mode = "dark" if is_dark_theme(self) else "light"
        t = TREE_WIDGET_STYLES[mode]
        fg = REBASE_ACTION_COLORS[mode].get(action, REBASE_ACTION_COLORS[mode]["pick"])
        bg = t["header_bg"]
        border = t["border"]
        popup_bg = t["bg"]
        popup_fg = t["fg"]
        sel_bg = t["selected_bg"]
        sel_fg = t["selected_fg"]
        combo.setStyleSheet(
            f"QComboBox {{ color: {fg}; background-color: {bg}; border: 1px solid {border}; "
            f"border-radius: 3px; padding: 1px 6px; font-weight: bold; }} "
            f"QComboBox QAbstractItemView {{ background-color: {popup_bg}; color: {popup_fg}; "
            f"selection-background-color: {sel_bg}; selection-color: {sel_fg}; "
            f"border: 1px solid {border}; }}"
        )
        repolish_widget(combo)
        if combo.view() is not None:
            repolish_widget(combo.view())

    def _style_all_action_combos(self) -> None:
        if not hasattr(self, "todo_table"):
            return
        for row in range(self.todo_table.rowCount()):
            widget = self.todo_table.cellWidget(row, 1)
            if isinstance(widget, QComboBox):
                self._apply_combo_style(widget, widget.currentText())

    def _row_for_oid(self, oid: str) -> int:
        for idx, entry in enumerate(self._entries):
            if entry.oid == oid:
                return idx
        return -1

    def _on_row_action_changed(self, oid: str, new_action: str) -> None:
        if new_action not in _REBASE_ACTIONS:
            return
        idx = self._row_for_oid(oid)
        if idx < 0:
            return
        entry = self._entries[idx]
        default_msg = entry.new_message
        if new_action == "reword" and default_msg is None:
            default_msg = entry.summary
        elif new_action not in ("reword", "squash"):
            default_msg = None
        self._entries[idx] = replace(entry, action=new_action, new_message=default_msg)

        combo = self.todo_table.cellWidget(idx, 1)
        if isinstance(combo, QComboBox):
            self._apply_combo_style(combo, new_action)

        self.todo_table.selectRow(idx)
        self._sync_message_editor_for_selection()
        self._validate_and_update_state()

    def _on_selection_changed(self) -> None:
        self._sync_message_editor_for_selection()
        self._update_controls_enabled()

    def _current_selected_row(self) -> int:
        rows = self.todo_table.selectionModel().selectedRows()
        if rows:
            return rows[0].row()
        return self.todo_table.currentRow()

    def _sync_message_editor_for_selection(self) -> None:
        row = self._current_selected_row()
        if not (0 <= row < len(self._entries)):
            self._active_editor_oid = None
            self.message_editor_container.setVisible(False)
            return

        entry = self._entries[row]
        if entry.action not in ("reword", "squash"):
            self._active_editor_oid = None
            self.message_editor_container.setVisible(False)
            return

        self._active_editor_oid = entry.oid
        self.message_editor_header.setText(
            self.tr(f"Commit message for {entry.short_oid} ({entry.action}):")
        )
        self._syncing_editor = True
        try:
            self.message_edit.setPlainText(entry.new_message or "")
        finally:
            self._syncing_editor = False
        self.message_editor_container.setVisible(True)

    def _on_message_text_changed(self) -> None:
        if self._syncing_editor or not self._active_editor_oid:
            return
        idx = self._row_for_oid(self._active_editor_oid)
        if idx < 0:
            return
        entry = self._entries[idx]
        raw = self.message_edit.toPlainText()
        if entry.action == "squash" and not raw.strip():
            updated_msg: str | None = None
        else:
            updated_msg = raw
        self._entries[idx] = replace(entry, new_message=updated_msg)
        self._validate_and_update_state()

    @Slot(int, int)
    def move_row(self, from_row: int, to_row: int) -> None:
        """Move a commit row from `from_row` to `to_row`, rebuilding cell widgets cleanly."""
        if self._is_busy or not (0 <= from_row < len(self._entries)):
            return
        dest = max(0, min(to_row, len(self._entries) - 1))
        if dest == from_row:
            return
        entry = self._entries.pop(from_row)
        self._entries.insert(dest, entry)
        self._rebuild_table(selected_row=dest)
        self._validate_and_update_state()

    def set_row_action(self, row: int, action: str) -> None:
        """Set the rebase action for `row` programmatically and refresh validation."""
        if not (0 <= row < len(self._entries)) or action not in _REBASE_ACTIONS:
            return
        combo = self.todo_table.cellWidget(row, 1)
        if isinstance(combo, QComboBox):
            combo.setCurrentText(action)
        else:
            self._on_row_action_changed(self._entries[row].oid, action)

    def planned_entries(self) -> list[RebaseTodoEntry]:
        """Return an immutable snapshot list of planned RebaseTodoEntry objects in order."""
        return list(self._entries)

    def _on_move_up_clicked(self) -> None:
        row = self._current_selected_row()
        if row > 0:
            self.move_row(row, row - 1)

    def _on_move_down_clicked(self) -> None:
        row = self._current_selected_row()
        if 0 <= row < len(self._entries) - 1:
            self.move_row(row, row + 1)

    def _clear_row_highlights(self) -> None:
        self._invalid_rows = []
        for r in range(self.todo_table.rowCount()):
            for c in (0, 2, 3, 4):
                item = self.todo_table.item(r, c)
                if item is not None:
                    item.setData(Qt.ItemDataRole.BackgroundRole, None)

    def _highlight_invalid_row(self, row: int) -> None:
        if row not in self._invalid_rows:
            self._invalid_rows.append(row)
        mode = "dark" if is_dark_theme(self) else "light"
        tint = QColor(get_banner_style("error", mode == "dark")["bg"])
        for c in (0, 2, 3, 4):
            item = self.todo_table.item(row, c)
            if item is not None:
                item.setBackground(tint)

    def _show_banner_error(self, message: str, *, retryable: bool) -> None:
        self.validation_label.setText(engine.redact_secrets(message))
        self.retry_btn.setVisible(retryable)
        self.validation_banner.setVisible(True)

    def _hide_banner_error(self) -> None:
        self.validation_banner.setVisible(False)
        self.retry_btn.setVisible(False)

    def _validate_plan(self) -> tuple[bool, str | None]:
        self._clear_row_highlights()
        if not self._entries:
            return False, self.tr(
                f"No commits found between {self._base_label} and HEAD to rebase."
            )
        if self._is_truncated:
            return False, self.tr(
                "Commit range exceeds 1000 commits; select a closer base commit "
                "to prevent dropping older commits."
            )
        if self._entries[0].action in ("squash", "fixup"):
            self._highlight_invalid_row(0)
            return False, self.tr(
                "Cannot squash/fixup the first commit — no previous commit above it"
            )
        for idx, entry in enumerate(self._entries):
            if (
                entry.action == "reword"
                and entry.new_message is not None
                and not entry.new_message.strip()
            ):
                self._highlight_invalid_row(idx)
                return False, self.tr(
                    f"Reworded commit message for {entry.short_oid} cannot be empty."
                )
        return True, None

    def _validate_and_update_state(self) -> bool:
        if self._is_loading:
            self._update_controls_enabled(plan_valid=False)
            return False
        valid, err = self._validate_plan()
        if valid:
            self._hide_banner_error()
        else:
            self._show_banner_error(err or "", retryable=False)
        self._update_controls_enabled(plan_valid=valid)
        self._update_cli_preview()
        return valid

    def _update_controls_enabled(self, *, plan_valid: bool | None = None) -> None:
        if plan_valid is None:
            plan_valid = bool(self._entries) and not self._is_truncated
        busy = self._is_busy
        loading = self._is_loading
        row = self._current_selected_row()
        self.todo_table.setEnabled(not busy and not loading)
        self.autostash_cb.setEnabled(not busy)
        self.autosquash_cb.setEnabled(not busy)
        self.message_edit.setEnabled(not busy)
        self.cancel_btn.setEnabled(not busy)
        self.move_up_btn.setEnabled(not busy and not loading and row > 0)
        self.move_down_btn.setEnabled(
            not busy and not loading and 0 <= row < len(self._entries) - 1
        )
        self.start_btn.setEnabled(not busy and not loading and plan_valid)

    @Slot()
    def _update_cli_preview(self) -> None:
        try:
            args = engine.build_interactive_rebase_cli_args(
                self._base_oid,
                autostash=self.autostash_cb.isChecked(),
                autosquash=self.autosquash_cb.isChecked(),
            )
            self.preview_bar.set_command(["-C", str(self._repo_path), *args])
        except Exception as exc:
            logger.debug("Skipping CLI preview update: %s", exc)

    def _on_start_clicked(self) -> None:
        if self._is_busy or self._is_loading:
            return
        if not self._validate_and_update_state():
            return

        self._run_generation += 1
        self._is_busy = True
        self.last_result = None
        self._hide_banner_error()
        self.status_label.setText(self.tr("Running interactive rebase…"))
        self._update_controls_enabled(plan_valid=True)
        self.rebase_started.emit()

        worker = _RunInteractiveRebaseWorker(
            generation_id=self._run_generation,
            repo_path=self._repo_path,
            base_oid=self._base_oid,
            entries=self.planned_entries(),
            autostash=self.autostash_cb.isChecked(),
            autosquash=self.autosquash_cb.isChecked(),
            dialog_ref=weakref.ref(self),
            dispatcher=_get_rebase_dispatcher(),
        )
        QThreadPool.globalInstance().start(worker)

    @Slot(int, object)
    def _on_rebase_succeeded(self, generation_id: int, result: Any) -> None:
        if not shiboken6.isValid(self) or generation_id != self._run_generation:
            return
        self._is_busy = False
        self.last_result = result if isinstance(result, RebaseResult) else RebaseResult(
            status=getattr(result, "status", "complete"),
            conflicted_files=list(getattr(result, "conflicted_files", [])),
        )
        self._update_controls_enabled(plan_valid=True)
        self.rebase_completed.emit(self.last_result)
        self.accept()

    @Slot(int, str, bool)
    def _on_rebase_failed(self, generation_id: int, err_msg: str, retryable: bool) -> None:
        if not shiboken6.isValid(self) or generation_id != self._run_generation:
            return
        self._is_busy = False
        self.status_label.setText(self.tr("Interactive rebase failed."))
        self._show_banner_error(err_msg, retryable=retryable)
        self._update_controls_enabled(plan_valid=True)
        self.rebase_failed.emit(err_msg)

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
                        opener(
                            "Branches & Stacks",
                            "rebase.interactive_ui.enabled",
                            parent_dialog=self,
                        )
                    except TypeError:
                        opener("Branches & Stacks", "rebase.interactive_ui.enabled")
                finally:
                    self._settings_open = False
                    if shiboken6.isValid(self):
                        self.settings_open_banner.setVisible(False)
                        if self._pending_close_on_disable:
                            self._pending_close_on_disable = False
                            self.reject()
                return
            p = p.parent()
