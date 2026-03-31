"""
settings_dialog.py – Serial port & capture device selection dialog.
"""

from __future__ import annotations

import re
import sys

import cv2
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

from core.capture import CAP_BACKEND, enumerate_capture_formats


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

        # ---- Capture format ------------------------------------------------
        self._format_combo = QComboBox()
        self._format_combo.addItem("Auto Detect (1080p)", userData=None)
        self._detect_btn = QPushButton("Detect Formats")
        self._detect_btn.clicked.connect(self._on_detect_formats)
        layout.addRow("Capture Format:", self._format_combo)
        layout.addRow("", self._detect_btn)

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

    def _on_detect_formats(self) -> None:
        """選択中のデバイスの対応フォーマットを検出してコンボボックスを更新する。"""
        device_index = self._device_combo.currentData()
        if device_index is None:
            return

        self._detect_btn.setEnabled(False)
        self._detect_btn.setText("Detecting…")
        # UI を一時更新
        QApplication.processEvents()

        try:
            formats = enumerate_capture_formats(device_index)
        finally:
            self._detect_btn.setEnabled(True)
            self._detect_btn.setText("Detect Formats")

        self._format_combo.clear()
        self._format_combo.addItem("Auto Detect (1080p)", userData=None)
        for w, h, fps in formats:
            label = f"{w}×{h} @ {fps}fps"
            self._format_combo.addItem(label, userData=(w, h, fps))

    # ------------------------------------------------------------------
    # Result accessors
    # ------------------------------------------------------------------

    def get_values(self) -> tuple[str, int, tuple[int, int, int] | None]:
        """Return *(selected_port, selected_device_index, capture_format)*."""
        port   = self._port_combo.currentText()
        device = self._device_combo.currentData()
        if device is None:
            device = 0
        capture_format = self._format_combo.currentData()
        return port, int(device), capture_format
