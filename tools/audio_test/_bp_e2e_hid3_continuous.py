"""One-PC audio, three-HID stress, and continuous non-zero waveform probe.

The BP1 CDC port is exclusive on Windows, so audio and HID traffic are
injected through one locked serial handle.  Raw Input is observed for all
three BP2 HID interfaces while the normal audio probe runs.  Set
``BP_E2E_RUN_SECONDS`` to the desired duration (the release check uses 3600).
Mouse reports are sent only while the full-screen foreground input shield is
confirmed; if the shield cannot be shown or loses focus, injection stops or
the run fails closed.
"""

from __future__ import annotations

import contextlib
import ctypes
import io
import os
import sys
import threading
import time
from ctypes import wintypes
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Attach before importing Qt: importing the Qt platform integration can create
# thread-owned desktop objects, after which SetThreadDesktop is forbidden.
from tools.hid_desktop import attach_to_input_desktop as _attach_input_desktop  # noqa: E402
_desktop_attach_error = None
try:
    _attach_input_desktop()
except Exception as exc:  # keep the executable fail-closed in headless sessions
    _desktop_attach_error = exc

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QLabel, QVBoxLayout  # noqa: E402

from app.core.protocol import (  # noqa: E402
    build_keyboard_report,
    build_mouse_abs_report,
    build_mouse_report,
)
import tools.audio_test._bp_e2e_probe as audio  # noqa: E402
import tools.hardware_loopback as hid  # noqa: E402
from tools.bp2_identity import (  # noqa: E402
    BP2_AUDIO_PID,
    BP2_AUDIO_VID,
    bp2_audio_pnp_preflight,
)


BP2_VID = BP2_AUDIO_VID
BP2_PID = BP2_AUDIO_PID
RIDEV_NOHOTKEYS = 0x00000200
RIDEV_REMOVE = 0x00000001
RIM_TYPEKEYBOARD = 1


class RAWKEYBOARD(ctypes.Structure):
    _fields_ = [
        ("MakeCode", wintypes.USHORT),
        ("Flags", wintypes.USHORT),
        ("Reserved", wintypes.USHORT),
        ("VKey", wintypes.USHORT),
        ("Message", wintypes.UINT),
        ("ExtraInformation", wintypes.ULONG),
    ]


