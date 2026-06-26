from __future__ import annotations

import json

from apps.remote_runner.execution_rule_retry_projection import rule_retry_blocked_payload


def test_rule_retry_blocked_payload_uses_public_projection_without_internal_fields() -> None:
    plan = {
        "schemaVersion": "rule-retry-execution-plan.v1",
        "planHash": "a" * 64,
        "runId": "run_public_projection",
        "workflowRevisionId": "wfr_secret",
        "supported": True,
        "eligible": True,
        "eligibleNow": True,
        "executionEnabled": True,
        "executionReasonCode": "RULE_RETRY_EXECUTION_ENABLED",
        "commandPreviewAvailable": True,
        "reasonCode": "RULE_RETRY_EXECUTION_ENABLED",
        "blockedReasonCodes": [],
        "requiresBeforeExecution": [],
        "selectedRules": [
            {
                "runRuleId": "rr_secret",
                "ruleName": "secret_rule_name",
                "stepId": "align",
                "selectedAttempt": {"attemptId": "attempt_secret"},
            }
        ],
        "rerunScope": {"ruleCount": 1, "rules": ["secret_rule_name"]},
        "cacheRestorePlan": {
            "schemaVersion": "rule-cache-restore-plan.v1",
            "planHash": "b" * 64,
            "available": True,
            "previewAvailable": True,
            "reasonCode": "READY",
            "outputCount": 1,
            "cacheHitCount": 1,
            "cacheMissCount": 0,
            "rules": [
                {
                    "ruleName": "secret_rule_name",
                    "outputs": [
                        {
                            "artifactKey": "secret-output-key",
                            "storageUri": "s3://private-bucket/secret-object",
                            "path": r"C:\private\secret-output.bam",
                        }
                    ],
                }
            ],
            "redactionPolicy": {
                "cacheKeysExposed": False,
                "cacheKeyFingerprintsExposed": True,
                "storageUrisExposed": False,
                "pathsExposed": False,
            },
            "restorePinPolicy": {
                "previewAvailable": True,
                "requiredPinCount": 1,
                "createdPinCount": 1,
                "cacheKeyExposed": False,
            },
            "stagedFilePolicy": {"enabled": True, "targetCount": 1, "pathExposed": False},
            "finalOutputPromotionState": {
                "targetCount": 1,
                "promotedFinalOutputCount": 1,
                "adoptedCandidateOutputCount": 1,
            },
            "partialRestoreExecutor": {"executorReady": True},
        },
        "outputInvalidationPlan": {
            "schemaVersion": "rule-output-invalidation-plan.v1",
            "outputEdgeSummary": {"selectedOutputEdgeCount": 1, "payloadDeletionAllowed": False},
            "outputInvalidationState": {"state": "applied", "appliedOutputEdgeCount": 1},
        },
        "incompleteOutputAudit": {
            "schemaVersion": "rule-output-audit.v1",
            "available": True,
            "expectedOutputCount": 1,
            "checkedOutputCount": 1,
            "verifiedOutputCount": 1,
            "adoptedOutputCount": 1,
            "unsafeOutputCount": 0,
            "uncheckedOutputCount": 0,
            "unverifiedOutputCount": 0,
            "pathExposed": False,
            "storageUriExposed": False,
            "outputs": [
                {
                    "outputKey": "secret-output-key",
                    "path": r"C:\private\secret-output.bam",
                    "storageUri": "s3://private-bucket/secret-output.bam",
                }
            ],
        },
        "partialRerunLifecycle": {
            "schemaVersion": "rule-partial-rerun-lifecycle.v1",
            "available": True,
            "mode": "terminal-queued-rerun",
            "contractReady": True,
            "mutationReady": True,
            "sourceAttempt": {
                "attemptPresent": True,
                "selectedAttemptPresent": True,
                "attemptId": "attempt_secret",
                "leaseReleased": True,
                "leaseGeneration": 7,
            },
            "targetAttempt": {
                "targetAttemptRequired": True,
                "creationMode": "next-worker-claim",
                "sourcePlanHashRevalidationRequired": True,
                "outputAdoptionScopeRevalidationRequired": True,
            },
            "outputClosure": {"preservedOutputEdgesRequired": True},
            "queueMutationAllowed": True,
            "runStateMutationAllowed": True,
            "pathExposed": False,
            "storageUriExposed": False,
        },
        "partialRerunOutputClosure": {
            "schemaVersion": "rule-partial-rerun-output-closure.v1",
            "available": True,
            "edgeClosureReady": True,
            "closureReady": True,
            "reasonCode": "READY",
            "scopedOutputCount": 1,
            "adoptedScopedOutputCount": 1,
            "declaredOutputCount": 1,
            "verifiedDeclaredOutputCount": 1,
            "adoptedDeclaredOutputCount": 1,
            "allDeclaredOutputsVerified": True,
            "finalizeAllowed": True,
            "runStateMutationAllowed": True,
            "pathExposed": False,
            "storageUriExposed": False,
            "scopedOutputs": [{"outputKey": "secret-output-key"}],
            "preservedOutputs": [{"runArtifactEdgeId": "edge_secret"}],
            "unknownActiveOutputs": [{"storageUri": "s3://private-bucket/unexpected"}],
            "declaredOutputs": [{"path": r"C:\private\secret-output.bam"}],
        },
        "executorOrchestration": {
            "schemaVersion": "rerun-executor-orchestration.v1",
            "mode": "rule-partial-rerun",
            "available": True,
            "contractReady": True,
            "executorReady": True,
            "reasonCode": "RULE_PARTIAL_RERUN_EXECUTOR_READY",
            "launchPreflight": {
                "schemaVersion": "rule-partial-rerun-launch-preflight.v1",
                "available": True,
                "preflightReady": True,
                "launchReady": True,
                "sourcePlanHash": "a" * 64,
                "outputAdoptionScope": {"outputKeys": ["secret-output-key"]},
            },
            "executionBoundary": {
                "schemaVersion": "rule-partial-rerun-execution-boundary.v1",
                "available": True,
                "boundaryReady": True,
                "explicitTargetCount": 1,
                "finalizeRunAllowed": True,
                "queueMutationAllowed": True,
                "runStateMutationAllowed": True,
            },
            "queueMutationAllowed": True,
            "runStateMutationAllowed": True,
            "pathExposed": False,
            "storageUriExposed": False,
        },
        "snakemakeOptions": {
            "schemaVersion": "snakemake-rule-rerun-options.v1",
            "rerunIncomplete": True,
            "forcerunRules": ["secret_rule_name"],
            "targetOutputKeys": ["secret-output-key"],
            "argsPreview": ["--rerun-incomplete", "--forcerun", "secret_rule_name"],
            "unsafeFlagsProhibited": ["--forceall"],
        },
        "activationReadiness": {
            "schemaVersion": "rule-retry-activation-readiness.v1",
            "runId": "run_public_projection",
            "workflowRevisionId": "wfr_secret",
            "executionReady": True,
            "executionEnabled": True,
            "reasonCode": "ACTIVATION_READY",
            "blockedReasonCodes": [],
            "readyCheckCount": 15,
            "blockedCheckCount": 0,
            "checks": [{"name": "publicMutation", "ready": True, "reasonCode": "READY"}],
            "summary": {"selectedRuleCount": 1, "executorReady": 1},
            "redactionPolicy": {"pathsExposed": False, "storageUrisExposed": False},
        },
        "executionOptions": {"raw": "do-not-leak"},
    }

    payload = rule_retry_blocked_payload(plan, "RULE_RETRY_EXECUTION_DISABLED")
    public_plan = payload["ruleRetryExecutionPlan"]

    assert public_plan["schemaVersion"] == "run-rule-retry-public-plan.v1"
    assert public_plan["planHash"] == plan["planHash"]
    assert public_plan["workflowRevisionIdPresent"] is True
    assert public_plan["executionEnabled"] is False
    assert public_plan["activationReadiness"]["executionReady"] is False
    assert public_plan["selectedRuleCount"] == 1
    assert public_plan["snakemakeOptions"]["forcerunRuleCount"] == 1
    assert public_plan["snakemakeOptions"]["targetOutputCount"] == 1
    assert public_plan["executorOrchestration"]["queueMutationAllowed"] is False
    assert public_plan["executorOrchestration"]["launchPreflight"]["queueMutationAllowed"] is False
    assert public_plan["executorOrchestration"]["executionBoundary"]["finalizeRunAllowed"] is False
    assert "rules" not in public_plan["cacheRestorePlan"]
    assert "selectedRules" not in public_plan
    assert "scopedOutputs" not in public_plan["partialRerunOutputClosure"]
    assert "argsPreview" not in public_plan["snakemakeOptions"]

    serialized = json.dumps(payload, sort_keys=True)
    for forbidden in (
        "secret_rule_name",
        "secret-output-key",
        "attempt_secret",
        "edge_secret",
        "do-not-leak",
        "s3://private-bucket",
        r"C:\private",
    ):
        assert forbidden not in serialized
    assert '"executionOptions":' not in serialized
