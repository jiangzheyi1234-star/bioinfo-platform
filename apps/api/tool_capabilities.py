"""Online tool capability search for conda package sources."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

from apps.api.bioconda_tool_index import get_bioconda_index_cache_dir, search_bioconda_index_page
from apps.api.snakemake_wrappers import find_snakemake_wrappers_for_tool
from apps.api.tool_contract_resolver import DEFAULT_TOOL_CONTRACT_RESOLVER


ANACONDA_SEARCH_URL = "https://api.anaconda.org/search"
ANACONDA_PACKAGE_URL = "https://api.anaconda.org/package"
SUPPORTED_CHANNELS = ("bioconda", "conda-forge")
CACHE_TTL_SECONDS = 300
ANACONDA_TOTAL_SEARCH_TIMEOUT_SECONDS = 30.0
ANACONDA_SEARCH_TIMEOUT_SECONDS = 20.0
ANACONDA_EXACT_LOOKUP_TIMEOUT_SECONDS = 5.0
ONLINE_SEARCH_RESULT_LIMIT = 200

_CACHE: dict[str, tuple[float, list[dict[str, Any]]]] = {}


@dataclass(frozen=True)
class CondaPackageHit:
    name: str
    channel: str
    summary: str
    latest_version: str
    versions: list[str]
    package_spec: str
    source_url: str
    platforms: list[str]
    target_platform: str
    target_platform_supported: bool

    def to_dict(self) -> dict[str, Any]:
        source_label = "Bioconda" if self.channel == "bioconda" else "conda-forge"
        return {
            "id": f"{self.channel}::{self.name}",
            "name": self.name,
            "summary": self.summary,
            "source": self.channel,
            "sourceLabel": source_label,
            "category": "在线工具",
            "tasks": [],
            "packageSpec": self.package_spec,
            "latestVersion": self.latest_version,
            "versions": self.versions,
            "targetModule": "选择流程后配置",
            "envPath": "envs/<module>.yaml",
            "sourceUrl": self.source_url,
            "platforms": self.platforms,
            "targetPlatform": self.target_platform,
            "targetPlatformSupported": self.target_platform_supported,
            "capabilities": [],
            "online": True,
        }


def search_tool_capabilities(
    query: str,
    *,
    target_platform: str = "",
    limit: int = 20,
    page: int = 1,
    page_size: int | None = None,
) -> dict[str, Any]:
    normalized = _normalize_query(query)
    normalized_target_platform = _normalize_target_platform(target_platform)
    bounded_page = max(1, int(page or 1))
    bounded_page_size = max(1, min(int(page_size or limit or 20), 100))
    if len(normalized) < 1:
        return {
            "data": {
                "items": [],
                "query": normalized,
                "online": True,
                "total": 0,
                "page": bounded_page,
                "pageSize": bounded_page_size,
                "hasMore": False,
            }
        }
    index_page = _search_bioconda_index_items(
        normalized,
        target_platform=normalized_target_platform,
        page=bounded_page,
        page_size=bounded_page_size,
    )
    if index_page["total"] > 0:
        items = _attach_snakemake_wrappers(index_page["items"])
        return {
            "data": {
                "items": items,
                "query": normalized,
                "online": False,
                "cached": True,
                "source": "bioconda-index",
                "complete": True,
                "total": index_page["total"],
                "page": index_page["page"],
                "pageSize": index_page["pageSize"],
                "hasMore": index_page["hasMore"],
                "localIndexAvailable": bool(index_page.get("indexAvailable")),
            }
        }

    cache_key = f"{normalized}:{normalized_target_platform}"
    cached = _CACHE.get(cache_key)
    now = time.time()
    if cached and now - cached[0] < CACHE_TTL_SECONDS:
        all_items = cached[1]
        items = _page_items(all_items, page=bounded_page, page_size=bounded_page_size)
        return {
            "data": {
                "items": items,
                "query": normalized,
                "online": True,
                "cached": True,
                "complete": False,
                "total": len(all_items),
                "page": bounded_page,
                "pageSize": bounded_page_size,
                "hasMore": bounded_page * bounded_page_size < len(all_items),
                "localIndexAvailable": bool(index_page.get("indexAvailable")),
            }
        }

    try:
        hits = _search_anaconda(
            normalized,
            target_platform=normalized_target_platform,
            limit=ONLINE_SEARCH_RESULT_LIMIT,
        )
    except urllib.error.HTTPError as exc:
        if exc.code != 403:
            raise
        return _online_search_unavailable_response(
            query=normalized,
            page=bounded_page,
            page_size=bounded_page_size,
            index_available=bool(index_page.get("indexAvailable")),
            reason="ANACONDA_RATE_LIMITED",
        )
    all_items = [hit.to_dict() for hit in hits[:ONLINE_SEARCH_RESULT_LIMIT]]
    all_items = _attach_snakemake_wrappers(all_items)
    _CACHE[cache_key] = (now, all_items)
    items = _page_items(all_items, page=bounded_page, page_size=bounded_page_size)
    return {
        "data": {
            "items": items,
            "query": normalized,
            "online": True,
            "cached": False,
            "complete": False,
            "total": len(all_items),
            "page": bounded_page,
            "pageSize": bounded_page_size,
            "hasMore": bounded_page * bounded_page_size < len(all_items),
            "localIndexAvailable": bool(index_page.get("indexAvailable")),
        }
    }


def _attach_snakemake_wrappers(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    enriched: list[dict[str, Any]] = []
    for item in items:
        tool_name = str(item.get("name") or "").strip()
        wrappers = find_snakemake_wrappers_for_tool(tool_name)
        first_wrapper_draft = _first_wrapper_rule_spec_draft(wrappers)
        dependency_draft = DEFAULT_TOOL_CONTRACT_RESOLVER.resolve_dependency(item, wrappers=wrappers)
        enriched.append(
            {
                **item,
                "snakemakeWrappers": wrappers,
                "snakemakeWrapperCount": len(wrappers),
                "ruleSpecDraft": _preferred_rule_spec_draft(dependency_draft, first_wrapper_draft),
            }
        )
    return enriched


def _online_search_unavailable_response(
    *,
    query: str,
    page: int,
    page_size: int,
    index_available: bool,
    reason: str,
) -> dict[str, Any]:
    return {
        "data": {
            "items": [],
            "query": query,
            "online": False,
            "cached": False,
            "complete": False,
            "total": 0,
            "page": page,
            "pageSize": page_size,
            "hasMore": False,
            "localIndexAvailable": index_available,
            "onlineUnavailableReason": reason,
        }
    }


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


def _normalize_query(query: str) -> str:
    return str(query or "").strip().lower()


def _search_bioconda_index_items(
    query: str,
    *,
    target_platform: str,
    page: int,
    page_size: int,
) -> dict[str, Any]:
    index_page = search_bioconda_index_page(
        query,
        page=page,
        page_size=page_size,
        cache_dir=get_bioconda_index_cache_dir(),
    )
    items: list[dict[str, Any]] = []
    records = index_page.get("items")
    if not isinstance(records, list):
        records = []
    for record in records:
        name = str(record.get("name") or "").strip()
        if not name:
            continue
        latest_version = str(record.get("latestVersion") or "").strip()
        versions = [str(item).strip() for item in record.get("versions", []) if str(item or "").strip()]
        platforms = [str(item).strip() for item in record.get("platforms", []) if str(item or "").strip()]
        hit = CondaPackageHit(
            name=name,
            channel="bioconda",
            summary=str(record.get("summary") or "Conda package"),
            latest_version=latest_version,
            versions=versions,
            package_spec=_package_spec("bioconda", name, latest_version),
            source_url=f"https://anaconda.org/bioconda/{name}",
            platforms=platforms,
            target_platform=target_platform,
            target_platform_supported=_platform_supported(platforms, target_platform),
        ).to_dict()
        hit["cached"] = True
        items.append(hit)
    return {
        "items": items,
        "total": int(index_page.get("total") or 0),
        "page": int(index_page.get("page") or page),
        "pageSize": int(index_page.get("pageSize") or page_size),
        "hasMore": bool(index_page.get("hasMore")),
        "indexAvailable": bool(index_page.get("indexAvailable")),
    }


def _page_items(items: list[dict[str, Any]], *, page: int, page_size: int) -> list[dict[str, Any]]:
    offset = (page - 1) * page_size
    return items[offset : offset + page_size]


def _search_anaconda(query: str, *, target_platform: str, limit: int) -> list[CondaPackageHit]:
    deadline = time.monotonic() + ANACONDA_TOTAL_SEARCH_TIMEOUT_SECONDS
    payload = _request_json(
        ANACONDA_SEARCH_URL,
        {
            "name": query,
        },
        timeout=_remaining_timeout(deadline, ANACONDA_SEARCH_TIMEOUT_SECONDS),
    )
    if not isinstance(payload, list):
        raise ValueError("ANACONDA_SEARCH_INVALID_RESPONSE")

    hits: list[CondaPackageHit] = []
    seen: set[tuple[str, str]] = set()
    for raw in payload:
        item = _parse_search_item(raw, target_platform=target_platform)
        if item is None:
            continue
        key = (item.channel, item.name)
        if key in seen:
            continue
        seen.add(key)
        hits.append(item)
        if len(hits) >= limit:
            break

    if hits:
        return hits

    return _search_exact_packages(
        query,
        target_platform=target_platform,
        deadline=deadline,
    )


def _parse_search_item(raw: Any, *, target_platform: str) -> CondaPackageHit | None:
    if not isinstance(raw, dict):
        return None
    channel = str(raw.get("owner") or raw.get("channel") or "").strip().lower()
    if channel not in SUPPORTED_CHANNELS:
        return None
    name = str(raw.get("name") or "").strip()
    if not name:
        return None
    summary = str(raw.get("summary") or raw.get("description") or "").strip()
    latest_version = _latest_version(raw)
    versions = _versions(raw)
    platforms = _platforms(raw)
    return CondaPackageHit(
        name=name,
        channel=channel,
        summary=summary or "Conda package",
        latest_version=latest_version,
        versions=versions,
        package_spec=_package_spec(channel, name, latest_version),
        source_url=f"https://anaconda.org/{channel}/{name}",
        platforms=platforms,
        target_platform=target_platform,
        target_platform_supported=_platform_supported(platforms, target_platform),
    )


def _latest_version(raw: dict[str, Any]) -> str:
    for key in ("latest_version", "latestVersion", "version"):
        value = str(raw.get(key) or "").strip()
        if value:
            return value
    versions = raw.get("versions")
    if isinstance(versions, list) and versions:
        return str(versions[-1] or "").strip()
    return ""


def _versions(raw: dict[str, Any]) -> list[str]:
    versions = raw.get("versions")
    if not isinstance(versions, list):
        return []
    return [str(item).strip() for item in versions if str(item or "").strip()]


def _package_spec(channel: str, name: str, version: str) -> str:
    if version:
        return f"{channel}::{name}={version}"
    return f"{channel}::{name}"


def _platforms(raw: dict[str, Any]) -> list[str]:
    conda_platforms = raw.get("conda_platforms")
    if isinstance(conda_platforms, list):
        return sorted({str(item).strip() for item in conda_platforms if str(item or "").strip()})

    platforms = raw.get("platforms")
    if isinstance(platforms, dict):
        return sorted({str(item).strip() for item in platforms.keys() if str(item or "").strip()})
    if isinstance(platforms, list):
        return sorted({str(item).strip() for item in platforms if str(item or "").strip()})

    files = raw.get("files")
    if isinstance(files, list):
        subdirs = set()
        for file_item in files:
            if not isinstance(file_item, dict):
                continue
            subdir = str(file_item.get("attrs", {}).get("subdir") or file_item.get("subdir") or "").strip()
            if subdir:
                subdirs.add(subdir)
        return sorted(subdirs)

    return []


def _normalize_target_platform(target_platform: str) -> str:
    return str(target_platform or "").strip().lower()


def _platform_supported(platforms: list[str], target_platform: str) -> bool:
    if not target_platform:
        return True
    if not platforms:
        return False
    return target_platform in platforms or "noarch" in platforms


def _remaining_timeout(deadline: float, request_timeout: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("ANACONDA_SEARCH_TIMEOUT")
    return min(request_timeout, remaining)


def _search_exact_packages(
    query: str,
    *,
    target_platform: str,
    deadline: float,
) -> list[CondaPackageHit]:
    hits: list[CondaPackageHit] = []
    for channel in SUPPORTED_CHANNELS:
        try:
            raw = _request_json(
                f"{ANACONDA_PACKAGE_URL}/{channel}/{urllib.parse.quote(query)}",
                {},
                timeout=_remaining_timeout(deadline, ANACONDA_EXACT_LOOKUP_TIMEOUT_SECONDS),
            )
        except urllib.error.HTTPError as exc:
            if exc.code != 404:
                raise
            continue
        if not isinstance(raw, dict):
            continue
        name = str(raw.get("name") or query).strip()
        latest_version = _latest_version(raw)
        versions = _versions(raw)
        summary = str(raw.get("summary") or raw.get("description") or "").strip()
        platforms = _platforms(raw)
        hits.append(
            CondaPackageHit(
                name=name,
                channel=channel,
                summary=summary or "Conda package",
                latest_version=latest_version,
                versions=versions,
                package_spec=_package_spec(channel, name, latest_version),
                source_url=f"https://anaconda.org/{channel}/{name}",
                platforms=platforms,
                target_platform=target_platform,
                target_platform_supported=_platform_supported(platforms, target_platform),
            )
        )
    return hits


def _request_json(url: str, params: dict[str, str], *, timeout: float) -> Any:
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "H2OMeta/0.1 tool-capability-search",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read().decode("utf-8", errors="replace")
    return json.loads(raw)
