"""Offscreen Base64 clipboard UI tests with all hardware access forbidden."""

import base64
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))

from PySide6.QtCore import QSettings  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from core.keyboard_layouts import KeyboardLayout  # noqa: E402
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


def _open_and_start(window, monkeypatch, source):
    sequences = []
    monkeypatch.setattr(
        window._serial,
        "enqueue_sequence",
        lambda sequence: sequences.append(sequence) or True,
    )
    QApplication.clipboard().setText(source)
    window._on_serial_connected(True)
    window._open_base64_transfer()
    dialog = window._base64_dialog
    assert dialog is not None
    dialog.start_requested.emit()
    assert len(sequences) == 1
    return dialog, sequences[0]


def test_menu_action_tracks_connection_and_dialog_state(tmp_path, monkeypatch):
    window = _window(tmp_path, monkeypatch)

    assert window._base64_clipboard_action.isEnabled() is False
    window._on_serial_connected(True)
    assert window._base64_clipboard_action.isEnabled() is True

    QApplication.clipboard().setText("text")
    window._open_base64_transfer()
    assert window._base64_clipboard_action.isEnabled() is False

    window._base64_dialog.reject()
    assert window._base64_clipboard_action.isEnabled() is True
    window.close()
    window.deleteLater()


def test_empty_text_clipboard_does_not_open_or_queue_transfer(
    tmp_path,
    monkeypatch,
):
    window = _window(tmp_path, monkeypatch)
    sequences = []
    monkeypatch.setattr(
        window._serial,
        "enqueue_sequence",
        lambda sequence: sequences.append(sequence) or True,
    )
    QApplication.clipboard().setText("")
    window._on_serial_connected(True)

    window._open_base64_transfer()

    assert window._base64_dialog is None
    assert sequences == []
    assert "clipboard" in window.statusBar().currentMessage().lower()
    window.close()
    window.deleteLater()


def test_start_queues_only_full_standard_base64_and_updates_progress(
    tmp_path,
    monkeypatch,
):
    source = "日本語\n😀"
    window = _window(tmp_path, monkeypatch)
    dialog, sequence = _open_and_start(window, monkeypatch, source)

    expected = base64.b64encode(source.encode("utf-8")).decode("ascii")
    assert dialog.payload.encoded_text == expected
    assert sequence.progress_total == len(expected)
    assert sequence.transfer_id == window._base64_transfer_id
    assert dialog.keyboard_layout is KeyboardLayout.JIS
    assert sequence.steps[-3].data[3:6] == bytes([0x02, 0, 0x2D])
    assert window._settings.value("input/base64_keyboard_layout") == "jis"

    window._on_base64_sequence_progress(
        sequence.transfer_id,
        len(expected) // 2,
        len(expected),
    )
    assert 0 < dialog._progress.value() < 100

    window._on_base64_sequence_finished(sequence.transfer_id, "completed")
    assert window._base64_transfer_id is None
    assert dialog._progress.value() == 100
    assert "completed" in window.statusBar().currentMessage().lower()

    dialog.accept()
    window.close()
    window.deleteLater()


def test_us_layout_selection_is_used_and_persisted(tmp_path, monkeypatch):
    window = _window(tmp_path, monkeypatch)
    sequences = []
    monkeypatch.setattr(
        window._serial,
        "enqueue_sequence",
        lambda sequence: sequences.append(sequence) or True,
    )
    QApplication.clipboard().setText("A")  # QQ==
    window._on_serial_connected(True)
    window._open_base64_transfer()
    dialog = window._base64_dialog
    assert dialog is not None
    dialog._layout_combo.setCurrentIndex(
        dialog._layout_combo.findData(KeyboardLayout.US.value)
    )

    dialog.start_requested.emit()

    assert len(sequences) == 1
    assert sequences[0].steps[-3].data[3:6] == bytes([0, 0, 0x2E])
    assert window._settings.value("input/base64_keyboard_layout") == "us"

    window._on_base64_sequence_finished(
        sequences[0].transfer_id,
        "completed",
    )
    dialog.accept()
    window.close()
    window.deleteLater()


def test_cancel_button_sets_sequence_event_without_real_serial_io(
    tmp_path,
    monkeypatch,
):
    window = _window(tmp_path, monkeypatch)
    dialog, sequence = _open_and_start(window, monkeypatch, "cancel 日本語")

    dialog.request_cancel()

    assert sequence.cancel_event is not None
    assert sequence.cancel_event.is_set() is True
    window._on_base64_sequence_finished(sequence.transfer_id, "cancelled")
    assert "cancelled" in dialog._status_label.text().lower()

    dialog.accept()
    window.close()
    window.deleteLater()


def test_heartbeat_is_not_queued_while_base64_transfer_is_active(
    tmp_path,
    monkeypatch,
):
    window = _window(tmp_path, monkeypatch)
    queued = []
    monkeypatch.setattr(window._serial, "isRunning", lambda: True)
    monkeypatch.setattr(
        window._serial,
        "enqueue",
        lambda packet: queued.append(packet) or True,
    )

    window._base64_transfer_id = "active-transfer"
    window._send_heartbeat()
    assert queued == []

    window._base64_transfer_id = None
    window._send_heartbeat()
    assert len(queued) == 1
    window.close()
    window.deleteLater()
