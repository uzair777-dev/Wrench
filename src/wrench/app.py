"""QApplication bootstrap and main window wiring."""

import logging
import sys

from PySide6.QtWidgets import QApplication, QMessageBox

from wrench.core import lock_recovery
from wrench.storage.db import get_connection
from wrench.ui.main_window import MainWindow

logger = logging.getLogger(__name__)


def main():
    logging.basicConfig(level=logging.INFO)

    app = QApplication(sys.argv)
    app.setApplicationName("Wrench")
    app.setOrganizationName("wrench")

    # 1. Initialize SQLite database & apply any pending migrations
    conn = get_connection()

    # 2. Check for stale locks across all registered repos on startup (FR-1.9)
    stale_locks = lock_recovery.check_all_repos(conn)
    if stale_locks:
        repo_names = ", ".join([name for _, name, _ in stale_locks])
        reply = QMessageBox.question(
            None,
            "Stale Git Locks Detected",
            f"Stale git index lock files were detected in the following repositories:\n\n"
            f"{repo_names}\n\n"
            f"Would you like Wrench to clean them up now?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            for _, _, lock_path in stale_locks:
                from pathlib import Path

                lock_recovery.remove_lock(Path(lock_path).parent.parent)

    # 3. Create and show main window
    window = MainWindow(conn=conn)
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
