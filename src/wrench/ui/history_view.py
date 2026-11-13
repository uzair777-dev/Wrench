"""3-Column HistoryView, Refs Sidebar, Commit Inspector Dock & Pure-Painter Neon Graph (FR-3.17, ui-planning.md §6.29.5).

Provides:
- AvatarPixmapCache: 128-entry LRU cache for 20x20 circular avatar/initials pixmaps with 2px glowing lane rings.
- CommitGraphRowDelegate: Pure-painter QStyledItemDelegate with 12% alpha lane row gradient,
  dedicated BRANCH/TAG connector wires, cubic Bezier lanes, and avatar-in-node painting. (OPT-11 compliant, ZERO setCellWidget).
- RefsSidebarWidget: 230px collapsible refs hierarchy (Local, Remote folders, Tags, Stashes).
- CommitInspectorDock: 380px right-hand commit details, parent links, changed files diffstat, and integrated DiffWidget.
- HistoryView: 3-column horizontal QSplitter container hosting sidebar, center graph, and inspector dock.
"""

from __future__ import annotations

import collections
import logging
from typing import Any

import shiboken6
from PySide6.QtCore import (
    QEvent,
    QModelIndex,
    QPointF,
    QRectF,
    Qt,
    Signal,
)
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFontMetrics,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSplitter,
    QStyle,
    QStyledItemDelegate,
    QTextEdit,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from wrench.core import engine
from wrench.core.engine import RepoHandle
from wrench.core.models import (
    Commit,
    RefSidebarTree,
)
from wrench.storage.settings_registry import SettingsRegistry
from wrench.ui import icons
from wrench.ui.commit_graph.graph_widget import CommitGraphWidget
from wrench.ui.commit_graph.layout import GraphRow
from wrench.ui.diff_view.diff_widget import DiffWidget
from wrench.ui.theme import (
    DEFAULT_ICON_COLOR,
    DIFF_ADD_BAR,
    INSPECTOR_BG_DARK,
    INSPECTOR_BG_LIGHT,
    NEON_LANES_DARK,
    SIDEBAR_BG_DARK,
    SIDEBAR_BG_LIGHT,
    is_dark_theme,
)

logger = logging.getLogger(__name__)


class AvatarPixmapCache:
    """128-entry LRU cache mapping (author_email, size_px, ring_color_hex) -> circular QPixmap."""

    def __init__(self, maxsize: int = 128) -> None:
        self._maxsize = maxsize
        self._cache: collections.OrderedDict[tuple[str, int, str], QPixmap] = (
            collections.OrderedDict()
        )

    def get_or_render(
        self,
        name: str,
        email: str,
        size: int,
        ring_color_hex: str,
    ) -> QPixmap:
        """Returns cached circular avatar/initials pixmap with 2px ring border."""
        key = (email.strip().lower(), size, ring_color_hex)
        if key in self._cache:
            pix = self._cache[key]
            self._cache.move_to_end(key)
            return pix

        pix = QPixmap(size, size)
        pix.fill(Qt.GlobalColor.transparent)

        painter = QPainter(pix)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        # Background circular fill
        r = float(size) / 2.0
        center = QPointF(r, r)

        # Derive initial letters from author name
        words = name.strip().split()
        if len(words) >= 2:
            initials = (words[0][:1] + words[1][:1]).upper()
        elif words:
            initials = words[0][:2].upper()
        else:
            initials = email[:2].upper() if email else "??"

        ring_color = QColor(ring_color_hex)
        bg_color = QColor(ring_color.red(), ring_color.green(), ring_color.blue(), 60)

        # Draw circle background
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(bg_color))
        painter.drawEllipse(center, r - 1.5, r - 1.5)

        # Draw 2px solid ring border
        painter.setPen(QPen(ring_color, 2.0))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(center, r - 1.5, r - 1.5)

        # Draw initials text
        painter.setPen(QPen(QColor(255, 255, 255, 240)))
        font = painter.font()
        font.setPointSize(max(7, int(size * 0.38)))
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(QRectF(0, 0, size, size), Qt.AlignmentFlag.AlignCenter, initials)

        painter.end()

        if len(self._cache) >= self._maxsize:
            self._cache.popitem(last=False)
        self._cache[key] = pix
        return pix


