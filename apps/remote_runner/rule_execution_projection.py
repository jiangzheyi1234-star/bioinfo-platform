from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .config import RemoteRunnerConfig
from .rule_execution_storage import append_run_rule_event, fetch_run_rules, upsert_run_rule_state


def seed_run_rules_from_graph(
    cfg: RemoteRunnerConfig,
    *,
    run_id: str,
    attempt_id: str | None,
    lease_generation: int | None,
    attempt_number: int | None,
    graph: dict[str, Any] | None,
    occurred_at: str | None = None,
) -> None:
    if not _has_attempt_context(attempt_id, lease_generation):
        return
    for rule in _graph_rule_specs(graph):
        upsert_run_rule_state(
            cfg,
            run_id=run_id,
            rule_name=rule["ruleName"],
            step_id=rule["stepId"],
            runtime_status_key=rule["runtimeStatusKey"],
            status="planned",
            attempt_id=str(attempt_id),
            lease_generation=int(lease_generation),
            attempt_number=attempt_number,
            inputs=rule["inputs"],
            outputs=rule["outputs"],
            logs=rule["logs"],
            occurred_at=occurred_at,
        )
        append_run_rule_event(
            cfg,
            run_id=run_id,
            rule_name=rule["ruleName"],
            step_id=rule["stepId"],
            event_type="rule_planned",
            status="planned",
            attempt_id=str(attempt_id),
            lease_generation=int(lease_generation),
            attempt_number=attempt_number,
            message="Rule planned for this attempt.",
            occurred_at=occurred_at,
        )


def seed_run_rules_from_config(
    cfg: RemoteRunnerConfig,
    *,
    run_id: str,
    attempt_id: str | None,
    lease_generation: int | None,
    attempt_number: int | None,
    config_path: Path,
    occurred_at: str | None = None,
) -> None:
    raw = json.loads(config_path.read_text(encoding="utf-8"))
    workflow = raw.get("workflow") if isinstance(raw, dict) else {}
    graph = workflow.get("graph") if isinstance(workflow, dict) else None
    steps = workflow.get("steps") if isinstance(workflow, dict) else None
    if isinstance(graph, dict):
        seed_run_rules_from_graph(
            cfg,
            run_id=run_id,
            attempt_id=attempt_id,
            lease_generation=lease_generation,
            attempt_number=attempt_number,
            graph=graph,
            occurred_at=occurred_at,
        )
        return
    seed_run_rules_from_steps(
        cfg,
        run_id=run_id,
        attempt_id=attempt_id,
        lease_generation=lease_generation,
        attempt_number=attempt_number,
        steps=steps if isinstance(steps, list) else [],
        occurred_at=occurred_at,
    )


def seed_run_rules_from_steps(
    cfg: RemoteRunnerConfig,
    *,
    run_id: str,
    attempt_id: str | None,
    lease_generation: int | None,
    attempt_number: int | None,
    steps: list[Any],
    occurred_at: str | None = None,
) -> None:
    if not _has_attempt_context(attempt_id, lease_generation):
        return
    for step in steps:
        if not isinstance(step, dict):
            continue
        step_id = str(step.get("id") or step.get("stepId") or "").strip()
        rule_name = str(step.get("rule") or step_id).strip()
        if not rule_name:
            continue
        outputs = step.get("outputs") if isinstance(step.get("outputs"), dict) else {}
        upsert_run_rule_state(
            cfg,
            run_id=run_id,
            rule_name=rule_name,
            step_id=step_id,
            runtime_status_key=f"rule:{rule_name}",
            status="planned",
            attempt_id=str(attempt_id),
            lease_generation=int(lease_generation),
            attempt_number=attempt_number,
            inputs=_string_list(step.get("inputs")),
            outputs=[str(value) for value in outputs.values()],
            logs=_step_logs(step),
            occurred_at=occurred_at,
        )


def mark_run_rules_running(
    cfg: RemoteRunnerConfig,
    *,
    run_id: str,
    attempt_id: str | None,
    lease_generation: int | None,
    attempt_number: int | None,
    occurred_at: str | None = None,
) -> None:
    _mark_existing_rules(
        cfg,
        run_id=run_id,
        attempt_id=attempt_id,
        lease_generation=lease_generation,
        attempt_number=attempt_number,
        status="running",
        event_type="rule_started",
        message="Snakemake execution started.",
        occurred_at=occurred_at,
    )


def mark_run_rules_succeeded(
    cfg: RemoteRunnerConfig,
    *,
    run_id: str,
    attempt_id: str | None,
    lease_generation: int | None,
    attempt_number: int | None,
    occurred_at: str | None = None,
) -> None:
    _mark_existing_rules(
        cfg,
        run_id=run_id,
        attempt_id=attempt_id,
        lease_generation=lease_generation,
        attempt_number=attempt_number,
        status="succeeded",
        event_type="rule_finished",
        message="Snakemake execution completed.",
        exit_code=0,
        occurred_at=occurred_at,
    )


def mark_run_rules_cached(
    cfg: RemoteRunnerConfig,
    *,
    run_id: str,
    attempt_id: str | None,
    lease_generation: int | None,
    attempt_number: int | None,
    occurred_at: str | None = None,
) -> None:
    _mark_existing_rules(
        cfg,
        run_id=run_id,
        attempt_id=attempt_id,
        lease_generation=lease_generation,
        attempt_number=attempt_number,
        status="succeeded",
        event_type="rule_cache_hit",
        message="Rule satisfied from artifact cache.",
        exit_code=0,
        occurred_at=occurred_at,
    )


