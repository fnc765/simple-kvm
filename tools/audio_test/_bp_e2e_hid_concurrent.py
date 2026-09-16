"""Run the audio probe while injecting BP2 HID reports on the same CDC handle.

The production CDC link is opened exclusively on Windows, so the normal HID
loopback verifier cannot open COM11 while the audio probe owns it.  This
diagnostic harness keeps one serial handle, injects absolute-mouse packets from
a worker, and records the resulting Raw Input events while the audio probe is
running.
"""

from __future__ import annotations

import contextlib
import io
import os
import sys
import threading
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.hid_desktop import attach_to_input_desktop as _attach_input_desktop  # noqa: E402
_desktop_attach_error = None
try:
    _attach_input_desktop()
except Exception as exc:
    _desktop_attach_error = exc

from app.core.protocol import build_mouse_abs_report

import tools.audio_test._bp_e2e_probe as audio
import tools.hardware_loopback as hid
from tools.bp2_identity import (  # noqa: E402
    BP2_AUDIO_PID,
    BP2_AUDIO_VID,
    bp2_audio_pnp_preflight,
)
from tools.verification_policy import (  # noqa: E402
    VerificationPolicyError,
    preflight,
)


def main() -> int:
    os.environ.setdefault("BP_E2E_EXCLUSIVE", "1")
    os.environ.setdefault("BP_E2E_RUN_SECONDS", "20")
    os.environ.setdefault("BP_E2E_RENDER_MIX", "0")
    os.environ.setdefault("BP_E2E_CAPTURE_MIX", "0")
    os.environ.setdefault("BP_E2E_RAW", "0")

    try:
        verification_plan = preflight(
            "audio + HID smoke",
            float(os.environ["BP_E2E_RUN_SECONDS"]),
        )
    except (KeyError, ValueError, VerificationPolicyError) as exc:
        print(
            "AUDIO_HID_SIMULTANEOUS_FAIL: verification policy: "
            f"{exc}",
            flush=True,
        )
        return 2

    hid._configure_win32()
    if _desktop_attach_error is not None:
        print(
            "AUDIO_HID_SIMULTANEOUS_SAFETY_FAIL: "
            f"input desktop unavailable: {_desktop_attach_error}",
            flush=True,
        )
        return 3
    app = hid.QApplication.instance() or hid.QApplication(sys.argv[:1])
    monitor = hid.RawMouseMonitor()
    try:
        monitor.start()
        original_cursor = hid.get_cursor_position()
    except Exception as exc:
        print(f"AUDIO_HID_SIMULTANEOUS_SAFETY_FAIL: {exc}", flush=True)
        monitor.close()
        return 3

    raw_mice = hid.enumerate_raw_mice()
    identity = bp2_audio_pnp_preflight(raw_mice)
    print("BP2_AUDIO_PNP_PREFLIGHT", identity, flush=True)
    if not identity["ok"]:
        print(
            f"AUDIO_HID_SIMULTANEOUS_FAIL: BP2 audio identity preflight: "
            f"{identity['reason']}",
            flush=True,
        )
        monitor.close()
        return 2

    target_candidates = [
        name
        for name in raw_mice
        if hid.device_name_matches(name, vid=BP2_AUDIO_VID, pid=BP2_AUDIO_PID,
                                   interface=hid.BP2_MOUSE_INTERFACE)
    ]
    if not target_candidates:
        print("AUDIO_HID_SIMULTANEOUS_FAIL: BP2 absolute HID not enumerated",
              flush=True)
        monitor.close()
        return 2

    stop = threading.Event()
    injection_enabled = threading.Event()
    injection_enabled.set()
    safety_lost = threading.Event()
    original_serial = audio.serial.Serial
    original_sleep = audio.time.sleep
    serial_proxy = None

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
            stop.set()
            return self._real.close()

        def __getattr__(self, name):
            return getattr(self._real, name)

    def open_serial(*args, **kwargs):
        nonlocal serial_proxy
        if not monitor.safety_ok():
            raise RuntimeError(
                f"AUDIO_HID_SIMULTANEOUS_SAFETY_FAIL before injection: "
                f"{monitor.safety_failure}"
            )
        real = original_serial(*args, **kwargs)
        serial_proxy = SharedSerial(real)

        def injector() -> None:
            try:
                original_sleep(1.0)
                points = [
                    (8192, 8192),
                    (24576, 8192),
                    (24576, 24576),
                    (8192, 24576),
                    (16384, 16384),
                ]
                for x, y in points:
                    if (
                        stop.is_set()
                        or not injection_enabled.is_set()
                        or not monitor.foreground_safe()
                    ):
                        injection_enabled.clear()
                        safety_lost.set()
                        stop.set()
                        return
                    serial_proxy.write(build_mouse_abs_report(0, x, y))
                    serial_proxy.flush()
                    original_sleep(0.08)
                if (
                    stop.is_set()
                    or not injection_enabled.is_set()
                    or not monitor.foreground_safe()
                ):
                    injection_enabled.clear()
                    safety_lost.set()
                    stop.set()
                    return
                serial_proxy.write(build_mouse_abs_report(1, 20316, 20643))
                serial_proxy.flush()
                original_sleep(0.12)
                serial_proxy.write(build_mouse_abs_report(0, 20316, 20643))
                serial_proxy.flush()
            except Exception as exc:
                print(f"HID_INJECT_EXCEPTION: {exc}", flush=True)

        threading.Thread(target=injector, name="hid-injector", daemon=True).start()
        return serial_proxy

    def pump_sleep(seconds: float) -> None:
        app.processEvents()
        if not monitor.safety_ok():
            injection_enabled.clear()
            safety_lost.set()
            stop.set()
        original_sleep(seconds)
        app.processEvents()

    audio.serial.Serial = open_serial
    audio.time.sleep = pump_sleep
    output = io.StringIO()
    try:
        with contextlib.redirect_stdout(output):
            audio.main()
    except Exception as exc:
        output.write(f"AUDIO_MAIN_EXCEPTION: {exc}\n")
    finally:
        stop.set()
        audio.serial.Serial = original_serial
        audio.time.sleep = original_sleep
        app.processEvents()

    text = output.getvalue()
    print(text, end="", flush=True)
    events = [
        event
        for event in monitor.events
        if hid.device_name_matches(event.device_name, vid=BP2_AUDIO_VID,
                                   pid=BP2_AUDIO_PID,
                                   interface=hid.BP2_MOUSE_INTERFACE)
    ]
    absolute = [event for event in events
                if event.us_flags & hid.MOUSE_MOVE_ABSOLUTE]
    button = [event for event in events
              if event.button_flags & (hid.RI_MOUSE_LEFT_BUTTON_DOWN |
                                       hid.RI_MOUSE_LEFT_BUTTON_UP)]
    audio_pass = "AUDIO_SINGLE_HOST_PASS" in text
    concurrent_pass = audio_pass and len(absolute) >= 5 and len(button) >= 2
    concurrent_pass = concurrent_pass and not safety_lost.is_set()
    print("AUDIO_HID_SIMULTANEOUS_METRICS", {
        "audio_pass_marker": audio_pass,
        "verification_stage": verification_plan.stage,
        "verification_duration_s": verification_plan.planned_seconds,
        "target_candidates": target_candidates,
        "absolute_events": len(absolute),
        "button_events": len(button),
        "total_target_events": len(events),
        "safety_surface_ok": not safety_lost.is_set() and monitor.safety_ok(),
        "safety_failure": monitor.safety_failure,
    }, flush=True)
    print(
        "AUDIO_HID_SIMULTANEOUS_PASS" if concurrent_pass
        else "AUDIO_HID_SIMULTANEOUS_FAIL",
        flush=True,
    )

    try:
        hid.user32.SetCursorPos(original_cursor.x, original_cursor.y)
    except Exception:
        pass
    monitor.close()
    return 0 if concurrent_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
