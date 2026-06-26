from __future__ import annotations

import pytest

from apps.remote_runner.execution_plan_hash import stable_plan_hash
from apps.remote_runner.rule_retry_execution_plan import build_rule_retry_execution_plan, rule_retry_execution_options


def test_rule_retry_execution_plan_previews_snakemake_forcerun_options_without_enabling_execution() -> None:
    plan = build_rule_retry_execution_plan(_rule_retry_plan())

    assert plan["schemaVersion"] == "rule-retry-execution-plan.v1"
    assert len(plan["planHash"]) == 64
    assert plan["planHash"] == stable_plan_hash(plan)
    assert plan["supported"] is False
    assert plan["eligibleNow"] is False
    assert plan["executionEnabled"] is False
    assert plan["executionReasonCode"] == "RULE_RETRY_EXECUTION_DISABLED"
    assert plan["activationReadiness"]["schemaVersion"] == "rule-retry-activation-readiness.v1"
    assert plan["activationReadiness"]["executionReady"] is False
    assert plan["activationReadiness"]["executionEnabled"] is False
    assert plan["activationReadiness"]["reasonCode"] == "DOWNSTREAM_OUTPUT_INVALIDATION_APPLY_REQUIRED"
    assert plan["activationReadiness"]["readyCheckCount"] == 2
    assert plan["activationReadiness"]["blockedCheckCount"] == 9
    assert plan["activationReadiness"]["summary"]["selectedRuleCount"] == 1
    assert plan["activationReadiness"]["summary"]["rerunRuleCount"] == 2
    assert plan["activationReadiness"]["redactionPolicy"] == {
        "rawIdentifiersExposed": False,
        "fingerprintsExposed": True,
        "storageUrisExposed": False,
        "pathsExposed": False,
    }
    assert plan["reasonCode"] == "PARTIAL_RULE_RETRY_UNSUPPORTED"
    assert plan["sourceReasonCode"] == "PARTIAL_RULE_RETRY_UNSUPPORTED"
    assert plan["sourceBlockedReasonCodes"] == ["CACHE_ADOPTION_UNPROVEN", "ARTIFACT_ADOPTION_UNPROVEN"]
    assert plan["commandPreviewAvailable"] is True
    assert [rule["ruleName"] for rule in plan["selectedRules"]] == ["align"]
    assert [rule["ruleName"] for rule in plan["rerunScope"]["rules"]] == ["align", "report"]
    assert plan["snakemakeOptions"] == {
        "schemaVersion": "snakemake-rule-rerun-options.v1",
        "rerunIncomplete": True,
        "forcerunRules": ["align"],
        "argsPreview": ["--rerun-incomplete", "--forcerun", "align"],
        "unsafeFlagsProhibited": ["--forceall", "--touch", "--ignore-incomplete"],
    }
    assert plan["executorOrchestration"]["schemaVersion"] == "rerun-executor-orchestration.v1"
    assert plan["executorOrchestration"]["mode"] == "rule-partial-rerun"
    assert plan["executorOrchestration"]["contractReady"] is False
    assert plan["executorOrchestration"]["executorReady"] is False
    assert plan["executorOrchestration"]["queueMutationAllowed"] is False
    assert plan["executorOrchestration"]["runStateMutationAllowed"] is False
    assert plan["executorOrchestration"]["pathExposed"] is False
    assert "ATTEMPT_OUTPUT_RESTORE_UNPROVEN" in plan["blockedReasonCodes"]
    assert "RULE_RETRY_MUTATION_API_DISABLED" in plan["blockedReasonCodes"]
    assert "CACHE_ADOPTION_UNPROVEN" in plan["blockedReasonCodes"]
    assert "STAGED_FILE_POLICY_UNREPRESENTED" in plan["blockedReasonCodes"]
    assert "RESTORE_PIN_POLICY_UNREPRESENTED" in plan["blockedReasonCodes"]
    assert plan["cacheRestorePlan"]["schemaVersion"] == "rule-cache-restore-plan.v1"
    assert len(plan["cacheRestorePlan"]["planHash"]) == 64
    assert plan["cacheRestorePlan"]["planHash"] == stable_plan_hash(plan["cacheRestorePlan"])
    assert plan["cacheRestorePlan"]["reasonCode"] == "PER_RULE_CACHE_PREFLIGHT_UNAVAILABLE"
    assert plan["cacheRestorePlan"]["redactionPolicy"]["cacheKeysExposed"] is False
    assert plan["cacheRestorePlan"]["redactionPolicy"]["cacheKeyFingerprintsExposed"] is True
    assert plan["cacheRestorePlan"]["stagedFilePolicy"]["overwriteAllowed"] is False
    assert plan["cacheRestorePlan"]["restorePinPolicy"]["pinCreationAllowed"] is False
    assert plan["cacheRestorePlan"]["restorePinPolicy"]["ownerIdExposed"] is False


