"""Build-profile invariants shared by legacy and audio firmware."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_bluepill2_legacy_force_includes_complete_endpoint_layout():
    platformio = (ROOT / "platformio.ini").read_text(encoding="utf-8")
    override = (
        ROOT / "firmware" / "bluepill2" / "usbd_ep_conf_override.h"
    ).read_text(encoding="utf-8")

    assert "-include firmware/bluepill2/usbd_ep_conf_override.h" in platformio
    assert "#define DEV_NUM_EP                     0x04U" in override
    assert "#define __USBD_EP_CONF_H" in override


def test_bluepill2_legacy_pma_regions_do_not_overlap():
    dev_num_ep = 4
    regions = [
        ("buffer_table", 0, 8 * dev_num_ep),
        ("ep0_out", 8 * dev_num_ep, 64),
        ("ep0_in", 8 * dev_num_ep + 64, 64),
        ("mouse_in", 8 * dev_num_ep + 128, 8),
        ("keyboard_in", 8 * dev_num_ep + 136, 8),
        ("abs_mouse_in", 8 * dev_num_ep + 144, 8),
    ]

    ordered = sorted(regions, key=lambda item: item[1])
    for previous, current in zip(ordered, ordered[1:]):
        assert previous[1] + previous[2] <= current[1]
    assert ordered[-1][1] + ordered[-1][2] == 184
    assert ordered[-1][1] + ordered[-1][2] <= 512


def test_usb_patches_do_not_depend_on_duplicate_symbol_link_order():
    platformio = (ROOT / "platformio.ini").read_text(encoding="utf-8")
    middleware = (
        ROOT / "tools" / "platformio" / "replace_stock_usb.py"
    ).read_text(encoding="utf-8")

    assert "--allow-multiple-definition" not in platformio
    assert "replace_stock_usb.py" in platformio
    assert "/usbdevice/src/usbd_ep_conf.c" in middleware
    assert "/usbdevice/src/usbd_desc.c" in middleware
    assert "/usbdevice/src/cdc/usbd_cdc.c" in middleware
    assert "/usbdevice/src/hid/usbd_hid_composite.c" in middleware
