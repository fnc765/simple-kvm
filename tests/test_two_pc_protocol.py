from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

import pytest

from tools.audio_test.two_pc_protocol import ProtocolError, new_request, validate_request
from tools.audio_test.controller import candidate_id


CANDIDATE = "a" * 64


def test_prepare_is_closed_and_zero_duration():
    request = new_request("PREPARE", CANDIDATE)
    assert request.command == "PREPARE"
    assert request.planned_seconds == 0.0
    assert validate_request(asdict(request)) == request


def test_active_request_rechecks_intermediate_budget():
    options = {"safety_token": "b" * 32}
    request = new_request(
        "RUN_HID_CHECK", CANDIDATE, planned_seconds=60.0, options=options
    )
    assert request.planned_seconds == 60.0
    with pytest.raises(ProtocolError, match="limited to"):
        new_request(
            "RUN_HID_CHECK",
            CANDIDATE,
            planned_seconds=60.001,
            options=options,
        )


def test_final_request_requires_five_minutes():
    with pytest.raises(ProtocolError, match="at least"):
        new_request(
            "START_CAPTURE",
            CANDIDATE,
            stage="final-integration",
            planned_seconds=299.0,
        )
    request = new_request(
        "START_CAPTURE",
        CANDIDATE,
        stage="final-integration",
        planned_seconds=300.0,
    )
    assert request.planned_seconds == 300.0


def test_rejects_shell_text_and_unknown_fields():
    request = asdict(new_request("PREPARE", CANDIDATE))
    request["command"] = "powershell.exe Get-ChildItem"
    with pytest.raises(ProtocolError, match="not allowed"):
        validate_request(request)
    request = asdict(new_request("PREPARE", CANDIDATE))
    request["shell"] = "whoami"
    with pytest.raises(ProtocolError, match="unknown request"):
        validate_request(request)


def test_passive_commands_reject_hidden_runtime():
    with pytest.raises(ProtocolError, match="requires planned_seconds = 0"):
        new_request("PREPARE", CANDIDATE, planned_seconds=1.0)


def test_options_are_closed_per_command():
    with pytest.raises(ProtocolError, match="unknown PREPARE option"):
        new_request("PREPARE", CANDIDATE, options={"shell": "whoami"})
    with pytest.raises(ProtocolError, match="target_request_id"):
        new_request(
            "STOP_CAPTURE",
            CANDIDATE,
            options={"target_request_id": "..\\..\\outside"},
        )
    request = new_request(
        "RUN_HID_CHECK",
        CANDIDATE,
        planned_seconds=10,
        options={"safety_port": 47652, "safety_token": "b" * 32},
    )
    assert request.options["safety_port"] == 47652


def test_candidate_digest_changes_with_content(monkeypatch, tmp_path: Path):
    first = tmp_path / "first.txt"
    first.write_text("one", encoding="utf-8")
    monkeypatch.setattr("tools.audio_test.controller.REPO_ROOT", tmp_path)
    before = candidate_id([first])
    first.write_text("two", encoding="utf-8")
    assert candidate_id([first]) != before
