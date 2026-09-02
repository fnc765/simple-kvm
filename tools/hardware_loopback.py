#!/usr/bin/env python3
"""Unattended BP1 -> UART -> BP2 -> USB HID loopback verification.

This Windows-only tool deliberately uses the production SerialComm queue and
identifies BP2 by its Raw Input device handle.  A blank full-screen window is
kept in front while the single test click is generated, so the click cannot
activate another application.
"""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import subprocess
import sys
import time
import traceback
from ctypes import wintypes
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Callable


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402
from serial.tools import list_ports  # noqa: E402

from app.core.absolute_mouse import (  # noqa: E402
    build_absolute_button_transition,
    build_absolute_click,
)
from app.core.hardware_loopback import (  # noqa: E402
    MOUSE_MOVE_ABSOLUTE,
    RI_MOUSE_LEFT_BUTTON_DOWN,
    RI_MOUSE_LEFT_BUTTON_UP,
    ObservedMouseEvent,
    device_name_matches,
    find_click_order,
    hid_to_screen_coordinate,
    position_matches,
)
from app.core.protocol import HID_ABS_MAX, build_mouse_abs_report  # noqa: E402
from app.core.serial_comm import SerialComm  # noqa: E402


BP1_VID = 0x0483
BP1_PID = 0x5740
BP2_VID = 0x046D
BP2_PID = 0xC52B
BP2_MOUSE_INTERFACE = 2

WM_INPUT = 0x00FF
RID_INPUT = 0x10000003
RIDI_DEVICENAME = 0x20000007
RIM_TYPEMOUSE = 0
RIDEV_INPUTSINK = 0x00000100
RIDEV_DEVNOTIFY = 0x00002000
SM_CXSCREEN = 0
SM_CYSCREEN = 1
VK_LBUTTON = 0x01
UINT_ERROR = 0xFFFFFFFF


