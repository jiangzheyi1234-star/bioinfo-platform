"""Semantic capability graph derived from validated Bio Tool Packs."""

from __future__ import annotations

from typing import Any

from core.contracts.rule_ports import mismatched_compatibility_field, port_spec_from_rule_item

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
        nodes[profile_node] = {
            "id": profile_node,
            "kind": "ToolProfile",
            "profileId": profile.profile_id,
            "packId": profile.pack_id,
            "workflowStage": profile.workflow_stage,
            "operation": profile.operation,
            "agentSelectable": agent_selectable,
            "toolRevisionId": str((ready_tool or {}).get("toolRevisionId") or ""),
        }
        rule_template = complete_rule_template_semantics(profile.rule_template)
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
                nodes[port_node] = {
                    "id": port_node,
                    "kind": "InputPort" if direction == "inputs" else "OutputPort",
                    "profileId": profile.profile_id,
                    "name": port_name,
                    **spec,
                }
                edges.append({"from": profile_node, "to": port_node, "kind": edge_kind})
                _connect_literal(nodes, edges, port_node, "edamData", spec.get("data", ""), "hasData")
                _connect_literal(nodes, edges, port_node, "edamFormat", spec.get("format", ""), "hasFormat")
        for resource_key, spec in (rule_template.get("resources") or {}).items():
            if isinstance(spec, dict) and str(spec.get("type") or "") == "database":
                for template_id in spec.get("acceptedTemplates") or []:
                    _connect_literal(nodes, edges, profile_node, "databaseTemplate", str(template_id), "requires")
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
    return mismatched_compatibility_field(port_spec_from_rule_item(input_port), port_spec_from_rule_item(output_port)) == ""


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


def _workflow_ready_tools_by_name(tools: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    for tool in tools:
        contract = tool.get("toolContract") if isinstance(tool.get("toolContract"), dict) else {}
        if not (contract.get("workflowReady") or contract.get("state") == "ProductionEnabled"):
            continue
        for name in (tool.get("name"), tool.get("id"), tool.get("toolId"), tool.get("toolRevisionId")):
            normalized = _normalize_name(name)
            if normalized:
                indexed.setdefault(normalized, tool)
    return indexed


def _matching_ready_tool(profile: ToolProfile, ready_by_name: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    for name in (profile.profile_id, profile.package_name, *profile.tool_names):
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
    return text


def _node_id(*parts: str) -> str:
    return ":".join(str(part).replace(":", "_").strip() for part in parts if str(part).strip())


def _default_profiles() -> tuple[ToolProfile, ...]:
    from .tool_profile_definitions import TOOL_PROFILES

    return TOOL_PROFILES
