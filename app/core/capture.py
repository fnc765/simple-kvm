"""
capture.py – OpenCV VideoCapture loop running in a QThread.

Captures frames from a UVC device (HDMI capture dongle) and emits them
as QImage signals for display in the main window.
"""

from __future__ import annotations

import sys
import time

import cv2
from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QImage

# Use DirectShow on Windows for lower latency; fall back to platform default
CAP_BACKEND = cv2.CAP_DSHOW if sys.platform == "win32" else cv2.CAP_ANY

_MAX_CONSECUTIVE_FAILURES = 30


class CaptureThread(QThread):
    """
    Background thread that continuously reads frames from an OpenCV capture
    device and emits them as :class:`~PySide6.QtGui.QImage` objects.

    Signals:
        frame_ready(QImage): Emitted for every successfully decoded frame.
        fps_updated(float):  Emitted once per second with the current FPS.
        error(str):          Emitted when the device cannot be opened or disconnects.
    """

    frame_ready: Signal = Signal(QImage)
    fps_updated: Signal = Signal(float)
    error: Signal = Signal(str)

    def __init__(self, device_index: int = 0, parent=None) -> None:
        super().__init__(parent)
        self._device_index = device_index

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_device(self, index: int) -> None:
        """Update the capture device index (takes effect on next start)."""
        self._device_index = index

    def stop(self) -> None:
        """Request the thread to stop and wait for it to finish."""
        self.requestInterruption()
        self.wait()

    # ------------------------------------------------------------------
    # QThread entry point
    # ------------------------------------------------------------------

    def run(self) -> None:  # noqa: D102
        cap = cv2.VideoCapture(self._device_index, CAP_BACKEND)
        if not cap.isOpened():
            self.error.emit(f"Device {self._device_index} could not be opened")
            return

        try:
            # Minimise buffering for the lowest possible latency
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            cap.set(cv2.CAP_PROP_FPS, 60)

            frame_count          = 0
            fps_ts               = time.monotonic()
            consecutive_failures = 0

            while not self.isInterruptionRequested():
                ret, frame = cap.read()
                if not ret:
                    consecutive_failures += 1
                    if consecutive_failures >= _MAX_CONSECUTIVE_FAILURES:
                        self.error.emit("Capture device disconnected")
                        break
                    self.msleep(10)
                    continue
                consecutive_failures = 0

                # Resize to the display resolution
                frame_resized = cv2.resize(frame, (640, 480))
                frame_rgb     = cv2.cvtColor(frame_resized, cv2.COLOR_BGR2RGB)

                h, w, ch = frame_rgb.shape
                bytes_per_line = ch * w
                # .copy() is essential: QImage does not own the NumPy buffer
                qimage = QImage(
                    frame_rgb.data, w, h, bytes_per_line,
                    QImage.Format.Format_RGB888,
                ).copy()

                self.frame_ready.emit(qimage)

                frame_count += 1
                now      = time.monotonic()
                elapsed  = now - fps_ts
                if elapsed >= 1.0:
                    self.fps_updated.emit(frame_count / elapsed)
                    frame_count = 0
                    fps_ts      = now

        finally:
            cap.release()
