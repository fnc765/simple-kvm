"""
mainwindow.py – Main application window.

Layout
------
  ┌──────────────────────────────────────────┐
  │  MenuBar: File > Settings / Quit         │
  ├──────────────────────────────────────────┤
  │  VideoWidget (640 × 480 QLabel)          │
  │  Click here to enter KVM focus mode.     │
  │  Press Esc to exit focus mode.           │
  ├──────────────────────────────────────────┤
  │  StatusBar: connection state  |  FPS     │
  └──────────────────────────────────────────┘

Focus mode
----------
When the user clicks inside the VideoWidget:
  - Mouse cursor is hidden (BlankCursor).
  - Cursor is kept locked at the VideoWidget centre via QCursor.setPos().
  - mouseMoveEvent computes relative displacement from the centre position,
    sends a mouse packet, then resets the cursor back to centre.
  - All keyboard events are forwarded to the target instead of the host OS.
  - Press Esc or click outside to exit.
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtGui import (
    QCursor,
    QImage,
    QKeyEvent,
    QMouseEvent,
    QPixmap,
    QWheelEvent,
)
from PySide6.QtWidgets import (
    QApplication,
    QLabel,
    QMainWindow,
    QMenu,
    QMenuBar,
    QStatusBar,
)

from core.capture import CaptureThread
from core.input_hook import InputState
from core.keymap import get_modifier_bit, is_modifier_key, qt_key_to_hid
from core.protocol import build_heartbeat, build_keyboard_report, build_mouse_report
from core.serial_comm import SerialComm
from ui.settings_dialog import SettingsDialog


class VideoWidget(QLabel):
    """640 × 480 label that displays the HDMI capture feed."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFixedSize(640, 480)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet("background: #111;")
        self.setText("No Signal – click to start capture")