class CombinedRawMonitor(hid.RawMouseMonitor):
    """Record bounded Raw Input evidence for BP2 mouse and keyboard HID."""

    def __init__(self) -> None:
        super().__init__()
        # Mouse reports move the Windows cursor. Keep the stress run behind a
        # visible, foreground-only safety surface so a lost/hidden test window
        # can never turn reports into clicks in an unrelated application.
        self.setWindowTitle("Simple KVM HID stress (input shield)")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setStyleSheet(
            "QWidget { background-color: #1b1f27; color: #f7f7f7; }"
            "QLabel { color: #f7f7f7; font-size: 28px; }"
        )
        label = QLabel(
            "SIMPLE KVM HID STRESS\n\n"
            "この画面が表示されている間だけ試験入力を送信します。\n"
            "画面が隠れた場合は自動停止します。"
        )
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout = QVBoxLayout(self)
        layout.addWidget(label)
        self.mouse_counts = {"relative": 0, "absolute": 0}
        self.mouse_button_counts = {"relative": 0, "absolute": 0}
        self.keyboard_counts = {"make": 0, "break": 0}
        self.keyboard_events: list[dict[str, object]] = []

    @staticmethod
    def _interface(name: str) -> str | None:
        upper = name.upper()
        if not hid.device_name_matches(
            name, vid=BP2_VID, pid=BP2_PID, interface=None
        ):
            return None
        if "&MI_01#" in upper:
            return "relative"
        if "&MI_02#" in upper:
            return "absolute"
        return None

    @staticmethod
    def _is_keyboard(name: str) -> bool:
        return hid.device_name_matches(
            name, vid=BP2_VID, pid=BP2_PID, interface=0
        )

    def start(self) -> None:
        super().start()
        # RawMouseMonitor.start() has already verified the shield before any
        # registration; add the keyboard usage only after that gate succeeds.
        registration = hid.RAWINPUTDEVICE(
            0x01,
            0x06,
            hid.RIDEV_INPUTSINK | RIDEV_NOHOTKEYS,
            wintypes.HWND(int(self.winId())),
        )
        assert hid.user32 is not None
        if not hid.user32.RegisterRawInputDevices(
            ctypes.byref(registration), 1, ctypes.sizeof(registration)
        ):
            raise ctypes.WinError(ctypes.get_last_error())

    def closeEvent(self, event):  # noqa: N802, ANN001
        # Explicitly unregister both usage registrations before destroying the
        # target window. This prevents a stale Raw Input target from outliving
        # an aborted test run.
        if hid.user32 is not None:
            for usage in (0x02, 0x06):
                registration = hid.RAWINPUTDEVICE(
                    0x01,
                    usage,
                    RIDEV_REMOVE,
                    wintypes.HWND(0),
                )
                hid.user32.RegisterRawInputDevices(
                    ctypes.byref(registration), 1, ctypes.sizeof(registration)
                )
        self._surface_ready = False
        super().closeEvent(event)

    def nativeEvent(self, event_type, message):  # noqa: N802, ANN001, ANN201
        msg = hid.MSG.from_address(int(message))
        if msg.message != hid.WM_INPUT:
            return False, 0
        assert hid.user32 is not None
        byte_count = wintypes.UINT(0)
        result = hid.user32.GetRawInputData(
            wintypes.HANDLE(msg.lParam),
            hid.RID_INPUT,
            None,
            ctypes.byref(byte_count),
            ctypes.sizeof(hid.RAWINPUTHEADER),
        )
        if result == hid.UINT_ERROR or not byte_count.value:
            return False, 0
        buffer = ctypes.create_string_buffer(byte_count.value)
        result = hid.user32.GetRawInputData(
            wintypes.HANDLE(msg.lParam),
            hid.RID_INPUT,
            buffer,
            ctypes.byref(byte_count),
            ctypes.sizeof(hid.RAWINPUTHEADER),
        )
        if result == hid.UINT_ERROR:
            return False, 0
        header = hid.RAWINPUTHEADER.from_buffer_copy(buffer)
        if header.dwType == hid.RIM_TYPEMOUSE:
            before = len(self.events)
            result = super().nativeEvent(event_type, message)
            for event in self.events[before:]:
                interface = self._interface(event.device_name)
                if interface is None:
                    continue
                self.mouse_counts[interface] += 1
                if event.button_flags:
                    self.mouse_button_counts[interface] += 1
            if len(self.events) > 128:
                del self.events[:-128]
            return result
        if header.dwType != RIM_TYPEKEYBOARD:
            return False, 0
        keyboard = RAWKEYBOARD.from_buffer_copy(
            buffer, ctypes.sizeof(hid.RAWINPUTHEADER)
        )
        name = hid._device_name(header.hDevice)
        if not self._is_keyboard(name):
            return False, 0
        is_break = bool(keyboard.Flags & 0x01)
        self.keyboard_counts["break" if is_break else "make"] += 1
        self.keyboard_events.append(
            {
                "device_name": name,
                "make_code": int(keyboard.MakeCode),
                "flags": int(keyboard.Flags),
                "vkey": int(keyboard.VKey),
                "is_break": is_break,
            }
        )
        if len(self.keyboard_events) > 128:
            del self.keyboard_events[:-128]
        return False, 0


class SharedSerial:
    def __init__(self, real):
        self._real = real
        self._lock = threading.Lock()

    def write(self, data):
        with self._lock:
            return self._real.write(data)

    def flush(self):
        with self._lock:
            return self._real.flush()

    def close(self):
        return self._real.close()

    def __getattr__(self, name):
        return getattr(self._real, name)


