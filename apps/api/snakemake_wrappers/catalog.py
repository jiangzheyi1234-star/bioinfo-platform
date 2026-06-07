"""Search and summarize the Snakemake wrapper catalog."""

from __future__ import annotations

from typing import Any

from apps.api.tool_candidate_model import snakemake_wrapper_candidate_fields

from .candidate import normalize_tool_name
from .index import wrapper_index
from .metadata import wrapper_contract_hints
from .package_metadata import wrapper_source_ref


MAX_WRAPPER_MATCHES_PER_TOOL = 8


def find_snakemake_wrappers_for_tool(tool_name: str) -> list[dict[str, Any]]:
    normalized = normalize_tool_name(tool_name)
    if not normalized:
        return []
    index = wrapper_index()
    return [
        _with_wrapper_contract_hints(entry)
        for entry in list(index.get(normalized, []))[:MAX_WRAPPER_MATCHES_PER_TOOL]
    ]


def catalog_snakemake_wrappers(*, query: str = "", page: int = 1, page_size: int = 50) -> dict[str, Any]:
    normalized_query = normalize_tool_name(query)
    bounded_page = max(1, int(page or 1))
    bounded_page_size = max(1, min(int(page_size or 50), 100))
    items = _catalog_items(wrapper_index(), query=normalized_query)
    total = len(items)
    addable_total = sum(1 for item in items if _has_addable_wrapper_draft(item))
    draft_runnable_total = sum(1 for item in items if _is_draft_runnable_wrapper(item))
    offset = (bounded_page - 1) * bounded_page_size
    page_items = [_with_wrapper_contract_hints(item) for item in items[offset : offset + bounded_page_size]]
    return {
        "items": page_items,
        "query": normalized_query,
        "total": total,
        "page": bounded_page,
        "pageSize": bounded_page_size,
        "hasMore": offset + bounded_page_size < total,
        "addableTotal": addable_total,
        "qualityCounts": {
            "discovered": total,
            "draftRunnable": draft_runnable_total,
            "workflowReady": 0,
            "productionEnabled": 0,
        },
        "sourceRef": wrapper_source_ref(),
    }


def _catalog_items(index: dict[str, list[dict[str, Any]]], *, query: str) -> list[dict[str, Any]]:
    items = [_with_candidate_fields(entry) for entries in index.values() for entry in entries]
    if query:
        items = [entry for entry in items if _matches_query(entry, query)]
    return sorted(items, key=lambda entry: str(entry.get("wrapperPath") or ""))


def _matches_query(entry: dict[str, Any], query: str) -> bool:
    haystack = " ".join(
        str(entry.get(key) or "").lower()
        for key in ("name", "toolName", "wrapperPath", "wrapperIdentifier")
    )
    return query in haystack


def _has_addable_wrapper_draft(entry: dict[str, Any]) -> bool:
    draft = entry.get("ruleSpecDraft")
    template = draft.get("ruleTemplate") if isinstance(draft, dict) else None
    wrapper = str(template.get("wrapper") or "").strip() if isinstance(template, dict) else ""
    return bool(wrapper)


def _is_draft_runnable_wrapper(entry: dict[str, Any]) -> bool:
    draft = entry.get("ruleSpecDraft")
    return isinstance(draft, dict) and draft.get("requiresUserCompletion") is False


def _with_candidate_fields(entry: dict[str, Any]) -> dict[str, Any]:
    if entry.get("candidateKind") == "snakemake-wrapper" and entry.get("candidateId"):
        return entry
    return {
        **entry,
        **snakemake_wrapper_candidate_fields(entry),
    }


def _with_wrapper_contract_hints(entry: dict[str, Any]) -> dict[str, Any]:
    hints = wrapper_contract_hints(str(entry.get("wrapperPath") or ""))
    if not hints:
        return entry
    enriched = {**entry, "wrapperContractHints": hints}
    prepare_payload = _wrapper_prepare_payload(enriched)
    if prepare_payload is not None:
        enriched["preparePayload"] = prepare_payload
    return enriched


def _wrapper_prepare_payload(entry: dict[str, Any]) -> dict[str, Any] | None:
    draft = entry.get("ruleSpecDraft") if isinstance(entry.get("ruleSpecDraft"), dict) else {}
    template = draft.get("ruleTemplate") if isinstance(draft.get("ruleTemplate"), dict) else {}
    if not str(template.get("wrapper") or "").strip():
        return None
    dependency = _wrapper_primary_dependency(entry)
    if dependency is None:
        return None
    source = dependency["source"]
    name = dependency["name"]
    version = dependency["version"]
    package_spec = f"{source}::{name}={version}" if version else f"{source}::{name}"
    wrapper_match = {
        key: entry.get(key)
        for key in (
            "candidateId",
            "candidateKind",
            "qualityTier",
            "sourceRef",
            "name",
            "toolName",
            "wrapperRepository",
            "wrapperRef",
            "wrapperPath",
            "wrapperIdentifier",
            "wrapperUrl",
            "environmentUrl",
            "ruleSpecDraft",
        )
        if entry.get(key) is not None
    }
    return {
        "id": f"{source}::{name}",
        "name": name,
        "source": source,
        "sourceLabel": "Bioconda" if source == "bioconda" else "conda-forge",
        "version": version,
        "latestVersion": version,
        "packageSpec": package_spec,
        "targetPlatform": "linux-64",
        "targetPlatformSupported": True,
        "sourceUrl": str(entry.get("wrapperUrl") or ""),
        "snakemakeWrappers": [wrapper_match],
        "snakemakeWrapperCount": 1,
        "ruleTemplate": dict(template),
        "ruleSpecDraft": dict(draft),
    }


def _wrapper_primary_dependency(entry: dict[str, Any]) -> dict[str, str] | None:
    hints = entry.get("wrapperContractHints") if isinstance(entry.get("wrapperContractHints"), dict) else {}
    environment = hints.get("environment") if isinstance(hints.get("environment"), dict) else {}
    conda = environment.get("conda") if isinstance(environment.get("conda"), dict) else {}
    channels = [str(item).strip() for item in conda.get("channels", []) if str(item or "").strip()]
    dependencies = [str(item).strip() for item in conda.get("dependencies", []) if str(item or "").strip()]
    preferred_name = normalize_tool_name(str(entry.get("toolName") or entry.get("name") or ""))
    parsed = [_parse_conda_dependency(dependency, channels=channels) for dependency in dependencies]
    candidates = [dependency for dependency in parsed if dependency is not None]
    if not candidates:
        return None
    for dependency in candidates:
        if normalize_tool_name(dependency["name"]) == preferred_name:
            return dependency
    for dependency in candidates:
        if normalize_tool_name(dependency["name"]) != "snakemake-wrapper-utils":
            return dependency
    return candidates[0]


def _parse_conda_dependency(raw: str, *, channels: list[str]) -> dict[str, str] | None:
    text = str(raw or "").strip()
    if not text:
        return None
    source = ""
    if "::" in text:
        source, text = [part.strip() for part in text.split("::", 1)]
    if source not in {"bioconda", "conda-forge"}:
        source = "bioconda" if "bioconda" in channels else "conda-forge"
    normalized = " ".join(text.replace("==", "=").split())
    name = normalized
    version = ""
    if "=" in normalized:
        name, version = [part.strip() for part in normalized.split("=", 1)]
    if not name or name.startswith("-"):
        return None
    return {"source": source, "name": name, "version": version}
