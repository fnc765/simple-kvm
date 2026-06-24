"""
settings_dialog.py -- Serial port & capture device selection dialog.
"""

from __future__ import annotations

import re

import serial.tools.list_ports
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
)

from core.capture import list_dshow_devices


# Display labels for the Mouse Mode combo box.  ``(value, label)`` pairs.
_MOUSE_MODE_OPTIONS: list[tuple[str, str]] = [
    ("relative", "Relative (warp to center)"),
    ("hybrid",   "Hybrid (jump on activation, then relative)"),
    ("absolute", "Absolute (desktop / overlay helper)"),
]


class SettingsDialog(QDialog):
    """Modal dialog for choosing the COM port and capture device.

    The capture device is selected by name (e.g. ``"USB3. 0 capture"``)
    rather than by numeric index, because PyAV/FFmpeg identifies
    DirectShow devices by their friendly name.
    """

    def __init__(
        self,
        current_port: str = "",
        current_device: str = "",
        current_aspect: str = "keep",
        current_speed: float = 1.0,
        current_mouse_mode: str = "relative",
        current_firmware_abs_supported: bool = False,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setMinimumWidth(360)

        layout = QFormLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        # ---- Serial port ---------------------------------------------------
        self._port_combo = QComboBox()
        self._refresh_ports()
        if current_port and self._port_combo.findText(current_port) == -1:
            self._port_combo.addItem(current_port)
        if current_port:
            self._port_combo.setCurrentText(current_port)

        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self._refresh_ports)
        layout.addRow("Serial Port:", self._port_combo)
        layout.addRow("", refresh_btn)

        # ---- Capture device ------------------------------------------------
        self._device_combo = QComboBox()
        self._populate_devices()
        idx = self._device_combo.findText(current_device)
        if idx >= 0:
            self._device_combo.setCurrentIndex(idx)

        layout.addRow("Capture Device:", self._device_combo)
        layout.addRow(
            "",
            QLabel("Capture is always 1920x1080 @ 30 fps via FFmpeg"),
        )

        # ---- Aspect ratio --------------------------------------------------
        self._aspect_combo = QComboBox()
        self._aspect_combo.addItem("Maintain Aspect Ratio")
        self._aspect_combo.addItem("Stretch to Fill")
        if current_aspect == "fill":
            self._aspect_combo.setCurrentIndex(1)
        layout.addRow("Aspect Ratio:", self._aspect_combo)

        # ---- Mouse speed slider (0.5x .. 2.0x, 0.1 step) ------------------
        self._speed_slider = QSlider(Qt.Orientation.Horizontal)
        self._speed_slider.setRange(0, 15)       # 0.5 + 0*0.1 .. 0.5 + 15*0.1 = 2.0
        self._speed_slider.setSingleStep(1)
        self._speed_slider.setPageStep(3)
        self._speed_slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        self._speed_slider.setTickInterval(3)
        # Set initial slider position from current_speed
        initial_index = int(round((current_speed - 0.5) / 0.1))
        self._speed_slider.setValue(max(0, min(15, initial_index)))

        self._speed_label = QLabel(f"{current_speed:.1f}x")
        speed_layout = QHBoxLayout()
        speed_layout.addWidget(self._speed_slider)
        speed_layout.addWidget(self._speed_label)
        layout.addRow("Mouse Speed:", speed_layout)

        self._speed_slider.valueChanged.connect(self._on_speed_changed)

        # ---- Mouse mode ---------------------------------------------------
        self._mode_combo = QComboBox()
        for value, label in _MOUSE_MODE_OPTIONS:
            self._mode_combo.addItem(label, value)
        # Map current_mouse_mode -> current index (default 0 = relative)
        mode_index = 0
        for i, (value, _label) in enumerate(_MOUSE_MODE_OPTIONS):
            if value == current_mouse_mode:
                mode_index = i
                break
        self._mode_combo.setCurrentIndex(mode_index)
        layout.addRow("Mouse Mode:", self._mode_combo)
        layout.addRow(
            "",
            QLabel("Mouse Speed applies to Relative / Hybrid movement only."),
        )

        # ---- Firmware supports absolute HID -------------------------------
        self._firmware_abs_checkbox = QCheckBox(
            "Firmware supports absolute HID (Phase 3 BP2 firmware)"
        )
        self._firmware_abs_checkbox.setChecked(bool(current_firmware_abs_supported))
        self._firmware_abs_checkbox.setToolTip(
            "Enable only if BluePill #2 has been flashed with the\n"
            "3-interface HID composite firmware that exposes an\n"
            "absolute mouse interface.  Older firmware will blink\n"
            "an error when it receives PKT_MOUSE_ABS."
        )
        layout.addRow("", self._firmware_abs_checkbox)

        # ---- Buttons -------------------------------------------------------
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _refresh_ports(self) -> None:
        current = self._port_combo.currentText()
        self._port_combo.clear()

        def _port_num(p) -> int:
            m = re.search(r"\d+", p.device)
            return int(m.group()) if m else 0

        ports = [
            p.device
            for p in sorted(serial.tools.list_ports.comports(), key=_port_num)
        ]
        self._port_combo.addItems(ports)
        if current in ports:
            self._port_combo.setCurrentText(current)

    def _populate_devices(self) -> None:
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            self._device_combo.clear()
            devices = list_dshow_devices()
            self._device_combo.addItems(devices)
        finally:
            QApplication.restoreOverrideCursor()

    def _on_speed_changed(self, value: int) -> None:
        """Update speed label when slider value changes."""
        speed = 0.5 + value * 0.1
        self._speed_label.setText(f"{speed:.1f}x")

    # ------------------------------------------------------------------
    # Result accessors
    # ------------------------------------------------------------------

    def get_values(self) -> tuple[str, str, str, float, str, bool]:
        """Return *(port, device, aspect, speed, mouse_mode, firmware_abs_supported)*."""
        port = self._port_combo.currentText()
        device = self._device_combo.currentText()
        aspect = "keep" if self._aspect_combo.currentIndex() == 0 else "fill"
        speed = 0.5 + self._speed_slider.value() * 0.1
        mode_value = self._mode_combo.currentData() or "relative"
        firmware_abs = self._firmware_abs_checkbox.isChecked()
        return port, device, aspect, speed, mode_value, firmware_abs
