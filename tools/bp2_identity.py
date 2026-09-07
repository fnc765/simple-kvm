"""Fail-closed identity and PnP preflight for the BP2 audio profile."""

from __future__ import annotations

import json
import os
import re
import subprocess
from collections.abc import Iterable, Mapping


BP2_AUDIO_VID = 0x046D
BP2_AUDIO_PID = 0xC52C
BP2_AUDIO_PRODUCT = "USB Receiver"
BP2_AUDIO_INTERFACE = 3
BP2_AUDIO_HID_INTERFACES = (0, 1, 2)
BP2_AUDIO_USB_TOKEN = f"VID_{BP2_AUDIO_VID:04X}&PID_{BP2_AUDIO_PID:04X}"

_INTERFACE_RE = re.compile(r"&MI_([0-9A-F]{2})(?:[#\\]|$)", re.IGNORECASE)
_PRODUCT_FIELDS = ("FriendlyName", "Name", "Description", "DeviceDesc")


def _value(record: Mapping[str, object], field: str) -> str:
    value = record.get(field, "")
    return "" if value is None else str(value)


def _instance_id(record: Mapping[str, object]) -> str:
    return _value(record, "InstanceId").upper()


def _record_text(record: Mapping[str, object]) -> str:
    return " ".join(_value(record, field) for field in _PRODUCT_FIELDS)


def _result(
    ok: bool,
    reason: str,
    target: list[Mapping[str, object]],
    interfaces: set[str],
    product_matches: list[str],
) -> dict[str, object]:
    return {
        "ok": ok,
        "reason": reason,
        "target_instance_ids": sorted(_instance_id(record) for record in target),
        "interfaces": sorted(interfaces),
        "product_matches": sorted(product_matches),
    }


def validate_bp2_audio_identity(
    records: Iterable[Mapping[str, object]],
    raw_device_names: Iterable[str] | None = None,
) -> dict[str, object]:
    """Validate VID/PID, product string, composite interfaces and Raw Input.

    ``records`` is intentionally passed in so native tests can exercise the
    fail-closed rules without requiring a Windows device.  Runtime callers use
    :func:`bp2_audio_pnp_preflight`, which obtains the records read-only from
    Windows PnP.
    """

    target = [
        record for record in records
        if _instance_id(record).find(BP2_AUDIO_USB_TOKEN) >= 0
    ]
    if not target:
        return _result(False, "no BP2 audio VID/PID record", [], set(), [])

    interfaces = {
        match.group(1).upper()
        for record in target
        for match in [_INTERFACE_RE.search(_instance_id(record))]
        if match is not None
    }
    expected_interfaces = {f"{index:02X}" for index in range(4)}
    missing = sorted(expected_interfaces - interfaces)
    if missing:
        return _result(
            False,
            f"missing BP2 audio interface(s): MI_{', MI_'.join(missing)}",
            target,
            interfaces,
            [],
        )

    parents = {
        _instance_id(record)
        for record in target
        if _instance_id(record).startswith("USB\\")
        and _INTERFACE_RE.search(_instance_id(record)) is None
    }
    if len(parents) != 1:
        return _result(
            False,
            f"expected one BP2 audio USB parent, found {len(parents)}",
            target,
            interfaces,
            [],
        )

    product_matches = [
        _instance_id(record)
        for record in target
        if BP2_AUDIO_PRODUCT.casefold() in _record_text(record).casefold()
    ]
    if not product_matches:
        return _result(
            False,
            f'product string "{BP2_AUDIO_PRODUCT}" not found for BP2 audio',
            target,
            interfaces,
            [],
        )

    if raw_device_names is not None:
        raw_interfaces = {
            match.group(1).upper()
            for name in raw_device_names
            if BP2_AUDIO_USB_TOKEN in str(name).upper()
            for match in [_INTERFACE_RE.search(str(name).upper())]
            if match is not None
        }
        expected_raw = {"01", "02"}
        missing_raw = sorted(expected_raw - raw_interfaces)
        if missing_raw:
            return _result(
                False,
                f"missing BP2 Raw Input mouse interface(s): "
                f"MI_{', MI_'.join(missing_raw)}",
                target,
                interfaces,
                product_matches,
            )

    return _result(True, "", target, interfaces, product_matches)


def query_bp2_audio_pnp() -> tuple[list[dict[str, object]], str | None]:
    """Read currently present BP2 audio PnP records without changing state."""

    if os.name != "nt":
        return [], "Windows PnP query is unavailable on this platform"
    script = (
        "$items = Get-PnpDevice -PresentOnly | "
        f"Where-Object {{ $_.InstanceId -match '{BP2_AUDIO_USB_TOKEN}' }} | "
        "Select-Object Status,Class,FriendlyName,InstanceId; "
        "if ($null -eq $items) { '[]' } "
        "else { @($items) | ConvertTo-Json -Compress }"
    )
    try:
        completed = subprocess.run(
            [
                "powershell.exe",
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                script,
            ],
            check=False,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=10,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except Exception as exc:
        return [], f"PnP query failed: {exc}"
    if completed.returncode != 0:
        detail = completed.stderr.strip() or "unknown PowerShell error"
        return [], f"PnP query failed: {detail}"
    try:
        raw = json.loads(completed.stdout.strip() or "[]")
    except json.JSONDecodeError as exc:
        return [], f"PnP query returned invalid JSON: {exc}"
    if not isinstance(raw, list):
        return [], "PnP query returned a non-list result"
    return [dict(item) for item in raw if isinstance(item, dict)], None


def bp2_audio_pnp_preflight(
    raw_device_names: Iterable[str] | None = None,
) -> dict[str, object]:
    """Return a machine-readable, fail-closed BP2 audio identity result."""

    records, error = query_bp2_audio_pnp()
    if error is not None:
        return {
            "ok": False,
            "reason": error,
            "target_instance_ids": [],
            "interfaces": [],
            "product_matches": [],
        }
    return validate_bp2_audio_identity(records, raw_device_names)
