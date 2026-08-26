"""FR-2.1: Diff view widget."""

from PySide6.QtWidgets import QWidget

from wrench.core.engine import RepoHandle


class DiffView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._repo: RepoHandle | None = None

    def set_repo(self, repo: RepoHandle):
        self._repo = repo
        self.refresh()

    def refresh(self):
        pass
