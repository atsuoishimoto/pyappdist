"""PySide6 を使った最小 GUI サンプル。

ラベルと「閉じる」ボタンだけのウィンドウを表示する。GUI アプリなので
pyappdist 側は ``gui = true``（pythonw.exe 起動）で配布する。
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
    close_button = QPushButton("閉じる")
    close_button.clicked.connect(window.close)
    layout.addWidget(close_button)

    window.show()
    return app.exec()
