"""Semantic recommendations over tool candidates with declared rule ports."""

from __future__ import annotations

from typing import Any

from apps.api.tool_candidate_model import tool_profile_candidate_fields
from apps.api.tool_profile_external_refs import profile_external_candidate_fields
from apps.api.tool_profile_model import ToolProfile
from apps.api.tool_profile_prepare_payload import profile_prepare_payload
from apps.api.tool_profile_semantics import enrich_rule_template_semantics
from apps.api.tool_profile_sources import all_tool_profiles
from apps.api.tool_validation_plan import workflow_ready_validation_plan
from core.contracts.rule_ports import (
    matched_compatibility_fields,
    mismatched_compatibility_field,
    port_spec_from_rule_item,
)


def recommend_tool_candidates(
    *,
    output_port: dict[str, Any],
    query: str = "",
    page: int = 1,
    page_size: int = 20,
    registered_tools: list[dict[str, Any]] | None = None,
    latest_prepare_jobs_by_tool_id: dict[str, Any] | None = None,
    catalog_items: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    normalized_query = str(query or "").strip().lower()
    bounded_page = max(1, int(page or 1))
    bounded_page_size = max(1, min(int(page_size or 20), 100))
    output_spec = port_spec_from_rule_item(output_port)
    registered = registered_tools or []
    latest_jobs = latest_prepare_jobs_by_tool_id or {}
    workflow_ready_tools = _workflow_ready_tools_by_name(registered)
    items = sorted(
        [
            *_profile_recommendations(
                output_spec=output_spec,
                query=normalized_query,
                workflow_ready_tools=workflow_ready_tools,
                latest_prepare_jobs_by_tool_id=latest_jobs,
            ),
            *_catalog_candidate_recommendations(
                output_spec=output_spec,
                query=normalized_query,
                catalog_items=catalog_items or [],
                workflow_ready_tools=workflow_ready_tools,
                latest_prepare_jobs_by_tool_id=latest_jobs,
            ),
        ],
        key=lambda item: (-float(item["confidence"]), str(item["candidate"]["candidateId"]), str(item["inputPort"]["name"])),
    )
    offset = (bounded_page - 1) * bounded_page_size
    return {
        "items": items[offset : offset + bounded_page_size],
        "query": normalized_query,
        "outputPort": output_spec,
        "total": len(items),
        "page": bounded_page,
        "pageSize": bounded_page_size,
        "hasMore": offset + bounded_page_size < len(items),
    }


def _profile_recommendations(
    *,
    output_spec: dict[str, str],
    query: str,
    workflow_ready_tools: dict[str, dict[str, Any]],
    latest_prepare_jobs_by_tool_id: dict[str, Any],
) -> list[dict[str, Any]]:
    recommendations: list[dict[str, Any]] = []
    for profile in all_tool_profiles():
        if query and not _profile_matches_query(profile, query):
            continue
        registered_tool = _matching_registered_tool(profile, workflow_ready_tools)
        latest_prepare_job = _latest_prepare_job(profile, latest_prepare_jobs_by_tool_id)
        for input_port in _input_ports(profile):
            input_spec = port_spec_from_rule_item(input_port)
            if mismatched_compatibility_field(input_spec, output_spec):
                continue
            matched_fields = matched_compatibility_fields(input_spec, output_spec)
            if not matched_fields:
                continue
            item = {
                "decision": "recommended",
                "candidate": _profile_candidate(profile),
                "executionGate": _execution_gate(profile, registered_tool=registered_tool, latest_prepare_job=latest_prepare_job),
                "inputPort": _input_port_summary(input_port, input_spec),
                "matchedFields": matched_fields,
                "confidence": _confidence(matched_fields=matched_fields, input_port=input_port),
                "hardChecks": ["端口方向 output -> input", "类型字段无冲突"],
                "evidence": _evidence(matched_fields=matched_fields, input_spec=input_spec),
            }
            item["blockReason"] = "" if item["executionGate"]["canAddStep"] else item["executionGate"]["reason"]
            if registered_tool is None:
                item["validationPlan"] = workflow_ready_validation_plan()
                if latest_prepare_job is not None:
                    item["latestPrepareJob"] = latest_prepare_job
                if not _active_prepare_job(latest_prepare_job):
                    item["preparePayload"] = item["candidate"]["preparePayload"]
            recommendations.append(item)
    return recommendations


def _catalog_candidate_recommendations(
    *,
    output_spec: dict[str, str],
    query: str,
    catalog_items: list[dict[str, Any]],
    workflow_ready_tools: dict[str, dict[str, Any]],
    latest_prepare_jobs_by_tool_id: dict[str, Any],
) -> list[dict[str, Any]]:
    recommendations: list[dict[str, Any]] = []
    for item in catalog_items:
        if str(item.get("candidateKind") or "") == "h2ometa-tool-profile":
            continue
        candidate = _catalog_candidate(item)
        if candidate is None:
            continue
        if query and not _catalog_candidate_matches_query(candidate, query):
            continue
        registered_tool = _matching_registered_candidate(candidate, workflow_ready_tools)
        latest_prepare_job = _latest_prepare_job_for_tool_ids(
            _candidate_prepare_tool_ids(candidate),
            latest_prepare_jobs_by_tool_id,
        )
        for input_port in _catalog_candidate_input_ports(candidate):
            input_spec = port_spec_from_rule_item(input_port)
            if mismatched_compatibility_field(input_spec, output_spec):
                continue
            matched_fields = matched_compatibility_fields(input_spec, output_spec)
            if not matched_fields:
                continue
            recommendation = {
                "decision": "recommended",
                "candidate": candidate,
                "executionGate": _candidate_execution_gate(candidate, registered_tool=registered_tool, latest_prepare_job=latest_prepare_job),
                "inputPort": _input_port_summary(input_port, input_spec),
                "matchedFields": matched_fields,
                "confidence": _confidence(matched_fields=matched_fields, input_port=input_port),
                "hardChecks": ["端口方向 output -> input", "类型字段无冲突"],
                "evidence": _evidence(matched_fields=matched_fields, input_spec=input_spec),
            }
            recommendation["blockReason"] = (
                "" if recommendation["executionGate"]["canAddStep"] else recommendation["executionGate"]["reason"]
            )
            if registered_tool is None:
                recommendation["validationPlan"] = workflow_ready_validation_plan()
                if latest_prepare_job is not None:
                    recommendation["latestPrepareJob"] = latest_prepare_job
                if not _active_prepare_job(latest_prepare_job):
                    recommendation["preparePayload"] = candidate["preparePayload"]
            recommendations.append(recommendation)
    return recommendations


def _catalog_candidate(item: dict[str, Any]) -> dict[str, Any] | None:
    prepare_payload = item.get("preparePayload") if isinstance(item.get("preparePayload"), dict) else None
    if prepare_payload is None:
        return None
    rule_template = prepare_payload.get("ruleTemplate")
    if not isinstance(rule_template, dict):
        return None
    candidate = {
        key: item.get(key)
        for key in (
            "candidateId",
            "candidateKind",
            "sourceRef",
            "contractState",
            "qualityTier",
            "name",
            "toolName",
            "toolNames",
            "snakemakeWrapperCount",
            "snakemakeWrappers",
            "wrapperPath",
            "wrapperIdentifier",
        )
        if item.get(key) is not None
    }
    candidate["preparePayload"] = dict(prepare_payload)
    return candidate


def _catalog_candidate_input_ports(candidate: dict[str, Any]) -> list[dict[str, Any]]:
    prepare_payload = candidate.get("preparePayload") if isinstance(candidate.get("preparePayload"), dict) else {}
    template = prepare_payload.get("ruleTemplate") if isinstance(prepare_payload.get("ruleTemplate"), dict) else {}
    enriched = enrich_rule_template_semantics(template)
    return [item for item in enriched.get("inputs") or [] if isinstance(item, dict)]


def _candidate_execution_gate(
    candidate: dict[str, Any],
    *,
    registered_tool: dict[str, Any] | None,
    latest_prepare_job: dict[str, Any] | None,
) -> dict[str, Any]:
    if registered_tool is not None:
        return _ready_execution_gate(registered_tool)
    if _active_prepare_job(latest_prepare_job):
        return {
            "currentState": str(candidate.get("contractState") or "SnakemakeRenderable"),
            "requiredState": "WorkflowReady",
            "canAddStep": False,
            "nextAction": "wait-for-tool-validation",
            "reason": "TOOL_PREPARE_JOB_ACTIVE",
            "sourceOfTruth": "toolPrepareJob",
            "jobId": str(latest_prepare_job.get("jobId") or ""),
            "toolId": str(latest_prepare_job.get("toolId") or ""),
        }
    return {
        "currentState": str(candidate.get("contractState") or "Discovered"),
        "requiredState": "WorkflowReady",
        "canAddStep": False,
        "nextAction": "prepare-tool",
        "reason": "WORKFLOW_TOOL_NOT_READY",
        "sourceOfTruth": "registeredTool.toolContract",
    }


def _catalog_candidate_matches_query(candidate: dict[str, Any], query: str) -> bool:
    return query in " ".join(_candidate_names(candidate)).lower()


def _matching_registered_candidate(candidate: dict[str, Any], tools_by_name: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    for name in _candidate_names(candidate):
        normalized = _normalized_tool_name(_tool_name_from_identifier(name))
        if normalized in tools_by_name:
            return tools_by_name[normalized]
    return None


def _latest_prepare_job_for_tool_ids(tool_ids: list[str], latest_prepare_jobs_by_tool_id: dict[str, Any]) -> dict[str, Any] | None:
    for tool_id in tool_ids:
        value = latest_prepare_jobs_by_tool_id.get(tool_id)
        if isinstance(value, dict):
            return dict(value)
    return None


def _candidate_prepare_tool_ids(candidate: dict[str, Any]) -> list[str]:
    prepare_payload = candidate.get("preparePayload") if isinstance(candidate.get("preparePayload"), dict) else {}
    return _unique_strings(
        str(value or "").strip()
        for value in (
            prepare_payload.get("id"),
            prepare_payload.get("packageSpec"),
            prepare_payload.get("name"),
            candidate.get("candidateId"),
        )
        if str(value or "").strip()
    )


def _candidate_names(candidate: dict[str, Any]) -> list[str]:
    names: list[str] = []
    raw_tool_names = candidate.get("toolNames")
    if isinstance(raw_tool_names, list):
        names.extend(str(value).strip() for value in raw_tool_names if str(value or "").strip())
    prepare_payload = candidate.get("preparePayload") if isinstance(candidate.get("preparePayload"), dict) else {}
    for value in (
        candidate.get("name"),
        candidate.get("toolName"),
        candidate.get("candidateId"),
        prepare_payload.get("name"),
        prepare_payload.get("id"),
        prepare_payload.get("packageSpec"),
    ):
        text = str(value or "").strip()
        if text:
            names.append(text)
    return _unique_strings(names)


def _unique_strings(values: Any) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        unique.append(text)
    return unique


def _profile_candidate(profile: ToolProfile) -> dict[str, Any]:
    return {
        "profileId": profile.profile_id,
        "profileVersion": profile.version,
        "packId": profile.pack_id,
        "toolNames": list(profile.tool_names),
        "preferredWrapperPaths": list(profile.preferred_wrapper_paths),
        "preparePayload": profile_prepare_payload(profile),
        **profile_external_candidate_fields(profile),
        **tool_profile_candidate_fields(profile),
    }


def _execution_gate(
    profile: ToolProfile,
    *,
    registered_tool: dict[str, Any] | None = None,
    latest_prepare_job: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if registered_tool is not None:
        return _ready_execution_gate(registered_tool)
    if _active_prepare_job(latest_prepare_job):
        return {
            "currentState": "SnakemakeRenderable",
            "requiredState": "WorkflowReady",
            "canAddStep": False,
            "nextAction": "wait-for-tool-validation",
            "reason": "TOOL_PREPARE_JOB_ACTIVE",
            "sourceOfTruth": "toolPrepareJob",
            "jobId": str(latest_prepare_job.get("jobId") or ""),
            "toolId": str(latest_prepare_job.get("toolId") or ""),
        }
    candidate = _profile_candidate(profile)
    return {
        "currentState": candidate.get("contractState") or "Discovered",
        "requiredState": "WorkflowReady",
        "canAddStep": False,
        "nextAction": "prepare-tool",
        "reason": "WORKFLOW_TOOL_NOT_READY",
        "sourceOfTruth": "registeredTool.toolContract",
    }


def _ready_execution_gate(registered_tool: dict[str, Any]) -> dict[str, Any]:
    contract = registered_tool.get("toolContract") if isinstance(registered_tool.get("toolContract"), dict) else {}
    return {
        "currentState": str(contract.get("state") or "WorkflowReady"),
        "requiredState": "WorkflowReady",
        "canAddStep": True,
        "nextAction": "add-step",
        "reason": "WORKFLOW_TOOL_READY",
        "sourceOfTruth": "registeredTool.toolContract",
        "toolRevisionId": str(registered_tool.get("toolRevisionId") or ""),
        "toolId": str(registered_tool.get("id") or registered_tool.get("toolId") or ""),
    }


def _workflow_ready_tools_by_name(tools: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    for tool in tools:
        if not _is_workflow_ready_tool(tool):
            continue
        for name in _registered_tool_names(tool):
            indexed.setdefault(name, tool)
    return indexed


def _matching_registered_tool(profile: ToolProfile, tools_by_name: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    for name in [profile.profile_id, *profile.tool_names]:
        normalized = _normalized_tool_name(name)
        if normalized in tools_by_name:
            return tools_by_name[normalized]
    return None


def _latest_prepare_job(profile: ToolProfile, latest_prepare_jobs_by_tool_id: dict[str, Any]) -> dict[str, Any] | None:
    for tool_id in _profile_prepare_tool_ids(profile):
        value = latest_prepare_jobs_by_tool_id.get(tool_id)
        if isinstance(value, dict):
            return dict(value)
    return None


def _profile_prepare_tool_ids(profile: ToolProfile) -> list[str]:
    tool_name = str(profile.tool_names[0] if profile.tool_names else profile.profile_id).strip()
    package_name = str(profile.package_name or tool_name).strip()
    return [tool_id for tool_id in [f"bioconda::{package_name}", package_name, tool_name] if tool_id]


def _active_prepare_job(value: dict[str, Any] | None) -> bool:
    if not isinstance(value, dict):
        return False
    return str(value.get("status") or "").strip() in {"queued", "running"}


def _is_workflow_ready_tool(tool: dict[str, Any]) -> bool:
    contract = tool.get("toolContract") if isinstance(tool.get("toolContract"), dict) else {}
    return bool(contract.get("workflowReady")) or str(contract.get("state") or "") == "ProductionEnabled"


def _registered_tool_names(tool: dict[str, Any]) -> list[str]:
    names = [
        tool.get("name"),
        tool.get("id"),
        tool.get("toolRevisionId"),
    ]
    return [
        normalized
        for value in names
        for normalized in [_normalized_tool_name(_tool_name_from_identifier(value))]
        if normalized
    ]


def _tool_name_from_identifier(value: Any) -> str:
    text = str(value or "").strip()
    if "::" in text:
        text = text.rsplit("::", 1)[-1]
    if "@" in text:
        text = text.split("@", 1)[0]
    return text


def _normalized_tool_name(value: Any) -> str:
    return str(value or "").strip().lower()


def _input_ports(profile: ToolProfile) -> list[dict[str, Any]]:
    template = enrich_rule_template_semantics(profile.rule_template)
    return [item for item in template.get("inputs") or [] if isinstance(item, dict)]


def _input_port_summary(input_port: dict[str, Any], input_spec: dict[str, str]) -> dict[str, Any]:
    return {
        "name": str(input_port.get("name") or "").strip(),
        "required": bool(input_port.get("required", True)),
        **input_spec,
    }


def _confidence(*, matched_fields: list[str], input_port: dict[str, Any]) -> float:
    score = 0.35 + len(matched_fields) * 0.1
    if bool(input_port.get("required", True)):
        score += 0.05
    return min(0.95, round(score, 2))


def _evidence(*, matched_fields: list[str], input_spec: dict[str, str]) -> list[str]:
    return [f"{field} matches: {input_spec[field]}" for field in matched_fields]


def _profile_matches_query(profile: ToolProfile, query: str) -> bool:
    haystack = " ".join(
        [
            profile.profile_id,
            " ".join(profile.tool_names),
            " ".join(profile.preferred_wrapper_paths),
        ]
    ).lower()
    return query in haystack
