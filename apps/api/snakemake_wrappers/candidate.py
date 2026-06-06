"""Build normalized Snakemake wrapper candidate records."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from apps.api.tool_candidate_model import snakemake_wrapper_candidate_fields
from apps.api.tool_contract_resolver import DEFAULT_TOOL_CONTRACT_RESOLVER

from .archive import SNAKEMAKE_WRAPPERS_REF, SNAKEMAKE_WRAPPERS_REPOSITORY, SNAKEMAKE_WRAPPERS_WEB_ROOT
from .package_metadata import wrapper_environment_url


def build_wrapper_entry(wrapper_dir: str, *, has_environment: bool) -> dict[str, Any]:
    wrapper_identifier = f"{SNAKEMAKE_WRAPPERS_REF}/{wrapper_dir}"
    rule_spec_draft = DEFAULT_TOOL_CONTRACT_RESOLVER.resolve_snakemake_wrapper(
        wrapper_repository=SNAKEMAKE_WRAPPERS_REPOSITORY,
        wrapper_ref=SNAKEMAKE_WRAPPERS_REF,
        wrapper_path=wrapper_dir,
        wrapper_identifier=wrapper_identifier,
    )
    entry = {
        "name": wrapper_label(wrapper_dir),
        "toolName": tool_name_from_wrapper_dir(wrapper_dir),
        "wrapperRepository": SNAKEMAKE_WRAPPERS_REPOSITORY,
        "wrapperRef": SNAKEMAKE_WRAPPERS_REF,
        "wrapperPath": wrapper_dir,
        "wrapperIdentifier": wrapper_identifier,
        "wrapperUrl": f"{SNAKEMAKE_WRAPPERS_WEB_ROOT}/{wrapper_dir}",
        "ruleSpecDraft": rule_spec_draft,
    }
    entry.update(snakemake_wrapper_candidate_fields(entry))
    if has_environment:
        entry["environmentUrl"] = wrapper_environment_url(wrapper_dir)
    return entry


def rehydrate_cached_wrapper_entry(raw: dict[str, Any], *, cache_path: Path) -> dict[str, Any]:
    entry = dict(raw)
    wrapper_repository = str(entry.get("wrapperRepository") or "").strip()
    wrapper_ref = str(entry.get("wrapperRef") or "").strip()
    wrapper_path = str(entry.get("wrapperPath") or "").strip()
    wrapper_identifier = str(entry.get("wrapperIdentifier") or "").strip()
    if not wrapper_repository or not wrapper_ref or not wrapper_path or not wrapper_identifier:
        raise ValueError(f"SNAKEMAKE_WRAPPER_CACHE_INVALID: {cache_path}")
    entry["wrapperRepository"] = wrapper_repository
    entry["wrapperRef"] = wrapper_ref
    entry["wrapperPath"] = wrapper_path
    entry["wrapperIdentifier"] = wrapper_identifier
    entry["ruleSpecDraft"] = DEFAULT_TOOL_CONTRACT_RESOLVER.resolve_snakemake_wrapper(
        wrapper_repository=wrapper_repository,
        wrapper_ref=wrapper_ref,
        wrapper_path=wrapper_path,
        wrapper_identifier=wrapper_identifier,
    )
    entry.update(snakemake_wrapper_candidate_fields(entry))
    return entry


def is_wrapper_file(path: str) -> bool:
    return path.endswith(("/wrapper.py", "/wrapper.R", "/wrapper.Rmd", "/wrapper.rs"))


def wrapper_dir(path: str) -> str:
    if "/" not in path:
        return ""
    return path.rsplit("/", 1)[0]


def tool_name_from_wrapper_dir(wrapper_dir: str) -> str:
    parts = [part for part in wrapper_dir.split("/") if part]
    if len(parts) < 2 or parts[0] != "bio":
        return ""
    return normalize_tool_name(parts[1])


def wrapper_label(wrapper_dir: str) -> str:
    parts = [part for part in wrapper_dir.split("/") if part]
    return " ".join(parts[1:]) if len(parts) > 1 else wrapper_dir


def normalize_tool_name(value: str) -> str:
    return str(value or "").strip().lower().replace("_", "-")
