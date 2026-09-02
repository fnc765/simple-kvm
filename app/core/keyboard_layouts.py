"""Keyboard-layout identifiers used for generated HID text."""

from __future__ import annotations

from enum import Enum


class KeyboardLayout(str, Enum):
    """Target-PC keyboard layouts supported by generated text typing."""

    JIS = "jis"
    US = "us"


def coerce_keyboard_layout(value: object) -> KeyboardLayout:
    """Return a layout enum or raise for unsupported values."""
    if isinstance(value, KeyboardLayout):
        return value
    try:
        return KeyboardLayout(str(value).strip().lower())
    except ValueError as exc:
        raise ValueError(f"unsupported keyboard layout: {value!r}") from exc
