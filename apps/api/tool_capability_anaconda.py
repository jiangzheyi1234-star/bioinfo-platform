"""Anaconda package search response parsing for tool capability search."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any


SUPPORTED_CHANNELS = ("bioconda", "conda-forge")


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


def parse_search_item(raw: Any, *, target_platform: str) -> CondaPackageHit | None:
    if not isinstance(raw, dict):
        return None
    channel = str(raw.get("owner") or raw.get("channel") or "").strip().lower()
    if channel not in SUPPORTED_CHANNELS:
        return None
    name = str(raw.get("name") or "").strip()
    if not name:
        return None
    summary = str(raw.get("summary") or raw.get("description") or "").strip()
    current_version = latest_version(raw)
    available_versions = versions(raw)
    available_platforms = platforms(raw)
    return CondaPackageHit(
        name=name,
        channel=channel,
        summary=summary or "Conda package",
        latest_version=current_version,
        versions=available_versions,
        package_spec=package_spec(channel, name, current_version),
        source_url=f"https://anaconda.org/{channel}/{name}",
        platforms=available_platforms,
        target_platform=target_platform,
        target_platform_supported=platform_supported(available_platforms, target_platform),
    )


def latest_version(raw: dict[str, Any]) -> str:
    for key in ("latest_version", "latestVersion", "version"):
        value = str(raw.get(key) or "").strip()
        if value:
            return value
    raw_versions = raw.get("versions")
    if isinstance(raw_versions, list) and raw_versions:
        return str(raw_versions[-1] or "").strip()
    return ""


def versions(raw: dict[str, Any]) -> list[str]:
    raw_versions = raw.get("versions")
    if not isinstance(raw_versions, list):
        return []
    return [str(item).strip() for item in raw_versions if str(item or "").strip()]


def package_spec(channel: str, name: str, version: str) -> str:
    if version:
        return f"{channel}::{name}={version}"
    return f"{channel}::{name}"


def platforms(raw: dict[str, Any]) -> list[str]:
    conda_platforms = raw.get("conda_platforms")
    if isinstance(conda_platforms, list):
        return sorted({str(item).strip() for item in conda_platforms if str(item or "").strip()})

    raw_platforms = raw.get("platforms")
    if isinstance(raw_platforms, dict):
        return sorted({str(item).strip() for item in raw_platforms if str(item or "").strip()})
    if isinstance(raw_platforms, list):
        return sorted({str(item).strip() for item in raw_platforms if str(item or "").strip()})

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


def normalize_target_platform(target_platform: str) -> str:
    return str(target_platform or "").strip().lower()


def platform_supported(platforms: list[str], target_platform: str) -> bool:
    if not target_platform:
        return True
    if not platforms:
        return False
    return target_platform in platforms or "noarch" in platforms


def remaining_timeout(deadline: float, request_timeout: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("ANACONDA_SEARCH_TIMEOUT")
    return min(request_timeout, remaining)
