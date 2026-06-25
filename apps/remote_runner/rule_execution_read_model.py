from __future__ import annotations

from collections import Counter
from typing import Any

from .config import RemoteRunnerConfig
from .execution_query_storage import fetch_run_results
from .rule_execution_storage import fetch_run_rules
from .run_failure_locator_read_model import (
    build_rule_log_context,
    public_rule_event_summary,
    public_rule_message,
    safe_rule_wildcards,
)


RUN_RULES_PUBLIC_SCHEMA = "run-rules.v1"
RUN_RULES_SUMMARY_SCHEMA = "run-rules-summary.v1"


def fetch_public_run_rules(cfg: RemoteRunnerConfig, run_id: str) -> dict[str, Any]:
    raw_rules = fetch_run_rules(cfg, run_id)
    results = fetch_run_results(cfg, run_id)
    artifacts = _dict_items(results.get("artifacts"))
    result_id = _canonical_result_id_for_run(run_id)
    items = [
        _public_rule(cfg, result_id=result_id, rule=rule, artifacts=artifacts)
        for rule in _dict_items(raw_rules.get("items"))
    ]
    return {
        "schemaVersion": RUN_RULES_PUBLIC_SCHEMA,
        "runId": run_id,
        "summary": _public_summary(items),
        "redactionPolicy": {
            "artifactPathsExposed": False,
            "storageUrisExposed": False,
            "commandSummaryExposed": False,
            "ruleInputsExposed": False,
            "ruleOutputsExposed": False,
            "ruleLogPathsExposed": False,
            "eventDetailsSanitized": True,
            "sourceLocationsSanitized": True,
        },
        "items": items,
    }


def _public_summary(rules: list[dict[str, Any]]) -> dict[str, Any]:
    statuses = Counter(_status_value(rule.get("status")) for rule in rules)
    log_contexts = [_dict_value(rule.get("logContext")) for rule in rules]
    log_statuses = Counter(_status_value(context.get("status")) for context in log_contexts)
    log_reasons = Counter(_reason_value(context.get("reasonCode")) for context in log_contexts)
    return {
        "schemaVersion": RUN_RULES_SUMMARY_SCHEMA,
        "ruleCount": len(rules),
        "ruleEventCount": sum(len(_list_items(rule.get("events"))) for rule in rules),
        "statusCounts": dict(sorted(statuses.items())),
        "failedRuleCount": sum(_status_value(rule.get("status")) in {"failed", "error"} for rule in rules),
        "runningRuleCount": sum(_status_value(rule.get("status")) in {"running", "started"} for rule in rules),
        "blockedRuleCount": sum(_status_value(rule.get("status")) == "blocked" for rule in rules),
        "rulesWithAttemptMetadata": sum(bool(rule.get("attemptId") or rule.get("attemptNumber")) for rule in rules),
        "inputReferenceCount": sum(_safe_int(rule.get("inputCount")) for rule in rules),
        "outputReferenceCount": sum(_safe_int(rule.get("outputCount")) for rule in rules),
        "logReferenceCount": sum(_safe_int(rule.get("logReferenceCount")) for rule in rules),
        "rulesWithLogReferences": sum(_safe_int(rule.get("logReferenceCount")) > 0 for rule in rules),
        "rulesWithAvailableLogEvidence": sum(_status_value(context.get("status")) == "available" for context in log_contexts),
        "rulesWithPathOnlyLogEvidence": sum(_reason_value(context.get("reasonCode")) == "PATH_REFERENCE_ONLY" for context in log_contexts),
        "rulesWithUnavailableLogEvidence": sum(_status_value(context.get("status")) == "unavailable" for context in log_contexts),
        "logEvidenceStatusCounts": dict(sorted(log_statuses.items())),
        "logEvidenceReasonCodes": dict(sorted(log_reasons.items())),
    }


def _public_rule(
    cfg: RemoteRunnerConfig,
    *,
    result_id: str,
    rule: dict[str, Any],
    artifacts: list[dict[str, Any]],
) -> dict[str, Any]:
    events = [
        summary
        for summary in (public_rule_event_summary(event) for event in _dict_items(rule.get("events")))
        if summary is not None
    ]
    source_location = _latest_source_location(events)
    return {
        "runRuleId": rule.get("runRuleId"),
        "runId": rule.get("runId"),
        "ruleName": rule.get("ruleName"),
        "stepId": rule.get("stepId"),
        "runtimeStatusKey": rule.get("runtimeStatusKey"),
        "status": rule.get("status"),
        "attemptId": rule.get("attemptId"),
        "leaseGeneration": rule.get("leaseGeneration"),
        "attemptNumber": rule.get("attemptNumber"),
        "startedAt": rule.get("startedAt"),
        "finishedAt": rule.get("finishedAt"),
        "exitCode": rule.get("exitCode"),
        "message": public_rule_message(rule.get("message")),
        "inputCount": len(list(rule.get("inputs") or [])),
        "outputCount": len(list(rule.get("outputs") or [])),
        "logReferenceCount": len(list(rule.get("logs") or [])),
        "wildcards": safe_rule_wildcards(rule.get("wildcards")),
        "updatedAt": rule.get("updatedAt"),
        "sourceLocation": source_location,
        "events": events,
        "logContext": build_rule_log_context(cfg, result_id=result_id, rule=rule, artifacts=artifacts),
    }


def _latest_source_location(events: list[dict[str, Any]]) -> dict[str, Any] | None:
    for event in reversed(events):
        source_location = event.get("sourceLocation")
        if isinstance(source_location, dict):
            return source_location
    return None


def _dict_items(value: Any) -> list[dict[str, Any]]:
    return [item for item in (value or []) if isinstance(item, dict)]


def _dict_value(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list_items(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _safe_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _status_value(value: Any) -> str:
    return (str(value or "unknown").strip() or "unknown").lower()


def _reason_value(value: Any) -> str:
    return str(value or "unknown").strip() or "unknown"


def _canonical_result_id_for_run(run_id: str) -> str:
    normalized = run_id.strip()
    return normalized if normalized.startswith("res_") else f"res_{normalized}"
