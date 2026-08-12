"""Hardware-free tests for the Amical romaji/HID bridge."""

import os
import sys
from threading import Event

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))

from core.amical_bridge import (  # noqa: E402
    AmicalPasteGate,
    ascii_char_to_hid,
    build_ascii_typing_sequence,
    romanize_for_hid,
)


def test_romanize_japanese_and_drop_symbols():
    result = romanize_for_hid("今日はテスト123です。")

    assert result.text == "konnichiha tesuto 123 desu"
    assert result.source_length == 12
    assert result.dropped_symbols == 1
    assert result.truncated is False


def test_romanize_keeps_only_ascii_words_and_normalizes_spaces():
    result = romanize_for_hid("Simple KVMで音声入力しています！？")

    assert result.text == "Simple KVM de onseinyuuryoku shiteimasu"
    assert all(char.isascii() and (char.isalnum() or char == " ")
               for char in result.text)


def test_romanize_reports_truncation():
    result = romanize_for_hid("テストテスト", max_characters=7)

    assert result.text == "tesutot"
    assert result.truncated is True


def test_ascii_hid_mapping_supports_letters_digits_and_space():
    assert ascii_char_to_hid("a") == (0, 0x04)
    assert ascii_char_to_hid("Z") == (0x02, 0x1D)
    assert ascii_char_to_hid("1") == (0, 0x1E)
    assert ascii_char_to_hid("0") == (0, 0x27)
    assert ascii_char_to_hid(" ") == (0, 0x2C)
    assert ascii_char_to_hid("-") is None


def test_typing_sequence_has_release_between_every_character():
    cancel = Event()
    sequence = build_ascii_typing_sequence(
        "a A0",
        report_delay_ms=10,
        cancel_event=cancel,
    )

    assert sequence.cancel_event is cancel
    assert len(sequence.steps) == 2 * len("a A0") + 2
    # Framed keyboard packet payload starts at byte 3:
    # modifier, reserved, then the first HID usage.
    assert sequence.steps[1].data[3:6] == bytes([0, 0, 0x04])
    assert sequence.steps[3].data[3:6] == bytes([0, 0, 0x2C])
    assert sequence.steps[5].data[3:6] == bytes([0x02, 0, 0x04])
    assert sequence.steps[7].data[3:6] == bytes([0, 0, 0x27])
    assert all(
        step.data[3:11] == bytes(8)
        for step in sequence.steps[0::2]
    )


def test_f9_gate_accepts_exactly_one_paste_before_timeout():
    gate = AmicalPasteGate(timeout_seconds=5.0)

    assert gate.on_f9_down(now=10.0) is True
    assert gate.on_f9_down(now=10.1) is False
    assert gate.on_f9_up(now=12.0) is True
    assert gate.is_waiting(now=16.9) is True
    assert gate.consume(now=16.9) is True
    assert gate.consume(now=17.0) is False

    assert gate.on_f9_down(now=20.0) is True
    assert gate.on_f9_up(now=20.1) is True
    assert gate.consume(now=25.2) is False