def main() -> int:
    os.environ.setdefault("BP_E2E_EXCLUSIVE", "1")
    os.environ.setdefault("BP_E2E_RUN_SECONDS", "3600")
    os.environ.setdefault("BP_E2E_RENDER_MIX", "0")
    os.environ.setdefault("BP_E2E_CAPTURE_MIX", "0")
    os.environ.setdefault("BP_E2E_RAW", "0")
    os.environ["BP_E2E_CONTINUOUS_NONZERO"] = "1"

    hid._configure_win32()
    if _desktop_attach_error is not None:
        print(
            f"HID3_SAFETY_FAIL: input desktop unavailable: {_desktop_attach_error}",
            flush=True,
        )
        return 3
    app = hid.QApplication.instance() or hid.QApplication(sys.argv[:1])
    monitor = CombinedRawMonitor()
    try:
        monitor.start()
        # Cursor restoration is part of the safety contract. If Windows does
        # not allow us to read the current cursor in this desktop/session, do
        # not send any input that we could not safely restore.
        original_cursor = hid.get_cursor_position()
    except OSError as exc:
        print(f"HID3_SAFETY_FAIL: cursor position unavailable: {exc}", flush=True)
        monitor.close()
        return 3
    except Exception as exc:
        print(f"HID3_SAFETY_FAIL: {exc}", flush=True)
        monitor.close()
        return 3

    raw_mice = hid.enumerate_raw_mice()
    identity = bp2_audio_pnp_preflight(raw_mice)
    print("BP2_AUDIO_PNP_PREFLIGHT", identity, flush=True)
    if not identity["ok"]:
        print(
            f"HID3_CONTINUOUS_FAIL: BP2 audio identity preflight: "
            f"{identity['reason']}",
            flush=True,
        )
        monitor.close()
        return 2

    target_mice = [
        name
        for name in raw_mice
        if hid.device_name_matches(name, vid=BP2_VID, pid=BP2_PID, interface=1)
        or hid.device_name_matches(name, vid=BP2_VID, pid=BP2_PID, interface=2)
    ]
    if not target_mice:
        print("HID3_CONTINUOUS_FAIL: BP2 mouse interfaces not enumerated", flush=True)
        monitor.close()
        return 2

    stop = threading.Event()
    injection_enabled = threading.Event()
    injection_enabled.set()
    safety_lost = threading.Event()
    original_serial = audio.serial.Serial
    original_sleep = audio.time.sleep
    original_monotonic = audio.time.monotonic
    serial_proxy: SharedSerial | None = None

    def open_serial(*args, **kwargs):
        nonlocal serial_proxy
        if not monitor.safety_ok():
            raise RuntimeError(
                f"HID3_SAFETY_FAIL before injection: {monitor.safety_failure}"
            )
        serial_proxy = SharedSerial(original_serial(*args, **kwargs))

        def injector() -> None:
            try:
                # New threads need their own desktop association before they
                # call foreground checks from the fail-closed injector loop.
                hid.attach_to_input_desktop()
                original_sleep(1.0)
                index = 0
                # Keep the stress rate explicit and reproducible.  Four base
                # reports per cycle (plus an occasional relative-button pair)
                # are sent through the same BP1 CDC stream as the audio probe.
                # The default is 50 cycles/s; short runs can lower this while
                # diagnosing host/firmware scheduling limits.
                hid_hz = max(
                    1.0, float(os.environ.get("BP_E2E_HID_HZ", "50"))
                )
                cycle_period = 1.0 / hid_hz
                next_cycle = original_monotonic()
                deadline = original_monotonic() + float(
                    os.environ.get("BP_E2E_RUN_SECONDS", "3600")
                )
                while (
                    not stop.is_set()
                    and injection_enabled.is_set()
                    and original_monotonic() < deadline
                ):
                    dx = 2 if index % 2 == 0 else -2
                    dy = -1 if index % 3 == 0 else 1
                    x = 4096 + (index * 257) % 24576
                    y = 4096 + (index * 149) % 24576
                    packets = [
                        build_keyboard_report(0, [0x04]),
                        build_mouse_report(0, dx, dy),
                        build_mouse_abs_report(0, x, y),
                        build_keyboard_report(0, []),
                    ]
                    if index % 20 == 0:
                        packets.extend(
                            (
                                build_mouse_report(1, 0, 0),
                                build_mouse_report(0, 0, 0),
                            )
                    )
                    for packet in packets:
                        if (
                            stop.is_set()
                            or not injection_enabled.is_set()
                            or not monitor.foreground_safe()
                        ):
                            injection_enabled.clear()
                            safety_lost.set()
                            stop.set()
                            return
                        assert serial_proxy is not None
                        serial_proxy.write(packet)
                        serial_proxy.flush()
                    index += 1
                    next_cycle += cycle_period
                    delay = next_cycle - original_monotonic()
                    if delay > 0.0:
                        original_sleep(delay)
                    else:
                        # Do not accumulate an unbounded backlog if the USB
                        # stack briefly stalls; resume at the next cycle.
                        next_cycle = original_monotonic()
            except Exception as exc:
                print(f"HID3_INJECT_EXCEPTION: {exc}", flush=True)

        threading.Thread(target=injector, name="hid3-injector", daemon=True).start()
        return serial_proxy

    pump_last = [0.0]

    def pump_sleep(seconds: float) -> None:
        now = original_monotonic()
        if now - pump_last[0] >= 0.005:
            app.processEvents()
            if not monitor.safety_ok():
                injection_enabled.clear()
                safety_lost.set()
                stop.set()
            pump_last[0] = now
        original_sleep(seconds)

    audio.serial.Serial = open_serial
    audio.time.sleep = pump_sleep
    captured_output = io.StringIO()

    class Tee:
        def write(self, value: str) -> int:
            captured_output.write(value)
            return sys.__stdout__.write(value)

        def flush(self) -> None:
            captured_output.flush()
            sys.__stdout__.flush()

    tee = Tee()
    try:
        with contextlib.redirect_stdout(tee):
            audio.main()
    except Exception as exc:
        print(f"AUDIO_MAIN_EXCEPTION: {exc}", flush=True)
    finally:
        stop.set()
        audio.serial.Serial = original_serial
        audio.time.sleep = original_sleep
        audio.time.monotonic = original_monotonic
        app.processEvents()

    text = captured_output.getvalue()
    audio_pass = "AUDIO_SINGLE_HOST_PASS" in text
    relative_events = monitor.mouse_counts["relative"]
    absolute_events = monitor.mouse_counts["absolute"]
    keyboard_make = monitor.keyboard_counts["make"]
    keyboard_break = monitor.keyboard_counts["break"]
    keyboard_balanced = keyboard_make == keyboard_break and keyboard_make > 0
    hid_pass = (
        relative_events >= 100
        and absolute_events >= 100
        and keyboard_make >= 100
        and keyboard_break >= 100
        and keyboard_balanced
    )
    safety_pass = not safety_lost.is_set() and monitor.safety_ok()
    duration = float(os.environ.get("BP_E2E_RUN_SECONDS", "3600"))
    continuous_pass = audio_pass and duration >= 3600.0 and hid_pass and safety_pass
    print("HID3_CONTINUOUS_METRICS", {
        "audio_pass_marker": audio_pass,
        "duration_s": duration,
        "target_mouse_devices": target_mice,
        "relative_mouse_events": relative_events,
        "absolute_mouse_events": absolute_events,
        "relative_button_events": monitor.mouse_button_counts["relative"],
        "keyboard_make_events": keyboard_make,
        "keyboard_break_events": keyboard_break,
        "keyboard_balanced": keyboard_balanced,
        "safety_surface_ok": safety_pass,
        "safety_failure": monitor.safety_failure,
        "last_keyboard_events": monitor.keyboard_events[-4:],
    }, flush=True)
    print(
        "HID3_CONTINUOUS_PASS" if continuous_pass else "HID3_CONTINUOUS_FAIL",
        flush=True,
    )

    if original_cursor is not None:
        try:
            hid.user32.SetCursorPos(original_cursor.x, original_cursor.y)
        except Exception:
            pass
    monitor.close()
    return 0 if continuous_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
