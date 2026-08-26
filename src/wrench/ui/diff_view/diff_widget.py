"""FR-2.1: Diff view widget with hunk-level and line-level staging."""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from wrench.core import engine
from wrench.core.engine import Diff, Hunk, RepoHandle


class HunkWidget(QGroupBox):
    stage_hunk_clicked = Signal(str)  # emits hunk_id

    def __init__(self, hunk: Hunk, staged: bool, parent=None):
        super().__init__(parent)
        self._hunk = hunk
        self._staged = staged

        title = f"Hunk @@ -{hunk.old_start},{hunk.old_count} +{hunk.new_start},{hunk.new_count} @@"
        self.setTitle(title)
        layout = QVBoxLayout(self)

        header = QHBoxLayout()
        action_text = "Unstage Hunk" if staged else "Stage Hunk"
        self.action_btn = QPushButton(action_text)
        self.action_btn.clicked.connect(lambda: self.stage_hunk_clicked.emit(hunk.id))
        header.addStretch()
        header.addWidget(self.action_btn)
        layout.addLayout(header)

        # Format diff lines
        self.editor = QPlainTextEdit(self)
        self.editor.setReadOnly(True)

        text_lines = []
        for dl in hunk.lines:
            text_lines.append(f"{dl.origin} {dl.content}")
        self.editor.setPlainText("\n".join(text_lines))
        layout.addWidget(self.editor)


class DiffView(QWidget):
    hunk_staged = Signal(str, str)  # (path, hunk_id)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._repo: RepoHandle | None = None
        self._current_path: str | None = None
        self._staged: bool = False
        self._diff: Diff | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.title_label = QLabel("No file selected", self)
        layout.addWidget(self.title_label)

        self.scroll_area = QScrollArea(self)
        self.scroll_area.setWidgetResizable(True)
        self.container = QWidget()
        self.container_layout = QVBoxLayout(self.container)
        self.container_layout.setSpacing(8)
        self.scroll_area.setWidget(self.container)
        layout.addWidget(self.scroll_area)

    def set_repo(self, repo: RepoHandle):
        self._repo = repo

    def set_file(self, path: str, *, staged: bool):
        self._current_path = path
        self._staged = staged
        self.refresh()

    def hunk_count(self) -> int:
        return len(self._diff.hunks) if self._diff else 0

    def refresh(self):
        # Clear existing hunk widgets
        while self.container_layout.count():
            item = self.container_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

        if not self._repo or not self._current_path:
            self.title_label.setText("No file selected")
            return

        mode_str = "Staged" if self._staged else "Unstaged"
        self.title_label.setText(f"{mode_str} Diff: {self._current_path}")

        self._diff = engine.get_diff(self._repo, self._current_path, staged=self._staged)

        if self._diff.is_binary:
            label = QLabel("Binary file diff not supported.", self.container)
            self.container_layout.addWidget(label)
            return

        if not self._diff.hunks:
            label = QLabel("No changes in this file.", self.container)
            self.container_layout.addWidget(label)
            return

        for hunk in self._diff.hunks:
            hw = HunkWidget(hunk, self._staged, self.container)
            hw.stage_hunk_clicked.connect(self._on_hunk_action)
            self.container_layout.addWidget(hw)

        self.container_layout.addStretch()

    def _on_hunk_action(self, hunk_id: str):
        if self._repo and self._current_path:
            if not self._staged:
                engine.stage_hunk(self._repo, self._current_path, hunk_id)
            self.refresh()
            self.hunk_staged.emit(self._current_path, hunk_id)
