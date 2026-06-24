"""Unit tests for app/core/protocol.py - serial packet encoder.

These tests pin down the wire format of every packet type.  They also
guard the legacy ``build_mouse_report`` (relative) path so that adding
``PKT_MOUSE_ABS`` does not break existing behaviour.
"""
import sys, os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))

from core.protocol import (
    PKT_KEYBOARD,
    PKT_MOUSE,
    PKT_MOUSE_ABS,
    PKT_HEARTBEAT,
    PKT_START,
    HID_ABS_MAX,
    build_keyboard_report,
    build_mouse_report,
    build_mouse_abs_report,
    build_heartbeat,
    _crc8,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

def test_packet_type_constants():
    """Type numbers must be stable (firmware reads them)."""
    assert PKT_KEYBOARD  == 0x01
    assert PKT_MOUSE     == 0x02
    assert PKT_MOUSE_ABS == 0x03
    assert PKT_HEARTBEAT == 0xFF
    assert PKT_START     == 0xAA


def test_hid_abs_max_constant():
    assert HID_ABS_MAX == 32767


# ---------------------------------------------------------------------------
# Legacy: build_mouse_report (relative)
# ---------------------------------------------------------------------------

def test_build_mouse_report_basic():
    """A typical relative mouse packet is 9 bytes (1 start + 1 type + 1 len + 5 payload + 1 crc)."""
    pkt = build_mouse_report(0x01, 10, -20, 1, 0)
    assert len(pkt) == 9
    assert pkt[0] == PKT_START
    assert pkt[1] == PKT_MOUSE
    assert pkt[2] == 5           # payload length
    assert pkt[3] == 0x01        # buttons
    assert pkt[4] == 0x0A        # dx = 10 (signed int8)
    assert pkt[5] == 0xEC        # dy = -20 (two's complement)
    assert pkt[6] == 0x01        # wheel_v
    assert pkt[7] == 0x00        # wheel_h
    assert pkt[8] == _crc8(bytes([PKT_MOUSE, 5, 0x01, 0x0A, 0xEC, 0x01, 0x00]))


def test_build_mouse_report_clamps_to_int8():
    pkt = build_mouse_report(0, 200, -200, 200, -200)
    assert pkt[4] == 0x7F     # +127
    assert pkt[5] == 0x81     # -127 (two's complement)
    assert pkt[6] == 0x7F
    assert pkt[7] == 0x81


def test_build_mouse_report_masks_buttons():
    """Buttons should be masked to the low 3 bits."""
    pkt = build_mouse_report(0xFF, 0, 0)
    assert pkt[3] == 0x07


# ---------------------------------------------------------------------------
# New: build_mouse_abs_report
# ---------------------------------------------------------------------------

def test_build_mouse_abs_report_origin():
    """(0, 0) -> payload [0, 0, 0, 0, 0]."""
    pkt = build_mouse_abs_report(0, 0, 0)
    assert len(pkt) == 9
    assert pkt[0] == PKT_START
    assert pkt[1] == PKT_MOUSE_ABS
    assert pkt[2] == 5
    assert pkt[3:8] == bytes([0, 0, 0, 0, 0])
    assert pkt[8] == _crc8(bytes([PKT_MOUSE_ABS, 5, 0, 0, 0, 0, 0]))


def test_build_mouse_abs_report_max_coordinates():
    """(32767, 32767) -> payload [0, 0xFF, 0x7F, 0xFF, 0x7F]."""
    pkt = build_mouse_abs_report(0x00, 32767, 32767)
    assert pkt[3:8] == bytes([0, 0xFF, 0x7F, 0xFF, 0x7F])
    # CRC-8 known value
    assert pkt[8] == _crc8(bytes([PKT_MOUSE_ABS, 5, 0, 0xFF, 0x7F, 0xFF, 0x7F]))


def test_build_mouse_abs_report_little_endian():
    """x and y are little-endian uint16 (within HID_ABS_MAX)."""
    pkt = build_mouse_abs_report(0, 0x1234, 0x7BCD)
    # x_lo=0x34, x_hi=0x12, y_lo=0xCD, y_hi=0x7B
    assert pkt[3:8] == bytes([0, 0x34, 0x12, 0xCD, 0x7B])


def test_build_mouse_abs_report_clamps_negative_to_zero():
    pkt = build_mouse_abs_report(0, -1, -100)
    assert pkt[3:8] == bytes([0, 0, 0, 0, 0])


def test_build_mouse_abs_report_clamps_over_max():
    pkt = build_mouse_abs_report(0, 40000, 50000)
    assert pkt[3:8] == bytes([0, 0xFF, 0x7F, 0xFF, 0x7F])


def test_build_mouse_abs_report_masks_buttons():
    pkt = build_mouse_abs_report(0xFF, 0, 0)
    assert pkt[3] == 0x07


def test_build_mouse_abs_report_with_left_button():
    """Buttons are preserved in the high bits of byte 3."""
    pkt = build_mouse_abs_report(0x01, 100, 200)
    assert pkt[3] == 0x01
    # x = 100 = 0x64 -> lo=0x64, hi=0x00
    assert pkt[4] == 0x64
    assert pkt[5] == 0x00
    # y = 200 = 0xC8 -> lo=0xC8, hi=0x00
    assert pkt[6] == 0xC8
    assert pkt[7] == 0x00


# ---------------------------------------------------------------------------
# Other types should be unchanged
# ---------------------------------------------------------------------------

def test_keyboard_report_unchanged():
    """Adding PKT_MOUSE_ABS must not affect existing packets."""
    pkt = build_keyboard_report(0x02, [0x04, 0, 0, 0, 0, 0])
    assert pkt[0] == PKT_START
    assert pkt[1] == PKT_KEYBOARD
    assert pkt[2] == 8
    assert pkt[3] == 0x02
    assert pkt[4] == 0x00
    assert pkt[5] == 0x04


def test_heartbeat_unchanged():
    pkt = build_heartbeat()
    assert pkt[0] == PKT_START
    assert pkt[1] == PKT_HEARTBEAT
    assert pkt[2] == 0           # LEN
    assert len(pkt) == 4         # start + type + len + crc
