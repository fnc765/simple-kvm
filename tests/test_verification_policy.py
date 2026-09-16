from __future__ import annotations

import pytest

from tools.verification_policy import (
    FINAL_INTEGRATION_STAGE,
    INTERMEDIATE_STAGE,
    VerificationPolicyError,
    normalize_stage,
    preflight,
)


def test_intermediate_budget_accepts_sixty_seconds():
    plan = preflight("unit", 60.0, INTERMEDIATE_STAGE)
    assert plan.stage == INTERMEDIATE_STAGE


def test_intermediate_budget_rejects_long_run():
    with pytest.raises(VerificationPolicyError, match="limited to"):
        preflight("unit", 60.001, INTERMEDIATE_STAGE)


def test_final_integration_requires_five_minutes():
    with pytest.raises(VerificationPolicyError, match="at least"):
        preflight("final", 299.0, FINAL_INTEGRATION_STAGE)
    with pytest.raises(VerificationPolicyError, match="at least"):
        preflight("final", 0.0, FINAL_INTEGRATION_STAGE)
    assert preflight("final", 300.0, FINAL_INTEGRATION_STAGE).planned_seconds == 300.0


def test_final_stage_alias_is_canonical():
    assert normalize_stage("final") == FINAL_INTEGRATION_STAGE
