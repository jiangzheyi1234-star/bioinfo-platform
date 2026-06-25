from __future__ import annotations

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


def fetch_public_run_rules(cfg: RemoteRunnerConfig, run_id: str) -> dict[str, Any]:
    raw_rules = fetch_run_rules(cfg, run_id)
    results = fetch_run_results(cfg, run_id)
    artifacts = _dict_items(results.get("artifacts"))
    result_id = _canonical_result_id_for_run(run_id)
    return {
        "schemaVersion": RUN_RULES_PUBLIC_SCHEMA,
        "runId": run_id,
        "redactionPolicy": {
            "artifactPathsExposed": False,
            "storageUrisExposed": False,
            "commandSummaryExposed": False,
            "ruleInputsExposed": False,
            "ruleOutputsExposed": False,
            "ruleLogPathsExposed": False,
            "eventDetailsSanitized": True,
        },
        "items": [
            _public_rule(cfg, result_id=result_id, rule=rule, artifacts=artifacts)
            for rule in _dict_items(raw_rules.get("items"))
        ],
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
        "events": events,
        "logContext": build_rule_log_context(cfg, result_id=result_id, rule=rule, artifacts=artifacts),
    }


def _dict_items(value: Any) -> list[dict[str, Any]]:
    return [item for item in (value or []) if isinstance(item, dict)]


def _canonical_result_id_for_run(run_id: str) -> str:
    normalized = run_id.strip()
    return normalized if normalized.startswith("res_") else f"res_{normalized}"
