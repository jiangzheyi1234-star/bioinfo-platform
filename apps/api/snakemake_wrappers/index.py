"""Build and cache the Snakemake wrapper index."""

from __future__ import annotations

import json
import time
import urllib.error
from pathlib import Path
from typing import Any

from config import get_app_cache_dir

from . import archive
from .candidate import (
    build_wrapper_entry,
    is_wrapper_file,
    rehydrate_cached_wrapper_entry,
    tool_name_from_wrapper_dir,
    wrapper_dir,
)
from .package_metadata import wrapper_environment_dirs


WRAPPER_CACHE_TTL_SECONDS = 3600
WRAPPER_INDEX_CACHE_FILENAME = f"wrapper-index-v2-{archive.SNAKEMAKE_WRAPPERS_REF}.json"

_WRAPPER_CACHE: tuple[Path, float, dict[str, list[dict[str, Any]]]] | None = None


def clear_wrapper_index_cache() -> None:
    global _WRAPPER_CACHE
    _WRAPPER_CACHE = None


def wrapper_index() -> dict[str, list[dict[str, Any]]]:
    global _WRAPPER_CACHE
    now = time.time()
    cache_path = wrapper_index_cache_path()
    if (
        _WRAPPER_CACHE
        and _WRAPPER_CACHE[0] == cache_path
        and now - _WRAPPER_CACHE[1] < WRAPPER_CACHE_TTL_SECONDS
    ):
        return _WRAPPER_CACHE[2]
    cached_index = load_cached_wrapper_index()
    if cached_index is not None:
        index = cached_index or bundled_wrapper_index()
        _WRAPPER_CACHE = (cache_path, now, index)
        return index
    try:
        payload = archive.request_wrapper_tree()
    except urllib.error.HTTPError as exc:
        if exc.code != 403:
            raise
        index = bundled_wrapper_index()
        _WRAPPER_CACHE = (cache_path, now, index)
        return index
    index = build_wrapper_index(payload)
    save_cached_wrapper_index(index)
    _WRAPPER_CACHE = (cache_path, now, index)
    return index


def build_wrapper_index(payload: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    tree = payload.get("tree")
    if not isinstance(tree, list):
        raise ValueError("SNAKEMAKE_WRAPPER_TREE_INVALID")
    environment_paths = wrapper_environment_dirs(tree)
    index: dict[str, list[dict[str, Any]]] = {}
    seen: set[tuple[str, str]] = set()
    for item in tree:
        if not isinstance(item, dict) or item.get("type") != "blob":
            continue
        path = str(item.get("path") or "")
        current_wrapper_dir = wrapper_dir(path)
        if not current_wrapper_dir or not is_wrapper_file(path):
            continue
        tool_name = tool_name_from_wrapper_dir(current_wrapper_dir)
        if not tool_name:
            continue
        key = (tool_name, current_wrapper_dir)
        if key in seen:
            continue
        seen.add(key)
        entry = build_wrapper_entry(
            current_wrapper_dir,
            has_environment=current_wrapper_dir in environment_paths,
        )
        index.setdefault(tool_name, []).append(entry)
    for entries in index.values():
        entries.sort(key=lambda entry: entry["wrapperPath"])
    return index


def bundled_wrapper_index() -> dict[str, list[dict[str, Any]]]:
    wrapper_root = Path(__file__).resolve().parents[2] / "remote_runner" / "snakemake_wrappers" / archive.SNAKEMAKE_WRAPPERS_REF
    if not wrapper_root.is_dir():
        return {}
    tree = [
        {
            "path": path.relative_to(wrapper_root).as_posix(),
            "type": "blob",
        }
        for path in wrapper_root.rglob("*")
        if path.is_file()
    ]
    return build_wrapper_index({"tree": tree})


def wrapper_index_cache_path() -> Path:
    return get_app_cache_dir() / "snakemake-wrappers" / WRAPPER_INDEX_CACHE_FILENAME


def load_cached_wrapper_index() -> dict[str, list[dict[str, Any]]] | None:
    path = wrapper_index_cache_path()
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise OSError(f"SNAKEMAKE_WRAPPER_CACHE_UNREADABLE: {path}") from exc
    except ValueError as exc:
        raise ValueError(f"SNAKEMAKE_WRAPPER_CACHE_INVALID: {path}") from exc
    index = payload.get("index") if isinstance(payload, dict) else None
    if not isinstance(index, dict):
        raise ValueError(f"SNAKEMAKE_WRAPPER_CACHE_INVALID: {path}")
    normalized: dict[str, list[dict[str, Any]]] = {}
    for key, entries in index.items():
        if not isinstance(key, str) or not isinstance(entries, list):
            raise ValueError(f"SNAKEMAKE_WRAPPER_CACHE_INVALID: {path}")
        normalized[key] = [rehydrate_cached_wrapper_entry(item, cache_path=path) for item in entries if isinstance(item, dict)]
        if len(normalized[key]) != len(entries):
            raise ValueError(f"SNAKEMAKE_WRAPPER_CACHE_INVALID: {path}")
    return normalized


def save_cached_wrapper_index(index: dict[str, list[dict[str, Any]]]) -> None:
    path = wrapper_index_cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"version": 2, "fetchedAt": time.time(), "index": index}, ensure_ascii=False),
        encoding="utf-8",
    )
