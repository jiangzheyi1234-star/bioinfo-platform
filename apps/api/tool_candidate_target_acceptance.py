"""Acceptance metrics for the Bio Agent Tool Catalog v1 target."""

from __future__ import annotations

from typing import Any

from apps.api.tool_candidate_catalog import search_tool_candidates
from apps.api.tool_profile_catalog import catalog_tool_profiles


CATALOG_TARGETS = {
    "discovered": 500,
    "addableDraft": 100,
    "snakemakeRenderable": 20,
    "workflowReady": 30,
    "productionEnabled": 10,
}


def bio_agent_catalog_target_acceptance(*, target_platform: str = "linux-64") -> dict[str, Any]:
    normalized_target_platform = str(target_platform or "linux-64").strip() or "linux-64"
    catalog = search_tool_candidates(
        "",
        target_platform=normalized_target_platform,
        page=1,
        page_size=1,
    )
    profile_catalog = catalog_tool_profiles(query="", page=1, page_size=100)
    quality_counts = _record_value(catalog.get("qualityCounts"))
    addable_counts = _record_value(catalog.get("addableDraftCounts"))
    targets = {
        "discovered": _target_result(actual=_count_value(quality_counts.get("discovered")), target=CATALOG_TARGETS["discovered"]),
        "addableDraft": _target_result(actual=_count_value(addable_counts.get("total")), target=CATALOG_TARGETS["addableDraft"]),
        "snakemakeRenderable": _target_result(
            actual=_contract_state_count(profile_catalog, "SnakemakeRenderable"),
            target=CATALOG_TARGETS["snakemakeRenderable"],
        ),
        "workflowReady": _target_result(actual=_count_value(quality_counts.get("workflowReady")), target=CATALOG_TARGETS["workflowReady"]),
        "productionEnabled": _target_result(
            actual=_count_value(quality_counts.get("productionEnabled")),
            target=CATALOG_TARGETS["productionEnabled"],
        ),
    }
    blocked_targets = [name for name, result in targets.items() if result["passed"] is not True]
    return {
        "targetName": "Bio Agent Tool Catalog & Recommendation v1",
        "targetPlatform": normalized_target_platform,
        "complete": not blocked_targets,
        "blockedTargets": blocked_targets,
        "nextActions": [_next_action(name, targets[name]) for name in blocked_targets],
        "targets": targets,
        "catalog": {
            "total": _count_value(catalog.get("total")),
            "sourceCounts": _record_value(catalog.get("sourceCounts")),
            "addableDraftCounts": addable_counts,
            "qualityCounts": quality_counts,
        },
    }


def _target_result(*, actual: int, target: int) -> dict[str, Any]:
    return {
        "target": target,
        "actual": actual,
        "passed": actual >= target,
        "remaining": max(0, target - actual),
    }


def _next_action(target_name: str, result: dict[str, Any]) -> dict[str, Any]:
    remaining = _count_value(result.get("remaining"))
    if target_name == "workflowReady":
        return {
            "target": target_name,
            "remaining": remaining,
            "action": "prepare-and-validate-tool-contracts",
            "requiredState": "WorkflowReady",
            "evidence": "Snakemake dry-run, smoke run, and output validation evidence",
        }
    if target_name == "productionEnabled":
        return {
            "target": target_name,
            "remaining": remaining,
            "action": "promote-workflow-ready-tools-with-production-evidence",
            "requiredState": "ProductionEnabled",
            "evidence": "Scoped production attestation for tool revision, platform, environment, data scope, and policy",
        }
    return {
        "target": target_name,
        "remaining": remaining,
        "action": "expand-catalog-source-coverage",
        "requiredState": target_name,
        "evidence": "Catalog source counts and candidate quality counts",
    }


def _contract_state_count(catalog: dict[str, Any], state: str) -> int:
    items = catalog.get("items")
    if not isinstance(items, list):
        return 0
    return sum(1 for item in items if isinstance(item, dict) and item.get("contractState") == state)


def _record_value(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _count_value(value: Any) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0
