"""Unit tests for app/core/mouse_modes.py."""
import sys, os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))

from core.mouse_modes import (
    MouseMode,
    MouseModeConfig,
    normalize_mouse_mode,
    should_warp_cursor,
    should_hide_host_cursor,
    can_send_absolute,
)


# ---------------------------------------------------------------------------
# normalize_mouse_mode
# ---------------------------------------------------------------------------

def test_normalize_mouse_mode_recognises_known_values():
    assert normalize_mouse_mode("relative") is MouseMode.RELATIVE
    assert normalize_mouse_mode("hybrid") is MouseMode.HYBRID
    assert normalize_mouse_mode("absolute") is MouseMode.ABSOLUTE


def test_normalize_mouse_mode_falls_back_for_unknown():
    """Unknown strings fall back to RELATIVE (safest, current behaviour)."""
    assert normalize_mouse_mode("") is MouseMode.RELATIVE
    assert normalize_mouse_mode("ovr") is MouseMode.RELATIVE
    assert normalize_mouse_mode("OVR") is MouseMode.RELATIVE
    assert normalize_mouse_mode("Hybrid") is MouseMode.RELATIVE  # case sensitive
    assert normalize_mouse_mode(None) is MouseMode.RELATIVE


# ---------------------------------------------------------------------------
# should_warp_cursor
# ---------------------------------------------------------------------------

def test_warp_relative_true():
    cfg = MouseModeConfig(MouseMode.RELATIVE, firmware_abs_supported=False)
    assert should_warp_cursor(cfg) is True


def test_warp_hybrid_true():
    cfg = MouseModeConfig(MouseMode.HYBRID, firmware_abs_supported=True)
    assert should_warp_cursor(cfg) is True


def test_warp_absolute_false():
    cfg = MouseModeConfig(MouseMode.ABSOLUTE, firmware_abs_supported=True)
    assert should_warp_cursor(cfg) is False


# ---------------------------------------------------------------------------
# should_hide_host_cursor
# ---------------------------------------------------------------------------

def test_hide_cursor_relative_true():
    cfg = MouseModeConfig(MouseMode.RELATIVE, firmware_abs_supported=False)
    assert should_hide_host_cursor(cfg) is True


def test_hide_cursor_hybrid_true():
    cfg = MouseModeConfig(MouseMode.HYBRID, firmware_abs_supported=True)
    assert should_hide_host_cursor(cfg) is True


def test_hide_cursor_absolute_false():
    """In absolute mode the host cursor *is* the input source.

    Hiding it would be confusing (you wouldn't know where the next click
    will land).
    """
    cfg = MouseModeConfig(MouseMode.ABSOLUTE, firmware_abs_supported=True)
    assert should_hide_host_cursor(cfg) is False


# ---------------------------------------------------------------------------
# can_send_absolute (gated by firmware support)
# ---------------------------------------------------------------------------

def test_can_send_absolute_relative_false():
    cfg = MouseModeConfig(MouseMode.RELATIVE, firmware_abs_supported=True)
    assert can_send_absolute(cfg) is False


def test_can_send_absolute_hybrid_firmware_unsupported_false():
    cfg = MouseModeConfig(MouseMode.HYBRID, firmware_abs_supported=False)
    assert can_send_absolute(cfg) is False


def test_can_send_absolute_hybrid_firmware_supported_true():
    cfg = MouseModeConfig(MouseMode.HYBRID, firmware_abs_supported=True)
    assert can_send_absolute(cfg) is True


def test_can_send_absolute_absolute_firmware_unsupported_false():
    """Even absolute mode requires firmware support; otherwise we cannot
    send PKT_MOUSE_ABS at all.
    """
    cfg = MouseModeConfig(MouseMode.ABSOLUTE, firmware_abs_supported=False)
    assert can_send_absolute(cfg) is False


def test_can_send_absolute_absolute_firmware_supported_true():
    cfg = MouseModeConfig(MouseMode.ABSOLUTE, firmware_abs_supported=True)
    assert can_send_absolute(cfg) is True
