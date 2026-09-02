"""Hardware-free tests for pure Base64 clipboard typing helpers."""

import base64
import os
import re
import sys
from threading import Event

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))

from core.clipboard_base64 import (  # noqa: E402
    build_base64_typing_sequence,
    encode_clipboard_text,
)
from core.hid_typing import ascii_char_to_hid  # noqa: E402
from core.keyboard_layouts import KeyboardLayout  # noqa: E402


def test_japanese_newline_and_emoji_are_encoded_as_pure_standard_base64():
    source = "日本語\n😀"

    payload = encode_clipboard_text(source)

    assert payload.encoded_text == "5pel5pys6KqeCvCfmIA="
    assert base64.b64decode(payload.encoded_text).decode("utf-8") == source
    assert re.fullmatch(r"[A-Za-z0-9+/]+={0,2}", payload.encoded_text)
    assert "\n" not in payload.encoded_text
    assert payload.source_characters == len(source)
    assert payload.utf8_bytes == len(source.encode("utf-8"))


def test_whitespace_only_text_is_preserved_but_empty_text_is_rejected():
    payload = encode_clipboard_text(" \n\t")

    assert base64.b64decode(payload.encoded_text).decode("utf-8") == " \n\t"
    with pytest.raises(ValueError, match="empty"):
        encode_clipboard_text("")


def test_every_standard_base64_character_has_a_hid_mapping_for_both_layouts():
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/="

    for layout in KeyboardLayout:
        assert all(
            ascii_char_to_hid(char, layout) is not None
            for char in alphabet
        )

    assert ascii_char_to_hid("+", KeyboardLayout.US) == (0x02, 0x2E)
    assert ascii_char_to_hid("=", KeyboardLayout.US) == (0, 0x2E)
    assert ascii_char_to_hid("+", KeyboardLayout.JIS) == (0x02, 0x33)
    assert ascii_char_to_hid("=", KeyboardLayout.JIS) == (0x02, 0x2D)
    assert ascii_char_to_hid("/", KeyboardLayout.US) == (0, 0x38)
    assert ascii_char_to_hid("/", KeyboardLayout.JIS) == (0, 0x38)

    with pytest.raises(ValueError, match="unsupported keyboard layout"):
        ascii_char_to_hid("=", "dvorak")


def test_base64_sequence_defaults_to_jis_symbol_keys_and_can_select_us():
    payload = encode_clipboard_text("A")  # QQ== exercises Base64 padding.

    jis = build_base64_typing_sequence(
        payload,
        transfer_id="jis-transfer",
        cancel_event=Event(),
    )
    us = build_base64_typing_sequence(
        payload,
        transfer_id="us-transfer",
        cancel_event=Event(),
        keyboard_layout=KeyboardLayout.US,
    )

    # Last Base64 character is '='. Press report payload is modifier/reserved/key.
    assert jis.steps[-3].data[3:6] == bytes([0x02, 0, 0x2D])
    assert us.steps[-3].data[3:6] == bytes([0, 0, 0x2E])


def test_base64_sequence_tracks_one_progress_unit_per_typed_character():
    payload = encode_clipboard_text("日本語")
    cancel = Event()

    sequence = build_base64_typing_sequence(
        payload,
        transfer_id="transfer-1",
        cancel_event=cancel,
    )

    assert sequence.transfer_id == "transfer-1"
    assert sequence.cancel_event is cancel
    assert sequence.progress_total == payload.encoded_characters
    assert sum(step.progress_units for step in sequence.steps) == len(
        payload.encoded_text
    )
    assert len(sequence.steps) == 2 * payload.encoded_characters + 2
    # Only press steps carry a key usage; Enter (0x28) must never be added.
    press_usages = [
        sequence.steps[index].data[5]
        for index in range(1, len(sequence.steps) - 1, 2)
    ]
    assert 0x28 not in press_usages

    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/="
    inverse_mapping = {
        ascii_char_to_hid(char): char
        for char in alphabet
    }
    typed_text = "".join(
        inverse_mapping[(
            sequence.steps[index].data[3],
            sequence.steps[index].data[5],
        )]
        for index in range(1, len(sequence.steps) - 1, 2)
    )
    assert typed_text == payload.encoded_text
