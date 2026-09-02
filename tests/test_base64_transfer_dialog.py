"""Offscreen tests for the Base64 transfer progress dialog."""

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))

from PySide6.QtWidgets import QApplication  # noqa: E402

from core.clipboard_base64 import encode_clipboard_text  # noqa: E402
from core.keyboard_layouts import KeyboardLayout  # noqa: E402
from ui.base64_transfer_dialog import Base64TransferDialog  # noqa: E402


app = QApplication.instance() or QApplication([])


def test_dialog_defaults_to_jis_and_allows_us_selection():
    dialog = Base64TransferDialog(encode_clipboard_text("layout"))

    assert dialog.keyboard_layout is KeyboardLayout.JIS
    dialog._layout_combo.setCurrentIndex(
        dialog._layout_combo.findData(KeyboardLayout.US.value)
    )
    assert dialog.keyboard_layout is KeyboardLayout.US

    dialog.begin_transfer()
    assert dialog._layout_combo.isEnabled() is False
    dialog.set_outcome("cancelled")
    dialog.close()
    dialog.deleteLater()


def test_dialog_reports_progress_and_completed_outcome():
    payload = encode_clipboard_text("日本語")
    dialog = Base64TransferDialog(payload)

    dialog.begin_transfer()
    dialog.set_progress(3, payload.encoded_characters)

    assert dialog._progress.value() == (
        3 * 100 // payload.encoded_characters
    )
    assert dialog._count_label.text().startswith("3 /")

    dialog.set_outcome("completed")

    assert dialog._progress.value() == 100
    assert dialog._progress.format() == "100%"
    assert dialog._secondary_button.text() == "Close"
    assert "sent" in dialog._status_label.text().lower()
    dialog.close()
    dialog.deleteLater()


def test_dialog_emits_cancel_once_and_waits_for_terminal_outcome():
    dialog = Base64TransferDialog(encode_clipboard_text("cancel me"))
    requests = []
    dialog.cancel_requested.connect(lambda: requests.append(True))

    dialog.begin_transfer()
    dialog.request_cancel()
    dialog.request_cancel()

    assert requests == [True]
    assert dialog._secondary_button.isEnabled() is False
    assert "cancelling" in dialog._status_label.text().lower()

    dialog.set_outcome("cancelled")

    assert dialog._secondary_button.isEnabled() is True
    assert "cancelled" in dialog._status_label.text().lower()
    dialog.close()
    dialog.deleteLater()
