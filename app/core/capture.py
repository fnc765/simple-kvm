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


def _detect_best_1080p_fps(cap: cv2.VideoCapture) -> int:
    """MJPEG + 1920x1080 で対応する最高 fps を検出して返す。

    fps 候補を高い順に試し、実際のフレーム取得速度が要求値の 70% 以上であれば
    その fps を採用する。全候補で達成できなければ 15 を返す。
    """
    candidates = [60, 50, 30, 25, 20, 15]

    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)

    for fps in candidates:
        cap.set(cv2.CAP_PROP_FPS, fps)

        # ウォームアップ（2フレーム破棄）
        for _ in range(2):
            cap.grab()

        # 実測（5フレーム計測）
        start = time.perf_counter()
        acquired = 0
        for _ in range(5):
            if cap.grab():
                acquired += 1
        elapsed = time.perf_counter() - start

        if acquired < 3:
            continue  # フレームが取れない

        actual_fps = acquired / elapsed
        if actual_fps >= fps * 0.70:
            return fps

    return 15  # フォールバック


def enumerate_capture_formats(
    device_index: int,
    backend: int = CAP_BACKEND,
) -> list[tuple[int, int, int]]:
    """デバイスが対応する (width, height, fps) の組み合わせを列挙して返す。

    MJPEG フォーマットで各解像度・fps の組み合わせを実測し、
    実際に取得できたものだけをリストアップする。
    """
    RESOLUTIONS = [(1920, 1080), (1280, 720), (640, 480)]
    FPS_CANDIDATES = [60, 30, 15]

    cap = cv2.VideoCapture(device_index, backend)
    supported: list[tuple[int, int, int]] = []

    try:
        if not cap.isOpened():
            return []
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        for w, h in RESOLUTIONS:
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, w)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, h)

            for fps in FPS_CANDIDATES:
                cap.set(cv2.CAP_PROP_FPS, fps)

                # ウォームアップ (2フレーム破棄)
                for _ in range(2):
                    cap.grab()

                # 実測 (3フレーム)
                start = time.perf_counter()
                count = sum(1 for _ in range(3) if cap.grab())
                elapsed = time.perf_counter() - start

                if count >= 2 and elapsed > 0 and count / elapsed >= fps * 0.65:
                    supported.append((w, h, fps))
    finally:
        cap.release()

    return supported


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
        self._capture_width: int | None = None
        self._capture_height: int | None = None
        self._capture_fps: int | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_device(self, index: int) -> None:
        """Update the capture device index (takes effect on next start)."""
        self._device_index = index

    def set_format(
        self,
        width: int | None,
        height: int | None,
        fps: int | None,
    ) -> None:
        """キャプチャフォーマットを設定する (None の場合は自動検出)。"""
        self._capture_width = width
        self._capture_height = height
        self._capture_fps = fps

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
            # 高画質のためMJPEGフォーマットを要求（YUY2よりUSB帯域が少なく高解像度に対応）
            cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
            if self._capture_width and self._capture_height and self._capture_fps:
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, self._capture_width)
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self._capture_height)
                cap.set(cv2.CAP_PROP_FPS, self._capture_fps)
            else:
                best_fps = _detect_best_1080p_fps(cap)
                cap.set(cv2.CAP_PROP_FPS, best_fps)

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

                frame_rgb      = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

                h, w = frame_rgb.shape[:2]
                bytes_per_line = int(frame_rgb.strides[0])
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
