"""FR-2.2: Commit graph table widget with custom QStyledItemDelegate."""

import logging

from PySide6.QtCore import (
    QAbstractTableModel,
    QModelIndex,
    QPointF,
    QRectF,
    Qt,
    Signal,
)
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QGuiApplication,
    QPainter,
    QPainterPath,
    QPen,
)
from PySide6.QtWidgets import (
    QHeaderView,
    QMenu,
    QStyle,
    QStyledItemDelegate,
    QTableView,
    QWidget,
)

from wrench.core import engine
from wrench.core.engine import Commit, LogFilter, RepoHandle
from wrench.ui.commit_graph.layout import (
    GRAPH_COLORS,
    GraphRow,
    compute_graph_layout,
)

logger = logging.getLogger(__name__)

LANE_WIDTH = 18
ROW_HEIGHT = 26
NODE_RADIUS = 4.5


class GraphItemDelegate(QStyledItemDelegate):
    """Paints the lane rails, bezier connectors, and commit nodes for column 0."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)

    def paint(self, painter: QPainter, option, index: QModelIndex):
        if not index.isValid():
            return

        row_data: GraphRow = index.data(Qt.UserRole)
        if not row_data:
            return

        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)

        rect = option.rect
        x_offset = rect.x() + 10
        y_center = rect.y() + rect.height() / 2.0
        y_top = float(rect.y())
        y_bottom = float(rect.y() + rect.height())

        lane_idx = row_data.lane_index
        node_color = QColor(GRAPH_COLORS[lane_idx % len(GRAPH_COLORS)])

        # 1. Paint vertical pass-through rails for other active lanes
        for active_lane in row_data.active_lanes:
            if active_lane != lane_idx:
                rail_color = QColor(GRAPH_COLORS[active_lane % len(GRAPH_COLORS)])
                painter.setPen(QPen(rail_color, 2.0))
                lx = x_offset + active_lane * LANE_WIDTH
                painter.drawLine(QPointF(lx, y_top), QPointF(lx, y_bottom))

        # 2. Paint incoming/outgoing connectors (curves)
        for conn in row_data.connectors:
            conn_color = QColor(conn.color)
            painter.setPen(QPen(conn_color, 2.0))
            painter.setBrush(Qt.NoBrush)

            x_from = x_offset + conn.from_lane * LANE_WIDTH
            x_to = x_offset + conn.to_lane * LANE_WIDTH

            path = QPainterPath()
            path.moveTo(x_from, y_bottom)
            # Cubic bezier curve connecting from bottom of from_lane into center of to_lane
            c1 = QPointF(x_from, y_center + (y_bottom - y_center) * 0.5)
            c2 = QPointF(x_to, y_center)
            path.cubicTo(c1, c2, QPointF(x_to, y_center))
            painter.drawPath(path)

        # 3. Paint top-half and bottom-half rail for the occupied lane
        # Top-half rail (connects to commit row above if lane was active)
        painter.setPen(QPen(node_color, 2.0))
        node_x = x_offset + lane_idx * LANE_WIDTH
        painter.drawLine(QPointF(node_x, y_top), QPointF(node_x, y_center))
        # Bottom-half rail if this lane continues to parents
        if row_data.commit.parent_shas:
            painter.drawLine(QPointF(node_x, y_center), QPointF(node_x, y_bottom))

        # 4. Paint commit node circle
        painter.setPen(QPen(node_color.darker(120), 1.5))
        painter.setBrush(QBrush(node_color))

        is_merge = len(row_data.commit.parent_shas) > 1
        r = NODE_RADIUS + (1.0 if is_merge else 0.0)
        painter.drawEllipse(QPointF(node_x, y_center), r, r)

        if is_merge:
            # Draw inner white dot for merge commits
            painter.setBrush(QBrush(Qt.white))
            painter.drawEllipse(QPointF(node_x, y_center), 1.5, 1.5)

        painter.restore()


class RefLabelDelegate(QStyledItemDelegate):
    """Paints ref badges (branch, tag, head) alongside commit message in Column 1."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)

    def paint(self, painter: QPainter, option, index: QModelIndex):
        if not index.isValid():
            return

        row_data: GraphRow = index.data(Qt.UserRole)
        if not row_data:
            super().paint(painter, option, index)
            return

        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)

        # Draw selection background if selected
        is_selected = bool(option.state & QStyle.StateFlag.State_Selected)
        if is_selected:
            painter.fillRect(option.rect, option.palette.highlight())

        rect = option.rect
        x = rect.x() + 4
        y_center = rect.y() + rect.height() / 2.0

        badge_font = QFont(option.font)
        badge_font.setPointSize(max(7, badge_font.pointSize() - 2))
        badge_font.setBold(True)

        painter.setFont(badge_font)

        # Draw ref labels
        for label in row_data.ref_labels:
            text = label.name
            metrics = painter.fontMetrics()
            tw = metrics.horizontalAdvance(text) + 8
            th = metrics.height() + 2
            badge_rect = QRectF(x, y_center - th / 2.0, tw, th)

            if label.kind == "head":
                bg = QColor("#8e44ad")
            elif label.kind == "tag":
                bg = QColor("#d35400")
            else:
                bg = QColor("#2980b9")

            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(bg))
            painter.drawRoundedRect(badge_rect, 3, 3)

            painter.setPen(QPen(Qt.white))
            painter.drawText(badge_rect, Qt.AlignCenter, text)

            x += tw + 4

        # Draw commit message text
        msg = row_data.commit.message.splitlines()[0] if row_data.commit.message else ""
        text_rect = QRectF(x, rect.y(), rect.width() - (x - rect.x()) - 4, rect.height())
        painter.setFont(option.font)
        painter.setPen(
            QPen(
                option.palette.highlightedText().color()
                if is_selected
                else option.palette.text().color()
            )
        )
        painter.drawText(text_rect, Qt.AlignLeft | Qt.AlignVCenter, msg)

        painter.restore()


