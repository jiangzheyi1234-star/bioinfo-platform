"""Search and summarize the Snakemake wrapper catalog."""

from __future__ import annotations

from typing import Any

from .candidate import normalize_tool_name
from .index import wrapper_index
from .package_metadata import wrapper_source_ref


MAX_WRAPPER_MATCHES_PER_TOOL = 8


def find_snakemake_wrappers_for_tool(tool_name: str) -> list[dict[str, Any]]:
    normalized = normalize_tool_name(tool_name)
    if not normalized:
        return []
    index = wrapper_index()
    return list(index.get(normalized, []))[:MAX_WRAPPER_MATCHES_PER_TOOL]


def catalog_snakemake_wrappers(*, query: str = "", page: int = 1, page_size: int = 50) -> dict[str, Any]:
    normalized_query = normalize_tool_name(query)
    bounded_page = max(1, int(page or 1))
    bounded_page_size = max(1, min(int(page_size or 50), 100))
    items = _catalog_items(wrapper_index(), query=normalized_query)
    total = len(items)
    addable_total = sum(1 for item in items if _is_addable_wrapper(item))
    offset = (bounded_page - 1) * bounded_page_size
    return {
        "items": items[offset : offset + bounded_page_size],
        "query": normalized_query,
        "total": total,
        "page": bounded_page,
        "pageSize": bounded_page_size,
        "hasMore": offset + bounded_page_size < total,
        "addableTotal": addable_total,
        "qualityCounts": {
            "discovered": total,
            "draftRunnable": addable_total,
            "workflowReady": 0,
            "productionEnabled": 0,
        },
        "sourceRef": wrapper_source_ref(),
    }


def _catalog_items(index: dict[str, list[dict[str, Any]]], *, query: str) -> list[dict[str, Any]]:
    items = [entry for entries in index.values() for entry in entries]
    if query:
        items = [entry for entry in items if _matches_query(entry, query)]
    return sorted(items, key=lambda entry: str(entry.get("wrapperPath") or ""))


def _matches_query(entry: dict[str, Any], query: str) -> bool:
    haystack = " ".join(
        str(entry.get(key) or "").lower()
        for key in ("name", "toolName", "wrapperPath", "wrapperIdentifier")
    )
    return query in haystack


def _is_addable_wrapper(entry: dict[str, Any]) -> bool:
    draft = entry.get("ruleSpecDraft")
    return isinstance(draft, dict) and draft.get("requiresUserCompletion") is False
