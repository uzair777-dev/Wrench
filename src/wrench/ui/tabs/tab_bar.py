"""Hybrid Tab Navigation System (ui-planning.md §2).

Provides custom TabBar and TabContainer widgets supporting:
- Vertical mode (left side, default) and Horizontal mode (top)
- Dynamic tabs with close (×) button and right-click pin/unpin
- Context menu: Pin Tab, Close Tab, Close Other Tabs, Close Tabs to the Right/Below
- Per-repo deduplication rule: (tab_type, repo_path, entity_id)
- Add (+) dropdown menu for all category tabs (Changes, History, PRs, Issues)
- Keyboard switching (Ctrl+1, Ctrl+2, ...)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QIcon, QKeySequence, QPalette, QShortcut
from PySide6.QtWidgets import (
    QBoxLayout,
    QHBoxLayout,
    QMenu,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QToolButton,
    QWidget,
)

logger = logging.getLogger(__name__)


@dataclass
class TabMetadata:
    widget: QWidget
    label: str
    icon: QIcon | None
    tab_type: str
    repo_path: str
    entity_id: str | None = None
    closable: bool = True
    is_pinned: bool = False


class TabButton(QWidget):
    """A single tab button in the tab bar strip with close button and context menu."""

    clicked = Signal()
    close_requested = Signal()
    pin_toggled = Signal()
    close_others_requested = Signal()
    close_right_requested = Signal()

    def __init__(
        self,
        label: str,
        icon: QIcon | None = None,
        closable: bool = True,
        is_pinned: bool = False,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self._label_text = label
        self._is_pinned = is_pinned
        self._closable = closable and not is_pinned
        self._is_active = False
        self._orientation = Qt.Vertical

        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(6)

        self.main_btn = QPushButton(self)
        self.main_btn.setFlat(True)
        if icon and not icon.isNull():
            self.main_btn.setIcon(icon)
        self.main_btn.clicked.connect(self.clicked.emit)
        self.main_btn.setFocusPolicy(Qt.NoFocus)
        layout.addWidget(self.main_btn)

        self.close_btn = QToolButton(self)
        self.close_btn.setText("×")
        self.close_btn.setToolTip(self.tr("Close Tab"))
        self.close_btn.setAccessibleName(self.tr("Close Tab"))
        self.close_btn.setStyleSheet(
            "QToolButton { border: none; font-size: 14px; font-weight: bold; "
            "padding: 0px 3px; color: gray; } "
            "QToolButton:hover { color: #e55b5b; background: transparent; }"
        )
        self.close_btn.clicked.connect(self.close_requested.emit)
        layout.addWidget(self.close_btn)

        self._update_display_text()
        self.close_btn.setVisible(self._closable and not self._is_pinned)

        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)

        self._update_style()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)

    def _show_context_menu(self, pos: QPoint) -> None:
        menu = QMenu(self)

        if self._is_pinned:
            act_pin = menu.addAction(self.tr("Unpin Tab"))
        else:
            act_pin = menu.addAction(self.tr("Pin Tab"))
        act_pin.triggered.connect(self.pin_toggled.emit)

        menu.addSeparator()

        act_close = menu.addAction(self.tr("Close Tab"))
        act_close.setEnabled(not self._is_pinned)
        act_close.triggered.connect(self.close_requested.emit)

        act_close_others = menu.addAction(self.tr("Close Other Tabs"))
        act_close_others.triggered.connect(self.close_others_requested.emit)

        right_label = (
            self.tr("Close Tabs to the Right")
            if self._orientation == Qt.Horizontal
            else self.tr("Close Tabs Below")
        )
        act_close_right = menu.addAction(right_label)
        act_close_right.triggered.connect(self.close_right_requested.emit)

        menu.exec(self.mapToGlobal(pos))

    def _update_display_text(self) -> None:
        prefix = "📌 " if self._is_pinned else ""
        self.main_btn.setText(f"{prefix}{self._label_text}")

    def set_label(self, label: str) -> None:
        self._label_text = label
        self._update_display_text()

    def set_pinned(self, pinned: bool) -> None:
        self._is_pinned = pinned
        self._closable = not pinned
        if self.close_btn:
            self.close_btn.setVisible(not pinned)
        self._update_display_text()
        self._update_style()

    def set_active(self, active: bool) -> None:
        if self._is_active != active:
            self._is_active = active
            self._update_style()

    def set_orientation(self, orientation: Qt.Orientation) -> None:
        self._orientation = orientation
        self._update_style()

    def _update_style(self) -> None:
        pal = self.palette()
        highlight_color = pal.color(QPalette.Highlight).name()
        bg_highlight = pal.color(QPalette.AlternateBase).name()

        if self._is_active:
            if self._orientation == Qt.Vertical:
                border_style = f"border-left: 3px solid {highlight_color};"
            else:
                border_style = f"border-bottom: 3px solid {highlight_color};"
            self.setStyleSheet(
                f"TabButton {{ background-color: {bg_highlight}; {border_style} "
                f"font-weight: bold; }} "
                f"QPushButton {{ text-align: left; border: none; font-weight: bold; "
                f"padding: 4px; background: transparent; }}"
            )
        else:
            self.setStyleSheet(
                "TabButton { background-color: transparent; border: none; } "
                "QPushButton { text-align: left; border: none; padding: 4px; "
                "background: transparent; } "
                "TabButton:hover { background-color: rgba(128, 128, 128, 0.15); }"
            )


class TabContainer(QWidget):
    """Main tab container holding the TabBar strip and the QStackedWidget content area."""

    current_changed = Signal(int)
    tab_closed = Signal(int)
    tabs_mutated = Signal()
    orientation_changed = Signal(Qt.Orientation)
    add_category_tab_requested = Signal(str)  # 'changes' | 'history' | 'pr_list' | 'issues_list'

    def __init__(
        self,
        orientation: Qt.Orientation = Qt.Vertical,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self._orientation = orientation
        self._tabs: list[TabMetadata] = []
        self._tab_buttons: list[TabButton] = []
        self._current_index = -1

        self._main_layout = QBoxLayout(
            QBoxLayout.LeftToRight if orientation == Qt.Vertical else QBoxLayout.TopToBottom,
            self,
        )
        self._main_layout.setContentsMargins(0, 0, 0, 0)
        self._main_layout.setSpacing(0)

        self._strip_widget = QWidget(self)
        self._strip_layout = QBoxLayout(
            QBoxLayout.TopToBottom if orientation == Qt.Vertical else QBoxLayout.LeftToRight,
            self._strip_widget,
        )
        self._strip_layout.setSpacing(2)

        self._stack = QStackedWidget(self)
        self._main_layout.addWidget(self._strip_widget)
        self._main_layout.addWidget(self._stack, 1)

        self._add_btn = QToolButton(self)
        self._add_btn.setText("+")
        self._add_btn.setToolTip(self.tr("Add new tab"))
        self._add_btn.setAccessibleName(self.tr("Add new tab"))
        self._add_btn.setStyleSheet(
            "QToolButton { font-size: 16px; font-weight: bold; border: none; padding: 4px 8px; } "
            "QToolButton:hover { background-color: rgba(128, 128, 128, 0.2); border-radius: 3px; }"
        )
        self._add_btn.clicked.connect(self._show_add_menu)

        self._setup_layout()
        self._setup_shortcuts()

    def _setup_shortcuts(self) -> None:
        """Sets up Ctrl+1..Ctrl+9 shortcuts to switch tabs by index."""
        for i in range(1, 10):
            seq = QKeySequence(f"Ctrl+{i}")
            shortcut = QShortcut(seq, self)
            shortcut.activated.connect(lambda idx=i - 1: self._on_shortcut_activated(idx))

    def _on_shortcut_activated(self, index: int) -> None:
        if 0 <= index < len(self._tabs):
            self.set_current_index(index)

    def _setup_layout(self) -> None:
        if self._orientation == Qt.Vertical:
            self._main_layout.setDirection(QBoxLayout.LeftToRight)
            self._strip_layout.setDirection(QBoxLayout.TopToBottom)
            self._strip_widget.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
            self._strip_widget.setMinimumWidth(120)
            self._strip_widget.setMaximumWidth(180)
            self._strip_widget.setMinimumHeight(0)
            self._strip_widget.setMaximumHeight(16777215)
            self._strip_layout.setContentsMargins(2, 4, 2, 4)
        else:
            self._main_layout.setDirection(QBoxLayout.TopToBottom)
            self._strip_layout.setDirection(QBoxLayout.LeftToRight)
            self._strip_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            self._strip_widget.setMinimumWidth(0)
            self._strip_widget.setMaximumWidth(16777215)
            self._strip_widget.setMinimumHeight(32)
            self._strip_widget.setMaximumHeight(44)
            self._strip_layout.setContentsMargins(4, 2, 4, 2)

        self._rebuild_strip()

    def _rebuild_strip(self) -> None:
        """Rebuilds the buttons inside the tab strip layout."""
        if not self._strip_layout:
            return

        # Clear layout
        while self._strip_layout.count():
            item = self._strip_layout.takeAt(0)
            if item.widget() and item.widget() != self._add_btn:
                item.widget().setParent(None)

        self._tab_buttons.clear()

        for idx, tab in enumerate(self._tabs):
            btn = TabButton(
                label=tab.label,
                icon=tab.icon,
                closable=tab.closable,
                is_pinned=tab.is_pinned,
                parent=self._strip_widget,
            )
            btn.set_orientation(self._orientation)
            btn.set_active(idx == self._current_index)
            btn.clicked.connect(lambda i=idx: self.set_current_index(i))
            btn.close_requested.connect(lambda i=idx: self.remove_tab(i))
            btn.pin_toggled.connect(lambda i=idx: self.toggle_pin(i))
            btn.close_others_requested.connect(lambda i=idx: self.close_other_tabs(i))
            btn.close_right_requested.connect(lambda i=idx: self.close_tabs_to_right(i))
            self._strip_layout.addWidget(btn)
            self._tab_buttons.append(btn)

        if self._orientation == Qt.Vertical:
            self._strip_layout.addStretch()
            self._strip_layout.addWidget(self._add_btn, 0, Qt.AlignLeft)
        else:
            self._strip_layout.addWidget(self._add_btn, 0, Qt.AlignVCenter)
            self._strip_layout.addStretch()

    def set_orientation(self, orientation: Qt.Orientation) -> None:
        if self._orientation != orientation:
            self._orientation = orientation
            self._setup_layout()
            self.orientation_changed.emit(orientation)

    def orientation(self) -> Qt.Orientation:
        return self._orientation

    def count(self) -> int:
        return len(self._tabs)

    def current_index(self) -> int:
        return self._current_index

    def current_widget(self) -> QWidget | None:
        if 0 <= self._current_index < len(self._tabs):
            return self._tabs[self._current_index].widget
        return None

    def widget(self, index: int) -> QWidget | None:
        if 0 <= index < len(self._tabs):
            return self._tabs[index].widget
        return None

    def tab_metadata(self, index: int) -> TabMetadata | None:
        if 0 <= index < len(self._tabs):
            return self._tabs[index]
        return None

    def find_tab(
        self,
        tab_type: str,
        repo_path: str,
        entity_id: str | None = None,
    ) -> int | None:
        """Finds an open tab matching the identity triple (tab_type, repo_path, entity_id)."""
        for idx, tab in enumerate(self._tabs):
            if (
                tab.tab_type == tab_type
                and tab.repo_path == repo_path
                and (tab.entity_id or "") == (entity_id or "")
            ):
                return idx
        return None

    def add_tab(
        self,
        widget: QWidget,
        label: str,
        icon: QIcon | None = None,
        tab_type: str = "custom",
        repo_path: str = "",
        entity_id: str | None = None,
        closable: bool = True,
        is_pinned: bool = False,
    ) -> int:
        """Adds a new tab or switches to an existing one if already open (deduplication rule)."""
        # Only deduplicate if tab_type is a specific category/detail type or has an entity_id
        if tab_type != "custom" or entity_id is not None or repo_path != "":
            existing_idx = self.find_tab(tab_type, repo_path, entity_id)
            if existing_idx is not None:
                self.set_current_index(existing_idx)
                return existing_idx

        meta = TabMetadata(
            widget=widget,
            label=label,
            icon=icon,
            tab_type=tab_type,
            repo_path=repo_path,
            entity_id=entity_id,
            closable=closable and not is_pinned,
            is_pinned=is_pinned,
        )
        self._tabs.append(meta)
        self._stack.addWidget(widget)

        self._rebuild_strip()
        idx = len(self._tabs) - 1
        self.set_current_index(idx)
        self.tabs_mutated.emit()
        return idx

    def pin_tab(self, index: int) -> None:
        """Pins a tab, making it non-closable and displaying a pin badge."""
        if 0 <= index < len(self._tabs):
            self._tabs[index].is_pinned = True
            self._tabs[index].closable = False
            self._rebuild_strip()
            self.tabs_mutated.emit()

    def unpin_tab(self, index: int) -> None:
        """Unpins a tab, restoring normal closable status."""
        if 0 <= index < len(self._tabs):
            self._tabs[index].is_pinned = False
            self._tabs[index].closable = True
            self._rebuild_strip()
            self.tabs_mutated.emit()

    def toggle_pin(self, index: int) -> None:
        """Toggles pinned state of a tab."""
        if 0 <= index < len(self._tabs):
            if self._tabs[index].is_pinned:
                self.unpin_tab(index)
            else:
                self.pin_tab(index)

    def close_other_tabs(self, keep_index: int) -> None:
        """Closes all non-pinned tabs except the specified keep_index."""
        if not (0 <= keep_index < len(self._tabs)):
            return
        keep_tab = self._tabs[keep_index]
        to_remove = [i for i, t in enumerate(self._tabs) if t != keep_tab and not t.is_pinned]
        for i in reversed(to_remove):
            self.remove_tab(i)

    def close_tabs_to_right(self, index: int) -> None:
        """Closes all non-pinned tabs positioned after index."""
        if not (0 <= index < len(self._tabs)):
            return
        to_remove = [i for i in range(index + 1, len(self._tabs)) if not self._tabs[i].is_pinned]
        for i in reversed(to_remove):
            self.remove_tab(i)

    def remove_tab(self, index: int) -> None:
        """Closes a tab by index. Pinned tabs cannot be removed."""
        if not (0 <= index < len(self._tabs)):
            return

        meta = self._tabs[index]
        if meta.is_pinned or not meta.closable:
            logger.warning("Attempted to close pinned tab: %s", meta.label)
            return

        target_focus_idx = max(0, index - 1)

        widget = self._tabs[index].widget
        self._stack.removeWidget(widget)
        self._tabs.pop(index)

        self.tab_closed.emit(index)
        self._rebuild_strip()

        if len(self._tabs) > 0:
            new_idx = min(target_focus_idx, len(self._tabs) - 1)
            self.set_current_index(new_idx)
        else:
            self._current_index = -1

        self.tabs_mutated.emit()

    def clear_tabs(self) -> None:
        """Removes all open tabs from the container."""
        while self._tabs:
            widget = self._tabs.pop().widget
            self._stack.removeWidget(widget)
        self._tab_buttons.clear()
        self._current_index = -1
        self._rebuild_strip()
        self.tabs_mutated.emit()

    def serialize_tabs(self) -> dict:
        """Serializes current tab state to a dictionary for persistence."""
        items = []
        for tab in self._tabs:
            items.append(
                {
                    "tab_type": tab.tab_type,
                    "label": tab.label,
                    "repo_path": tab.repo_path,
                    "entity_id": tab.entity_id,
                    "closable": tab.closable,
                    "is_pinned": tab.is_pinned,
                }
            )
        return {
            "active_index": self._current_index,
            "items": items,
        }

    def set_current_index(self, index: int) -> None:
        if 0 <= index < len(self._tabs):
            self._current_index = index
            self._stack.setCurrentWidget(self._tabs[index].widget)
            for i, btn in enumerate(self._tab_buttons):
                btn.set_active(i == index)
            self.current_changed.emit(index)

    def set_tab_label(self, index: int, label: str) -> None:
        if 0 <= index < len(self._tabs):
            self._tabs[index].label = label
            if index < len(self._tab_buttons):
                self._tab_buttons[index].set_label(label)

    def _show_add_menu(self) -> None:
        """Shows dropdown menu of available category tabs when (+) button is clicked."""
        menu = QMenu(self)

        # Check which category tabs are currently open
        has_changes = any(t.tab_type == "changes" for t in self._tabs)
        has_history = any(t.tab_type == "history" for t in self._tabs)
        has_prs = any(t.tab_type == "pr_list" for t in self._tabs)
        has_issues = any(t.tab_type == "issues_list" for t in self._tabs)

        if not has_changes:
            act_changes = menu.addAction(self.tr("Changes"))
            act_changes.triggered.connect(lambda: self.add_category_tab_requested.emit("changes"))

        if not has_history:
            act_history = menu.addAction(self.tr("History"))
            act_history.triggered.connect(lambda: self.add_category_tab_requested.emit("history"))

        if not has_prs:
            act_pr = menu.addAction(self.tr("Pull Requests"))
            act_pr.triggered.connect(lambda: self.add_category_tab_requested.emit("pr_list"))

        if not has_issues:
            act_issues = menu.addAction(self.tr("Issues"))
            act_issues.triggered.connect(
                lambda: self.add_category_tab_requested.emit("issues_list")
            )

        if menu.isEmpty():
            disabled_act = menu.addAction(self.tr("All category tabs are open"))
            disabled_act.setEnabled(False)

        menu.exec(self._add_btn.mapToGlobal(QPoint(0, self._add_btn.height())))
