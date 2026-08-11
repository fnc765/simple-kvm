"""Pure unit tests for predefined special-key chords."""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))

from core.special_keys import (  # noqa: E402
    CTRL_ALT_DELETE,
    SPECIAL_KEY_PRESETS,
    SpecialKeyPreset,
)


def test_ctrl_alt_delete_builds_press_and_redundant_release_sequence():
    sequence = CTRL_ALT_DELETE.build_sequence()

    assert CTRL_ALT_DELETE.modifier == 0x05
    assert CTRL_ALT_DELETE.keys == (0x4C,)
    assert len(sequence.steps) == 3

    press, release, release_retry = sequence.steps
    assert press.data[3:11] == bytes([0x05, 0x00, 0x4C, 0, 0, 0, 0, 0])
    assert press.delay_after_ms == 20
    assert release.data[3:11] == bytes(8)
    assert release.delay_after_ms == 10
    assert release_retry.data == release.data
    assert release_retry.delay_after_ms == 0
    assert sequence.cleanup_data == release.data


def test_preset_ids_are_unique():
    ids = [preset.id for preset in SPECIAL_KEY_PRESETS]
    assert ids == ["ctrl_alt_delete"]
    assert len(ids) == len(set(ids))


@pytest.mark.parametrize(
    "kwargs",
    [
        {"id": "", "label": "Bad", "modifier": 0, "keys": (0x04,)},
        {"id": "bad", "label": "", "modifier": 0, "keys": (0x04,)},
        {"id": "bad", "label": "Bad", "modifier": 0x100, "keys": (0x04,)},
        {"id": "bad", "label": "Bad", "modifier": 0, "keys": ()},
        {"id": "bad", "label": "Bad", "modifier": 0, "keys": (1, 2, 3, 4, 5, 6, 7)},
        {"id": "bad", "label": "Bad", "modifier": 0, "keys": (0x04, 0x04)},
        {"id": "bad", "label": "Bad", "modifier": 0, "keys": (0,)},
        {"id": "bad", "label": "Bad", "modifier": 0, "keys": (0x100,)},
    ],
)
def test_invalid_presets_are_rejected(kwargs):
    with pytest.raises(ValueError):
        SpecialKeyPreset(**kwargs)
