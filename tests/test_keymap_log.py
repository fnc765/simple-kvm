"""Debug tool: log Raw Input key events with full details."""
import sys, os, ctypes
from ctypes import wintypes
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))
from core.keymap import scancode_to_hid, vk_to_modifier
from core.input_hook import RawInputHook


def log_key_down(scancode, vk, flags, is_e0):
    mod = vk_to_modifier(vk)
    hid = scancode_to_hid(scancode, is_e0, vk) if not mod else 0
    print(f"↓ sc=0x{scancode:02X} vk=0x{vk:02X} e0={int(is_e0)} | "
          f"mod=0x{mod:02X} hid=0x{hid:02X}")


def log_key_up(scancode, vk, flags, is_e0):
    mod = vk_to_modifier(vk)
    hid = scancode_to_hid(scancode, is_e0, vk) if not mod else 0
    print(f"↑ sc=0x{scancode:02X} vk=0x{vk:02X} e0={int(is_e0)} | "
          f"mod=0x{mod:02X} hid=0x{hid:02X}")


if __name__ == "__main__":
    print("Raw Input Key Logger - press keys to see scancode/VK/HID mapping")
    print("Press Ctrl+C to exit\n")

    hook = RawInputHook(log_key_down, log_key_up)

    # Register on the console window
    hwnd = ctypes.windll.kernel32.GetConsoleWindow()
    hook.register(hwnd)

    # Windows message loop
    msg = wintypes.MSG()
    while True:
        if ctypes.windll.user32.PeekMessageW(ctypes.byref(msg), 0, 0, 0, 1):
            if msg.message == 0x00FF:  # WM_INPUT
                hook.handle_message(msg.message, msg.lParam)
            ctypes.windll.user32.TranslateMessage(ctypes.byref(msg))
            ctypes.windll.user32.DispatchMessageW(ctypes.byref(msg))
