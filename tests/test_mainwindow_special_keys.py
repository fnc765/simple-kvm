"""Offscreen UI tests for the special-key menu (no hardware access)."""

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))

from PySide6.QtCore import QSettings  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from ui.mainwindow import MainWindow  # noqa: E402


app = QApplication.instance() or QApplication([])


EXPECTED_ACTIONS = {
    "ctrl_alt_delete": "Ctrl+Alt+Delete",
    "ctrl_shift_escape": "Ctrl+Shift+Esc",
    "alt_f4": "Alt+F4",
    "win_l": "Win+L",
    "win_r": "Win+R",
    "command_option_escape": "Command+Option+Esc",
    "delete": "Delete",
    "f2": "F2",
    "f12": "F12",
}


def _window(tmp_path, monkeypatch):
    settings = QSettings(
        str(tmp_path / "settings.ini"),
        QSettings.Format.IniFormat,
    )

    def unexpected_start(*_args, **_kwargs):
        raise AssertionError("a hardware-backed thread was started during a UI test")

    monkeypatch.setattr("ui.mainwindow.SerialComm.start", unexpected_start)
    monkeypatch.setattr("ui.mainwindow.CaptureThread.start", unexpected_start)
    return MainWindow(settings=settings, auto_connect=False)


def test_special_key_action_tracks_connection_state(tmp_path, monkeypatch):
    window = _window(tmp_path, monkeypatch)

    assert {
        preset_id: action.text()
        for preset_id, action in window._special_key_actions.items()
    } == EXPECTED_ACTIONS
    assert all(
        not action.isEnabled()
        for action in window._special_key_actions.values()
    )

    window._on_serial_connected(True)
    assert all(
        action.isEnabled()
        for action in window._special_key_actions.values()
    )

    window._on_serial_connected(False)
    assert all(
        not action.isEnabled()
        for action in window._special_key_actions.values()
    )
    window.close()
    window.deleteLater()


def test_trigger_enqueues_one_sequence_without_mutating_physical_state(
    tmp_path, monkeypatch,
):
    window = _window(tmp_path, monkeypatch)
    captured = []
    monkeypatch.setattr(
        window._serial,
        "enqueue_sequence",
        lambda sequence: captured.append(sequence) or True,
    )
    window._input_state.press_modifier(0x02)
    window._input_state.press_key(0x04)
    before = window._input_state.get_keyboard_report()

    window._on_serial_connected(True)
    window._special_key_actions["ctrl_alt_delete"].trigger()

    assert len(captured) == 1
    assert window._input_state.get_keyboard_report() == before
    assert "Ctrl+Alt+Delete" in window.statusBar().currentMessage()
    window.close()
    window.deleteLater()


def test_queue_full_is_reported_as_not_sent(tmp_path, monkeypatch):
    window = _window(tmp_path, monkeypatch)
    monkeypatch.setattr(window._serial, "enqueue_sequence", lambda _sequence: False)

    window._on_serial_connected(True)
    window._special_key_actions["ctrl_alt_delete"].trigger()

    assert "not sent" in window.statusBar().currentMessage().lower()
    window.close()
    window.deleteLater()
