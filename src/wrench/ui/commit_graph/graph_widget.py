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
    QScrollBar,
    QStyle,
    QStyledItemDelegate,
    QTableView,
    QWidget,
)

from wrench.core import engine
from wrench.core.engine import Commit, LogFilter, RepoHandle
from wrench.ui.commit_graph.layout import (
    GRAPH_COLORS,
    ConnectorKind,
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
        painter.setClipRect(option.rect)

        graph_scroll_x = getattr(self.parent(), "_graph_scroll_x", 0)

        rect = option.rect
        x_offset = rect.x() + 10 - graph_scroll_x
        y_center = rect.y() + rect.height() / 2.0
        y_top = float(rect.y())
        y_bottom = float(rect.y() + rect.height())

        lane_idx = row_data.lane_index
        node_color = QColor(row_data.node_color)

        # 1. Paint vertical pass-through rails for other active lanes
        active_lane_colors = getattr(row_data, "active_lane_colors", None) or [
            (lane_num, GRAPH_COLORS[lane_num % len(GRAPH_COLORS)])
            for lane_num in row_data.active_lanes
        ]
        for active_lane, color_hex in active_lane_colors:
            if active_lane != lane_idx:
                rail_color = QColor(color_hex)
                painter.setPen(QPen(rail_color, 2.0))
                lx = x_offset + active_lane * LANE_WIDTH
                painter.drawLine(QPointF(lx, y_top), QPointF(lx, y_bottom))

        # 2. Paint incoming/outgoing connectors (directional smooth cubic S-curves)
        for conn in row_data.connectors:
            conn_color = QColor(conn.color)
            painter.setPen(QPen(conn_color, 2.0))
            painter.setBrush(Qt.NoBrush)

            x_from = x_offset + conn.from_lane * LANE_WIDTH
            x_to = x_offset + conn.to_lane * LANE_WIDTH
            conn_kind = getattr(conn, "kind", ConnectorKind.MERGE_UP)

            path = QPainterPath()

            if conn_kind == ConnectorKind.FORK_DOWN:
                # Leaves node at y_center downward, enters parent rail at y_bottom
                path.moveTo(x_from, y_center)
                dy = y_bottom - y_center
                c1 = QPointF(x_from, y_center + dy * 0.5)
                c2 = QPointF(x_to, y_bottom - dy * 0.5)
                path.cubicTo(c1, c2, QPointF(x_to, y_bottom))
            elif conn_kind == ConnectorKind.JOIN_TOP:
                # Enters from y_top downward, joins commit node at y_center
                path.moveTo(x_from, y_top)
                dy = y_center - y_top
                c1 = QPointF(x_from, y_top + dy * 0.5)
                c2 = QPointF(x_to, y_center - dy * 0.5)
                path.cubicTo(c1, c2, QPointF(x_to, y_center))
            else:  # MERGE_UP
                # Leaves branch rail at y_bottom upward, enters merge node at y_center
                path.moveTo(x_from, y_bottom)
                dy = y_bottom - y_center
                c1 = QPointF(x_from, y_bottom - dy * 0.5)
                c2 = QPointF(x_to, y_center + dy * 0.5)
                path.cubicTo(c1, c2, QPointF(x_to, y_center))

            painter.drawPath(path)

        # 3. Paint top-half and bottom-half rail for the occupied lane
        painter.setPen(QPen(node_color, 2.0))
        node_x = x_offset + lane_idx * LANE_WIDTH

        # Top-half rail (only if this lane was active/expected from row above)
        if getattr(row_data, "has_top_rail", True):
            painter.drawLine(QPointF(node_x, y_top), QPointF(node_x, y_center))

        # Bottom-half rail (if this lane continues straight down to parents)
        if row_data.commit.parent_shas:
            has_deflecting_fork = any(
                conn.from_lane == lane_idx
                and conn.to_lane != lane_idx
                and getattr(conn, "kind", ConnectorKind.MERGE_UP) == ConnectorKind.FORK_DOWN
                for conn in row_data.connectors
            )
            if not has_deflecting_fork:
                painter.drawLine(QPointF(node_x, y_center), QPointF(node_x, y_bottom))

        is_selected = bool(option.state & QStyle.StateFlag.State_Selected)

        # 4. Paint selected node halo glow
        if is_selected:
            halo_r = NODE_RADIUS + 3.0
            halo_brush = QBrush(QColor(node_color.red(), node_color.green(), node_color.blue(), 80))
            painter.setPen(QPen(QColor(255, 255, 255, 220), 1.8))
            painter.setBrush(halo_brush)
            painter.drawEllipse(QPointF(node_x, y_center), halo_r, halo_r)

        # 5. Paint commit node circle
        painter.setPen(QPen(node_color.darker(120), 1.5))
        painter.setBrush(QBrush(node_color))

        is_merge = len(row_data.commit.parent_shas) > 1
        r = NODE_RADIUS + (1.0 if is_merge else 0.0)
        painter.drawEllipse(QPointF(node_x, y_center), r, r)

        if is_merge:
            # Draw inner white dot for merge commits
            painter.setBrush(QBrush(Qt.white))
            painter.drawEllipse(QPointF(node_x, y_center), 1.5, 1.5)
        elif is_selected:
            # High-contrast center dot for selected regular commit
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
        painter.setClipRect(option.rect)

        # Draw selection background or solid row background to prevent bleed
        is_selected = bool(option.state & QStyle.StateFlag.State_Selected)
        if is_selected:
            painter.fillRect(option.rect, option.palette.highlight())
        else:
            bg_brush = (
                option.palette.alternateBase() if (index.row() % 2 == 1) else option.palette.base()
            )
            painter.fillRect(option.rect, bg_brush)

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

        if role == Qt.ToolTipRole:

            if col == 0:
                msg_first = row.commit.message.splitlines()[0] if row.commit.message else ""
                return (
                    f"{msg_first} ({row.commit.sha[:8]})"
                    if msg_first
                    else (row.commit.sha[:8] if row.commit.sha else None)
                )
            elif col == 1:
                if not row.commit.message:
                    return None
                msg = row.commit.message.strip()
                if len(msg) > 2000:
                    msg = msg[:2000] + "\n\n... [message truncated]"
                if row.ref_labels:
                    badges = " ".join(f"[{lbl.name}]" for lbl in row.ref_labels)
                    return f"{badges}\n\n{msg}"
                return msg
            elif col == 2:
                if row.commit.author_name and row.commit.author_email:
                    return f"{row.commit.author_name} <{row.commit.author_email}>"
                return row.commit.author_name or None
            elif col == 3:
                return f"Committed: {row.commit.author_date}" if row.commit.author_date else None
            elif col == 4:
                return f"Commit SHA: {row.commit.sha}" if row.commit.sha else None

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
    graph_scroll_changed = Signal(int, int)  # emits (current_scroll_x, max_scroll_x)

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
        self._is_initial_load: bool = True

        self._graph_scroll_x: int = 0
        self._max_graph_scroll_x: int = 0

        self._model = CommitTableModel(self)
        self.setModel(self._model)

        self._graph_delegate = GraphItemDelegate(self)
        self._ref_delegate = RefLabelDelegate(self)
        self.setItemDelegateForColumn(0, self._graph_delegate)
        self.setItemDelegateForColumn(1, self._ref_delegate)

        self._init_ui()

    @property
    def graph_scrollbar(self) -> QScrollBar:
        """Exposes the internal graph column horizontal scrollbar."""
        return self._graph_scrollbar

    def _init_ui(self):
        self.setSelectionBehavior(QTableView.SelectRows)
        self.setSelectionMode(QTableView.SingleSelection)
        self.verticalHeader().setDefaultSectionSize(ROW_HEIGHT)
        self.verticalHeader().setVisible(False)
        self.setShowGrid(False)
        self.setAlternatingRowColors(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)

        # Graph column dedicated scrollbar (sharing exact same style as main horizontal scrollbar)
        self._graph_scrollbar = QScrollBar(Qt.Horizontal, self)
        bar_h = self.horizontalScrollBar().sizeHint().height() or 12
        self._graph_scrollbar.setFixedHeight(bar_h)
        self._graph_scrollbar.valueChanged.connect(self.set_graph_scroll_x)
        self._graph_scrollbar.setToolTip(self.tr("Graph lane horizontal pan (or Shift+Scroll)"))
        self._graph_scrollbar.setVisible(False)

        header = self.horizontalHeader()
        header.setMinimumSectionSize(60)
        header.setSectionResizeMode(0, QHeaderView.Interactive)
        header.resizeSection(0, 100)
        header.setSectionResizeMode(1, QHeaderView.Interactive)
        header.resizeSection(1, 300)
        header.setSectionResizeMode(2, QHeaderView.Interactive)
        header.resizeSection(2, 140)
        header.setSectionResizeMode(3, QHeaderView.Interactive)
        header.resizeSection(3, 140)
        header.setSectionResizeMode(4, QHeaderView.Interactive)
        header.resizeSection(4, 90)
        header.setStretchLastSection(False)

        header.sectionResized.connect(self._on_section_resized)
        self.selectionModel().selectionChanged.connect(self._on_selection_changed)
        self.verticalScrollBar().valueChanged.connect(self._on_scroll)
        self.verticalScrollBar().valueChanged.connect(self._update_graph_scrollbar_geom)
        self.horizontalScrollBar().valueChanged.connect(self._update_graph_scrollbar_geom)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)

    def bind_horizontal_scrollbar(self, scrollbar: QScrollBar) -> None:
        """Backwards compatibility hook for external scrollbar binding."""
        scrollbar.valueChanged.connect(self.set_graph_scroll_x)
        self.graph_scroll_changed.connect(
            lambda cur, max_val: (
                scrollbar.blockSignals(True),
                scrollbar.setRange(0, max_val),
                scrollbar.setValue(cur),
                scrollbar.setVisible(max_val > 0),
                scrollbar.blockSignals(False),
            )
        )

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_graph_scrollbar_geom()

    def _update_graph_scrollbar_geom(self) -> None:
        if not hasattr(self, "_graph_scrollbar") or not self._graph_scrollbar:
            return
        col_0_width = self.horizontalHeader().sectionSize(0)
        col_0_x = self.horizontalHeader().sectionPosition(0) - self.horizontalScrollBar().value()

        h_scroll_h = (
            self.horizontalScrollBar().height() if self.horizontalScrollBar().isVisible() else 0
        )
        v_scroll_w = self.verticalScrollBar().width() if self.verticalScrollBar().isVisible() else 0

        bar_h = self.horizontalScrollBar().sizeHint().height() or 12
        self._graph_scrollbar.setFixedHeight(bar_h)
        y = max(0, self.height() - h_scroll_h - bar_h)

        actual_x = max(0, col_0_x)
        max_w = self.width() - v_scroll_w - actual_x
        actual_w = max(0, min(col_0_width - (actual_x - col_0_x), max_w))
        self._graph_scrollbar.setGeometry(actual_x, y, actual_w, bar_h)
        self._graph_scrollbar.setVisible(self._max_graph_scroll_x > 0 and actual_w > 10)
        self._graph_scrollbar.raise_()

    def set_graph_scroll_x(self, val: int) -> None:
        """Sets horizontal scroll offset in pixels and repaints graph column."""
        clamped = max(0, min(val, self._max_graph_scroll_x))
        if clamped != self._graph_scroll_x:
            self._graph_scroll_x = clamped
            if self._graph_scrollbar.value() != clamped:
                self._graph_scrollbar.blockSignals(True)
                if self._graph_scrollbar.maximum() != self._max_graph_scroll_x:
                    self._graph_scrollbar.setRange(0, self._max_graph_scroll_x)
                self._graph_scrollbar.setValue(clamped)
                self._graph_scrollbar.blockSignals(False)
            self.viewport().update()
            self.graph_scroll_changed.emit(self._graph_scroll_x, self._max_graph_scroll_x)

    def _on_section_resized(self, logical_index: int, old_size: int, new_size: int) -> None:
        if logical_index == 0:
            self._update_scrollbar_range()
        self._update_graph_scrollbar_geom()

    def _update_scrollbar_range(self) -> None:
        col_0_width = self.horizontalHeader().sectionSize(0)
        if not self._model._rows:
            self._max_graph_scroll_x = 0
        else:
            max_lane = max(
                (max(r.active_lanes, default=0) for r in self._model._rows),
                default=0,
            )
            max_graph_width = 10 + (max_lane + 1) * LANE_WIDTH + 30
            self._max_graph_scroll_x = max(0, max_graph_width - col_0_width)

        self._graph_scroll_x = max(0, min(self._graph_scroll_x, self._max_graph_scroll_x))

        self._graph_scrollbar.blockSignals(True)
        self._graph_scrollbar.setRange(0, self._max_graph_scroll_x)
        self._graph_scrollbar.setValue(self._graph_scroll_x)
        self._graph_scrollbar.setPageStep(col_0_width)
        self._graph_scrollbar.setSingleStep(LANE_WIDTH)
        self._graph_scrollbar.blockSignals(False)

        self._update_graph_scrollbar_geom()
        self.graph_scroll_changed.emit(self._graph_scroll_x, self._max_graph_scroll_x)

    def _auto_scroll_to_node(self, lane_index: int) -> None:
        """Pans the graph horizontally with hysteresis deadzone to make node visible."""
        col_width = self.horizontalHeader().sectionSize(0)
        node_x = 10 + lane_index * LANE_WIDTH
        screen_x = node_x - self._graph_scroll_x

        left_threshold = 24
        right_threshold = col_width - 32

        target_scroll = self._graph_scroll_x
        if screen_x > right_threshold:
            target_scroll = node_x - (col_width // 2)
        elif screen_x < left_threshold:
            target_scroll = max(0, node_x - 32)

        self.set_graph_scroll_x(target_scroll)

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
        self._is_initial_load = True
        self._all_commits = []
        self._offset = 0
        self._has_more = True
        self._fetch_next_batch()

    def _fetch_next_batch(self):
        if not self._repo or self._is_loading_batch or not self._has_more:
            return

        self._is_loading_batch = True
        scroll_pos = self.verticalScrollBar().value()
        selected_rows = [i.row() for i in self.selectionModel().selectedRows()]

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
            self._update_scrollbar_range()

            if self._is_initial_load:
                self._is_initial_load = False
                if rows and not self.selectionModel().hasSelection():
                    self.selectRow(0)
            else:
                # Maintain smooth continuous scrolling and preserve selection across batch fetches
                self.verticalScrollBar().setValue(scroll_pos)
                if selected_rows:
                    target_row = selected_rows[0]
                    if target_row < len(rows):
                        self.selectionModel().blockSignals(True)
                        self.selectRow(target_row)
                        self.selectionModel().blockSignals(False)

        except Exception as e:
            logger.exception("Failed to fetch commit batch: %s", e)
        finally:
            self._is_loading_batch = False

    def _on_scroll(self, value: int):
        max_val = self.verticalScrollBar().maximum()
        if max_val > 0 and value >= max_val - 20:
            self._fetch_next_batch()

    def wheelEvent(self, event):
        """Allows horizontal Shift+Wheel or trackpad horizontal pan over Column 0."""
        cursor_col = self.columnAt(int(event.position().x()))
        is_over_graph = cursor_col == 0

        is_shift = bool(event.modifiers() & Qt.ShiftModifier)
        h_delta = event.pixelDelta().x() if event.pixelDelta().x() != 0 else event.angleDelta().x()
        v_delta = event.pixelDelta().y() if event.pixelDelta().y() != 0 else event.angleDelta().y()

        if is_over_graph and (is_shift or h_delta != 0) and self._max_graph_scroll_x > 0:
            step = -h_delta if h_delta != 0 else -v_delta
            self.set_graph_scroll_x(self._graph_scroll_x + step // 2)
            event.accept()
            return

        super().wheelEvent(event)

    def _on_selection_changed(self):
        selected_indexes = self.selectionModel().selectedRows()
        if not selected_indexes:
            self.commit_selected.emit(None)
            return

        row_idx = selected_indexes[0].row()
        if 0 <= row_idx < len(self._model._rows):
            row_data = self._model._rows[row_idx]
            self.commit_selected.emit(row_data.commit)
            self._auto_scroll_to_node(row_data.lane_index)

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