class POINT(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


class MSG(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("message", wintypes.UINT),
        ("wParam", wintypes.WPARAM),
        ("lParam", wintypes.LPARAM),
        ("time", wintypes.DWORD),
        ("pt", POINT),
    ]


class RAWINPUTHEADER(ctypes.Structure):
    _fields_ = [
        ("dwType", wintypes.DWORD),
        ("dwSize", wintypes.DWORD),
        ("hDevice", wintypes.HANDLE),
        ("wParam", wintypes.WPARAM),
    ]


class _BUTTON_FIELDS(ctypes.Structure):
    _fields_ = [
        ("usButtonFlags", wintypes.USHORT),
        ("usButtonData", wintypes.USHORT),
    ]


class _BUTTON_UNION(ctypes.Union):
    _anonymous_ = ("fields",)
    _fields_ = [("ulButtons", wintypes.ULONG), ("fields", _BUTTON_FIELDS)]


class RAWMOUSE(ctypes.Structure):
    _anonymous_ = ("buttons",)
    _fields_ = [
        ("usFlags", wintypes.USHORT),
        ("buttons", _BUTTON_UNION),
        ("ulRawButtons", wintypes.ULONG),
        ("lLastX", wintypes.LONG),
        ("lLastY", wintypes.LONG),
        ("ulExtraInformation", wintypes.ULONG),
    ]


class RAWINPUTDEVICELIST(ctypes.Structure):
    _fields_ = [("hDevice", wintypes.HANDLE), ("dwType", wintypes.DWORD)]


class RAWINPUTDEVICE(ctypes.Structure):
    _fields_ = [
        ("usUsagePage", wintypes.USHORT),
        ("usUsage", wintypes.USHORT),
        ("dwFlags", wintypes.DWORD),
        ("hwndTarget", wintypes.HWND),
    ]


class VerificationFailure(RuntimeError):
    """Raised after a failed check has been recorded."""


user32 = ctypes.WinDLL("user32", use_last_error=True) if os.name == "nt" else None


def _configure_win32() -> None:
    assert user32 is not None
    user32.RegisterRawInputDevices.argtypes = [
        ctypes.POINTER(RAWINPUTDEVICE),
        wintypes.UINT,
        wintypes.UINT,
    ]
    user32.RegisterRawInputDevices.restype = wintypes.BOOL
    user32.GetRawInputData.argtypes = [
        wintypes.HANDLE,
        wintypes.UINT,
        wintypes.LPVOID,
        ctypes.POINTER(wintypes.UINT),
        wintypes.UINT,
    ]
    user32.GetRawInputData.restype = wintypes.UINT
    user32.GetRawInputDeviceInfoW.argtypes = [
        wintypes.HANDLE,
        wintypes.UINT,
        wintypes.LPVOID,
        ctypes.POINTER(wintypes.UINT),
    ]
    user32.GetRawInputDeviceInfoW.restype = wintypes.UINT
    user32.GetRawInputDeviceList.argtypes = [
        ctypes.POINTER(RAWINPUTDEVICELIST),
        ctypes.POINTER(wintypes.UINT),
        wintypes.UINT,
    ]
    user32.GetRawInputDeviceList.restype = wintypes.UINT
    user32.GetCursorPos.argtypes = [ctypes.POINTER(POINT)]
    user32.GetCursorPos.restype = wintypes.BOOL
    user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
    user32.SetCursorPos.restype = wintypes.BOOL
    user32.GetSystemMetrics.argtypes = [ctypes.c_int]
    user32.GetSystemMetrics.restype = ctypes.c_int
    user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
    user32.GetAsyncKeyState.restype = ctypes.c_short


def _device_name(handle: wintypes.HANDLE) -> str:
    assert user32 is not None
    char_count = wintypes.UINT(0)
    result = user32.GetRawInputDeviceInfoW(
        handle, RIDI_DEVICENAME, None, ctypes.byref(char_count)
    )
    if result == UINT_ERROR or not char_count.value:
        return ""
    buffer = ctypes.create_unicode_buffer(char_count.value + 1)
    capacity = wintypes.UINT(len(buffer))
    result = user32.GetRawInputDeviceInfoW(
        handle, RIDI_DEVICENAME, buffer, ctypes.byref(capacity)
    )
    return "" if result == UINT_ERROR else buffer.value


def enumerate_raw_mice() -> list[str]:
    """Return the Raw Input paths for all currently connected mice."""

    assert user32 is not None
    count = wintypes.UINT(0)
    entry_size = ctypes.sizeof(RAWINPUTDEVICELIST)
    result = user32.GetRawInputDeviceList(None, ctypes.byref(count), entry_size)
    if result == UINT_ERROR:
        raise ctypes.WinError(ctypes.get_last_error())
    if not count.value:
        return []
    entries = (RAWINPUTDEVICELIST * count.value)()
    result = user32.GetRawInputDeviceList(entries, ctypes.byref(count), entry_size)
    if result == UINT_ERROR:
        raise ctypes.WinError(ctypes.get_last_error())
    return [
        name
        for entry in entries[: count.value]
        if entry.dwType == RIM_TYPEMOUSE and (name := _device_name(entry.hDevice))
    ]


def pnp_problem_snapshot() -> dict[str, object]:
    """Capture inspectable PnP diagnostics without changing device state."""

    try:
        completed = subprocess.run(
            ["pnputil", "/enum-devices", "/problem"],
            check=False,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=10,
        )
    except Exception as exc:
        return {"error": str(exc)}
    return {
        "exit_code": completed.returncode,
        "output": completed.stdout,
        "stderr": completed.stderr,
    }


class RawMouseMonitor(QWidget):
    """Safe foreground surface and device-specific Raw Input recorder."""

    def __init__(self) -> None:
        super().__init__()
        self.events: list[ObservedMouseEvent] = []
        self._device_names: dict[int, str] = {}
        self.setWindowTitle("Simple KVM hardware loopback verification")
        self.setStyleSheet("background-color: #20242b;")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )

    def start(self) -> None:
        """Show the safe surface and register for background mouse reports."""

        self.showFullScreen()
        self.raise_()
        self.activateWindow()
        QApplication.processEvents()
        registration = RAWINPUTDEVICE(
            0x01,
            0x02,
            RIDEV_INPUTSINK | RIDEV_DEVNOTIFY,
            wintypes.HWND(int(self.winId())),
        )
        assert user32 is not None
        if not user32.RegisterRawInputDevices(
            ctypes.byref(registration), 1, ctypes.sizeof(RAWINPUTDEVICE)
        ):
            raise ctypes.WinError(ctypes.get_last_error())

    def nativeEvent(self, event_type, message):  # noqa: N802, ANN001, ANN201
        """Capture WM_INPUT for the exact originating mouse device."""

        msg = MSG.from_address(int(message))
        if msg.message != WM_INPUT:
            return False, 0
        assert user32 is not None
        byte_count = wintypes.UINT(0)
        result = user32.GetRawInputData(
            wintypes.HANDLE(msg.lParam),
            RID_INPUT,
            None,
            ctypes.byref(byte_count),
            ctypes.sizeof(RAWINPUTHEADER),
        )
        if result == UINT_ERROR or not byte_count.value:
            return False, 0
        buffer = ctypes.create_string_buffer(byte_count.value)
        result = user32.GetRawInputData(
            wintypes.HANDLE(msg.lParam),
            RID_INPUT,
            buffer,
            ctypes.byref(byte_count),
            ctypes.sizeof(RAWINPUTHEADER),
        )
        if result == UINT_ERROR:
            return False, 0
        header = RAWINPUTHEADER.from_buffer_copy(buffer)
        if header.dwType != RIM_TYPEMOUSE:
            return False, 0
        mouse = RAWMOUSE.from_buffer_copy(buffer, ctypes.sizeof(RAWINPUTHEADER))
        handle_value = int(ctypes.cast(header.hDevice, ctypes.c_void_p).value or 0)
        name = self._device_names.get(handle_value)
        if name is None:
            name = _device_name(header.hDevice)
            self._device_names[handle_value] = name
        self.events.append(
            ObservedMouseEvent(
                timestamp_ns=time.perf_counter_ns(),
                device_name=name,
                us_flags=int(mouse.usFlags),
                button_flags=int(mouse.usButtonFlags),
                raw_x=int(mouse.lLastX),
                raw_y=int(mouse.lLastY),
            )
        )
        return False, 0


