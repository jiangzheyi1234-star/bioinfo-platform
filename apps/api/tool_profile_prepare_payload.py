"""Prepare-job payloads for curated H2OMeta tool profiles."""

from __future__ import annotations

from typing import Any

from apps.api.bioconda_tool_index import search_bioconda_index_page
from apps.api.tool_candidate_dependencies import (
    conda_dependency_from_environment_hints,
    normalize_package_name,
    package_spec_from_conda_dependency,
)
from apps.api.tool_profile_external_refs import profile_snakemake_wrappers
from apps.api.tool_profile_model import ToolProfile
from apps.api.tool_profiles import resolve_tool_profile_record


def profile_prepare_payload(profile: ToolProfile) -> dict[str, Any]:
    tool_name = str(profile.tool_names[0] if profile.tool_names else profile.profile_id).strip()
    source = "bioconda"
    package_name = str(profile.package_name or tool_name).strip()
    package_spec = f"{source}::{package_name}"
    wrappers = profile_snakemake_wrappers(profile)
    dependency = _profile_primary_dependency(profile, wrappers, preferred_name=package_name)
    if dependency is None:
        dependency = _profile_manifest_dependency(profile, preferred_name=package_name)
    if dependency is None and not profile.pack_id:
        dependency = _bioconda_dependency_from_index(package_name)
    version = ""
    if dependency is not None:
        source = dependency["source"]
        package_name = dependency["name"]
        version = dependency["version"]
        package_spec = package_spec_from_conda_dependency(dependency)
    tool_id = f"{source}::{package_name}"
    draft = resolve_tool_profile_record(
        profile,
        {
            "id": tool_id,
            "name": tool_name,
            "source": source,
            "packageSpec": package_spec,
            "version": version,
            "latestVersion": version,
        },
        wrappers=wrappers,
    )
    payload = {
        "id": tool_id,
        "name": tool_name,
        "source": source,
        "sourceLabel": _source_label(source),
        "packageSpec": package_spec,
        "targetPlatform": "linux-64",
        "targetPlatformSupported": True,
        "snakemakeWrappers": wrappers,
        "snakemakeWrapperCount": len(wrappers),
        "ruleTemplate": dict((draft or {}).get("ruleTemplate") or {}),
        "ruleSpecDraft": dict(draft or {}),
    }
    if version:
        payload["version"] = version
        payload["latestVersion"] = version
    return payload


def _profile_primary_dependency(
    profile: ToolProfile,
    wrappers: list[dict[str, Any]],
    *,
    preferred_name: str,
) -> dict[str, str] | None:
    preferred_paths = set(profile.preferred_wrapper_paths)
    for wrapper in wrappers:
        if preferred_paths and str(wrapper.get("wrapperPath") or "").strip() not in preferred_paths:
            continue
        dependency = _wrapper_dependency(wrapper, preferred_name=preferred_name)
        if dependency is not None:
            return dependency
    for wrapper in wrappers:
        dependency = _wrapper_dependency(wrapper, preferred_name=preferred_name)
        if dependency is not None:
            return dependency
    return None


def _profile_manifest_dependency(profile: ToolProfile, *, preferred_name: str) -> dict[str, str] | None:
    if not profile.pack_id:
        return None
    environment = profile.rule_template.get("environment") if isinstance(profile.rule_template.get("environment"), dict) else {}
    conda = environment.get("conda") if isinstance(environment.get("conda"), dict) else {}
    channels = [str(item).strip() for item in conda.get("channels", []) if str(item or "").strip()]
    dependencies = [
        preferred_name if str(item or "").strip() == "{packageSpec}" else str(item or "").strip()
        for item in conda.get("dependencies", [])
        if str(item or "").strip()
    ]
    hints = {"environment": {"conda": {"channels": channels, "dependencies": dependencies}}}
    return conda_dependency_from_environment_hints(hints, preferred_name=preferred_name)


def _wrapper_dependency(wrapper: dict[str, Any], *, preferred_name: str) -> dict[str, str] | None:
    hints = wrapper.get("wrapperContractHints") if isinstance(wrapper.get("wrapperContractHints"), dict) else {}
    return conda_dependency_from_environment_hints(hints, preferred_name=preferred_name)


def _bioconda_dependency_from_index(package_name: str) -> dict[str, str] | None:
    normalized_package_name = normalize_package_name(package_name)
    if not normalized_package_name:
        return None
    page = search_bioconda_index_page(package_name, page=1, page_size=10)
    items = page.get("items") if isinstance(page, dict) else None
    if not isinstance(items, list):
        return None
    for item in items:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        version = str(item.get("latestVersion") or "").strip()
        if normalize_package_name(name) == normalized_package_name and version:
            return {"source": "bioconda", "name": name, "version": version}
    return None


def _source_label(source: str) -> str:
    return "Bioconda" if source == "bioconda" else source
