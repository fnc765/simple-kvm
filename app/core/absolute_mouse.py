"""Reliable absolute-mouse transition builders.

Motion packets may be coalesced, but button edges are state transitions and
must remain ordered.  These helpers build atomic serial sequences that first
place the pointer at the requested coordinate using the previous button state,
then apply the new state at the exact same coordinate.
"""

from __future__ import annotations

from .protocol import build_mouse_abs_report
from .serial_comm import PacketSequence, PacketStep


def build_absolute_button_transition(
    previous_buttons: int,
    next_buttons: int,
    x: int,
    y: int,
) -> PacketSequence:
    """Build ``position/old-state -> same-position/new-state``.

    A release-all cleanup packet is included so a serial write failure cannot
    intentionally leave the target in a held-button state.
    """
    before = build_mouse_abs_report(previous_buttons, x, y)
    after = build_mouse_abs_report(next_buttons, x, y)
    release = build_mouse_abs_report(0, x, y)
    return PacketSequence(
        steps=(PacketStep(before), PacketStep(after)),
        cleanup_data=release,
    )


def build_absolute_click(button: int, x: int, y: int) -> PacketSequence:
    """Build an ordered move, button-down, button-up click transaction."""
    move = build_mouse_abs_report(0, x, y)
    down = build_mouse_abs_report(button, x, y)
    up = build_mouse_abs_report(0, x, y)
    return PacketSequence(
        steps=(PacketStep(move), PacketStep(down), PacketStep(up)),
        cleanup_data=up,
    )
