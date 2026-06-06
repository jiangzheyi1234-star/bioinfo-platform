"""Unified tool candidate catalog across package, wrapper, and profile sources."""

from __future__ import annotations

from typing import Any

from apps.api.snakemake_wrappers import catalog_snakemake_wrappers
from apps.api.tool_capabilities import search_tool_capabilities
from apps.api.tool_profile_catalog import catalog_tool_profiles


SOURCE_ORDER = {
    "h2ometa-tool-profile": 0,
    "snakemake-wrapper": 1,
    "conda-package": 2,
}


def search_tool_candidates(
    query: str,
    *,
    target_platform: str = "",
    page: int = 1,
    page_size: int = 50,
) -> dict[str, Any]:
    normalized_query = str(query or "").strip()
    bounded_page = max(1, int(page or 1))
    bounded_page_size = max(1, min(int(page_size or 50), 100))
    source_page_size = min(max(bounded_page * bounded_page_size, bounded_page_size), 100)
    profile_items = catalog_tool_profiles(query=normalized_query, page=1, page_size=source_page_size)["items"]
    wrapper_items = catalog_snakemake_wrappers(query=normalized_query, page=1, page_size=source_page_size)["items"]
    conda_items = _conda_candidate_items(
        normalized_query,
        target_platform=target_platform,
        page_size=source_page_size,
    )
    items = sorted(
        [*profile_items, *wrapper_items, *conda_items],
        key=lambda item: (SOURCE_ORDER.get(str(item.get("candidateKind") or ""), 99), str(item.get("candidateId") or "")),
    )
    offset = (bounded_page - 1) * bounded_page_size
    return {
        "items": items[offset : offset + bounded_page_size],
        "query": normalized_query,
        "total": len(items),
        "page": bounded_page,
        "pageSize": bounded_page_size,
        "hasMore": offset + bounded_page_size < len(items),
        "sourceCounts": {
            "condaPackages": len(conda_items),
            "snakemakeWrappers": len(wrapper_items),
            "toolProfiles": len(profile_items),
        },
        "qualityCounts": _quality_counts(items),
    }


def _conda_candidate_items(query: str, *, target_platform: str, page_size: int) -> list[dict[str, Any]]:
    if not query:
        return []
    payload = search_tool_capabilities(
        query,
        target_platform=target_platform,
        limit=page_size,
        page=1,
        page_size=page_size,
    )
    data = payload.get("data") if isinstance(payload, dict) else None
    items = data.get("items") if isinstance(data, dict) else None
    return [item for item in items if isinstance(item, dict)] if isinstance(items, list) else []


def _quality_counts(items: list[dict[str, Any]]) -> dict[str, int]:
    counts = {
        "discovered": 0,
        "draftRunnable": 0,
        "workflowReady": 0,
        "productionEnabled": 0,
    }
    for item in items:
        tier = str(item.get("qualityTier") or "discovered")
        if tier == "production-enabled":
            counts["productionEnabled"] += 1
        elif tier == "workflow-ready":
            counts["workflowReady"] += 1
        elif tier == "draft-runnable":
            counts["draftRunnable"] += 1
        else:
            counts["discovered"] += 1
    return counts
