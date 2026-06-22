"""Semantic capability graph derived from validated Bio Tool Packs."""

from __future__ import annotations

import re
from typing import Any

from core.contracts.rule_ports import port_compatibility_decision, port_spec_from_rule_item

from .bio_tool_pack_manifest import complete_rule_template_semantics
from .tool_profile_model import ToolProfile


def semantic_capability_graph(
    *,
    profiles: tuple[ToolProfile, ...] | None = None,
    registered_tools: list[dict[str, Any]] | None = None,
    agent_selectable_only: bool = False,
) -> dict[str, Any]:
    selected_profiles = profiles if profiles is not None else _default_profiles()
    ready_by_name = _workflow_ready_tools_by_name(registered_tools or [])
    nodes: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, str]] = []
    for profile in selected_profiles:
        ready_tool = _matching_ready_tool(profile, ready_by_name)
        agent_selectable = ready_tool is not None
        if agent_selectable_only and not agent_selectable:
            continue
        profile_node = _node_id("profile", profile.pack_id, profile.profile_id)
        rule_template = complete_rule_template_semantics(profile.rule_template)
        nodes[profile_node] = {
            "id": profile_node,
            "kind": "ToolProfile",
            "profileId": profile.profile_id,
            "packId": profile.pack_id,
            "workflowStage": profile.workflow_stage,
            "operation": profile.operation,
            "agentSelectable": agent_selectable,
            "toolRevisionId": str((ready_tool or {}).get("toolRevisionId") or ""),
            "resourceRequirements": _resource_requirements(rule_template),
        }
        _connect_literal(nodes, edges, profile_node, "operation", profile.operation, "performs")
        _connect_literal(nodes, edges, profile_node, "workflowStage", profile.workflow_stage, "belongsToStage")
        for direction, edge_kind in (("inputs", "consumes"), ("outputs", "produces")):
            for port in rule_template.get(direction) or []:
                if not isinstance(port, dict):
                    continue
                port_name = str(port.get("name") or "").strip()
                if not port_name:
                    continue
                port_node = _node_id("port", profile.pack_id, profile.profile_id, direction[:-1], port_name)
                spec = port_spec_from_rule_item(port)
                port_kind = spec.pop("kind", "")
                nodes[port_node] = {
                    "id": port_node,
                    "kind": "InputPort" if direction == "inputs" else "OutputPort",
                    "profileId": profile.profile_id,
                    "name": port_name,
                    "kindLabel": port_kind,
                    **spec,
                }
                edges.append({"from": profile_node, "to": port_node, "kind": edge_kind})
                _connect_literal(nodes, edges, port_node, "edamData", spec.get("data", ""), "hasData")
                _connect_literal(nodes, edges, port_node, "edamFormat", spec.get("format", ""), "hasFormat")
                _connect_literal(nodes, edges, port_node, "edamOperation", spec.get("operation", ""), "hasOperation")
                _connect_literal(nodes, edges, port_node, "resource", spec.get("resource", ""), "hasResource")
        for resource_key, spec in (rule_template.get("resources") or {}).items():
            if isinstance(spec, dict) and str(spec.get("type") or "") == "database":
                for template_id in spec.get("acceptedTemplates") or []:
                    _connect_literal(nodes, edges, profile_node, "databaseTemplate", str(template_id), "requires")
                for capability in spec.get("acceptedCapabilities") or []:
                    _connect_literal(nodes, edges, profile_node, "databaseCapability", str(capability), "requiresCapability")
        for report_schema in profile.report_schemas:
            if isinstance(report_schema, dict):
                _connect_literal(
                    nodes,
                    edges,
                    profile_node,
                    "reportType",
                    str(report_schema.get("kind") or "artifact"),
                    "reports",
                )
    return {
        "contractVersion": "semantic-capability-graph-v1",
        "nodes": sorted(nodes.values(), key=lambda node: node["id"]),
        "edges": sorted(edges, key=lambda edge: (edge["from"], edge["kind"], edge["to"])),
        "agentSelectableProfileIds": sorted(
            node["profileId"]
            for node in nodes.values()
            if node["kind"] == "ToolProfile" and node.get("agentSelectable")
        ),
    }