def pump_until(
    predicate: Callable[[], object], timeout_s: float, *, interval_s: float = 0.005
):
    """Pump Qt messages until *predicate* returns a truthy value."""

    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        QApplication.processEvents()
        value = predicate()
        if value:
            return value
        time.sleep(interval_s)
    QApplication.processEvents()
    return predicate()


def get_cursor_position() -> POINT:
    point = POINT()
    assert user32 is not None
    if not user32.GetCursorPos(ctypes.byref(point)):
        raise ctypes.WinError(ctypes.get_last_error())
    return point


def pixel_to_hid(value: int, extent: int) -> int:
    if extent <= 1:
        return 0
    return round(max(0, min(extent - 1, value)) * HID_ABS_MAX / (extent - 1))


def find_bp1_port(requested: str | None) -> tuple[str, list[dict[str, object]]]:
    inventory = [
        {
            "device": port.device,
            "vid": port.vid,
            "pid": port.pid,
            "description": port.description,
            "hwid": port.hwid,
        }
        for port in list_ports.comports()
    ]
    if requested:
        matching = [item for item in inventory if item["device"].upper() == requested.upper()]
    else:
        matching = [
            item
            for item in inventory
            if item["vid"] == BP1_VID and item["pid"] == BP1_PID
        ]
    if len(matching) != 1:
        raise VerificationFailure(
            f"expected exactly one BP1 CDC port, found {len(matching)}"
        )
    return str(matching[0]["device"]), inventory