def test_rule_retry_execution_plan_drops_output_invalidation_blocker_after_apply() -> None:
    plan = build_rule_retry_execution_plan(
        _rule_retry_plan(),
        output_invalidation_plan={
            "schemaVersion": "rule-output-invalidation-plan.v1",
            "planHash": "a" * 64,
            "previewAvailable": True,
            "reasonCode": "OUTPUT_EDGE_INVALIDATION_ALREADY_APPLIED",
            "blockedReasonCodes": ["OUTPUT_EDGE_INVALIDATION_ALREADY_APPLIED"],
            "outputInvalidationState": {
                "schemaVersion": "rule-output-invalidation-state.v1",
                "state": "applied",
                "appliedOutputEdgeCount": 2,
                "appliedLineageEdgeCount": 2,
                "evidenceEventCount": 1,
            },
        },
    )

    assert plan["executionEnabled"] is False
    readiness = plan["activationReadiness"]
    checks = {item["name"]: item for item in readiness["checks"]}
    assert readiness["executionReady"] is False
    assert checks["outputInvalidationApplied"]["ready"] is True
    assert checks["publicMutation"]["reasonCode"] == "RULE_RETRY_MUTATION_API_DISABLED"
    assert checks["partialRerunExecutor"]["reasonCode"] == "PER_RULE_CACHE_PREFLIGHT_UNAVAILABLE"
    assert plan["executorOrchestration"]["contractReady"] is False
    assert plan["executorOrchestration"]["reasonCode"] == "PER_RULE_CACHE_PREFLIGHT_UNAVAILABLE"
    assert "DOWNSTREAM_OUTPUT_INVALIDATION_APPLY_REQUIRED" not in plan["blockedReasonCodes"]
    assert "DOWNSTREAM_OUTPUT_INVALIDATION_APPLY_REQUIRED" not in plan["requiresBeforeExecution"]
    assert "STAGED_FILE_POLICY_UNREPRESENTED" not in plan["blockedReasonCodes"]
    assert "STAGED_FILE_POLICY_EXECUTION_DISABLED" in plan["blockedReasonCodes"]
    assert "STAGED_FILE_POLICY_EXECUTION_DISABLED" in plan["requiresBeforeExecution"]
    assert "RESTORE_PIN_POLICY_UNREPRESENTED" not in plan["blockedReasonCodes"]
    assert "RESTORE_PIN_ACTIVE_LEASE_REQUIRED" in plan["blockedReasonCodes"]
    assert "RESTORE_PIN_ACTIVE_LEASE_REQUIRED" in plan["requiresBeforeExecution"]
    assert "PARTIAL_RESTORE_EXECUTOR_UNAVAILABLE" in plan["requiresBeforeExecution"]