def mark_run_rules_failed(
    cfg: RemoteRunnerConfig,
    *,
    run_id: str,
    attempt_id: str | None,
    lease_generation: int | None,
    attempt_number: int | None,
    stderr: str,
    occurred_at: str | None = None,
) -> None:
    if not _has_attempt_context(attempt_id, lease_generation):
        return
    failed_names = _failed_rule_names(stderr)
    rules = _attempt_rules(cfg, run_id, str(attempt_id), int(lease_generation))
    for rule in rules:
        rule_name = str(rule.get("ruleName") or "")
        failed = not failed_names or rule_name in failed_names
        status = "failed" if failed else "blocked"
        message = _failure_message(stderr, rule_name) if failed else "Rule blocked after another rule failed."
        upsert_run_rule_state(
            cfg,
            run_id=run_id,
            rule_name=rule_name,
            step_id=str(rule.get("stepId") or ""),
            runtime_status_key=str(rule.get("runtimeStatusKey") or ""),
            status=status,
            attempt_id=str(attempt_id),
            lease_generation=int(lease_generation),
            attempt_number=attempt_number,
            exit_code=1 if failed else None,
            message=message,
            inputs=_string_list(rule.get("inputs")),
            outputs=_string_list(rule.get("outputs")),
            logs=_string_list(rule.get("logs")),
            occurred_at=occurred_at,
        )
        append_run_rule_event(
            cfg,
            run_id=run_id,
            rule_name=rule_name,
            step_id=str(rule.get("stepId") or ""),
            event_type="rule_failed" if failed else "rule_blocked",
            status=status,
            attempt_id=str(attempt_id),
            lease_generation=int(lease_generation),
            attempt_number=attempt_number,
            message=message,
            occurred_at=occurred_at,
        )


def _mark_existing_rules(
    cfg: RemoteRunnerConfig,
    *,
    run_id: str,
    attempt_id: str | None,
    lease_generation: int | None,
    attempt_number: int | None,
    status: str,
    event_type: str,
    message: str,
    exit_code: int | None = None,
    occurred_at: str | None = None,
) -> None:
    if not _has_attempt_context(attempt_id, lease_generation):
        return
    for rule in _attempt_rules(cfg, run_id, str(attempt_id), int(lease_generation)):
        rule_name = str(rule.get("ruleName") or "")
        upsert_run_rule_state(
            cfg,
            run_id=run_id,
            rule_name=rule_name,
            step_id=str(rule.get("stepId") or ""),
            runtime_status_key=str(rule.get("runtimeStatusKey") or ""),
            status=status,
            attempt_id=str(attempt_id),
            lease_generation=int(lease_generation),
            attempt_number=attempt_number,
            exit_code=exit_code,
            message=message,
            inputs=_string_list(rule.get("inputs")),
            outputs=_string_list(rule.get("outputs")),
            logs=_string_list(rule.get("logs")),
            occurred_at=occurred_at,
        )
        append_run_rule_event(
            cfg,
            run_id=run_id,
            rule_name=rule_name,
            step_id=str(rule.get("stepId") or ""),
            event_type=event_type,
            status=status,
            attempt_id=str(attempt_id),
            lease_generation=int(lease_generation),
            attempt_number=attempt_number,
            message=message,
            occurred_at=occurred_at,
        )


def _attempt_rules(cfg: RemoteRunnerConfig, run_id: str, attempt_id: str, lease_generation: int) -> list[dict[str, Any]]:
    return [
        rule
        for rule in fetch_run_rules(cfg, run_id).get("items", [])
        if rule.get("attemptId") == attempt_id and int(rule.get("leaseGeneration") or 0) == int(lease_generation)
    ]


def _graph_rule_specs(graph: dict[str, Any] | None) -> list[dict[str, Any]]:
    nodes = graph.get("nodes") if isinstance(graph, dict) else []
    specs: list[dict[str, Any]] = []
    for node in nodes if isinstance(nodes, list) else []:
        if not isinstance(node, dict) or str(node.get("kind") or "rule") != "rule":
            continue
        rule_name = str(node.get("label") or node.get("id") or "").strip()
        if not rule_name:
            continue
        specs.append(
            {
                "ruleName": rule_name,
                "stepId": str(node.get("id") or rule_name),
                "runtimeStatusKey": str(node.get("runtimeStatusKey") or f"rule:{rule_name}"),
                "inputs": _string_list(node.get("inputs")),
                "outputs": _string_list(node.get("outputs")),
                "logs": _string_list(node.get("logs")),
            }
        )
    return specs


def _failed_rule_names(stderr: str) -> set[str]:
    names: set[str] = set()
    for pattern in (r"Error in rule ([A-Za-z0-9_.-]+):", r"rule ([A-Za-z0-9_.-]+):"):
        names.update(match.group(1) for match in re.finditer(pattern, stderr or ""))
    return names


def _failure_message(stderr: str, rule_name: str) -> str:
    lines = [line.strip() for line in str(stderr or "").splitlines() if line.strip()]
    for index, line in enumerate(lines):
        if rule_name and rule_name in line:
            return line[:500]
        if "Error in rule" in line:
            return line[:500]
        if index > 20:
            break
    return "Snakemake execution failed."


def _step_logs(step: dict[str, Any]) -> list[str]:
    raw = step.get("log") or step.get("logs")
    if isinstance(raw, dict):
        return [str(value) for value in raw.values() if str(value).strip()]
    return _string_list(raw)


def _string_list(value: Any) -> list[str]:
    if isinstance(value, dict):
        return [str(item) for item in value.values() if str(item).strip()]
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _has_attempt_context(attempt_id: str | None, lease_generation: int | None) -> bool:
    return bool(str(attempt_id or "").strip() and lease_generation is not None)
