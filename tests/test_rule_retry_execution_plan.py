from __future__ import annotations

import pytest

from apps.remote_runner.execution_plan_hash import attach_plan_hash, stable_plan_hash
from apps.remote_runner.rule_partial_rerun_claim_preflight import build_rule_partial_rerun_claim_binding
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
    assert plan["activationReadiness"]["blockedCheckCount"] == 13
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
        "targetOutputKeys": [],
        "argsPreview": ["--rerun-incomplete", "--forcerun", "align"],
        "unsafeFlagsProhibited": ["--forceall", "--touch", "--ignore-incomplete"],
    }
    assert plan["postExecutionArtifactAdoption"] == {
        "mode": "scoped-candidate-output-adoption",
        "outputCount": 0,
        "finalizeRunOnAdoption": False,
        "runStateMutationAllowed": False,
        "pathExposed": False,
        "storageUriExposed": False,
    }
    assert plan["executorOrchestration"]["schemaVersion"] == "rerun-executor-orchestration.v1"
    assert plan["executorOrchestration"]["mode"] == "rule-partial-rerun"
    assert plan["executorOrchestration"]["contractReady"] is False
    assert plan["executorOrchestration"]["executorReady"] is False
    assert plan["executorOrchestration"]["launchPreflight"]["schemaVersion"] == "rule-partial-rerun-launch-preflight.v1"
    assert plan["executorOrchestration"]["launchPreflight"]["preflightReady"] is False
    assert plan["executorOrchestration"]["launchPreflight"]["launchReady"] is False
    assert plan["executorOrchestration"]["launchPreflight"]["executorStartAllowed"] is False
    assert plan["executorOrchestration"]["executionBoundary"]["schemaVersion"] == (
        "rule-partial-rerun-execution-boundary.v1"
    )
    assert plan["executorOrchestration"]["executionBoundary"]["boundaryReady"] is False
    assert plan["executorOrchestration"]["executionBoundary"]["finalizeRunAllowed"] is False
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
            "managedRoot": True,
            "directoryPresent": True,
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


