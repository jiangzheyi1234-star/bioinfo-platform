"""Snakemake wrapper package and source metadata helpers."""

from __future__ import annotations

from typing import Any

from .archive import SNAKEMAKE_WRAPPERS_REF, SNAKEMAKE_WRAPPERS_REPOSITORY, SNAKEMAKE_WRAPPERS_WEB_ROOT


def wrapper_environment_dirs(tree: list[Any]) -> set[str]:
    return {
        _wrapper_dir_from_path(str(item.get("path") or ""))
        for item in tree
        if isinstance(item, dict)
        and item.get("type") == "blob"
        and str(item.get("path") or "").endswith("/environment.yaml")
    }


def wrapper_environment_url(current_wrapper_dir: str) -> str:
    return f"{SNAKEMAKE_WRAPPERS_WEB_ROOT}/{current_wrapper_dir}/environment.yaml"


def wrapper_source_ref() -> dict[str, str]:
    return {
        "type": "github-tree",
        "repository": SNAKEMAKE_WRAPPERS_REPOSITORY,
        "ref": SNAKEMAKE_WRAPPERS_REF,
    }


def _wrapper_dir_from_path(path: str) -> str:
    if "/" not in path:
        return ""
    return path.rsplit("/", 1)[0]
