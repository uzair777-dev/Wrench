"""FR-1.12: Multi-Repository Discovery Results Dialog."""

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class DiscoverReposDialog(QDialog):
    """Dialog displaying discovered repositories with checkable selection."""

    def __init__(
        self,
        repos: list[Path],
        root_dir: Path,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._repos = sorted(repos)
        self._root_dir = root_dir

        self.setWindowTitle(self.tr("Discovered Repositories"))
        self.setAccessibleName(self.tr("Discovered Repositories Dialog"))
        self.resize(640, 420)

        self._init_ui()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)

        # Header description
        count = len(self._repos)
        repo_word = "repositories" if count != 1 else "repository"
        header_text = self.tr(f"Found {count} Git {repo_word} under '{self._root_dir}':")
        self.lbl_header = QLabel(header_text, self)
        self.lbl_header.setWordWrap(True)
        layout.addWidget(self.lbl_header)

        # Selection action bar
        bar_layout = QHBoxLayout()
        self.btn_select_all = QPushButton(self.tr("Select All"), self)
        self.btn_select_all.clicked.connect(self._select_all)
        bar_layout.addWidget(self.btn_select_all)

        self.btn_deselect_all = QPushButton(self.tr("Deselect All"), self)
        self.btn_deselect_all.clicked.connect(self._deselect_all)
        bar_layout.addWidget(self.btn_deselect_all)

        bar_layout.addStretch()
        layout.addLayout(bar_layout)

        # Repositories list widget
        self.repo_list = QListWidget(self)
        self.repo_list.setAccessibleName(self.tr("Discovered Repositories List"))
        for repo_path in self._repos:
            item = QListWidgetItem(f"{repo_path.name} — {repo_path}")
            item.setData(Qt.ItemDataRole.UserRole, repo_path)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked)
            item.setToolTip(str(repo_path))
            self.repo_list.addItem(item)

        layout.addWidget(self.repo_list, stretch=1)

        # Dialog buttons
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        self.btn_cancel = QPushButton(self.tr("Cancel"), self)
        self.btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(self.btn_cancel)

        self.btn_add = QPushButton(self.tr("Add Selected Repositories"), self)
        self.btn_add.setDefault(True)
        self.btn_add.clicked.connect(self.accept)
        btn_layout.addWidget(self.btn_add)

        layout.addLayout(btn_layout)

    def _select_all(self) -> None:
        for i in range(self.repo_list.count()):
            self.repo_list.item(i).setCheckState(Qt.CheckState.Checked)

    def _deselect_all(self) -> None:
        for i in range(self.repo_list.count()):
            self.repo_list.item(i).setCheckState(Qt.CheckState.Unchecked)

    def selected_repositories(self) -> list[Path]:
        """Returns the list of Path objects checked by the user."""
        selected: list[Path] = []
        for i in range(self.repo_list.count()):
            item = self.repo_list.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                path = item.data(Qt.ItemDataRole.UserRole)
                if isinstance(path, Path):
                    selected.append(path)
        return selected
