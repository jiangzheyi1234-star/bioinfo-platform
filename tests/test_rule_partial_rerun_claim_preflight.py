from __future__ import annotations

import json

import pytest

from apps.remote_runner.rule_partial_rerun_claim_preflight import (
    build_rule_partial_rerun_claim_preflight,
    build_rule_partial_rerun_claim_binding,
    rule_partial_rerun_execution_options_requested,
    validate_rule_partial_rerun_claim_preflight,
)
from apps.remote_runner.run_execution_storage import claim_next_run_job
from apps.remote_runner.storage import create_run_record
from apps.remote_runner.storage_core import get_connection
from tests.helpers.reference_database import make_configured_remote_runner


def test_rule_partial_rerun_claim_preflight_accepts_plan_bound_scope() -> None:
    options = _execution_options()

    preflight = build_rule_partial_rerun_claim_preflight(
        options,
        run_id="run_rule_claim",
        attempt_id="att_rule_claim",
        lease_generation=2,
    )

    assert rule_partial_rerun_execution_options_requested(options) is True
    assert preflight["schemaVersion"] == "rule-partial-rerun-claim-preflight.v1"
    assert preflight["claimReady"] is True
    assert preflight["reasonCode"] == "RULE_PARTIAL_RERUN_CLAIM_PREFLIGHT_READY"
    assert preflight["sourcePlanHash"] == "a" * 64
    assert preflight["claimBindingPresent"] is True
    assert preflight["sourcePlanHashMatchesBinding"] is True
    assert preflight["outputAdoptionScopePlanHashMatches"] is True
    assert preflight["outputAdoptionScopeReady"] is True
    assert preflight["outputAdoptionScopeOutputCount"] == 1
    assert preflight["targetOutputKeys"] == ["bam"]
    assert preflight["finalizeRunOnAdoption"] is False
    assert preflight["forcerunRuleCount"] == 1
    assert preflight["pathExposed"] is False
    assert preflight["storageUriExposed"] is False


def test_rule_partial_rerun_claim_preflight_rejects_missing_source_plan_hash() -> None:
    options = _execution_options(source_plan_hash="")

    preflight = build_rule_partial_rerun_claim_preflight(
        options,
        run_id="run_rule_claim",
        attempt_id="att_rule_claim",
        lease_generation=2,
    )

    assert preflight["claimReady"] is False
    assert preflight["reasonCode"] == "RULE_PARTIAL_RERUN_SOURCE_PLAN_HASH_REQUIRED"
    with pytest.raises(ValueError, match="RULE_PARTIAL_RERUN_SOURCE_PLAN_HASH_REQUIRED"):
        validate_rule_partial_rerun_claim_preflight(
            options,
            run_id="run_rule_claim",
            attempt_id="att_rule_claim",
            lease_generation=2,
        )


def test_rule_partial_rerun_claim_preflight_rejects_missing_claim_binding() -> None:
    options = _execution_options()
    del options["rulePartialRerunClaimBinding"]

    preflight = build_rule_partial_rerun_claim_preflight(
        options,
        run_id="run_rule_claim",
        attempt_id="att_rule_claim",
        lease_generation=2,
    )

    assert preflight["claimReady"] is False
    assert preflight["reasonCode"] == "RULE_PARTIAL_RERUN_CLAIM_BINDING_REQUIRED"
    assert preflight["claimBindingPresent"] is False


def test_rule_partial_rerun_claim_preflight_rejects_stale_source_plan_hash_binding() -> None:
    options = _execution_options()
    options["rulePartialRerunClaimBinding"] = {
        **options["rulePartialRerunClaimBinding"],
        "sourcePlanHash": "b" * 64,
    }

    preflight = build_rule_partial_rerun_claim_preflight(
        options,
        run_id="run_rule_claim",
        attempt_id="att_rule_claim",
        lease_generation=2,
    )

    assert preflight["claimReady"] is False
    assert preflight["reasonCode"] == "RULE_PARTIAL_RERUN_SOURCE_PLAN_HASH_STALE"
    assert preflight["sourcePlanHashMatchesBinding"] is False


def test_rule_partial_rerun_claim_preflight_rejects_scope_output_mismatch() -> None:
    options = _execution_options()
    options["outputAdoptionScope"]["outputs"] = [
        {
            "outputKey": "other",
            "stepId": "align",
            "outputOrdinal": 1,
            "invalidationRole": "selected",
            "cacheHit": True,
        }
    ]

    preflight = build_rule_partial_rerun_claim_preflight(
        options,
        run_id="run_rule_claim",
        attempt_id="att_rule_claim",
        lease_generation=2,
    )

    assert preflight["claimReady"] is False
    assert "RULE_RERUN_OUTPUT_ADOPTION_SCOPE_OUTPUTS_MISMATCH" in preflight["blockedReasonCodes"]


