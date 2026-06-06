"""Open-source evidence attached to curated tool profiles."""

from __future__ import annotations

from typing import Any

from apps.api.snakemake_wrappers import find_snakemake_wrappers_for_tool
from apps.api.tool_profile_model import ToolProfile


def profile_external_refs(profile: ToolProfile) -> list[dict[str, Any]]:
    refs = _package_registry_refs(profile)
    refs.extend(_wrapper_external_ref(wrapper) for wrapper in profile_snakemake_wrappers(profile))
    return refs


def profile_snakemake_wrappers(profile: ToolProfile, *, limit: int = 4) -> list[dict[str, Any]]:
    wrappers_by_path: dict[str, dict[str, Any]] = {}
    tool_names = [*profile.tool_names]
    if profile.package_name:
        tool_names.append(profile.package_name)
    for tool_name in tool_names:
        for wrapper in find_snakemake_wrappers_for_tool(tool_name):
            path = str(wrapper.get("wrapperPath") or "").strip()
            if path:
                wrappers_by_path.setdefault(path, wrapper)

    preferred = [
        wrappers_by_path[path]
        for path in profile.preferred_wrapper_paths
        if path in wrappers_by_path
    ]
    fallback = [
        wrapper
        for path, wrapper in sorted(wrappers_by_path.items())
        if path not in set(profile.preferred_wrapper_paths)
    ]
    return [_wrapper_evidence(wrapper) for wrapper in [*preferred, *fallback][: max(0, limit)]]


def profile_external_candidate_fields(profile: ToolProfile) -> dict[str, Any]:
    wrappers = profile_snakemake_wrappers(profile)
    return {
        "externalRefs": [*_package_registry_refs(profile), *[_wrapper_external_ref(wrapper) for wrapper in wrappers]],
        "snakemakeWrappers": wrappers,
        "snakemakeWrapperCount": len(wrappers),
    }


def _wrapper_evidence(wrapper: dict[str, Any]) -> dict[str, Any]:
    evidence = {
        "wrapperRepository": str(wrapper.get("wrapperRepository") or "").strip(),
        "wrapperRef": str(wrapper.get("wrapperRef") or "").strip(),
        "wrapperPath": str(wrapper.get("wrapperPath") or "").strip(),
        "wrapperIdentifier": str(wrapper.get("wrapperIdentifier") or "").strip(),
        "sourceRef": dict(wrapper.get("sourceRef") or {}),
    }
    wrapper_url = str(wrapper.get("wrapperUrl") or "").strip()
    if wrapper_url:
        evidence["wrapperUrl"] = wrapper_url
    environment_url = str(wrapper.get("environmentUrl") or "").strip()
    if environment_url:
        evidence["environmentUrl"] = environment_url
    return evidence


def _package_registry_refs(profile: ToolProfile) -> list[dict[str, Any]]:
    package_name = str(profile.package_name or profile.tool_names[0] if profile.tool_names else profile.profile_id).strip()
    if not package_name:
        return []
    biotools_id = _biotools_id(profile)
    refs = [
        {
            "type": "bioconda-package",
            "channel": "bioconda",
            "name": package_name,
            "url": f"https://anaconda.org/bioconda/{package_name}",
            "verified": True,
        },
        {
            "type": "biocontainers-container",
            "registry": "quay.io",
            "namespace": "biocontainers",
            "name": package_name,
            "image": f"quay.io/biocontainers/{package_name}",
            "registryUrl": "https://biocontainers.pro/",
            "verified": False,
            "derivation": "bioconda-package-name",
        },
    ]
    if biotools_id:
        refs.append(
            {
                "type": "bio.tools-entry",
                "biotoolsId": biotools_id,
                "url": f"https://bio.tools/{biotools_id}",
                "verified": False,
                "derivation": "tool-name-normalized",
            }
        )
    return refs


def _wrapper_external_ref(wrapper: dict[str, Any]) -> dict[str, Any]:
    ref = {
        "type": "snakemake-wrapper",
        "repository": str(wrapper.get("wrapperRepository") or "").strip(),
        "ref": str(wrapper.get("wrapperRef") or "").strip(),
        "path": str(wrapper.get("wrapperPath") or "").strip(),
        "identifier": str(wrapper.get("wrapperIdentifier") or "").strip(),
        "verified": True,
    }
    url = str(wrapper.get("wrapperUrl") or "").strip()
    if url:
        ref["url"] = url
    return ref


def _biotools_id(profile: ToolProfile) -> str:
    tool_name = str(profile.tool_names[0] if profile.tool_names else profile.package_name or profile.profile_id).strip().lower()
    return "".join(character if character.isalnum() else "-" for character in tool_name).strip("-")
