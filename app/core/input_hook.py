"""
input_hook.py – Keyboard and mouse input state tracker for KVM forwarding.

This module tracks the "live" state of all pressed keys and mouse buttons so
that the mainwindow can generate correct HID reports on every key event.

Two input paths are supported:
  1. Qt events (keyPressEvent / keyReleaseEvent) – always available.
  2. Windows Raw Input (RawInputHook) – optional, provides scancode-level
     precision for full left/right modifier and numpad discrimination.

No external hooks (pynput etc.) are used.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
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


# ---------------------------------------------------------------------------
# Windows Raw Input – ctypes structures
# ---------------------------------------------------------------------------

class RAWINPUTHEADER(ctypes.Structure):
    """RAWINPUTHEADER from the Windows SDK."""
    _fields_ = [
        ("dwType",  wintypes.DWORD),
        ("dwSize",  wintypes.DWORD),
        ("hDevice", wintypes.HANDLE),
        ("wParam",  wintypes.WPARAM),
    ]


class RAWKEYBOARD(ctypes.Structure):
    """RAWKEYBOARD structure from the Windows SDK.

    https://learn.microsoft.com/en-us/windows/win32/api/winuser/ns-winuser-rawkeyboard
    """
    _fields_ = [
        ("MakeCode",         wintypes.USHORT),
        ("Flags",            wintypes.USHORT),
        ("Reserved",         wintypes.USHORT),
        ("VKey",             wintypes.USHORT),
        ("Message",          wintypes.UINT),
        ("ExtraInformation", wintypes.ULONG),
    ]


# ---------------------------------------------------------------------------
# RawInputHook – Windows WM_INPUT keyboard capture
# ---------------------------------------------------------------------------

class RawInputHook:
    """Captures keyboard input via the Windows Raw Input API.

    Unlike Qt's key events, Raw Input exposes the raw scan code and E0 flag
    directly, enabling precise physical-key discrimination (left vs right
    modifiers, numpad vs main keys, navigation cluster vs numpad, etc.).

    Usage::

        hook = RawInputHook(on_key_down=my_down, on_key_up=my_up)
        hook.register(hwnd)                     # one-time registration

        # In nativeEvent():
        if hook.handle_message(msg, lparam):
            return True, 0

    The callbacks receive ``(scancode, vk, flags, is_e0)`` where:

    *scancode*
        The Set-1 scan code (MakeCode field).
    *vk*
        OS-resolved virtual key (VK_LCONTROL, VK_ESCAPE, …).
    *flags*
        Raw RI_KEY_* flags bitmask.
    *is_e0*
        ``True`` if the E0 prefix was present.
    """

    # Raw Input constants
    RID_INPUT       = 0x10000003
    RIM_TYPEKEYBOARD = 1
    RI_KEY_MAKE     = 0
    RI_KEY_BREAK    = 1
    RI_KEY_E0       = 2
    RI_KEY_E1       = 4

    def __init__(self, on_key_down, on_key_up):
        """
        Args:
            on_key_down: callable(scancode, vk, flags, is_e0) for key press.
            on_key_up:   callable(scancode, vk, flags, is_e0) for key release.
        """
        self._on_key_down = on_key_down
        self._on_key_up   = on_key_up

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(self, hwnd: int) -> bool:
        """Register *hwnd* to receive ``WM_INPUT`` for keyboard devices.

        Returns:
            ``True`` on success (non-zero return from
            ``RegisterRawInputDevices``).
        """
        RIDEV_INPUTSINK = 0x00000100
        RIDEV_NOHOTKEYS = 0x00000200

        class _RAWINPUTDEVICE(ctypes.Structure):
            _fields_ = [
                ("usUsagePage", wintypes.USHORT),
                ("usUsage",     wintypes.USHORT),
                ("dwFlags",     wintypes.DWORD),
                ("hwndTarget",  wintypes.HWND),
            ]

        dev = _RAWINPUTDEVICE()
        dev.usUsagePage = 0x01   # Generic Desktop
        dev.usUsage     = 0x06   # Keyboard
        dev.dwFlags     = RIDEV_INPUTSINK | RIDEV_NOHOTKEYS
        dev.hwndTarget  = hwnd

        result = ctypes.windll.user32.RegisterRawInputDevices(
            ctypes.byref(dev), 1, ctypes.sizeof(dev)
        )
        return bool(result)

    # ------------------------------------------------------------------
    # Message dispatch
    # ------------------------------------------------------------------

    def handle_message(self, msg: int, lparam: int) -> bool:
        """Process a ``WM_INPUT`` message.

        Call this from :meth:`QWidget.nativeEvent` whenever the message
        ID is ``0x00FF`` (WM_INPUT).

        Returns:
            ``True`` if the message was consumed (the caller should return
            ``(True, 0)`` from ``nativeEvent``).
        """
        if msg != 0x00FF:  # WM_INPUT
            return False

        HEADER_SIZE = ctypes.sizeof(RAWINPUTHEADER)

        # Query required buffer size
        size = wintypes.UINT()
        ret = ctypes.windll.user32.GetRawInputData(
            lparam, self.RID_INPUT, None,
            ctypes.byref(size), HEADER_SIZE,
        )
        if ret == 0xFFFFFFFF or ret == 0:
            return False

        buf = ctypes.create_string_buffer(size.value)
        ret = ctypes.windll.user32.GetRawInputData(
            lparam, self.RID_INPUT, buf,
            ctypes.byref(size), HEADER_SIZE,
        )
        if ret == 0xFFFFFFFF or ret == 0:
            return False

        # RAWINPUT buffer layout: [RAWINPUTHEADER][RAWKEYBOARD]
        header = ctypes.cast(buf, ctypes.POINTER(RAWINPUTHEADER)).contents
        if header.dwType != self.RIM_TYPEKEYBOARD:
            return False

        # RAWKEYBOARD starts at offset HEADER_SIZE
        kb = RAWKEYBOARD.from_buffer_copy(buf[HEADER_SIZE:])
        scancode = kb.MakeCode
        flags    = kb.Flags
        vk       = kb.VKey

        # Discard E1-prefixed sequences (Pause key etc.) – too complex
        if flags & self.RI_KEY_E1:
            return True

        is_e0 = bool(flags & self.RI_KEY_E0)
        is_up = bool(flags & self.RI_KEY_BREAK)

        if is_up:
            if self._on_key_up:
                self._on_key_up(scancode, vk, flags, is_e0)
        else:
            if self._on_key_down:
                self._on_key_down(scancode, vk, flags, is_e0)

        return True
