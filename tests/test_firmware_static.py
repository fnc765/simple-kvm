"""Static tests for Phase 3 firmware (BP2) - absolute mouse support.

These tests read the firmware source files as text and assert that the
required symbols and configuration changes are present.  They do not
invoke the compiler; the actual build is verified by ``pio run``.

They exist to catch accidental regressions when refactoring the patch
files.
"""
import os
import re
import sys

REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
FIRMWARE_DIR = os.path.join(REPO_ROOT, "firmware", "bluepill2")
COMMON_DIR = os.path.join(REPO_ROOT, "firmware", "common")


def _read(rel_path: str) -> str:
    with open(os.path.join(FIRMWARE_DIR, rel_path), encoding="utf-8") as f:
        return f.read()


def _read_common(filename: str) -> str:
    with open(os.path.join(COMMON_DIR, filename), encoding="utf-8") as f:
        return f.read()


# ---------------------------------------------------------------------------
# Common packet parser
# ---------------------------------------------------------------------------

def test_packet_parser_h_declares_mouse_abs():
    """The packet parser header must declare PKT_MOUSE_ABS = 0x03."""
    text = _read_common("packet_parser.h")
    assert "PKT_MOUSE_ABS" in text
    assert re.search(r"#define\s+PKT_MOUSE_ABS\s+0x03u", text), (
        "PKT_MOUSE_ABS must be 0x03"
    )
    assert re.search(r"#define\s+PKT_LEN_MOUSE_ABS\s+5u", text), (
        "PKT_LEN_MOUSE_ABS must be 5"
    )


# ---------------------------------------------------------------------------
# hid_handler
# ---------------------------------------------------------------------------

def test_hid_handler_h_declares_absolute_mouse_struct():
    text = _read("hid_handler.h")
    assert "KVMMouseAbsReport" in text
    # buttons + x (uint16) + y (uint16) = 5 bytes
    assert re.search(
        r"typedef\s+struct\s+__attribute__\(\(packed\)\)\s*\{[^}]*uint8_t\s+buttons[^}]*uint16_t\s+x[^}]*uint16_t\s+y[^}]*\}\s*KVMMouseAbsReport",
        text,
        re.DOTALL,
    ), "KVMMouseAbsReport must contain buttons, x, y"


def test_hid_handler_h_declares_validator():
    text = _read("hid_handler.h")
    assert "validate_mouse_abs_report" in text


def test_hid_handler_cpp_implements_validator():
    text = _read("hid_handler.cpp")
    assert re.search(
        r"bool\s+validate_mouse_abs_report\s*\(\s*const\s+uint8_t\s*\*\s*payload",
        text,
    ), "validate_mouse_abs_report implementation missing"
    # Must check x and y are within range
    assert "HID_ABS_MAX_VALUE" in text or "32767" in text


# ---------------------------------------------------------------------------
# USB composite patch header
# ---------------------------------------------------------------------------

def test_patch_header_declares_3rd_interface():
    text = _read("usbd_hid_composite_patch.h")
    assert re.search(
        r"#define\s+HID_ABS_MOUSE_INTERFACE\s+0x02U",
        text,
    ), "HID_ABS_MOUSE_INTERFACE must be 0x02"


def test_patch_header_declares_endpoint_address():
    text = _read("usbd_hid_composite_patch.h")
    # Endpoint 0x83 is the next available IN endpoint after mouse (0x81)
    # and keyboard (0x82).
    assert re.search(
        r"#define\s+HID_ABS_MOUSE_EPIN_ADDR\s+0x83U",
        text,
    ), "HID_ABS_MOUSE_EPIN_ADDR must be 0x83"


def test_patch_header_increments_config_descriptor_size():
    """USB_COMPOSITE_HID_CONFIG_DESC_SIZ must accommodate the 3rd interface.

    2 interfaces (kbd + rel mouse) = 59 bytes
    3 interfaces (+ abs mouse)      = 84 bytes
    """
    text = _read("usbd_hid_composite_patch.h")
    assert re.search(
        r"#define\s+USB_COMPOSITE_HID_CONFIG_DESC_SIZ\s+84U",
        text,
    ), "USB_COMPOSITE_HID_CONFIG_DESC_SIZ must be 84U for 3 interfaces"