def test_rule_retry_execution_plan_marks_workdir_reuse_ready_from_redacted_policy() -> None:
    plan = build_rule_retry_execution_plan(
        _rule_retry_plan(),
        workdir_reuse_policy={
            "schemaVersion": "run-workdir-reuse-policy.v1",
            "workDirReusable": True,
            "pathExposed": False,
            "reasonCode": "WORKDIR_REUSABLE",
        },
    )

    checks = {item["name"]: item for item in plan["activationReadiness"]["checks"]}
    assert checks["workdirReuse"] == {
        "name": "workdirReuse",
        "ready": True,
        "reasonCode": "READY",
    }
    assert plan["activationReadiness"]["executionReady"] is False
    assert plan["executionEnabled"] is False


def test_rule_retry_execution_plan_marks_orchestration_contract_ready_without_enabling_executor() -> None:
    plan = build_rule_retry_execution_plan(
        _rule_retry_plan(),
        output_invalidation_plan=_applied_output_invalidation_plan(),
        cache_restore_plan=_adopted_cache_restore_plan(),
        workdir_reuse_policy={
            "schemaVersion": "run-workdir-reuse-policy.v1",
            "workDirReusable": True,
            "pathExposed": False,
            "reasonCode": "WORKDIR_REUSABLE",
        },
        incomplete_output_audit={
            "schemaVersion": "rule-output-audit.v1",
            "available": True,
            "expectedOutputCount": 1,
            "verifiedOutputCount": 1,
            "rerunRequiredOutputCount": 0,
            "unverifiedOutputCount": 0,
            "unsafeOutputCount": 0,
            "uncheckedOutputCount": 0,
            "pathExposed": False,
            "storageUriExposed": False,
            "reasonCode": "OUTPUT_AUDIT_VERIFIED",
        },
    )

    orchestration = plan["executorOrchestration"]
    readiness_checks = {item["name"]: item for item in plan["activationReadiness"]["checks"]}
    assert orchestration["contractReady"] is True
    assert orchestration["executorReady"] is False
    assert orchestration["reasonCode"] == "PARTIAL_RERUN_EXECUTOR_ORCHESTRATION_PREVIEW_ONLY"
    assert orchestration["queueMutationAllowed"] is False
    assert orchestration["pathExposed"] is False
    assert readiness_checks["partialRerunExecutor"]["reasonCode"] == (
        "PARTIAL_RERUN_EXECUTOR_ORCHESTRATION_PREVIEW_ONLY"
    )
    assert readiness_checks["publicMutation"]["reasonCode"] == "RULE_RETRY_MUTATION_API_DISABLED"
    assert plan["executionEnabled"] is False


def test_rule_retry_execution_options_refuses_disabled_preview_plan() -> None:
    plan = build_rule_retry_execution_plan(_rule_retry_plan())

    with pytest.raises(ValueError, match="RULE_RETRY_EXECUTION_DISABLED"):
        rule_retry_execution_options(plan)


def test_rule_retry_execution_options_materializes_enabled_plan() -> None:
    plan = {
        **build_rule_retry_execution_plan(_rule_retry_plan()),
        "supported": True,
        "eligible": True,
        "eligibleNow": True,
        "executionEnabled": True,
        "blockedReasonCodes": [],
        "requiresBeforeExecution": [],
    }

    assert rule_retry_execution_options(plan) == {
        "schemaVersion": "run-job-execution-options.v1",
        "snakemake": {
            "schemaVersion": "snakemake-rule-rerun-options.v1",
            "rerunIncomplete": True,
            "forcerunRules": ["align"],
        },
    }


def test_rule_retry_execution_plan_blocks_without_selected_attempt() -> None:
    source = _rule_retry_plan()
    source["rules"][0]["attemptSelection"]["selected"] = False
    source["selectedAttemptCount"] = 0

    plan = build_rule_retry_execution_plan(source)

    assert plan["commandPreviewAvailable"] is False
    assert plan["reasonCode"] == "RULE_RETRY_NO_SELECTED_RULE_ATTEMPTS"
    assert plan["snakemakeOptions"]["argsPreview"] == []


