"""Progress and cancellation UI for clipboard Base64 transfers."""

from __future__ import annotations

import math

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QDialog,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
)

from core.clipboard_base64 import Base64ClipboardPayload
from core.keyboard_layouts import KeyboardLayout, coerce_keyboard_layout


def _format_duration(seconds: float) -> str:
    rounded = max(0, int(math.ceil(seconds)))
    minutes, remainder = divmod(rounded, 60)
    if minutes:
        return f"about {minutes}m {remainder}s"
    return f"about {remainder}s"


class Base64TransferDialog(QDialog):
    """Show transfer details, actual write progress, and a cancel button."""

    start_requested: Signal = Signal()
    cancel_requested: Signal = Signal()

    def __init__(
        self,
        payload: Base64ClipboardPayload,
        keyboard_layout: KeyboardLayout | str = KeyboardLayout.JIS,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._payload = payload
        self._active = False
        self._cancel_requested = False

        self.setWindowTitle("Send Clipboard as Base64")
        self.setMinimumWidth(420)
        self.setModal(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        details = QFormLayout()
        details.addRow(
            "Source text:",
            QLabel(f"{payload.source_characters:,} characters"),
        )
        details.addRow(
            "UTF-8 size:",
            QLabel(f"{payload.utf8_bytes:,} bytes"),
        )
        details.addRow(
            "Base64 output:",
            QLabel(f"{payload.encoded_characters:,} characters"),
        )
        details.addRow(
            "Estimated time:",
            QLabel(_format_duration(payload.estimated_seconds)),
        )
        self._layout_combo = QComboBox()
        self._layout_combo.addItem("Japanese (JIS)", KeyboardLayout.JIS.value)
        self._layout_combo.addItem("US", KeyboardLayout.US.value)
        selected_layout = coerce_keyboard_layout(keyboard_layout)
        selected_index = self._layout_combo.findData(selected_layout.value)
        self._layout_combo.setCurrentIndex(max(0, selected_index))
        details.addRow("Target keyboard layout:", self._layout_combo)
        layout.addLayout(details)

        self._status_label = QLabel("Ready to send the Base64 text.")
        layout.addWidget(self._status_label)

        self._progress = QProgressBar()
        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        self._progress.setFormat("0%")
        layout.addWidget(self._progress)

        self._count_label = QLabel(
            f"0 / {payload.encoded_characters:,} characters"
        )
        layout.addWidget(self._count_label)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        self._start_button = QPushButton("Start Sending")
        self._secondary_button = QPushButton("Close")
        self._start_button.clicked.connect(self.start_requested.emit)
        self._secondary_button.clicked.connect(self._on_secondary_clicked)
        button_row.addWidget(self._start_button)
        button_row.addWidget(self._secondary_button)
        layout.addLayout(button_row)

    @property
    def payload(self) -> Base64ClipboardPayload:
        return self._payload

    @property
    def keyboard_layout(self) -> KeyboardLayout:
        """Return the currently selected target keyboard layout."""
        return coerce_keyboard_layout(self._layout_combo.currentData())

    def begin_transfer(self) -> None:
        """Switch from confirmation state to active transfer state."""
        self._active = True
        self._cancel_requested = False
        self._start_button.setEnabled(False)
        self._start_button.hide()
        self._layout_combo.setEnabled(False)
        self._secondary_button.setText("Cancel")
        self._secondary_button.setEnabled(True)
        self._status_label.setText("Sending Base64 text…")

    def set_progress(self, completed: int, total: int) -> None:
        """Update progress using completed Base64 characters."""
        if total <= 0:
            return
        completed = max(0, min(completed, total))
        percentage = (completed * 100) // total
        self._progress.setValue(percentage)
        self._progress.setFormat(f"{percentage}%")
        self._count_label.setText(
            f"{completed:,} / {total:,} characters"
        )

    def set_outcome(self, outcome: str) -> None:
        """Show a terminal transfer outcome and allow the dialog to close."""
        self._active = False
        self._cancel_requested = False
        self._start_button.hide()
        self._secondary_button.setText("Close")
        self._secondary_button.setEnabled(True)

        if outcome == "completed":
            self.set_progress(
                self._payload.encoded_characters,
                self._payload.encoded_characters,
            )
            self._status_label.setText("Base64 text sent.")
        elif outcome == "cancelled":
            self._status_label.setText("Base64 transfer cancelled.")
        else:
            self._status_label.setText("Base64 transfer failed.")

    def request_cancel(self) -> None:
        """Request cancellation once and keep the dialog open for cleanup."""
        if not self._active or self._cancel_requested:
            return
        self._cancel_requested = True
        self._secondary_button.setEnabled(False)
        self._status_label.setText("Cancelling…")
        self.cancel_requested.emit()

    def _on_secondary_clicked(self) -> None:
        if self._active:
            self.request_cancel()
        else:
            self.accept()

    def reject(self) -> None:
        """Treat window-close and Escape as cancellation while active."""
        if self._active:
            self.request_cancel()
            return
        super().reject()
