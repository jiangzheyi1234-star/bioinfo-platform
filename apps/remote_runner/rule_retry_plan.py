from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Any

from .config import RemoteRunnerConfig
from .rule_execution_storage import fetch_run_rules
from .workflow_revision_storage import fetch_workflow_revision


RULE_RETRY_PLAN_SCHEMA_VERSION = "rule-retry-plan.v1"
RULE_ATTEMPT_SELECTION_SCHEMA_VERSION = "rule-attempt-selection.v1"
RULE_ADOPTION_BOUNDARY_SCHEMA_VERSION = "rule-adoption-boundary.v1"
FAILED_RULE_STATUSES = {"failed", "error"}
PARTIAL_RETRY_UNSUPPORTED = "PARTIAL_RULE_RETRY_UNSUPPORTED"


@dataclass(frozen=True)
class _GraphNode:
    node_id: str
    keys: frozenset[str]
    is_rule: bool


@dataclass(frozen=True)
class _GraphIndex:
    nodes: dict[str, _GraphNode]
    adjacency: dict[str, list[str]]
    order: dict[str, int]


def build_rule_retry_plan(cfg: RemoteRunnerConfig, run: dict[str, Any]) -> dict[str, Any]:
    run_id = str(run.get("runId") or "").strip()
    workflow_revision_id = str(run.get("workflowRevisionId") or "").strip()
    rules = list(fetch_run_rules(cfg, run_id).get("items", []))
    latest_rules = _latest_rules(rules)
    failed_rules = [_rule for _rule in latest_rules if _is_failed_rule(_rule)]
    selected_attempt_count = _selected_attempt_count(failed_rules)
    base = {
        "schemaVersion": RULE_RETRY_PLAN_SCHEMA_VERSION,
        "runId": run_id,
        "workflowRevisionId": workflow_revision_id or None,
        "supported": False,
        "eligible": False,
        "eligibleNow": False,
        "executionEnabled": False,
        "executionReasonCode": "RULE_RETRY_EXECUTION_DISABLED",
        "selectionMode": "failed-rule-attempts",
        "ruleCount": len(rules),
        "failedRuleCount": len(failed_rules),
        "selectedAttemptCount": selected_attempt_count,
        "invalidationPlanAvailable": False,
        "attemptSelection": _attempt_selection_summary(failed_rules),
        "cacheAdoptionBoundary": _adoption_boundary("cache"),
        "artifactAdoptionBoundary": _adoption_boundary("artifact"),
        "preservedRules": [],
        "invalidatedRules": [],
        "adoptedArtifacts": [],
        "adoptedCacheEntries": [],
        "blockedReasonCodes": ["CACHE_ADOPTION_UNPROVEN", "ARTIFACT_ADOPTION_UNPROVEN"],
        "rules": [],
    }
    if not failed_rules:
        return {
            **base,
            "reasonCode": "NO_FAILED_RULES",
            "message": "No failed rule is available for rule-level retry planning.",
        }
    if not workflow_revision_id:
        return _unsupported(base, "WORKFLOW_REVISION_MISSING")
    workflow_revision = fetch_workflow_revision(cfg, workflow_revision_id)
    if workflow_revision is None:
        return _unsupported(base, "WORKFLOW_REVISION_NOT_FOUND")
    graph = _workflow_graph(workflow_revision.get("graphSnapshot"))
    if graph is None:
        return _unsupported(base, "WORKFLOW_GRAPH_MISSING")
    try:
        graph_index = _build_graph_index(graph)
    except ValueError as exc:
        return _unsupported(base, str(exc))
    rule_by_key = _rules_by_key(latest_rules)
    planned_rules = [
        _failed_rule_plan(rule, graph_index=graph_index, rule_by_key=rule_by_key)
        for rule in failed_rules
    ]
    invalidated_rules = _invalidated_rules(planned_rules)
    return {
        **base,
        "invalidationPlanAvailable": True,
        "attemptSelection": _attempt_selection_summary(planned_rules),
        "selectedAttemptCount": _selected_attempt_count(planned_rules),
        "preservedRules": _preserved_rules(latest_rules, invalidated_rules),
        "invalidatedRules": invalidated_rules,
        "reasonCode": PARTIAL_RETRY_UNSUPPORTED,
        "message": "Rule-level retry is blocked until rerun execution can invalidate downstream outputs and adopt cache safely.",
        "rules": planned_rules,
    }


def _unsupported(base: dict[str, Any], reason_code: str) -> dict[str, Any]:
    return {
        **base,
        "reasonCode": reason_code,
        "message": f"Rule-level retry invalidation planning is unavailable: {reason_code}.",
    }