def ports_can_connect(output_port: dict[str, Any], input_port: dict[str, Any]) -> bool:
    return port_compatibility_decision(port_spec_from_rule_item(input_port), port_spec_from_rule_item(output_port))[
        "compatible"
    ] is True


def one_hop_converter_candidates(
    *,
    output_port: dict[str, Any],
    input_port: dict[str, Any],
    profiles: tuple[ToolProfile, ...] | None = None,
    registered_tools: list[dict[str, Any]] | None = None,
    limit: int = 5,
) -> list[dict[str, Any]]:
    selected_profiles = profiles if profiles is not None else _default_profiles()
    ready_by_name = _workflow_ready_tools_by_name(registered_tools or []) if registered_tools is not None else {}
    source_spec = port_spec_from_rule_item(output_port)
    target_spec = port_spec_from_rule_item(input_port)
    candidates: list[dict[str, Any]] = []
    for profile in selected_profiles:
        ready_tool = _matching_ready_tool(profile, ready_by_name) if registered_tools is not None else None
        if registered_tools is not None and ready_tool is None:
            continue
        if ready_tool is not None and _tool_blocked_reasons(ready_tool):
            continue
        rule_template = complete_rule_template_semantics(profile.rule_template)
        if _requires_database_resource(rule_template):
            continue
        converter_inputs = _rule_ports(rule_template, "inputs")
        required_inputs = [item for item in converter_inputs if item.get("required", True) is not False]
        for converter_input in converter_inputs:
            converter_input_name = str(converter_input.get("name") or "").strip()
            if any(str(item.get("name") or "").strip() != converter_input_name for item in required_inputs):
                continue
            input_decision = port_compatibility_decision(port_spec_from_rule_item(converter_input), source_spec)
            if input_decision["compatible"] is not True:
                continue
            if not _has_strong_port_evidence(input_decision):
                continue
            for converter_output in _rule_ports(rule_template, "outputs"):
                output_decision = port_compatibility_decision(target_spec, port_spec_from_rule_item(converter_output))
                if output_decision["compatible"] is not True:
                    continue
                if not _has_strong_port_evidence(output_decision):
                    continue
                input_score = int(input_decision.get("score") or 0)
                output_score = int(output_decision.get("score") or 0)
                candidates.append(
                    {
                        "profileId": profile.profile_id,
                        "packId": profile.pack_id,
                        "toolRevisionId": str((ready_tool or {}).get("toolRevisionId") or ""),
                        "operation": profile.operation,
                        "workflowStage": profile.workflow_stage,
                        "inputPort": str(converter_input.get("name") or "").strip(),
                        "outputPort": str(converter_output.get("name") or "").strip(),
                        "score": input_score + output_score + _converter_specificity_score(profile),
                        "inputDecision": input_decision,
                        "outputDecision": output_decision,
                        "hardChecks": [
                            "source-output-to-converter-input",
                            "converter-output-to-target-input",
                            "no-database-resource-required",
                        ],
                    }
                )
    return sorted(candidates, key=lambda item: (-int(item["score"]), str(item["profileId"])))[: max(limit, 0)]


def _connect_literal(
    nodes: dict[str, dict[str, Any]],
    edges: list[dict[str, str]],
    source: str,
    kind: str,
    value: str,
    edge_kind: str,
) -> None:
    normalized = str(value or "").strip()
    if not normalized:
        return
    target = _node_id(kind, normalized)
    nodes.setdefault(target, {"id": target, "kind": kind, "value": normalized})
    edges.append({"from": source, "to": target, "kind": edge_kind})


def _has_strong_port_evidence(decision: dict[str, Any]) -> bool:
    return any(str(field) != "type" for field in decision.get("matchedFields") or [])


