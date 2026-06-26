from __future__ import annotations

from typing import Any


RULE_PARTIAL_RERUN_LIFECYCLE_SCHEMA_VERSION = "rule-partial-rerun-lifecycle.v1"
RETRYABLE_TERMINAL_RUN_STATUSES = {"failed", "canceled", "cancelled"}
TERMINAL_JOB_STATES = {"completed", "failed", "cancelled", "canceled"}
RELEASED_LEASE_STATES = {"expired", "fenced", "failed", "canceled", "cancelled"}
TERMINAL_ATTEMPT_STATES = {"succeeded", "failed", "canceled", "cancelled", "fenced"}
READY_REASON = "RULE_PARTIAL_RERUN_LIFECYCLE_CONTRACT_READY"


def blocked_rule_partial_rerun_lifecycle(reason_code: str = "RULE_PARTIAL_RERUN_LIFECYCLE_UNAVAILABLE") -> dict[str, Any]:
    return _contract(
        mode="unavailable",
        source_attempt={},
        target_attempt={},
        output_closure={},
        blockers=[reason_code],
        active_lease_present=False,
    )


def build_rule_partial_rerun_lifecycle(
    *,
    run: dict[str, Any],
    job: dict[str, Any] | None,
    attempts: list[dict[str, Any]],
    current_lease: dict[str, Any] | None,
    active_lease: dict[str, Any] | None,
    rule_retry_plan: dict[str, Any],
    workdir_reuse_policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    selected_rules = _selected_rules(rule_retry_plan)
    selected_attempts = _selected_source_attempts(selected_rules)
    selected_attempt = selected_attempts[0] if selected_attempts else {}
    attempt = _attempt_for_selection(attempts, selected_attempt)
    lease_matches_source = _lease_matches_selection(current_lease, selected_attempt)
    current_lease_state = str(_dict_value(current_lease).get("state") or "").lower()
    source_lease_released = lease_matches_source and current_lease_state in RELEASED_LEASE_STATES
    active_lease_present = isinstance(active_lease, dict)
    run_status = str(run.get("status") or "").lower()
    job_state = str(_dict_value(job).get("state") or "").lower()
    mode = "active-attempt-repair" if active_lease_present else "terminal-queued-rule-rerun"

    blockers: list[str] = []
    if active_lease_present:
        blockers.append("ACTIVE_ATTEMPT_REPAIR_UNSUPPORTED")
    if len(selected_attempts) > 1:
        blockers.append("RULE_PARTIAL_RERUN_MULTI_SOURCE_ATTEMPTS_UNSUPPORTED")
    if not selected_attempt:
        blockers.append("RULE_PARTIAL_RERUN_SOURCE_ATTEMPT_REQUIRED")
    if attempt is None:
        blockers.append("RULE_PARTIAL_RERUN_SOURCE_ATTEMPT_NOT_FOUND")
    elif str(attempt.get("state") or "").lower() not in TERMINAL_ATTEMPT_STATES:
        blockers.append("RULE_PARTIAL_RERUN_SOURCE_ATTEMPT_NOT_TERMINAL")
    if run_status not in RETRYABLE_TERMINAL_RUN_STATUSES:
        blockers.append("RULE_PARTIAL_RERUN_RUN_NOT_RETRYABLE_TERMINAL")
    if job is None:
        blockers.append("RULE_PARTIAL_RERUN_JOB_NOT_FOUND")
    else:
        if job_state not in TERMINAL_JOB_STATES:
            blockers.append("RULE_PARTIAL_RERUN_JOB_NOT_TERMINAL")
        if _safe_int(job.get("maxAttempts")) - _safe_int(job.get("attemptCount")) <= 0:
            blockers.append("RULE_PARTIAL_RERUN_ATTEMPT_BUDGET_EXHAUSTED")
        if job.get("deadLetteredAt"):
            blockers.append("RULE_PARTIAL_RERUN_JOB_DEAD_LETTERED")
    if current_lease is None:
        blockers.append("RULE_PARTIAL_RERUN_SOURCE_LEASE_EVIDENCE_MISSING")
    elif not lease_matches_source:
        blockers.append("RULE_PARTIAL_RERUN_SOURCE_LEASE_MISMATCH")
    elif not source_lease_released:
        blockers.append("RULE_PARTIAL_RERUN_SOURCE_LEASE_NOT_RELEASED")
    if _dict_value(workdir_reuse_policy).get("workDirReusable") is not True:
        blockers.append("WORKDIR_REUSE_POLICY_UNPROVEN")

    source_attempt = {
        "attemptPresent": attempt is not None,
        "selectedAttemptPresent": bool(selected_attempt),
        "attemptId": str(selected_attempt.get("attemptId") or ""),
        "attemptNumber": selected_attempt.get("attemptNumber"),
        "leaseGeneration": selected_attempt.get("leaseGeneration"),
        "selectedStatus": str(selected_attempt.get("status") or ""),
        "attemptState": str(_dict_value(attempt).get("state") or ""),
        "leaseState": current_lease_state,
        "leaseMatchesSelectedAttempt": lease_matches_source,
        "leaseReleased": source_lease_released,
        "selectedRuleCount": len(selected_rules),
        "selectedSourceAttemptCount": len(selected_attempts),
        "pathExposed": False,
    }
    target_attempt = {
        "creationMode": "next-worker-claim",
        "targetAttemptRequired": True,
        "activeLeaseRequiredBeforeMutation": False,
        "activeLeaseRequiredDuringExecution": True,
        "sourcePlanHashRevalidationRequired": True,
        "outputAdoptionScopeRevalidationRequired": True,
        "pathExposed": False,
    }
    output_closure = {
        "scopedOutputAdoptionRequired": True,
        "preservedOutputEdgesRequired": True,
        "allDeclaredOutputsRequiredBeforeFinalize": True,
        "unknownOutputHandling": "refuse",
        "pathExposed": False,
        "storageUriExposed": False,
    }
    return _contract(
        mode=mode,
        source_attempt=source_attempt,
        target_attempt=target_attempt,
        output_closure=output_closure,
        blockers=blockers,
        active_lease_present=active_lease_present,
    )


def _contract(
    *,
    mode: str,
    source_attempt: dict[str, Any],
    target_attempt: dict[str, Any],
    output_closure: dict[str, Any],
    blockers: list[str],
    active_lease_present: bool,
) -> dict[str, Any]:
    unique_blockers = _unique_strings(blockers)
    contract_ready = not unique_blockers
    return {
        "schemaVersion": RULE_PARTIAL_RERUN_LIFECYCLE_SCHEMA_VERSION,
        "available": contract_ready or bool(source_attempt),
        "mode": mode,
        "contractReady": contract_ready,
        "reasonCode": READY_REASON if contract_ready else unique_blockers[0],
        "blockedReasonCodes": unique_blockers,
        "mutationReady": False,
        "queueMutationAllowed": False,
        "runStateMutationAllowed": False,
        "executorStartAllowed": False,
        "activeAttemptRepair": {
            "supported": False,
            "activeLeasePresent": active_lease_present,
            "reasonCode": "ACTIVE_ATTEMPT_REPAIR_UNSUPPORTED",
        },
        "terminalQueuedRerun": {
            "supported": True,
            "sourceAttemptRequiresReleasedLease": True,
            "targetAttemptCreatedByClaim": True,
            "sourcePlanHashRequired": True,
        },
        "sourceAttempt": source_attempt,
        "targetAttempt": target_attempt,
        "outputClosure": output_closure,
        "pathExposed": False,
        "storageUriExposed": False,
    }


def _selected_source_attempts(selected_rules: list[dict[str, Any]]) -> list[dict[str, Any]]:
    attempts: list[dict[str, Any]] = []
    seen: set[tuple[str, int]] = set()
    for rule in selected_rules:
        selected = rule.get("selectedAttempt")
        if isinstance(selected, dict):
            key = (
                str(selected.get("attemptId") or ""),
                _safe_int(selected.get("leaseGeneration")),
            )
            if key not in seen:
                attempts.append(selected)
                seen.add(key)
    return attempts


def _selected_rules(rule_retry_plan: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        rule
        for rule in rule_retry_plan.get("rules") or []
        if isinstance(rule, dict)
        and _dict_value(rule.get("attemptSelection")).get("selected") is True
    ]


def _attempt_for_selection(
    attempts: list[dict[str, Any]],
    selected_attempt: dict[str, Any],
) -> dict[str, Any] | None:
    selected_id = str(selected_attempt.get("attemptId") or "")
    selected_generation = _safe_int(selected_attempt.get("leaseGeneration"))
    if not selected_id or selected_generation <= 0:
        return None
    for attempt in attempts:
        if (
            isinstance(attempt, dict)
            and str(attempt.get("attemptId") or "") == selected_id
            and _safe_int(attempt.get("leaseGeneration")) == selected_generation
        ):
            return attempt
    return None


def _lease_matches_selection(current_lease: dict[str, Any] | None, selected_attempt: dict[str, Any]) -> bool:
    if not isinstance(current_lease, dict) or not selected_attempt:
        return False
    return (
        str(current_lease.get("attemptId") or "") == str(selected_attempt.get("attemptId") or "")
        and _safe_int(current_lease.get("leaseGeneration")) == _safe_int(selected_attempt.get("leaseGeneration"))
    )


def _dict_value(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _safe_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _unique_strings(items: list[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for item in items:
        value = str(item or "").strip()
        if value and value not in seen:
            unique.append(value)
            seen.add(value)
    return unique
