"""Prepare-job payloads for curated H2OMeta tool profiles."""

from __future__ import annotations

from typing import Any

from apps.api.tool_candidate_dependencies import (
    package_spec_from_conda_dependency,
)
from apps.api.tool_profile_external_refs import profile_snakemake_wrappers
from apps.api.tool_profile_identity import profile_tool_id
from apps.api.tool_profile_model import ToolProfile
from apps.api.tool_profiles import resolve_tool_profile_record


def profile_prepare_payload(profile: ToolProfile) -> dict[str, Any]:
    tool_name = str(profile.tool_names[0] if profile.tool_names else profile.profile_id).strip()
    package_name = str(profile.package_name or tool_name).strip()
    dependency = _profile_locked_dependency(profile, preferred_name=package_name)
    source = dependency["source"]
    package_name = dependency["name"]
    version = dependency["version"]
    package_spec = package_spec_from_conda_dependency(dependency)
    wrappers = profile_snakemake_wrappers(profile)
    tool_id = profile_tool_id(profile, source=source)
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
        "profileId": profile.profile_id,
        "profileVersion": profile.version,
        "packId": profile.pack_id,
        "packageName": package_name,
        "validationTarget": profile.profile_id,
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


def _profile_locked_dependency(profile: ToolProfile, *, preferred_name: str) -> dict[str, str]:
    source = str(profile.package_source or "").strip()
    package_name = str(profile.package_name or preferred_name).strip()
    version = str(profile.package_version or "").strip()
    if not source:
        raise ValueError("BIO_TOOL_PROFILE_PACKAGE_SOURCE_REQUIRED")
    if not package_name:
        raise ValueError("BIO_TOOL_PROFILE_PACKAGE_NAME_REQUIRED")
    if not version:
        raise ValueError("BIO_TOOL_PROFILE_PACKAGE_VERSION_REQUIRED")
    return {"source": source, "name": package_name, "version": version}


def _source_label(source: str) -> str:
    return "Bioconda" if source == "bioconda" else source
