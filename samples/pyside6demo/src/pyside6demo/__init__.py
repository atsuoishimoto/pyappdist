"""Minimal PySide6 GUI sample.

Shows a window with a label and a Close button. It is a GUI app, so pyappdist
ships it with ``gui = true`` (launched via pythonw.exe).
"""

from __future__ import annotations

import sys

from PySide6.QtWidgets import (
    QApplication,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


def main() -> int:
    app = QApplication(sys.argv)

    window = QWidget()
    window.setWindowTitle("pyappdist + PySide6")
    window.resize(320, 160)

    layout = QVBoxLayout(window)
    layout.addWidget(QLabel("Hello from PySide6!"))
    close_button = QPushButton("Close")
    close_button.clicked.connect(window.close)
    layout.addWidget(close_button)

    window.show()
    return app.exec()
