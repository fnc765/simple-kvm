"""
mouse_modes.py – Mouse input mode decision helpers for KVM forwarding.

Three mouse modes are supported:

* ``relative`` – existing behaviour: warp host cursor to widget centre
  and send PKT_MOUSE (relative dx/dy).  Works with any firmware.
* ``hybrid``   – at KVM activation time, send a single PKT_MOUSE_ABS
  jump so the target cursor snaps to the clicked-on video coordinate;
  afterwards behave as ``relative`` (centre warp + PKT_MOUSE).
  Requires firmware with absolute HID support.
* ``absolute`` – continuously translate the host cursor position inside
  the VideoWidget to a PKT_MOUSE_ABS.  Best for desktop / SteamVR
  desktop dashboard.  Requires firmware with absolute HID support.

These helpers are pure functions / dataclasses so they can be
unit-tested directly.  Qt types are intentionally avoided here.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class MouseMode(str, Enum):
    """Mouse input mode."""

    RELATIVE = "relative"
    HYBRID = "hybrid"
    ABSOLUTE = "absolute"


@dataclass(frozen=True)
class MouseModeConfig:
    """Snapshot of the current mouse-mode configuration."""

    mode: MouseMode
    firmware_abs_supported: bool
    fallback_relative_jump: bool = False


# ---------------------------------------------------------------------------
# Normalisation
# ---------------------------------------------------------------------------


def normalize_mouse_mode(value: Optional[str]) -> MouseMode:
    """Map a user-supplied setting string to a :class:`MouseMode`.

    Unknown / None values fall back to :attr:`MouseMode.RELATIVE` (the
    pre-existing behaviour) so the app keeps working when the
    ``input/mouse_mode`` key is missing or corrupted.
    """
    if not isinstance(value, str):
        return MouseMode.RELATIVE
    try:
        return MouseMode(value)
    except ValueError:
        return MouseMode.RELATIVE


# ---------------------------------------------------------------------------
# Behaviour predicates
# ---------------------------------------------------------------------------


def should_warp_cursor(cfg: MouseModeConfig) -> bool:
    """Whether the host cursor should be warped to the widget centre.

    ``absolute`` mode does NOT warp, because the host cursor position
    is the input source.
    """
    return cfg.mode is not MouseMode.ABSOLUTE


def should_hide_host_cursor(cfg: MouseModeConfig) -> bool:
    """Whether the host cursor should be hidden in KVM focus mode.

    In ``absolute`` mode the host cursor *is* the source of the
    absolute coordinate, so hiding it would make targeting impossible.
    """
    return cfg.mode is not MouseMode.ABSOLUTE


def can_send_absolute(cfg: MouseModeConfig) -> bool:
    """Whether :func:`core.protocol.build_mouse_abs_report` may be used.

    Requires both a mode that wants absolute coordinates
    (``hybrid`` / ``absolute``) AND a firmware that exposes the
    absolute mouse interface.
    """
    if not cfg.firmware_abs_supported:
        return False
    return cfg.mode in (MouseMode.HYBRID, MouseMode.ABSOLUTE)
