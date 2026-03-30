"""
keymap.py – Qt.Key / Qt.KeyboardModifier → HID Usage ID mappings.

References:
  USB HID Usage Tables 1.4, Section 10: Keyboard/Keypad Usage Page (0x07)
"""

from PySide6.QtCore import Qt

# ---------------------------------------------------------------------------
# Qt.Key → HID Usage ID
# ---------------------------------------------------------------------------
_KEY_MAP: dict[int, int] = {
    # Letters A–Z  (HID 0x04–0x1D)
    Qt.Key.Key_A: 0x04,
    Qt.Key.Key_B: 0x05,
    Qt.Key.Key_C: 0x06,
    Qt.Key.Key_D: 0x07,
    Qt.Key.Key_E: 0x08,
    Qt.Key.Key_F: 0x09,
    Qt.Key.Key_G: 0x0A,
    Qt.Key.Key_H: 0x0B,
    Qt.Key.Key_I: 0x0C,
    Qt.Key.Key_J: 0x0D,
    Qt.Key.Key_K: 0x0E,
    Qt.Key.Key_L: 0x0F,
    Qt.Key.Key_M: 0x10,
    Qt.Key.Key_N: 0x11,
    Qt.Key.Key_O: 0x12,
    Qt.Key.Key_P: 0x13,
    Qt.Key.Key_Q: 0x14,
    Qt.Key.Key_R: 0x15,
    Qt.Key.Key_S: 0x16,
    Qt.Key.Key_T: 0x17,
    Qt.Key.Key_U: 0x18,
    Qt.Key.Key_V: 0x19,
    Qt.Key.Key_W: 0x1A,
    Qt.Key.Key_X: 0x1B,
    Qt.Key.Key_Y: 0x1C,
    Qt.Key.Key_Z: 0x1D,

    # Digits 1–9 / 0  (HID 0x1E–0x27)
    Qt.Key.Key_1: 0x1E,
    Qt.Key.Key_2: 0x1F,
    Qt.Key.Key_3: 0x20,
    Qt.Key.Key_4: 0x21,
    Qt.Key.Key_5: 0x22,
    Qt.Key.Key_6: 0x23,
    Qt.Key.Key_7: 0x24,
    Qt.Key.Key_8: 0x25,
    Qt.Key.Key_9: 0x26,
    Qt.Key.Key_0: 0x27,

    # Control keys
    Qt.Key.Key_Return:    0x28,  # Enter (main)
    Qt.Key.Key_Escape:    0x29,
    Qt.Key.Key_Backspace: 0x2A,
    Qt.Key.Key_Tab:       0x2B,
    Qt.Key.Key_Space:     0x2C,

    # Punctuation / symbols (US layout)
    Qt.Key.Key_Minus:        0x2D,  # -  _
    Qt.Key.Key_Equal:        0x2E,  # =  +
    Qt.Key.Key_BracketLeft:  0x2F,  # [  {
    Qt.Key.Key_BracketRight: 0x30,  # ]  }
    Qt.Key.Key_Backslash:    0x31,  # \  |
    Qt.Key.Key_Semicolon:    0x33,  # ;  :
    Qt.Key.Key_Apostrophe:   0x34,  # '  "
    Qt.Key.Key_QuoteLeft:    0x35,  # `  ~  (grave accent)
    Qt.Key.Key_Comma:        0x36,  # ,  <
    Qt.Key.Key_Period:       0x37,  # .  >
    Qt.Key.Key_Slash:        0x38,  # /  ?

    # Lock keys
    Qt.Key.Key_CapsLock:   0x39,
    Qt.Key.Key_NumLock:    0x53,
    Qt.Key.Key_ScrollLock: 0x47,

    # Function keys F1–F12  (HID 0x3A–0x45)
    Qt.Key.Key_F1:  0x3A,
    Qt.Key.Key_F2:  0x3B,
    Qt.Key.Key_F3:  0x3C,
    Qt.Key.Key_F4:  0x3D,
    Qt.Key.Key_F5:  0x3E,
    Qt.Key.Key_F6:  0x3F,
    Qt.Key.Key_F7:  0x40,
    Qt.Key.Key_F8:  0x41,
    Qt.Key.Key_F9:  0x42,
    Qt.Key.Key_F10: 0x43,
    Qt.Key.Key_F11: 0x44,
    Qt.Key.Key_F12: 0x45,

    # Extended function keys
    Qt.Key.Key_F13: 0x68,
    Qt.Key.Key_F14: 0x69,
    Qt.Key.Key_F15: 0x6A,
    Qt.Key.Key_F16: 0x6B,
    Qt.Key.Key_F17: 0x6C,
    Qt.Key.Key_F18: 0x6D,
    Qt.Key.Key_F19: 0x6E,
    Qt.Key.Key_F20: 0x6F,
    Qt.Key.Key_F21: 0x70,
    Qt.Key.Key_F22: 0x71,
    Qt.Key.Key_F23: 0x72,
    Qt.Key.Key_F24: 0x73,

    # System / navigation cluster
    Qt.Key.Key_Print:     0x46,  # Print Screen
    Qt.Key.Key_Pause:     0x48,
    Qt.Key.Key_Insert:    0x49,
    Qt.Key.Key_Home:      0x4A,
    Qt.Key.Key_PageUp:    0x4B,
    Qt.Key.Key_Delete:    0x4C,
    Qt.Key.Key_End:       0x4D,
    Qt.Key.Key_PageDown:  0x4E,
    Qt.Key.Key_Right:     0x4F,
    Qt.Key.Key_Left:      0x50,
    Qt.Key.Key_Down:      0x51,
    Qt.Key.Key_Up:        0x52,

    # Enter (numpad)
    Qt.Key.Key_Enter: 0x58,

    # Numpad keys: on Windows, Qt returns the same key codes as the main
    # keyboard digits when NumLock is on, making numpad vs main-key
    # indistinguishable at the Qt level.  This is a known limitation of
    # the Qt-only approach.  NumPad-specific HID IDs (0x59–0x63) cannot
    # be produced without OS-level hooks.
}

