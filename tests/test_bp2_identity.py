"""Hardware-free tests for the BP2 audio identity preflight."""

from tools.bp2_identity import (
    BP2_AUDIO_PID,
    BP2_AUDIO_PRODUCT,
    BP2_AUDIO_VID,
    validate_bp2_audio_identity,
)


def _records(*, product: str = BP2_AUDIO_PRODUCT, parents: int = 1):
    token = f"VID_{BP2_AUDIO_VID:04X}&PID_{BP2_AUDIO_PID:04X}"
    result = [
        {
            "InstanceId": f"USB\\{token}\\PARENT{index}",
            "FriendlyName": product,
        }
        for index in range(parents)
    ]
    result.extend(
        {
            "InstanceId": f"HID\\{token}&MI_{interface:02X}\\CHILD",
            "FriendlyName": "HID device",
        }
        for interface in range(3)
    )
    result.append(
        {
            "InstanceId": f"USB\\{token}&MI_03\\AUDIO",
            "FriendlyName": product,
        }
    )
    return result


def test_bp2_audio_identity_requires_product_and_all_interfaces():
    raw_mice = [
        r"\\?\HID#VID_046D&PID_C52C&MI_01#mouse",
        r"\\?\HID#VID_046D&PID_C52C&MI_02#absolute",
    ]
    result = validate_bp2_audio_identity(_records(), raw_mice)
    assert result["ok"] is True
    assert result["interfaces"] == ["00", "01", "02", "03"]
    assert result["product_matches"]


def test_bp2_audio_identity_rejects_legacy_pid_and_missing_product():
    legacy = [
        {
            "InstanceId": "USB\\VID_046D&PID_C52B\\LEGACY",
            "FriendlyName": "USB Receiver",
        }
    ]
    result = validate_bp2_audio_identity(legacy)
    assert result["ok"] is False
    assert "VID/PID" in result["reason"]

    result = validate_bp2_audio_identity(_records(product="USB Composite Device"))
    assert result["ok"] is False
    assert "product string" in result["reason"]


def test_bp2_audio_identity_rejects_ambiguous_usb_parents():
    result = validate_bp2_audio_identity(_records(parents=2))
    assert result["ok"] is False
    assert "one BP2 audio USB parent" in result["reason"]
