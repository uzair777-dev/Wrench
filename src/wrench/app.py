"""QApplication bootstrap and main window wiring."""

import sys

from PySide6.QtWidgets import QApplication, QMainWindow


class MainWindow(QMainWindow):
    """Placeholder main window for Phase 0 skeleton."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Wrench")
        self.resize(1000, 600)


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Wrench")
    app.setOrganizationName("wrench")

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