def test_rule_retry_execution_plan_enables_mutation_after_all_activation_evidence_is_ready() -> None:
    plan = build_rule_retry_execution_plan(
        _rule_retry_plan(),
        output_invalidation_plan=_applied_output_invalidation_plan(),
        cache_restore_plan=_adopted_cache_restore_plan(),
        workdir_reuse_policy={
            "schemaVersion": "run-workdir-reuse-policy.v1",
            "workDirReusable": True,
            "managedRoot": True,
            "directoryPresent": True,
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
        partial_rerun_lifecycle=_ready_partial_rerun_lifecycle(),
        partial_rerun_output_closure=_ready_partial_rerun_output_closure(),
    )

    orchestration = plan["executorOrchestration"]
    readiness_checks = {item["name"]: item for item in plan["activationReadiness"]["checks"]}
    assert orchestration["contractReady"] is True
    assert orchestration["executorReady"] is True
    assert orchestration["reasonCode"] == "RULE_PARTIAL_RERUN_EXECUTOR_READY"
    assert orchestration["blockedReasonCodes"] == []
    assert orchestration["requiresBeforeExecution"] == []
    assert plan["blockedReasonCodes"] == []
    assert plan["requiresBeforeExecution"] == []
    assert orchestration["launchPreflightReady"] is True
    assert orchestration["launchReady"] is True
    assert orchestration["executionBoundaryReady"] is True
    execution_boundary = orchestration["executionBoundary"]
    assert execution_boundary["schemaVersion"] == "rule-partial-rerun-execution-boundary.v1"
    assert execution_boundary["boundaryReady"] is True
    assert execution_boundary["reasonCode"] == "RULE_PARTIAL_RERUN_EXECUTION_BOUNDARY_READY"
    assert execution_boundary["explicitTargetCount"] == 1
    assert execution_boundary["explicitTargetsPresent"] is True
    assert execution_boundary["scopedOutputCount"] == 1
    assert execution_boundary["postExecutionArtifactAdoptionMode"] == "scoped-candidate-output-adoption"
    assert execution_boundary["finalizeWouldCompleteRun"] is False
    assert execution_boundary["finalizeRunAllowed"] is False
    assert execution_boundary["blockedReasonCodes"] == []
    launch_preflight = orchestration["launchPreflight"]
    assert launch_preflight["schemaVersion"] == "rule-partial-rerun-launch-preflight.v1"
    assert launch_preflight["preflightReady"] is True
    assert launch_preflight["launchReady"] is True
    assert launch_preflight["mode"] == "operator-mutation-ready"
    assert launch_preflight["reasonCode"] == "RULE_PARTIAL_RERUN_LAUNCH_PREFLIGHT_READY"
    assert launch_preflight["preflightReasonCode"] == "RULE_PARTIAL_RERUN_LAUNCH_PREFLIGHT_READY"
    assert launch_preflight["terminalSourceAttemptReady"] is True
    assert launch_preflight["targetAttemptPresent"] is False
    assert launch_preflight["activeLeasePresent"] is False
    assert launch_preflight["workdirReady"] is True
    assert launch_preflight["snakemakeOptionsReady"] is True
    assert launch_preflight["unsafeFlagsAbsent"] is True
    assert launch_preflight["outputClosureReady"] is True
    assert launch_preflight["lifecycleContractReady"] is True
    assert launch_preflight["outputAdoptionScopeReady"] is True
    assert launch_preflight["outputAdoptionScope"]["outputKeys"] == ["bam"]
    assert launch_preflight["outputAdoptionScope"]["targetOutputKeys"] == ["bam"]
    assert launch_preflight["outputAdoptionScope"]["finalizeRunOnAdoption"] is False
    assert launch_preflight["outputAdoptionScopeOutputCount"] == 1
    assert launch_preflight["executionPlanHashRevalidationRequired"] is True
    assert launch_preflight["sourcePlanHashRevalidationRequired"] is True
    assert launch_preflight["outputAdoptionScopeRevalidationRequired"] is True
    assert launch_preflight["planHashCurrent"] is False
    assert launch_preflight["planHashMatches"] is False
    assert launch_preflight["executorStartAllowed"] is False
    assert launch_preflight["queueMutationAllowed"] is True
    assert launch_preflight["runStateMutationAllowed"] is True
    assert launch_preflight["pathExposed"] is False
    assert launch_preflight["storageUriExposed"] is False
    assert launch_preflight["blockedReasonCodes"] == []
    assert orchestration["queueMutationAllowed"] is True
    assert orchestration["runStateMutationAllowed"] is True
    assert orchestration["pathExposed"] is False
    assert readiness_checks["partialRerunLaunchPreflight"]["ready"] is True
    assert readiness_checks["partialRerunExecutionBoundary"]["ready"] is True
    assert readiness_checks["partialRerunExecutionBoundary"]["reasonCode"] == "READY"
    assert readiness_checks["partialRerunExecutor"]["ready"] is True
    assert readiness_checks["partialRerunExecutor"]["reasonCode"] == "READY"
    assert readiness_checks["partialRerunLifecycle"]["ready"] is True
    assert readiness_checks["partialOutputClosure"]["ready"] is True
    assert readiness_checks["publicMutation"]["ready"] is True
    assert readiness_checks["publicMutation"]["reasonCode"] == "READY"
    assert plan["executionEnabled"] is True
    assert plan["executionReasonCode"] == "RULE_RETRY_EXECUTION_ENABLED"
    assert plan["activationReadiness"]["executionReady"] is True


def test_rule_retry_execution_plan_propagates_lifecycle_redaction_to_readiness_and_orchestration() -> None:
    unsafe_lifecycle = {
        **_ready_partial_rerun_lifecycle(),
        "targetAttempt": {
            **_ready_partial_rerun_lifecycle()["targetAttempt"],
            "pathExposed": True,
        },
        "outputClosure": {
            **_ready_partial_rerun_lifecycle()["outputClosure"],
            "storageUriExposed": True,
        },
    }

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
            "unverifiedOutputCount": 0,
            "unsafeOutputCount": 0,
            "uncheckedOutputCount": 0,
            "pathExposed": False,
            "storageUriExposed": False,
        },
        partial_rerun_lifecycle=unsafe_lifecycle,
        partial_rerun_output_closure=_ready_partial_rerun_output_closure(),
    )

    checks = {item["name"]: item for item in plan["activationReadiness"]["checks"]}
    assert checks["partialRerunLifecycle"]["ready"] is False
    assert checks["partialRerunLifecycle"]["reasonCode"] == "RULE_PARTIAL_RERUN_LIFECYCLE_REDACTION_UNSAFE"
    assert plan["activationReadiness"]["redactionPolicy"]["pathsExposed"] is True
    assert plan["activationReadiness"]["redactionPolicy"]["storageUrisExposed"] is True
    assert plan["executorOrchestration"]["pathExposed"] is True
    assert plan["executorOrchestration"]["storageUriExposed"] is True
    assert "RULE_PARTIAL_RERUN_LIFECYCLE_REDACTION_UNSAFE" in plan["executorOrchestration"]["blockedReasonCodes"]


