"""Catalog curated H2OMeta tool profiles as tool candidates."""

from __future__ import annotations

import re
from typing import Any

from apps.api.tool_candidate_model import tool_profile_candidate_fields
from apps.api.tool_profile_external_refs import profile_external_candidate_fields
from apps.api.tool_profile_model import ToolProfile
from apps.api.tool_profile_registry import TOOL_PROFILES


def catalog_tool_profiles(*, query: str = "", page: int = 1, page_size: int = 50) -> dict[str, Any]:
    normalized_query = _normalize_query(query)
    bounded_page = max(1, int(page or 1))
    bounded_page_size = max(1, min(int(page_size or 50), 100))
    all_items = [_profile_candidate(profile) for profile in TOOL_PROFILES]
    matched_items = [item for item in all_items if _matches_query(item, normalized_query)] if normalized_query else all_items
    matched_items.sort(key=lambda item: str(item.get("profileId") or ""))
    offset = (bounded_page - 1) * bounded_page_size
    total = len(matched_items)
    return {
        "items": matched_items[offset : offset + bounded_page_size],
        "query": normalized_query,
        "total": total,
        "page": bounded_page,
        "pageSize": bounded_page_size,
        "hasMore": offset + bounded_page_size < total,
        "addableTotal": total,
        "qualityCounts": {
            "discovered": len(all_items),
            "draftRunnable": len(all_items),
            "workflowReady": 0,
            "productionEnabled": 0,
        },
        "sourceRef": {
            "type": "h2ometa-tool-profile-registry",
            "profileCount": str(len(all_items)),
        },
    }


def _profile_candidate(profile: ToolProfile) -> dict[str, Any]:
    return {
        "profileId": profile.profile_id,
        "profileVersion": profile.version,
        "toolNames": list(profile.tool_names),
        "preferredWrapperPaths": list(profile.preferred_wrapper_paths),
        **profile_external_candidate_fields(profile),
        **tool_profile_candidate_fields(profile),
    }


def _matches_query(item: dict[str, Any], query: str) -> bool:
    haystack = " ".join(
        [
            str(item.get("profileId") or ""),
            " ".join(str(value) for value in item.get("toolNames") or []),
            " ".join(str(value) for value in item.get("preferredWrapperPaths") or []),
        ]
    ).lower()
    return query in haystack


def _normalize_query(query: str) -> str:
    return re.sub(r"[^a-z0-9.+-]+", "-", str(query or "").strip().lower()).strip("-")
