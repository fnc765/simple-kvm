"""Encode clipboard text and build a pure standard-Base64 HID transfer."""

from __future__ import annotations

import base64
from dataclasses import dataclass
from threading import Event

from core.hid_typing import (
    DEFAULT_HID_REPORT_DELAY_MS,
    build_ascii_typing_sequence,
    estimate_ascii_typing_seconds,
)
from core.keyboard_layouts import KeyboardLayout
from core.serial_comm import PacketSequence


@dataclass(frozen=True)
class Base64ClipboardPayload:
    """Prepared clipboard text and its standard Base64 representation."""

    source_characters: int
    utf8_bytes: int
    encoded_text: str
    estimated_seconds: float

    @property
    def encoded_characters(self) -> int:
        return len(self.encoded_text)


def encode_clipboard_text(
    source: str,
    *,
    report_delay_ms: int = DEFAULT_HID_REPORT_DELAY_MS,
) -> Base64ClipboardPayload:
    """Return unwrapped standard Base64 for the complete UTF-8 text."""
    if not isinstance(source, str):
        raise TypeError("clipboard source must be text")
    if source == "":
        raise ValueError("clipboard text is empty")

    utf8 = source.encode("utf-8")
    encoded = base64.b64encode(utf8).decode("ascii")
    return Base64ClipboardPayload(
        source_characters=len(source),
        utf8_bytes=len(utf8),
        encoded_text=encoded,
        estimated_seconds=estimate_ascii_typing_seconds(
            len(encoded),
            report_delay_ms=report_delay_ms,
        ),
    )


def build_base64_typing_sequence(
    payload: Base64ClipboardPayload,
    *,
    transfer_id: str,
    cancel_event: Event,
    report_delay_ms: int = DEFAULT_HID_REPORT_DELAY_MS,
    keyboard_layout: KeyboardLayout | str = KeyboardLayout.JIS,
) -> PacketSequence:
    """Build a tracked sequence that types only the Base64 payload."""
    return build_ascii_typing_sequence(
        payload.encoded_text,
        report_delay_ms=report_delay_ms,
        cancel_event=cancel_event,
        transfer_id=transfer_id,
        track_progress=True,
        keyboard_layout=keyboard_layout,
    )
