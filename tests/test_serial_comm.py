"""Hardware-free tests for atomic serial packet sequences."""

import os
import queue
import sys
from threading import Event

import pytest
import serial

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))

from core.serial_comm import (  # noqa: E402
    PacketSequence,
    PacketStep,
    SerialComm,
    _write_queue_item,
)


class FakeSerial:
    def __init__(self):
        self.writes = []

    def write(self, data):
        self.writes.append(data)


def _sequence():
    return PacketSequence((
        PacketStep(b"press", 20),
        PacketStep(b"release", 10),
        PacketStep(b"release", 0),
    ))


def test_enqueue_sequence_uses_one_atomic_queue_slot():
    comm = SerialComm()
    sequence = _sequence()

    assert comm.enqueue_sequence(sequence) is True
    assert comm._queue.qsize() == 1
    assert comm._queue.get_nowait() == sequence


def test_enqueue_sequence_rejects_the_whole_item_when_queue_is_full():
    comm = SerialComm()
    comm._queue = queue.Queue(maxsize=1)
    comm._queue.put_nowait(b"existing")

    assert comm.enqueue_sequence(_sequence()) is False
    assert comm._queue.qsize() == 1
    assert comm._queue.get_nowait() == b"existing"


def test_write_queue_item_preserves_order_and_delays_without_real_serial():
    fake = FakeSerial()
    sleeps = []

    _write_queue_item(fake, _sequence(), sleeper=sleeps.append)

    assert fake.writes == [b"press", b"release", b"release"]
    assert sleeps == [0.020, 0.010]


def test_write_queue_item_still_supports_an_ordinary_packet():
    fake = FakeSerial()

    _write_queue_item(fake, b"ordinary", sleeper=lambda _seconds: None)

    assert fake.writes == [b"ordinary"]


def test_sequence_attempts_cleanup_after_a_mid_sequence_timeout():
    class TimeoutOnFirstRelease(FakeSerial):
        def __init__(self):
            super().__init__()
            self.calls = 0

        def write(self, data):
            self.calls += 1
            if self.calls == 2:
                raise serial.SerialTimeoutException("simulated timeout")
            super().write(data)

    fake = TimeoutOnFirstRelease()
    sequence = PacketSequence(
        (
            PacketStep(b"press", 20),
            PacketStep(b"release", 10),
            PacketStep(b"release", 0),
        ),
        cleanup_data=b"release",
    )

    with pytest.raises(serial.SerialTimeoutException):
        _write_queue_item(fake, sequence, sleeper=lambda _seconds: None)

    assert fake.writes == [b"press", b"release"]


def test_cancelled_sequence_stops_and_sends_cleanup():
    fake = FakeSerial()
    cancel = Event()
    sleeps = []

    def cancel_after_first_step(seconds):
        sleeps.append(seconds)
        cancel.set()

    sequence = PacketSequence(
        (
            PacketStep(b"press", 10),
            PacketStep(b"release", 10),
            PacketStep(b"next", 0),
        ),
        cleanup_data=b"cleanup",
        cancel_event=cancel,
    )

    _write_queue_item(fake, sequence, sleeper=cancel_after_first_step)

    assert sleeps == [0.010]
    assert fake.writes == [b"press", b"cleanup"]


def test_stop_wait_budget_covers_a_complete_three_write_sequence():
    class StopProbe(SerialComm):
        def __init__(self):
            super().__init__()
            self.interruption_requested = False
            self.waited_ms = 0

        def requestInterruption(self):
            self.interruption_requested = True

        def wait(self, milliseconds):
            self.waited_ms = milliseconds
            return True

    comm = StopProbe()
    comm.stop()

    assert comm.interruption_requested is True
    assert comm.waited_ms >= 4_100
