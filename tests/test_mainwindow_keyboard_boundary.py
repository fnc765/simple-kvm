"""Keyboard forwarding must follow the host cursor's KVM-window boundary."""

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))

from PySide6.QtCore import QEvent, QSettings, Qt  # noqa: E402
from PySide6.QtGui import QKeyEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from core.protocol import build_keyboard_report  # noqa: E402
from ui.mainwindow import MainWindow  # noqa: E402


app = QApplication.instance() or QApplication([])


def _window(tmp_path, monkeypatch):
    settings = QSettings(
        str(tmp_path / "settings.ini"),
        QSettings.Format.IniFormat,
    )

    def unexpected_start(*_args, **_kwargs):
        raise AssertionError("a hardware-backed thread was started")

    monkeypatch.setattr("ui.mainwindow.SerialComm.start", unexpected_start)
    monkeypatch.setattr("ui.mainwindow.CaptureThread.start", unexpected_start)
    window = MainWindow(settings=settings, auto_connect=False)
    window._kvm_active = True
    return window


def _qt_a_event(event_type):
    return QKeyEvent(
        event_type,
        Qt.Key.Key_A,
        Qt.KeyboardModifier.NoModifier,
    )


def test_qt_key_press_outside_window_is_not_forwarded(tmp_path, monkeypatch):
    window = _window(tmp_path, monkeypatch)
    packets = []
    monkeypatch.setattr(
        window,
        "_keyboard_forwarding_allowed",
        lambda: False,
    )
    monkeypatch.setattr(
        window._serial,
        "enqueue",
        lambda packet: packets.append(packet) or True,
    )
    window._use_raw_input = False

    window.keyPressEvent(_qt_a_event(QEvent.Type.KeyPress))

    assert packets == []
    assert window._input_state.get_keyboard_report() == (0, [0] * 6)
    window.close()
    window.deleteLater()


def test_raw_key_press_outside_window_is_not_forwarded(tmp_path, monkeypatch):
    window = _window(tmp_path, monkeypatch)
    packets = []
    monkeypatch.setattr(
        window,
        "_keyboard_forwarding_allowed",
        lambda: False,
    )
    monkeypatch.setattr(
        window._serial,
        "enqueue",
        lambda packet: packets.append(packet) or True,
    )

    window._on_raw_key_down(0x1E, 0x41, 0, False)

    assert packets == []
    assert window._input_state.get_keyboard_report() == (0, [0] * 6)
    window.close()
    window.deleteLater()


def test_leaving_window_releases_keyboard_without_releasing_mouse(
    tmp_path,
    monkeypatch,
):
    window = _window(tmp_path, monkeypatch)
    packets = []
    monkeypatch.setattr(
        window._serial,
        "enqueue",
        lambda packet: packets.append(packet) or True,
    )
    window._input_state.press_modifier(0x02)
    window._input_state.press_key(0x04)
    window._input_state.set_mouse_button(0x01, True)

    window.leaveEvent(QEvent(QEvent.Type.Leave))

    assert packets == [build_keyboard_report(0, [])]
    assert window._input_state.get_keyboard_report() == (0, [0] * 6)
    assert window._input_state.mouse_buttons == 0x01
    assert window._kvm_active is True
    window.close()
    window.deleteLater()


def test_raw_key_release_outside_clears_previously_forwarded_key(
    tmp_path,
    monkeypatch,
):
    window = _window(tmp_path, monkeypatch)
    packets = []
    inside = True
    monkeypatch.setattr(
        window,
        "_keyboard_forwarding_allowed",
        lambda: inside,
    )
    monkeypatch.setattr(
        window._serial,
        "enqueue",
        lambda packet: packets.append(packet) or True,
    )

    window._on_raw_key_down(0x1E, 0x41, 0, False)
    inside = False
    window._on_raw_key_up(0x1E, 0x41, 1, False)

    assert packets[-1] == build_keyboard_report(0, [])
    assert window._input_state.get_keyboard_report() == (0, [0] * 6)
    window.close()
    window.deleteLater()
