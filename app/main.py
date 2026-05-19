"""
main.py -- simple-kvm application entry point.

Usage:
    python -m app
    simple-kvm  (after pip install -e .)
"""

import sys
from pathlib import Path

# PyInstaller frozen and normal execution path resolution
if getattr(sys, "frozen", False):
    # Packaged by PyInstaller: resolve relative to the exe location
    _APP_DIR = Path(sys.executable).parent
else:
    _APP_DIR = Path(__file__).resolve().parent

# Append to avoid shadowing standard library modules (safer than insert)
if str(_APP_DIR) not in sys.path:
    sys.path.append(str(_APP_DIR))

from PySide6.QtWidgets import QApplication

# Single source of truth for version
try:
    from app._version import __version__  # noqa: E402
except ImportError:
    __version__ = "0.1.0"


def main() -> None:
    try:
        app = QApplication(sys.argv)
    except Exception as e:
        print(f"Failed to initialize QApplication: {e}", file=sys.stderr)
        print(
            "Ensure PySide6 is installed and platform plugins are available.",
            file=sys.stderr,
        )
        sys.exit(1)

    app.setApplicationName("simple-kvm")
    app.setApplicationVersion(__version__)

    # Delayed import after sys.path is configured
    from ui.mainwindow import MainWindow  # noqa: E402, PLC0415

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