def test_rule_retry_execution_plan_blocks_partial_attempt_selection() -> None:
    source = _rule_retry_plan()
    invalid = {
        **source["rules"][0],
        "runRuleId": "rr_report",
        "ruleName": "report",
        "stepId": "report",
        "runtimeStatusKey": "rule:report",
        "attemptSelection": {
            **source["rules"][0]["attemptSelection"],
            "selected": False,
            "reasonCode": "RULE_ATTEMPT_LEASE_GENERATION_MISSING",
        },
    }
    source["rules"] = [source["rules"][0], invalid]
    source["invalidatedRules"].append(invalid)
    source["selectedAttemptCount"] = 1

    plan = build_rule_retry_execution_plan(source)

    assert plan["commandPreviewAvailable"] is False
    assert plan["reasonCode"] == "RULE_RETRY_ATTEMPT_SELECTION_INCOMPLETE"
    assert plan["snakemakeOptions"]["argsPreview"] == []


def test_rule_retry_execution_plan_blocks_unsafe_forcerun_rule_name() -> None:
    source = _rule_retry_plan()
    source["rules"][0]["ruleName"] = "align;rm"

    plan = build_rule_retry_execution_plan(source)

    assert plan["commandPreviewAvailable"] is False
    assert plan["reasonCode"] == "SNAKEMAKE_FORCERUN_RULE_INVALID"
    assert plan["snakemakeOptions"]["forcerunRules"] == []


def test_rule_retry_execution_plan_blocks_graph_unmatched_rule_before_command_preview() -> None:
    source = _rule_retry_plan()
    source["rules"][0]["reasonCode"] = "WORKFLOW_GRAPH_RULE_UNMATCHED"

    plan = build_rule_retry_execution_plan(source)

    assert plan["commandPreviewAvailable"] is False
    assert plan["reasonCode"] == "WORKFLOW_GRAPH_RULE_UNMATCHED"
    assert plan["snakemakeOptions"]["argsPreview"] == []


def test_rule_retry_execution_plan_blocks_unsupported_source_schema() -> None:
    plan = build_rule_retry_execution_plan({"schemaVersion": "legacy-rule-retry-plan.v0"})

    assert plan["sourcePlanSchemaVersion"] == "legacy-rule-retry-plan.v0"
    assert plan["commandPreviewAvailable"] is False
    assert plan["reasonCode"] == "RULE_RETRY_PLAN_SCHEMA_UNSUPPORTED"


def test_rule_retry_execution_plan_blocks_when_source_plan_has_no_invalidation_plan() -> None:
    for reason_code in ("NO_FAILED_RULES", "WORKFLOW_REVISION_MISSING", "WORKFLOW_GRAPH_MISSING"):
        source = {
            "schemaVersion": "rule-retry-plan.v1",
            "runId": "run_rule_retry",
            "reasonCode": reason_code,
            "invalidationPlanAvailable": False,
            "blockedReasonCodes": [],
            "rules": [],
        }
        plan = build_rule_retry_execution_plan(source)
        assert plan["commandPreviewAvailable"] is False
        assert plan["reasonCode"] == reason_code
        assert plan["snakemakeOptions"]["argsPreview"] == []


def test_rule_retry_execution_plan_deduplicates_forcerun_rule_names() -> None:
    source = _rule_retry_plan()
    duplicate = {**source["rules"][0], "runRuleId": "rr_align_retry"}
    source["rules"] = [source["rules"][0], duplicate]
    source["selectedAttemptCount"] = 2

    plan = build_rule_retry_execution_plan(source)

    assert plan["commandPreviewAvailable"] is True
    assert plan["snakemakeOptions"]["forcerunRules"] == ["align"]
    assert plan["snakemakeOptions"]["argsPreview"] == ["--rerun-incomplete", "--forcerun", "align"]


