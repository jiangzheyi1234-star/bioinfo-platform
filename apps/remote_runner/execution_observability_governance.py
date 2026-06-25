from __future__ import annotations

from collections import Counter
from typing import Any

from .config import RemoteRunnerConfig
from .governance_audit import record_governance_audit_event


def record_run_events_read_audit(cfg: RemoteRunnerConfig, run_id: str, events: list[dict[str, Any]]) -> None:
    event_types = Counter(str(item.get("eventType") or "unknown") for item in events if isinstance(item, dict))
    record_governance_audit_event(
        cfg,
        action="run.events.read",
        actor=_actor(cfg),
        subject_kind="run_events",
        subject_id=run_id,
        details={
            "returnedCount": len(events),
            "eventTypes": dict(sorted(event_types.items())),
        },
    )


def record_run_execution_context_read_audit(
    cfg: RemoteRunnerConfig,
    run_id: str,
    context: dict[str, Any],
) -> None:
    attempts = _list_value(context.get("attempts"))
    rule_retry_plan = _dict_value(context.get("ruleRetryPlan"))
    rule_retry_execution_plan = _dict_value(context.get("ruleRetryExecutionPlan"))
    record_governance_audit_event(
        cfg,
        action="run.execution_context.read",
        actor=_actor(cfg),
        subject_kind="run_execution_context",
        subject_id=run_id,
        details={
            "hasJob": isinstance(context.get("job"), dict),
            "attemptCount": len(attempts),
            "activeLeasePresent": isinstance(context.get("activeLease"), dict),
            "retryEligible": bool(_dict_value(context.get("retryEligibility")).get("eligible")),
            "retryEligibleNow": bool(_dict_value(context.get("retryEligibility")).get("eligibleNow")),
            "resumeSupported": bool(context.get("resumeSupported")),
            "ruleRetryFailedRuleCount": _safe_int(rule_retry_plan.get("failedRuleCount")),
            "ruleRetrySelectedAttemptCount": _safe_int(rule_retry_plan.get("selectedAttemptCount")),
            "ruleRetryExecutionEnabled": bool(rule_retry_execution_plan.get("executionEnabled")),
        },
    )


def record_run_attempts_read_audit(cfg: RemoteRunnerConfig, run_id: str, attempts_model: dict[str, Any]) -> None:
    summary = _dict_value(attempts_model.get("summary"))
    record_governance_audit_event(
        cfg,
        action="run.attempts.read",
        actor=_actor(cfg),
        subject_kind="run_attempts",
        subject_id=run_id,
        details={
            "attemptCount": _safe_int(summary.get("attemptCount")),
            "slotCount": _safe_int(summary.get("slotCount")),
            "activeLeasePresent": bool(summary.get("activeLeasePresent")),
            "attemptStates": _string_int_map(summary.get("attemptsByState")),
            "slotStates": _string_int_map(summary.get("slotsByState")),
        },
    )


def record_run_logs_read_audit(
    cfg: RemoteRunnerConfig,
    run_id: str,
    *,
    stream: str,
    cursor: str | None,
    log_lines: dict[str, Any],
) -> None:
    record_governance_audit_event(
        cfg,
        action="run.logs.read",
        actor=_actor(cfg),
        subject_kind="run_logs",
        subject_id=run_id,
        details={
            "stream": str(stream or ""),
            "cursorProvided": bool(str(cursor or "").strip()),
            "returnedLineCount": len(_list_value(log_lines.get("lines"))),
            "nextCursorProvided": bool(str(log_lines.get("nextCursor") or "").strip()),
        },
    )


def record_run_rules_read_audit(cfg: RemoteRunnerConfig, run_id: str, rules: dict[str, Any]) -> None:
    items = _list_value(rules.get("items"))
    statuses = Counter(str(item.get("status") or "unknown") for item in items if isinstance(item, dict))
    event_count = sum(len(_list_value(item.get("events"))) for item in items if isinstance(item, dict))
    log_contexts = [_dict_value(item.get("logContext")) for item in items if isinstance(item, dict)]
    log_reasons = Counter(str(context.get("reasonCode") or "unknown") for context in log_contexts)
    log_statuses = Counter(str(context.get("status") or "unknown") for context in log_contexts)
    rules_with_source_locations = sum(
        isinstance(item, dict) and isinstance(item.get("sourceLocation"), dict)
        for item in items
    )
    record_governance_audit_event(
        cfg,
        action="run.rules.read",
        actor=_actor(cfg),
        subject_kind="run_rules",
        subject_id=run_id,
        details={
            "ruleCount": len(items),
            "ruleEventCount": event_count,
            "ruleStatuses": dict(sorted(statuses.items())),
            "rulesWithLogReferences": sum(_safe_int(item.get("logReferenceCount")) > 0 for item in items if isinstance(item, dict)),
            "rulesWithSourceLocations": rules_with_source_locations,
            "sourceLocationsSanitized": bool(_dict_value(rules.get("redactionPolicy")).get("sourceLocationsSanitized")),
            "ruleLogStatuses": dict(sorted(log_statuses.items())),
            "ruleLogReasonCodes": dict(sorted(log_reasons.items())),
        },
    )


def record_run_failure_locator_read_audit(cfg: RemoteRunnerConfig, run_id: str, locator: dict[str, Any]) -> None:
    log_context = _dict_value(locator.get("logContext"))
    rule_log_context = _dict_value(locator.get("ruleLogContext"))
    artifact_context = _dict_value(locator.get("artifactContext"))
    failed_rule = _dict_value(locator.get("failedRule"))
    record_governance_audit_event(
        cfg,
        action="run.failure_locator.read",
        actor=_actor(cfg),
        subject_kind="run_failure_locator",
        subject_id=run_id,
        details={
            "available": bool(locator.get("available")),
            "reasonCode": str(locator.get("reasonCode") or ""),
            "failedRulePresent": isinstance(locator.get("failedRule"), dict),
            "sourceLocationPresent": isinstance(failed_rule.get("sourceLocation"), dict),
            "sourceLocationsSanitized": bool(_dict_value(locator.get("redactionPolicy")).get("sourceLocationsSanitized")),
            "stderrLineCount": _safe_int(log_context.get("stderrLineCount")),
            "stderrTailLineCount": len(_list_value(log_context.get("stderrTail"))),
            "ruleLogStatus": str(rule_log_context.get("status") or ""),
            "ruleLogReasonCode": str(rule_log_context.get("reasonCode") or ""),
            "relatedArtifactCount": _safe_int(artifact_context.get("relatedArtifactCount")),
        },
    )


def _actor(cfg: RemoteRunnerConfig) -> str:
    return str(cfg.api_token_actor or "").strip() or "remote-runner-api"


def _dict_value(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list_value(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _string_int_map(value: Any) -> dict[str, int]:
    if not isinstance(value, dict):
        return {}
    return {str(key): _safe_int(item) for key, item in sorted(value.items())}


def _safe_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0
