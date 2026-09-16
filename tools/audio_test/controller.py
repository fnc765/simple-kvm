"""SSH controller for the interactive two-PC verification target.

The controller deploys a content-addressed release, registers the target as an
interactive logon task, and exchanges only validated JSON requests/results.
It never sends controller-provided shell text through the agent protocol.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import socket
import subprocess
import sys
import tempfile
import time
import uuid
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.audio_test.two_pc_protocol import (  # noqa: E402
    TargetRequest,
    new_request,
    utc_now,
    write_request,
)


DEFAULT_TASK_NAME = "SimpleKvmBenchTarget"
PACKAGE_DIRS = ("app", "tools")
PACKAGE_FILES = ("pyproject.toml", "README.md", "LICENSE")
EXCLUDED_PARTS = frozenset(
    {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", "logs", ".pio"}
)


def _package_paths() -> list[Path]:
    paths: list[Path] = []
    for directory in PACKAGE_DIRS:
        for path in (REPO_ROOT / directory).rglob("*"):
            relative = path.relative_to(REPO_ROOT)
            if (
                path.is_file()
                and not any(part in EXCLUDED_PARTS for part in relative.parts)
                and path.suffix not in {".pyc", ".pyo"}
            ):
                paths.append(path)
    for filename in PACKAGE_FILES:
        path = REPO_ROOT / filename
        if path.is_file():
            paths.append(path)
    return sorted(paths, key=lambda value: value.relative_to(REPO_ROOT).as_posix())


def candidate_id(paths: list[Path] | None = None) -> str:
    digest = hashlib.sha256()
    for path in paths or _package_paths():
        relative = path.relative_to(REPO_ROOT).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        data = path.read_bytes()
        digest.update(len(data).to_bytes(8, "big"))
        digest.update(data)
    return digest.hexdigest()


def build_bundle(output: Path) -> dict[str, Any]:
    paths = _package_paths()
    identity = candidate_id(paths)
    manifest = {
        "schema": 1,
        "candidate_id": identity,
        "created_at": utc_now(),
        "controller_hostname": socket.gethostname(),
        "files": [path.relative_to(REPO_ROOT).as_posix() for path in paths],
    }
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in paths:
            archive.write(path, path.relative_to(REPO_ROOT).as_posix())
        archive.writestr(
            "manifest.json",
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        )
    return manifest


def _ps_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _encoded_powershell(script: str) -> list[str]:
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    return [
        "powershell.exe",
        "-NoLogo",
        "-NoProfile",
        "-NonInteractive",
        "-EncodedCommand",
        encoded,
    ]


class RemoteTarget:
    def __init__(
        self,
        host: str,
        user: str,
        identity: Path,
        *,
        root: str,
        task_name: str = DEFAULT_TASK_NAME,
    ) -> None:
        self.host = host
        self.user = user
        self.identity = identity.resolve()
        self.root = root.rstrip("\\/")
        self.task_name = task_name

    @property
    def destination(self) -> str:
        return f"{self.user}@{self.host}"

    def _connection_args(self) -> list[str]:
        return [
            "-i",
            str(self.identity),
            "-o",
            "IdentitiesOnly=yes",
            "-o",
            "BatchMode=yes",
            "-o",
            "StrictHostKeyChecking=yes",
            "-o",
            "ConnectTimeout=10",
        ]

    def powershell(
        self,
        script: str,
        *,
        timeout: float = 30.0,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        command = ["ssh.exe", *self._connection_args(), self.destination]
        remote_script = "\n".join(
            [
                "$ProgressPreference='SilentlyContinue'",
                "[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new($false)",
                script,
            ]
        )
        command.extend(_encoded_powershell(remote_script))
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if check and completed.returncode != 0:
            raise RuntimeError(
                f"remote PowerShell failed with {completed.returncode}: "
                f"stdout={completed.stdout.strip()!r} stderr={completed.stderr.strip()!r}"
            )
        return completed

    def copy_to(self, local: Path, remote_path: str, *, timeout: float = 120.0) -> None:
        remote_scp_path = PurePosixPath(remote_path.replace("\\", "/"))
        subprocess.run(
            [
                "scp.exe",
                *self._connection_args(),
                str(local),
                f"{self.destination}:{remote_scp_path}",
            ],
            check=True,
            timeout=timeout,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )

    def copy_from(self, remote_path: str, local: Path, *, timeout: float = 120.0) -> None:
        remote_scp_path = PurePosixPath(remote_path.replace("\\", "/"))
        local.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            [
                "scp.exe",
                *self._connection_args(),
                f"{self.destination}:{remote_scp_path}",
                str(local),
            ],
            check=True,
            timeout=timeout,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )

    def install(self) -> dict[str, Any]:
        with tempfile.TemporaryDirectory(prefix="simple-kvm-target-") as temp:
            archive = Path(temp) / "release.zip"
            manifest = build_bundle(archive)
            identity = str(manifest["candidate_id"])
            incoming_dir = f"{self.root}\\incoming"
            remote_archive = f"{incoming_dir}\\{identity}.zip"
            release = f"{self.root}\\releases\\{identity}"
            self.powershell(
                f"New-Item -ItemType Directory -Force -Path {_ps_literal(incoming_dir)} | Out-Null"
            )
            self.copy_to(archive, remote_archive)
            install_script = f"{release}\\tools\\audio_test\\install_target_agent.ps1"
            script = "\n".join(
                [
                    "$ErrorActionPreference='Stop'",
                    f"$release={_ps_literal(release)}",
                    "if (Test-Path -LiteralPath $release) { Remove-Item -LiteralPath $release -Recurse -Force }",
                    "New-Item -ItemType Directory -Force -Path $release | Out-Null",
                    f"Expand-Archive -LiteralPath {_ps_literal(remote_archive)} -DestinationPath $release -Force",
                    f"& {_ps_literal(install_script)} -Root {_ps_literal(self.root)} -ReleaseRoot $release -TaskName {_ps_literal(self.task_name)}",
                    "if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }",
                ]
            )
            completed = self.powershell(script, timeout=600.0)
            output = completed.stdout.strip()
            try:
                task = json.loads(output[output.index("{") :])
            except (ValueError, json.JSONDecodeError):
                task = {"raw_output": output}
            return {"manifest": manifest, "task": task}

    def _trigger(self) -> None:
        task = _ps_literal(self.task_name)
        completed = self.powershell(
            f"Start-ScheduledTask -TaskName {task}; (Get-ScheduledTask -TaskName {task}).State",
            timeout=20.0,
        )
        state = completed.stdout.strip()
        if not state:
            raise RuntimeError("scheduled task did not return a state")

    def start_request(self, request: TargetRequest) -> None:
        request_path = f"{self.root}\\request.json"
        with tempfile.TemporaryDirectory(prefix="simple-kvm-request-") as temp:
            local_request = Path(temp) / "request.json"
            write_request(local_request, request)
            self.copy_to(local_request, request_path, timeout=30.0)
        self._trigger()

    def _read_json(self, remote_path: str) -> dict[str, Any] | None:
        literal = _ps_literal(remote_path)
        completed = self.powershell(
            f"if (Test-Path -LiteralPath {literal}) "
            f"{{ [IO.File]::ReadAllText({literal}, [Text.Encoding]::UTF8) }}",
            timeout=15.0,
            check=False,
        )
        text = completed.stdout.strip()
        if not text:
            return None
        try:
            value = json.loads(text[text.index("{") :])
        except (ValueError, json.JSONDecodeError):
            return None
        return value if isinstance(value, dict) else None

    def wait_for_state(
        self,
        request_id: str,
        statuses: set[str],
        *,
        timeout: float,
    ) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        last_state: dict[str, Any] | None = None
        while time.monotonic() < deadline:
            state = self._read_json(f"{self.root}\\state.json")
            if state is not None and state.get("request_id") == request_id:
                last_state = state
                status = str(state.get("status"))
                if status in statuses:
                    return state
                if status in {"fail", "error"}:
                    result = self._read_json(f"{self.root}\\result.json")
                    raise RuntimeError(f"target failed while waiting for {statuses}: {result or state}")
            time.sleep(0.25)
        raise TimeoutError(
            f"target request {request_id} did not reach {sorted(statuses)} after "
            f"{timeout:.1f}s; last_state={last_state}"
        )

    def signal_run(self, request_id: str, signal: str) -> None:
        if signal not in {"go", "stop"}:
            raise ValueError(f"unsupported target signal: {signal}")
        path = f"{self.root}\\runs\\{request_id}\\{signal}"
        self.powershell(
            f"New-Item -ItemType File -Force -Path {_ps_literal(path)} | Out-Null",
            timeout=15.0,
        )

    def wait_result(self, request_id: str, *, timeout: float) -> dict[str, Any]:
        result_path = f"{self.root}\\result.json"

        deadline = time.monotonic() + timeout
        last_state: dict[str, Any] | None = None
        while time.monotonic() < deadline:
            value = self._read_json(result_path)
            if isinstance(value, dict) and value.get("request_id") == request_id:
                last_state = value
                if value.get("status") in {"pass", "fail", "error"}:
                    return value
            time.sleep(0.5)
        raise TimeoutError(
            f"target request {request_id} timed out after {timeout:.1f}s; "
            f"last_state={last_state}"
        )

    def send_request(self, request: TargetRequest, *, timeout: float) -> dict[str, Any]:
        self.start_request(request)
        return self.wait_result(request.request_id, timeout=timeout)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", required=True)
    parser.add_argument("--user", required=True)
    parser.add_argument("--identity", type=Path, required=True)
    parser.add_argument(
        "--root",
        default=r"C:\Users\choco\AppData\Local\SimpleKvmBench",
    )
    parser.add_argument("--task-name", default=DEFAULT_TASK_NAME)
    subparsers = parser.add_subparsers(dest="operation", required=True)
    subparsers.add_parser("install")
    subparsers.add_parser("prepare")
    request_parser = subparsers.add_parser("request")
    request_parser.add_argument("command", choices=["START_CAPTURE", "RUN_HID_CHECK"])
    request_parser.add_argument("--stage", default="intermediate")
    request_parser.add_argument("--seconds", type=float, required=True)
    request_parser.add_argument("--shared", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    target = RemoteTarget(
        args.host,
        args.user,
        args.identity,
        root=args.root,
        task_name=args.task_name,
    )
    if args.operation == "install":
        result = target.install()
    else:
        local_candidate = candidate_id()
        if args.operation == "prepare":
            request = new_request("PREPARE", local_candidate)
            timeout = 45.0
        else:
            options = (
                {"exclusive": not args.shared, "wait_for_go": False}
                if args.command == "START_CAPTURE"
                else {"safety_port": 47652, "safety_token": uuid.uuid4().hex}
            )
            request = new_request(
                args.command,
                local_candidate,
                stage=args.stage,
                planned_seconds=args.seconds,
                options=options,
            )
            timeout = (
                args.seconds + 30.0
                if request.stage == "final-integration"
                else min(60.0, args.seconds + 20.0)
            )
        result = target.send_request(request, timeout=timeout)
    # Keep command output portable across the default Japanese cp932 console.
    # The JSON evidence files remain UTF-8 and preserve the original strings.
    print(json.dumps(result, ensure_ascii=True, indent=2, sort_keys=True))
    if isinstance(result, dict) and result.get("status") in {"fail", "error"}:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
