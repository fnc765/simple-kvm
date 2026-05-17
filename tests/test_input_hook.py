"""Unit tests for input_hook.py - InputState tracking."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))
from core.input_hook import InputState


def test_input_state():
    s = InputState()

    # Modifier press/release
    assert s.press_modifier(0x02) == True   # LShift
    assert s.press_modifier(0x02) == False  # already pressed
    assert s.release_modifier(0x02) == True
    assert s.release_modifier(0x02) == False # already released

    # Key press/release
    assert s.press_key(0x04) == True   # 'a'
    assert s.press_key(0x04) == False  # duplicate
    assert s.release_key(0x04) == True
    assert s.release_key(0x04) == False

    # 6KRO limit
    for k in [0x04, 0x05, 0x06, 0x07, 0x08, 0x09]:
        s.press_key(k)
    assert s.press_key(0x0A) == False  # 7th key blocked

    # Keyboard report
    s2 = InputState()
    s2.press_modifier(0x02)  # Shift
    s2.press_key(0x04)       # 'a'
    mod, keys = s2.get_keyboard_report()
    assert mod == 0x02
    assert keys[0] == 0x04
    assert keys[1:] == [0, 0, 0, 0, 0]

    print("All InputState tests passed!")


if __name__ == "__main__":
    test_input_state()
