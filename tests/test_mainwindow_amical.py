"""Offscreen integration tests for Amical paste capture."""

import os
import sys
from threading import Event

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))

from PySide6.QtCore import QEvent, QSettings, Qt  # noqa: E402
from PySide6.QtGui import QKeyEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

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
    return MainWindow(settings=settings, auto_connect=False)


def _native_key(event_type, key, modifiers, vk, text=""):
    return QKeyEvent(
        event_type,
        key,
        modifiers,
        0,  # Amical SendInput leaves native scan code at zero.
        vk,
        0x02 if modifiers & Qt.KeyboardModifier.ControlModifier else 0,
        text,
        False,
        1,
    )


def test_f9_then_injected_ctrl_v_queues_romaji_sequence(tmp_path, monkeypatch):
    window = _window(tmp_path, monkeypatch)
    normal_packets = []
    sequences = []
    monkeypatch.setattr(
        window._serial,
        "enqueue",
        lambda packet: normal_packets.append(packet) or True,
    )
    monkeypatch.setattr(
        window._serial,
        "enqueue_sequence",
        lambda sequence: sequences.append(sequence) or True,
    )

    window._amical_enabled_action.setChecked(True)
    window._connected = True
    window._kvm_active = True
    window._use_raw_input = True

    window._on_raw_key_down(0x43, 0x78, 0, False)
    window._on_raw_key_up(0x43, 0x78, 1, False)
    assert window._amical_gate.is_waiting() is True
    assert normal_packets == []  # F9 is reserved, not forwarded to target.

    QApplication.clipboard().setText("今日はテスト123です。")
    ctrl_down = _native_key(
        QEvent.Type.KeyPress,
        Qt.Key.Key_Control,
        Qt.KeyboardModifier.ControlModifier,
        0x11,
    )
    paste_down = _native_key(
        QEvent.Type.KeyPress,
        Qt.Key.Key_V,
        Qt.KeyboardModifier.ControlModifier,
        0x56,
        "\x16",
    )
    window.keyPressEvent(ctrl_down)
    window.keyPressEvent(paste_down)

    assert len(sequences) == 1
    assert len(sequences[0].steps) == 2 * len("konnichiha tesuto 123 desu") + 2
    assert "Queued Amical romaji" in window.statusBar().currentMessage()
    assert window._amical_gate.is_waiting() is False

    window.close()
    window.deleteLater()


def test_feature_is_opt_in_and_uses_production_menu_label(tmp_path, monkeypatch):
    window = _window(tmp_path, monkeypatch)

    assert window._amical_enabled_action.isChecked() is False
    assert window._amical_enabled_action.text() == "Amical Romaji Forwarding"
    assert "POC" not in window._amical_enabled_action.text()

    window.close()
    window.deleteLater()


def test_enabled_setting_is_restored(tmp_path, monkeypatch):
    settings_path = tmp_path / "settings.ini"
    settings = QSettings(str(settings_path), QSettings.Format.IniFormat)
    settings.setValue("input/amical_romaji_enabled", "true")
    settings.sync()

    def unexpected_start(*_args, **_kwargs):
        raise AssertionError("a hardware-backed thread was started")

    monkeypatch.setattr("ui.mainwindow.SerialComm.start", unexpected_start)
    monkeypatch.setattr("ui.mainwindow.CaptureThread.start", unexpected_start)
    window = MainWindow(settings=settings, auto_connect=False)

    assert window._amical_enabled is True
    assert window._amical_enabled_action.isChecked() is True

    window.close()
    window.deleteLater()


def test_injected_ctrl_v_without_f9_is_ignored(tmp_path, monkeypatch):
    window = _window(tmp_path, monkeypatch)
    sequences = []
    monkeypatch.setattr(
        window._serial,
        "enqueue_sequence",
        lambda sequence: sequences.append(sequence) or True,
    )
    window._amical_enabled_action.setChecked(True)
    window._connected = True
    window._kvm_active = True
    window._use_raw_input = True

    paste_down = _native_key(
        QEvent.Type.KeyPress,
        Qt.Key.Key_V,
        Qt.KeyboardModifier.ControlModifier,
        0x56,
        "\x16",
    )
    window.keyPressEvent(paste_down)

    assert sequences == []
    window.close()
    window.deleteLater()


def test_disabling_feature_cancels_queued_typing(tmp_path, monkeypatch):
    window = _window(tmp_path, monkeypatch)
    window._amical_enabled_action.setChecked(True)
    cancel_event = Event()
    window._amical_send_cancel = cancel_event

    window._amical_enabled_action.setChecked(False)

    assert cancel_event.is_set() is True
    assert window._amical_send_cancel is None
    window.close()
    window.deleteLater()
