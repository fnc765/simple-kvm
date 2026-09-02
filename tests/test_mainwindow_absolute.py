"""Offscreen tests for reliable absolute-mouse UI transitions."""

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))

from PySide6.QtCore import QPoint, QSettings  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from core.mouse_modes import MouseMode, MouseModeConfig  # noqa: E402
from core.protocol import build_mouse_abs_report  # noqa: E402
from ui.mainwindow import MainWindow  # noqa: E402


app = QApplication.instance() or QApplication([])


def _window(tmp_path, monkeypatch):
    settings = QSettings(
        str(tmp_path / "settings.ini"),
        QSettings.Format.IniFormat,
    )

    def unexpected_start(*_args, **_kwargs):
        raise AssertionError("hardware-backed thread started in a UI test")

    monkeypatch.setattr("ui.mainwindow.SerialComm.start", unexpected_start)
    monkeypatch.setattr("ui.mainwindow.CaptureThread.start", unexpected_start)
    window = MainWindow(settings=settings, auto_connect=False)
    window._mouse_mode = MouseMode.ABSOLUTE
    window._firmware_abs_supported = True
    window._mode_config = MouseModeConfig(MouseMode.ABSOLUTE, True)
    window._effective_mode = MouseMode.ABSOLUTE
    return window


def test_absolute_activation_click_is_forwarded_as_ordered_transaction(
    tmp_path, monkeypatch,
):
    window = _window(tmp_path, monkeypatch)
    captured = []
    monkeypatch.setattr(
        window._serial,
        "enqueue_mouse_transition",
        lambda item: captured.append(item) or True,
    )
    monkeypatch.setattr(
        window,
        "_set_kvm_active",
        lambda active: setattr(window, "_kvm_active", active),
    )
    window._pending_kvm_activation_widget_pos = QPoint(100, 100)
    window._pending_kvm_activation_button = 0x01

    window._activate_kvm_from_click()

    assert len(captured) == 1
    payloads = [step.data for step in captured[0].steps]
    assert len(payloads) == 3
    assert payloads[0][3] == 0x00
    assert payloads[1][3] == 0x01
    assert payloads[2][3] == 0x00
    window.close()
    window.deleteLater()


def test_deactivation_releases_absolute_buttons_at_last_known_position(
    tmp_path, monkeypatch,
):
    window = _window(tmp_path, monkeypatch)
    captured = []
    monkeypatch.setattr(
        window._serial,
        "enqueue_mouse_transition",
        lambda item: captured.append(item) or True,
    )
    monkeypatch.setattr(window, "_map_absolute_cursor", lambda **_kwargs: None)
    window._connected = True
    window._kvm_active = True
    window._input_state.mouse_buttons = 0x01
    window._last_abs_x = 111
    window._last_abs_y = 222

    window._set_kvm_active(False)

    assert len(captured) == 1
    assert [step.data for step in captured[0].steps] == [
        build_mouse_abs_report(0x01, 111, 222),
        build_mouse_abs_report(0x00, 111, 222),
    ]
    assert window._input_state.mouse_buttons == 0
    window.close()
    window.deleteLater()


def test_absolute_wheel_does_not_duplicate_held_button_on_relative_interface(
    tmp_path, monkeypatch,
):
    window = _window(tmp_path, monkeypatch)
    captured = []
    monkeypatch.setattr(
        window._serial,
        "enqueue",
        lambda packet: captured.append(packet) or True,
    )
    window._kvm_active = True
    window._input_state.mouse_buttons = 0x01

    class WheelDelta:
        @staticmethod
        def y():
            return 120

    class WheelEvent:
        @staticmethod
        def angleDelta():  # noqa: N802 - mirrors the Qt API
            return WheelDelta()

    window.wheelEvent(WheelEvent())

    assert len(captured) == 1
    assert captured[0][3] == 0x00  # relative-interface button mask
    assert captured[0][6] == 0x01  # one vertical wheel tick
    window.close()
    window.deleteLater()
