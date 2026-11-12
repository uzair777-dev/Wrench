"""FR-2.2: Commit graph table widget with custom QStyledItemDelegate."""

from __future__ import annotations

import logging
import math
import weakref
from pathlib import Path
from typing import Any

import shiboken6
from PySide6.QtCore import (
    QAbstractTableModel,
    QCoreApplication,
    QEvent,
    QModelIndex,
    QObject,
    QPointF,
    QRect,
    QRectF,
    QRunnable,
    Qt,
    QThreadPool,
    Signal,
    Slot,
)
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QFontMetricsF,
    QGuiApplication,
    QPainter,
    QPainterPath,
    QPaintEvent,
    QPen,
    QPixmap,
    QPixmapCache,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QMenu,
    QScrollBar,
    QStyle,
    QStyledItemDelegate,
    QTableView,
    QWidget,
)

from wrench.core import engine
from wrench.core.engine import Commit, LogFilter, LogPage, RefLabel, RepoHandle
from wrench.storage.settings_registry import SettingsRegistry, peek_settings_registry
from wrench.ui.commit_graph.layout import (
    GRAPH_COLORS,
    ConnectorKind,
    GraphLayoutState,
    GraphRow,
    Lane,
    compute_graph_layout_step,
    matches_filter,
)
from wrench.ui.theme import get_ref_badge_qcolor, is_dark_theme
from wrench.ui.widgets.avatar import get_avatar_loader, resolve_author_avatar_url

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
        x = float(rect.x() + 4)
        y_center = rect.y() + rect.height() / 2.0

        badge_font = QFont(option.font)
        if badge_font.pointSize() > 0:
            badge_font.setPointSize(max(7, badge_font.pointSize() - 2))
            font_sz_key = f"pt{badge_font.pointSize()}"
        else:
            px = badge_font.pixelSize()
            badge_font.setPixelSize(max(9, px - 2) if px > 0 else 10)
            font_sz_key = f"px{badge_font.pixelSize()}"
        badge_font.setBold(True)

        parent_w = option.widget or self.parent()
        dpr = (
            max(1.0, float(parent_w.devicePixelRatioF()))
            if parent_w is not None and hasattr(parent_w, "devicePixelRatioF")
            else 1.0
        )
        epoch = getattr(self.parent(), "_paint_cache_epoch", 0)
        is_dark = is_dark_theme(option.palette)
        metrics = QFontMetricsF(badge_font)

        # Draw ref labels using DPR-scaled QPixmapCache
        for label in row_data.ref_labels:
            text = label.name
            cache_key = (
                f"wrench:refpill:{label.kind}:{text}:{int(is_dark)}:"
                f"{font_sz_key}:{dpr:.2f}:{epoch}"
            )
            pm = QPixmapCache.find(cache_key)
            if pm is None or pm.isNull():
                tw = metrics.horizontalAdvance(text) + 8.0
                th = metrics.height() + 2.0
                phys_w = max(1, math.ceil(tw * dpr))
                phys_h = max(1, math.ceil(th * dpr))
                pm = QPixmap(phys_w, phys_h)
                pm.setDevicePixelRatio(dpr)
                pm.fill(Qt.GlobalColor.transparent)

                pill_painter = QPainter(pm)
                pill_painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
                pill_painter.setFont(badge_font)
                bg = get_ref_badge_qcolor(label.kind, is_dark)
                pill_painter.setPen(Qt.PenStyle.NoPen)
                pill_painter.setBrush(QBrush(bg))
                pill_painter.drawRoundedRect(QRectF(0.0, 0.0, tw, th), 3.0, 3.0)
                pill_painter.setPen(QPen(Qt.GlobalColor.white))
                pill_painter.drawText(
                    QRectF(0.0, 0.0, tw, th),
                    Qt.AlignmentFlag.AlignCenter,
                    text,
                )
                pill_painter.end()
                QPixmapCache.insert(cache_key, pm)
            else:
                tw = pm.width() / dpr
                th = pm.height() / dpr

            painter.drawPixmap(QPointF(x, y_center - th / 2.0), pm)
            x += tw + 4.0

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
        self._remote_urls: list[str] = []
        self._conn = None
        self._max_active_lane: int = 0
        self._paint_cache_epoch: int = 0
        self._avatar_url_cache: dict[tuple[str, str, tuple[str, ...]], str | None] = {}

    @staticmethod
    def _row_max_lane(row: GraphRow) -> int:
        max_lane = row.lane_index
        if row.active_lanes:
            max_lane = max(max_lane, max(row.active_lanes))
        return max_lane

    @property
    def max_active_lane(self) -> int:
        """Return maximum column lane index in O(1)."""
        return self._max_active_lane

    def set_rows(self, rows: list[GraphRow]):
        self.beginResetModel()
        self._rows = list(rows)
        self._avatar_url_cache.clear()
        self._max_active_lane = max((self._row_max_lane(r) for r in self._rows), default=0)
        self.endResetModel()

    def append_rows(self, new_rows: list[GraphRow]) -> None:
        """Append incremental graph rows without resetting viewport scroll or selection."""
        if not new_rows:
            return
        first = len(self._rows)
        last = first + len(new_rows) - 1
        self.beginInsertRows(QModelIndex(), first, last)
        self._rows.extend(new_rows)
        for row in new_rows:
            row_max = self._row_max_lane(row)
            if row_max > self._max_active_lane:
                self._max_active_lane = row_max
        self.endInsertRows()

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

        if role == Qt.DecorationRole and col == 2:
            is_dark = False
            dpr = 1.0
            epoch = self._paint_cache_epoch
            parent_widget = self.parent()
            if parent_widget is not None:
                is_dark = is_dark_theme(parent_widget)
                if hasattr(parent_widget, "devicePixelRatioF"):
                    dpr = max(1.0, float(parent_widget.devicePixelRatioF()))
                epoch = getattr(parent_widget, "_paint_cache_epoch", epoch)
            remote_urls = getattr(self, "_remote_urls", None)
            db_conn = getattr(self, "_conn", None)
            author_label = row.commit.author_name or row.commit.author_email or "?"
            url_cache_key = (
                row.commit.author_name or "",
                row.commit.author_email or "",
                tuple(remote_urls or ()),
            )
            if url_cache_key in self._avatar_url_cache:
                url = self._avatar_url_cache[url_cache_key]
            else:
                url = resolve_author_avatar_url(
                    row.commit.author_name,
                    row.commit.author_email,
                    remote_urls=remote_urls,
                    db_conn=db_conn,
                )
                self._avatar_url_cache[url_cache_key] = url
            avatar_key_id = url or f"{row.commit.author_name}|{row.commit.author_email}"
            cache_key = f"wrench:avatar:{avatar_key_id}:{int(is_dark)}:18:{dpr:.2f}:{epoch}"
            cached_pm = QPixmapCache.find(cache_key)
            if cached_pm is not None and not cached_pm.isNull():
                return cached_pm
            pm = get_avatar_loader().get_avatar(
                url,
                author_label,
                size=18,
                is_dark=is_dark,
            )
            if pm is not None and not pm.isNull():
                QPixmapCache.insert(cache_key, pm)
            return pm

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