def test_patch_header_overrides_dev_num_ep():
    """DEV_NUM_EP must be overridden to 4 to include the absolute-mouse
    IN endpoint in the PMA layout."""
    text = _read("usbd_hid_composite_patch.h")
    assert re.search(
        r"#define\s+DEV_NUM_EP\s+0x04U",
        text,
    ), "DEV_NUM_EP must be overridden to 0x04U"


def test_patch_header_declares_report_desc_size():
    text = _read("usbd_hid_composite_patch.h")
    # The exact size depends on the descriptor (we counted 51 bytes
    # when the struct is 5 bytes: buttons + 2*uint16).  Just check
    # the macro exists and is in a sensible range.
    m = re.search(r"#define\s+HID_ABS_MOUSE_REPORT_DESC_SIZE\s+(\d+)U", text)
    assert m, "HID_ABS_MOUSE_REPORT_DESC_SIZE must be defined"
    size = int(m.group(1))
    assert 40 <= size <= 80, (
        f"HID_ABS_MOUSE_REPORT_DESC_SIZE={size} is outside sane range"
    )


# ---------------------------------------------------------------------------
# USB composite patch source
# ---------------------------------------------------------------------------

def test_patch_c_source_defines_state_field():
    """The struct USBD_HID_HandleTypeDef (declared in the patch header)
    must include an AbsMousestate field.  The .c file uses it in
    USBD_HID_DataIn to confirm the field exists."""
    text = _read("usbd_hid_composite_patch.c")
    assert re.search(
        r"\bAbsMousestate\s*=\s*HID_IDLE\b",
        text,
    ), "AbsMousestate must be reset to HID_IDLE somewhere (Init or DataIn)"


def test_patch_c_source_opens_third_endpoint():
    """Init() must open the 3rd endpoint via USBD_LL_OpenEP."""
    text = _read("usbd_hid_composite_patch.c")
    # Count USBD_LL_OpenEP calls in the Init function area (rough match)
    assert text.count("USBD_LL_OpenEP(pdev, HIDAMInEpAdd") >= 1, (
        "HIDAMInEpAdd must be opened in USBD_HID_Init"
    )


def test_patch_c_source_closes_third_endpoint():
    text = _read("usbd_hid_composite_patch.c")
    assert "USBD_LL_CloseEP(pdev, HIDAMInEpAdd)" in text


def test_patch_c_source_defines_send_report():
    text = _read("usbd_hid_composite_patch.c")
    assert "USBD_HID_ABS_MOUSE_SendReport" in text


def test_patch_c_source_defines_setup():
    text = _read("usbd_hid_composite_patch.c")
    assert "USBD_HID_ABS_MOUSE_Setup" in text


def test_patch_c_source_routes_setup_to_abs_mouse():
    """The composite setup handler must route wIndex 0x02 to
    USBD_HID_ABS_MOUSE_Setup."""
    text = _read("usbd_hid_composite_patch.c")
    # Find the COMPOSITE_HID_Setup function and check the routing.
    m = re.search(
        r"USBD_COMPOSITE_HID_Setup\s*\([^)]*\)\s*\{(.+?)\n\}",
        text,
        re.DOTALL,
    )
    assert m, "USBD_COMPOSITE_HID_Setup function not found"
    body = m.group(1)
    assert "HID_ABS_MOUSE_INTERFACE" in body
    assert "USBD_HID_ABS_MOUSE_Setup" in body


def test_patch_c_source_clears_abs_mousestate_on_datain():
    """USBD_HID_DataIn must clear AbsMousestate when the 3rd endpoint
    completes an IN transfer."""
    text = _read("usbd_hid_composite_patch.c")
    m = re.search(
        r"USBD_HID_DataIn\s*\([^)]*\)\s*\{(.+?)\n\}",
        text,
        re.DOTALL,
    )
    assert m, "USBD_HID_DataIn function not found"
    body = m.group(1)
    assert "HID_ABS_MOUSE_EPIN_ADDR" in body
    assert "AbsMousestate" in body


