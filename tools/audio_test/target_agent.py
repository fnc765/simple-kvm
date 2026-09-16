"""Interactive-session target agent for deterministic two-PC verification."""

from __future__ import annotations

import argparse
import ctypes
import getpass
import json
import os
import platform
import socket
import sys
import time
import traceback
from contextlib import AbstractContextManager
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.audio_test.two_pc_protocol import (  # noqa: E402
    ProtocolError,
    TargetRequest,
    atomic_write_json,
    load_request,
    utc_now,
)


class SingleInstance(AbstractContextManager["SingleInstance"]):
    """Named Windows mutex that keeps scheduled-task invocations serialized."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.handle: int | None = None

    def __enter__(self) -> "SingleInstance":
        if os.name != "nt":
            return self
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateMutexW.restype = ctypes.c_void_p
        handle = kernel32.CreateMutexW(None, False, self.name)
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())
        self.handle = int(handle)
        if ctypes.get_last_error() == 183:  # ERROR_ALREADY_EXISTS
            kernel32.CloseHandle(ctypes.c_void_p(self.handle))
            self.handle = None
            raise RuntimeError("target agent is already running")
        return self

    def __exit__(self, exc_type, exc, tb) -> None:  # noqa: ANN001
        if self.handle is not None:
            ctypes.WinDLL("kernel32").CloseHandle(ctypes.c_void_p(self.handle))
            self.handle = None


def _session_id() -> int | None:
    if os.name != "nt":
        return None
    session = ctypes.c_uint32()
    ok = ctypes.WinDLL("kernel32").ProcessIdToSessionId(
        os.getpid(), ctypes.byref(session)
    )
    return int(session.value) if ok else None


def _machine_context() -> dict[str, object]:
    return {
        "hostname": socket.gethostname(),
        "username": getpass.getuser(),
        "platform": platform.platform(),
        "python": sys.version,
        "pid": os.getpid(),
        "session_id": _session_id(),
        "interactive_session": _session_id() not in (None, 0),
    }


def _load_manifest_candidate() -> str:
    manifest_path = REPO_ROOT / "manifest.json"
    raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    candidate_id = str(raw.get("candidate_id", "")).lower()
    if len(candidate_id) != 64 or any(
        character not in "0123456789abcdef" for character in candidate_id
    ):
        raise RuntimeError("deployed manifest has no valid candidate_id")
    return candidate_id


def _attach_input_desktop() -> None:
    from tools.hid_desktop import attach_to_input_desktop

    attach_to_input_desktop()


def _prepare() -> dict[str, object]:
    checks: list[dict[str, object]] = []
    try:
        _attach_input_desktop()
        checks.append({"name": "input_desktop", "ok": True})
    except Exception as exc:
        checks.append({"name": "input_desktop", "ok": False, "reason": str(exc)})

    raw_mice: list[str] = []
    try:
        import tools.hardware_loopback as hid

        hid._configure_win32()
        raw_mice = hid.enumerate_raw_mice()
        checks.append({"name": "raw_input_inventory", "ok": True, "count": len(raw_mice)})
    except Exception as exc:
        checks.append(
            {"name": "raw_input_inventory", "ok": False, "reason": str(exc)}
        )

    from tools.bp2_identity import bp2_audio_pnp_preflight

    identity = bp2_audio_pnp_preflight(raw_mice)
    checks.append({"name": "bp2_identity", **identity})

    capture_entries: list[tuple[str, str]] = []
    capture_id: str | None = None
    try:
        from tools.audio_test.windows_audio import (
            capture_inventory,
            resolve_bp2_capture_endpoint,
        )

        capture_entries = capture_inventory()
        capture_id = resolve_bp2_capture_endpoint(capture_entries)
        checks.append({"name": "bp2_capture_endpoint", "ok": True, "id": capture_id})
    except Exception as exc:
        checks.append(
            {"name": "bp2_capture_endpoint", "ok": False, "reason": str(exc)}
        )

    return {
        "ok": all(bool(check.get("ok")) for check in checks),
        "checks": checks,
        "raw_mice": raw_mice,
        "capture_endpoints": [
            {"id": endpoint_id, "friendly_name": friendly}
            for endpoint_id, friendly in capture_entries
        ],
        "capture_id": capture_id,
    }


def _start_capture(request: TargetRequest, root: Path) -> dict[str, object]:
    from tools.bp2_identity import bp2_audio_pnp_preflight
    from tools.audio_test.windows_audio import (
        capture_inventory,
        capture_pcm16,
        resolve_bp2_capture_endpoint,
    )

    identity = bp2_audio_pnp_preflight()
    if not identity["ok"]:
        raise RuntimeError(f"BP2 identity preflight failed: {identity['reason']}")
    endpoint_id = resolve_bp2_capture_endpoint(capture_inventory())
    run_dir = root / "runs" / request.request_id
    run_dir.mkdir(parents=True, exist_ok=True)
    stop_path = run_dir / "stop"

    go_path = run_dir / "go"

    def armed(metadata: dict[str, object]) -> None:
        atomic_write_json(
            root / "state.json",
            {
                "schema": 1,
                "request_id": request.request_id,
                "status": "armed",
                "updated_at": utc_now(),
                "capture": metadata,
            },
        )

    def started(metadata: dict[str, object]) -> None:
        atomic_write_json(
            root / "state.json",
            {
                "schema": 1,
                "request_id": request.request_id,
                "status": "capturing",
                "updated_at": utc_now(),
                "capture": metadata,
            },
        )

    pcm, metadata = capture_pcm16(
        endpoint_id,
        request.planned_seconds,
        exclusive=bool(request.options.get("exclusive", True)),
        on_armed=armed,
        wait_until=go_path.exists if request.options.get("wait_for_go", True) else None,
        arm_timeout_s=float(request.options.get("arm_timeout_seconds", 20.0)),
        on_started=started,
        should_stop=stop_path.exists,
    )
    capture_path = run_dir / "capture.pcm"
    capture_path.write_bytes(pcm)
    return {
        "ok": not bool(metadata.get("stopped_early")),
        "identity": identity,
        "capture": metadata,
        "capture_path": str(capture_path),
    }


def _run_hid_check(request: TargetRequest, root: Path) -> dict[str, object]:
    _attach_input_desktop()
    import tools.hardware_loopback as hid
    from tools.audio_test._bp_e2e_hid3_continuous import CombinedRawMonitor
    from tools.bp2_identity import bp2_audio_pnp_preflight

    hid._configure_win32()
    app = hid.QApplication.instance() or hid.QApplication(sys.argv[:1])
    monitor = CombinedRawMonitor()
    original_cursor = None
    server = None
    connection = None
    try:
        monitor.start()
        original_cursor = hid.get_cursor_position()
        raw_mice = hid.enumerate_raw_mice()
        identity = bp2_audio_pnp_preflight(raw_mice)
        if not identity["ok"]:
            raise RuntimeError(f"BP2 identity preflight failed: {identity['reason']}")
        safety_port = int(request.options.get("safety_port", 47652))
        safety_token = str(request.options.get("safety_token", ""))
        if not (1024 <= safety_port <= 65535):
            raise ProtocolError("RUN_HID_CHECK safety_port is outside 1024..65535")
        if len(safety_token) != 32 or any(
            character not in "0123456789abcdef" for character in safety_token
        ):
            raise ProtocolError("RUN_HID_CHECK safety_token must be 32 lowercase hex characters")
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind(("127.0.0.1", safety_port))
        server.listen(1)
        server.setblocking(False)
        atomic_write_json(
            root / "state.json",
            {
                "schema": 1,
                "request_id": request.request_id,
                "status": "armed",
                "updated_at": utc_now(),
                "safety_port": safety_port,
            },
        )
        deadline = time.monotonic() + request.planned_seconds
        received = bytearray()
        while time.monotonic() < deadline:
            app.processEvents()
            if not monitor.safety_ok():
                raise RuntimeError(
                    f"input shield safety lost: {monitor.safety_failure}"
                )
            if connection is None:
                try:
                    connection, _ = server.accept()
                    connection.setblocking(False)
                except BlockingIOError:
                    pass
            if connection is not None:
                try:
                    chunk = connection.recv(4096)
                    if chunk:
                        received.extend(chunk)
                    else:
                        connection.close()
                        connection = None
                        received.clear()
                except BlockingIOError:
                    pass
                while b"\n" in received and connection is not None:
                    raw_line, _, tail = received.partition(b"\n")
                    received[:] = tail
                    line = raw_line.decode("ascii", errors="replace")
                    if line == f"{safety_token} CHECK":
                        response = b"SAFE\n" if monitor.safety_ok() else b"STOP\n"
                    elif line == f"{safety_token} DONE":
                        response = b"ACK\n"
                    else:
                        response = b"DENY\n"
                    connection.sendall(response)
            time.sleep(0.005)
        counts = {
            "mouse": dict(monitor.mouse_counts),
            "mouse_buttons": dict(monitor.mouse_button_counts),
            "keyboard": dict(monitor.keyboard_counts),
        }
        required = [
            counts["mouse"]["relative"],
            counts["mouse"]["absolute"],
            counts["mouse_buttons"]["relative"],
            counts["keyboard"]["make"],
            counts["keyboard"]["break"],
        ]
        return {
            "ok": all(int(value) > 0 for value in required),
            "identity": identity,
            "counts": counts,
            "safety_ok": monitor.safety_ok(),
        }
    finally:
        if connection is not None:
            connection.close()
        if server is not None:
            server.close()
        monitor.close()
        app.processEvents()
        if original_cursor is not None and hid.user32 is not None:
            hid.user32.SetCursorPos(original_cursor.x, original_cursor.y)


def execute_request(request: TargetRequest, root: Path) -> dict[str, object]:
    if request.command == "PREPARE":
        return _prepare()
    if request.command == "START_CAPTURE":
        return _start_capture(request, root)
    if request.command == "RUN_HID_CHECK":
        return _run_hid_check(request, root)
    if request.command == "STOP_CAPTURE":
        target_id = str(request.options.get("target_request_id", ""))
        if not target_id:
            raise ProtocolError("STOP_CAPTURE requires options.target_request_id")
        stop_path = root / "runs" / target_id / "stop"
        stop_path.parent.mkdir(parents=True, exist_ok=True)
        stop_path.touch()
        return {"ok": True, "stopped_request_id": target_id}
    if request.command == "GET_RESULT":
        target_id = str(request.options.get("target_request_id", ""))
        result_path = root / "runs" / target_id / "result.json"
        if not result_path.is_file():
            return {"ok": False, "reason": "result_not_found", "target_request_id": target_id}
        return {"ok": True, "target_result": json.loads(result_path.read_text("utf-8"))}
    raise ProtocolError(f"unsupported command: {request.command}")


def run(root: Path, request_path: Path) -> int:
    if not request_path.is_file():
        return 0
    started_at = utc_now()
    request: TargetRequest | None = None
    try:
        request = load_request(request_path)
        last_path = root / "last_request_id.txt"
        if last_path.is_file() and last_path.read_text("ascii").strip() == request.request_id:
            return 0
        deployed_candidate = _load_manifest_candidate()
        if request.candidate_id != deployed_candidate:
            raise ProtocolError(
                "candidate mismatch: controller request does not match deployed agent"
            )
        atomic_write_json(
            root / "state.json",
            {
                "schema": 1,
                "request_id": request.request_id,
                "status": "running",
                "updated_at": utc_now(),
                "machine": _machine_context(),
            },
        )
        payload = execute_request(request, root)
        passed = bool(payload.get("ok"))
        result = {
            "schema": 1,
            "request_id": request.request_id,
            "command": request.command,
            "candidate_id": request.candidate_id,
            "status": "pass" if passed else "fail",
            "started_at": started_at,
            "finished_at": utc_now(),
            "machine": _machine_context(),
            "payload": payload,
        }
        exit_code = 0 if passed else 2
    except Exception as exc:
        result = {
            "schema": 1,
            "request_id": request.request_id if request else None,
            "command": request.command if request else None,
            "status": "error",
            "started_at": started_at,
            "finished_at": utc_now(),
            "machine": _machine_context(),
            "error": str(exc),
            "traceback": traceback.format_exc(),
        }
        exit_code = 1
    request_id = result.get("request_id")
    atomic_write_json(root / "result.json", result)
    if isinstance(request_id, str):
        run_result = root / "runs" / request_id / "result.json"
        atomic_write_json(run_result, result)
        (root / "last_request_id.txt").write_text(request_id + "\n", encoding="ascii")
    atomic_write_json(
        root / "state.json",
        {
            "schema": 1,
            "request_id": request_id,
            "status": result["status"],
            "updated_at": utc_now(),
        },
    )
    return exit_code


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--request", type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    root = args.root.resolve()
    request_path = (args.request or (root / "request.json")).resolve()
    root.mkdir(parents=True, exist_ok=True)
    try:
        with SingleInstance("Local\\SimpleKvmBenchTargetAgent"):
            return run(root, request_path)
    except RuntimeError as exc:
        print(f"TARGET_AGENT_BUSY: {exc}", file=sys.stderr, flush=True)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
