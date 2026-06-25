"""Semantic port diagnostics for WorkflowDesignDraft plan responses."""

from __future__ import annotations

import re
from typing import Any

from core.contracts.rule_ports import port_compatibility_decision, port_spec_from_rule_item

from .config import RemoteRunnerConfig
from .generated_workflow_names import safe_identifier, safe_snakemake_name
from .generated_workflow_plan import resolve_rule_contract
from .tool_revisions import fetch_tool_revision
from .tools import list_registered_tools, normalize_rule_template
from core.contracts.workflow_design import WorkflowDesignDraftV1, WorkflowDesignEdge


SEMANTIC_PORT_PLAN_SCHEMA_VERSION = "h2ometa.workflow-design-semantic-port-plan.v1"
_GRAPH_MUTATION_BLOCKERS = ["confirmation-required", "graph-mutation-requires-user-action"]
_CONVERTER_LIMIT = 5


def build_workflow_design_semantic_port_plan(
    cfg: RemoteRunnerConfig,
    design: WorkflowDesignDraftV1,
) -> dict[str, Any]:
    contexts = _node_contexts(cfg, design)
    excluded_revisions = {str(node.toolRevisionId or "").strip() for node in design.nodes if str(node.toolRevisionId or "").strip()}
    converters = _converter_contexts(cfg, excluded_revisions=excluded_revisions)
    edges = [_edge_semantic_plan(edge, contexts=contexts, converters=converters) for edge in design.edges]
    compatible_count = sum(1 for edge in edges if edge["decision"]["compatible"] is True)
    blocked_count = sum(1 for edge in edges if edge["decision"]["compatible"] is not True)
    converter_count = sum(len(edge["converterCandidates"]) for edge in edges)
    return {
        "schemaVersion": SEMANTIC_PORT_PLAN_SCHEMA_VERSION,
        "edgeCount": len(edges),
        "compatibleEdgeCount": compatible_count,
        "blockedEdgeCount": blocked_count,
        "converterCandidateCount": converter_count,
        "edges": edges,
    }


def empty_workflow_design_semantic_port_plan() -> dict[str, Any]:
    return {
        "schemaVersion": SEMANTIC_PORT_PLAN_SCHEMA_VERSION,
        "edgeCount": 0,
        "compatibleEdgeCount": 0,
        "blockedEdgeCount": 0,
        "converterCandidateCount": 0,
        "edges": [],
    }


def _edge_semantic_plan(
    edge: WorkflowDesignEdge,
    *,
    contexts: dict[str, dict[str, Any]],
    converters: list[dict[str, Any]],
) -> dict[str, Any]:
    source = _resolve_edge_port(edge.from_.nodeId, edge.from_.port, "outputs", contexts)
    target = _resolve_edge_port(edge.to.nodeId, edge.to.port, "inputs", contexts)
    edge_ref = _edge_ref(edge)
    if not source["ok"]:
        return _blocked_edge(edge_ref, "SOURCE_PORT_UNRESOLVED", str(source["message"]))
    if not target["ok"]:
        return _blocked_edge(edge_ref, "TARGET_PORT_UNRESOLVED", str(target["message"]))

    decision = _public_decision(port_compatibility_decision(target["spec"], source["spec"]))
    if decision["compatible"] is True:
        return {
            **edge_ref,
            "decision": decision,
            "recommendation": {
                "action": "connect",
                "reasonCode": "PORTS_COMPATIBLE",
                "confidence": _confidence_from_score(decision.get("score")),
                "hardChecks": list(decision.get("hardChecks") or []),
                "evidence": _edge_evidence(source=source, target=target, decision=decision),
                "converterCandidateCount": 0,
            },
            "converterCandidates": [],
        }

    candidates = _one_hop_converter_candidates(source=source, target=target, converters=converters)
    action = "insert-converter" if candidates else "block"
    reason_code = "ONE_HOP_CONVERTER_AVAILABLE" if candidates else "PORTS_INCOMPATIBLE"
    return {
        **edge_ref,
        "decision": decision,
        "recommendation": {
            "action": action,
            "reasonCode": reason_code,
            "confidence": _confidence_from_score(candidates[0]["totalScore"] if candidates else decision.get("score")),
            "hardChecks": list(decision.get("hardChecks") or []),
            "evidence": _edge_evidence(source=source, target=target, decision=decision),
            "converterCandidateCount": len(candidates),
        },
        "converterCandidates": candidates,
    }


