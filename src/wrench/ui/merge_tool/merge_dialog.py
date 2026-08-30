"""FR-3.2: 3-Way Merge Tool Dialog (ui-planning.md §6.6).

Displays Base, Ours, Theirs versions alongside an editable Result editor with
conflict marker detection, quick resolution actions, and auto-staging on save.
"""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from wrench.core import engine
from wrench.core.engine import RepoHandle

logger = logging.getLogger(__name__)


class MergeDialog(QDialog):
    """3-Way visual merge tool for resolving conflicting files."""

    def __init__(
        self,
        repo: RepoHandle,
        file_path: str,
        *,
        mode: str = "merge",  # "merge" or "rebase"
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self._repo = repo
        self._file_path = file_path
        self._mode = mode

        self.base_content = ""
        self.ours_content = ""
        self.theirs_content = ""

        self.setWindowTitle(f"Resolve Conflict — {file_path}")
        self.resize(1000, 700)

        self._load_conflict_contents()
        self._init_ui()

    def _load_conflict_contents(self) -> None:
        """Extract ancestor (base), ours, and theirs blob contents from git index."""
        r = self._repo.pygit2_repo
        try:
            r.index.read()
            if r.index.conflicts is not None:
                for ancestor, ours, theirs in r.index.conflicts:
                    entry_path = (
                        (ours.path if ours else None)
                        or (theirs.path if theirs else None)
                        or (ancestor.path if ancestor else None)
                    )
                    if entry_path == self._file_path:
                        if ancestor and ancestor.id in r:
                            self.base_content = r[ancestor.id].data.decode(
                                "utf-8", errors="replace"
                            )
                        if ours and ours.id in r:
                            self.ours_content = r[ours.id].data.decode("utf-8", errors="replace")
                        if theirs and theirs.id in r:
                            self.theirs_content = r[theirs.id].data.decode(
                                "utf-8", errors="replace"
                            )
                        break
        except Exception as e:
            logger.exception("Failed to load conflict versions from pygit2: %s", e)

        # Working tree file content as default in result editor
        target_file = Path(self._repo.path) / self._file_path
        if target_file.exists():
            try:
                self.worktree_content = target_file.read_text(encoding="utf-8", errors="replace")
            except Exception:
                self.worktree_content = ""
        else:
            self.worktree_content = ""

    def _init_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.setSpacing(6)

        # Header info
        header_layout = QHBoxLayout()
        title_lbl = QLabel(f"<b>File:</b> {self._file_path}", self)
        header_layout.addWidget(title_lbl)
        header_layout.addStretch()

        if self._mode == "rebase":
            mode_lbl = QLabel(
                "<span style='color: #e67e22;'><b>Mode: Rebase</b> "
                "(Ours = Upstream target, Theirs = Commit being applied)</span>",
                self,
            )
        else:
            mode_lbl = QLabel(
                "<span style='color: #3498db;'><b>Mode: Merge</b> "
                "(Ours = Current branch, Theirs = Incoming branch)</span>",
                self,
            )

        header_layout.addWidget(mode_lbl)
        main_layout.addLayout(header_layout)

        # Main splitter (Top: 3-way panes, Bottom: Result)
        v_splitter = QSplitter(Qt.Vertical, self)

        # Top 3-way horizontal splitter
        top_splitter = QSplitter(Qt.Horizontal, self)

        # 1. Base Pane
        base_widget = QWidget(self)
        base_layout = QVBoxLayout(base_widget)
        base_layout.setContentsMargins(0, 0, 0, 0)
        base_layout.addWidget(QLabel("<b>Base (Common Ancestor)</b>", self))
        self.base_edit = QTextEdit(self)
        self.base_edit.setReadOnly(True)
        self.base_edit.setFont(QFont("Monospace", 9))
        self.base_edit.setPlainText(self.base_content)
        base_layout.addWidget(self.base_edit)
        top_splitter.addWidget(base_widget)

        # 2. Ours Pane
        ours_widget = QWidget(self)
        ours_layout = QVBoxLayout(ours_widget)
        ours_layout.setContentsMargins(0, 0, 0, 0)
        ours_title = (
            "<b>Ours (Current Branch)</b>"
            if self._mode != "rebase"
            else "<b>Ours (Upstream / Onto)</b>"
        )
        ours_layout.addWidget(QLabel(ours_title, self))
        self.ours_edit = QTextEdit(self)
        self.ours_edit.setReadOnly(True)
        self.ours_edit.setFont(QFont("Monospace", 9))
        self.ours_edit.setPlainText(self.ours_content)
        ours_layout.addWidget(self.ours_edit)
        top_splitter.addWidget(ours_widget)

        # 3. Theirs Pane
        theirs_widget = QWidget(self)
        theirs_layout = QVBoxLayout(theirs_widget)
        theirs_layout.setContentsMargins(0, 0, 0, 0)
        theirs_title = (
            "<b>Theirs (Incoming Branch)</b>"
            if self._mode != "rebase"
            else "<b>Theirs (Applying Commit)</b>"
        )
        theirs_layout.addWidget(QLabel(theirs_title, self))
        self.theirs_edit = QTextEdit(self)
        self.theirs_edit.setReadOnly(True)
        self.theirs_edit.setFont(QFont("Monospace", 9))
        self.theirs_edit.setPlainText(self.theirs_content)
        theirs_layout.addWidget(self.theirs_edit)
        top_splitter.addWidget(theirs_widget)

        v_splitter.addWidget(top_splitter)

        # Bottom Pane: Result editor & quick actions
        bottom_widget = QWidget(self)
        bottom_layout = QVBoxLayout(bottom_widget)
        bottom_layout.setContentsMargins(0, 0, 0, 0)

        res_header = QHBoxLayout()
        res_header.addWidget(QLabel("<b>Result (Editable Output)</b>", self))
        res_header.addStretch()

        accept_ours_btn = QPushButton("Accept Ours", self)
        accept_ours_btn.clicked.connect(self._accept_ours)
        res_header.addWidget(accept_ours_btn)

        accept_theirs_btn = QPushButton("Accept Theirs", self)
        accept_theirs_btn.clicked.connect(self._accept_theirs)
        res_header.addWidget(accept_theirs_btn)

        accept_both_btn = QPushButton("Accept Both (Ours then Theirs)", self)
        accept_both_btn.clicked.connect(self._accept_both)
        res_header.addWidget(accept_both_btn)

        bottom_layout.addLayout(res_header)

        self.result_edit = QTextEdit(self)
        self.result_edit.setFont(QFont("Monospace", 9))
        self.result_edit.setPlainText(self.worktree_content or self.ours_content)
        bottom_layout.addWidget(self.result_edit)

        v_splitter.addWidget(bottom_widget)
        v_splitter.setStretchFactor(0, 1)
        v_splitter.setStretchFactor(1, 1)

        main_layout.addWidget(v_splitter, 1)

        # Dialog Buttons
        btn_bar = QHBoxLayout()
        btn_bar.addStretch()

        cancel_btn = QPushButton("Cancel", self)
        cancel_btn.clicked.connect(self.reject)
        btn_bar.addWidget(cancel_btn)

        self.save_btn = QPushButton("Save && Mark Resolved", self)
        self.save_btn.setDefault(True)
        self.save_btn.setStyleSheet(
            "font-weight: bold; background-color: #27ae60; color: white; padding: 6px 12px;"
        )
        self.save_btn.clicked.connect(self._save_and_mark_resolved)
        btn_bar.addWidget(self.save_btn)

        main_layout.addLayout(btn_bar)

    def _accept_ours(self) -> None:
        self.result_edit.setPlainText(self.ours_content)

    def _accept_theirs(self) -> None:
        self.result_edit.setPlainText(self.theirs_content)

    def _accept_both(self) -> None:
        both = (
            self.ours_content
            + ("\n" if not self.ours_content.endswith("\n") else "")
            + self.theirs_content
        )
        self.result_edit.setPlainText(both)

    def _save_and_mark_resolved(self) -> None:
        text = self.result_edit.toPlainText()

        # Guard against unresolved conflict markers
        if "<<<<<<<" in text or "=======" in text or ">>>>>>>" in text:
            reply = QMessageBox.warning(
                self,
                "Conflict Markers Detected",
                "The result still contains git conflict markers (<<<<<<<, =======, >>>>>>>).\n\n"
                "Are you sure you want to save anyway?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                return

        try:
            target_path = Path(self._repo.path) / self._file_path
            target_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.write_text(text, encoding="utf-8")

            # Stage the resolved file
            engine.stage_file(self._repo, self._file_path)
            self.accept()
        except Exception as e:
            logger.exception("Failed to write and stage resolved file: %s", e)
            QMessageBox.critical(self, "Error Saving File", f"Could not save resolved file:\n{e}")
