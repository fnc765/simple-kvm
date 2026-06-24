"""Unit tests for app/core/settings_values.py - mouse mode persistence."""
import sys, os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))

from core.mouse_modes import MouseMode
from core.settings_values import (
    DEFAULT_MOUSE_MODE,
    DEFAULT_FIRMWARE_ABS_SUPPORTED,
    MOUSE_MODE_KEY,
    FIRMWARE_ABS_KEY,
    read_mouse_mode_setting,
    read_firmware_abs_setting,
    write_mouse_mode_setting,
    write_firmware_abs_setting,
    parse_bool_setting,
)


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

def test_defaults_are_safe():
    """Defaults must preserve pre-existing behaviour."""
    assert DEFAULT_MOUSE_MODE is MouseMode.RELATIVE
    assert DEFAULT_FIRMWARE_ABS_SUPPORTED is False


def test_setting_keys_are_namespaced():
    """Setting keys live under input/ to match existing convention."""
    assert MOUSE_MODE_KEY.startswith("input/")
    assert FIRMWARE_ABS_KEY.startswith("input/")


# ---------------------------------------------------------------------------
# Mouse mode round-trip
# ---------------------------------------------------------------------------

class _DictSettings:
    """Minimal mapping-like object that mimics QSettings for the helpers."""

    def __init__(self, data=None):
        self._data = dict(data or {})

    def value(self, key, default=None, type=None):
        if key in self._data:
            v = self._data[key]
            if type is bool:
                return parse_bool_setting(v)
            return v
        return default

    def setValue(self, key, val):
        self._data[key] = val


def test_read_mouse_mode_default_when_missing():
    s = _DictSettings()
    assert read_mouse_mode_setting(s) is MouseMode.RELATIVE


def test_read_mouse_mode_valid_values():
    for v in ("relative", "hybrid", "absolute"):
        s = _DictSettings({MOUSE_MODE_KEY: v})
        assert read_mouse_mode_setting(s) is MouseMode(v)


def test_read_mouse_mode_invalid_falls_back():
    s = _DictSettings({MOUSE_MODE_KEY: "ovr"})
    assert read_mouse_mode_setting(s) is MouseMode.RELATIVE
    s = _DictSettings({MOUSE_MODE_KEY: ""})
    assert read_mouse_mode_setting(s) is MouseMode.RELATIVE
    s = _DictSettings({MOUSE_MODE_KEY: None})
    assert read_mouse_mode_setting(s) is MouseMode.RELATIVE


def test_write_and_read_mouse_mode_roundtrip():
    s = _DictSettings()
    write_mouse_mode_setting(s, MouseMode.HYBRID)
    assert s._data[MOUSE_MODE_KEY] == "hybrid"
    assert read_mouse_mode_setting(s) is MouseMode.HYBRID


# ---------------------------------------------------------------------------
# Firmware abs supported round-trip
# ---------------------------------------------------------------------------

def test_read_firmware_abs_default_when_missing():
    s = _DictSettings()
    assert read_firmware_abs_setting(s) is False


def test_read_firmware_abs_truthy_strings():
    for v in ("true", "True", "1", "yes", "on"):
        s = _DictSettings({FIRMWARE_ABS_KEY: v})
        assert read_firmware_abs_setting(s) is True, f"failed for {v!r}"


def test_read_firmware_abs_falsy_strings():
    for v in ("false", "False", "0", "no", "off", ""):
        s = _DictSettings({FIRMWARE_ABS_KEY: v})
        assert read_firmware_abs_setting(s) is False, f"failed for {v!r}"


def test_read_firmware_abs_native_bool():
    s = _DictSettings({FIRMWARE_ABS_KEY: True})
    assert read_firmware_abs_setting(s) is True
    s = _DictSettings({FIRMWARE_ABS_KEY: False})
    assert read_firmware_abs_setting(s) is False


def test_write_and_read_firmware_abs_roundtrip():
    s = _DictSettings()
    write_firmware_abs_setting(s, True)
    assert s._data[FIRMWARE_ABS_KEY] == "true"
    assert read_firmware_abs_setting(s) is True
    write_firmware_abs_setting(s, False)
    assert s._data[FIRMWARE_ABS_KEY] == "false"
    assert read_firmware_abs_setting(s) is False


# ---------------------------------------------------------------------------
# parse_bool_setting helper
# ---------------------------------------------------------------------------

def test_parse_bool_setting_strict():
    assert parse_bool_setting("true")  is True
    assert parse_bool_setting("True")  is True
    assert parse_bool_setting("TRUE")  is True
    assert parse_bool_setting("false") is False
    assert parse_bool_setting("False") is False
    assert parse_bool_setting("0")     is False
    assert parse_bool_setting("")      is False
    assert parse_bool_setting(None)    is False
    assert parse_bool_setting(True)    is True
    assert parse_bool_setting(False)   is False