class MainWindow(QMainWindow):
    """Top-level KVM window."""

    _HEARTBEAT_INTERVAL_MS = 1_000

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("simple-kvm")

        # ---- Video widget ---------------------------------------------------
        self._video_widget = VideoWidget(self)
        self.setCentralWidget(self._video_widget)

        # ---- Status bar -----------------------------------------------------
        self._status = QStatusBar()
        self.setStatusBar(self._status)
        self._status.showMessage("Disconnected – open File > Settings to connect")

        # ---- Menu bar -------------------------------------------------------
        menu_bar = QMenuBar(self)
        self.setMenuBar(menu_bar)
        file_menu = QMenu("File", self)
        menu_bar.addMenu(file_menu)
        file_menu.addAction("Settings…", self._open_settings)
        file_menu.addSeparator()
        file_menu.addAction("Quit", QApplication.quit)

        # ---- Input / KVM state ----------------------------------------------
        self._kvm_active    = False
        self._center        = QPoint()       # VideoWidget centre in global coords
        self._input_state   = InputState()
        self._warp_pending  = False          # True while cursor warp is in-flight

        # ---- Serial communication -------------------------------------------
        self._serial = SerialComm(self)
        self._serial.connected.connect(self._on_serial_connected)

        # ---- Capture thread -------------------------------------------------
        self._capture = CaptureThread(0, self)
        self._capture.frame_ready.connect(self._on_frame_ready)
        self._capture.fps_updated.connect(self._on_fps_update)

        # ---- Stored settings ------------------------------------------------
        self._port           = ""
        self._capture_index  = 0
        self._connected      = False

        # ---- Heartbeat timer ------------------------------------------------
        self._hb_timer = QTimer(self)
        self._hb_timer.timeout.connect(self._send_heartbeat)
        self._hb_timer.start(self._HEARTBEAT_INTERVAL_MS)

        # Enable mouse tracking so we receive move events without click
        self.setMouseTracking(True)
        self._video_widget.setMouseTracking(True)

        self.resize(640, self._video_widget.height() + 60)

        # Focus-loss guard: deactivate KVM when any other window gains focus
        QApplication.instance().focusChanged.connect(self._on_focus_changed)

    # -------------------------------------------------------------------------
    # Settings
    # -------------------------------------------------------------------------

    def _open_settings(self) -> None:
        dlg = SettingsDialog(self._port, self._capture_index, self)
        if dlg.exec():
            port, device = dlg.get_values()
            if port != self._port or device != self._capture_index:
                self._port          = port
                self._capture_index = device
                self._apply_settings()

    def _apply_settings(self) -> None:
        self._set_kvm_active(False)

        # Restart serial
        self._serial.stop()
        if self._port:
            self._serial.set_port(self._port)
            self._serial.start()

        # Restart capture
        self._capture.stop()
        self._capture.set_device(self._capture_index)
        self._capture.start()

    # -------------------------------------------------------------------------
    # Serial / capture callbacks
    # -------------------------------------------------------------------------

    def _on_serial_connected(self, connected: bool) -> None:
        self._connected = connected
        if connected:
            self._status.showMessage(f"Connected: {self._port}")
        else:
            self._status.showMessage("Disconnected")

    def _on_frame_ready(self, image: QImage) -> None:
        pixmap = QPixmap.fromImage(image)
        self._video_widget.setPixmap(
            pixmap.scaled(
                self._video_widget.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )

    def _on_fps_update(self, fps: float) -> None:
        port_part = f"Connected: {self._port}" if self._connected else "Disconnected"
        self._status.showMessage(f"{port_part}  |  FPS: {fps:.1f}")

    def _send_heartbeat(self) -> None:
        if self._serial.isRunning():
            self._serial.enqueue(build_heartbeat())

    # -------------------------------------------------------------------------
    # Focus / KVM active mode
    # -------------------------------------------------------------------------

    def _set_kvm_active(self, active: bool) -> None:
        if self._kvm_active == active:
            return
        self._kvm_active = active

        if active:
            self.menuBar().setEnabled(False)
            self.setCursor(Qt.CursorShape.BlankCursor)
            # Compute the VideoWidget centre in global screen coordinates
            self._center = self._video_widget.mapToGlobal(
                QPoint(
                    self._video_widget.width()  // 2,
                    self._video_widget.height() // 2,
                )
            )
            QCursor.setPos(self._center)
            self._status.showMessage(
                f"{self._port} – KVM active (Esc to release)"
            )
        else:
            self.menuBar().setEnabled(True)
            self.unsetCursor()
            # Release all held keys/buttons
            self._input_state.clear_keys()
            modifier, keys = self._input_state.get_keyboard_report()
            self._serial.enqueue(build_keyboard_report(modifier, keys))
            self._serial.enqueue(build_mouse_report(0, 0, 0))
            if self._connected:
                self._status.showMessage(f"Connected: {self._port}")

    # -------------------------------------------------------------------------
    # Mouse events
    # -------------------------------------------------------------------------

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if not self._kvm_active:
            # Enter KVM mode when clicking inside the VideoWidget area
            local = self._video_widget.mapFromGlobal(
                event.globalPosition().toPoint()
            )
            in_widget = (
                0 <= local.x() < self._video_widget.width()
                and 0 <= local.y() < self._video_widget.height()
            )
            if in_widget:
                self._set_kvm_active(True)
            return

        btn = event.button()
        if btn == Qt.MouseButton.LeftButton:
            self._input_state.set_mouse_button(0x01, True)
        elif btn == Qt.MouseButton.RightButton:
            self._input_state.set_mouse_button(0x02, True)
        elif btn == Qt.MouseButton.MiddleButton:
            self._input_state.set_mouse_button(0x04, True)

        self._serial.enqueue(
            build_mouse_report(self._input_state.mouse_buttons, 0, 0)
        )

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if not self._kvm_active:
            return

        btn = event.button()
        if btn == Qt.MouseButton.LeftButton:
            self._input_state.set_mouse_button(0x01, False)
        elif btn == Qt.MouseButton.RightButton:
            self._input_state.set_mouse_button(0x02, False)
        elif btn == Qt.MouseButton.MiddleButton:
            self._input_state.set_mouse_button(0x04, False)

        self._serial.enqueue(
            build_mouse_report(self._input_state.mouse_buttons, 0, 0)
        )

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if not self._kvm_active:
            return

        # Ignore the synthetic move event generated by our own QCursor.setPos()
        if self._warp_pending:
            self._warp_pending = False
            return

        # Recompute centre every move in case the window was repositioned
        self._center = self._video_widget.mapToGlobal(
            QPoint(
                self._video_widget.width()  // 2,
                self._video_widget.height() // 2,
            )
        )

        global_pos = event.globalPosition().toPoint()
        dx = global_pos.x() - self._center.x()
        dy = global_pos.y() - self._center.y()

        if dx != 0 or dy != 0:
            self._serial.enqueue(
                build_mouse_report(
                    self._input_state.mouse_buttons,
                    dx,   # build_mouse_report clamps to ±127
                    dy,
                )
            )
            self._warp_pending = True
            QCursor.setPos(self._center)

    def wheelEvent(self, event: QWheelEvent) -> None:  # noqa: N802
        if not self._kvm_active:
            return

        delta   = event.angleDelta().y()
        wheel_v = 1 if delta > 0 else (-1 if delta < 0 else 0)
        if wheel_v:
            self._serial.enqueue(
                build_mouse_report(
                    self._input_state.mouse_buttons,
                    0, 0, wheel_v,
                )
            )

    # -------------------------------------------------------------------------
    # Keyboard events
    # -------------------------------------------------------------------------

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        key = event.key()

        # Esc always exits focus mode
        if key == Qt.Key.Key_Escape and self._kvm_active:
            self._set_kvm_active(False)
            return

        if not self._kvm_active:
            super().keyPressEvent(event)
            return

        # Update modifier or key state
        if is_modifier_key(key):
            bit = get_modifier_bit(key)
            if bit is not None:
                self._input_state.press_modifier(bit)
        else:
            hid = qt_key_to_hid(key)
            if hid:
                self._input_state.press_key(hid)

        modifier, keys = self._input_state.get_keyboard_report()
        self._serial.enqueue(build_keyboard_report(modifier, keys))

    def keyReleaseEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if not self._kvm_active:
            super().keyReleaseEvent(event)
            return

        if event.isAutoRepeat():
            return

        key = event.key()
        if is_modifier_key(key):
            bit = get_modifier_bit(key)
            if bit is not None:
                self._input_state.release_modifier(bit)
        else:
            hid = qt_key_to_hid(key)
            if hid:
                self._input_state.release_key(hid)

        modifier, keys = self._input_state.get_keyboard_report()
        self._serial.enqueue(build_keyboard_report(modifier, keys))

    # -------------------------------------------------------------------------
    # Focus / close
    # -------------------------------------------------------------------------

    def focusOutEvent(self, event) -> None:  # noqa: N802
        self._set_kvm_active(False)
        super().focusOutEvent(event)

    def _on_focus_changed(self, old, new) -> None:
        """Deactivate KVM when focus moves away from this window."""
        if self._kvm_active and (new is None or new.window() is not self):
            self._set_kvm_active(False)

    def closeEvent(self, event) -> None:  # noqa: N802
        self._set_kvm_active(False)
        self._capture.stop()
        self._capture.wait(2000)
        self._serial.stop()
        self._serial.wait(2000)
        super().closeEvent(event)
