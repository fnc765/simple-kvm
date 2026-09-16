"""Repository-wide verification duration hook for pytest."""

from __future__ import annotations

import time

from tools.verification_policy import (
    INTERMEDIATE_MAX_SECONDS,
    preflight,
)


def pytest_sessionstart(session):
    session._simple_kvm_verification_started = time.monotonic()
    preflight("pytest suite", stage="intermediate")


def pytest_sessionfinish(session, exitstatus):
    started = getattr(session, "_simple_kvm_verification_started", None)
    if started is None:
        return
    elapsed = time.monotonic() - started
    print(
        "VERIFICATION_POLICY_RESULT "
        f"name=pytest_suite stage=intermediate elapsed_seconds={elapsed:.3f}",
        flush=True,
    )
    if elapsed > INTERMEDIATE_MAX_SECONDS:
        print(
            "VERIFICATION_POLICY_FAIL "
            f"name=pytest_suite reason=elapsed_seconds_exceeded_{INTERMEDIATE_MAX_SECONDS:.0f}",
            flush=True,
        )
        if session.exitstatus == 0:
            session.exitstatus = 1
