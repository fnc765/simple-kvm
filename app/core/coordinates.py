"""
coordinates.py – Pure coordinate-mapping helpers for absolute mouse mode.

This module translates a click/move inside the ``VideoWidget`` (logical
pixel) into a HID absolute coordinate (0..32767) for the target PC.

Design notes
------------
* The host application uses Qt's logical coordinate system for both the
  widget rect and the mouse events.  HiDPI / device pixel ratio is
  already accounted for at the pixmap level (``_update_scaled_pixmap``
  in ``mainwindow.py``).  This layer does **not** apply DPR again or
  the result will be off by a factor of 1.5 / 2.0 etc.
* The math is kept free of Qt types so the module can be unit-tested
  directly with pytest.
"""

from __future__ import annotations

from dataclasses import dataclass

HID_ABS_MAX: int = 32767

# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Size2D:
    """Integer width / height pair (source image, widget rect, ...)."""

    width: int
    height: int


@dataclass(frozen=True)
class Point2D:
    """Float x / y pair (e.g. sub-pixel widget coordinates)."""

    x: float
    y: float


@dataclass(frozen=True)
class Size2Df:
    """Float width / height pair.

    Used for sub-pixel displayed rects (e.g. a 1000x562.5 letterbox
    inside a 1000x1000 widget).
    """

    width: float
    height: float


@dataclass(frozen=True)
class VideoMapping:
    """Result of :func:`compute_video_mapping`.

    ``displayed_origin`` is the top-left of the *visible* video rect
    inside the widget (in widget logical pixels).  ``displayed_size`` is
    its size.  In KeepAspectRatio mode the displayed rect may be smaller
    than the widget (letterboxed); in Stretch/Fill mode it covers the
    whole widget.
    """

    source_size: Size2D
    widget_size: Size2D
    displayed_origin: Point2D
    displayed_size: Size2Df
    aspect_mode: str  # "keep" or "fill"


@dataclass(frozen=True)
class MappedPoint:
    """Result of :func:`map_widget_point_to_hid`."""

    local_x: float
    local_y: float
    source_x: float
    source_y: float
    hid_x: int
    hid_y: int
    clamped: bool


# ---------------------------------------------------------------------------
# Mapping construction
# ---------------------------------------------------------------------------


def compute_video_mapping(
    source_size: Size2D,
    widget_size: Size2D,
    aspect_mode: str,
) -> VideoMapping:
    """Return the displayed video rect for a given widget + source size.

    Args:
        source_size:  Native capture size, e.g. 1920x1080.
        widget_size:  Current widget size in logical pixels.
        aspect_mode:  ``"keep"`` (KeepAspectRatio, with letterbox) or
                      ``"fill"`` (IgnoreAspectRatio, stretch to fill).
    """
    if aspect_mode not in ("keep", "fill"):
        raise ValueError(
            f"aspect_mode must be 'keep' or 'fill' (got {aspect_mode!r})"
        )

    sw = max(0, int(source_size.width))
    sh = max(0, int(source_size.height))
    ww = max(0, int(widget_size.width))
    wh = max(0, int(widget_size.height))

    if aspect_mode == "fill" or sw <= 0 or sh <= 0 or ww <= 0 or wh <= 0:
        # Stretch to fill: displayed rect == widget rect.
        return VideoMapping(
            source_size=Size2D(sw, sh),
            widget_size=Size2D(ww, wh),
            displayed_origin=Point2D(0.0, 0.0),
            displayed_size=Size2Df(float(ww), float(wh)),
            aspect_mode=aspect_mode,
        )

    # Keep aspect ratio.
    scale = min(ww / sw, wh / sh)
    disp_w = sw * scale
    disp_h = sh * scale
    x0 = (ww - disp_w) / 2.0
    y0 = (wh - disp_h) / 2.0
    return VideoMapping(
        source_size=Size2D(sw, sh),
        widget_size=Size2D(ww, wh),
        displayed_origin=Point2D(x0, y0),
        displayed_size=Size2Df(disp_w, disp_h),
        aspect_mode=aspect_mode,
    )


# ---------------------------------------------------------------------------
# Point mapping
# ---------------------------------------------------------------------------


def _clamp(value: float, lo: float, hi: float) -> float:
    if value < lo:
        return lo
    if value > hi:
        return hi
    return value


def map_widget_point_to_hid(
    local_x: float,
    local_y: float,
    mapping: VideoMapping,
    hid_max: int = HID_ABS_MAX,
) -> MappedPoint:
    """Map a widget-local point to HID absolute coordinates.

    Clicks outside the displayed video rect are clamped to the nearest
    edge (and ``clamped`` is set to ``True``).
    """
    src_w = mapping.source_size.width
    src_h = mapping.source_size.height

    # Degenerate cases.
    if (
        mapping.widget_size.width <= 0
        or mapping.widget_size.height <= 0
        or src_w <= 0
        or src_h <= 0
    ):
        return MappedPoint(
            local_x=float(local_x),
            local_y=float(local_y),
            source_x=0.0,
            source_y=0.0,
            hid_x=0,
            hid_y=0,
            clamped=True,
        )

    disp_x0 = mapping.displayed_origin.x
    disp_y0 = mapping.displayed_origin.y
    disp_w = mapping.displayed_size.width
    disp_h = mapping.displayed_size.height

    # Coords relative to the displayed rect's top-left.
    raw_vx = float(local_x) - disp_x0
    raw_vy = float(local_y) - disp_y0
    # Clamp the *position* to the displayed rect, treating the rect as
    # spanning [0, disp_w] (and the *last clickable position* as
    # disp_w - 1, which makes the formula match for both integer and
    # sub-pixel displayed rects).
    vx = _clamp(raw_vx, 0.0, max(0.0, disp_w - 1.0))
    vy = _clamp(raw_vy, 0.0, max(0.0, disp_h - 1.0))
    clamped = (raw_vx != vx) or (raw_vy != vy)

    # Map "clickable position" inside the displayed rect [0, disp_w-1]
    # linearly to source pixel index [0, src_w-1] and HID [0, hid_max].
    denom_x = max(1.0, disp_w - 1.0)
    denom_y = max(1.0, disp_h - 1.0)
    src_x = vx * (src_w - 1) / denom_x
    src_y = vy * (src_h - 1) / denom_y
    hid_x = int(round(vx * hid_max / denom_x))
    hid_y = int(round(vy * hid_max / denom_y))
    hid_x = max(0, min(hid_max, hid_x))
    hid_y = max(0, min(hid_max, hid_y))

    return MappedPoint(
        local_x=float(local_x),
        local_y=float(local_y),
        source_x=src_x,
        source_y=src_y,
        hid_x=hid_x,
        hid_y=hid_y,
        clamped=clamped,
    )