def _ratio_to_hid(ratio: float) -> int:
    return round(ratio * HID_ABS_MAX)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", help="BP1 CDC COM port; auto-detected by default")
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="evidence directory (default: logs/hardware_loopback/<timestamp>)",
    )
    parser.add_argument("--event-timeout", type=float, default=2.0)
    parser.add_argument("--pixel-tolerance", type=int, default=4)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    stamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")
    output_dir = args.output_dir or REPO_ROOT / "logs" / "hardware_loopback" / stamp
    output_dir.mkdir(parents=True, exist_ok=True)
    result_path = output_dir / "result.json"
    evidence: dict[str, object] = {
        "schema": 1,
        "started_at": datetime.now().astimezone().isoformat(),
        "checks": [],
        "result": "FAIL",
    }
    monitor: RawMouseMonitor | None = None
    serial_comm: SerialComm | None = None
    app: QApplication | None = None
    original_cursor: POINT | None = None
    screen_width = 0
    screen_height = 0
    exit_code = 1

    def check(marker: str, passed: bool, detail: object) -> None:
        checks = evidence["checks"]
        assert isinstance(checks, list)
        checks.append({"marker": marker, "passed": passed, "detail": detail})
        print(f"{marker}_{'PASS' if passed else 'FAIL'}: {detail}", flush=True)
        if not passed:
            raise VerificationFailure(f"{marker}: {detail}")

    try:
        if os.name != "nt":
            raise VerificationFailure("the hardware loopback verifier requires Windows")
        _configure_win32()
        assert user32 is not None
        screen_width = user32.GetSystemMetrics(SM_CXSCREEN)
        screen_height = user32.GetSystemMetrics(SM_CYSCREEN)
        original_cursor = get_cursor_position()
        evidence["primary_screen"] = {"width": screen_width, "height": screen_height}
        evidence["original_cursor"] = {
            "x": original_cursor.x,
            "y": original_cursor.y,
        }

        try:
            port, serial_inventory = find_bp1_port(args.port)
        except VerificationFailure as exc:
            evidence["serial_inventory"] = [
                {
                    "device": item.device,
                    "vid": item.vid,
                    "pid": item.pid,
                    "description": item.description,
                    "hwid": item.hwid,
                }
                for item in list_ports.comports()
            ]
            check("BP1_CDC_ENUM", False, str(exc))
            raise AssertionError("unreachable")
        evidence["serial_inventory"] = serial_inventory
        evidence["bp1_port"] = port
        check("BP1_CDC_ENUM", True, port)

        app = QApplication.instance() or QApplication(sys.argv[:1])
        monitor = RawMouseMonitor()
        monitor.start()
        raw_mice = enumerate_raw_mice()
        evidence["raw_mouse_inventory"] = raw_mice
        candidates = [
            name
            for name in raw_mice
            if device_name_matches(
                name,
                vid=BP2_VID,
                pid=BP2_PID,
                interface=BP2_MOUSE_INTERFACE,
            )
        ]
        if not candidates:
            evidence["pnp_problem_devices"] = pnp_problem_snapshot()
        check(
            "BP2_HID_ENUM",
            bool(candidates),
            {"candidate_count": len(candidates), "candidates": candidates},
        )

        connected_states: list[bool] = []
        serial_comm = SerialComm()
        serial_comm.connected.connect(connected_states.append)
        serial_comm.set_port(port)
        serial_comm.start()
        connected = pump_until(
            lambda: True if connected_states and connected_states[-1] else None,
            args.event_timeout,
        )
        check("BP1_CDC_OPEN", bool(connected), {"port": port, "states": connected_states})

        probe_x = _ratio_to_hid(0.43)
        probe_y = _ratio_to_hid(0.37)
        probe_start = time.perf_counter_ns()
        serial_comm.enqueue_mouse_motion(build_mouse_abs_report(0, probe_x, probe_y))

        def find_probe():
            return next(
                (
                    event
                    for event in monitor.events
                    if event.timestamp_ns >= probe_start
                    and event.device_name in candidates
                    and position_matches(event, probe_x, probe_y)
                ),
                None,
            )

        probe = pump_until(find_probe, args.event_timeout)
        check(
            "ABS_RAWINPUT",
            isinstance(probe, ObservedMouseEvent),
            asdict(probe) if isinstance(probe, ObservedMouseEvent) else "no matching absolute report",
        )
        assert isinstance(probe, ObservedMouseEvent)
        target_device = probe.device_name
        evidence["bp2_raw_device"] = target_device

        position_results: list[dict[str, object]] = []
        for x_ratio, y_ratio in (
            (0.20, 0.20),
            (0.80, 0.20),
            (0.50, 0.50),
            (0.20, 0.80),
            (0.80, 0.80),
        ):
            hid_x = _ratio_to_hid(x_ratio)
            hid_y = _ratio_to_hid(y_ratio)
            marker = time.perf_counter_ns()
            serial_comm.enqueue_mouse_motion(build_mouse_abs_report(0, hid_x, hid_y))
            observed = pump_until(
                lambda x=hid_x, y=hid_y, start=marker: next(
                    (
                        event
                        for event in monitor.events
                        if event.timestamp_ns >= start
                        and event.device_name == target_device
                        and position_matches(event, x, y)
                    ),
                    None,
                ),
                args.event_timeout,
            )
            expected_x = hid_to_screen_coordinate(hid_x, screen_width)
            expected_y = hid_to_screen_coordinate(hid_y, screen_height)
            cursor_ok = pump_until(
                lambda: (
                    point
                    if abs((point := get_cursor_position()).x - expected_x)
                    <= args.pixel_tolerance
                    and abs(point.y - expected_y) <= args.pixel_tolerance
                    else None
                ),
                args.event_timeout,
            )
            actual = get_cursor_position()
            position_results.append(
                {
                    "hid": [hid_x, hid_y],
                    "raw_event": asdict(observed)
                    if isinstance(observed, ObservedMouseEvent)
                    else None,
                    "expected_cursor": [expected_x, expected_y],
                    "actual_cursor": [actual.x, actual.y],
                    "passed": bool(observed and cursor_ok),
                }
            )
        check(
            "ABS_CURSOR_POSITION",
            all(bool(item["passed"]) for item in position_results),
            position_results,
        )

        click_x = _ratio_to_hid(0.62)
        click_y = _ratio_to_hid(0.63)
        click_start = time.perf_counter_ns()
        serial_comm.enqueue_mouse_transition(build_absolute_click(1, click_x, click_y))
        click_order = pump_until(
            lambda: (
                result
                if (
                    result := find_click_order(
                        monitor.events,
                        device_name=target_device,
                        since_ns=click_start,
                        hid_x=click_x,
                        hid_y=click_y,
                    )
                ).passed
                else None
            ),
            args.event_timeout,
        )
        check(
            "CLICK_ORDER",
            bool(click_order and click_order.passed),
            asdict(click_order)
            if click_order
            else "move/down/up subsequence not observed",
        )

        latest_x = _ratio_to_hid(0.74)
        latest_y = _ratio_to_hid(0.34)
        latest_start = time.perf_counter_ns()
        for index in range(200):
            ratio = 0.10 + (index / 199) * 0.80
            x = latest_x if index == 199 else _ratio_to_hid(ratio)
            y = latest_y if index == 199 else _ratio_to_hid(0.85 - ratio / 2)
            serial_comm.enqueue_mouse_motion(build_mouse_abs_report(0, x, y))
        final_event = pump_until(
            lambda: next(
                (
                    event
                    for event in monitor.events
                    if event.timestamp_ns >= latest_start
                    and event.device_name == target_device
                    and position_matches(event, latest_x, latest_y)
                ),
                None,
            ),
            args.event_timeout,
        )
        expected_latest_x = hid_to_screen_coordinate(latest_x, screen_width)
        expected_latest_y = hid_to_screen_coordinate(latest_y, screen_height)
        latest_cursor = pump_until(
            lambda: (
                point
                if abs((point := get_cursor_position()).x - expected_latest_x)
                <= args.pixel_tolerance
                and abs(point.y - expected_latest_y) <= args.pixel_tolerance
                else None
            ),
            args.event_timeout,
        )
        settle_start = (
            final_event.timestamp_ns
            if isinstance(final_event, ObservedMouseEvent)
            else time.perf_counter_ns()
        )
        pump_until(lambda: False, 0.35)
        later_off_target = [
            asdict(event)
            for event in monitor.events
            if event.timestamp_ns > settle_start
            and event.device_name == target_device
            and event.us_flags & MOUSE_MOVE_ABSOLUTE
            and not position_matches(event, latest_x, latest_y)
        ]
        check(
            "LATEST_WINS",
            bool(final_event and latest_cursor and not later_off_target),
            {
                "final_event": asdict(final_event) if final_event else None,
                "expected_cursor": [expected_latest_x, expected_latest_y],
                "actual_cursor": [
                    get_cursor_position().x,
                    get_cursor_position().y,
                ],
                "later_off_target": later_off_target,
            },
        )

        timeout_x = _ratio_to_hid(0.35)
        timeout_y = _ratio_to_hid(0.68)
        timeout_start = time.perf_counter_ns()
        serial_comm.enqueue_mouse_transition(
            build_absolute_button_transition(0, 1, timeout_x, timeout_y)
        )
        down_event = pump_until(
            lambda: next(
                (
                    event
                    for event in monitor.events
                    if event.timestamp_ns >= timeout_start
                    and event.device_name == target_device
                    and event.button_flags & RI_MOUSE_LEFT_BUTTON_DOWN
                ),
                None,
            ),
            args.event_timeout,
        )
        if not isinstance(down_event, ObservedMouseEvent):
            check("TIMEOUT_RELEASE", False, "left-down was not observed")
        assert isinstance(down_event, ObservedMouseEvent)
        up_event = pump_until(
            lambda: next(
                (
                    event
                    for event in monitor.events
                    if event.timestamp_ns > down_event.timestamp_ns
                    and event.device_name == target_device
                    and event.button_flags & RI_MOUSE_LEFT_BUTTON_UP
                ),
                None,
            ),
            4.2,
        )
        elapsed_ms = (
            (up_event.timestamp_ns - down_event.timestamp_ns) / 1_000_000
            if isinstance(up_event, ObservedMouseEvent)
            else None
        )
        button_is_up = not bool(user32.GetAsyncKeyState(VK_LBUTTON) & 0x8000)
        check(
            "TIMEOUT_RELEASE",
            bool(
                isinstance(up_event, ObservedMouseEvent)
                and elapsed_ms is not None
                and 2_000 <= elapsed_ms <= 3_800
                and button_is_up
            ),
            {
                "down": asdict(down_event),
                "up": asdict(up_event) if isinstance(up_event, ObservedMouseEvent) else None,
                "elapsed_ms": elapsed_ms,
                "button_is_up": button_is_up,
            },
        )

        evidence["result"] = "PASS"
        print("LOOPBACK_E2E_PASS", flush=True)
        exit_code = 0
    except Exception as exc:
        evidence["error"] = str(exc)
        evidence["traceback"] = traceback.format_exc()
        print(f"LOOPBACK_E2E_FAIL: {exc}", flush=True)
        exit_code = 2 if isinstance(exc, VerificationFailure) else 1
    finally:
        if serial_comm is not None:
            try:
                if original_cursor is not None and screen_width and screen_height:
                    cleanup_x = pixel_to_hid(original_cursor.x, screen_width)
                    cleanup_y = pixel_to_hid(original_cursor.y, screen_height)
                    serial_comm.enqueue_mouse_transition(
                        build_mouse_abs_report(0, cleanup_x, cleanup_y)
                    )
                    pump_until(lambda: False, 0.15)
                serial_comm.stop()
            except Exception as cleanup_exc:
                evidence["serial_cleanup_error"] = str(cleanup_exc)
        if user32 is not None:
            try:
                if original_cursor is not None:
                    user32.SetCursorPos(original_cursor.x, original_cursor.y)
            except Exception as cleanup_exc:
                evidence["cursor_cleanup_error"] = str(cleanup_exc)
        if monitor is not None:
            monitor.close()
        if app is not None:
            app.processEvents()
        if monitor is not None:
            evidence["bp2_events"] = [
                asdict(event)
                for event in monitor.events
                if device_name_matches(
                    event.device_name,
                    vid=BP2_VID,
                    pid=BP2_PID,
                    interface=BP2_MOUSE_INTERFACE,
                )
            ]
        evidence["finished_at"] = datetime.now().astimezone().isoformat()
        result_path.write_text(
            json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"EVIDENCE_PATH={result_path}", flush=True)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
