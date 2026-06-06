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
QUALITY_COUNT_KEYS = (
    "discovered",
    "draftRunnable",
    "workflowReady",
    "productionEnabled",
)


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
    profile_catalog = catalog_tool_profiles(query=normalized_query, page=1, page_size=source_page_size)
    wrapper_catalog = catalog_snakemake_wrappers(query=normalized_query, page=1, page_size=source_page_size)
    conda_catalog = _conda_candidate_catalog(
        normalized_query,
        target_platform=target_platform,
        page_size=source_page_size,
    )
    profile_items = _payload_items(profile_catalog)
    wrapper_items = _payload_items(wrapper_catalog)
    conda_items = _payload_items(conda_catalog)
    items = sorted(
        [*profile_items, *wrapper_items, *conda_items],
        key=lambda item: (SOURCE_ORDER.get(str(item.get("candidateKind") or ""), 99), str(item.get("candidateId") or "")),
    )
    offset = (bounded_page - 1) * bounded_page_size
    conda_total = _source_total(conda_catalog, conda_items)
    wrapper_total = _source_total(wrapper_catalog, wrapper_items)
    profile_total = _source_total(profile_catalog, profile_items)
    total = conda_total + wrapper_total + profile_total
    return {
        "items": items[offset : offset + bounded_page_size],
        "query": normalized_query,
        "total": total,
        "page": bounded_page,
        "pageSize": bounded_page_size,
        "hasMore": offset + bounded_page_size < total,
        "sourceCounts": {
            "condaPackages": conda_total,
            "snakemakeWrappers": wrapper_total,
            "toolProfiles": profile_total,
        },
        "qualityCounts": _merge_quality_counts(
            _quality_counts_from_source(conda_catalog, conda_items),
            _quality_counts_from_source(wrapper_catalog, wrapper_items),
            _quality_counts_from_source(profile_catalog, profile_items),
        ),
    }


def _conda_candidate_catalog(query: str, *, target_platform: str, page_size: int) -> dict[str, Any]:
    if not query:
        return {"items": [], "total": 0}
    payload = search_tool_capabilities(
        query,
        target_platform=target_platform,
        limit=page_size,
        page=1,
        page_size=page_size,
    )
    data = payload.get("data") if isinstance(payload, dict) else None
    return data if isinstance(data, dict) else {"items": [], "total": 0}


def _payload_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    items = payload.get("items") if isinstance(payload, dict) else None
    return [item for item in items if isinstance(item, dict)] if isinstance(items, list) else []


def _source_total(payload: dict[str, Any], items: list[dict[str, Any]]) -> int:
    try:
        return max(0, int(payload.get("total", len(items))))
    except (TypeError, ValueError):
        return len(items)


def _quality_counts_from_source(payload: dict[str, Any], items: list[dict[str, Any]]) -> dict[str, int]:
    quality_counts = payload.get("qualityCounts") if isinstance(payload, dict) else None
    if isinstance(quality_counts, dict):
        return {key: _count_value(quality_counts.get(key)) for key in QUALITY_COUNT_KEYS}
    return _quality_counts(items)


def _merge_quality_counts(*groups: dict[str, int]) -> dict[str, int]:
    return {key: sum(group.get(key, 0) for group in groups) for key in QUALITY_COUNT_KEYS}


def _count_value(value: Any) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _quality_counts(items: list[dict[str, Any]]) -> dict[str, int]:
    counts = {key: 0 for key in QUALITY_COUNT_KEYS}
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
