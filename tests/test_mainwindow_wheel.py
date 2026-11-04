"""Exercise wheel delivery through the video widget and Qt's window dispatch."""

import os
import sys

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))

from PySide6.QtCore import QPoint, QPointF, QSettings  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from core.mouse_modes import MouseMode  # noqa: E402
from ui.mainwindow import MainWindow  # noqa: E402


app = QApplication.instance() or QApplication([])


@pytest.fixture(params=list(MouseMode))
def wheel_window(request, tmp_path, monkeypatch):
    def unexpected_start(*_args, **_kwargs):
        raise AssertionError("hardware-backed thread started in a wheel test")

    monkeypatch.setattr("ui.mainwindow.SerialComm.start", unexpected_start)
    monkeypatch.setattr("ui.mainwindow.CaptureThread.start", unexpected_start)
    monkeypatch.setattr(MainWindow, "_setup_raw_input", lambda _self: None)
    window = MainWindow(
        settings=QSettings(str(tmp_path / "settings.ini"), QSettings.IniFormat),
        auto_connect=False,
    )
    window._mouse_mode = request.param
    window._firmware_abs_supported = True
    window.show()
    app.processEvents()
    window._set_kvm_active(True)
    packets = []
    monkeypatch.setattr(
        window._serial, "enqueue", lambda packet: packets.append(packet) or True,
    )
    yield window, packets
    window._set_kvm_active(False)
    window.close()
    window.deleteLater()


def _scroll(window, delta):
    position = window._video_widget.mapTo(window, QPoint(100, 100))
    QTest.wheelEvent(window.windowHandle(), QPointF(position), QPoint(0, delta))
    app.processEvents()


@pytest.mark.parametrize(("deltas", "ticks"), [
    ([120], [1]),
    ([-120], [-1]),
    ([240], [2]),
    ([-240], [-2]),
    ([30, 30, 30, 30], [1]),
    ([-30, -30, -30, -30], [-1]),
    ([60, -60], []),
    ([180, 60], [1, 1]),
    ([-180, -60], [-1, -1]),
    ([-60, 120, 60], [1]),
    ([0], []),
    ([120 * 300], [127, 127, 46]),
    ([-120 * 300], [-127, -127, -46]),
])
def test_wheel_preserves_rotation_and_fractional_steps(wheel_window, deltas, ticks):
    window, packets = wheel_window
    for delta in deltas:
        _scroll(window, delta)

    assert [int.from_bytes(p[6:7], "little", signed=True) for p in packets] == ticks
    assert all(p[1:3] == b"\x02\x05" and p[4:6] == b"\x00\x00" for p in packets)


def test_wheel_button_state_stays_on_the_correct_interface(wheel_window):
    window, packets = wheel_window
    window._input_state.mouse_buttons = 0x05
    _scroll(window, 240)

    buttons = 0 if window._effective_mode is MouseMode.ABSOLUTE else 0x05
    assert len(packets) == 1
    assert packets[0][3] == buttons
    assert packets[0][6] == 2


def test_wheel_remainder_does_not_cross_kvm_sessions(wheel_window):
    window, packets = wheel_window
    _scroll(window, 60)
    window._set_kvm_active(False)
    packets.clear()
    _scroll(window, 120)
    assert packets == []

    window._set_kvm_active(True)
    _scroll(window, 60)
    assert packets == []
    _scroll(window, 60)
    assert len(packets) == 1
    assert packets[0][6] == 1
