"""Hardware-free tests for ordered absolute mouse transactions."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))

from core.absolute_mouse import (  # noqa: E402
    build_absolute_button_transition,
    build_absolute_click,
)
from core.protocol import build_mouse_abs_report  # noqa: E402
from core.serial_comm import _write_queue_item  # noqa: E402


class FakeSerial:
    def __init__(self):
        self.writes = []

    def write(self, data):
        self.writes.append(data)


def _write(sequence):
    fake = FakeSerial()
    _write_queue_item(fake, sequence, sleeper=lambda _seconds: None)
    return fake.writes


def test_click_is_move_then_down_then_up_at_one_absolute_coordinate():
    sequence = build_absolute_click(0x01, 1234, 2345)

    assert _write(sequence) == [
        build_mouse_abs_report(0x00, 1234, 2345),
        build_mouse_abs_report(0x01, 1234, 2345),
        build_mouse_abs_report(0x00, 1234, 2345),
    ]
    assert sequence.cleanup_data == build_mouse_abs_report(0, 1234, 2345)


def test_drag_release_moves_while_held_before_releasing_at_endpoint():
    sequence = build_absolute_button_transition(0x01, 0x00, 30000, 20000)

    assert _write(sequence) == [
        build_mouse_abs_report(0x01, 30000, 20000),
        build_mouse_abs_report(0x00, 30000, 20000),
    ]


def test_multi_button_transition_preserves_other_held_buttons():
    sequence = build_absolute_button_transition(0x01, 0x03, 10, 20)

    assert _write(sequence) == [
        build_mouse_abs_report(0x01, 10, 20),
        build_mouse_abs_report(0x03, 10, 20),
    ]