def test_rule_retry_execution_plan_propagates_output_closure_redaction_to_readiness_and_orchestration() -> None:
    unsafe_closure = {
        **_ready_partial_rerun_output_closure(),
        "unknownActiveOutputs": [
            {
                "portName": "unexpected",
                "pathExposed": True,
                "storageUriExposed": True,
            }
        ],
    }

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
            "unverifiedOutputCount": 0,
            "unsafeOutputCount": 0,
            "uncheckedOutputCount": 0,
            "pathExposed": False,
            "storageUriExposed": False,
        },
        partial_rerun_lifecycle=_ready_partial_rerun_lifecycle(),
        partial_rerun_output_closure=unsafe_closure,
    )

    checks = {item["name"]: item for item in plan["activationReadiness"]["checks"]}
    assert checks["partialOutputClosure"]["ready"] is False
    assert checks["partialOutputClosure"]["reasonCode"] == "RULE_PARTIAL_RERUN_OUTPUT_CLOSURE_REDACTION_UNSAFE"
    assert plan["activationReadiness"]["redactionPolicy"]["pathsExposed"] is True
    assert plan["activationReadiness"]["redactionPolicy"]["storageUrisExposed"] is True
    assert plan["executorOrchestration"]["pathExposed"] is True
    assert plan["executorOrchestration"]["storageUriExposed"] is True
    assert "RULE_PARTIAL_RERUN_OUTPUT_CLOSURE_REDACTION_UNSAFE" in plan["executorOrchestration"][
        "blockedReasonCodes"
    ]


def test_rule_retry_execution_options_refuses_disabled_preview_plan() -> None:
    plan = build_rule_retry_execution_plan(_rule_retry_plan())

    with pytest.raises(ValueError, match="RULE_RETRY_EXECUTION_DISABLED"):
        rule_retry_execution_options(plan)


def test_rule_retry_execution_options_materializes_enabled_plan() -> None:
    plan = _ready_enabled_rule_retry_execution_plan()
    options = rule_retry_execution_options(plan)

    expected_scope = {
        "schemaVersion": "rule-output-adoption-scope.v1",
        "mode": "rule-partial-rerun",
        "sourcePlanHash": plan["planHash"],
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
    assert options == {
        "schemaVersion": "run-job-execution-options.v1",
        "snakemake": {
            "schemaVersion": "snakemake-rule-rerun-options.v1",
            "rerunIncomplete": True,
            "forcerunRules": ["align"],
            "targetOutputKeys": ["bam"],
        },
        "outputAdoptionScope": expected_scope,
        "rulePartialRerunClaimBinding": build_rule_partial_rerun_claim_binding(expected_scope),
    }


def test_rule_retry_execution_options_refuses_enabled_plan_without_launch_preflight() -> None:
    plan = {
        **build_rule_retry_execution_plan(
            _rule_retry_plan(),
            cache_restore_plan=_adopted_cache_restore_plan(),
        ),
        "supported": True,
        "eligible": True,
        "eligibleNow": True,
        "executionEnabled": True,
        "blockedReasonCodes": [],
        "requiresBeforeExecution": [],
    }
    plan = attach_plan_hash(plan)

    with pytest.raises(ValueError, match="RULE_PARTIAL_RERUN_LAUNCH_PREFLIGHT_REQUIRED"):
        rule_retry_execution_options(plan)


def test_rule_retry_execution_options_refuses_enabled_plan_without_output_scope() -> None:
    plan = {
        **build_rule_retry_execution_plan(_rule_retry_plan()),
        "supported": True,
        "eligible": True,
        "eligibleNow": True,
        "executionEnabled": True,
        "blockedReasonCodes": [],
        "requiresBeforeExecution": [],
    }
    plan["executorOrchestration"] = {"launchPreflight": {"preflightReady": True}}
    plan = attach_plan_hash(plan)

    with pytest.raises(ValueError, match="RULE_RETRY_OUTPUT_ADOPTION_SCOPE_REQUIRED"):
        rule_retry_execution_options(plan)


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
        "rules": [
            {
                "ruleName": "align",
                "stepId": "align",
                "invalidationRole": "selected",
                "outputs": [
                    {
                        "artifactKey": "bam",
                        "stepId": "align",
                        "outputOrdinal": 1,
                        "cacheHit": True,
                    }
                ],
            }
        ],
    }


