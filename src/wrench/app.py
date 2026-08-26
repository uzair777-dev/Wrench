"""QApplication bootstrap and main window wiring."""

import argparse
import logging
import os
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication, QMessageBox

from wrench.core import lock_recovery
from wrench.storage.db import get_connection
from wrench.ui.main_window import MainWindow

logger = logging.getLogger("wrench")


def setup_logging(debug: bool = False):
    """Configure structured logging output with timestamps and colors."""
    level = logging.DEBUG if debug else logging.INFO
    log_format = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    date_format = "%H:%M:%S"
    logging.basicConfig(
        level=level,
        format=log_format,
        datefmt=date_format,
        force=True,
    )
    if debug:
        logger.info("Verbose debug logging enabled (--debug).")


def main():
    parser = argparse.ArgumentParser(description="Wrench Git Client")
    parser.add_argument(
        "--debug",
        "-d",
        action="store_true",
        default=bool(os.getenv("WRENCH_DEBUG")),
        help="Enable verbose debug logging in terminal",
    )
    parser.add_argument(
        "repo_path",
        nargs="?",
        help="Optional path to a git repository to open on launch",
    )
    args, _ = parser.parse_known_args()

    setup_logging(debug=args.debug)

    app = QApplication(sys.argv)
    app.setApplicationName("Wrench")
    app.setOrganizationName("wrench")

    # 1. Initialize SQLite database & apply any pending migrations
    conn = get_connection()
    logger.debug("Connected to SQLite database.")

    # 2. Check for stale locks across all registered repos on startup (FR-1.9)
    stale_locks = lock_recovery.check_all_repos(conn)
    if stale_locks:
        repo_names = ", ".join([name for _, name, _ in stale_locks])
        logger.warning("Stale git index locks detected: %s", repo_names)
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
                lock_recovery.remove_lock(Path(lock_path).parent.parent)

    # 3. Create and show main window
    window = MainWindow(conn=conn)
    if args.repo_path:
        target = Path(args.repo_path).resolve()
        if target.exists():
            logger.info("Opening specified repository: %s", target)
            window._open_repo_path(str(target))

    window.show()
    logger.info("Wrench application initialized.")

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
