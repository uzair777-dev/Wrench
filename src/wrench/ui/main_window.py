"""Main application window."""

from PySide6.QtWidgets import QMainWindow


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Wrench")
        self.resize(1000, 600)
