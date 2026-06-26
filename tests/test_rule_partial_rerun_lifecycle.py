from __future__ import annotations

from apps.remote_runner.rule_partial_rerun_lifecycle import build_rule_partial_rerun_lifecycle


def test_rule_partial_rerun_lifecycle_models_terminal_queued_retry_without_mutation() -> None:
    lifecycle = build_rule_partial_rerun_lifecycle(
        run={"status": "failed"},
        job={
            "state": "failed",
            "attemptCount": 1,
            "maxAttempts": 3,
            "deadLetteredAt": None,
        },
        attempts=[
            {
                "attemptId": "att_failed",
                "leaseGeneration": 1,
                "attemptNumber": 1,
                "state": "failed",
            }
        ],
        current_lease={
            "attemptId": "att_failed",
            "leaseGeneration": 1,
            "state": "failed",
        },
        active_lease=None,
        rule_retry_plan=_rule_retry_plan(),
        workdir_reuse_policy={"workDirReusable": True, "pathExposed": False},
    )

    assert lifecycle["schemaVersion"] == "rule-partial-rerun-lifecycle.v1"
    assert lifecycle["mode"] == "terminal-queued-rule-rerun"
    assert lifecycle["contractReady"] is True
    assert lifecycle["mutationReady"] is False
    assert lifecycle["queueMutationAllowed"] is False
    assert lifecycle["runStateMutationAllowed"] is False
    assert lifecycle["sourceAttempt"]["leaseReleased"] is True
    assert lifecycle["targetAttempt"]["creationMode"] == "next-worker-claim"
    assert lifecycle["targetAttempt"]["sourcePlanHashRevalidationRequired"] is True
    assert lifecycle["outputClosure"]["preservedOutputEdgesRequired"] is True
    assert lifecycle["pathExposed"] is False
    assert lifecycle["storageUriExposed"] is False


def test_rule_partial_rerun_lifecycle_blocks_active_attempt_repair_mode() -> None:
    lifecycle = build_rule_partial_rerun_lifecycle(
        run={"status": "failed"},
        job={"state": "failed", "attemptCount": 1, "maxAttempts": 3},
        attempts=[],
        current_lease={"state": "active"},
        active_lease={"state": "active", "attemptId": "att_active", "leaseGeneration": 2},
        rule_retry_plan=_rule_retry_plan(),
        workdir_reuse_policy={"workDirReusable": True, "pathExposed": False},
    )

    assert lifecycle["mode"] == "active-attempt-repair"
    assert lifecycle["contractReady"] is False
    assert "ACTIVE_ATTEMPT_REPAIR_UNSUPPORTED" in lifecycle["blockedReasonCodes"]
    assert lifecycle["activeAttemptRepair"] == {
        "supported": False,
        "activeLeasePresent": True,
        "reasonCode": "ACTIVE_ATTEMPT_REPAIR_UNSUPPORTED",
    }


def test_rule_partial_rerun_lifecycle_requires_lease_to_match_selected_source_attempt() -> None:
    lifecycle = build_rule_partial_rerun_lifecycle(
        run={"status": "failed"},
        job={"state": "failed", "attemptCount": 1, "maxAttempts": 3},
        attempts=[
            {
                "attemptId": "att_failed",
                "leaseGeneration": 1,
                "attemptNumber": 1,
                "state": "failed",
            }
        ],
        current_lease={
            "attemptId": "att_other",
            "leaseGeneration": 2,
            "state": "failed",
        },
        active_lease=None,
        rule_retry_plan=_rule_retry_plan(),
        workdir_reuse_policy={"workDirReusable": True, "pathExposed": False},
    )

    assert lifecycle["contractReady"] is False
    assert lifecycle["sourceAttempt"]["leaseMatchesSelectedAttempt"] is False
    assert lifecycle["sourceAttempt"]["leaseReleased"] is False
    assert "RULE_PARTIAL_RERUN_SOURCE_LEASE_MISMATCH" in lifecycle["blockedReasonCodes"]


def test_rule_partial_rerun_lifecycle_blocks_multiple_source_attempts() -> None:
    plan = _rule_retry_plan()
    second = {
        **plan["rules"][0],
        "runRuleId": "rr_report",
        "ruleName": "report",
        "selectedAttempt": {
            "attemptId": "att_report_failed",
            "attemptNumber": 2,
            "leaseGeneration": 2,
            "status": "failed",
        },
        "attemptSelection": {
            "schemaVersion": "rule-attempt-selection.v1",
            "selected": True,
            "attemptId": "att_report_failed",
            "leaseGeneration": 2,
        },
    }
    plan["rules"] = [plan["rules"][0], second]
    lifecycle = build_rule_partial_rerun_lifecycle(
        run={"status": "failed"},
        job={"state": "failed", "attemptCount": 2, "maxAttempts": 3},
        attempts=[
            {"attemptId": "att_failed", "leaseGeneration": 1, "attemptNumber": 1, "state": "failed"},
            {"attemptId": "att_report_failed", "leaseGeneration": 2, "attemptNumber": 2, "state": "failed"},
        ],
        current_lease={"attemptId": "att_failed", "leaseGeneration": 1, "state": "failed"},
        active_lease=None,
        rule_retry_plan=plan,
        workdir_reuse_policy={"workDirReusable": True, "pathExposed": False},
    )

    assert lifecycle["contractReady"] is False
    assert lifecycle["sourceAttempt"]["selectedSourceAttemptCount"] == 2
    assert "RULE_PARTIAL_RERUN_MULTI_SOURCE_ATTEMPTS_UNSUPPORTED" in lifecycle["blockedReasonCodes"]


def _rule_retry_plan() -> dict:
    selected_attempt = {
        "attemptId": "att_failed",
        "attemptNumber": 1,
        "leaseGeneration": 1,
        "status": "failed",
    }
    return {
        "schemaVersion": "rule-retry-plan.v1",
        "runId": "run_rule_retry",
        "workflowRevisionId": "wfrev_rule_retry",
        "selectedAttemptCount": 1,
        "invalidationPlanAvailable": True,
        "rules": [
            {
                "runRuleId": "rr_align",
                "ruleName": "align",
                "stepId": "align",
                "runtimeStatusKey": "rule:align",
                "selectedAttempt": selected_attempt,
                "attemptSelection": {
                    "schemaVersion": "rule-attempt-selection.v1",
                    "selected": True,
                    "attemptId": "att_failed",
                    "leaseGeneration": 1,
                },
            }
        ],
    }
