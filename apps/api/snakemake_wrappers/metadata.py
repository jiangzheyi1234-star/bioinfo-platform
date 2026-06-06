"""Snakemake wrapper meta.yaml extraction."""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import yaml

from config import get_app_cache_dir

from .archive import (
    SNAKEMAKE_WRAPPERS_REF,
    SNAKEMAKE_WRAPPERS_REPOSITORY,
    WRAPPER_LOOKUP_TIMEOUT_SECONDS,
)


WRAPPER_META_CACHE_TTL_SECONDS = 24 * 3600
SNAKEMAKE_WRAPPERS_RAW_ROOT = f"https://raw.githubusercontent.com/{SNAKEMAKE_WRAPPERS_REPOSITORY}/{SNAKEMAKE_WRAPPERS_REF}"

_META_HINTS_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}


def wrapper_contract_hints(wrapper_path: str) -> dict[str, Any]:
    normalized_path = _normalize_wrapper_path(wrapper_path)
    if not normalized_path:
        return {}
    now = time.time()
    cached = _META_HINTS_CACHE.get(normalized_path)
    if cached and now - cached[0] < WRAPPER_META_CACHE_TTL_SECONDS:
        return dict(cached[1])
    disk = _load_cached_meta_hints(normalized_path)
    if disk is not None:
        _META_HINTS_CACHE[normalized_path] = (now, disk)
        return dict(disk)
    hints: dict[str, Any] = {}
    try:
        hints.update(wrapper_contract_hints_from_meta_yaml(_request_wrapper_meta_yaml(normalized_path)))
    except (OSError, urllib.error.URLError, ValueError, yaml.YAMLError):
        pass
    if hints:
        source_ref = dict(hints.get("sourceRef") or {})
        source_ref.update(
            {
                "path": f"{normalized_path}/meta.yaml",
                "repository": SNAKEMAKE_WRAPPERS_REPOSITORY,
                "ref": SNAKEMAKE_WRAPPERS_REF,
                "url": wrapper_meta_url(normalized_path),
            }
        )
        hints["sourceRef"] = source_ref
    try:
        environment = wrapper_environment_hints_from_environment_yaml(_request_wrapper_environment_yaml(normalized_path))
    except (OSError, urllib.error.URLError, ValueError, yaml.YAMLError):
        environment = {}
    if environment:
        source_ref = dict(environment.get("sourceRef") or {})
        source_ref.update(
            {
                "path": f"{normalized_path}/environment.yaml",
                "repository": SNAKEMAKE_WRAPPERS_REPOSITORY,
                "ref": SNAKEMAKE_WRAPPERS_REF,
                "url": wrapper_environment_url(normalized_path),
            }
        )
        environment["sourceRef"] = source_ref
        hints["environment"] = environment
    _save_cached_meta_hints(normalized_path, hints)
    _META_HINTS_CACHE[normalized_path] = (now, hints)
    return dict(hints)


def wrapper_contract_hints_from_meta_yaml(raw: str) -> dict[str, Any]:
    payload = yaml.safe_load(str(raw or "")) or {}
    if not isinstance(payload, dict):
        return {}
    hints: dict[str, Any] = {}
    for key in ("name", "description", "url"):
        value = _string(payload.get(key))
        if value:
            hints[key] = value
    authors = _string_list(payload.get("authors"))
    if authors:
        hints["authors"] = authors
    for key in ("input", "output", "params", "notes"):
        values = _string_list(payload.get(key))
        if values:
            hints[key] = values
    if hints:
        hints["sourceRef"] = {"type": "snakemake-wrapper-meta", "format": "meta.yaml"}
    return hints


def wrapper_environment_hints_from_environment_yaml(raw: str) -> dict[str, Any]:
    payload = yaml.safe_load(str(raw or "")) or {}
    if not isinstance(payload, dict):
        return {}
    channels = _string_list(payload.get("channels"))
    dependencies = _string_list(payload.get("dependencies"))
    conda: dict[str, Any] = {}
    if channels:
        conda["channels"] = channels
    if dependencies:
        conda["dependencies"] = dependencies
    if not conda:
        return {}
    return {
        "conda": conda,
        "sourceRef": {
            "type": "snakemake-wrapper-environment",
            "format": "environment.yaml",
        },
    }


def wrapper_meta_url(wrapper_path: str) -> str:
    return f"{SNAKEMAKE_WRAPPERS_RAW_ROOT}/{_normalize_wrapper_path(wrapper_path)}/meta.yaml"


def wrapper_environment_url(wrapper_path: str) -> str:
    return f"{SNAKEMAKE_WRAPPERS_RAW_ROOT}/{_normalize_wrapper_path(wrapper_path)}/environment.yaml"


def _request_wrapper_meta_yaml(wrapper_path: str) -> str:
    request = urllib.request.Request(
        wrapper_meta_url(wrapper_path),
        headers={"Accept": "text/yaml,*/*", "User-Agent": "h2ometa-tool-search"},
    )
    with urllib.request.urlopen(request, timeout=WRAPPER_LOOKUP_TIMEOUT_SECONDS) as response:
        return response.read().decode("utf-8")


def _request_wrapper_environment_yaml(wrapper_path: str) -> str:
    request = urllib.request.Request(
        wrapper_environment_url(wrapper_path),
        headers={"Accept": "text/yaml,*/*", "User-Agent": "h2ometa-tool-search"},
    )
    with urllib.request.urlopen(request, timeout=WRAPPER_LOOKUP_TIMEOUT_SECONDS) as response:
        return response.read().decode("utf-8")


def _load_cached_meta_hints(wrapper_path: str) -> dict[str, Any] | None:
    path = _meta_cache_path(wrapper_path)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    fetched_at = float(payload.get("fetchedAt") or 0)
    if time.time() - fetched_at >= WRAPPER_META_CACHE_TTL_SECONDS:
        return None
    hints = payload.get("hints")
    return dict(hints) if isinstance(hints, dict) else None


def _save_cached_meta_hints(wrapper_path: str, hints: dict[str, Any]) -> None:
    path = _meta_cache_path(wrapper_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"fetchedAt": time.time(), "hints": hints}, ensure_ascii=False), encoding="utf-8")


def _meta_cache_path(wrapper_path: str) -> Path:
    safe_name = re.sub(r"[^a-zA-Z0-9_.-]+", "__", _normalize_wrapper_path(wrapper_path)).strip("_")
    return get_app_cache_dir() / "snakemake-wrappers" / "meta" / f"{SNAKEMAKE_WRAPPERS_REF}-{safe_name}.json"


def _normalize_wrapper_path(value: str) -> str:
    return str(value or "").strip().strip("/")


def _string(value: Any) -> str:
    return str(value or "").strip() if value is not None else ""


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [item for item in (_string(item) for item in value) if item]
    text = _string(value)
    if not text:
        return []
    return [line.strip() for line in text.splitlines() if line.strip()]