def _failed_rule_plan(
    rule: dict[str, Any],
    *,
    graph_index: _GraphIndex,
    rule_by_key: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    start_node = _node_for_rule(rule, graph_index)
    downstream_rules = (
        _downstream_rules(start_node.node_id, graph_index=graph_index, rule_by_key=rule_by_key)
        if start_node is not None
        else []
    )
    selected_rule = _rule_ref(rule)
    rerun_scope = [selected_rule, *downstream_rules]
    return {
        **selected_rule,
        "eligible": False,
        "eligibleNow": False,
        "reasonCode": PARTIAL_RETRY_UNSUPPORTED if start_node is not None else "WORKFLOW_GRAPH_RULE_UNMATCHED",
        "selectionReasonCode": _selection_reason_code(rule),
        "selectedAttempt": _selected_attempt(rule),
        "invalidatesOwnOutputs": True,
        "attemptSelection": _attempt_selection(rule),
        "adoptionBoundary": _rule_adoption_boundary(),
        "downstreamInvalidation": {
            "ruleCount": len(downstream_rules),
            "rules": downstream_rules,
        },
        "rerunScope": {
            "ruleCount": len(rerun_scope),
            "rules": rerun_scope,
        },
    }


def _attempt_selection_summary(rules: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schemaVersion": RULE_ATTEMPT_SELECTION_SCHEMA_VERSION,
        "strategy": "latest_failed_rule_attempt",
        "available": bool(rules),
        "selectedRuleCount": len(rules),
        "reasonCode": "FAILED_RULE_ATTEMPT_SELECTION_AVAILABLE" if rules else "NO_FAILED_RULES",
    }


def _attempt_selection(rule: dict[str, Any]) -> dict[str, Any]:
    selected = bool(str(rule.get("attemptId") or "").strip() and rule.get("leaseGeneration") is not None)
    return {
        "schemaVersion": RULE_ATTEMPT_SELECTION_SCHEMA_VERSION,
        "strategy": "latest_failed_rule_attempt",
        "selected": selected,
        "reasonCode": _selection_reason_code(rule),
        "runRuleId": rule.get("runRuleId"),
        "ruleName": rule.get("ruleName"),
        "stepId": rule.get("stepId"),
        "runtimeStatusKey": rule.get("runtimeStatusKey"),
        "status": rule.get("status"),
        "attemptId": rule.get("attemptId"),
        "leaseGeneration": rule.get("leaseGeneration"),
        "attemptNumber": rule.get("attemptNumber"),
    }


def _selected_attempt(rule: dict[str, Any]) -> dict[str, Any]:
    return {
        "attemptId": rule.get("attemptId"),
        "attemptNumber": rule.get("attemptNumber"),
        "leaseGeneration": rule.get("leaseGeneration"),
        "status": rule.get("status"),
    }


def _selection_reason_code(rule: dict[str, Any]) -> str:
    if not str(rule.get("attemptId") or "").strip():
        return "RULE_ATTEMPT_ID_MISSING"
    if rule.get("leaseGeneration") is None:
        return "RULE_ATTEMPT_LEASE_GENERATION_MISSING"
    return "RULE_ATTEMPT_SELECTED_FOR_PLANNING"


def _adoption_boundary(kind: str) -> dict[str, Any]:
    cache = kind == "cache"
    return {
        "schemaVersion": RULE_ADOPTION_BOUNDARY_SCHEMA_VERSION,
        "kind": "cache" if cache else "artifact",
        "enabled": False,
        "adoptedArtifacts": [],
        "adoptedCacheEntries": [],
        "reasonCode": "CACHE_ADOPTION_UNPROVEN" if cache else "ARTIFACT_ADOPTION_UNPROVEN",
        "message": (
            "Per-rule cache adoption is disabled until exact cache verification and staged-file policy controls are proven."
            if cache
            else "Per-rule artifact adoption is disabled until selected/downstream output invalidation is proven."
        ),
        "requires": [
            "exact_workflow_revision",
            "verified_payload_checksum",
            "downstream_invalidation",
            "staged_file_policy",
        ],
    }


def _rule_adoption_boundary() -> dict[str, Any]:
    return {
        "cacheAdoptionAllowed": False,
        "artifactAdoptionAllowed": False,
        "upstreamArtifactsPreserved": True,
        "downstreamArtifactsInvalidated": True,
        "adoptedArtifacts": [],
        "adoptedCacheEntries": [],
        "blockedReasonCodes": [
            "DOWNSTREAM_INVALIDATION_REQUIRED",
            "SELECTED_RULE_OUTPUTS_REQUIRE_INVALIDATION",
            "CACHE_ADOPTION_UNPROVEN",
            "ARTIFACT_ADOPTION_UNPROVEN",
            "UPSTREAM_ADOPTION_BOUNDARY_READ_ONLY",
        ],
    }


def _selected_attempt_count(rules: list[dict[str, Any]]) -> int:
    return sum(1 for rule in rules if str(rule.get("attemptId") or "").strip() and rule.get("leaseGeneration") is not None)


def _invalidated_rules(planned_rules: list[dict[str, Any]]) -> list[dict[str, Any]]:
    invalidated: list[dict[str, Any]] = []
    seen: set[str] = set()
    for rule in planned_rules:
        for ref in (rule.get("rerunScope") or {}).get("rules", []):
            key = _rule_ref_identity(ref)
            if key and key not in seen:
                invalidated.append(ref)
                seen.add(key)
    return invalidated


def _preserved_rules(latest_rules: list[dict[str, Any]], invalidated_rules: list[dict[str, Any]]) -> list[dict[str, Any]]:
    invalidated_keys = {_rule_ref_identity(rule) for rule in invalidated_rules}
    return [_rule_ref(rule) for rule in latest_rules if _rule_ref_identity(rule) not in invalidated_keys]


def _downstream_rules(
    node_id: str,
    *,
    graph_index: _GraphIndex,
    rule_by_key: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    downstream_node_ids = _transitive_downstream(node_id, graph_index.adjacency)
    downstream_nodes = [
        graph_index.nodes[item]
        for item in downstream_node_ids
        if item in graph_index.nodes and graph_index.nodes[item].is_rule
    ]
    downstream_nodes.sort(key=lambda item: graph_index.order.get(item.node_id, 0))
    refs: list[dict[str, Any]] = []
    seen: set[str] = set()
    for node in downstream_nodes:
        rule = _rule_for_node(node, rule_by_key)
        if rule is None:
            continue
        key = str(rule.get("runRuleId") or rule.get("ruleName") or "").strip()
        if key and key not in seen:
            refs.append(_rule_ref(rule))
            seen.add(key)
    return refs


def _transitive_downstream(node_id: str, adjacency: dict[str, list[str]]) -> list[str]:
    visited: set[str] = set()
    ordered: list[str] = []
    queue: deque[str] = deque(adjacency.get(node_id, []))
    while queue:
        current = queue.popleft()
        if current in visited:
            continue
        visited.add(current)
        ordered.append(current)
        queue.extend(adjacency.get(current, []))
    return ordered


def _workflow_graph(snapshot: Any) -> dict[str, Any] | None:
    if not isinstance(snapshot, dict):
        return None
    direct = _graph_if_present(snapshot)
    if direct is not None:
        return direct
    run_spec = snapshot.get("runSpec")
    workflow = run_spec.get("workflow") if isinstance(run_spec, dict) else None
    if not isinstance(workflow, dict):
        return None
    nested = workflow.get("graph")
    if isinstance(nested, dict):
        nested_graph = _graph_if_present(nested)
        if nested_graph is not None:
            return nested_graph
    return _graph_if_present(workflow)


def _graph_if_present(value: dict[str, Any]) -> dict[str, Any] | None:
    nodes = value.get("nodes")
    edges = value.get("edges")
    if isinstance(nodes, list) or isinstance(edges, list):
        return value
    return None


def _build_graph_index(graph: dict[str, Any]) -> _GraphIndex:
    raw_nodes = graph.get("nodes") if isinstance(graph.get("nodes"), list) else []
    nodes: dict[str, _GraphNode] = {}
    order: dict[str, int] = {}
    for index, raw_node in enumerate(raw_nodes):
        node = _graph_node(raw_node)
        if node is None:
            continue
        nodes[node.node_id] = node
        order[node.node_id] = index
    adjacency = {node_id: [] for node_id in nodes}
    raw_edges = graph.get("edges") if isinstance(graph.get("edges"), list) else []
    for raw_edge in raw_edges:
        source = _edge_endpoint(raw_edge, ("from", "source", "sourceNodeId", "sourceStepId"))
        target = _edge_endpoint(raw_edge, ("to", "target", "targetNodeId", "targetStepId"))
        if not source or not target:
            raise ValueError("WORKFLOW_GRAPH_EDGE_UNSUPPORTED")
        if source not in nodes or target not in nodes:
            raise ValueError("WORKFLOW_GRAPH_EDGE_NODE_NOT_FOUND")
        adjacency.setdefault(source, []).append(target)
    return _GraphIndex(nodes=nodes, adjacency=adjacency, order=order)


def _graph_node(raw_node: Any) -> _GraphNode | None:
    if isinstance(raw_node, str):
        node_id = raw_node.strip()
        if not node_id:
            return None
        return _GraphNode(node_id=node_id, keys=frozenset({node_id}), is_rule=bool(node_id))
    if not isinstance(raw_node, dict):
        return None
    node_id = _first_text(raw_node, ("id", "stepId", "nodeId", "ruleName"))
    if not node_id:
        return None
    keys = {
        value
        for value in (
            node_id,
            _first_text(raw_node, ("stepId",)),
            _first_text(raw_node, ("nodeId",)),
            _first_text(raw_node, ("ruleName", "label", "title")),
            _first_text(raw_node, ("runtimeStatusKey",)),
        )
        if value
    }
    return _GraphNode(
        node_id=node_id,
        keys=frozenset(keys),
        is_rule=str(raw_node.get("kind") or "rule") == "rule",
    )


def _edge_endpoint(raw_edge: Any, keys: tuple[str, ...]) -> str:
    if not isinstance(raw_edge, dict):
        return ""
    for key in keys:
        value = raw_edge.get(key)
        if isinstance(value, dict):
            endpoint = _first_text(value, ("nodeId", "id", "stepId", "ruleName"))
            if endpoint:
                return endpoint
        endpoint = str(value or "").strip()
        if endpoint:
            return endpoint
    return ""


def _node_for_rule(rule: dict[str, Any], graph_index: _GraphIndex) -> _GraphNode | None:
    keys = _rule_keys(rule)
    for node in graph_index.nodes.values():
        if node.is_rule and node.keys & keys:
            return node
    return None


def _latest_rules(rules: list[dict[str, Any]]) -> list[dict[str, Any]]:
    latest_by_key: dict[str, dict[str, Any]] = {}
    for rule in rules:
        key = _rule_identity(rule)
        existing = latest_by_key.get(key)
        if existing is None or _rule_attempt_sort_key(rule) > _rule_attempt_sort_key(existing):
            latest_by_key[key] = rule
    return list(latest_by_key.values())


def _rule_identity(rule: dict[str, Any]) -> str:
    return (
        str(rule.get("runtimeStatusKey") or "").strip()
        or str(rule.get("stepId") or "").strip()
        or str(rule.get("ruleName") or "").strip()
        or str(rule.get("runRuleId") or id(rule))
    )


def _rule_attempt_sort_key(rule: dict[str, Any]) -> tuple[int, int, str]:
    return (
        _optional_int(rule.get("attemptNumber")),
        _optional_int(rule.get("leaseGeneration")),
        str(rule.get("updatedAt") or ""),
    )


def _rule_for_node(node: _GraphNode, rule_by_key: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    for key in node.keys:
        rule = rule_by_key.get(key)
        if rule is not None:
            return rule
    return None


def _rules_by_key(rules: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    for rule in rules:
        for key in _rule_keys(rule):
            indexed.setdefault(key, rule)
    return indexed


def _rule_keys(rule: dict[str, Any]) -> frozenset[str]:
    return frozenset(
        key
        for key in (
            str(rule.get("runtimeStatusKey") or "").strip(),
            str(rule.get("stepId") or "").strip(),
            str(rule.get("ruleName") or "").strip(),
        )
        if key
    )


def _rule_ref(rule: dict[str, Any]) -> dict[str, Any]:
    return {
        "runRuleId": rule.get("runRuleId"),
        "ruleName": rule.get("ruleName"),
        "stepId": rule.get("stepId"),
        "runtimeStatusKey": rule.get("runtimeStatusKey"),
        "status": rule.get("status"),
        "attemptId": rule.get("attemptId"),
        "leaseGeneration": rule.get("leaseGeneration"),
        "attemptNumber": rule.get("attemptNumber"),
    }


def _rule_ref_identity(rule: dict[str, Any]) -> str:
    return (
        str(rule.get("runtimeStatusKey") or "").strip()
        or str(rule.get("stepId") or "").strip()
        or str(rule.get("ruleName") or "").strip()
        or str(rule.get("runRuleId") or "").strip()
    )


def _is_failed_rule(rule: dict[str, Any]) -> bool:
    return str(rule.get("status") or "").lower() in FAILED_RULE_STATUSES


def _optional_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _first_text(value: dict[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        text = str(value.get(key) or "").strip()
        if text:
            return text
    return ""
