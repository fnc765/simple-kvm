"""
capture.py -- FFmpeg-based video capture running in a QThread.

Captures frames from a UVC device (HDMI capture dongle) via PyAV/FFmpeg's
dshow device and emits them as QImage signals for display in the main window.

Uses PyAV (Python bindings for FFmpeg) instead of OpenCV because
FFmpeg's DirectShow device driver properly negotiates streaming format
with USB 3.0 UVC dongles, achieving 1080p @ 30 fps where OpenCV's
DSHOW backend is limited to ~5 fps on many devices.
"""

from __future__ import annotations

import time

import av
import numpy as np
from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QImage

# ---------------------------------------------------------------------------
# Default device name used by FFmpeg's dshow input.
# Run ``ffmpeg -list_devices true -f dshow -i dummy`` to list available names.
# ---------------------------------------------------------------------------
DEFAULT_DEVICE = "USB3. 0 capture"
DEFAULT_FPS = 30
DEFAULT_WIDTH = 1920
DEFAULT_HEIGHT = 1080
ORGANIZATION = "simple-kvm"
APP_NAME = "app"
_MAX_CONSECUTIVE_FAILURES = 30


def list_dshow_devices() -> list[str]:
    """Return a list of available DirectShow video device names.

    Uses pygrabber to enumerate DirectShow devices by their **friendly
    name** (e.g. ``"USB3. 0 capture"``), which is the format required
    by FFmpeg's dshow input.
    """
    try:
        from pygrabber.dshow_graph import FilterGraph
        graph = FilterGraph()
        return graph.get_input_devices()
    except ImportError:
        # Fallback: return just the default device
        return [DEFAULT_DEVICE]


class CaptureThread(QThread):
    """Background thread that reads frames from a UVC device via FFmpeg/PyAV.

    Signals:
        frame_ready(QImage): Emitted for every successfully decoded frame.
        fps_updated(float):  Emitted once per second with the current FPS.
        error(str):          Emitted when the device cannot be opened.
    """

    frame_ready: Signal = Signal(QImage)
    fps_updated: Signal = Signal(float)
    error: Signal = Signal(str)

    def __init__(self, device: str = DEFAULT_DEVICE, parent=None) -> None:
        super().__init__(parent)
        self._device = device
        self._capture_width: int = DEFAULT_WIDTH
        self._capture_height: int = DEFAULT_HEIGHT
        self._capture_fps: int = DEFAULT_FPS

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_device(self, device: str) -> None:
        """Update the capture device name (takes effect on next start)."""
        self._device = device

    def set_format(self, width: int, height: int, fps: int) -> None:
        """Set capture format (takes effect on next start)."""
        self._capture_width = width
        self._capture_height = height
        self._capture_fps = fps

    def stop(self) -> None:
        """Request the thread to stop and wait for it to finish."""
        self.requestInterruption()
        self.wait(3_000)

    # ------------------------------------------------------------------
    # QThread entry point
    # ------------------------------------------------------------------

    def run(self) -> None:  # noqa: D102
        # Open the device through FFmpeg's dshow driver.
        # dshow negotiates the correct media type (resolution + framerate)
        # directly with the UVC driver -- the same mechanism OBS uses.
        try:
            container = av.open(
                f"video={self._device}",
                format="dshow",
                options={
                    "framerate": str(self._capture_fps),
                    "video_size": f"{self._capture_width}x{self._capture_height}",
                },
            )
        except av.error.FFmpegError as exc:
            self.error.emit(f"Cannot open {self._device!r}: {exc}")
            return
        except Exception as exc:
            self.error.emit(f"Cannot open {self._device!r}: {exc}")
            return

        try:
            stream = container.streams.video[0]

            frame_count = 0
            fps_ts = time.monotonic()
            consecutive_failures = 0

            for packet in container.demux(stream):
                if self.isInterruptionRequested():
                    break

                try:
                    frames = list(packet.decode())
                except av.error.FFmpegError:
                    consecutive_failures += 1
                    if consecutive_failures >= _MAX_CONSECUTIVE_FAILURES:
                        self.error.emit("Capture device disconnected")
                        break
                    continue

                if not frames:
                    consecutive_failures += 1
                    if consecutive_failures >= _MAX_CONSECUTIVE_FAILURES:
                        self.error.emit("Capture device disconnected")
                        break
                    continue

                consecutive_failures = 0

                for frame in frames:
                    img: np.ndarray = frame.to_ndarray(format="bgr24")
                    h, w = img.shape[:2]
                    bytes_per_line = int(img.strides[0])

                    # QImage needs a deep copy (does not own the buffer)
                    qimage = QImage(
                        img.data, w, h, bytes_per_line,
                        QImage.Format.Format_BGR888,
                    ).copy()

                    self.frame_ready.emit(qimage)

                frame_count += len(frames)
                now = time.monotonic()
                elapsed = now - fps_ts
                if elapsed >= 1.0:
                    self.fps_updated.emit(frame_count / elapsed)
                    frame_count = 0
                    fps_ts = now

        finally:
            container.close()
