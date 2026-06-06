"""Semantic recommendations over tool candidates with declared rule ports."""

from __future__ import annotations

from typing import Any

from apps.api.tool_candidate_model import tool_profile_candidate_fields
from apps.api.tool_profile_model import ToolProfile
from apps.api.tool_profile_registry import TOOL_PROFILES
from apps.remote_runner.rule_ports import (
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
) -> dict[str, Any]:
    normalized_query = str(query or "").strip().lower()
    bounded_page = max(1, int(page or 1))
    bounded_page_size = max(1, min(int(page_size or 20), 100))
    output_spec = port_spec_from_rule_item(output_port)
    items = sorted(
        _profile_recommendations(output_spec=output_spec, query=normalized_query),
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


def _profile_recommendations(*, output_spec: dict[str, str], query: str) -> list[dict[str, Any]]:
    recommendations: list[dict[str, Any]] = []
    for profile in TOOL_PROFILES:
        if query and not _profile_matches_query(profile, query):
            continue
        for input_port in _input_ports(profile):
            input_spec = port_spec_from_rule_item(input_port)
            if mismatched_compatibility_field(input_spec, output_spec):
                continue
            matched_fields = matched_compatibility_fields(input_spec, output_spec)
            if not matched_fields:
                continue
            recommendations.append(
                {
                    "decision": "recommended",
                    "candidate": _profile_candidate(profile),
                    "executionGate": _execution_gate(profile),
                    "inputPort": _input_port_summary(input_port, input_spec),
                    "matchedFields": matched_fields,
                    "confidence": _confidence(matched_fields=matched_fields, input_port=input_port),
                    "hardChecks": ["端口方向 output -> input", "类型字段无冲突"],
                    "evidence": _evidence(matched_fields=matched_fields, input_spec=input_spec),
                }
            )
    return recommendations


def _profile_candidate(profile: ToolProfile) -> dict[str, Any]:
    return {
        "profileId": profile.profile_id,
        "profileVersion": profile.version,
        "toolNames": list(profile.tool_names),
        "preferredWrapperPaths": list(profile.preferred_wrapper_paths),
        **tool_profile_candidate_fields(profile),
    }


def _execution_gate(profile: ToolProfile) -> dict[str, Any]:
    candidate = _profile_candidate(profile)
    return {
        "currentState": candidate.get("contractState") or "Discovered",
        "requiredState": "WorkflowReady",
        "canAddStep": False,
        "nextAction": "prepare-tool",
        "reason": "WORKFLOW_TOOL_NOT_READY",
    }


def _input_ports(profile: ToolProfile) -> list[dict[str, Any]]:
    return [item for item in profile.rule_template.get("inputs") or [] if isinstance(item, dict)]


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
