"""Lightweight local Bioconda package search index."""

from __future__ import annotations

import bz2
import json
import time
import urllib.request
from pathlib import Path
from typing import Any

from config import get_app_cache_dir


BIOCONDA_BASE_URL = "https://conda.anaconda.org/bioconda"
INDEX_VERSION = 1
INDEX_FILENAME = "search-index-v1.json"
SOURCE_FILENAMES = {
    "channeldata": "channeldata.json",
    "linux-64": "linux-64-repodata.json",
    "noarch": "noarch-repodata.json",
}
DOWNLOAD_TIMEOUT_SECONDS = 20
_INDEX_MEMORY_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}


def get_bioconda_index_cache_dir() -> Path:
    return get_app_cache_dir() / "conda-index" / "bioconda"


def search_bioconda_index(query: str, *, limit: int, cache_dir: Path | None = None) -> list[dict[str, Any]]:
    page = search_bioconda_index_page(query, page=1, page_size=limit, cache_dir=cache_dir)
    items = page.get("items")
    return [dict(item) for item in items] if isinstance(items, list) else []


def search_bioconda_index_page(
    query: str,
    *,
    page: int,
    page_size: int,
    cache_dir: Path | None = None,
) -> dict[str, Any]:
    normalized = _normalize_query(query)
    bounded_page = max(1, int(page or 1))
    bounded_page_size = max(1, min(int(page_size or 20), 100))
    if not normalized:
        return {
            "items": [],
            "total": 0,
            "page": bounded_page,
            "pageSize": bounded_page_size,
            "hasMore": False,
            "indexAvailable": False,
        }
    index = load_bioconda_index(cache_dir=cache_dir)
    if index is None:
        return {
            "items": [],
            "total": 0,
            "page": bounded_page,
            "pageSize": bounded_page_size,
            "hasMore": False,
            "indexAvailable": False,
        }
    records = index.get("packages")
    if not isinstance(records, list):
        return {
            "items": [],
            "total": 0,
            "page": bounded_page,
            "pageSize": bounded_page_size,
            "hasMore": False,
            "indexAvailable": False,
        }

    scored: list[tuple[int, str, dict[str, Any]]] = []
    for raw in records:
        if not isinstance(raw, dict):
            continue
        score = _score_record(raw, normalized)
        if score <= 0:
            continue
        scored.append((score, str(raw.get("name") or ""), raw))
    scored.sort(key=lambda item: (-item[0], item[1]))
    total = len(scored)
    offset = (bounded_page - 1) * bounded_page_size
    page_items = scored[offset : offset + bounded_page_size]
    return {
        "items": [dict(item[2]) for item in page_items],
        "total": total,
        "page": bounded_page,
        "pageSize": bounded_page_size,
        "hasMore": offset + len(page_items) < total,
        "indexAvailable": True,
    }


