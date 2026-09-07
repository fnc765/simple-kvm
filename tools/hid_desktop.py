"""Windows desktop attachment used by fail-closed HID verification tools."""

from __future__ import annotations

import ctypes
import os
from ctypes import wintypes


user32 = ctypes.WinDLL("user32", use_last_error=True) if os.name == "nt" else None
_input_desktop_handle: wintypes.HANDLE | None = None
_INPUT_DESKTOP_ACCESS = 0x0001 | 0x0002 | 0x0080 | 0x0100


def attach_to_input_desktop() -> None:
    """Move the calling thread to the interactive input desktop."""

    global _input_desktop_handle
    if user32 is None:
        raise RuntimeError("Windows user32 is unavailable")
    user32.OpenInputDesktop.argtypes = [
        wintypes.DWORD,
        wintypes.BOOL,
        wintypes.DWORD,
    ]
    user32.OpenInputDesktop.restype = wintypes.HANDLE
    user32.SetThreadDesktop.argtypes = [wintypes.HANDLE]
    user32.SetThreadDesktop.restype = wintypes.BOOL
    handle = user32.OpenInputDesktop(0, False, _INPUT_DESKTOP_ACCESS)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    if not user32.SetThreadDesktop(handle):
        error = ctypes.get_last_error()
        user32.CloseDesktop(handle)
        raise ctypes.WinError(error)
    # Keep the desktop handle alive for the lifetime of the Raw Input window.
    _input_desktop_handle = handle
