"""Smoke test: MainWindow can be constructed in offscreen mode.

This guards against attribute-initialisation-order regressions where a
field used in __init__ is referenced before it is set (e.g. the
``_mouse_mode`` / ``_firmware_abs_supported`` ordering bug fixed in
Phase 1).
"""
import os
import sys

# Force offscreen Qt platform so this test does not require a display.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))

# ``QSettings`` on Windows uses the registry; isolate the test from the
# real user settings by pointing it at a temporary INI file.
import tempfile
import pathlib

_td = tempfile.mkdtemp(prefix="simple_kvm_test_")
os.environ["XDG_CONFIG_HOME"] = _td  # ignored on Windows but harmless
_ini = pathlib.Path(_td) / "test.ini"
os.environ["QSETTINGS_TEST_INI"] = str(_ini)

from PySide6.QtCore import QSettings
QSettings.setDefaultFormat(QSettings.Format.IniFormat)
QSettings.setPath(
    QSettings.Format.IniFormat,
    QSettings.Scope.UserScope,
    _td,
)

from PySide6.QtWidgets import QApplication
app = QApplication.instance() or QApplication([])

from ui.mainwindow import MainWindow


def test_mainwindow_constructs_without_error():
    """Constructing MainWindow must not raise AttributeError or similar."""
    w = MainWindow()
    # The mouse-mode fields the bug was about must be present and
    # have sensible defaults.
    assert hasattr(w, "_mouse_mode")
    assert hasattr(w, "_firmware_abs_supported")
    assert hasattr(w, "_mode_config")
    assert hasattr(w, "_effective_mode")
    # Default is the safe pre-Phase-3 behaviour.
    assert w._mouse_mode.value == "relative"
    assert w._firmware_abs_supported is False
    w.close()
    w.deleteLater()


if __name__ == "__main__":
    test_mainwindow_constructs_without_error()
    print("MainWindow smoke test passed.")