# ---------------------------------------------------------------------------
# Qt.KeyboardModifier → HID modifier bitmask
# ---------------------------------------------------------------------------
_MODIFIER_MAP: list[tuple[Qt.KeyboardModifier, int]] = [
    (Qt.KeyboardModifier.ControlModifier, 0x01),  # Left Ctrl
    (Qt.KeyboardModifier.ShiftModifier,   0x02),  # Left Shift
    (Qt.KeyboardModifier.AltModifier,     0x04),  # Left Alt
    (Qt.KeyboardModifier.MetaModifier,    0x08),  # Left GUI (Win/Cmd)
]

# Modifier keys themselves: map Qt.Key → (modifier bit, should NOT add to keys[])
# Note: Qt maps all Ctrl keys to Key_Control, all Shift keys to Key_Shift, etc.
# Right-side modifiers (RCtrl=0x10, RShift=0x20, RGUI=0x80) cannot be
# distinguished from left-side modifiers using Qt events alone.
_MODIFIER_KEYS: dict[int, int] = {
    Qt.Key.Key_Control:   0x01,
    Qt.Key.Key_Shift:     0x02,
    Qt.Key.Key_Alt:       0x04,
    Qt.Key.Key_Meta:      0x08,
    Qt.Key.Key_AltGr:     0x40,  # Right Alt
}


def qt_key_to_hid(qt_key: int) -> int:
    """
    Convert a Qt.Key value to a HID Usage ID.

    Returns 0 if the key is not mapped (or is a modifier key – those are
    handled separately via qt_modifiers_to_hid).
    """
    return _KEY_MAP.get(qt_key, 0)


def get_hid_keycode(qt_key: int) -> int | None:
    """Return the HID Usage ID for *qt_key*, or None if not mapped."""
    return _KEY_MAP.get(qt_key)


def get_modifier_bit(qt_key: int) -> int | None:
    """Return the HID modifier bitmask for a modifier key, or None if not a modifier."""
    return _MODIFIER_KEYS.get(qt_key)


def qt_modifiers_to_hid(modifiers: Qt.KeyboardModifier) -> int:
    """
    Convert Qt keyboard modifiers to the HID modifier byte.

    Maps Qt's combined modifier flags to the 8-bit HID modifier field.
    """
    result = 0
    for qt_mod, hid_bit in _MODIFIER_MAP:
        if modifiers & qt_mod:
            result |= hid_bit
    return result


def is_modifier_key(qt_key: int) -> bool:
    """Return True if the Qt key is a modifier key (Ctrl/Shift/Alt/Meta)."""
    return qt_key in _MODIFIER_KEYS
