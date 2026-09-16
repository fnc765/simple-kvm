"""Safe, automated BP1-to-BP2 HID verification across two Windows PCs."""

from __future__ import annotations

import argparse
import json
import socket
import subprocess
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path

import serial

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.core.protocol import (  # noqa: E402
    build_keyboard_report,
    build_mouse_abs_report,
    build_mouse_report,
)
import tools.audio_test._bp_e2e_probe as audio  # noqa: E402
from tools.audio_test.controller import RemoteTarget, candidate_id  # noqa: E402
from tools.audio_test.two_pc_protocol import atomic_write_json, new_request, utc_now  # noqa: E402
from tools.verification_policy import preflight  # noqa: E402


def _default_output_dir() -> Path:
    stamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")
    return REPO_ROOT / "logs" / "two_pc" / f"{stamp}-hid"


def _free_local_port() -> int:
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])
    finally:
        probe.close()


def _recv_line(connection: socket.socket) -> str:
    data = bytearray()
    while b"\n" not in data:
        chunk = connection.recv(256)
        if not chunk:
            raise RuntimeError("target safety channel closed")
        data.extend(chunk)
        if len(data) > 1024:
            raise RuntimeError("target safety response exceeded 1024 bytes")
    return bytes(data.partition(b"\n")[0]).decode("ascii", errors="replace")


def _connect_safety(port: int, timeout: float = 5.0) -> socket.socket:
    deadline = time.monotonic() + timeout
    last_error: OSError | None = None
    while time.monotonic() < deadline:
        connection = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        connection.settimeout(1.0)
        try:
            connection.connect(("127.0.0.1", port))
            return connection
        except OSError as exc:
            last_error = exc
            connection.close()
            time.sleep(0.05)
    raise TimeoutError(f"SSH safety tunnel was not ready: {last_error}")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="100.114.238.82")
    parser.add_argument("--user", default="choco")
    parser.add_argument(
        "--identity",
        type=Path,
        default=Path.home() / ".ssh" / "id_ed25519_simple_kvm_fmvu34017",
    )
    parser.add_argument(
        "--target-root",
        default=r"C:\Users\choco\AppData\Local\SimpleKvmBench",
    )
    parser.add_argument("--stage", default="intermediate")
    parser.add_argument("--seconds", type=float, default=10.0)
    parser.add_argument("--cycles", type=int, default=5)
    parser.add_argument("--output-dir", type=Path)
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> tuple[int, dict[str, object]]:
    plan = preflight("two-PC BP1/BP2 HID", args.seconds, args.stage)
    if args.cycles <= 0 or args.cycles > 100:
        raise ValueError("cycles must be within 1..100")
    output_dir = (args.output_dir or _default_output_dir()).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    result_path = output_dir / "result.json"
    evidence: dict[str, object] = {
        "schema": 1,
        "started_at": utc_now(),
        "stage": plan.stage,
        "planned_seconds": plan.planned_seconds,
        "candidate_id": candidate_id(),
        "target": args.host,
        "result": "FAIL",
        "failures": [],
    }
    target = RemoteTarget(
        args.host,
        args.user,
        args.identity,
        root=args.target_root,
    )
    request = None
    port = None
    tunnel = None
    connection = None
    try:
        port_name = audio.resolve_bp1_serial_port()
        evidence["bp1_serial_port"] = port_name
        port = serial.Serial(port_name, 115200, timeout=0.001)
        port.reset_input_buffer()

        remote_safety_port = 47652
        local_safety_port = _free_local_port()
        safety_token = uuid.uuid4().hex
        request = new_request(
            "RUN_HID_CHECK",
            str(evidence["candidate_id"]),
            stage=plan.stage,
            planned_seconds=float(plan.planned_seconds or 0.0),
            options={
                "safety_port": remote_safety_port,
                "safety_token": safety_token,
            },
        )
        target.start_request(request)
        evidence["target_armed"] = target.wait_for_state(
            request.request_id, {"armed"}, timeout=20.0
        )

        tunnel = subprocess.Popen(
            [
                "ssh.exe",
                *target._connection_args(),
                "-N",
                "-L",
                f"127.0.0.1:{local_safety_port}:127.0.0.1:{remote_safety_port}",
                target.destination,
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        connection = _connect_safety(local_safety_port)

        sent_packets = 0
        for index in range(args.cycles):
            packets = (
                build_keyboard_report(0, [0x04]),
                build_keyboard_report(0, []),
                build_mouse_report(0, 2 if index % 2 == 0 else -2, 1),
                build_mouse_abs_report(
                    0,
                    4096 + (index * 4096) % 24576,
                    4096 + (index * 3072) % 24576,
                ),
                build_mouse_report(1, 0, 0),
                build_mouse_report(0, 0, 0),
            )
            for packet in packets:
                connection.sendall(f"{safety_token} CHECK\n".encode("ascii"))
                response = _recv_line(connection)
                if response != "SAFE":
                    raise RuntimeError(f"target denied HID injection: {response}")
                port.write(packet)
                port.flush()
                sent_packets += 1
                time.sleep(0.01)
        connection.sendall(f"{safety_token} DONE\n".encode("ascii"))
        if _recv_line(connection) != "ACK":
            raise RuntimeError("target did not acknowledge HID completion")
        evidence["sent_packets"] = sent_packets

        target_result = target.wait_result(
            request.request_id,
            timeout=(float(plan.planned_seconds or 0.0) + 20.0),
        )
        evidence["target_result"] = target_result
        failures: list[str] = []
        if target_result.get("status") != "pass":
            failures.append("target_hid_status")
        counts = target_result.get("payload", {}).get("counts", {})
        required = {
            "relative_mouse": counts.get("mouse", {}).get("relative", 0),
            "absolute_mouse": counts.get("mouse", {}).get("absolute", 0),
            "relative_buttons": counts.get("mouse_buttons", {}).get("relative", 0),
            "keyboard_make": counts.get("keyboard", {}).get("make", 0),
            "keyboard_break": counts.get("keyboard", {}).get("break", 0),
        }
        for name, value in required.items():
            if int(value) <= 0:
                failures.append(name)
        evidence["observed"] = required
        evidence["failures"] = failures
        evidence["result"] = "PASS" if not failures else "FAIL"
        return (0 if not failures else 2), evidence
    except Exception as exc:
        failures = evidence.get("failures")
        if isinstance(failures, list):
            failures.append(f"exception: {exc}")
        return 1, evidence
    finally:
        if connection is not None:
            connection.close()
        if tunnel is not None:
            tunnel.terminate()
            try:
                tunnel.wait(timeout=3.0)
            except subprocess.TimeoutExpired:
                tunnel.kill()
        if port is not None:
            try:
                port.write(build_keyboard_report(0, []))
                port.write(build_mouse_report(0, 0, 0))
                port.flush()
            finally:
                port.close()
        evidence["finished_at"] = utc_now()
        atomic_write_json(result_path, evidence)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        exit_code, evidence = run(args)
    except ValueError as exc:
        print(f"TWO_PC_HID_POLICY_FAIL: {exc}", flush=True)
        return 2
    print(json.dumps(evidence, ensure_ascii=True, indent=2, sort_keys=True), flush=True)
    print(f"TWO_PC_HID_{evidence['result']}", flush=True)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