def test_three_config_descriptors_have_bnuminterfaces_3():
    """All three config descriptors (FS, HS, OtherSpeed) must declare
    bNumInterfaces = 0x03."""
    text = _read("usbd_hid_composite_patch.c")
    # Each config descriptor has the structure:
    #   0x09, USB_DESC_TYPE_CONFIGURATION, LOBYTE(...), HIBYTE(...),
    #   0x03, ...   <-- bNumInterfaces
    # The 0x03 byte follows the wTotalLength HIBYTE.  Simpler check:
    # look for "0x03, /\\* bNumInterfaces" or just count occurrences.
    count = text.count("/* bNumInterfaces: 3 interface")
    assert count >= 3, (
        f"Expected >=3 config descriptors with bNumInterfaces=3, "
        f"found {count}"
    )


def test_three_config_descriptors_have_absolute_mouse_block():
    """Each config descriptor must include the 3rd interface block
    (bInterfaceNumber = 0x02 for the absolute mouse)."""
    text = _read("usbd_hid_composite_patch.c")
    count = text.count("bInterfaceNumber: Absolute Mouse = 2")
    assert count >= 3, (
        f"Expected >=3 occurrences of the abs-mouse interface block, "
        f"found {count}"
    )


def test_absolute_mouse_report_descriptor_uses_absolute_xy():
    """The HID report descriptor must declare X / Y as absolute."""
    text = _read("usbd_hid_composite_patch.c")
    # Locate the descriptor array - the body starts after the first `{`
    # following the size spec and ends at the matching `};`.  Use a
    # non-greedy match.
    m = re.search(
        r"HID_ABS_MOUSE_ReportDesc\s*\[[^\]]+\][^{]*\{(.*?)\n\};",
        text,
        re.DOTALL,
    )
    assert m, "HID_ABS_MOUSE_ReportDesc array not found"
    body = m.group(1)
    # Usage X and Y must be present
    assert "Usage (X)" in body
    assert "Usage (Y)" in body
    # Logical Maximum must be 32767 (0x7FFF)
    assert "0xFF, 0x7F" in body, "Logical Maximum must be 32767"
    # Must be "Data,Var,Abs" (absolute) - 0x81, 0x02
    assert "0x81, 0x02" in body, "X/Y must be Data,Var,Abs"


# ---------------------------------------------------------------------------
# usbd_ep_conf override
# ---------------------------------------------------------------------------

def test_usbd_ep_conf_override_exists():
    path = os.path.join(FIRMWARE_DIR, "usbd_ep_conf.c")
    assert os.path.exists(path), "usbd_ep_conf.c override must exist"
    text = open(path, encoding="utf-8").read()
    assert "HID_ABS_MOUSE_EPIN_ADDR" in text
    assert "PMA_ABS_MOUSE_IN_ADDR" in text or "HID_ABS_MOUSE_EPIN_SIZE" in text


# ---------------------------------------------------------------------------
# usbd_desc_patch
# ---------------------------------------------------------------------------

def test_bcddevice_bumped_for_phase3():
    text = _read("usbd_desc_patch.c")
    # bcdDevice 24.01 is 0x01, 0x18 (low byte first, then high byte)
    assert re.search(r"0x01,\s*/\*\s*bcdDevice rel\. 24\.01", text), (
        "bcdDevice must be bumped to 24.01 (0x01, 0x18) for Phase 3"
    )


# ---------------------------------------------------------------------------
# main.cpp
# ---------------------------------------------------------------------------

def test_main_cpp_handles_pkt_mouse_abs():
    text = _read("main.cpp")
    assert "PKT_MOUSE_ABS" in text
    assert "hid_send_mouse_abs" in text
    # The switch case must exist
    assert re.search(
        r"case\s+PKT_MOUSE_ABS\s*:\s*hid_send_mouse_abs",
        text,
    ), "switch case for PKT_MOUSE_ABS must dispatch to hid_send_mouse_abs"
