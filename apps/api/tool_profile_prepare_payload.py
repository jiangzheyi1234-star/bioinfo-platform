"""Prepare-job payloads for curated H2OMeta tool profiles."""

from __future__ import annotations

from typing import Any

from apps.api.tool_candidate_dependencies import (
    conda_dependency_from_environment_hints,
    package_spec_from_conda_dependency,
)
from apps.api.tool_profile_external_refs import profile_snakemake_wrappers
from apps.api.tool_profile_model import ToolProfile
from apps.api.tool_profiles import resolve_tool_profile


def profile_prepare_payload(profile: ToolProfile) -> dict[str, Any]:
    tool_name = str(profile.tool_names[0] if profile.tool_names else profile.profile_id).strip()
    source = "bioconda"
    package_name = str(profile.package_name or tool_name).strip()
    package_spec = f"{source}::{package_name}"
    wrappers = profile_snakemake_wrappers(profile)
    dependency = _profile_primary_dependency(profile, wrappers, preferred_name=package_name)
    version = ""
    if dependency is not None:
        source = dependency["source"]
        package_name = dependency["name"]
        version = dependency["version"]
        package_spec = package_spec_from_conda_dependency(dependency)
    tool_id = f"{source}::{package_name}"
    draft = resolve_tool_profile(
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


def _wrapper_dependency(wrapper: dict[str, Any], *, preferred_name: str) -> dict[str, str] | None:
    hints = wrapper.get("wrapperContractHints") if isinstance(wrapper.get("wrapperContractHints"), dict) else {}
    return conda_dependency_from_environment_hints(hints, preferred_name=preferred_name)


def _source_label(source: str) -> str:
    return "Bioconda" if source == "bioconda" else source