def _rule_ports(rule_template: dict[str, Any], key: str) -> list[dict[str, Any]]:
    return [
        item
        for item in rule_template.get(key) or []
        if isinstance(item, dict) and str(item.get("name") or "").strip()
    ]


def _requires_database_resource(rule_template: dict[str, Any]) -> bool:
    resources = rule_template.get("resources") if isinstance(rule_template.get("resources"), dict) else {}
    return any(
        isinstance(spec, dict) and str(spec.get("type") or "") == "database"
        for spec in resources.values()
    )


def _resource_requirements(rule_template: dict[str, Any]) -> list[dict[str, Any]]:
    resources = rule_template.get("resources") if isinstance(rule_template.get("resources"), dict) else {}
    requirements: list[dict[str, Any]] = []
    for key, spec in resources.items():
        if not isinstance(spec, dict) or str(spec.get("type") or "") != "database":
            continue
        requirements.append(
            {
                "resourceKey": str(key),
                "type": "database",
                "required": bool(spec.get("required", True)),
                "configKey": str(spec.get("configKey") or key).strip(),
                "acceptedTemplates": [str(item).strip() for item in spec.get("acceptedTemplates") or [] if str(item).strip()],
                "acceptedCapabilities": [
                    str(item).strip() for item in spec.get("acceptedCapabilities") or [] if str(item).strip()
                ],
            }
        )
    return requirements


def _tool_blocked_reasons(tool: dict[str, Any]) -> list[str]:
    status = tool.get("capabilityBundleStatus") if isinstance(tool.get("capabilityBundleStatus"), dict) else {}
    bundle = tool.get("capabilityBundle") if isinstance(tool.get("capabilityBundle"), dict) else {}
    return [
        str(reason)
        for reason in list(status.get("blockedReasons") or []) + list(bundle.get("blockedReasons") or [])
        if str(reason or "").strip()
    ]


def _converter_specificity_score(profile: ToolProfile) -> int:
    text = f"{profile.operation} {profile.workflow_stage}".lower()
    if re.search(r"(convert|conversion|format|transform|normalize|sort|index)", text):
        return 3
    return 0


def _workflow_ready_tools_by_name(tools: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    for tool in tools:
        contract = tool.get("toolContract") if isinstance(tool.get("toolContract"), dict) else {}
        if not (contract.get("workflowReady") or contract.get("state") == "ProductionEnabled"):
            continue
        draft = tool.get("ruleSpecDraft") if isinstance(tool.get("ruleSpecDraft"), dict) else {}
        lock = draft.get("lock") if isinstance(draft.get("lock"), dict) else {}
        locked_profile_id = _normalize_name(lock.get("profileId"))
        if locked_profile_id:
            indexed.setdefault(locked_profile_id, tool)
        for name in (tool.get("name"), tool.get("id"), tool.get("toolId"), tool.get("toolRevisionId")):
            normalized = _normalize_name(name)
            if normalized:
                indexed.setdefault(normalized, tool)
    return indexed


def _matching_ready_tool(profile: ToolProfile, ready_by_name: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    for name in (profile.profile_id, *profile.tool_names):
        normalized = _normalize_name(name)
        if normalized in ready_by_name:
            return ready_by_name[normalized]
    return None


def _normalize_name(value: Any) -> str:
    text = str(value or "").strip().lower()
    if "::" in text:
        text = text.rsplit("::", 1)[-1]
    if "@" in text:
        text = text.split("@", 1)[0]
    if "#" in text:
        text = text.split("#", 1)[0]
    return re.sub(r"[^a-z0-9.+-]+", "-", text).strip("-")


def _node_id(*parts: str) -> str:
    return ":".join(str(part).replace(":", "_").strip() for part in parts if str(part).strip())


def _default_profiles() -> tuple[ToolProfile, ...]:
    from .tool_profile_sources import all_tool_profiles

    return all_tool_profiles()
