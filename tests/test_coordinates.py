"""Unit tests for app/core/coordinates.py.

These tests pin down the math used to translate a click/move inside the
``VideoWidget`` (logical pixel) into a HID absolute coordinate
(0..32767) for the target PC.  HiDPI / DPR is *not* applied here; Qt
already reports logical pixels in mouse events and the scaled pixmap
is laid out in the same coordinate system.
"""
import math
import sys, os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))

from core.coordinates import (
    HID_ABS_MAX,
    Size2D,
    compute_video_mapping,
    map_widget_point_to_hid,
)


SRC_1080P = Size2D(1920, 1080)


# ---------------------------------------------------------------------------
# Test 1: KeepAspectRatio with widget == source
# ---------------------------------------------------------------------------

def test_keep_widget_equals_source_corners():
    """When widget and source match, the corners map directly."""
    mapping = compute_video_mapping(SRC_1080P, Size2D(1920, 1080), "keep")

    # top-left -> (0, 0)
    p = map_widget_point_to_hid(0.0, 0.0, mapping)
    assert (p.hid_x, p.hid_y) == (0, 0)
    assert p.clamped is False

    # bottom-right pixel -> (32767, 32767)
    p = map_widget_point_to_hid(1919.0, 1079.0, mapping)
    assert (p.hid_x, p.hid_y) == (32767, 32767)
    assert p.clamped is False


def test_keep_widget_equals_source_center_is_near_middle():
    """The geometric centre of the widget should map to ~middle of HID range."""
    mapping = compute_video_mapping(SRC_1080P, Size2D(1920, 1080), "keep")

    # 959.5, 539.5 is the centre between pixels 0..1919 and 0..1079
    p = map_widget_point_to_hid(959.5, 539.5, mapping)
    assert 16380 <= p.hid_x <= 16388
    assert 16380 <= p.hid_y <= 16388


# ---------------------------------------------------------------------------
# Test 2: KeepAspectRatio with widget smaller than source (1280x720)
# ---------------------------------------------------------------------------

def test_keep_widget_smaller_no_letterbox():
    """When widget aspect matches source, no letterbox is added."""
    mapping = compute_video_mapping(SRC_1080P, Size2D(1280, 720), "keep")

    assert mapping.displayed_origin.x == 0.0
    assert mapping.displayed_origin.y == 0.0
    assert math.isclose(mapping.displayed_size.width, 1280.0)
    assert math.isclose(mapping.displayed_size.height, 720.0)

    # corners
    p = map_widget_point_to_hid(0.0, 0.0, mapping)
    assert (p.hid_x, p.hid_y) == (0, 0)

    p = map_widget_point_to_hid(1279.0, 719.0, mapping)
    assert (p.hid_x, p.hid_y) == (32767, 32767)


# ---------------------------------------------------------------------------
# Test 3: KeepAspectRatio with letterbox (square widget on 16:9 source)
# ---------------------------------------------------------------------------

def test_keep_widget_square_letterbox_clamps_to_video_edge():
    """A 1000x1000 widget on 16:9 source has top/bottom letterbox.

    Clicking in the letterbox must clamp the source y to 0 or 1079.
    """
    mapping = compute_video_mapping(SRC_1080P, Size2D(1000, 1000), "keep")

    # Aspect 16:9 -> scale = 1000/1920 = 0.5208..., disp_w=1000, disp_h=562.5
    assert math.isclose(mapping.displayed_size.width, 1000.0, abs_tol=1e-9)
    assert math.isclose(mapping.displayed_size.height, 562.5, abs_tol=1e-9)
    # vertical letterbox
    assert math.isclose(mapping.displayed_origin.x, 0.0, abs_tol=1e-9)
    assert math.isclose(mapping.displayed_origin.y, (1000.0 - 562.5) / 2.0, abs_tol=1e-9)

    # Top letterbox click -> clamp to source_y = 0
    p = map_widget_point_to_hid(500.0, 0.0, mapping)
    assert p.clamped is True
    assert p.hid_y == 0
    assert p.source_y == 0.0

    # Bottom letterbox click -> clamp to source_y = 1079
    p = map_widget_point_to_hid(500.0, 999.0, mapping)
    assert p.clamped is True
    assert p.hid_y == 32767
    assert math.isclose(p.source_y, 1079.0)

    # Inside displayed area -> not clamped
    p = map_widget_point_to_hid(500.0, 500.0, mapping)
    assert p.clamped is False
    # 500 is at the vertical middle of the displayed rect (218.75..781.25)
    # so the mapped y should be near 16384
    assert 16000 <= p.hid_y <= 16500


# ---------------------------------------------------------------------------
# Test 4: Stretch / fill (IgnoreAspectRatio) - linear mapping, no letterbox
# ---------------------------------------------------------------------------

def test_fill_stretches_to_widget_bounds():
    """In 'fill' mode the entire widget is mapped linearly to source."""
    mapping = compute_video_mapping(SRC_1080P, Size2D(1000, 1000), "fill")

    assert mapping.displayed_origin.x == 0.0
    assert mapping.displayed_origin.y == 0.0
    assert math.isclose(mapping.displayed_size.width, 1000.0)
    assert math.isclose(mapping.displayed_size.height, 1000.0)

    # centre
    p = map_widget_point_to_hid(500.0, 500.0, mapping)
    assert 16300 <= p.hid_x <= 16400
    assert 16300 <= p.hid_y <= 16400

    # corners
    p = map_widget_point_to_hid(0.0, 0.0, mapping)
    assert (p.hid_x, p.hid_y) == (0, 0)
    p = map_widget_point_to_hid(999.0, 999.0, mapping)
    assert (p.hid_x, p.hid_y) == (32767, 32767)


# ---------------------------------------------------------------------------
# Test 5: HiDPI / DPR is not applied in this layer
# ---------------------------------------------------------------------------

def test_no_dpi_scaling_in_coordinate_layer():
    """The coordinate layer operates on logical pixels only.

    DPR is handled at the Qt-pixmap layer; mouse events already arrive
    in logical coordinates.  We must not multiply by DPR here or
    coordinates will be off by a factor of 1.5 / 2.0 etc.
    """
    mapping = compute_video_mapping(SRC_1080P, Size2D(1920, 1080), "keep")

    # The function signature does not take a DPR argument; logical
    # pixels in == logical pixels out.  Sanity check that the formula
    # is linear: doubling the local x should approximately double hid_x.
    p1 = map_widget_point_to_hid(100.0, 100.0, mapping)
    p2 = map_widget_point_to_hid(200.0, 100.0, mapping)
    assert p2.hid_x > p1.hid_x
    # The ratio should be ~2x
    ratio = p2.hid_x / max(1, p1.hid_x)
    assert 1.9 < ratio < 2.1


# ---------------------------------------------------------------------------
# Test 6: Robustness
# ---------------------------------------------------------------------------

def test_zero_size_widget_does_not_crash():
    """If the widget has zero size (e.g. hidden), no exception is raised.

    The output is clamped to 0 (we treat it as "no information").
    """
    mapping = compute_video_mapping(SRC_1080P, Size2D(0, 0), "keep")
    p = map_widget_point_to_hid(0.0, 0.0, mapping)
    assert (p.hid_x, p.hid_y) == (0, 0)


def test_hid_abs_max_constant_is_32767():
    assert HID_ABS_MAX == 32767
