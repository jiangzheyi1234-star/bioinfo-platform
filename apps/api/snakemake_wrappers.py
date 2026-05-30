"""Snakemake wrapper repository lookup helpers."""

from __future__ import annotations

import time
import urllib.request
from pathlib import Path
from typing import Any

from apps.api.rule_spec_drafts import build_wrapper_rule_spec_draft
from config import get_app_cache_dir


SNAKEMAKE_WRAPPERS_REPOSITORY = "snakemake/snakemake-wrappers"
SNAKEMAKE_WRAPPERS_REF = "v9.8.0"
SNAKEMAKE_WRAPPERS_TREE_URL = f"https://api.github.com/repos/{SNAKEMAKE_WRAPPERS_REPOSITORY}/git/trees/{SNAKEMAKE_WRAPPERS_REF}?recursive=1"
SNAKEMAKE_WRAPPERS_WEB_ROOT = f"https://github.com/{SNAKEMAKE_WRAPPERS_REPOSITORY}/tree/{SNAKEMAKE_WRAPPERS_REF}"
WRAPPER_CACHE_TTL_SECONDS = 3600
WRAPPER_LOOKUP_TIMEOUT_SECONDS = 30.0
MAX_WRAPPER_MATCHES_PER_TOOL = 8
WRAPPER_INDEX_CACHE_FILENAME = f"wrapper-index-v1-{SNAKEMAKE_WRAPPERS_REF}.json"

_WRAPPER_CACHE: tuple[float, dict[str, list[dict[str, Any]]]] | None = None


def find_snakemake_wrappers_for_tool(tool_name: str) -> list[dict[str, Any]]:
    normalized = _normalize_tool_name(tool_name)
    if not normalized:
        return []
    index = _wrapper_index()
    return list(index.get(normalized, []))[:MAX_WRAPPER_MATCHES_PER_TOOL]


def _wrapper_index() -> dict[str, list[dict[str, Any]]]:
    global _WRAPPER_CACHE
    now = time.time()
    if _WRAPPER_CACHE and now - _WRAPPER_CACHE[0] < WRAPPER_CACHE_TTL_SECONDS:
        return _WRAPPER_CACHE[1]
    cached_index = _load_cached_wrapper_index()
    if cached_index is not None:
        _WRAPPER_CACHE = (now, cached_index)
        return cached_index
    payload = _request_wrapper_tree()
    index = _build_wrapper_index(payload)
    _save_cached_wrapper_index(index)
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


def _build_wrapper_index(payload: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
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
    index: dict[str, list[dict[str, Any]]] = {}
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
        wrapper_identifier = f"{SNAKEMAKE_WRAPPERS_REF}/{wrapper_dir}"
        rule_spec_draft = build_wrapper_rule_spec_draft(
            wrapper_repository=SNAKEMAKE_WRAPPERS_REPOSITORY,
            wrapper_ref=SNAKEMAKE_WRAPPERS_REF,
            wrapper_path=wrapper_dir,
            wrapper_identifier=wrapper_identifier,
        )
        entry = {
            "name": _wrapper_label(wrapper_dir),
            "toolName": tool_name,
            "wrapperRepository": SNAKEMAKE_WRAPPERS_REPOSITORY,
            "wrapperRef": SNAKEMAKE_WRAPPERS_REF,
            "wrapperPath": wrapper_dir,
            "wrapperIdentifier": wrapper_identifier,
            "wrapperUrl": f"{SNAKEMAKE_WRAPPERS_WEB_ROOT}/{wrapper_dir}",
            "ruleSpecDraft": rule_spec_draft,
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


def _wrapper_index_cache_path() -> Path:
    return get_app_cache_dir() / "snakemake-wrappers" / WRAPPER_INDEX_CACHE_FILENAME


def _load_cached_wrapper_index() -> dict[str, list[dict[str, Any]]] | None:
    path = _wrapper_index_cache_path()
    if not path.exists():
        return None
    import json

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
        normalized[key] = [dict(item) for item in entries if isinstance(item, dict)]
        if len(normalized[key]) != len(entries):
            raise ValueError(f"SNAKEMAKE_WRAPPER_CACHE_INVALID: {path}")
    return normalized


def _save_cached_wrapper_index(index: dict[str, list[dict[str, Any]]]) -> None:
    path = _wrapper_index_cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    import json

    path.write_text(
        json.dumps({"version": 1, "fetchedAt": time.time(), "index": index}, ensure_ascii=False),
        encoding="utf-8",
    )


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
