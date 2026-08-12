"""
settings_values.py – Pure persistence helpers for application input settings.

This module is Qt-free so the read/write/parse logic can be unit-tested
without spinning up a QApplication or a QSettings backend.  Callers
(such as MainWindow) pass a duck-typed object that implements
``value(key, default=None, type=None)`` and ``setValue(key, val)`` –
which is exactly the ``QSettings`` interface.

Boolean values are stored as the strings ``"true"`` / ``"false"`` so
the persisted format is portable (registry on Windows, plist on macOS,
INI on Linux).  This also matches how the rest of the app persists
configuration.
"""

from __future__ import annotations

from typing import Any

from .mouse_modes import MouseMode, normalize_mouse_mode

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MOUSE_MODE_KEY: str = "input/mouse_mode"
FIRMWARE_ABS_KEY: str = "input/firmware_abs_supported"
AMICAL_ROMAJI_ENABLED_KEY: str = "input/amical_romaji_enabled"

DEFAULT_MOUSE_MODE: MouseMode = MouseMode.RELATIVE
DEFAULT_FIRMWARE_ABS_SUPPORTED: bool = False
DEFAULT_AMICAL_ROMAJI_ENABLED: bool = False


# ---------------------------------------------------------------------------
# Mouse mode
# ---------------------------------------------------------------------------


def read_mouse_mode_setting(settings: Any) -> MouseMode:
    """Return the persisted mouse mode, falling back to the default."""
    raw = settings.value(MOUSE_MODE_KEY, DEFAULT_MOUSE_MODE.value)
    return normalize_mouse_mode(raw)


def write_mouse_mode_setting(settings: Any, mode: MouseMode) -> None:
    """Persist *mode* under :data:`MOUSE_MODE_KEY`."""
    settings.setValue(MOUSE_MODE_KEY, mode.value)


# ---------------------------------------------------------------------------
# Firmware abs supported
# ---------------------------------------------------------------------------


def parse_bool_setting(value: Any) -> bool:
    """Best-effort coerce of a stored value to bool.

    ``QSettings`` on different platforms can hand us back a string, a
    bool, or ``None``.  Treat ``"true"`` / ``"1"`` / ``"yes"`` / ``"on"``
    (case-insensitive) and Python ``True`` as truthy; everything else
    (including ``None`` and empty string) as falsy.
    """
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, str):
        return value.strip().lower() in ("true", "1", "yes", "on")
    return bool(value)


def read_firmware_abs_setting(settings: Any) -> bool:
    """Return the persisted firmware-abs-supported flag."""
    raw = settings.value(FIRMWARE_ABS_KEY, "false")
    return parse_bool_setting(raw)


def write_firmware_abs_setting(settings: Any, supported: bool) -> None:
    """Persist the firmware-abs-supported flag."""
    settings.setValue(FIRMWARE_ABS_KEY, "true" if supported else "false")


# ---------------------------------------------------------------------------
# Amical Romaji Forwarding
# ---------------------------------------------------------------------------


def read_amical_romaji_enabled_setting(settings: Any) -> bool:
    """Return whether the opt-in Amical forwarding feature is enabled."""
    raw = settings.value(AMICAL_ROMAJI_ENABLED_KEY, "false")
    return parse_bool_setting(raw)


def write_amical_romaji_enabled_setting(settings: Any, enabled: bool) -> None:
    """Persist the Amical forwarding feature flag."""
    settings.setValue(
        AMICAL_ROMAJI_ENABLED_KEY,
        "true" if enabled else "false",
    )
