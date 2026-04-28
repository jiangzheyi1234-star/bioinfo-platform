"""Online tool capability search for conda package sources."""

from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any


ANACONDA_SEARCH_URL = "https://api.anaconda.org/search"
ANACONDA_PACKAGE_URL = "https://api.anaconda.org/package"
SUPPORTED_CHANNELS = ("bioconda", "conda-forge")
DEFAULT_TARGET_PLATFORM = "linux-64"
CACHE_TTL_SECONDS = 300

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
            "online": True,
        }


def search_tool_capabilities(query: str, *, limit: int = 20) -> dict[str, Any]:
    normalized = _normalize_query(query)
    if len(normalized) < 2:
        return {"data": {"items": [], "query": normalized, "online": True}}
    cache_key = f"{normalized}:{limit}"
    cached = _CACHE.get(cache_key)
    now = time.time()
    if cached and now - cached[0] < CACHE_TTL_SECONDS:
        return {"data": {"items": cached[1], "query": normalized, "online": True, "cached": True}}

    hits = _search_anaconda(normalized, limit=limit)
    items = [hit.to_dict() for hit in hits[:limit]]
    _CACHE[cache_key] = (now, items)
    return {"data": {"items": items, "query": normalized, "online": True, "cached": False}}


def _normalize_query(query: str) -> str:
    return str(query or "").strip().lower()


def _search_anaconda(query: str, *, limit: int) -> list[CondaPackageHit]:
    payload = _request_json(
        ANACONDA_SEARCH_URL,
        {
            "name": query,
        },
        timeout=12,
    )
    if not isinstance(payload, list):
        raise ValueError("ANACONDA_SEARCH_INVALID_RESPONSE")

    hits: list[CondaPackageHit] = []
    seen: set[tuple[str, str]] = set()
    for raw in payload:
        item = _parse_search_item(raw)
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

    return _search_exact_packages(query)


def _parse_search_item(raw: Any) -> CondaPackageHit | None:
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
        target_platform=DEFAULT_TARGET_PLATFORM,
        target_platform_supported=_platform_supported(platforms, DEFAULT_TARGET_PLATFORM),
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


def _platform_supported(platforms: list[str], target_platform: str) -> bool:
    if not platforms:
        return True
    return target_platform in platforms or "noarch" in platforms


def _search_exact_packages(query: str) -> list[CondaPackageHit]:
    hits: list[CondaPackageHit] = []
    for channel in SUPPORTED_CHANNELS:
        try:
            raw = _request_json(f"{ANACONDA_PACKAGE_URL}/{channel}/{urllib.parse.quote(query)}", {}, timeout=10)
        except Exception:
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
                target_platform=DEFAULT_TARGET_PLATFORM,
                target_platform_supported=_platform_supported(platforms, DEFAULT_TARGET_PLATFORM),
            )
        )
    return hits


def _request_json(url: str, params: dict[str, str], *, timeout: int) -> Any:
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
