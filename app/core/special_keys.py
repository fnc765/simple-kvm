"""Predefined keyboard chords that cannot be captured reliably locally."""

from __future__ import annotations

from dataclasses import dataclass

from core.protocol import build_keyboard_report
from core.serial_comm import PacketSequence, PacketStep


@dataclass(frozen=True)
class SpecialKeyPreset:
    """A named HID keyboard chord and its press/release timing."""

    id: str
    label: str
    modifier: int
    keys: tuple[int, ...]
    hold_ms: int = 20
    release_retry_ms: int = 10

    def __post_init__(self) -> None:
        if not self.id or not self.label:
            raise ValueError("preset id and label must not be empty")
        if not 0 <= self.modifier <= 0xFF:
            raise ValueError("modifier must fit in one byte")
        if not 1 <= len(self.keys) <= 6:
            raise ValueError("preset must contain between one and six keys")
        if len(self.keys) != len(set(self.keys)):
            raise ValueError("preset keys must be unique")
        if any(not 1 <= key <= 0xFF for key in self.keys):
            raise ValueError("key usages must be between 0x01 and 0xFF")
        if self.hold_ms < 0 or self.release_retry_ms < 0:
            raise ValueError("preset delays cannot be negative")

    def build_sequence(self) -> PacketSequence:
        """Build press, release, and redundant release packets."""
        pressed = build_keyboard_report(self.modifier, list(self.keys))
        released = build_keyboard_report(0, [])
        return PacketSequence((
            PacketStep(pressed, self.hold_ms),
            PacketStep(released, self.release_retry_ms),
            PacketStep(released),
        ), cleanup_data=released)


CTRL_ALT_DELETE = SpecialKeyPreset(
    id="ctrl_alt_delete",
    label="Ctrl+Alt+Delete",
    modifier=0x01 | 0x04,
    keys=(0x4C,),
)

CTRL_SHIFT_ESCAPE = SpecialKeyPreset(
    id="ctrl_shift_escape",
    label="Ctrl+Shift+Esc",
    modifier=0x01 | 0x02,
    keys=(0x29,),
)

ALT_F4 = SpecialKeyPreset(
    id="alt_f4",
    label="Alt+F4",
    modifier=0x04,
    keys=(0x3D,),
)

WIN_L = SpecialKeyPreset(
    id="win_l",
    label="Win+L",
    modifier=0x08,
    keys=(0x0F,),
)

WIN_R = SpecialKeyPreset(
    id="win_r",
    label="Win+R",
    modifier=0x08,
    keys=(0x15,),
)

COMMAND_OPTION_ESCAPE = SpecialKeyPreset(
    id="command_option_escape",
    label="Command+Option+Esc",
    modifier=0x08 | 0x04,
    keys=(0x29,),
)

BIOS_DELETE = SpecialKeyPreset(
    id="delete",
    label="Delete",
    modifier=0x00,
    keys=(0x4C,),
)

BIOS_F2 = SpecialKeyPreset(
    id="f2",
    label="F2",
    modifier=0x00,
    keys=(0x3B,),
)

BIOS_F12 = SpecialKeyPreset(
    id="f12",
    label="F12",
    modifier=0x00,
    keys=(0x45,),
)

SPECIAL_KEY_PRESETS = (
    CTRL_ALT_DELETE,
    CTRL_SHIFT_ESCAPE,
    ALT_F4,
    WIN_L,
    WIN_R,
    COMMAND_OPTION_ESCAPE,
    BIOS_DELETE,
    BIOS_F2,
    BIOS_F12,
)
