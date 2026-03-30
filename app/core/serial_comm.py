"""
serial_comm.py – Non-blocking serial communication running in a QThread.

Packets are enqueued from the main thread and written to the serial port
by this background thread, keeping the UI responsive at all times.
"""

from __future__ import annotations

import queue
import re

import serial
from PySide6.QtCore import QThread, Signal

_COM_PORT_RE = re.compile(r'^COM\d{1,3}$', re.IGNORECASE)


class SerialComm(QThread):
    """
    Background thread that owns a :class:`serial.Serial` connection and
    drains a send queue in a tight loop.

    Signals:
        connected(bool): Emitted when the port is opened (True) or
                         closed / errored (False).
    """

    connected: Signal = Signal(bool)

    _SEND_TIMEOUT = 0.05  # seconds to wait for a new packet before looping

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._port    = ""
        self._baud    = 115_200
        self._queue: queue.Queue[bytes] = queue.Queue(maxsize=64)

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

    def stop(self) -> None:
        """Request shutdown and wait for the thread to finish."""
        self.requestInterruption()
        self.wait()

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
                        data = self._queue.get(timeout=self._SEND_TIMEOUT)
                        ser.write(data)
                    except queue.Empty:
                        pass  # nothing to send; loop back
                    except serial.SerialTimeoutException:
                        break

        except serial.SerialException:
            pass  # connection failed; emit False in finally
        finally:
            self.connected.emit(False)
