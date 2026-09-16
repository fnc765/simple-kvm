"""Closed request protocol shared by the two-PC audio/HID harness.

The target deliberately accepts a small command vocabulary instead of shell
text.  Both peers validate the verification stage and duration before any
hardware is touched, so a stale controller cannot silently start a long run.
"""

from __future__ import annotations

import json
import os
import re
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from tools.verification_policy import preflight


SCHEMA_VERSION = 1
ALLOWED_COMMANDS = frozenset(
    {"PREPARE", "START_CAPTURE", "STOP_CAPTURE", "RUN_HID_CHECK", "GET_RESULT"}
)
_ACTIVE_COMMANDS = frozenset({"START_CAPTURE", "RUN_HID_CHECK"})
_COMMAND_OPTIONS = {
    "PREPARE": frozenset(),
    "START_CAPTURE": frozenset(
        {"exclusive", "wait_for_go", "arm_timeout_seconds"}
    ),
    "STOP_CAPTURE": frozenset({"target_request_id"}),
    "RUN_HID_CHECK": frozenset({"safety_port", "safety_token"}),
    "GET_RESULT": frozenset({"target_request_id"}),
}
_REQUEST_ID_RE = re.compile(r"^[0-9a-f]{32}$")
_CANDIDATE_ID_RE = re.compile(r"^[0-9a-f]{64}$")
MAX_REQUEST_BYTES = 64 * 1024


class ProtocolError(ValueError):
    """Raised when a controller request is malformed or unsafe."""


@dataclass(frozen=True)
class TargetRequest:
    schema: int
    request_id: str
    command: str
    candidate_id: str
    stage: str
    planned_seconds: float
    created_at: str
    options: dict[str, Any]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def new_request(
    command: str,
    candidate_id: str,
    *,
    stage: str = "intermediate",
    planned_seconds: float = 0.0,
    options: Mapping[str, Any] | None = None,
) -> TargetRequest:
    raw = {
        "schema": SCHEMA_VERSION,
        "request_id": uuid.uuid4().hex,
        "command": command,
        "candidate_id": candidate_id,
        "stage": stage,
        "planned_seconds": planned_seconds,
        "created_at": utc_now(),
        "options": dict(options or {}),
    }
    return validate_request(raw)


def validate_request(raw: Mapping[str, Any]) -> TargetRequest:
    if not isinstance(raw, Mapping):
        raise ProtocolError("request must be a JSON object")
    allowed_fields = {
        "schema",
        "request_id",
        "command",
        "candidate_id",
        "stage",
        "planned_seconds",
        "created_at",
        "options",
    }
    unknown = sorted(set(raw) - allowed_fields)
    if unknown:
        raise ProtocolError(f"unknown request field(s): {', '.join(unknown)}")
    if raw.get("schema") != SCHEMA_VERSION:
        raise ProtocolError(f"unsupported request schema: {raw.get('schema')!r}")

    request_id = str(raw.get("request_id", "")).lower()
    if not _REQUEST_ID_RE.fullmatch(request_id):
        raise ProtocolError("request_id must be 32 lowercase hexadecimal characters")
    command = str(raw.get("command", "")).upper()
    if command not in ALLOWED_COMMANDS:
        raise ProtocolError(f"command is not allowed: {command!r}")
    candidate_id = str(raw.get("candidate_id", "")).lower()
    if not _CANDIDATE_ID_RE.fullmatch(candidate_id):
        raise ProtocolError("candidate_id must be a SHA-256 hexadecimal digest")

    options = raw.get("options", {})
    if not isinstance(options, dict):
        raise ProtocolError("options must be a JSON object")
    unknown_options = sorted(set(options) - _COMMAND_OPTIONS[command])
    if unknown_options:
        raise ProtocolError(
            f"unknown {command} option(s): {', '.join(unknown_options)}"
        )
    if command == "START_CAPTURE":
        for name in ("exclusive", "wait_for_go"):
            if name in options and not isinstance(options[name], bool):
                raise ProtocolError(f"START_CAPTURE {name} must be a boolean")
        try:
            arm_timeout = float(options.get("arm_timeout_seconds", 20.0))
        except (TypeError, ValueError) as exc:
            raise ProtocolError("START_CAPTURE arm_timeout_seconds must be numeric") from exc
        if not 1.0 <= arm_timeout <= 30.0:
            raise ProtocolError("START_CAPTURE arm_timeout_seconds must be within 1..30")
    elif command == "RUN_HID_CHECK":
        try:
            safety_port = int(options.get("safety_port", 47652))
        except (TypeError, ValueError) as exc:
            raise ProtocolError("RUN_HID_CHECK safety_port must be an integer") from exc
        if not 1024 <= safety_port <= 65535:
            raise ProtocolError("RUN_HID_CHECK safety_port must be within 1024..65535")
        safety_token = str(options.get("safety_token", ""))
        if not _REQUEST_ID_RE.fullmatch(safety_token):
            raise ProtocolError(
                "RUN_HID_CHECK safety_token must be 32 lowercase hex characters"
            )
    elif command in {"STOP_CAPTURE", "GET_RESULT"}:
        target_id = str(options.get("target_request_id", ""))
        if not _REQUEST_ID_RE.fullmatch(target_id):
            raise ProtocolError(
                f"{command} target_request_id must be 32 lowercase hex characters"
            )
    created_at = str(raw.get("created_at", ""))
    try:
        datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ProtocolError("created_at must be an ISO-8601 timestamp") from exc

    try:
        duration = float(raw.get("planned_seconds", 0.0))
        plan = preflight(
            f"two-PC {command}", planned_seconds=duration, stage=str(raw.get("stage", ""))
        )
    except (TypeError, ValueError) as exc:
        raise ProtocolError(str(exc)) from exc
    if command in _ACTIVE_COMMANDS and duration <= 0.0:
        raise ProtocolError(f"{command} requires planned_seconds > 0")
    if command not in _ACTIVE_COMMANDS and duration != 0.0:
        raise ProtocolError(f"{command} requires planned_seconds = 0")

    return TargetRequest(
        schema=SCHEMA_VERSION,
        request_id=request_id,
        command=command,
        candidate_id=candidate_id,
        stage=plan.stage,
        planned_seconds=float(plan.planned_seconds or 0.0),
        created_at=created_at,
        options=dict(options),
    )


def load_request(path: Path) -> TargetRequest:
    size = path.stat().st_size
    if size > MAX_REQUEST_BYTES:
        raise ProtocolError(f"request exceeds {MAX_REQUEST_BYTES} bytes")
    raw = json.loads(path.read_text(encoding="utf-8"))
    return validate_request(raw)


def atomic_write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def write_request(path: Path, request: TargetRequest) -> None:
    atomic_write_json(path, asdict(request))
