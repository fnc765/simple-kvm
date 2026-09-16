"""Guardrails for the duration and stage of repository verification runs.

Every verification entry point should call :func:`preflight` before touching
hardware or starting a long-running check.  The reminder is intentionally
machine-readable and human-readable so logs make the time budget explicit.
"""

from __future__ import annotations

import argparse
import json
import math
import os
from dataclasses import dataclass


INTERMEDIATE_STAGE = "intermediate"
FINAL_INTEGRATION_STAGE = "final-integration"
DEFAULT_STAGE = INTERMEDIATE_STAGE
INTERMEDIATE_MAX_SECONDS = 60.0
FINAL_INTEGRATION_MIN_SECONDS = 300.0
STAGE_ENV = "SIMPLE_KVM_VERIFICATION_STAGE"


class VerificationPolicyError(ValueError):
    """Raised when a verification request violates the time policy."""


@dataclass(frozen=True)
class VerificationPlan:
    name: str
    stage: str
    planned_seconds: float | None


def normalize_stage(stage: str | None = None) -> str:
    """Return the canonical stage name from an argument or environment."""

    value = (stage or os.environ.get(STAGE_ENV) or DEFAULT_STAGE).strip().lower()
    aliases = {
        "final": FINAL_INTEGRATION_STAGE,
        "final_integration": FINAL_INTEGRATION_STAGE,
        "final-integration": FINAL_INTEGRATION_STAGE,
        "intermediate": INTERMEDIATE_STAGE,
    }
    try:
        return aliases[value]
    except KeyError as exc:
        raise VerificationPolicyError(
            f"unknown verification stage {value!r}; use "
            f"{INTERMEDIATE_STAGE!r} or {FINAL_INTEGRATION_STAGE!r}"
        ) from exc


def _validate_duration(planned_seconds: float | None) -> float | None:
    if planned_seconds is None:
        return None
    value = float(planned_seconds)
    if not math.isfinite(value) or value < 0.0:
        raise VerificationPolicyError(
            f"planned verification duration must be finite and non-negative: "
            f"{planned_seconds!r}"
        )
    return value


def _violation(stage: str, duration: float | None) -> str | None:
    if duration is None:
        return None
    if stage == INTERMEDIATE_STAGE and duration > INTERMEDIATE_MAX_SECONDS:
        return (
            f"intermediate verification is limited to "
            f"{INTERMEDIATE_MAX_SECONDS:.0f}s; requested {duration:.3f}s"
        )
    if stage == FINAL_INTEGRATION_STAGE and duration < FINAL_INTEGRATION_MIN_SECONDS:
        return (
            f"final integration verification must run at least "
            f"{FINAL_INTEGRATION_MIN_SECONDS:.0f}s; requested {duration:.3f}s"
        )
    return None


def preflight(
    name: str,
    planned_seconds: float | None = None,
    stage: str | None = None,
) -> VerificationPlan:
    """Print the policy reminder and reject an invalid planned duration."""

    canonical_stage = normalize_stage(stage)
    duration = _validate_duration(planned_seconds)
    plan = VerificationPlan(str(name), canonical_stage, duration)
    reminder = {
        "name": plan.name,
        "stage": plan.stage,
        "planned_seconds": plan.planned_seconds,
        "intermediate_max_seconds": INTERMEDIATE_MAX_SECONDS,
        "final_integration_min_seconds": FINAL_INTEGRATION_MIN_SECONDS,
        # Keep the primary reminder ASCII-safe: the PowerShell/cmd code page
        # can otherwise render the Japanese text as mojibake in saved logs.
        "message": "intermediate verification <= 60 seconds; final integration >= 300 seconds",
    }
    print(
        "VERIFICATION_POLICY_REMINDER "
        + json.dumps(reminder, ensure_ascii=False, sort_keys=True),
        flush=True,
    )
    violation = _violation(canonical_stage, duration)
    if violation is not None:
        print(
            "VERIFICATION_POLICY_FAIL "
            + json.dumps({"name": plan.name, "reason": violation}, ensure_ascii=False),
            flush=True,
        )
        raise VerificationPolicyError(violation)
    print(
        "VERIFICATION_POLICY_OK "
        + json.dumps(
            {"name": plan.name, "stage": plan.stage},
            ensure_ascii=False,
            sort_keys=True,
        ),
        flush=True,
    )
    return plan


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", default="verification")
    parser.add_argument("--stage")
    parser.add_argument("--duration", type=float)
    args = parser.parse_args(argv)
    try:
        preflight(args.name, args.duration, args.stage)
    except VerificationPolicyError:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
