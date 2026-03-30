"""
input_hook.py – Keyboard and mouse input state tracker for KVM forwarding.

This module tracks the "live" state of all pressed keys and mouse buttons so
that the mainwindow can generate correct HID reports on every key event.
No external hooks (pynput etc.) are used; all input comes via Qt events.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from threading import Lock

MAX_KEYS = 6  # HID 6-key rollover limit


@dataclass
class InputState:
    """
    Mutable live state of the current keyboard / mouse state.

    The mainwindow updates this on every keyPress/keyRelease/mousePress/
    mouseRelease event and reads it when building HID reports.
    All public methods are thread-safe via an internal Lock.
    """

    modifier: int = 0
    """HID modifier bitmask (LCtrl=0x01, LShift=0x02, LAlt=0x04, LGUI=0x08, …)"""

    pressed_keys: list[int] = field(default_factory=list)
    """List of active HID Usage IDs (at most MAX_KEYS entries)."""

    mouse_buttons: int = 0
    """Mouse button bitmask (bit0=Left, bit1=Right, bit2=Middle)."""

    _lock: Lock = field(default_factory=Lock, init=False, repr=False, compare=False)

    # ------------------------------------------------------------------
    # Modifier helpers
    # ------------------------------------------------------------------

    def press_modifier(self, bit: int) -> bool:
        """Set a modifier bit. Returns True if the state changed."""
        with self._lock:
            old = self.modifier
            self.modifier |= bit
            return self.modifier != old

    def release_modifier(self, bit: int) -> bool:
        """Clear a modifier bit. Returns True if the state changed."""
        with self._lock:
            old = self.modifier
            self.modifier &= ~bit
            return self.modifier != old

    # ------------------------------------------------------------------
    # Keyboard helpers
    # ------------------------------------------------------------------

    def press_key(self, keycode: int) -> bool:
        """
        Add *keycode* to the pressed set.

        Returns True if the state changed, False if the key was already
        pressed or the 6KRO limit was reached.
        """
        with self._lock:
            if keycode == 0 or keycode in self.pressed_keys:
                return False
            if len(self.pressed_keys) >= MAX_KEYS:
                return False  # 6KRO limit – drop silently
            self.pressed_keys.append(keycode)
            return True

    def release_key(self, keycode: int) -> bool:
        """
        Remove *keycode* from the pressed set.

        Returns True if the key was present and removed.
        """
        with self._lock:
            if keycode not in self.pressed_keys:
                return False
            self.pressed_keys.remove(keycode)
            return True

    def get_keyboard_report(self) -> tuple[int, list[int]]:
        """
        Return *(modifier, keys)* ready for :func:`~core.protocol.build_keyboard_report`.

        *keys* is always a list of exactly 6 entries (zero-padded).
        """
        with self._lock:
            padded = (self.pressed_keys + [0, 0, 0, 0, 0, 0])[:6]
            return self.modifier, padded

    # ------------------------------------------------------------------
    # Mouse helpers
    # ------------------------------------------------------------------

    def set_mouse_button(self, bit: int, pressed: bool) -> bool:
        """Set or clear a mouse button bit. Returns True if changed."""
        with self._lock:
            old = self.mouse_buttons
            if pressed:
                self.mouse_buttons |= bit
            else:
                self.mouse_buttons &= ~bit
            return self.mouse_buttons != old

    # ------------------------------------------------------------------
    # Reset
    # ------------------------------------------------------------------

    def clear_keys(self) -> None:
        """Release all keys, modifiers, and buttons (e.g. when focus is lost)."""
        with self._lock:
            self.pressed_keys.clear()
            self.modifier      = 0
            self.mouse_buttons = 0
