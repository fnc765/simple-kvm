"""Decode the actual BP2 relative HID descriptor, including its bit offsets."""

from pathlib import Path
import re

import pytest

from tools.audio_test.audit_firmware import audit_hid_report_lengths


FIRMWARE = Path(__file__).resolve().parents[1] / "firmware" / "bluepill2"


def _c_array(filename, symbol):
    source = (FIRMWARE / filename).read_text(encoding="utf-8")
    initializer = source.split(f"{symbol}[", 1)[1]
    initializer = initializer.split("{", 1)[1].split("};", 1)[0]
    initializer = re.sub(r"/\*.*?\*/", "", initializer, flags=re.DOTALL)
    return bytes(int(value, 16) for value in re.findall(r"0x[0-9a-fA-F]+", initializer))


def _descriptor():
    return _c_array("usbd_hid_composite_patch.c", "HID_MOUSE_ReportDesc")


def _input_fields(descriptor):
    """Expand HID short items into (page, usage, bit offset, size, flags)."""
    page = size = count = offset = 0
    usages = []
    usage_min = None
    fields = []
    pos = 0
    while pos < len(descriptor):
        prefix = descriptor[pos]
        length = (0, 1, 2, 4)[prefix & 3]
        value = int.from_bytes(descriptor[pos + 1:pos + 1 + length], "little")
        pos += 1 + length
        kind, tag = (prefix >> 2) & 3, prefix >> 4
        if kind == 1:
            if tag == 0:
                page = value
            elif tag == 7:
                size = value
            elif tag == 9:
                count = value
        elif kind == 2:
            if tag == 0:
                usages.append(value)
            elif tag == 1:
                usage_min = value
            elif tag == 2:
                usages.extend(range(usage_min, value + 1))
        elif kind == 0:
            if tag == 8:  # Input
                for i in range(count):
                    usage = usages[min(i, len(usages) - 1)] if usages else None
                    fields.append((page, usage, offset, size, value))
                    offset += size
            usages = []
            usage_min = None
    return fields, offset


def test_relative_mouse_exposes_exactly_one_vertical_wheel():
    fields, _ = _input_fields(_descriptor())
    wheels = [field for field in fields if field[:2] == (1, 0x38) and not field[4] & 1]
    assert wheels == [(1, 0x38, 24, 8, 0x06)]


def test_relative_mouse_keeps_five_byte_wire_format_with_reserved_last_byte():
    fields, bits = _input_fields(_descriptor())
    assert bits == 40
    assert [(p, u, o, s) for p, u, o, s, f in fields if not f & 1] == [
        (9, 1, 0, 1), (9, 2, 1, 1), (9, 3, 2, 1),
        (1, 0x30, 8, 8), (1, 0x31, 16, 8), (1, 0x38, 24, 8),
    ]
    assert fields[-1][2:4] == (32, 8)
    assert fields[-1][4] & 1  # reserved horizontal byte is constant padding


def test_relative_mouse_descriptor_length_matches_usb_advertisement():
    header = (FIRMWARE / "usbd_hid_composite_patch.h").read_text(encoding="utf-8")
    size = re.search(r"#define\s+HID_MOUSE_REPORT_DESC_SIZE\s+(\d+)U", header)
    assert len(_descriptor()) == int(size[1])


def test_audio_config_advertises_the_complete_relative_mouse_descriptor():
    config = _c_array(
        "usbd_hid_audio_composite_patch.c", "simple_kvm_bp2_audio_config_descriptor",
    )
    offset = 0
    interface = None
    lengths = {}
    while offset < len(config):
        length, kind = config[offset:offset + 2]
        assert length >= 2
        if kind == 4:  # interface descriptor
            interface = config[offset + 2]
        elif kind == 0x21:  # HID descriptor
            lengths[interface] = int.from_bytes(config[offset + 7:offset + 9], "little")
        offset += length
    assert lengths[1] == len(_descriptor())


def test_elf_audit_rejects_an_advertised_hid_length_mismatch():
    config = _c_array(
        "usbd_hid_audio_composite_patch.c", "simple_kvm_bp2_audio_config_descriptor",
    )
    table = {
        name: (0, len(_c_array("usbd_hid_composite_patch.c", name)))
        for name in ("HID_MOUSE_ReportDesc", "HID_KEYBOARD_ReportDesc",
                     "HID_ABS_MOUSE_ReportDesc")
    }
    audit_hid_report_lengths(config, table)
    table["HID_MOUSE_ReportDesc"] = (0, len(_descriptor()) + 1)
    with pytest.raises(AssertionError, match="HID_MOUSE_ReportDesc"):
        audit_hid_report_lengths(config, table)
