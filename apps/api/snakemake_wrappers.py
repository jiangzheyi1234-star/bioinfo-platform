"""Snakemake wrapper repository lookup helpers."""

from __future__ import annotations

import time
import urllib.error
import urllib.request
from typing import Any


SNAKEMAKE_WRAPPERS_TREE_URL = "https://api.github.com/repos/snakemake/snakemake-wrappers/git/trees/master?recursive=1"
SNAKEMAKE_WRAPPERS_WEB_ROOT = "https://github.com/snakemake/snakemake-wrappers/tree/master"
WRAPPER_CACHE_TTL_SECONDS = 3600
WRAPPER_LOOKUP_TIMEOUT_SECONDS = 8.0
MAX_WRAPPER_MATCHES_PER_TOOL = 8

_WRAPPER_CACHE: tuple[float, dict[str, list[dict[str, str]]]] | None = None


def find_snakemake_wrappers_for_tool(tool_name: str) -> list[dict[str, str]]:
    normalized = _normalize_tool_name(tool_name)
    if not normalized:
        return []
    try:
        index = _wrapper_index()
    except (OSError, TimeoutError, ValueError, urllib.error.URLError):
        return []
    return list(index.get(normalized, []))[:MAX_WRAPPER_MATCHES_PER_TOOL]


def _wrapper_index() -> dict[str, list[dict[str, str]]]:
    global _WRAPPER_CACHE
    now = time.time()
    if _WRAPPER_CACHE and now - _WRAPPER_CACHE[0] < WRAPPER_CACHE_TTL_SECONDS:
        return _WRAPPER_CACHE[1]
    payload = _request_wrapper_tree()
    index = _build_wrapper_index(payload)
    _WRAPPER_CACHE = (now, index)
    return index


def _request_wrapper_tree() -> dict[str, Any]:
    request = urllib.request.Request(
        SNAKEMAKE_WRAPPERS_TREE_URL,
        headers={"Accept": "application/vnd.github+json", "User-Agent": "h2ometa-tool-search"},
    )
    with urllib.request.urlopen(request, timeout=WRAPPER_LOOKUP_TIMEOUT_SECONDS) as response:
        raw = response.read()
    import json

    payload = json.loads(raw.decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("SNAKEMAKE_WRAPPER_TREE_INVALID")
    return payload


def _build_wrapper_index(payload: dict[str, Any]) -> dict[str, list[dict[str, str]]]:
    tree = payload.get("tree")
    if not isinstance(tree, list):
        raise ValueError("SNAKEMAKE_WRAPPER_TREE_INVALID")
    environment_paths = {
        _wrapper_dir(str(item.get("path") or ""))
        for item in tree
        if isinstance(item, dict)
        and item.get("type") == "blob"
        and str(item.get("path") or "").endswith("/environment.yaml")
    }
    index: dict[str, list[dict[str, str]]] = {}
    seen: set[tuple[str, str]] = set()
    for item in tree:
        if not isinstance(item, dict) or item.get("type") != "blob":
            continue
        path = str(item.get("path") or "")
        wrapper_dir = _wrapper_dir(path)
        if not wrapper_dir or not _is_wrapper_file(path):
            continue
        tool_name = _tool_name_from_wrapper_dir(wrapper_dir)
        if not tool_name:
            continue
        key = (tool_name, wrapper_dir)
        if key in seen:
            continue
        seen.add(key)
        entry = {
            "name": _wrapper_label(wrapper_dir),
            "toolName": tool_name,
            "wrapperPath": wrapper_dir,
            "wrapperUrl": f"{SNAKEMAKE_WRAPPERS_WEB_ROOT}/{wrapper_dir}",
        }
        if wrapper_dir in environment_paths:
            entry["environmentUrl"] = f"{SNAKEMAKE_WRAPPERS_WEB_ROOT}/{wrapper_dir}/environment.yaml"
        index.setdefault(tool_name, []).append(entry)
    for entries in index.values():
        entries.sort(key=lambda entry: entry["wrapperPath"])
    return index


def _is_wrapper_file(path: str) -> bool:
    return path.endswith(("/wrapper.py", "/wrapper.R", "/wrapper.Rmd", "/wrapper.rs"))


def _wrapper_dir(path: str) -> str:
    if "/" not in path:
        return ""
    return path.rsplit("/", 1)[0]


def _tool_name_from_wrapper_dir(wrapper_dir: str) -> str:
    parts = [part for part in wrapper_dir.split("/") if part]
    if len(parts) < 2 or parts[0] != "bio":
        return ""
    return _normalize_tool_name(parts[1])


def _wrapper_label(wrapper_dir: str) -> str:
    parts = [part for part in wrapper_dir.split("/") if part]
    return " ".join(parts[1:]) if len(parts) > 1 else wrapper_dir


def _normalize_tool_name(value: str) -> str:
    return str(value or "").strip().lower().replace("_", "-")
