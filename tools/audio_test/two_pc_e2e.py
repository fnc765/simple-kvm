"""Automated BP1-controller to BP2-target two-PC audio verification."""

from __future__ import annotations

import argparse
import json
import math
import os
import struct
import sys
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import serial

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import tools.audio_test._bp_e2e_probe as audio  # noqa: E402
from tools.audio_test.controller import RemoteTarget, candidate_id  # noqa: E402
from tools.audio_test.two_pc_protocol import atomic_write_json, new_request, utc_now  # noqa: E402
from tools.audio_test.waveform import analyze_capture, make_signal, numeric_failures  # noqa: E402
from tools.audio_test.windows_audio import render_pcm16  # noqa: E402
from tools.verification_policy import (  # noqa: E402
    FINAL_INTEGRATION_STAGE,
    VerificationPolicyError,
    preflight,
)


def _default_output_dir() -> Path:
    stamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")
    return REPO_ROOT / "logs" / "two_pc" / stamp


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
    parser.add_argument("--output-dir", type=Path)
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> tuple[int, dict[str, object]]:
    plan = preflight("two-PC BP1/BP2 audio E2E", args.seconds, args.stage)
    capture_margin_seconds = 0.2
    if plan.stage != FINAL_INTEGRATION_STAGE and args.seconds > 59.0:
        raise VerificationPolicyError(
            "two-PC intermediate audio reserves one second for coordination; "
            "request at most 59 seconds"
        )
    output_dir = (args.output_dir or _default_output_dir()).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    result_path = output_dir / "result.json"
    capture_path = output_dir / "capture.pcm"
    evidence: dict[str, object] = {
        "schema": 1,
        "started_at": utc_now(),
        "stage": plan.stage,
        "planned_seconds": plan.planned_seconds,
        "target_capture_seconds": float(plan.planned_seconds or 0.0)
        + capture_margin_seconds,
        "controller": os.environ.get("COMPUTERNAME", ""),
        "target": args.host,
        "candidate_id": candidate_id(),
        "result": "FAIL",
        "failures": [],
    }
    target = RemoteTarget(
        args.host,
        args.user,
        args.identity,
        root=args.target_root,
    )
    target_request = None
    port = None
    try:
        render_entries = audio._audio_endpoint_inventory(audio.E_DATA_FLOW_RENDER)
        render_id = audio._select_endpoint(
            render_entries,
            audio.RENDER_ENDPOINT_ENV,
            "BP1 render endpoint",
            token=audio.BP1_RENDER_TOKENS,
            allow_single=True,
        )
        port_name = audio.resolve_bp1_serial_port()
        evidence["bp1"] = {
            "render_id": render_id,
            "serial_port": port_name,
            "render_inventory": [
                {"id": endpoint_id, "friendly_name": friendly}
                for endpoint_id, friendly in render_entries
            ],
        }
        port = serial.Serial(port_name, 115200, timeout=0.001)
        port.reset_input_buffer()
        evidence["caps"] = audio.decode_responses(audio.send_control(port, 0x20))
        evidence["status_before"] = audio.read_status_pages(port)

        target_request = new_request(
            "START_CAPTURE",
            str(evidence["candidate_id"]),
            stage=plan.stage,
            # Exclusive WASAPI exposes 100-ms capture periods. Capture two
            # extra periods, then analyze exactly the requested render window.
            planned_seconds=float(evidence["target_capture_seconds"]),
            options={
                "exclusive": True,
                "wait_for_go": True,
                "arm_timeout_seconds": 20.0,
            },
        )
        target.start_request(target_request)
        evidence["target_armed"] = target.wait_for_state(
            target_request.request_id, {"armed"}, timeout=20.0
        )

        signal, preamble, tone, prbs = make_signal()
        run_id = int(time.time() * 1000) & 0xFFFFFFFF

        def before_start(_: dict[str, object]) -> None:
            target.signal_run(target_request.request_id, "go")

        def on_started(_: dict[str, object]) -> None:
            packets = audio.send_control(
                port, 0x23, struct.pack("<I", run_id), drain=0.03
            )
            evidence["run_start"] = {
                "run_id": run_id,
                "responses": [(kind, payload.hex()) for kind, payload in packets],
            }

        evidence["render"] = render_pcm16(
            render_id,
            signal,
            float(plan.planned_seconds or 0.0),
            before_start=before_start,
            on_started=on_started,
        )
        end_packets = audio.send_control(
            port, 0x24, struct.pack("<I", run_id), drain=0.05
        )
        evidence["run_end"] = {
            "run_id": run_id,
            "responses": [(kind, payload.hex()) for kind, payload in end_packets],
        }
        evidence["status_after"] = audio.read_status_pages(port)

        target_result = target.wait_result(
            target_request.request_id,
            timeout=(
                float(plan.planned_seconds or 0.0) + 30.0
                if plan.stage == FINAL_INTEGRATION_STAGE
                else 20.0
            ),
        )
        evidence["target_result"] = target_result
        remote_capture = str(target_result.get("payload", {}).get("capture_path", ""))
        if not remote_capture:
            raise RuntimeError("target result did not contain capture_path")
        target.copy_from(remote_capture, capture_path)
        captured_full = np.fromfile(capture_path, dtype="<i2")
        expected_frames = int(
            math.ceil(float(plan.planned_seconds or 0.0) * 48000)
        )
        captured = captured_full[:expected_frames]
        evidence["capture_frames_downloaded"] = int(captured_full.size)
        evidence["capture_frames_analyzed"] = int(captured.size)
        target_capture = target_result.get("payload", {}).get("capture", {})
        metrics = analyze_capture(
            captured,
            preamble,
            tone,
            prbs,
            silent_capture_packets=int(target_capture.get("silent_packets", 0)),
            expected_frames=expected_frames,
            continuous_nonzero=True,
        )
        evidence["metrics"] = metrics
        failures = numeric_failures(metrics)
        if target_result.get("status") != "pass":
            failures.append("target_capture_status")
        if target_capture.get("exclusive") is not True:
            failures.append("target_capture_not_exclusive")
        if target_capture.get("format") != "48000Hz/1ch/PCM/16bit":
            failures.append("target_capture_format")
        evidence["failures"] = failures
        evidence["result"] = "PASS" if not failures else "FAIL"
        return (0 if not failures else 2), evidence
    except Exception as exc:
        failures = evidence.get("failures")
        if isinstance(failures, list):
            failures.append(f"exception: {exc}")
        if target_request is not None:
            try:
                target.signal_run(target_request.request_id, "stop")
            except Exception as stop_exc:
                if isinstance(failures, list):
                    failures.append(f"target_stop: {stop_exc}")
        return 1, evidence
    finally:
        if port is not None:
            port.close()
        evidence["finished_at"] = utc_now()
        atomic_write_json(result_path, evidence)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        exit_code, evidence = run(args)
    except (ValueError, VerificationPolicyError) as exc:
        print(f"TWO_PC_AUDIO_POLICY_FAIL: {exc}", flush=True)
        return 2
    print(json.dumps(evidence, ensure_ascii=True, indent=2, sort_keys=True), flush=True)
    print(f"TWO_PC_AUDIO_{evidence['result']}", flush=True)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