class _GraphWorkerDispatcher(QObject):
    """Application-lifetime queued dispatcher routing graph worker callbacks to live widgets."""

    page_ready = Signal(object, int, object, object, object)
    page_failed = Signal(object, int, str)
    search_ready = Signal(object, int, object, object, object)
    search_failed = Signal(object, int, str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.page_ready.connect(self._deliver_page_ready, Qt.ConnectionType.QueuedConnection)
        self.page_failed.connect(self._deliver_page_failed, Qt.ConnectionType.QueuedConnection)
        self.search_ready.connect(self._deliver_search_ready, Qt.ConnectionType.QueuedConnection)
        self.search_failed.connect(self._deliver_search_failed, Qt.ConnectionType.QueuedConnection)

    @Slot(object, int, object, object, object)
    def _deliver_page_ready(
        self,
        widget_ref: Any,
        generation_id: int,
        page: Any,
        rows: Any,
        next_state: Any,
    ) -> None:
        widget = widget_ref() if callable(widget_ref) else None
        if widget is not None and shiboken6.isValid(widget):
            widget._on_page_ready(generation_id, page, rows, next_state)

    @Slot(object, int, str)
    def _deliver_page_failed(self, widget_ref: Any, generation_id: int, error_msg: str) -> None:
        widget = widget_ref() if callable(widget_ref) else None
        if widget is not None and shiboken6.isValid(widget):
            widget._on_page_failed(generation_id, error_msg)

    @Slot(object, int, object, object, object)
    def _deliver_search_ready(
        self,
        widget_ref: Any,
        generation_id: int,
        page: Any,
        rows: Any,
        next_state: Any,
    ) -> None:
        widget = widget_ref() if callable(widget_ref) else None
        if widget is not None and shiboken6.isValid(widget):
            widget._on_search_ready(generation_id, page, rows, next_state)

    @Slot(object, int, str)
    def _deliver_search_failed(self, widget_ref: Any, generation_id: int, error_msg: str) -> None:
        widget = widget_ref() if callable(widget_ref) else None
        if widget is not None and shiboken6.isValid(widget):
            widget._on_search_failed(generation_id, error_msg)


_graph_worker_dispatcher: _GraphWorkerDispatcher | None = None


def _get_graph_dispatcher() -> _GraphWorkerDispatcher:
    global _graph_worker_dispatcher
    if _graph_worker_dispatcher is None or not shiboken6.isValid(_graph_worker_dispatcher):
        _graph_worker_dispatcher = _GraphWorkerDispatcher(parent=QCoreApplication.instance())
    return _graph_worker_dispatcher


class _GraphPageWorker(QRunnable):
    """Fetch and lay out a single page of commits on a background thread."""

    def __init__(
        self,
        *,
        generation_id: int,
        repo_path: Path,
        log_filter: LogFilter | None,
        limit: int,
        cursor_sha: str | None,
        all_refs: bool,
        ref_labels: dict[str, list[RefLabel]],
        layout_state: GraphLayoutState,
        widget_ref: weakref.ref[CommitGraphWidget],
        dispatcher: _GraphWorkerDispatcher,
    ) -> None:
        super().__init__()
        self._generation_id = generation_id
        self._repo_path = repo_path
        self._log_filter = log_filter
        self._limit = limit
        self._cursor_sha = cursor_sha
        self._all_refs = all_refs
        self._ref_labels = ref_labels
        self._layout_state = layout_state
        self._widget_ref = widget_ref
        self._dispatcher = dispatcher
        self.setAutoDelete(True)

    def run(self) -> None:
        if self._widget_ref() is None:
            return
        try:
            worker_repo = RepoHandle(self._repo_path)
            page = engine.get_log_page(
                worker_repo,
                filter=self._log_filter,
                limit=self._limit,
                cursor_sha=self._cursor_sha,
                all_refs=self._all_refs,
            )
            rows, next_state = compute_graph_layout_step(
                list(page.commits),
                ref_labels=self._ref_labels,
                state=self._layout_state,
            )
            if self._widget_ref() is not None and shiboken6.isValid(self._dispatcher):
                self._dispatcher.page_ready.emit(
                    self._widget_ref, self._generation_id, page, rows, next_state
                )
        except Exception as exc:
            logger.exception("Background commit graph page load failed: %s", exc)
            if self._widget_ref() is not None and shiboken6.isValid(self._dispatcher):
                self._dispatcher.page_failed.emit(self._widget_ref, self._generation_id, str(exc))


class _GraphSearchWorker(QRunnable):
    """Run initial filtered commit search page on a background thread."""

    def __init__(
        self,
        *,
        generation_id: int,
        repo_path: Path,
        log_filter: LogFilter | None,
        limit: int,
        all_refs: bool,
        ref_labels: dict[str, list[RefLabel]],
        widget_ref: weakref.ref[CommitGraphWidget],
        dispatcher: _GraphWorkerDispatcher,
    ) -> None:
        super().__init__()
        self._generation_id = generation_id
        self._repo_path = repo_path
        self._log_filter = log_filter
        self._limit = limit
        self._all_refs = all_refs
        self._ref_labels = ref_labels
        self._widget_ref = widget_ref
        self._dispatcher = dispatcher
        self.setAutoDelete(True)

    def run(self) -> None:
        if self._widget_ref() is None:
            return
        try:
            worker_repo = RepoHandle(self._repo_path)
            page = engine.get_log_page(
                worker_repo,
                filter=self._log_filter,
                limit=self._limit,
                cursor_sha=None,
                all_refs=self._all_refs,
            )
            rows, next_state = compute_graph_layout_step(
                list(page.commits),
                ref_labels=self._ref_labels,
                state=GraphLayoutState(),
            )
            if self._widget_ref() is not None and shiboken6.isValid(self._dispatcher):
                self._dispatcher.search_ready.emit(
                    self._widget_ref, self._generation_id, page, rows, next_state
                )
        except Exception as exc:
            logger.exception("Background commit graph search failed: %s", exc)
            if self._widget_ref() is not None and shiboken6.isValid(self._dispatcher):
                self._dispatcher.search_failed.emit(self._widget_ref, self._generation_id, str(exc))


class CommitGraphWidget(QTableView):
    """High-performance commit graph view with infinite scroll and custom rendering."""

    commit_selected = Signal(object)  # emits Commit or None
    rebase_requested = Signal(str)  # emits target sha/ref
    interactive_rebase_requested = Signal(str)  # emits base sha
    merge_requested = Signal(str)  # emits source sha/ref
    create_branch_requested = Signal(str)
    create_tag_requested = Signal(str)
    graph_scroll_changed = Signal(int, int)  # emits (current_scroll_x, max_scroll_x)

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        settings_registry: SettingsRegistry | None = None,
    ):
        super().__init__(parent)
        self._repo: RepoHandle | None = None
        self._all_commits: list[Commit] = []
        self._cached_unfiltered_commits: list[Commit] = []
        self._ref_labels_cache: dict[str, list[RefLabel]] = {}
        self._layout_state: GraphLayoutState = GraphLayoutState()
        self._all_refs_mode: bool = True
        self._filter: LogFilter | None = None
        self._is_loading_batch: bool = False
        self._has_more: bool = True
        self._all_history_in_memory: bool = False
        self._cursor_sha: str | None = None
        self._offset: int = 0
        self._batch_size: int = 500
        self._is_initial_load: bool = True

        self._page_generation_id: int = 0
        self._search_generation_id: int = 0
        self._paint_cache_epoch: int = 0
        self._last_painted_row_range: tuple[int, int] = (0, 0)

        self._settings_registry: SettingsRegistry | None = settings_registry
        self._connected_registry: SettingsRegistry | None = None

        self._graph_scroll_x: int = 0
        self._max_graph_scroll_x: int = 0

        self._model = CommitTableModel(self)
        self.setModel(self._model)

        self._graph_delegate = GraphItemDelegate(self)
        self._ref_delegate = RefLabelDelegate(self)
        self.setItemDelegateForColumn(0, self._graph_delegate)
        self.setItemDelegateForColumn(1, self._ref_delegate)

        self._init_ui()
        self._ensure_registry_connection()
        self._avatar_loader_connected: bool = False
        get_avatar_loader().avatar_ready.connect(self._on_avatar_ready)
        self._avatar_loader_connected = True

    def closeEvent(self, event) -> None:
        self._page_generation_id += 1
        self._search_generation_id += 1
        self._is_loading_batch = False
        if hasattr(self, "_model") and shiboken6.isValid(self._model):
            self._model._avatar_url_cache.clear()
        self._disconnect_avatar_loader()
        self._disconnect_registry()
        super().closeEvent(event)

    def _disconnect_avatar_loader(self, *_) -> None:
        if not getattr(self, "_avatar_loader_connected", False):
            return
        self._avatar_loader_connected = False
        try:
            get_avatar_loader().avatar_ready.disconnect(self._on_avatar_ready)
        except RuntimeError, TypeError:
            pass

    def _ensure_registry_connection(self) -> None:
        reg = self._settings_registry or peek_settings_registry()
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
        if key == "performance.graph_page_size":
            self._batch_size = self._effective_page_size()

    def set_settings_registry(self, registry: SettingsRegistry | None) -> None:
        """Bind or update the SettingsRegistry driving commit-graph page size."""
        self._settings_registry = registry
        self._ensure_registry_connection()
        self._batch_size = self._effective_page_size()

    def _effective_page_size(self) -> int:
        reg = self._settings_registry or peek_settings_registry()
        repo_str = str(self._repo.path) if self._repo else None
        if reg is not None:
            val = reg.get_int("performance.graph_page_size", repo_str)
            if val > 0:
                return max(100, min(5000, int(val)))
        return max(1, int(getattr(self, "_batch_size", 500) or 500))

    def invalidate_paint_caches(self) -> None:
        """Bump paint-cache epoch so pills/avatars re-render for palette or DPR."""
        self._paint_cache_epoch += 1
        self._model._paint_cache_epoch = self._paint_cache_epoch
        self._model._avatar_url_cache.clear()
        if shiboken6.isValid(self) and self.viewport() is not None:
            self.viewport().update()

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() in (
            QEvent.Type.PaletteChange,
            QEvent.Type.ApplicationPaletteChange,
            QEvent.Type.ThemeChange,
            QEvent.Type.StyleChange,
        ):
            self.invalidate_paint_caches()

    def paintEvent(self, event: QPaintEvent) -> None:
        """Clip vertical painting strictly to rows inside the visible viewport bounds."""
        row_count = self._model.rowCount()
        if row_count <= 0:
            self._last_painted_row_range = (0, 0)
            super().paintEvent(event)
            return

        vp_rect = self.viewport().rect()
        ev_rect = event.rect().intersected(vp_rect)
        if ev_rect.isEmpty():
            self._last_painted_row_range = (0, 0)
            return

        top_y = max(0, ev_rect.top())
        bottom_y = max(top_y, min(vp_rect.height() - 1, ev_rect.bottom()))

        raw_first = self.rowAt(top_y)
        raw_last = self.rowAt(bottom_y)
        first_row = 0 if raw_first < 0 else raw_first
        last_row = (row_count - 1) if raw_last < 0 else raw_last

        first_row = max(0, min(first_row, row_count - 1))
        last_row = max(first_row, min(last_row, row_count - 1))
        self._last_painted_row_range = (first_row, last_row + 1)

        if raw_last >= 0:
            y_start = self.rowViewportPosition(first_row)
            y_end = self.rowViewportPosition(last_row) + max(0, self.rowHeight(last_row))
            clipped_top = max(ev_rect.top(), y_start)
            clipped_bottom = min(ev_rect.bottom(), y_end)
            clipped_rect = QRect(
                ev_rect.left(),
                clipped_top,
                ev_rect.width(),
                max(0, clipped_bottom - clipped_top + 1),
            )
            super().paintEvent(QPaintEvent(clipped_rect))
        else:
            # Bottom empty space below last row: keep ev_rect to clear background.
            super().paintEvent(event)

    @Slot(str, int)
    @Slot()
    def _on_avatar_ready(self, _url: str = "", _size: int = 0) -> None:
        try:
            if not shiboken6.isValid(self):
                return
            self.invalidate_paint_caches()
        except RuntimeError, AttributeError:
            pass

    @property
    def graph_scrollbar(self) -> QScrollBar:
        """Exposes the internal graph column horizontal scrollbar."""
        return self._graph_scrollbar

    def _init_ui(self):
        self.setSelectionBehavior(QTableView.SelectRows)
        self.setSelectionMode(QTableView.SingleSelection)
        self.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
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
        header.geometriesChanged.connect(self._update_graph_scrollbar_geom)
        self.selectionModel().selectionChanged.connect(self._on_selection_changed)
        self.verticalScrollBar().valueChanged.connect(self._on_scroll)
        self.verticalScrollBar().valueChanged.connect(self._update_graph_scrollbar_geom)
        self.horizontalScrollBar().valueChanged.connect(self._update_graph_scrollbar_geom)
        self.verticalScrollBar().rangeChanged.connect(self._update_graph_scrollbar_geom)
        self.horizontalScrollBar().rangeChanged.connect(self._update_graph_scrollbar_geom)
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

    def scrollContentsBy(self, dx: int, dy: int) -> None:
        super().scrollContentsBy(dx, dy)
        self._update_graph_scrollbar_geom()

    def _update_graph_scrollbar_geom(self, *args, **kwargs) -> None:
        if not hasattr(self, "_graph_scrollbar") or not self._graph_scrollbar:
            return
        header = self.horizontalHeader()
        col_0_width = header.sectionSize(0)
        col_0_x = self.viewport().x() + header.sectionViewportPosition(0)
        col_0_right = col_0_x + col_0_width

        viewport_left = self.viewport().x()
        viewport_right = self.viewport().x() + self.viewport().width()

        visible_left = max(col_0_x, viewport_left)
        visible_right = min(col_0_right, viewport_right)
        visible_w = max(0, visible_right - visible_left)

        h_scroll_h = (
            self.horizontalScrollBar().height() if self.horizontalScrollBar().isVisible() else 0
        )
        bar_h = self.horizontalScrollBar().sizeHint().height() or 12
        self._graph_scrollbar.setFixedHeight(bar_h)
        y = max(0, self.height() - h_scroll_h - bar_h)

        bar_w = max(0, min(col_0_width, viewport_right - col_0_x))
        self._graph_scrollbar.setGeometry(col_0_x, y, bar_w, bar_h)
        self._graph_scrollbar.setVisible(self._max_graph_scroll_x > 0 and visible_w > 10)
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
            max_lane = self._model.max_active_lane
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

    @staticmethod
    def _has_filter_criteria(log_filter: LogFilter | None) -> bool:
        if log_filter is None:
            return False
        return bool(
            log_filter.message_substring
            or log_filter.author
            or log_filter.path
            or log_filter.date_from
            or log_filter.date_to
        )

    @staticmethod
    def _clone_layout_state(state: GraphLayoutState) -> GraphLayoutState:
        return GraphLayoutState(
            lanes=[
                Lane(lane.expected_sha, lane.color, lane.index) if lane is not None else None
                for lane in state.lanes
            ],
            color_counter=state.color_counter,
        )

    def set_repo(self, repo: RepoHandle | None):
        self._repo = repo
        self._model._avatar_url_cache.clear()
        self._ensure_registry_connection()
        if repo:
            try:
                self._model._remote_urls = [
                    r.url
                    for r in engine.list_remotes(repo)
                    if hasattr(r, "url") and isinstance(r.url, str)
                ]
            except Exception:
                self._model._remote_urls = []
        else:
            self._model._remote_urls = []
        self.reload_commits()

    def set_all_refs_mode(self, all_refs: bool):
        if self._all_refs_mode != all_refs:
            self._all_refs_mode = all_refs
            self.reload_commits()

    def apply_filter(self, log_filter: LogFilter | None):
        normalized = log_filter if self._has_filter_criteria(log_filter) else None
        self._filter = normalized

        if not self._repo:
            self._all_commits = []
            self._model.set_rows([])
            self._update_scrollbar_range()
            return

        # Fast synchronous path when the entire repo history already fits in page 1
        if self._all_history_in_memory and (normalized is None or not normalized.path):
            self._page_generation_id += 1
            self._search_generation_id += 1
            self._is_loading_batch = False
            filtered = [c for c in self._cached_unfiltered_commits if matches_filter(c, normalized)]
            self._all_commits = filtered
            self._has_more = False
            self._cursor_sha = None
            self._offset = len(filtered)
            rows, state = compute_graph_layout_step(
                filtered,
                ref_labels=self._ref_labels_cache,
                state=GraphLayoutState(),
            )
            self._layout_state = state
            self._model.set_rows(rows)
            self._update_scrollbar_range()
            if rows and not self.selectionModel().hasSelection():
                self.selectRow(0)
            elif not rows:
                self.commit_selected.emit(None)
            return

        # Multi-page repos (or path filters): run search page 1 off the UI thread
        self._request_search_async()

    def reload_commits(self):
        self._page_generation_id += 1
        self._search_generation_id += 1
        self._is_initial_load = True
        self._all_commits = []
        self._cached_unfiltered_commits = []
        self._ref_labels_cache = {}
        self._layout_state = GraphLayoutState()
        self._cursor_sha = None
        self._offset = 0
        self._has_more = True
        self._all_history_in_memory = False
        self._is_loading_batch = False

        if not self._repo:
            self._model.set_rows([])
            self._update_scrollbar_range()
            self.commit_selected.emit(None)
            return

        self._load_initial_page_sync()

    def _load_initial_page_sync(self) -> None:
        if not self._repo:
            return
        page_size = self._effective_page_size()
        self._is_loading_batch = True
        try:
            ref_labels = engine.get_ref_labels(self._repo)
            self._ref_labels_cache = ref_labels
            page = engine.get_log_page(
                self._repo,
                filter=self._filter,
                limit=page_size,
                cursor_sha=None,
                all_refs=self._all_refs_mode,
            )
            commits = list(page.commits)
            self._all_commits = commits
            self._cursor_sha = page.next_cursor_sha
            self._has_more = page.has_more
            self._offset = len(commits)
            if self._filter is None and not page.has_more:
                self._all_history_in_memory = True
                self._cached_unfiltered_commits = list(commits)
            else:
                self._all_history_in_memory = False

            rows, next_state = compute_graph_layout_step(
                commits,
                ref_labels=ref_labels,
                state=GraphLayoutState(),
            )
            self._layout_state = next_state
            self._model.set_rows(rows)
            self._update_scrollbar_range()

            self._is_initial_load = False
            if rows and not self.selectionModel().hasSelection():
                self.selectRow(0)
            elif not rows:
                self.commit_selected.emit(None)
        except Exception as exc:
            logger.exception("Failed to load initial commit page: %s", exc)
        finally:
            self._is_loading_batch = False

    def _request_next_page_async(self) -> None:
        if not self._repo or self._is_loading_batch or not self._has_more:
            return

        self._is_loading_batch = True
        gen_id = self._page_generation_id
        page_size = self._effective_page_size()

        dispatcher = _get_graph_dispatcher()
        worker = _GraphPageWorker(
            generation_id=gen_id,
            repo_path=self._repo.path,
            log_filter=self._filter,
            limit=page_size,
            cursor_sha=self._cursor_sha,
            all_refs=self._all_refs_mode,
            ref_labels=dict(self._ref_labels_cache),
            layout_state=self._clone_layout_state(self._layout_state),
            widget_ref=weakref.ref(self),
            dispatcher=dispatcher,
        )
        QThreadPool.globalInstance().start(worker)

    def _request_search_async(self) -> None:
        if not self._repo:
            return
        self._page_generation_id += 1
        self._search_generation_id += 1
        gen_id = self._search_generation_id
        self._is_loading_batch = True
        page_size = self._effective_page_size()

        dispatcher = _get_graph_dispatcher()
        worker = _GraphSearchWorker(
            generation_id=gen_id,
            repo_path=self._repo.path,
            log_filter=self._filter,
            limit=page_size,
            all_refs=self._all_refs_mode,
            ref_labels=dict(self._ref_labels_cache),
            widget_ref=weakref.ref(self),
            dispatcher=dispatcher,
        )
        QThreadPool.globalInstance().start(worker)

    @Slot(int, object, object, object)
    def _on_page_ready(
        self,
        generation_id: int,
        page: LogPage,
        new_rows: list[GraphRow],
        next_state: GraphLayoutState,
    ) -> None:
        if not shiboken6.isValid(self) or generation_id != self._page_generation_id:
            return
        self._is_loading_batch = False
        self._cursor_sha = page.next_cursor_sha
        self._has_more = page.has_more
        self._layout_state = next_state
        if page.commits:
            self._all_commits.extend(page.commits)
            self._offset = len(self._all_commits)
            self._model.append_rows(new_rows)
            self._update_scrollbar_range()

    @Slot(int, str)
    def _on_page_failed(self, generation_id: int, error_msg: str) -> None:
        if not shiboken6.isValid(self) or generation_id != self._page_generation_id:
            return
        self._is_loading_batch = False
        logger.warning("Commit graph pagination error: %s", error_msg)

    @Slot(int, object, object, object)
    def _on_search_ready(
        self,
        generation_id: int,
        page: LogPage,
        rows: list[GraphRow],
        next_state: GraphLayoutState,
    ) -> None:
        if not shiboken6.isValid(self) or generation_id != self._search_generation_id:
            return
        self._is_loading_batch = False
        self._all_commits = list(page.commits)
        self._cursor_sha = page.next_cursor_sha
        self._has_more = page.has_more
        self._offset = len(self._all_commits)
        self._layout_state = next_state
        self._model.set_rows(rows)
        self._update_scrollbar_range()
        if rows and not self.selectionModel().hasSelection():
            self.selectRow(0)
        elif not rows:
            self.commit_selected.emit(None)

    @Slot(int, str)
    def _on_search_failed(self, generation_id: int, error_msg: str) -> None:
        if not shiboken6.isValid(self) or generation_id != self._search_generation_id:
            return
        self._is_loading_batch = False
        logger.warning("Commit graph background search error: %s", error_msg)

    def _fetch_next_batch(self):
        self._request_next_page_async()

    def _on_scroll(self, value: int):
        max_val = self.verticalScrollBar().maximum()
        if max_val > 0 and value >= int(max_val * 0.80):
            self._request_next_page_async()

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

        interactive_rebase_act = None
        reg = self._settings_registry or peek_settings_registry()
        repo_str = str(self._repo.path) if self._repo else None
        if reg is None or reg.is_enabled("rebase.interactive_ui.enabled", repo_str):
            interactive_rebase_act = menu.addAction(self.tr("Interactive Rebase from Here..."))

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
        elif interactive_rebase_act is not None and action == interactive_rebase_act:
            self.interactive_rebase_requested.emit(commit.sha)
