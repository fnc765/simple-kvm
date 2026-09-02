from app.core.hardware_loopback import (
    HID_ABS_MAX,
    MOUSE_MOVE_ABSOLUTE,
    RI_MOUSE_LEFT_BUTTON_DOWN,
    RI_MOUSE_LEFT_BUTTON_UP,
    ObservedMouseEvent,
    device_name_matches,
    find_click_order,
    hid_to_raw_coordinate,
    hid_to_screen_coordinate,
    position_matches,
)


DEVICE = r"\\?\HID#VID_046D&PID_C52B&MI_02#BP2"


def _event(
    timestamp_ns: int,
    *,
    flags: int = MOUSE_MOVE_ABSOLUTE,
    buttons: int = 0,
    x: int = 32_768,
    y: int = 32_768,
) -> ObservedMouseEvent:
    return ObservedMouseEvent(timestamp_ns, DEVICE, flags, buttons, x, y)


def test_coordinate_conversions_cover_endpoints() -> None:
    assert hid_to_raw_coordinate(0) == 0
    assert hid_to_raw_coordinate(HID_ABS_MAX) == 65_535
    assert hid_to_screen_coordinate(0, 1920) == 0
    assert hid_to_screen_coordinate(HID_ABS_MAX, 1920) == 1919


def test_coordinate_conversions_clamp_input() -> None:
    assert hid_to_raw_coordinate(-1) == 0
    assert hid_to_raw_coordinate(99_999) == 65_535


def test_screen_extent_must_be_positive() -> None:
    try:
        hid_to_screen_coordinate(1, 0)
    except ValueError as exc:
        assert "positive" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("ValueError not raised")


def test_device_name_match_requires_absolute_mouse_interface() -> None:
    assert device_name_matches(DEVICE)
    assert not device_name_matches(DEVICE.replace("MI_02", "MI_01"))
    assert not device_name_matches(DEVICE.replace("C52B", "0001"))
    assert device_name_matches(DEVICE, interface=None)


def test_position_match_requires_absolute_flag_and_tolerates_rounding() -> None:
    assert position_matches(_event(1), 16_384, 16_384)
    assert not position_matches(_event(1, flags=0), 16_384, 16_384)


def test_click_order_accepts_move_down_up_from_target_device() -> None:
    result = find_click_order(
        [
            _event(100),
            _event(110, buttons=RI_MOUSE_LEFT_BUTTON_DOWN),
            _event(120, buttons=RI_MOUSE_LEFT_BUTTON_UP),
        ],
        device_name=DEVICE,
        since_ns=100,
        hid_x=16_384,
        hid_y=16_384,
    )

    assert result.passed
    assert (result.move_index, result.down_index, result.up_index) == (0, 1, 2)


def test_click_order_rejects_down_without_a_preceding_move() -> None:
    result = find_click_order(
        [
            _event(100, buttons=RI_MOUSE_LEFT_BUTTON_DOWN),
            _event(110, buttons=RI_MOUSE_LEFT_BUTTON_UP),
        ],
        device_name=DEVICE,
        since_ns=100,
        hid_x=16_384,
        hid_y=16_384,
    )

    assert not result.passed
    assert "did not precede" in result.reason