_AVATAR_CACHE = AvatarPixmapCache(maxsize=128)


class CommitGraphRowDelegate(QStyledItemDelegate):
    """Pure-painter item delegate for 3-column HistoryView (OPT-11 compliant).

    Paints:
    1. 12% alpha lane row gradient tint across full row width
    2. Col 0 (BRANCH / TAG): SVG ref pill + 1.5px horizontal connector wire to right edge
    3. Col 1 (GRAPH): Cubic Bezier lanes + 20x20 circular author avatar node
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

    def paint(self, painter: QPainter, option: Any, index: QModelIndex) -> None:
        if not index.isValid():
            return

        row_data: GraphRow | None = index.data(Qt.ItemDataRole.UserRole)
        col = index.column()

        # Retrieve active lane color
        lane_idx = row_data.lane_index if row_data is not None else 0
        lane_color_hex = NEON_LANES_DARK[lane_idx % len(NEON_LANES_DARK)]
        lane_color = QColor(lane_color_hex)

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setClipRect(option.rect)

        # 1. 12% Alpha Row Gradient Background Tint
        rect = option.rect
        grad = QLinearGradient(rect.left(), rect.top(), rect.right(), rect.top())
        grad.setColorAt(0.0, QColor(lane_color.red(), lane_color.green(), lane_color.blue(), 30))
        grad.setColorAt(1.0, QColor(lane_color.red(), lane_color.green(), lane_color.blue(), 6))
        painter.fillRect(rect, grad)

        is_selected = bool(option.state & QStyle.StateFlag.State_Selected)
        if is_selected:
            sel_brush = QBrush(QColor(lane_color.red(), lane_color.green(), lane_color.blue(), 75))
            painter.fillRect(rect, sel_brush)

        # 2. Column-Specific Rendering
        if col == 0:
            # Dedicated BRANCH / TAG Column
            self._paint_branch_tag_cell(painter, option, row_data, lane_color)
        elif col == 1:
            # Neon Commit Graph Lane Rails + Avatar Node
            self._paint_graph_cell(painter, option, row_data, lane_color, is_selected)
        else:
            # Delegate remaining text columns to standard styling
            super().paint(painter, option, index)

        painter.restore()

    def _paint_branch_tag_cell(
        self,
        painter: QPainter,
        option: Any,
        row_data: GraphRow | None,
        lane_color: QColor,
    ) -> None:
        rect = option.rect
        y_center = rect.y() + rect.height() / 2.0

        if row_data is None:
            return

        labels = getattr(row_data, "ref_labels", []) or []
        refs = getattr(row_data.commit, "refs", []) or []
        if not labels and not refs:
            return

        # Render first ref pill
        icon_name = "branch"
        if labels:
            lbl = labels[0]
            pill_text = lbl.name
            if lbl.kind == "tag":
                icon_name = "tag"
            elif lbl.kind == "head":
                icon_name = "laptop"
            else:
                icon_name = "branch"
        else:
            ref = str(refs[0])
            pill_text = ref
            if ref.startswith("local:"):
                icon_name = "laptop"
                pill_text = ref[6:]
            elif ref.startswith("remote:"):
                icon_name = "cloud"
                pill_text = ref[7:]
            elif ref.startswith("tag:"):
                icon_name = "tag"
                pill_text = ref[4:]

        # Truncate pill text if too long
        font = option.font
        font.setPointSize(max(8, font.pointSize() - 1))
        font.setBold(True)
        painter.setFont(font)
        metrics = QFontMetrics(font)

        avail_w = rect.width() - 40
        disp_text = metrics.elidedText(pill_text, Qt.TextElideMode.ElideRight, avail_w)
        pill_w = metrics.horizontalAdvance(disp_text) + 26
        pill_h = 20

        pill_rect = QRectF(rect.x() + 6, y_center - pill_h / 2.0, pill_w, pill_h)

        # Draw Pill Background
        painter.setPen(QPen(lane_color, 1.2))
        pill_bg = QColor(lane_color.red(), lane_color.green(), lane_color.blue(), 45)
        painter.setBrush(QBrush(pill_bg))
        painter.drawRoundedRect(pill_rect, 4.0, 4.0)

        # Draw SVG Icon
        icon_pix = icons.get_pixmap(icon_name, color=lane_color.name(), size=14)
        painter.drawPixmap(int(pill_rect.x() + 4), int(y_center - 7), icon_pix)

        # Draw Pill Text
        painter.setPen(QPen(QColor(230, 235, 245)))
        painter.drawText(
            QRectF(pill_rect.x() + 20, pill_rect.y(), pill_rect.width() - 22, pill_rect.height()),
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            disp_text,
        )

        # Draw 1.5px Horizontal Connector Wire to right edge of cell
        wire_start_x = pill_rect.right()
        wire_end_x = float(rect.right())
        painter.setPen(QPen(lane_color, 1.5))
        painter.drawLine(QPointF(wire_start_x, y_center), QPointF(wire_end_x, y_center))

    def _paint_graph_cell(
        self,
        painter: QPainter,
        option: Any,
        row_data: GraphRow | None,
        lane_color: QColor,
        is_selected: bool,
    ) -> None:
        rect = option.rect
        y_center = rect.y() + rect.height() / 2.0
        y_top = float(rect.y())
        y_bottom = float(rect.y() + rect.height())

        if row_data is None:
            return

        lane_idx = row_data.lane_index
        lane_w = 22.0
        node_x = rect.x() + 14.0 + lane_idx * lane_w

        # Connect wire from left edge into node if commit has refs
        if getattr(row_data.commit, "refs", None):
            painter.setPen(QPen(lane_color, 1.5))
            painter.drawLine(QPointF(rect.left(), y_center), QPointF(node_x, y_center))

        # Vertical Rails
        painter.setPen(QPen(lane_color, 2.2))
        painter.drawLine(QPointF(node_x, y_top), QPointF(node_x, y_bottom))

        # Cubic Bezier Connector Curves
        for conn in getattr(row_data, "connectors", []):
            conn_color = QColor(conn.color)
            painter.setPen(QPen(conn_color, 2.0))
            painter.setBrush(Qt.BrushStyle.NoBrush)

            x_from = rect.x() + 14.0 + conn.from_lane * lane_w
            x_to = rect.x() + 14.0 + conn.to_lane * lane_w

            path = QPainterPath()
            path.moveTo(x_from, y_bottom)
            dy = y_bottom - y_center
            c1 = QPointF(x_from, y_bottom - dy * 0.5)
            c2 = QPointF(x_to, y_center + dy * 0.5)
            path.cubicTo(c1, c2, QPointF(x_to, y_center))
            painter.drawPath(path)

        # 20x20 Circular Author Avatar / Initials Node
        avatar_size = 20
        author_name = getattr(row_data.commit, "author_name", "") or ""
        author_email = getattr(row_data.commit, "author_email", "") or ""

        avatar_pix = _AVATAR_CACHE.get_or_render(
            author_name,
            author_email,
            avatar_size,
            lane_color.name(),
        )
        avatar_rect = QRectF(
            node_x - avatar_size / 2.0,
            y_center - avatar_size / 2.0,
            avatar_size,
            avatar_size,
        )
        painter.drawPixmap(int(avatar_rect.x()), int(avatar_rect.y()), avatar_pix)

        if is_selected:
            halo_brush = QBrush(QColor(lane_color.red(), lane_color.green(), lane_color.blue(), 90))
            painter.setPen(QPen(QColor(255, 255, 255, 230), 2.0))
            painter.setBrush(halo_brush)
            painter.drawEllipse(QPointF(node_x, y_center), 12.0, 12.0)


class RefsSidebarWidget(QWidget):
    """230px left column collapsible refs hierarchy."""

    ref_selected = Signal(str, str)  # ref_name, target_oid
    branch_checkout_requested = Signal(str)  # branch_name

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._applying_theme: bool = False
        self._init_ui()

    def _init_ui(self) -> None:
        self.setMinimumWidth(200)
        self.setMaximumWidth(320)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)

        # Filter Box
        self.filter_input = QLineEdit(self)
        self.filter_input.setPlaceholderText(self.tr("Filter branches & tags…"))
        self.filter_input.setClearButtonEnabled(True)
        self.filter_input.textChanged.connect(self._on_filter_changed)
        layout.addWidget(self.filter_input)

        # Tree Widget
        self.tree = QTreeWidget(self)
        self.tree.setHeaderHidden(True)
        self.tree.setAnimated(True)
        self.tree.itemClicked.connect(self._on_item_clicked)
        self.tree.itemDoubleClicked.connect(self._on_item_double_clicked)
        layout.addWidget(self.tree)

        # Top-level sections
        self.local_root = QTreeWidgetItem(self.tree, [self.tr("LOCAL")])
        self.local_root.setIcon(0, icons.get_icon("laptop", color=DEFAULT_ICON_COLOR, size=16))
        self.local_root.setExpanded(True)

        self.remote_root = QTreeWidgetItem(self.tree, [self.tr("REMOTE")])
        self.remote_root.setIcon(0, icons.get_icon("cloud", color=DEFAULT_ICON_COLOR, size=16))
        self.remote_root.setExpanded(True)

        self.tag_root = QTreeWidgetItem(self.tree, [self.tr("TAGS")])
        self.tag_root.setIcon(0, icons.get_icon("tag", color=DEFAULT_ICON_COLOR, size=16))
        self.tag_root.setExpanded(False)

        self.stash_root = QTreeWidgetItem(self.tree, [self.tr("STASHES")])
        self.stash_root.setIcon(0, icons.get_icon("stash", color=DEFAULT_ICON_COLOR, size=16))
        self.stash_root.setExpanded(False)

        self._apply_theme()

    def set_tree_data(self, tree_data: RefSidebarTree) -> None:
        """Populates the hierarchy from RefSidebarTree."""
        # Local
        self.local_root.takeChildren()
        self.local_root.setText(0, f"LOCAL ({len(tree_data.local_branches)})")
        for b in tree_data.local_branches:
            disp_text = b.name
            if b.is_head:
                disp_text = f"✓ {b.name}"
            if b.ahead > 0 or b.behind > 0:
                disp_text += f" [{b.ahead}↑ {b.behind}↓]"
            item = QTreeWidgetItem(self.local_root, [disp_text])
            item.setIcon(
                0,
                icons.get_icon(
                    "branch", color=DIFF_ADD_BAR if b.is_head else DEFAULT_ICON_COLOR, size=14
                ),
            )
            item.setData(0, Qt.ItemDataRole.UserRole, ("branch", b.name, b.target_oid))
            if b.is_head:
                font = item.font(0)
                font.setBold(True)
                item.setFont(0, font)

        # Remote (Hierarchical / grouping)
        self.remote_root.takeChildren()
        self.remote_root.setText(0, f"REMOTE ({len(tree_data.remote_branches)})")
        folders: dict[str, QTreeWidgetItem] = {}
        for b in tree_data.remote_branches:
            parts = b.name.split("/")
            remote_name = parts[0] if parts else "origin"
            branch_subpath = "/".join(parts[1:]) if len(parts) > 1 else b.name

            folder_key = remote_name
            if folder_key not in folders:
                folder_item = QTreeWidgetItem(self.remote_root, [remote_name])
                folder_item.setIcon(0, icons.get_icon("folder", color=DEFAULT_ICON_COLOR, size=14))
                folder_item.setExpanded(True)
                folders[folder_key] = folder_item

            sub_item = QTreeWidgetItem(folders[folder_key], [branch_subpath])
            sub_item.setIcon(0, icons.get_icon("branch", color=DEFAULT_ICON_COLOR, size=14))
            sub_item.setData(0, Qt.ItemDataRole.UserRole, ("remote", b.name, b.target_oid))

        # Tags
        self.tag_root.takeChildren()
        self.tag_root.setText(0, f"TAGS ({len(tree_data.tags)})")
        for t in tree_data.tags:
            item = QTreeWidgetItem(self.tag_root, [t.name])
            item.setIcon(0, icons.get_icon("tag", color=DEFAULT_ICON_COLOR, size=14))
            item.setData(0, Qt.ItemDataRole.UserRole, ("tag", t.name, t.target_oid))

        # Stashes
        self.stash_root.takeChildren()
        self.stash_root.setText(0, f"STASHES ({len(tree_data.stashes)})")
        for s in tree_data.stashes:
            disp = f"stash@{{{s.index}}}: {s.message}"
            item = QTreeWidgetItem(self.stash_root, [disp])
            item.setIcon(0, icons.get_icon("stash", color=DEFAULT_ICON_COLOR, size=14))
            item.setData(0, Qt.ItemDataRole.UserRole, ("stash", s.oid, s.oid))

    def _on_filter_changed(self, text: str) -> None:
        """Filters tree items by substring matching."""
        term = text.strip().lower()
        for root in (self.local_root, self.remote_root, self.tag_root, self.stash_root):
            for i in range(root.childCount()):
                item = root.child(i)
                self._filter_item_recursive(item, term)

    def _filter_item_recursive(self, item: QTreeWidgetItem, term: str) -> bool:
        matches = term in item.text(0).lower()
        child_matches = False
        for i in range(item.childCount()):
            if self._filter_item_recursive(item.child(i), term):
                child_matches = True
        visible = matches or child_matches
        item.setHidden(not visible)
        return visible

    def _on_item_clicked(self, item: QTreeWidgetItem, column: int) -> None:
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if data and len(data) >= 3:
            kind, name, oid = data[0], data[1], data[2]
            self.ref_selected.emit(name, oid)

    def _on_item_double_clicked(self, item: QTreeWidgetItem, column: int) -> None:
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if data and data[0] == "branch":
            self.branch_checkout_requested.emit(data[1])

    def changeEvent(self, event: QEvent) -> None:
        if getattr(self, "_applying_theme", False):
            return
        super().changeEvent(event)
        if event.type() in (QEvent.Type.PaletteChange, QEvent.Type.ThemeChange):
            self._apply_theme()

    def _apply_theme(self) -> None:
        if getattr(self, "_applying_theme", False):
            return
        self._applying_theme = True
        try:
            dark = is_dark_theme(self)
            bg = SIDEBAR_BG_DARK if dark else SIDEBAR_BG_LIGHT
            self.setStyleSheet(f"background-color: {bg}; border: none;")
        finally:
            self._applying_theme = False


class CommitInspectorDock(QWidget):
    """380px right column commit inspector dock with full details, diffstat, and DiffWidget."""

    parent_clicked = Signal(str)  # parent_sha

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._applying_theme: bool = False
        self._repo: RepoHandle | None = None
        self._commit: Commit | None = None
        self._init_ui()

    def _init_ui(self) -> None:
        self.setMinimumWidth(320)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        # Header Card: SHA + Copy + Parents
        header_card = QFrame(self)
        header_layout = QVBoxLayout(header_card)
        header_layout.setContentsMargins(6, 6, 6, 6)
        header_layout.setSpacing(4)

        sha_row = QHBoxLayout()
        self.sha_lbl = QLabel(self.tr("No commit selected"), header_card)
        self.sha_lbl.setStyleSheet("font-family: monospace; font-size: 12px; font-weight: bold;")
        sha_row.addWidget(self.sha_lbl, 1)

        self.copy_btn = QToolButton(header_card)
        self.copy_btn.setIcon(icons.get_icon("copy", color=DEFAULT_ICON_COLOR, size=14))
        self.copy_btn.setToolTip(self.tr("Copy commit SHA"))
        self.copy_btn.clicked.connect(self._copy_sha)
        sha_row.addWidget(self.copy_btn)
        header_layout.addLayout(sha_row)

        self.parents_layout = QHBoxLayout()
        header_layout.addLayout(self.parents_layout)
        layout.addWidget(header_card)

        # Author & Date Card
        self.author_card = QFrame(self)
        author_layout = QHBoxLayout(self.author_card)
        author_layout.setContentsMargins(6, 4, 6, 4)
        author_layout.setSpacing(8)

        self.avatar_lbl = QLabel(self.author_card)
        self.avatar_lbl.setFixedSize(28, 28)
        author_layout.addWidget(self.avatar_lbl)

        author_text_col = QVBoxLayout()
        author_text_col.setContentsMargins(0, 0, 0, 0)
        author_text_col.setSpacing(2)
        self.author_name_lbl = QLabel("", self.author_card)
        self.author_name_lbl.setStyleSheet("font-weight: bold; font-size: 12px;")
        author_text_col.addWidget(self.author_name_lbl)

        self.date_lbl = QLabel("", self.author_card)
        self.date_lbl.setStyleSheet("font-size: 11px;")
        author_text_col.addWidget(self.date_lbl)
        author_layout.addLayout(author_text_col, 1)
        layout.addWidget(self.author_card)

        # Message Text Card
        self.msg_edit = QTextEdit(self)
        self.msg_edit.setReadOnly(True)
        self.msg_edit.setMaximumHeight(120)
        layout.addWidget(self.msg_edit)

        # Files List Header + Diffstat
        self.files_header = QLabel(self.tr("Changed Files"), self)
        self.files_header.setStyleSheet("font-weight: bold; font-size: 12px;")
        layout.addWidget(self.files_header)

        self.files_list = QListWidget(self)
        self.files_list.setMaximumHeight(110)
        self.files_list.itemClicked.connect(self._on_file_clicked)
        layout.addWidget(self.files_list)

        # Integrated DiffWidget
        self.diff_widget = DiffWidget(self)
        layout.addWidget(self.diff_widget, 1)

        self._apply_theme()

    def set_repo(self, repo: RepoHandle | None) -> None:
        self._repo = repo
        self.diff_widget.set_repo(repo)

    def set_commit(self, commit: Commit | None) -> None:
        self._commit = commit
        if commit is None:
            self.sha_lbl.setText(self.tr("No commit selected"))
            self.author_name_lbl.setText("")
            self.date_lbl.setText("")
            self.msg_edit.setPlainText("")
            self.files_list.clear()
            self._clear_parents()
            self.diff_widget.clear()
            return

        if commit.sha.startswith("00000000"):
            self.sha_lbl.setText("// WIP (Uncommitted Changes)")
            self.author_name_lbl.setText(commit.author_name)
            self.date_lbl.setText("Now")
            self.msg_edit.setPlainText(commit.message)
            self._clear_parents()
            self.files_list.clear()
            if self._repo:
                try:
                    st = engine.get_status(self._repo)
                    all_changes = st.staged + st.unstaged
                    for ch in all_changes:
                        item = QListWidgetItem(ch.path, self.files_list)
                        item.setData(Qt.ItemDataRole.UserRole, ch.path)
                    for untracked in st.untracked:
                        item = QListWidgetItem(untracked, self.files_list)
                        item.setData(Qt.ItemDataRole.UserRole, untracked)
                    if self.files_list.count() > 0:
                        self.files_list.setCurrentRow(0)
                        self._on_file_clicked(self.files_list.item(0))
                except Exception as exc:
                    logger.debug("Failed loading working tree status for WIP: %s", exc)
            return

        self.sha_lbl.setText(commit.sha)
        self.author_name_lbl.setText(f"{commit.author_name} <{commit.author_email}>")
        date_str = str(commit.author_date)[:19].replace("T", " ")
        self.date_lbl.setText(date_str)
        self.msg_edit.setPlainText(commit.message)

        # Render avatar
        pix = _AVATAR_CACHE.get_or_render(
            commit.author_name,
            commit.author_email,
            28,
            NEON_LANES_DARK[0],
        )
        self.avatar_lbl.setPixmap(pix)

        # Render parents
        self._render_parents(commit.parent_shas)

        # Load changed files diffstat
        self.files_list.clear()
        if self._repo:
            try:
                commit_diff = engine.get_commit_diff(self._repo, commit.sha)
                for hunk_diff in commit_diff:
                    item = QListWidgetItem(hunk_diff.path, self.files_list)
                    item.setData(Qt.ItemDataRole.UserRole, hunk_diff.path)
                if self.files_list.count() > 0:
                    self.files_list.setCurrentRow(0)
                    self._on_file_clicked(self.files_list.item(0))
            except Exception as exc:
                logger.debug("Failed loading commit changed files: %s", exc)

    def _render_parents(self, parents: list[str]) -> None:
        self._clear_parents()
        if not parents:
            lbl = QLabel(self.tr("Root commit (no parents)"), self)
            lbl.setStyleSheet("font-size: 11px;")
            self.parents_layout.addWidget(lbl)
            return

        lbl = QLabel(self.tr("Parents:"), self)
        lbl.setStyleSheet("font-size: 11px; font-weight: bold;")
        self.parents_layout.addWidget(lbl)

        for p_sha in parents:
            btn = QPushButton(p_sha[:7], self)
            btn.setFixedHeight(22)
            btn.setStyleSheet("font-family: monospace; font-size: 11px;")
            btn.clicked.connect(lambda _, sha=p_sha: self.parent_clicked.emit(sha))
            self.parents_layout.addWidget(btn)
        self.parents_layout.addStretch()

    def _clear_parents(self) -> None:
        while self.parents_layout.count() > 0:
            item = self.parents_layout.takeAt(0)
            w = item.widget()
            if w is not None and shiboken6.isValid(w):
                w.deleteLater()

    def _copy_sha(self) -> None:
        if self._commit:
            cb = QApplication.clipboard()
            if cb:
                cb.setText(self._commit.sha)

    def _on_file_clicked(self, item: QListWidgetItem) -> None:
        path = item.data(Qt.ItemDataRole.UserRole)
        if not (self._repo and path):
            return
        if self._commit and self._commit.sha.startswith("00000000"):
            try:
                diff_model = engine.get_file_diff(self._repo, path)
                self.diff_widget.set_diff_model(diff_model)
            except Exception as exc:
                logger.debug("Failed showing working tree diff for WIP: %s", exc)
        elif self._commit:
            try:
                diff_model = engine.get_file_diff_at_commit(self._repo, path, self._commit.sha)
                self.diff_widget.set_diff_model(diff_model)
            except Exception as exc:
                logger.debug("Failed showing file diff at commit: %s", exc)

    def changeEvent(self, event: QEvent) -> None:
        if getattr(self, "_applying_theme", False):
            return
        super().changeEvent(event)
        if event.type() in (QEvent.Type.PaletteChange, QEvent.Type.ThemeChange):
            self._apply_theme()

    def _apply_theme(self) -> None:
        if getattr(self, "_applying_theme", False):
            return
        self._applying_theme = True
        try:
            dark = is_dark_theme(self)
            bg = INSPECTOR_BG_DARK if dark else INSPECTOR_BG_LIGHT
            self.setStyleSheet(f"background-color: {bg}; border: none;")
        finally:
            self._applying_theme = False


class HistoryView(QWidget):
    """3-Column GitKraken-class commit graph IDE view (FR-3.17)."""

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        settings_registry: SettingsRegistry | None = None,
    ) -> None:
        super().__init__(parent)
        self._settings_registry = settings_registry
        self._repo: RepoHandle | None = None
        self._init_ui()

    def _init_ui(self) -> None:
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # 3-Column horizontal splitter
        self.content_splitter = QSplitter(Qt.Orientation.Horizontal, self)
        main_layout.addWidget(self.content_splitter)

        # Col 1: Left Refs Sidebar (230px)
        self.sidebar = RefsSidebarWidget(self.content_splitter)
        self.sidebar.ref_selected.connect(self._on_ref_selected)
        self.sidebar.branch_checkout_requested.connect(self._on_branch_checkout_requested)
        self.content_splitter.addWidget(self.sidebar)

        # Col 2: Center Neon Commit Graph
        self.graph_widget = CommitGraphWidget(self.content_splitter)
        if self._settings_registry:
            self.graph_widget.set_settings_registry(self._settings_registry)
        self.graph_widget.set_three_column_mode(True)
        self.graph_widget.commit_selected.connect(self._on_commit_selected)
        self.content_splitter.addWidget(self.graph_widget)

        # Col 3: Right Commit Inspector Dock (380px)
        self.inspector_dock = CommitInspectorDock(self.content_splitter)
        self.inspector_dock.parent_clicked.connect(self._on_parent_sha_clicked)
        self.detail_panel = self.inspector_dock  # Alias for backward compatibility
        self.content_splitter.addWidget(self.inspector_dock)

        # Splitter sizing: 230px sidebar, 600px graph, 380px inspector
        self.content_splitter.setSizes([230, 600, 380])
        self.content_splitter.setStretchFactor(0, 0)
        self.content_splitter.setStretchFactor(1, 1)
        self.content_splitter.setStretchFactor(2, 0)

    def set_repo(self, repo: RepoHandle | None) -> None:
        self._repo = repo
        self.graph_widget.set_repo(repo)
        self.inspector_dock.set_repo(repo)
        self.refresh()

    def refresh(self) -> None:
        if not self._repo:
            return
        try:
            tree = engine.GitEngine(settings=self._settings_registry).get_ref_sidebar_tree(
                self._repo
            )
            self.sidebar.set_tree_data(tree)
        except Exception as exc:
            logger.debug("Failed refreshing ref sidebar tree: %s", exc)

    def _on_ref_selected(self, name: str, oid: str) -> None:
        # Scroll graph to target oid
        self.graph_widget.select_and_scroll_to_commit(oid)

    def _on_branch_checkout_requested(self, branch_name: str) -> None:
        win = self.window()
        if hasattr(win, "_on_checkout_branch"):
            try:
                engine.checkout_branch(self._repo, branch_name)
                win._on_checkout_branch(branch_name)
            except Exception as exc:
                logger.debug("Checkout failed from sidebar: %s", exc)

    def _on_commit_selected(self, commit: Any) -> None:
        if not self._repo:
            return
        if commit is None:
            self.inspector_dock.set_commit(None)
            return
        if isinstance(commit, str):
            sha = commit
        elif hasattr(commit, "sha"):
            sha = commit.sha
        else:
            self.inspector_dock.set_commit(None)
            return
        try:
            full_commit = engine.get_commit_details(self._repo, sha)
            self.inspector_dock.set_commit(full_commit)
        except Exception as exc:
            logger.debug("Failed loading commit details: %s", exc)
            if hasattr(commit, "sha"):
                self.inspector_dock.set_commit(commit)

    def _on_parent_sha_clicked(self, sha: str) -> None:
        self.graph_widget.select_and_scroll_to_commit(sha)

    # State persistence helpers
    def save_splitter_state(self) -> str:
        return self.content_splitter.saveState().toHex().data().decode("ascii")

    def restore_splitter_state(self, hex_state: str) -> None:
        try:
            from PySide6.QtCore import QByteArray

            self.content_splitter.restoreState(QByteArray.fromHex(hex_state.encode("ascii")))
        except Exception as exc:
            logger.debug("Failed restoring history splitter state: %s", exc)

    def save_header_state(self) -> str:
        return self.graph_widget.horizontalHeader().saveState().toHex().data().decode("ascii")

    def restore_header_state(self, hex_state: str) -> None:
        try:
            from PySide6.QtCore import QByteArray

            self.graph_widget.horizontalHeader().restoreState(
                QByteArray.fromHex(hex_state.encode("ascii"))
            )
        except Exception as exc:
            logger.debug("Failed restoring history header state: %s", exc)