def _rule_retry_plan() -> dict:
    selected_attempt = {
        "attemptId": "att_failed",
        "attemptNumber": 1,
        "leaseGeneration": 1,
        "status": "failed",
    }
    align = {
        "runRuleId": "rr_align",
        "ruleName": "align",
        "stepId": "align",
        "runtimeStatusKey": "rule:align",
        "reasonCode": "PARTIAL_RULE_RETRY_UNSUPPORTED",
        "selectedAttempt": selected_attempt,
        "attemptSelection": {
            "schemaVersion": "rule-attempt-selection.v1",
            "strategy": "latest_failed_rule_attempt",
            "selected": True,
            "reasonCode": "RULE_ATTEMPT_SELECTED_FOR_PLANNING",
            "attemptId": "att_failed",
            "leaseGeneration": 1,
        },
    }
    report = {
        "runRuleId": "rr_report",
        "ruleName": "report",
        "stepId": "report",
        "runtimeStatusKey": "rule:report",
    }
    return {
        "schemaVersion": "rule-retry-plan.v1",
        "runId": "run_rule_retry",
        "workflowRevisionId": "wfrev_rule_retry",
        "supported": False,
        "eligible": False,
        "eligibleNow": False,
        "executionEnabled": False,
        "executionReasonCode": "RULE_RETRY_EXECUTION_DISABLED",
        "selectedAttemptCount": 1,
        "invalidationPlanAvailable": True,
        "reasonCode": "PARTIAL_RULE_RETRY_UNSUPPORTED",
        "attemptSelection": {
            "schemaVersion": "rule-attempt-selection.v1",
            "strategy": "latest_failed_rule_attempt",
            "available": True,
            "selectedRuleCount": 1,
        },
        "cacheAdoptionBoundary": {"enabled": False, "reasonCode": "CACHE_ADOPTION_UNPROVEN"},
        "artifactAdoptionBoundary": {"enabled": False, "reasonCode": "ARTIFACT_ADOPTION_UNPROVEN"},
        "blockedReasonCodes": ["CACHE_ADOPTION_UNPROVEN", "ARTIFACT_ADOPTION_UNPROVEN"],
        "invalidatedRules": [align, report],
        "rules": [align],
    }


def _applied_output_invalidation_plan() -> dict:
    return {
        "schemaVersion": "rule-output-invalidation-plan.v1",
        "planHash": "a" * 64,
        "previewAvailable": True,
        "reasonCode": "OUTPUT_EDGE_INVALIDATION_ALREADY_APPLIED",
        "blockedReasonCodes": [],
        "outputInvalidationState": {
            "schemaVersion": "rule-output-invalidation-state.v1",
            "state": "applied",
            "appliedOutputEdgeCount": 1,
            "appliedLineageEdgeCount": 1,
            "evidenceEventCount": 1,
        },
    }


def _adopted_cache_restore_plan() -> dict:
    return {
        "schemaVersion": "rule-cache-restore-plan.v1",
        "reasonCode": "PER_RULE_CACHE_RESTORE_UNPROVEN",
        "outputCount": 1,
        "cacheHitCount": 1,
        "cacheMissCount": 0,
        "blockedReasonCodes": [],
        "redactionPolicy": {
            "cacheKeysExposed": False,
            "cacheKeyFingerprintsExposed": True,
            "keyPayloadsExposed": False,
            "storageUrisExposed": False,
            "pathsExposed": False,
        },
        "restorePinPolicy": {
            "reasonCode": "RESTORE_PIN_POLICY_APPLIED",
            "requiredPinCount": 1,
            "createdPinCount": 1,
        },
        "stagedFilePolicy": {
            "reasonCode": "STAGED_FILE_MATERIALIZATION_PIN_REQUIRED",
        },
        "finalOutputPromotionState": {
            "schemaVersion": "rule-cache-restore-final-output-promotion-state.v1",
            "state": "applied",
            "targetCount": 1,
            "promotedFinalOutputCount": 1,
            "adoptedCandidateOutputCount": 1,
        },
    }
