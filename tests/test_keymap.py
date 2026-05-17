"""Unit tests for keymap.py - scan code and VK mappings."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))
from core.keymap import scancode_to_hid, vk_to_modifier, qt_key_to_hid


def test_numpad():
    """Verify numpad keys map to correct HID Usage IDs."""
    # Non-E0 numpad (PS/2 or some USB)
    assert scancode_to_hid(0x4F, False) == 0x59, "KP 1 should be 0x59"
    assert scancode_to_hid(0x50, False) == 0x5A, "KP 2 should be 0x5A"
    assert scancode_to_hid(0x51, False) == 0x5B, "KP 3 should be 0x5B"

    # VK-based disambiguation (USB keyboards with E0)
    assert scancode_to_hid(0x4F, True, 0x61) == 0x59, "KP 1 (USB) should be 0x59"
    assert scancode_to_hid(0x50, True, 0x62) == 0x5A, "KP 2 (USB) should be 0x5A"

    # Navigation keys with E0 (should NOT return numpad)
    assert scancode_to_hid(0x4F, True, 0x23) == 0x4D, "End should be 0x4D"


def test_modifiers():
    """Verify modifier VK→bit mapping (with scancode disambiguation)."""
    # Generic VK codes + scancode disambiguation
    assert vk_to_modifier(0x10, 0x2A) == 0x02, "VK_SHIFT + sc=0x2A → LShift"
    assert vk_to_modifier(0x10, 0x36) == 0x20, "VK_SHIFT + sc=0x36 → RShift"
    assert vk_to_modifier(0x11, 0x1D, False) == 0x01, "VK_CONTROL, no E0 → LCtrl"
    assert vk_to_modifier(0x11, 0x1D, True) == 0x10, "VK_CONTROL, E0 → RCtrl"
    assert vk_to_modifier(0x12, 0x38, False) == 0x04, "VK_MENU, no E0 → LAlt"
    assert vk_to_modifier(0x12, 0x38, True) == 0x40, "VK_MENU, E0 → RAlt"
    # Specific VK codes
    assert vk_to_modifier(0xA0) == 0x02, "VK_LSHIFT"
    assert vk_to_modifier(0xA1) == 0x20, "VK_RSHIFT"
    # Non-modifier
    assert vk_to_modifier(0x41) == 0, "VK_A is not modifier"


def test_common_keys():
    """Verify common key mappings."""
    assert scancode_to_hid(0x29, False) == 0x35, "半角/全角"
    assert scancode_to_hid(0x01, False) == 0x29, "Esc"
    assert scancode_to_hid(0x1C, False) == 0x28, "Enter"
    assert scancode_to_hid(0x39, False) == 0x2C, "Space"


def test_all():
    test_numpad()
    test_modifiers()
    test_common_keys()
    print("All tests passed!")


if __name__ == "__main__":
    test_all()
