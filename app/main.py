"""
main.py – simple-kvm アプリケーションエントリポイント。

使い方:
    cd app
    python main.py
"""

import sys
import os

# app/ 直下のディレクトリを sys.path に追加して相対 import を有効化
sys.path.insert(0, os.path.dirname(__file__))

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("simple-kvm")
    app.setApplicationVersion("0.1.0")

    # High-DPI サポート（PySide6 6.4+ では AA_EnableHighDpiScaling は不要）
    app.setAttribute(Qt.ApplicationAttribute.AA_UseHighDpiPixmaps)

    # メインウィンドウは遅延 import（sys.path 設定後に行う）
    from ui.mainwindow import MainWindow  # noqa: PLC0415

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
