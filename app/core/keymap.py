"""
keymap.py – Qt.Key / Qt.KeyboardModifier → HID Usage ID mappings.

Supports two input paths:
  1. Qt events   → qt_key_to_hid() / qt_modifiers_to_hid()  (fallback)
  2. Raw Input   → scancode_to_hid() / vk_to_modifier()     (preferred on Windows)

The Raw Input path uses Windows Set 1 scan codes (with E0 prefix flag)
to provide complete physical-key discrimination including:
  - Left vs right modifiers (LCtrl/RCtrl, LShift/RShift, LAlt/RAlt, LGUI/RGUI)
  - Numpad vs main keyboard keys (KP0–KP9 vs number row, etc.)
  - Navigation cluster vs numpad (Ins/Del/Home/End/PgUp/PgDn/arrows)

References:
  USB HID Usage Tables 1.4, Section 10: Keyboard/Keypad Usage Page (0x07)
  Windows Platform SDK – RAWKEYBOARD structure / scan code Set 1
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
    # NOTE: 0x35 is shared between JP Zenkaku/Hankaku and US Grave Accent.
    # The target PC interprets based on its own keyboard layout.
    Qt.Key.Key_QuoteLeft:    0x35,  # `  ~  (grave accent)

    # Japanese keyboard – 半角/全角 (Zenkaku/Hankaku)
    # Shares HID ID 0x35 with Grave Accent on US keyboards
    Qt.Key.Key_Zenkaku_Hankaku: 0x35,

    Qt.Key.Key_Comma:        0x36,  # ,  <
    Qt.Key.Key_Period:       0x37,  # .  >
    Qt.Key.Key_Slash:        0x38,  # /  ?

    # Japanese keyboard specific keys
    Qt.Key.Key_Muhenkan:            0x8B,   # 無変換
    Qt.Key.Key_Henkan:              0x8A,   # 変換
    Qt.Key.Key_Hiragana_Katakana:   0x88,   # ひらがな/カタカナ
    Qt.Key.Key_yen:                 0x8D,   # ¥

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
# Scan code (Set 1) → HID Usage ID  (Windows Raw Input path)
# ---------------------------------------------------------------------------
# Keys sent with the E0 prefix use a tuple key: (0xE0, make_code).
# Keys without E0 prefix use the raw byte directly.
#
# Modifier keys are also listed here for reference, but the preferred way to
# detect modifiers in the Raw Input path is via vk_to_modifier() which maps
# the Windows virtual-key code to the HID modifier bitmask with full L/R
# discrimination.

_SCANCODE_TO_HID: dict[int | tuple[int, int], int] = {
    # ---- Letters A–Z (HID 0x04–0x1D) ----
    0x1E: 0x04,  # A
    0x30: 0x05,  # B
    0x2E: 0x06,  # C
    0x20: 0x07,  # D
    0x12: 0x08,  # E
    0x21: 0x09,  # F
    0x22: 0x0A,  # G
    0x23: 0x0B,  # H
    0x17: 0x0C,  # I
    0x24: 0x0D,  # J
    0x25: 0x0E,  # K
    0x26: 0x0F,  # L
    0x32: 0x10,  # M
    0x31: 0x11,  # N
    0x18: 0x12,  # O
    0x19: 0x13,  # P
    0x10: 0x14,  # Q
    0x13: 0x15,  # R
    0x1F: 0x16,  # S
    0x14: 0x17,  # T
    0x16: 0x18,  # U
    0x2F: 0x19,  # V
    0x11: 0x1A,  # W
    0x2D: 0x1B,  # X
    0x15: 0x1C,  # Y
    0x2C: 0x1D,  # Z

    # ---- Number row (HID 0x1E–0x27) ----
    0x02: 0x1E,  # 1
    0x03: 0x1F,  # 2
    0x04: 0x20,  # 3
    0x05: 0x21,  # 4
    0x06: 0x22,  # 5
    0x07: 0x23,  # 6
    0x08: 0x24,  # 7
    0x09: 0x25,  # 8
    0x0A: 0x26,  # 9
    0x0B: 0x27,  # 0

    # ---- Numpad (physical keys; no NumLock state needed) ----
    # Without E0: numpad keys.  With E0: navigation cluster (see below).
    (0xE0, 0x1C): 0x58,  # KP Enter
    (0xE0, 0x35): 0x54,  # KP /
    0x37:         0x55,  # KP *
    0x4A:         0x56,  # KP -
    0x4E:         0x57,  # KP +
    0x52:         0x62,  # KP 0 / Insert
    0x4F:         0x61,  # KP 1 / End
    0x50:         0x60,  # KP 2 / Down
    0x51:         0x5F,  # KP 3 / PgDn
    0x4B:         0x5E,  # KP 4 / Left
    0x4C:         0x5D,  # KP 5 (centre, no dual mapping)
    0x4D:         0x5C,  # KP 6 / Right
    0x47:         0x5B,  # KP 7 / Home
    0x48:         0x5A,  # KP 8 / Up
    0x49:         0x59,  # KP 9 / PgUp
    # KP . (make code 0x53, no E0 prefix).
    # Note: E0 0x53 is ambiguous (Delete vs KP .) and is mapped to
    # Delete (0x4C) below. Most keyboards send non-E0 0x53 for KP .
    0x53:         0x63,  # KP . (non-E0 variant)

    # ---- Function keys F1–F12 (HID 0x3A–0x45) ----
    0x3B: 0x3A,  # F1
    0x3C: 0x3B,  # F2
    0x3D: 0x3C,  # F3
    0x3E: 0x3D,  # F4
    0x3F: 0x3E,  # F5
    0x40: 0x3F,  # F6
    0x41: 0x40,  # F7
    0x42: 0x41,  # F8
    0x43: 0x42,  # F9
    0x44: 0x43,  # F10
    0x57: 0x44,  # F11
    0x58: 0x45,  # F12

    # ---- Navigation cluster (E0-prefixed) ----
    (0xE0, 0x48): 0x52,  # Up
    (0xE0, 0x50): 0x51,  # Down
    (0xE0, 0x4B): 0x50,  # Left
    (0xE0, 0x4D): 0x4F,  # Right
    (0xE0, 0x47): 0x4A,  # Home
    (0xE0, 0x4F): 0x4D,  # End
    (0xE0, 0x49): 0x4B,  # Page Up
    (0xE0, 0x51): 0x4E,  # Page Down
    (0xE0, 0x52): 0x49,  # Insert
    (0xE0, 0x53): 0x4C,  # Delete

    # ---- Special keys ----
    0x01: 0x29,  # Esc
    0x0E: 0x2A,  # Backspace
    0x0F: 0x2B,  # Tab
    0x1C: 0x28,  # Enter (main)
    0x39: 0x2C,  # Space
    0x3A: 0x39,  # Caps Lock

    # ---- Lock keys ----
    # Num Lock: 0x45 (no E0 on most keyboards, E0 on some)
    0x45:              0x53,  # Num Lock (non-E0)
    (0xE0, 0x45):      0x53,  # Num Lock (E0 variant)
    0x46:              0x47,  # Scroll Lock
    # Pause (0x48): uses a complex E1 3-byte sequence; skipped.

    # ---- Print Screen ----
    # Typical: E0 0x2A E0 0x37 (make) – we handle via the make code 0x37 with E0.
    (0xE0, 0x37):      0x46,  # Print Screen (E0-prefixed make)

    # ---- Modifier keys (scancode → HID usage ID, for reference) ----
    # Preferred detection: use vk_to_modifier() with the VKey field from
    # RAWKEYBOARD, as it yields the HID modifier byte bit directly.
    0x1D:              0xE0,  # Left Ctrl       (HID Keyboard LeftControl)
    0x2A:              0xE1,  # Left Shift      (HID Keyboard LeftShift)
    0x38:              0xE2,  # Left Alt        (HID Keyboard LeftAlt)
    (0xE0, 0x1D):      0xE4,  # Right Ctrl      (HID Keyboard RightControl)
    0x36:              0xE5,  # Right Shift     (HID Keyboard RightShift)
    (0xE0, 0x38):      0xE6,  # Right Alt      (HID Keyboard RightAlt)
    (0xE0, 0x5B):      0xE3,  # Left GUI        (HID Keyboard LeftGUI)
    (0xE0, 0x5C):      0xE7,  # Right GUI       (HID Keyboard RightGUI)

    # ---- Application / Menu key ----
    (0xE0, 0x5D):      0x65,  # Application (Menu)

    # ---- Punctuation / Symbols (US layout) ----
    # NOTE: 0x35 is shared between JP Zenkaku/Hankaku and US Grave Accent.
    # The target PC interprets based on its own keyboard layout.
    0x29: 0x35,  # ` ~  (Zenkaku/Hankaku 半角/全角 on JP keyboards)
    0x0C: 0x2D,  # - _
    0x0D: 0x2E,  # = +
    0x1A: 0x2F,  # [ {
    0x1B: 0x30,  # ] }
    0x2B: 0x31,  # \ |
    0x27: 0x33,  # ; :
    0x28: 0x34,  # ' "
    0x33: 0x36,  # , <
    0x34: 0x37,  # . >
    0x35: 0x38,  # / ?

    # ---- F13–F24 (extended keyboards) ----
    0x64: 0x68,  # F13
    0x65: 0x69,  # F14
    0x66: 0x6A,  # F15
    0x67: 0x6B,  # F16
    0x68: 0x6C,  # F17
    0x69: 0x6D,  # F18
    0x6A: 0x6E,  # F19
    0x6B: 0x6F,  # F20
    0x6C: 0x70,  # F21
    0x6D: 0x71,  # F22
    0x6E: 0x72,  # F23
    0x76: 0x73,  # F24

    # ---- Japanese keyboard specific (where different from US) ----
    # Japanese 109-key keyboard: Muhenkan, Henkan, Hiragana/Katakana, Yen.
    # Note: scan codes vary by keyboard vendor; these are common 106/109-key values.
    0x7B: 0x8B,  # 無変換 (Muhenkan)
    0x79: 0x8A,  # 変換   (Henkan)
    0x70: 0x88,  # ひらがな/カタカナ (Hiragana/Katakana)
    0x73: 0x87,  # ろ (Ro) – often produces 0x87 (International1)
    0x7D: 0x89,  # ¥ (Yen) – often 0x89 or 0x8D
    0x5C: 0x8D,  # ¥ (Yen, alternate)
}

# ---------------------------------------------------------------------------
# Virtual-Key → HID modifier bit  (Windows Raw Input path)
# ---------------------------------------------------------------------------
# Unlike the scancode table above, the VKey field in RAWKEYBOARD carries the
# OS-resolved virtual key, which already distinguishes left vs right variants
# of modifier keys (VK_LCONTROL vs VK_RCONTROL, etc.).

_VK_TO_MODIFIER: dict[int, int] = {
    0xA2: 0x01,  # VK_LCONTROL  → Left Ctrl
    0xA0: 0x02,  # VK_LSHIFT    → Left Shift
    0xA4: 0x04,  # VK_LMENU     → Left Alt
    0x5B: 0x08,  # VK_LWIN      → Left GUI (Windows)
    0xA3: 0x10,  # VK_RCONTROL  → Right Ctrl
    0xA1: 0x20,  # VK_RSHIFT    → Right Shift
    0xA5: 0x40,  # VK_RMENU     → Right Alt (AltGr)
    0x5C: 0x80,  # VK_RWIN      → Right GUI (Windows)
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


# ---------------------------------------------------------------------------
# Raw Input helpers (scancode / VK → HID)
# ---------------------------------------------------------------------------

def scancode_to_hid(scancode: int, is_e0: bool) -> int:
    """
    Convert a Windows Set-1 scan code + E0 flag to a HID Usage ID.

    Args:
        scancode: The MakeCode field from RAWKEYBOARD (0x01–0x7F).
        is_e0: True if the RI_KEY_E0 flag was set in the raw input.

    Returns:
        HID Usage ID (0x04–0xFF), or 0 if the key is not mapped.
        Modifier keys return their HID usage (0xE0–0xE7) but should be
        routed through vk_to_modifier() instead for the modifier byte.
    """
    if is_e0:
        key: int | tuple[int, int] = (0xE0, scancode)
    else:
        key = scancode
    return _SCANCODE_TO_HID.get(key, 0)


def vk_to_modifier(vk: int) -> int:
    """
    Return the HID modifier bit for a Windows virtual-key code.

    Args:
        vk: The VKey field from RAWKEYBOARD (e.g. 0xA2 = VK_LCONTROL).

    Returns:
        A single-bit HID modifier mask (0x01–0x80), or 0 if *vk* is not
        a recognised modifier key.
    """
    return _VK_TO_MODIFIER.get(vk, 0)
