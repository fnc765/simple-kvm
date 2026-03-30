"""
settings_dialog.py – Serial port & capture device selection dialog.
"""

from __future__ import annotations

import re
import sys

import cv2
import serial.tools.list_ports
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QPushButton,
)


class SettingsDialog(QDialog):
    """
    Modal dialog that lets the user choose:
    - the COM port connected to BluePill #1
    - the OpenCV device index for the HDMI capture dongle
    """

    def __init__(
        self,
        current_port: str   = "",
        current_device: int = 0,
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
        idx = self._device_combo.findData(current_device)
        if idx >= 0:
            self._device_combo.setCurrentIndex(idx)

        layout.addRow("Capture Device:", self._device_combo)
        layout.addRow(
            "",
            QLabel("(Device 0 is usually the first UVC / HDMI capture dongle)"),
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
            m = re.search(r'\d+', p.device)
            return int(m.group()) if m else 0

        ports = [p.device for p in sorted(
            serial.tools.list_ports.comports(),
            key=_port_num,
        )]
        self._port_combo.addItems(ports)
        if current in ports:
            self._port_combo.setCurrentText(current)

    def _populate_devices(self) -> None:
        from PySide6.QtCore import Qt
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            self._device_combo.clear()
            backend = cv2.CAP_DSHOW if sys.platform == "win32" else cv2.CAP_ANY
            consecutive_failures = 0
            for i in range(10):
                cap = cv2.VideoCapture(i, backend)
                if cap.isOpened():
                    self._device_combo.addItem(f"Device {i}", i)
                    cap.release()
                    consecutive_failures = 0
                else:
                    cap.release()
                    consecutive_failures += 1
                    if consecutive_failures >= 3:
                        break

            if self._device_combo.count() == 0:
                self._device_combo.addItem("Device 0 (not detected)", 0)
        finally:
            QApplication.restoreOverrideCursor()

    # ------------------------------------------------------------------
    # Result accessors
    # ------------------------------------------------------------------

    def get_values(self) -> tuple[str, int]:
        """Return *(selected_port, selected_device_index)*."""
        port   = self._port_combo.currentText()
        device = self._device_combo.currentData()
        if device is None:
            device = 0
        return port, int(device)
