"""
serial_comm.py – Non-blocking serial communication running in a QThread.

Packets are enqueued from the main thread and written to the serial port
by this background thread, keeping the UI responsive at all times.
"""

from __future__ import annotations

import queue
import re
import time
from dataclasses import dataclass
from enum import Enum
from threading import Event
from typing import Callable

import serial
from PySide6.QtCore import QThread, Signal

_COM_PORT_RE = re.compile(r'^COM\d{1,3}$', re.IGNORECASE)


@dataclass(frozen=True)
class PacketStep:
    """One packet in an atomic sequence, followed by an optional delay."""

    data: bytes
    delay_after_ms: int = 0
    progress_units: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.data, bytes) or not self.data:
            raise ValueError("packet data must be non-empty bytes")
        if self.delay_after_ms < 0:
            raise ValueError("packet delay cannot be negative")
        if self.progress_units < 0:
            raise ValueError("packet progress units cannot be negative")


@dataclass(frozen=True)
class PacketSequence:
    """Packets admitted to the send queue as one indivisible item."""

    steps: tuple[PacketStep, ...]
    cleanup_data: bytes | None = None
    cancel_event: Event | None = None
    transfer_id: str | None = None
    progress_total: int = 0

    def __post_init__(self) -> None:
        if not self.steps:
            raise ValueError("packet sequence must contain at least one step")
        if self.cleanup_data is not None and (
            not isinstance(self.cleanup_data, bytes) or not self.cleanup_data
        ):
            raise ValueError("sequence cleanup data must be non-empty bytes")
        if self.progress_total < 0:
            raise ValueError("sequence progress total cannot be negative")
        if self.progress_total and not self.transfer_id:
            raise ValueError("tracked sequence requires a transfer id")
        progress_units = sum(step.progress_units for step in self.steps)
        if progress_units != self.progress_total:
            raise ValueError(
                "sequence progress total must equal its step progress units"
            )


class SequenceOutcome(str, Enum):
    """Terminal result for one queued packet sequence."""

    COMPLETED = "completed"
    CANCELLED = "cancelled"


QueueItem = bytes | PacketSequence


def _write_cleanup(ser, item: PacketSequence) -> None:
    if item.cleanup_data is None:
        return
    try:
        ser.write(item.cleanup_data)
    except Exception:
        pass


def _write_queue_item(
    ser,
    item: QueueItem,
    sleeper=time.sleep,
    should_stop: Callable[[], bool] | None = None,
    on_progress: Callable[[int, int], None] | None = None,
) -> SequenceOutcome | None:
    """Write a normal packet or a complete atomic sequence to *ser*."""
    if isinstance(item, bytes):
        ser.write(item)
        return None

    completed_units = 0
    try:
        for step in item.steps:
            if (should_stop is not None and should_stop()) or (
                item.cancel_event is not None
                and item.cancel_event.is_set()
            ):
                _write_cleanup(ser, item)
                return SequenceOutcome.CANCELLED
            ser.write(step.data)
            if step.progress_units:
                completed_units += step.progress_units
                if on_progress is not None:
                    on_progress(completed_units, item.progress_total)
            if step.delay_after_ms:
                sleeper(step.delay_after_ms / 1_000)
    except Exception:
        _write_cleanup(ser, item)
        raise
    return SequenceOutcome.COMPLETED


class SerialComm(QThread):
    """
    Background thread that owns a :class:`serial.Serial` connection and
    drains a send queue in a tight loop.

    Signals:
        connected(bool): Emitted when the port is opened (True) or
                         closed / errored (False).
    """

    connected: Signal = Signal(bool)
    sequence_progress: Signal = Signal(str, int, int)
    sequence_finished: Signal = Signal(str, str)

    _SEND_TIMEOUT = 0.05  # seconds to wait for a new packet before looping

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._port    = ""
        self._baud    = 115_200
        self._queue: queue.Queue[QueueItem] = queue.Queue(maxsize=64)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_port(self, port: str, baud: int = 115_200) -> None:
        """Configure the serial port (call before :meth:`start`)."""
        if port and not _COM_PORT_RE.fullmatch(port):
            raise ValueError(f"Invalid COM port: {port!r}")
        self._port = port
        self._baud = baud

    def enqueue(self, data: bytes) -> bool:
        """
        Thread-safe: add *data* to the send queue.

        Returns True if enqueued, False if the queue is full (packet dropped).
        """
        try:
            self._queue.put_nowait(data)
            return True
        except queue.Full:
            return False

    def enqueue_sequence(self, sequence: PacketSequence) -> bool:
        """Atomically queue all steps in *sequence* as a single item."""
        try:
            self._queue.put_nowait(sequence)
            return True
        except queue.Full:
            return False

    def stop(self) -> None:
        """Request shutdown and wait for the thread to finish."""
        self.requestInterruption()
        self.wait(5_000)

    # ------------------------------------------------------------------
    # QThread entry point
    # ------------------------------------------------------------------

    def run(self) -> None:  # noqa: D102
        try:
            with serial.Serial(
                self._port, self._baud,
                timeout=0.1, write_timeout=1.0,
            ) as ser:
                self.connected.emit(True)

                while not self.isInterruptionRequested():
                    try:
                        item = self._queue.get(timeout=self._SEND_TIMEOUT)
                        transfer_id = (
                            item.transfer_id
                            if isinstance(item, PacketSequence)
                            else None
                        )
                        progress_callback = None
                        if transfer_id is not None:
                            def progress_callback(
                                completed: int,
                                total: int,
                                tracked: str = transfer_id,
                            ) -> None:
                                self.sequence_progress.emit(
                                    tracked, completed, total
                                )
                        try:
                            outcome = _write_queue_item(
                                ser,
                                item,
                                should_stop=self.isInterruptionRequested,
                                on_progress=progress_callback,
                            )
                        except Exception:
                            if transfer_id is not None:
                                self.sequence_finished.emit(
                                    transfer_id, "failed"
                                )
                            raise
                        if transfer_id is not None and outcome is not None:
                            self.sequence_finished.emit(
                                transfer_id, outcome.value
                            )
                    except queue.Empty:
                        pass  # nothing to send; loop back
                    except serial.SerialTimeoutException:
                        break

        except serial.SerialException:
            pass  # connection failed; emit False in finally
        finally:
            self.connected.emit(False)
