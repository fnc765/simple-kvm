"""
settings_dialog.py -- Serial port & capture device selection dialog.
"""

from __future__ import annotations

import re

import serial.tools.list_ports
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QPushButton,
)

from core.capture import list_dshow_devices


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

    # ------------------------------------------------------------------
    # Result accessors
    # ------------------------------------------------------------------

    def get_values(self) -> tuple[str, str]:
        """Return *(selected_port, selected_device_name)*."""
        port = self._port_combo.currentText()
        device = self._device_combo.currentText()
        return port, device
