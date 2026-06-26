from __future__ import annotations

from apps.remote_runner.rule_partial_rerun_execution_boundary import build_rule_partial_rerun_execution_boundary


def test_rule_partial_rerun_execution_boundary_blocks_without_explicit_targets() -> None:
    boundary = build_rule_partial_rerun_execution_boundary(
        {
            "selectedRules": [{"ruleName": "align"}],
            "rerunScope": {"ruleCount": 2},
            "snakemakeOptions": {
                "schemaVersion": "snakemake-rule-rerun-options.v1",
                "rerunIncomplete": True,
                "forcerunRules": ["align"],
                "argsPreview": ["--rerun-incomplete", "--forcerun", "align"],
            },
            "cacheRestorePlan": {"outputCount": 1},
            "partialRerunLifecycle": {"targetAttempt": {"creationMode": "next-worker-claim"}},
            "partialRerunOutputClosure": {"declaredOutputCount": 1},
        }
    )

    assert boundary["schemaVersion"] == "rule-partial-rerun-execution-boundary.v1"
    assert boundary["boundaryReady"] is False
    assert boundary["reasonCode"] == "SNAKEMAKE_RULE_RERUN_EXPLICIT_TARGETS_REQUIRED"
    assert "RULE_PARTIAL_RERUN_FINALIZE_BOUNDARY_UNPROVEN" in boundary["blockedReasonCodes"]
    assert boundary["explicitTargetCount"] == 0
    assert boundary["scopedOutputCount"] == 1
    assert boundary["finalizeWouldCompleteRun"] is True
    assert boundary["finalizeRunAllowed"] is False
    assert boundary["executorStartAllowed"] is False
    assert boundary["queueMutationAllowed"] is False
    assert boundary["runStateMutationAllowed"] is False
    assert boundary["pathExposed"] is False
    assert boundary["storageUriExposed"] is False
