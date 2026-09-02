"""Pure helpers shared by the Windows hardware-loopback verifier.

The verifier itself talks to Windows Raw Input.  Keeping coordinate conversion
and ordering checks here makes the safety-critical assertions unit-testable on
machines that do not have either Blue Pill connected.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


HID_ABS_MAX = 32_767
RAW_ABS_MAX = 65_535

MOUSE_MOVE_ABSOLUTE = 0x0001
RI_MOUSE_LEFT_BUTTON_DOWN = 0x0001
RI_MOUSE_LEFT_BUTTON_UP = 0x0002


@dataclass(frozen=True)
class ObservedMouseEvent:
    """One mouse report observed through Windows Raw Input."""

    timestamp_ns: int
    device_name: str
    us_flags: int
    button_flags: int
    raw_x: int
    raw_y: int


@dataclass(frozen=True)
class ClickOrderResult:
    """Indices proving move-before-down-before-up for one click."""

    passed: bool
    move_index: int | None
    down_index: int | None
    up_index: int | None
    reason: str


def hid_to_raw_coordinate(value: int) -> int:
    """Convert the firmware's 0..32767 axis to Raw Input's 0..65535 axis."""

    clamped = max(0, min(HID_ABS_MAX, value))
    return round(clamped * RAW_ABS_MAX / HID_ABS_MAX)


def hid_to_screen_coordinate(value: int, extent: int) -> int:
    """Convert one HID axis to a primary-screen pixel coordinate."""

    if extent <= 0:
        raise ValueError("screen extent must be positive")
    clamped = max(0, min(HID_ABS_MAX, value))
    return round(clamped * (extent - 1) / HID_ABS_MAX)


def device_name_matches(
    device_name: str,
    *,
    vid: int = 0x046D,
    pid: int = 0xC52B,
    interface: int | None = 2,
) -> bool:
    """Return whether a Raw Input path identifies the expected BP2 HID."""

    normalized = device_name.upper()
    if f"VID_{vid:04X}&PID_{pid:04X}" not in normalized:
        return False
    return interface is None or f"MI_{interface:02X}" in normalized


def position_matches(
    event: ObservedMouseEvent,
    hid_x: int,
    hid_y: int,
    *,
    tolerance: int = 32,
) -> bool:
    """Check an absolute Raw Input event against an expected HID position."""

    return bool(event.us_flags & MOUSE_MOVE_ABSOLUTE) and (
        abs(event.raw_x - hid_to_raw_coordinate(hid_x)) <= tolerance
        and abs(event.raw_y - hid_to_raw_coordinate(hid_y)) <= tolerance
    )


def find_click_order(
    events: Iterable[ObservedMouseEvent],
    *,
    device_name: str,
    since_ns: int,
    hid_x: int,
    hid_y: int,
    tolerance: int = 32,
) -> ClickOrderResult:
    """Prove an absolute move, left-down, left-up subsequence."""

    relevant = [
        event
        for event in events
        if event.timestamp_ns >= since_ns and event.device_name == device_name
    ]
    down_index = next(
        (
            index
            for index, event in enumerate(relevant)
            if event.button_flags & RI_MOUSE_LEFT_BUTTON_DOWN
        ),
        None,
    )
    if down_index is None:
        return ClickOrderResult(False, None, None, None, "left-down not observed")

    move_index = next(
        (
            index
            for index, event in enumerate(relevant[:down_index])
            if not event.button_flags
            and position_matches(event, hid_x, hid_y, tolerance=tolerance)
        ),
        None,
    )
    if move_index is None:
        return ClickOrderResult(
            False,
            None,
            down_index,
            None,
            "matching absolute move did not precede left-down",
        )

    up_index = next(
        (
            index
            for index, event in enumerate(relevant[down_index + 1 :], down_index + 1)
            if event.button_flags & RI_MOUSE_LEFT_BUTTON_UP
        ),
        None,
    )
    if up_index is None:
        return ClickOrderResult(
            False,
            move_index,
            down_index,
            None,
            "left-up not observed after left-down",
        )

    return ClickOrderResult(
        True,
        move_index,
        down_index,
        up_index,
        "move/down/up order observed",
    )