def load_bioconda_index(*, cache_dir: Path | None = None) -> dict[str, Any] | None:
    root = cache_dir or get_bioconda_index_cache_dir()
    index_path = root / INDEX_FILENAME
    try:
        mtime = index_path.stat().st_mtime
    except OSError:
        return None
    cache_key = str(index_path)
    cached = _INDEX_MEMORY_CACHE.get(cache_key)
    if cached and cached[0] == mtime:
        return cached[1]
    try:
        payload = json.loads(index_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(payload, dict) or int(payload.get("version") or 0) != INDEX_VERSION:
        return None
    _INDEX_MEMORY_CACHE[cache_key] = (mtime, payload)
    return payload


def bioconda_index_status(*, cache_dir: Path | None = None) -> dict[str, Any]:
    root = cache_dir or get_bioconda_index_cache_dir()
    index_path = root / INDEX_FILENAME
    index = load_bioconda_index(cache_dir=root)
    if index is None:
        return {
            "available": False,
            "channel": "bioconda",
            "packageCount": 0,
            "indexPath": str(index_path),
            "updatedAt": "",
        }
    packages = index.get("packages")
    return {
        "available": True,
        "channel": "bioconda",
        "packageCount": len(packages) if isinstance(packages, list) else 0,
        "indexPath": str(index_path),
        "updatedAt": str(index.get("updatedAt") or ""),
    }


def refresh_bioconda_index(*, cache_dir: Path | None = None) -> dict[str, Any]:
    root = cache_dir or get_bioconda_index_cache_dir()
    source_dir = root / "sources"
    source_dir.mkdir(parents=True, exist_ok=True)
    _download_text(f"{BIOCONDA_BASE_URL}/channeldata.json", source_dir / SOURCE_FILENAMES["channeldata"])
    _download_bz2(
        f"{BIOCONDA_BASE_URL}/linux-64/repodata.json.bz2",
        source_dir / SOURCE_FILENAMES["linux-64"],
    )
    _download_bz2(
        f"{BIOCONDA_BASE_URL}/noarch/repodata.json.bz2",
        source_dir / SOURCE_FILENAMES["noarch"],
    )
    index = build_bioconda_index(source_dir)
    root.mkdir(parents=True, exist_ok=True)
    index_path = root / INDEX_FILENAME
    index_path.write_text(json.dumps(index, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    _INDEX_MEMORY_CACHE.pop(str(index_path), None)
    return index


def build_bioconda_index(source_dir: Path) -> dict[str, Any]:
    channeldata = _read_json(source_dir / SOURCE_FILENAMES["channeldata"])
    package_meta = channeldata.get("packages") if isinstance(channeldata, dict) else {}
    if not isinstance(package_meta, dict):
        package_meta = {}

    records: dict[str, dict[str, Any]] = {}
    for platform in ("linux-64", "noarch"):
        repodata = _read_json(source_dir / SOURCE_FILENAMES[platform])
        for package in _iter_repodata_packages(repodata):
            name = str(package.get("name") or "").strip()
            version = str(package.get("version") or "").strip()
            if not name or not version:
                continue
            record = records.setdefault(
                name,
                {
                    "name": name,
                    "channel": "bioconda",
                    "summary": "",
                    "latestVersion": "",
                    "versions": [],
                    "platforms": [],
                },
            )
            if version not in record["versions"]:
                record["versions"].append(version)
            if platform not in record["platforms"]:
                record["platforms"].append(platform)

    for name, record in records.items():
        meta = package_meta.get(name)
        if isinstance(meta, dict):
            record["summary"] = str(meta.get("summary") or meta.get("description") or "").strip()
            latest = str(meta.get("version") or meta.get("latest_version") or "").strip()
            if latest:
                record["latestVersion"] = latest
        if not record["latestVersion"]:
            record["latestVersion"] = _latest_version(record["versions"])
        record["versions"] = sorted(record["versions"])
        record["platforms"] = sorted(record["platforms"])

    packages = sorted(records.values(), key=lambda item: str(item["name"]).lower())
    return {
        "version": INDEX_VERSION,
        "channel": "bioconda",
        "updatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "packages": packages,
    }


def _iter_repodata_packages(repodata: Any) -> list[dict[str, Any]]:
    if not isinstance(repodata, dict):
        return []
    packages: list[dict[str, Any]] = []
    for key in ("packages", "packages.conda"):
        raw = repodata.get(key)
        if isinstance(raw, dict):
            packages.extend(item for item in raw.values() if isinstance(item, dict))
    return packages


def _score_record(record: dict[str, Any], query: str) -> int:
    name = str(record.get("name") or "").lower()
    summary = str(record.get("summary") or "").lower()
    if name == query:
        return 100
    if name.startswith(query):
        return 80
    if query in name:
        return 60
    if query in summary:
        return 20
    return 0


def _latest_version(versions: list[str]) -> str:
    return versions[-1] if versions else ""


def _normalize_query(query: str) -> str:
    return str(query or "").strip().lower()


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _download_text(url: str, path: Path) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": "H2OMeta/0.1 bioconda-index"})
    with urllib.request.urlopen(request, timeout=DOWNLOAD_TIMEOUT_SECONDS) as response:
        raw = response.read().decode("utf-8", errors="replace")
    path.write_text(raw, encoding="utf-8")


def _download_bz2(url: str, path: Path) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": "H2OMeta/0.1 bioconda-index"})
    with urllib.request.urlopen(request, timeout=DOWNLOAD_TIMEOUT_SECONDS) as response:
        raw = response.read()
    path.write_text(bz2.decompress(raw).decode("utf-8", errors="replace"), encoding="utf-8")
