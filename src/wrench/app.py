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
    """Configure structured logging output with timestamps and component filters."""
    log_format = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    date_format = "%H:%M:%S"

    # Configure root handler
    logging.basicConfig(
        level=logging.INFO,
        format=log_format,
        datefmt=date_format,
        force=True,
    )

    # Enable detailed debug logs for Wrench modules
    wrench_level = logging.DEBUG if debug else logging.INFO
    logging.getLogger("wrench").setLevel(wrench_level)

    # Suppress verbose third-party internal buffer logs
    logging.getLogger("watchdog").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)

    if debug:
        logger.info("Verbose debug logging enabled for Wrench (--debug).")


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

    # 1b. Validate database integrity
    from wrench.storage.health import check_database_health

    health = check_database_health(conn)
    if health.get("status") != "ok":
        logger.warning("Database health check warning: %s", health)

    # 2. Create and show main window (Instant UI < 200ms)
    window = MainWindow(conn=conn)

    # 2b. Install global crash handler and session preserver
    from wrench.core.crash_handler import install_crash_handler

    install_crash_handler(window)

    if args.repo_path:
        target = Path(args.repo_path).resolve()
        if target.exists():
            logger.info("Opening specified repository: %s", target)
            window._open_repo_path(str(target))

    window.show()
    logger.info("Wrench application initialized.")

    # 3. Asynchronously inspect stale locks across registered repos post-launch (FR-1.9)
    from PySide6.QtCore import QTimer

    def _check_stale_locks():
        stale_locks = lock_recovery.check_all_repos(conn)
        if stale_locks:
            repo_names = ", ".join([name for _, name, _ in stale_locks])
            logger.warning("Stale git index locks detected: %s", repo_names)
            reply = QMessageBox.question(
                window,
                "Stale Git Locks Detected",
                (
                    "Stale git index lock files were detected in the following repositories:\n\n"
                    f"{repo_names}\n\n"
                    "Would you like Wrench to clean them up now?"
                ),
                QMessageBox.Yes | QMessageBox.No,
            )
            if reply == QMessageBox.Yes:
                for _, _, lock_path in stale_locks:
                    lock_recovery.remove_lock(Path(lock_path).parent.parent)

    QTimer.singleShot(150, _check_stale_locks)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
