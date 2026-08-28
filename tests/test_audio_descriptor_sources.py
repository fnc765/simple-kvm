"""Source-level UAC1 and PMA specifications written before USB implementation."""

from __future__ import annotations

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]


def _c_byte_array(path: Path, symbol: str) -> bytes:
    text = path.read_text(encoding="utf-8")
    match = re.search(
        rf"\b{re.escape(symbol)}\s*\[[^\]]*\]\s*=\s*\{{(.*?)\}};",
        text,
        re.DOTALL,
    )
    assert match, f"descriptor array {symbol} missing in {path}"
    values = re.findall(r"\b0x([0-9A-Fa-f]{1,2})\b", match.group(1))
    return bytes(int(value, 16) for value in values)


def _walk(data: bytes):
    offset = 0
    while offset < len(data):
        length = data[offset]
        assert length >= 2, f"invalid descriptor length {length} at {offset}"
        end = offset + length
        assert end <= len(data), f"descriptor overruns buffer at {offset}"
        yield offset, data[offset:end]
        offset = end
    assert offset == len(data)


def _interfaces(data: bytes):
    return [descriptor for _, descriptor in _walk(data) if descriptor[1] == 0x04]


def _endpoints(data: bytes):
    return [descriptor for _, descriptor in _walk(data) if descriptor[1] == 0x05]


def _assert_uac_format(data: bytes, streaming_interface: int, endpoint: int):
    interfaces = _interfaces(data)
    assert any(
        desc[2:9] == bytes([streaming_interface, 1, 1, 1, 2, 0, 0])
        for desc in interfaces
    )
    formats = [
        desc
        for _, desc in _walk(data)
        if desc[1:4] == bytes([0x24, 0x02, 0x01]) and len(desc) == 11
    ]
    assert any(
        desc[4:8] == bytes([1, 2, 16, 1])
        and desc[8:11] == bytes([0x80, 0xBB, 0x00])
        for desc in formats
    )
    endpoints = _endpoints(data)
    assert any(
        desc[:9] == bytes([9, 5, endpoint, 0x0D, 96, 0, 1, 0, 0])
        for desc in endpoints
    )
    assert any(desc == bytes([7, 0x25, 1, 0, 0, 0, 0]) for _, desc in _walk(data))


def test_bp1_cdc_uac1_descriptor_contract():
    data = _c_byte_array(
        ROOT / "firmware" / "bluepill1" / "usbd_cdc_audio_patch.c",
        "simple_kvm_bp1_audio_config_descriptor",
    )
    assert len(data) == 174
    assert data[:9] == bytes([9, 2, 174, 0, 4, 1, 0, 0x80, 0x32])
    assert data[2] | data[3] << 8 == len(data)
    assert bytes([8, 0x0B, 0, 2, 2, 2, 1, 0]) in data
    assert bytes([8, 0x0B, 2, 2, 1, 0, 0, 0]) in data
    assert bytes([9, 0x24, 1, 0, 1, 30, 0, 1, 3]) in data
    _assert_uac_format(data, streaming_interface=3, endpoint=0x01)

    endpoints = _endpoints(data)
    assert any(desc[2:6] == bytes([0x02, 0x02, 64, 0]) for desc in endpoints)
    assert any(desc[2:6] == bytes([0x82, 0x02, 64, 0]) for desc in endpoints)
    assert any(desc[2:6] == bytes([0x83, 0x03, 8, 0]) for desc in endpoints)


def test_bp2_hid_uac1_descriptor_contract():
    data = _c_byte_array(
        ROOT / "firmware" / "bluepill2" / "usbd_hid_audio_composite_patch.c",
        "simple_kvm_bp2_audio_config_descriptor",
    )
    assert len(data) == 183
    assert data[:9] == bytes([9, 2, 183, 0, 5, 1, 0, 0x80, 0x31])
    assert data[2] | data[3] << 8 == len(data)
    assert bytes([8, 0x0B, 3, 2, 1, 0, 0, 0]) in data
    assert bytes([9, 0x24, 1, 0, 1, 30, 0, 1, 4]) in data
    _assert_uac_format(data, streaming_interface=4, endpoint=0x84)

    interfaces = _interfaces(data)
    assert [desc[2] for desc in interfaces[:3]] == [0, 1, 2]
    endpoints = _endpoints(data)
    for endpoint in (0x81, 0x82, 0x83):
        assert any(desc[2] == endpoint and desc[3] == 3 for desc in endpoints)


def test_audio_pma_budgets_are_exact_and_non_overlapping():
    layouts = {
        "bp1": [
            ("buffer_table", 0, 32),
            ("ep0_out", 32, 64),
            ("ep0_in", 96, 64),
            ("audio_out_0", 160, 96),
            ("audio_out_1", 256, 96),
            ("cdc_out", 352, 64),
            ("cdc_in", 416, 64),
            ("cdc_cmd", 480, 8),
        ],
        "bp2": [
            ("buffer_table", 0, 40),
            ("ep0_out", 40, 64),
            ("ep0_in", 104, 64),
            ("mouse_in", 168, 8),
            ("keyboard_in", 176, 8),
            ("abs_mouse_in", 184, 8),
            ("audio_in_0", 192, 96),
            ("audio_in_1", 288, 96),
        ],
    }
    expected = {"bp1": 488, "bp2": 384}
    for board, regions in layouts.items():
        for name, start, size in regions:
            assert start % 2 == 0, (board, name)
            assert size % 2 == 0, (board, name)
        ordered = sorted(regions, key=lambda item: item[1])
        for previous, current in zip(ordered, ordered[1:]):
            assert previous[1] + previous[2] <= current[1]
        used = max(start + size for _, start, size in regions)
        assert used == expected[board]
        assert used <= 512


def test_audio_profiles_keep_legacy_profiles_available():
    text = (ROOT / "platformio.ini").read_text(encoding="utf-8")
    for environment in (
        "bluepill1",
        "bluepill2",
        "bluepill1_legacy",
        "bluepill2_legacy",
        "bluepill1_audio",
        "bluepill2_audio",
    ):
        assert f"[env:{environment}]" in text