def _ready_partial_rerun_lifecycle() -> dict:
    return {
        "schemaVersion": "rule-partial-rerun-lifecycle.v1",
        "available": True,
        "mode": "terminal-queued-rule-rerun",
        "contractReady": True,
        "reasonCode": "RULE_PARTIAL_RERUN_LIFECYCLE_CONTRACT_READY",
        "blockedReasonCodes": [],
        "mutationReady": False,
        "queueMutationAllowed": False,
        "runStateMutationAllowed": False,
        "executorStartAllowed": False,
        "sourceAttempt": {
            "attemptPresent": True,
            "selectedAttemptPresent": True,
            "attemptId": "att_failed",
            "attemptNumber": 1,
            "leaseGeneration": 1,
            "selectedStatus": "failed",
            "attemptState": "failed",
            "leaseState": "failed",
            "leaseReleased": True,
            "selectedRuleCount": 1,
            "pathExposed": False,
        },
        "targetAttempt": {
            "creationMode": "next-worker-claim",
            "targetAttemptRequired": True,
            "activeLeaseRequiredBeforeMutation": False,
            "activeLeaseRequiredDuringExecution": True,
            "sourcePlanHashRevalidationRequired": True,
            "outputAdoptionScopeRevalidationRequired": True,
            "pathExposed": False,
        },
        "outputClosure": {
            "scopedOutputAdoptionRequired": True,
            "preservedOutputEdgesRequired": True,
            "allDeclaredOutputsRequiredBeforeFinalize": True,
            "unknownOutputHandling": "refuse",
            "pathExposed": False,
            "storageUriExposed": False,
        },
        "pathExposed": False,
        "storageUriExposed": False,
    }


def _ready_partial_rerun_output_closure() -> dict:
    return {
        "schemaVersion": "rule-partial-rerun-output-closure.v1",
        "available": True,
        "edgeClosureReady": True,
        "closureReady": True,
        "reasonCode": "RULE_PARTIAL_RERUN_OUTPUT_CLOSURE_READY",
        "blockedReasonCodes": [],
        "scopedOutputCount": 1,
        "adoptedScopedOutputCount": 1,
        "pendingScopedOutputCount": 0,
        "preservedRuleCount": 0,
        "preservedOutputEdgeCount": 0,
        "missingPreservedOutputEdgeCount": 0,
        "unknownActiveOutputEdgeCount": 0,
        "declaredOutputCount": 1,
        "checkedDeclaredOutputCount": 1,
        "verifiedDeclaredOutputCount": 1,
        "adoptedDeclaredOutputCount": 1,
        "missingDeclaredOutputCount": 0,
        "rerunRequiredDeclaredOutputCount": 0,
        "allDeclaredOutputsVerified": True,
        "declaredOutputAuditReasonCode": "OUTPUT_AUDIT_VERIFIED",
        "declaredOutputBlockedReasonCodes": [],
        "finalizeAllowed": False,
        "runStateMutationAllowed": False,
        "pathExposed": False,
        "storageUriExposed": False,
        "scopedOutputs": [],
        "preservedOutputs": [],
        "unknownActiveOutputs": [],
        "declaredOutputs": [],
    }


def _ready_enabled_rule_retry_execution_plan() -> dict:
    plan = build_rule_retry_execution_plan(
        _rule_retry_plan(),
        output_invalidation_plan=_applied_output_invalidation_plan(),
        cache_restore_plan=_adopted_cache_restore_plan(),
        workdir_reuse_policy={
            "schemaVersion": "run-workdir-reuse-policy.v1",
            "workDirReusable": True,
            "managedRoot": True,
            "directoryPresent": True,
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
        partial_rerun_lifecycle=_ready_partial_rerun_lifecycle(),
        partial_rerun_output_closure=_ready_partial_rerun_output_closure(),
    )
    return attach_plan_hash({
        **plan,
        "supported": True,
        "eligible": True,
        "eligibleNow": True,
        "executionEnabled": True,
        "blockedReasonCodes": [],
        "requiresBeforeExecution": [],
    })
