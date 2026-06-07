"""Unified tool candidate catalog across package, wrapper, and profile sources."""

from __future__ import annotations

from typing import Any

from apps.api.bioconda_tool_index import get_bioconda_index_cache_dir, search_bioconda_index_page
from apps.api.snakemake_wrappers import catalog_snakemake_wrappers, find_snakemake_wrappers_for_tool
from apps.api.tool_candidate_model import conda_tool_candidate_fields
from apps.api.tool_capability_anaconda import (
    CondaPackageHit,
    normalize_target_platform,
    package_spec,
    platform_supported,
)
from apps.api.tool_contract_resolver import DEFAULT_TOOL_CONTRACT_RESOLVER
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
    conda_addable_total = _source_addable_total(conda_catalog, conda_items)
    wrapper_addable_total = _source_addable_total(wrapper_catalog, wrapper_items)
    profile_addable_total = _source_addable_total(profile_catalog, profile_items)
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
        "addableDraftCounts": {
            "condaPackages": conda_addable_total,
            "snakemakeWrappers": wrapper_addable_total,
            "toolProfiles": profile_addable_total,
            "total": conda_addable_total + wrapper_addable_total + profile_addable_total,
        },
        "qualityCounts": _merge_quality_counts(
            _quality_counts_from_source(conda_catalog, conda_items),
            _quality_counts_from_source(wrapper_catalog, wrapper_items),
            _quality_counts_from_source(profile_catalog, profile_items),
        ),
    }


def _conda_candidate_catalog(query: str, *, target_platform: str, page_size: int) -> dict[str, Any]:
    return catalog_conda_package_candidates(
        query=query,
        target_platform=target_platform,
        page=1,
        page_size=page_size,
    )


def catalog_conda_package_candidates(
    *,
    query: str,
    target_platform: str = "",
    page: int = 1,
    page_size: int = 50,
) -> dict[str, Any]:
    normalized_query = str(query or "").strip().lower()
    normalized_target_platform = normalize_target_platform(target_platform)
    bounded_page = max(1, int(page or 1))
    bounded_page_size = max(1, min(int(page_size or 50), 100))
    index_page = search_bioconda_index_page(
        normalized_query,
        page=bounded_page,
        page_size=bounded_page_size,
        cache_dir=get_bioconda_index_cache_dir(),
    )
    records = index_page.get("items")
    if not isinstance(records, list):
        records = []
    items = [
        _conda_candidate_from_index_record(record, target_platform=normalized_target_platform)
        for record in records
        if isinstance(record, dict)
    ]
    total = _count_value(index_page.get("total"))
    addable_total = _conda_addable_total(
        total=total,
        items=items,
        target_platform=normalized_target_platform,
    )
    quality_counts = _quality_counts(items)
    quality_counts["discovered"] = total
    return {
        "items": items,
        "query": normalized_query,
        "total": total,
        "addableTotal": addable_total,
        "page": int(index_page.get("page") or bounded_page),
        "pageSize": int(index_page.get("pageSize") or bounded_page_size),
        "hasMore": bool(index_page.get("hasMore")),
        "localIndexAvailable": bool(index_page.get("indexAvailable")),
        "qualityCounts": quality_counts,
        "sourceRef": {
            "type": "bioconda-index",
            "channel": "bioconda",
        },
    }


def _conda_addable_total(*, total: int, items: list[dict[str, Any]], target_platform: str) -> int:
    if not target_platform or target_platform == "linux-64":
        return total
    return sum(1 for item in items if _is_addable_draft(item))