def test_rule_partial_rerun_claim_preflight_rejects_stale_output_scope_binding() -> None:
    options = _execution_options()
    options["outputAdoptionScope"]["targetOutputKeys"] = ["other"]

    preflight = build_rule_partial_rerun_claim_preflight(
        options,
        run_id="run_rule_claim",
        attempt_id="att_rule_claim",
        lease_generation=2,
    )

    assert preflight["claimReady"] is False
    assert "RULE_PARTIAL_RERUN_OUTPUT_ADOPTION_SCOPE_STALE" in preflight["blockedReasonCodes"]
    assert "RULE_RERUN_TARGET_OUTPUT_KEYS_MISMATCH" in preflight["blockedReasonCodes"]
    assert preflight["outputAdoptionScopePlanHashMatches"] is False


def test_rule_partial_rerun_claim_preflight_rejects_missing_target_output_keys() -> None:
    options = _execution_options()
    del options["outputAdoptionScope"]["targetOutputKeys"]
    options["rulePartialRerunClaimBinding"] = build_rule_partial_rerun_claim_binding(
        options["outputAdoptionScope"]
    )

    preflight = build_rule_partial_rerun_claim_preflight(
        options,
        run_id="run_rule_claim",
        attempt_id="att_rule_claim",
        lease_generation=2,
    )

    assert preflight["claimReady"] is False
    assert preflight["reasonCode"] == "RULE_RERUN_TARGET_OUTPUT_KEYS_REQUIRED"
    assert preflight["outputAdoptionScopeReady"] is False


def test_rule_partial_rerun_claim_preflight_rejects_finalize_on_adoption() -> None:
    options = _execution_options()
    options["outputAdoptionScope"]["finalizeRunOnAdoption"] = True
    options["rulePartialRerunClaimBinding"] = build_rule_partial_rerun_claim_binding(
        options["outputAdoptionScope"]
    )

    preflight = build_rule_partial_rerun_claim_preflight(
        options,
        run_id="run_rule_claim",
        attempt_id="att_rule_claim",
        lease_generation=2,
    )

    assert preflight["claimReady"] is False
    assert preflight["reasonCode"] == "RULE_RERUN_OUTPUT_ADOPTION_SCOPE_FINALIZE_FORBIDDEN"
    assert preflight["outputAdoptionScopeReady"] is False


def test_rule_partial_rerun_claim_state_validates_active_job_attempt_and_lease(tmp_path) -> None:
    from apps.remote_runner.rule_partial_rerun_claim_preflight import validate_rule_partial_rerun_claim_state

    cfg = make_configured_remote_runner(tmp_path)
    create_run_record(
        cfg,
        server_id="srv_claim_preflight",
        request_id="req_claim_preflight",
        run_spec={
            "runId": "run_claim_preflight",
            "projectId": "proj_claim_preflight",
            "pipelineId": "pipeline_claim_preflight",
            "execution": {"retryPolicy": {"maxAttempts": 3, "backoffSeconds": 0}},
        },
        idempotency_key="idem_claim_preflight",
        payload_hash="h" * 64,
    )
    options = _execution_options()
    with get_connection(cfg) as connection:
        connection.execute(
            "UPDATE run_jobs SET execution_options_json = ? WHERE run_id = ?",
            (json.dumps(options, sort_keys=True, separators=(",", ":")), "run_claim_preflight"),
        )
        connection.commit()
    claim = claim_next_run_job(
        cfg,
        worker_id="worker_claim_preflight",
        now="2099-06-07T10:00:00Z",
        lease_seconds=30,
    )
    assert claim is not None
    preflight = validate_rule_partial_rerun_claim_state(
        cfg,
        options,
        run_id="run_claim_preflight",
        attempt_id=claim["attemptId"],
        lease_generation=claim["leaseGeneration"],
    )

    assert preflight["claimReady"] is True
    assert preflight["jobClaimed"] is True
    assert preflight["attemptRunning"] is True
    assert preflight["activeLeaseMatchesAttempt"] is True
    assert preflight["persistedExecutionOptionsMatch"] is True


def _execution_options(source_plan_hash: str = "a" * 64) -> dict:
    scope = {
        "schemaVersion": "rule-output-adoption-scope.v1",
        "mode": "rule-partial-rerun",
        "sourcePlanHash": source_plan_hash,
        "scopeSource": "ruleCacheRestorePlan.outputs",
        "outputCount": 1,
        "outputKeys": ["bam"],
        "targetOutputKeys": ["bam"],
        "finalizeRunOnAdoption": False,
        "outputs": [
            {
                "outputKey": "bam",
                "stepId": "align",
                "outputOrdinal": 1,
                "invalidationRole": "selected",
                "cacheHit": True,
            }
        ],
        "pathExposed": False,
        "storageUriExposed": False,
    }
    return {
        "schemaVersion": "run-job-execution-options.v1",
        "snakemake": {
            "schemaVersion": "snakemake-rule-rerun-options.v1",
            "rerunIncomplete": True,
            "forcerunRules": ["align"],
        },
        "outputAdoptionScope": scope,
        "rulePartialRerunClaimBinding": build_rule_partial_rerun_claim_binding(scope),
    }
