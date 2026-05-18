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

import ctypes
import time
from ctypes import wintypes

from PySide6.QtCore import QPoint, QSize, Qt, QTimer
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
    QSizePolicy,
    QStatusBar,
)

from core.capture import CaptureThread, DEFAULT_DEVICE, DEFAULT_WIDTH, DEFAULT_HEIGHT, DEFAULT_FPS
from core.input_hook import InputState, RawInputHook
from core.keymap import (
    get_modifier_bit,
    is_auto_release,
    is_modifier_key,
    qt_key_to_hid,
    scancode_to_hid,
    vk_to_modifier,
)
from core.protocol import build_heartbeat, build_keyboard_report, build_mouse_report
from core.serial_comm import SerialComm
from ui.settings_dialog import SettingsDialog


class VideoWidget(QLabel):
    """640 × 480 label that displays the HDMI capture feed."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumSize(320, 240)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet("background: #111;")
        self.setText("No Signal – click to start capture")
        self._pixmap: QPixmap | None = None  # オリジナルピクスマップを保持
        self._aspect_mode = Qt.AspectRatioMode.KeepAspectRatio  # default

    def set_aspect_mode(self, mode: Qt.AspectRatioMode) -> None:
        """Set aspect ratio mode: KeepAspectRatio or IgnoreAspectRatio."""
        self._aspect_mode = mode
        self._update_scaled_pixmap()

    def _update_scaled_pixmap(self) -> None:
        if self._pixmap is None:
            return
        dpr = self.devicePixelRatioF()
        target = QSize(
            int(self.width() * dpr),
            int(self.height() * dpr)
        )
        scaled = self._pixmap.scaled(
            target,
            self._aspect_mode,
            Qt.TransformationMode.SmoothTransformation,
        )
        scaled.setDevicePixelRatio(dpr)
        self.setPixmap(scaled)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._update_scaled_pixmap()


class _MSG(ctypes.Structure):
    """Windows MSG structure for nativeEvent parsing."""
    _fields_ = [
        ("hwnd",    wintypes.HWND),
        ("message", wintypes.UINT),
        ("wParam",  wintypes.WPARAM),
        ("lParam",  wintypes.LPARAM),
        ("time",    wintypes.DWORD),
        ("pt",      wintypes.POINT),
    ]


class MainWindow(QMainWindow):
    """Top-level KVM window."""

    _HEARTBEAT_INTERVAL_MS = 1_000

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("simple-kvm")

        # ---- Video widget ---------------------------------------------------
        self._video_widget = VideoWidget(self)
        self.setCentralWidget(self._video_widget)

        # ---- FPS overlay (visible only in fullscreen) -----------------------
        self._fps_overlay = QLabel(self._video_widget)
        self._fps_overlay.setStyleSheet(
            "QLabel {"
            "  background: rgba(0, 0, 0, 140);"
            "  color: #0f0;"
            "  font-family: Consolas, monospace;"
            "  font-size: 12px;"
            "  padding: 4px 8px;"
            "  border-radius: 4px;"
            "}"
        )
        self._fps_overlay.hide()

        # ---- Fullscreen hint overlay ----------------------------------------
        self._fullscreen_hint = QLabel(self._video_widget)
        self._fullscreen_hint.setText("Press ESC to exit fullscreen")
        self._fullscreen_hint.setStyleSheet(
            "QLabel {"
            "  background: rgba(0, 0, 0, 160);"
            "  color: #ccc;"
            "  font-size: 14px;"
            "  padding: 8px 16px;"
            "  border-radius: 6px;"
            "}"
        )
        self._fullscreen_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._fullscreen_hint.adjustSize()
        self._fullscreen_hint.hide()

        self._fullscreen_hint_timer = QTimer(self)
        self._fullscreen_hint_timer.setSingleShot(True)
        self._fullscreen_hint_timer.timeout.connect(self._fullscreen_hint.hide)

        # ---- Status bar -----------------------------------------------------
        self._status = QStatusBar()
        self.setStatusBar(self._status)
        self._status.showMessage("Ready – open File > Settings to configure")

        # ---- Menu bar -------------------------------------------------------
        menu_bar = QMenuBar(self)
        self.setMenuBar(menu_bar)
        file_menu = QMenu("File", self)
        menu_bar.addMenu(file_menu)
        file_menu.addAction("Settings…", self._open_settings)
        file_menu.addSeparator()
        file_menu.addAction("Quit", QApplication.quit)

        view_menu = QMenu("View", self)
        menu_bar.addMenu(view_menu)
        fullscreen_action = view_menu.addAction("Toggle Fullscreen\tF11")
        fullscreen_action.triggered.connect(self.toggle_fullscreen)

        # ---- Input / KVM state ----------------------------------------------
        self._kvm_active    = False
        self._center        = QPoint()       # VideoWidget centre in global coords
        self._input_state   = InputState()
        self._warp_pending  = False          # True while cursor warp is in-flight

        # ---- Fullscreen state ------------------------------------------------
        self._is_fullscreen = False
        self._pre_fullscreen_geometry = None   # QRect or None
        self._pre_fullscreen_state = None      # Qt.WindowStates or None
        self._esc_suppressed = False           # Suppress Qt keyPressEvent after Raw Input Esc

        # Single-click KVM delay timer (to distinguish from double-click for fullscreen)
        self._kvm_click_timer = QTimer(self)
        self._kvm_click_timer.setSingleShot(True)
        self._kvm_click_timer.timeout.connect(self._activate_kvm_from_click)

        # ---- Raw Input (Windows) --------------------------------------------
        self._raw_hook: RawInputHook | None = None
        self._use_raw_input: bool = False     # True when Raw Input is active

        # ---- Serial communication -------------------------------------------
        self._serial = SerialComm(self)
        self._serial.connected.connect(self._on_serial_connected)

        # ---- Capture thread -------------------------------------------------
        self._capture = CaptureThread(DEFAULT_DEVICE, self)
        self._capture.frame_ready.connect(self._on_frame_ready)
        self._capture.fps_updated.connect(self._on_fps_update)

        # ---- Stored settings ------------------------------------------------
        self._port           = ""
        self._capture_device = DEFAULT_DEVICE
        self._connected      = False
        self._mouse_speed    = 1.0       # Mouse cursor speed multiplier (0.5x .. 2.0x)

        # ---- Heartbeat timer ------------------------------------------------
        self._hb_timer = QTimer(self)
        self._hb_timer.timeout.connect(self._send_heartbeat)
        self._hb_timer.start(self._HEARTBEAT_INTERVAL_MS)

        # Enable mouse tracking so we receive move events without click
        self.setMouseTracking(True)
        self._video_widget.setMouseTracking(True)

        self.resize(640, 480 + 60)

        # Focus-loss guard: deactivate KVM when any other window gains focus
        QApplication.instance().focusChanged.connect(self._on_focus_changed)

    # -------------------------------------------------------------------------
    # Show event – initialise Raw Input once the native window exists
    # -------------------------------------------------------------------------

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        if not self._raw_hook:
            self._setup_raw_input()

    # -------------------------------------------------------------------------
    # Settings
    # -------------------------------------------------------------------------

    def _open_settings(self) -> None:
        current_aspect = "keep" if (
            self._video_widget._aspect_mode == Qt.AspectRatioMode.KeepAspectRatio
        ) else "fill"
        dlg = SettingsDialog(
            self._port,
            self._capture_device,
            current_aspect,
            self._mouse_speed,
            self,
        )
        if dlg.exec():
            port, device_name, aspect_mode, mouse_speed = dlg.get_values()
            changed = False
            if port != self._port or device_name != self._capture_device:
                self._port           = port
                self._capture_device = device_name
                changed = True
            new_mode = (
                Qt.AspectRatioMode.KeepAspectRatio if aspect_mode == "keep"
                else Qt.AspectRatioMode.IgnoreAspectRatio
            )
            if new_mode != self._video_widget._aspect_mode:
                self._video_widget.set_aspect_mode(new_mode)
            self._mouse_speed = mouse_speed
            if changed:
                self._apply_settings()

    def _apply_settings(self) -> None:
        self._set_kvm_active(False)

        # Restart serial
        self._serial.stop()
        if self._port:
            self._serial.set_port(self._port)
            self._serial.start()

        # Restart capture (PyAV always uses 1080p @ 30fps)
        self._capture.stop()
        self._capture.set_device(self._capture_device)
        self._capture.set_format(DEFAULT_WIDTH, DEFAULT_HEIGHT, DEFAULT_FPS)
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
        self._video_widget._pixmap = pixmap
        self._video_widget._update_scaled_pixmap()

    def _on_fps_update(self, fps: float) -> None:
        port_part = f"Connected: {self._port}" if self._connected else "Disconnected"
        fps_text = f"FPS: {fps:.1f}"

        if self._is_fullscreen:
            self._fps_overlay.setText(f"  {port_part}  |  {fps_text}  ")
            self._fps_overlay.adjustSize()
            if not self._fps_overlay.isVisible():
                self._fps_overlay.move(8, 8)
                self._fps_overlay.show()
            self._fps_overlay.raise_()
        else:
            self._status.showMessage(f"{port_part}  |  {fps_text}")

    def _activate_kvm_from_click(self) -> None:
        """Activate KVM mode after single-click confirmation (timer callback)."""
        if not self._kvm_active:
            self._set_kvm_active(True)

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
            # Guard: do not touch menu bar when fullscreen (it's already hidden)
            if not self._is_fullscreen:
                self.menuBar().setEnabled(False)
            self.setCursor(Qt.CursorShape.BlankCursor)
            self._recompute_center()
            QCursor.setPos(self._center)
            self._status.showMessage(
                f"{self._port} – KVM active (Esc to release)"
            )
        else:
            # Guard: do not touch menu bar when fullscreen (managed by fullscreen exit)
            if not self._is_fullscreen:
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
    # Fullscreen
    # -------------------------------------------------------------------------

    def toggle_fullscreen(self) -> None:
        """Toggle fullscreen mode on/off."""
        if self._is_fullscreen:
            self._exit_fullscreen()
        else:
            self._enter_fullscreen()

    def _enter_fullscreen(self) -> None:
        """Enter fullscreen mode."""
        self._is_fullscreen = True

        # Save current geometry and window state before going fullscreen
        self._pre_fullscreen_geometry = self.geometry()
        self._pre_fullscreen_state = self.windowState()

        # Save KVM state (showFullScreen may trigger focus events)
        was_kvm_active = self._kvm_active

        # Snapshot input state to survive focus-loss-induced clear
        with self._input_state._lock:
            _saved_modifier = self._input_state.modifier
            _saved_keys = list(self._input_state.pressed_keys)
            _saved_buttons = self._input_state.mouse_buttons

        # Hide menu bar
        self.menuBar().hide()

        # Hide status bar
        self._status.hide()

        # Enter fullscreen (may trigger focusOutEvent -> _set_kvm_active(False) -> clear_keys())
        self.showFullScreen()

        # Restore KVM state if it was lost during fullscreen transition
        if was_kvm_active and not self._kvm_active:
            self._set_kvm_active(True)
            # Restore input state that was cleared by focusOutEvent
            with self._input_state._lock:
                self._input_state.modifier = _saved_modifier
                self._input_state.pressed_keys.clear()
                self._input_state.pressed_keys.extend(_saved_keys)
                self._input_state.mouse_buttons = _saved_buttons
        elif self._kvm_active:
            self._recompute_center()

        # Show fullscreen hint
        self._show_fullscreen_hint()

        # Show FPS overlay
        self._fps_overlay.show()

    def _exit_fullscreen(self) -> None:
        """Exit fullscreen mode."""
        self._is_fullscreen = False
        self._fullscreen_hint_timer.stop()

        # Save KVM state (showNormal may trigger focus events, mirror of _enter_fullscreen)
        was_kvm_active = self._kvm_active

        # Snapshot input state to survive focus-loss-induced clear
        with self._input_state._lock:
            _saved_modifier = self._input_state.modifier
            _saved_keys = list(self._input_state.pressed_keys)
            _saved_buttons = self._input_state.mouse_buttons

        # Restore menu bar (respect KVM state)
        if not self._kvm_active:
            self.menuBar().show()
            self.menuBar().setEnabled(True)
        else:
            self.menuBar().show()
            self.menuBar().setEnabled(False)

        # Restore status bar
        self._status.show()

        # Restore normal window (may trigger focusOutEvent -> KVM deactivation)
        self.showNormal()

        # Restore KVM state if it was lost during normal window transition
        if was_kvm_active and not self._kvm_active:
            self._set_kvm_active(True)
            # Restore input state that was cleared by focusOutEvent
            with self._input_state._lock:
                self._input_state.modifier = _saved_modifier
                self._input_state.pressed_keys.clear()
                self._input_state.pressed_keys.extend(_saved_keys)
                self._input_state.mouse_buttons = _saved_buttons
        elif self._kvm_active:
            self._recompute_center()

        # Restore saved geometry and state
        if self._pre_fullscreen_geometry is not None:
            self.setGeometry(self._pre_fullscreen_geometry)
        if self._pre_fullscreen_state is not None:
            self.setWindowState(self._pre_fullscreen_state)

        # Hide FPS overlay
        self._fps_overlay.hide()

        # Hide fullscreen hint
        self._fullscreen_hint.hide()

    def _recompute_center(self) -> None:
        """Recalculate the VideoWidget centre in global coordinates."""
        self._center = self._video_widget.mapToGlobal(
            QPoint(
                self._video_widget.width() // 2,
                self._video_widget.height() // 2,
            )
        )

    def _show_fullscreen_hint(self) -> None:
        """Display fullscreen exit hint for 3 seconds."""
        pw = self._video_widget
        x = (pw.width() - self._fullscreen_hint.width()) // 2
        y = pw.height() - self._fullscreen_hint.height() - 40
        self._fullscreen_hint.move(x, y)
        self._fullscreen_hint.show()
        self._fullscreen_hint_timer.start(3000)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if self._is_fullscreen and self._fullscreen_hint.isVisible():
            pw = self._video_widget
            x = (pw.width() - self._fullscreen_hint.width()) // 2
            y = pw.height() - self._fullscreen_hint.height() - 40
            self._fullscreen_hint.move(x, y)

    # -------------------------------------------------------------------------
    # Mouse events
    # -------------------------------------------------------------------------

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if not self._kvm_active:
            # Delay KVM activation to distinguish single-click from double-click
            local = self._video_widget.mapFromGlobal(
                event.globalPosition().toPoint()
            )
            in_widget = (
                0 <= local.x() < self._video_widget.width()
                and 0 <= local.y() < self._video_widget.height()
            )
            if in_widget:
                self._kvm_click_timer.start(400)
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

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        """Double-click on video widget toggles fullscreen."""
        self._kvm_click_timer.stop()  # Cancel pending KVM activation
        if not self._kvm_active:
            local = self._video_widget.mapFromGlobal(
                event.globalPosition().toPoint()
            )
            in_widget = (
                0 <= local.x() < self._video_widget.width()
                and 0 <= local.y() < self._video_widget.height()
            )
            if in_widget:
                self.toggle_fullscreen()
                return
        super().mouseDoubleClickEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if not self._kvm_active:
            return

        # Ignore the synthetic move event generated by our own QCursor.setPos()
        if self._warp_pending:
            self._warp_pending = False
            return

        # Recompute centre every move in case the window was repositioned
        self._recompute_center()

        global_pos = event.globalPosition().toPoint()
        dx = global_pos.x() - self._center.x()
        dy = global_pos.y() - self._center.y()

        # Apply mouse speed multiplier
        if self._mouse_speed != 1.0:
            dx = int(round(dx * self._mouse_speed))
            dy = int(round(dy * self._mouse_speed))

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
        # --- Priority 1: Escape handling ---
        if event.key() == Qt.Key.Key_Escape:
            if self._esc_suppressed:
                self._esc_suppressed = False   # Reset flag for next Esc press
                return
            if self._kvm_active:
                self._set_kvm_active(False)
                return
            if self._is_fullscreen:
                self.toggle_fullscreen()
                return

        # --- Priority 2: F11 fullscreen toggle (only when KVM is not active) ---
        if event.key() == Qt.Key.Key_F11 and not self._kvm_active:
            self.toggle_fullscreen()
            return

        # --- Existing Raw Input / KVM handling below (DO NOT CHANGE) ---
        # When Raw Input is active, skip Qt keyboard events entirely
        # to avoid double-sending every keystroke.
        if self._use_raw_input and self._kvm_active:
            return

        key = event.key()

        if not self._kvm_active:
            super().keyPressEvent(event)
            return

        # Update modifier or key state
        changed = False
        if is_modifier_key(key):
            bit = get_modifier_bit(key)
            if bit is not None:
                changed = self._input_state.press_modifier(bit)
        else:
            hid = qt_key_to_hid(key)
            if hid:
                changed = self._input_state.press_key(hid)

        if changed:
            modifier, keys = self._input_state.get_keyboard_report()
            self._serial.enqueue(build_keyboard_report(modifier, keys))

    def keyReleaseEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        # When Raw Input is active, skip Qt keyboard events.
        if self._use_raw_input and self._kvm_active:
            return

        if not self._kvm_active:
            super().keyReleaseEvent(event)
            return

        if event.isAutoRepeat():
            return

        changed = False
        key = event.key()
        if is_modifier_key(key):
            bit = get_modifier_bit(key)
            if bit is not None:
                changed = self._input_state.release_modifier(bit)
        else:
            hid = qt_key_to_hid(key)
            if hid:
                changed = self._input_state.release_key(hid)

        if changed:
            modifier, keys = self._input_state.get_keyboard_report()
            self._serial.enqueue(build_keyboard_report(modifier, keys))

    # -------------------------------------------------------------------------
    # Raw Input (Windows) – native event interception
    # -------------------------------------------------------------------------

    def nativeEvent(self, eventType: bytes, message: int) -> tuple[bool, int]:
        """Intercept WM_INPUT messages for scancode-level keyboard input."""
        if not self._use_raw_input or not self._kvm_active:
            return super().nativeEvent(eventType, message)

        try:
            ptr = int(message)
        except (TypeError, ValueError):
            return super().nativeEvent(eventType, message)

        msg_struct = ctypes.cast(ptr, ctypes.POINTER(_MSG)).contents
        msg    = msg_struct.message
        lparam = msg_struct.lParam

        if self._raw_hook.handle_message(msg, lparam):
            return True, 0

        return super().nativeEvent(eventType, message)

    # -------------------------------------------------------------------------
    # Raw Input – setup and callbacks
    # -------------------------------------------------------------------------

    def _setup_raw_input(self) -> None:
        """Create and register the RawInputHook for this window."""
        try:
            self._raw_hook = RawInputHook(
                on_key_down=self._on_raw_key_down,
                on_key_up=self._on_raw_key_up,
            )
            hwnd = int(self.winId())
            if self._raw_hook.register(hwnd):
                self._use_raw_input = True
        except Exception:
            self._use_raw_input = False

    def _on_raw_key_down(self, scancode: int, vk: int, _flags: int,
                         is_e0: bool) -> None:
        """Raw Input keyboard press callback."""
        if not self._kvm_active:
            return

        # Escape handling with fullscreen awareness
        if scancode == 0x01:  # Esc
            if self._is_fullscreen:
                # KVM+fullscreen: first Esc exits KVM, second exits fullscreen
                if self._kvm_active:
                    self._set_kvm_active(False)
                    self._esc_suppressed = True  # Suppress subsequent Qt keyPressEvent
                else:
                    self.toggle_fullscreen()
            else:
                self._set_kvm_active(False)
            return

        # Modifier keys: use VK → modifier bit (full L/R discrimination)
        changed = False
        mod_bit = vk_to_modifier(vk, scancode, is_e0)
        if mod_bit:
            changed = self._input_state.press_modifier(mod_bit)
        else:
            hid = scancode_to_hid(scancode, is_e0, vk)
            if hid:
                changed = self._input_state.press_key(hid)
                # Toggle/lock keys: send the press report then immediately
                # release to prevent stuck-key syndrome.  The OS consumes the
                # UP event for these keys (LED / IME handling), so we never
                # receive an _on_raw_key_up callback.
                if is_auto_release(scancode):
                    modifier, keys = self._input_state.get_keyboard_report()
                    self._serial.enqueue(build_keyboard_report(modifier, keys))
                    time.sleep(0.01)
                    self._input_state.release_key(hid)

        if changed:
            modifier, keys = self._input_state.get_keyboard_report()
            self._serial.enqueue(build_keyboard_report(modifier, keys))

    def _on_raw_key_up(self, scancode: int, vk: int, _flags: int,
                       is_e0: bool) -> None:
        """Raw Input keyboard release callback."""
        if not self._kvm_active:
            return
        changed = False
        mod_bit = vk_to_modifier(vk, scancode, is_e0)
        if mod_bit:
            changed = self._input_state.release_modifier(mod_bit)
        else:
            hid = scancode_to_hid(scancode, is_e0, vk)
            if hid:
                changed = self._input_state.release_key(hid)

        if changed:
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
        self._kvm_click_timer.stop()
        if self._is_fullscreen:
            self._exit_fullscreen()
        self._set_kvm_active(False)
        self._capture.stop()
        self._serial.stop()
        super().closeEvent(event)
