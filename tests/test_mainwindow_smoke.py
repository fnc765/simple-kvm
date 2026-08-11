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

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication
app = QApplication.instance() or QApplication([])

from ui.mainwindow import MainWindow


def _isolated_window(tmp_path, monkeypatch):
    """Construct MainWindow while making hardware access a hard failure."""
    settings = QSettings(
        str(tmp_path / "settings.ini"),
        QSettings.Format.IniFormat,
    )

    def unexpected_start(*_args, **_kwargs):
        raise AssertionError("a hardware-backed thread was started during a UI test")

    monkeypatch.setattr("ui.mainwindow.SerialComm.start", unexpected_start)
    monkeypatch.setattr("ui.mainwindow.CaptureThread.start", unexpected_start)
    return MainWindow(settings=settings, auto_connect=False), settings


def test_mainwindow_constructs_without_error(tmp_path, monkeypatch):
    """Constructing MainWindow must not raise AttributeError or similar.

    Detailed persistence behaviour is covered by ``test_settings_values``;
    this test only checks that an isolated window has valid mode fields.
    """
    from core.mouse_modes import MouseMode
    w, _settings = _isolated_window(tmp_path, monkeypatch)
    # The mouse-mode fields the bug was about must be present.
    assert hasattr(w, "_mouse_mode")
    assert hasattr(w, "_firmware_abs_supported")
    assert hasattr(w, "_mode_config")
    assert hasattr(w, "_effective_mode")
    # Values must be valid (one of the known enums / bool).
    assert w._mouse_mode in (
        MouseMode.RELATIVE, MouseMode.HYBRID, MouseMode.ABSOLUTE,
    )
    assert isinstance(w._firmware_abs_supported, bool)
    w.close()
    w.deleteLater()


def test_mainwindow_can_disable_all_automatic_io(tmp_path, monkeypatch):
    """Tests must be able to construct the UI without touching real devices."""
    w, settings = _isolated_window(tmp_path, monkeypatch)
    assert w._settings is settings
    w.close()
    w.deleteLater()