def _conda_candidate_from_index_record(record: dict[str, Any], *, target_platform: str) -> dict[str, Any]:
    name = str(record.get("name") or "").strip()
    latest_version = str(record.get("latestVersion") or "").strip()
    versions = [str(item).strip() for item in record.get("versions", []) if str(item or "").strip()]
    platforms = [str(item).strip() for item in record.get("platforms", []) if str(item or "").strip()]
    hit = CondaPackageHit(
        name=name,
        channel="bioconda",
        summary=str(record.get("summary") or "Conda package"),
        latest_version=latest_version,
        versions=versions,
        package_spec=package_spec("bioconda", name, latest_version),
        source_url=f"https://anaconda.org/bioconda/{name}",
        platforms=platforms,
        target_platform=target_platform,
        target_platform_supported=platform_supported(platforms, target_platform),
    ).to_dict()
    hit["cached"] = True
    wrappers = find_snakemake_wrappers_for_tool(name)
    first_wrapper_draft = _first_wrapper_rule_spec_draft(wrappers)
    dependency_draft = DEFAULT_TOOL_CONTRACT_RESOLVER.resolve_dependency(hit, wrappers=wrappers)
    rule_spec_draft = _preferred_rule_spec_draft(dependency_draft, first_wrapper_draft)
    candidate = {
        **hit,
        "snakemakeWrappers": wrappers,
        "snakemakeWrapperCount": len(wrappers),
        "ruleSpecDraft": rule_spec_draft,
        **conda_tool_candidate_fields(hit, rule_spec_draft=rule_spec_draft),
    }
    prepare_payload = _conda_prepare_payload(hit, rule_spec_draft=rule_spec_draft, wrappers=wrappers)
    if prepare_payload is not None:
        candidate["preparePayload"] = prepare_payload
    return candidate


def _first_wrapper_rule_spec_draft(wrappers: list[dict[str, Any]]) -> dict[str, Any] | None:
    for wrapper in wrappers:
        draft = wrapper.get("ruleSpecDraft")
        if isinstance(draft, dict):
            return draft
    return None


def _preferred_rule_spec_draft(dependency_draft: dict[str, Any], wrapper_draft: dict[str, Any] | None) -> dict[str, Any]:
    if dependency_draft.get("requiresUserCompletion") is False:
        return dependency_draft
    return wrapper_draft or dependency_draft


def _conda_prepare_payload(
    tool: dict[str, Any],
    *,
    rule_spec_draft: dict[str, Any],
    wrappers: list[dict[str, Any]],
) -> dict[str, Any] | None:
    if rule_spec_draft.get("requiresUserCompletion") is not False:
        return None
    rule_template = rule_spec_draft.get("ruleTemplate")
    if not isinstance(rule_template, dict):
        return None
    return {
        "id": str(tool.get("id") or "").strip(),
        "name": str(tool.get("name") or "").strip(),
        "source": str(tool.get("source") or "").strip(),
        "sourceLabel": str(tool.get("sourceLabel") or "").strip(),
        "version": str(tool.get("latestVersion") or "").strip(),
        "latestVersion": str(tool.get("latestVersion") or "").strip(),
        "packageSpec": str(tool.get("packageSpec") or "").strip(),
        "targetPlatform": str(tool.get("targetPlatform") or "").strip(),
        "targetPlatformSupported": bool(tool.get("targetPlatformSupported")),
        "platforms": [str(item).strip() for item in tool.get("platforms", []) if str(item or "").strip()],
        "sourceUrl": str(tool.get("sourceUrl") or "").strip(),
        "capabilities": list(tool.get("capabilities") or []),
        "snakemakeWrappers": wrappers,
        "snakemakeWrapperCount": len(wrappers),
        "ruleTemplate": dict(rule_template),
        "ruleSpecDraft": dict(rule_spec_draft),
    }


def _payload_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    items = payload.get("items") if isinstance(payload, dict) else None
    return [item for item in items if isinstance(item, dict)] if isinstance(items, list) else []


def _source_total(payload: dict[str, Any], items: list[dict[str, Any]]) -> int:
    try:
        return max(0, int(payload.get("total", len(items))))
    except (TypeError, ValueError):
        return len(items)


def _source_addable_total(payload: dict[str, Any], items: list[dict[str, Any]]) -> int:
    if "addableTotal" in payload:
        return _count_value(payload.get("addableTotal"))
    return sum(1 for item in items if _is_addable_draft(item))


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


def _is_addable_draft(item: dict[str, Any]) -> bool:
    kind = str(item.get("candidateKind") or "")
    if kind == "h2ometa-tool-profile":
        return True
    if kind == "snakemake-wrapper":
        draft = item.get("ruleSpecDraft")
        return isinstance(draft, dict) and draft.get("requiresUserCompletion") is False
    if kind == "conda-package":
        package_spec = str(item.get("packageSpec") or "")
        return item.get("targetPlatformSupported") is True and "=" in package_spec
    return False