class CommitTableModel(QAbstractTableModel):
    """Table model feeding GraphRows to QTableView."""

    COLUMNS = ["Graph", "Message", "Author", "Date", "SHA"]

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._rows: list[GraphRow] = []

    def set_rows(self, rows: list[GraphRow]):
        self.beginResetModel()
        self._rows = rows
        self.endResetModel()

    def rowCount(self, parent: QModelIndex | None = None) -> int:
        return len(self._rows)

    def columnCount(self, parent: QModelIndex | None = None) -> int:
        return len(self.COLUMNS)

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.DisplayRole):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return self.COLUMNS[section]
        return None

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):
        if not index.isValid() or not (0 <= index.row() < len(self._rows)):
            return None

        row = self._rows[index.row()]
        col = index.column()

        if role == Qt.UserRole:
            return row

        if role == Qt.DisplayRole:
            if col == 0:
                return ""
            elif col == 1:
                return row.commit.message.splitlines()[0] if row.commit.message else ""
            elif col == 2:
                return row.commit.author_name
            elif col == 3:
                # Truncate ISO date to readable string
                return row.commit.author_date[:19].replace("T", " ")
            elif col == 4:
                return row.commit.sha[:8]

        return None


class CommitGraphWidget(QTableView):
    """High-performance commit graph view with infinite scroll and custom rendering."""

    commit_selected = Signal(object)  # emits Commit or None
    rebase_requested = Signal(str)  # emits target sha/ref
    merge_requested = Signal(str)  # emits source sha/ref
    create_branch_requested = Signal(str)
    create_tag_requested = Signal(str)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._repo: RepoHandle | None = None
        self._all_commits: list[Commit] = []
        self._all_refs_mode: bool = True
        self._filter: LogFilter | None = None
        self._is_loading_batch: bool = False
        self._has_more: bool = True
        self._offset: int = 0
        self._batch_size: int = 100

        self._model = CommitTableModel(self)
        self.setModel(self._model)

        self._graph_delegate = GraphItemDelegate(self)
        self._ref_delegate = RefLabelDelegate(self)
        self.setItemDelegateForColumn(0, self._graph_delegate)
        self.setItemDelegateForColumn(1, self._ref_delegate)

        self._init_ui()

    def _init_ui(self):
        self.setSelectionBehavior(QTableView.SelectRows)
        self.setSelectionMode(QTableView.SingleSelection)
        self.verticalHeader().setDefaultSectionSize(ROW_HEIGHT)
        self.verticalHeader().setVisible(False)
        self.setShowGrid(False)
        self.setAlternatingRowColors(True)

        header = self.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Interactive)
        header.resizeSection(0, 80)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.Interactive)
        header.resizeSection(2, 140)
        header.setSectionResizeMode(3, QHeaderView.Interactive)
        header.resizeSection(3, 140)
        header.setSectionResizeMode(4, QHeaderView.Interactive)
        header.resizeSection(4, 90)

        self.selectionModel().selectionChanged.connect(self._on_selection_changed)
        self.verticalScrollBar().valueChanged.connect(self._on_scroll)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)

    def set_repo(self, repo: RepoHandle | None):
        self._repo = repo
        self.reload_commits()

    def set_all_refs_mode(self, all_refs: bool):
        if self._all_refs_mode != all_refs:
            self._all_refs_mode = all_refs
            self.reload_commits()

    def apply_filter(self, log_filter: LogFilter | None):
        self._filter = log_filter
        self.reload_commits()

    def reload_commits(self):
        self._all_commits = []
        self._offset = 0
        self._has_more = True
        self._fetch_next_batch()

    def _fetch_next_batch(self):
        if not self._repo or self._is_loading_batch or not self._has_more:
            return

        self._is_loading_batch = True
        try:
            new_commits = engine.get_log(
                self._repo,
                filter=self._filter,
                limit=self._batch_size,
                offset=self._offset,
                all_refs=self._all_refs_mode,
            )
            if len(new_commits) < self._batch_size:
                self._has_more = False

            self._all_commits.extend(new_commits)
            self._offset += len(new_commits)

            ref_labels = engine.get_ref_labels(self._repo)
            rows = compute_graph_layout(self._all_commits, ref_labels)
            self._model.set_rows(rows)

            # Adjust column 0 width based on maximum lanes
            max_lanes = max((r.lane_index for r in rows), default=0) + 1
            calculated_width = max(60, 20 + max_lanes * LANE_WIDTH)
            self.horizontalHeader().resizeSection(0, calculated_width)

            if rows and not self.selectionModel().hasSelection():
                self.selectRow(0)

        except Exception as e:
            logger.exception("Failed to fetch commit batch: %s", e)
        finally:
            self._is_loading_batch = False

    def _on_scroll(self, value: int):
        max_val = self.verticalScrollBar().maximum()
        if max_val > 0 and value >= max_val - 20:
            self._fetch_next_batch()

    def _on_selection_changed(self):
        selected_indexes = self.selectionModel().selectedRows()
        if not selected_indexes:
            self.commit_selected.emit(None)
            return

        row_idx = selected_indexes[0].row()
        if 0 <= row_idx < len(self._model._rows):
            commit = self._model._rows[row_idx].commit
            self.commit_selected.emit(commit)

    def _show_context_menu(self, pos):
        index = self.indexAt(pos)
        if not index.isValid() or not (0 <= index.row() < len(self._model._rows)):
            return

        row_data = self._model._rows[index.row()]
        commit = row_data.commit

        menu = QMenu(self)
        copy_action = menu.addAction(f"Copy SHA ({commit.sha[:8]})")
        menu.addSeparator()
        create_branch_act = menu.addAction("Create Branch Here...")
        create_tag_act = menu.addAction("Create Tag Here...")
        menu.addSeparator()
        merge_act = menu.addAction(f"Merge '{commit.sha[:8]}' into current branch...")
        rebase_act = menu.addAction(f"Rebase current branch onto '{commit.sha[:8]}'...")

        action = menu.exec(self.viewport().mapToGlobal(pos))
        if action == copy_action:
            cb = QGuiApplication.clipboard()
            if cb:
                cb.setText(commit.sha)
        elif action == create_branch_act:
            self.create_branch_requested.emit(commit.sha)
        elif action == create_tag_act:
            self.create_tag_requested.emit(commit.sha)
        elif action == merge_act:
            self.merge_requested.emit(commit.sha)
        elif action == rebase_act:
            self.rebase_requested.emit(commit.sha)
