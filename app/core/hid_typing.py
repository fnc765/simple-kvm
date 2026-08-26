"""Build cancellable USB HID sequences for generated ASCII text."""

from __future__ import annotations

from threading import Event

from core.keyboard_layouts import KeyboardLayout, coerce_keyboard_layout
from core.protocol import build_keyboard_report
from core.serial_comm import PacketSequence, PacketStep


DEFAULT_HID_REPORT_DELAY_MS = 10


def ascii_char_to_hid(
    char: str,
    keyboard_layout: KeyboardLayout | str = KeyboardLayout.US,
) -> tuple[int, int] | None:
    """Map one supported ASCII character to ``(modifier, HID usage)``.

    Alphanumerics are shared by both layouts. Standard Base64's ``=`` and
    ``+`` use different physical keys on US and Japanese JIS keyboards.
    """
    if len(char) != 1:
        raise ValueError("expected exactly one character")
    layout = coerce_keyboard_layout(keyboard_layout)
    if "a" <= char <= "z":
        return 0, 0x04 + ord(char) - ord("a")
    if "A" <= char <= "Z":
        return 0x02, 0x04 + ord(char) - ord("A")  # Left Shift
    if "1" <= char <= "9":
        return 0, 0x1E + ord(char) - ord("1")
    if char == "0":
        return 0, 0x27
    if char == " ":
        return 0, 0x2C
    if char == "=":
        if layout is KeyboardLayout.JIS:
            return 0x02, 0x2D  # Shift + Minus on JIS
        return 0, 0x2E  # Equal on US
    if char == "+":
        if layout is KeyboardLayout.JIS:
            return 0x02, 0x33  # Shift + Semicolon on JIS
        return 0x02, 0x2E  # Shift + Equal on US
    if char == "/":
        return 0, 0x38
    return None


def estimate_ascii_typing_seconds(
    character_count: int,
    *,
    report_delay_ms: int = DEFAULT_HID_REPORT_DELAY_MS,
) -> float:
    """Estimate sequence duration from the configured inter-report delay."""
    if character_count < 0:
        raise ValueError("character count cannot be negative")
    if report_delay_ms < 0:
        raise ValueError("report delay cannot be negative")
    delayed_reports = 1 + (2 * character_count)
    return delayed_reports * report_delay_ms / 1_000


def build_ascii_typing_sequence(
    text: str,
    *,
    report_delay_ms: int = DEFAULT_HID_REPORT_DELAY_MS,
    cancel_event: Event | None = None,
    transfer_id: str | None = None,
    track_progress: bool = False,
    keyboard_layout: KeyboardLayout | str = KeyboardLayout.US,
) -> PacketSequence:
    """Build an atomic press/release sequence for supported ASCII text."""
    if report_delay_ms < 0:
        raise ValueError("report delay cannot be negative")
    if track_progress and not transfer_id:
        raise ValueError("tracked typing sequence requires a transfer id")

    strokes: list[tuple[int, int]] = []
    for char in text:
        stroke = ascii_char_to_hid(char, keyboard_layout)
        if stroke is None:
            raise ValueError("text contains unsupported ASCII characters")
        strokes.append(stroke)
    if not strokes:
        raise ValueError("text must contain at least one supported character")

    released = build_keyboard_report(0, [])
    steps = [PacketStep(released, report_delay_ms)]
    for modifier, usage in strokes:
        steps.append(
            PacketStep(
                build_keyboard_report(modifier, [usage]),
                report_delay_ms,
            )
        )
        steps.append(
            PacketStep(
                released,
                report_delay_ms,
                progress_units=1 if track_progress else 0,
            )
        )
    steps.append(PacketStep(released, 0))

    return PacketSequence(
        tuple(steps),
        cleanup_data=released,
        cancel_event=cancel_event,
        transfer_id=transfer_id,
        progress_total=len(text) if track_progress else 0,
    )