def _blocked_edge(edge_ref: dict[str, Any], reason_code: str, message: str) -> dict[str, Any]:
    decision = _blocked_decision(reason_code)
    return {
        **edge_ref,
        "decision": decision,
        "recommendation": {
            "action": "block",
            "reasonCode": reason_code,
            "confidence": 0.0,
            "hardChecks": list(decision["hardChecks"]),
            "evidence": [message],
            "converterCandidateCount": 0,
        },
        "converterCandidates": [],
    }


def _one_hop_converter_candidates(
    *,
    source: dict[str, Any],
    target: dict[str, Any],
    converters: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for converter in converters:
        required_inputs = [port for port in converter["inputs"] if port["required"] is not False]
        if len(required_inputs) != 1:
            continue
        converter_input = required_inputs[0]
        input_decision = port_compatibility_decision(converter_input["spec"], source["spec"])
        if input_decision["compatible"] is not True or not _has_strong_port_evidence(input_decision):
            continue
        for converter_output in converter["outputs"]:
            output_decision = port_compatibility_decision(target["spec"], converter_output["spec"])
            if output_decision["compatible"] is not True or not _has_strong_port_evidence(output_decision):
                continue
            input_score = int(input_decision.get("score") or 0)
            output_score = int(output_decision.get("score") or 0)
            total_score = input_score + output_score + _converter_specificity_score(converter)
            evidence = _converter_evidence(
                converter=converter,
                converter_input=converter_input,
                converter_output=converter_output,
                input_score=input_score,
                output_score=output_score,
            )
            candidates.append(
                {
                    "converterToolRevisionId": converter["toolRevisionId"],
                    "converterToolId": converter["toolId"],
                    "converterToolName": converter["toolName"],
                    "inputPort": converter_input["name"],
                    "outputPort": converter_output["name"],
                    "inputScore": input_score,
                    "outputScore": output_score,
                    "totalScore": total_score,
                    "operation": converter.get("operation", ""),
                    "workflowStage": converter.get("workflowStage", ""),
                    "confirmationRequired": True,
                    "insertionMode": "explicit-user-confirmed",
                    "autoInsertionBlockedReasons": list(_GRAPH_MUTATION_BLOCKERS),
                    "hardChecks": [
                        "workflow-ready-converter",
                        "single-required-input",
                        "converter-has-no-database-resource",
                        "source-output-to-converter-input-strong-evidence",
                        "converter-output-to-target-input-strong-evidence",
                    ],
                    "evidence": evidence,
                    "inputDecision": _public_decision(input_decision),
                    "outputDecision": _public_decision(output_decision),
                    "reason": "; ".join(evidence),
                }
            )
    return sorted(candidates, key=lambda item: (-int(item["totalScore"]), str(item["converterToolName"])))[:_CONVERTER_LIMIT]


def _node_contexts(cfg: RemoteRunnerConfig, design: WorkflowDesignDraftV1) -> dict[str, dict[str, Any]]:
    contexts: dict[str, dict[str, Any]] = {}
    for node in design.nodes:
        tool = fetch_tool_revision(cfg, node.toolRevisionId)
        if tool is None:
            contexts[node.id] = {"ok": False, "code": "TOOL_REVISION_NOT_FOUND"}
            continue
        try:
            rule_template, _ = resolve_rule_contract(tool=tool, tool_request={"toolRevisionId": node.toolRevisionId})
        except ValueError as exc:
            contexts[node.id] = {"ok": False, "code": _issue_code(str(exc))}
            continue
        contexts[node.id] = {
            "ok": True,
            "toolRevisionId": str(node.toolRevisionId),
            "toolName": str(tool.get("name") or node.toolRevisionId),
            "inputs": _indexed_ports(rule_template, "inputs"),
            "outputs": _indexed_ports(rule_template, "outputs"),
        }
    return contexts


def _converter_contexts(cfg: RemoteRunnerConfig, *, excluded_revisions: set[str]) -> list[dict[str, Any]]:
    converters: list[dict[str, Any]] = []
    for tool in list_registered_tools(cfg):
        revision_id = str(tool.get("toolRevisionId") or "").strip()
        if not revision_id or revision_id in excluded_revisions:
            continue
        if not _tool_workflow_ready(tool):
            continue
        try:
            rule_template = normalize_rule_template(tool.get("ruleTemplate"), required=True)
        except ValueError:
            continue
        if _requires_database_resource(rule_template):
            continue
        inputs = _rule_ports(rule_template, "inputs")
        outputs = _rule_ports(rule_template, "outputs")
        if not inputs or not outputs:
            continue
        metadata = _converter_metadata(tool, rule_template)
        converters.append(
            {
                "toolRevisionId": revision_id,
                "toolId": str(tool.get("id") or tool.get("toolId") or "").strip(),
                "toolName": str(tool.get("name") or revision_id).strip(),
                "inputs": inputs,
                "outputs": outputs,
                **metadata,
            }
        )
    return converters


def _resolve_edge_port(
    node_id: str,
    port_name: str,
    direction: str,
    contexts: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    context = contexts.get(node_id)
    if context is None:
        return {"ok": False, "message": f"WORKFLOW_DESIGN_NODE_UNKNOWN: {node_id}"}
    if context.get("ok") is not True:
        return {"ok": False, "message": f"{context.get('code') or 'TOOL_CONTEXT_UNRESOLVED'}: {node_id}"}
    ports = context.get(direction) if isinstance(context.get(direction), dict) else {}
    port = ports.get(port_name) or ports.get(safe_snakemake_name(port_name)) or ports.get(safe_identifier(port_name))
    if port is None:
        return {"ok": False, "message": f"WORKFLOW_DESIGN_PORT_UNKNOWN: {node_id}.{port_name}"}
    return {
        "ok": True,
        "nodeId": node_id,
        "port": port["name"],
        "toolRevisionId": str(context.get("toolRevisionId") or ""),
        "toolName": str(context.get("toolName") or ""),
        "spec": dict(port["spec"]),
    }


def _indexed_ports(rule_template: dict[str, Any], direction: str) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    for port in _rule_ports(rule_template, direction):
        item = {"name": port["name"], "required": port["required"], "spec": port["spec"]}
        for key in (port["name"], safe_snakemake_name(port["name"]), safe_identifier(port["name"])):
            if key:
                indexed.setdefault(key, item)
    return indexed


def _rule_ports(rule_template: dict[str, Any], direction: str) -> list[dict[str, Any]]:
    ports: list[dict[str, Any]] = []
    for index, item in enumerate(rule_template.get(direction) or []):
        if not isinstance(item, dict):
            continue
        fallback = "primary" if index == 0 else f"{direction[:-1]}_{index + 1}"
        name = str(item.get("name") or fallback).strip()
        if not name:
            continue
        ports.append(
            {
                "name": name,
                "required": item.get("required", True) is not False,
                "spec": port_spec_from_rule_item(item),
            }
        )
    return ports


def _public_decision(decision: dict[str, Any]) -> dict[str, Any]:
    return {
        "compatible": decision.get("compatible") is True,
        "score": decision.get("score") if decision.get("score") is not None else None,
        "matchedFields": [str(item) for item in decision.get("matchedFields") or []],
        "genericFields": [str(item) for item in decision.get("genericFields") or []],
        "advisoryFields": [str(item) for item in decision.get("advisoryFields") or []],
        "mismatchedField": str(decision.get("mismatchedField") or ""),
        "hardChecks": [str(item) for item in decision.get("hardChecks") or []],
        "advisoryChecks": [str(item) for item in decision.get("advisoryChecks") or []],
        "inputSpec": _semantic_spec(decision.get("inputSpec")),
        "outputSpec": _semantic_spec(decision.get("outputSpec")),
    }


def _blocked_decision(reason_code: str) -> dict[str, Any]:
    return {
        "compatible": False,
        "score": None,
        "matchedFields": [],
        "genericFields": [],
        "advisoryFields": [],
        "mismatchedField": "",
        "hardChecks": ["port-direction:output-to-input", reason_code],
        "advisoryChecks": [],
        "inputSpec": {},
        "outputSpec": {},
    }


def _semantic_spec(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, str] = {}
    for key in ("type", "kind", "mimeType", "data", "format", "operation", "resource"):
        text = str(value.get(key) or "").strip()
        if text:
            result[key] = text
    return result


def _edge_ref(edge: WorkflowDesignEdge) -> dict[str, Any]:
    edge_id = str(edge.id or "").strip()
    return {
        **({"edgeId": edge_id} if edge_id else {}),
        "from": {"nodeId": edge.from_.nodeId, "port": edge.from_.port},
        "to": {"nodeId": edge.to.nodeId, "port": edge.to.port},
    }


def _edge_evidence(*, source: dict[str, Any], target: dict[str, Any], decision: dict[str, Any]) -> list[str]:
    fields = list(decision.get("matchedFields") or []) + list(decision.get("genericFields") or [])
    field_text = ",".join(fields) if fields else "no strong semantic match"
    return [
        f"{source['nodeId']}.{source['port']} -> {target['nodeId']}.{target['port']}",
        f"semantic evidence: {field_text}",
    ]


def _converter_evidence(
    *,
    converter: dict[str, Any],
    converter_input: dict[str, Any],
    converter_output: dict[str, Any],
    input_score: int,
    output_score: int,
) -> list[str]:
    values = [
        f"source output satisfies converter input {converter_input['name']}",
        f"converter output {converter_output['name']} satisfies target input",
        f"score {input_score}+{output_score}",
    ]
    if converter.get("operation"):
        values.append(f"operation {converter['operation']}")
    if converter.get("workflowStage"):
        values.append(f"stage {converter['workflowStage']}")
    return values


def _tool_workflow_ready(tool: dict[str, Any]) -> bool:
    contract = tool.get("toolContract") if isinstance(tool.get("toolContract"), dict) else {}
    state = str(contract.get("state") or "").strip()
    return bool(contract.get("workflowReady")) or state in {"WorkflowReady", "ProductionEnabled"}


def _requires_database_resource(rule_template: dict[str, Any]) -> bool:
    resources = rule_template.get("resources") if isinstance(rule_template.get("resources"), dict) else {}
    return any(isinstance(spec, dict) and str(spec.get("type") or "").strip() == "database" for spec in resources.values())


def _has_strong_port_evidence(decision: dict[str, Any]) -> bool:
    return any(str(field) != "type" for field in decision.get("matchedFields") or [])


def _converter_metadata(tool: dict[str, Any], rule_template: dict[str, Any]) -> dict[str, str]:
    bundle = tool.get("capabilityBundle") if isinstance(tool.get("capabilityBundle"), dict) else {}
    summary = bundle.get("selectionSummary") if isinstance(bundle.get("selectionSummary"), dict) else {}
    capabilities = tool.get("capabilities") if isinstance(tool.get("capabilities"), list) else []
    capability = next((item for item in capabilities if isinstance(item, dict)), {})
    metadata = rule_template.get("metadata") if isinstance(rule_template.get("metadata"), dict) else {}
    return {
        "operation": _first_text(summary.get("operation"), capability.get("operation"), metadata.get("operation")),
        "workflowStage": _first_text(summary.get("workflowStage"), metadata.get("workflowStage")),
    }


def _converter_specificity_score(converter: dict[str, Any]) -> int:
    text = f"{converter.get('operation') or ''} {converter.get('workflowStage') or ''}".lower()
    if re.search(r"(convert|conversion|format|transform|normalize|sort|index)", text):
        return 3
    return 0


def _confidence_from_score(score: Any) -> float:
    if score is None:
        return 0.0
    try:
        value = int(score)
    except (TypeError, ValueError):
        return 0.0
    return min(0.95, round(0.45 + min(value, 20) * 0.02, 2))


def _first_text(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _issue_code(detail: str) -> str:
    return detail.split(":", 1)[0].strip() or "TOOL_CONTEXT_UNRESOLVED"
