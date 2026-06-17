"""Open-source evidence attached to curated tool profiles."""

from __future__ import annotations

from typing import Any

from apps.api.snakemake_wrappers import find_snakemake_wrappers_for_tool
from apps.api.snakemake_wrappers.archive import (
    SNAKEMAKE_WRAPPERS_REF,
    SNAKEMAKE_WRAPPERS_REPOSITORY,
    SNAKEMAKE_WRAPPERS_WEB_ROOT,
)
from apps.api.snakemake_wrappers.package_metadata import wrapper_environment_url
from apps.api.tool_profile_model import ToolProfile

_DEFAULT_WRAPPER_LOOKUP_MODULE = "apps.api.snakemake_wrappers.catalog"
_STATIC_WRAPPER_DEPENDENCIES = {
    "bio/fastqc": ["fastqc =0.12.1", "snakemake-wrapper-utils =0.8.0"],
}


def profile_external_refs(profile: ToolProfile) -> list[dict[str, Any]]:
    refs = [dict(ref) for ref in profile.source_refs]
    refs.extend(_package_registry_refs(profile))
    refs.extend(_wrapper_external_ref(wrapper) for wrapper in profile_snakemake_wrappers(profile))
    return refs


def profile_snakemake_wrappers(profile: ToolProfile, *, limit: int = 4) -> list[dict[str, Any]]:
    static_wrappers = _static_profile_snakemake_wrappers(profile, limit=limit)
    if profile.pack_id and _using_default_wrapper_lookup():
        return static_wrappers

    wrappers_by_path: dict[str, dict[str, Any]] = {}
    tool_names = [*profile.tool_names]
    if profile.package_name:
        tool_names.append(profile.package_name)
    for tool_name in tool_names:
        for wrapper in find_snakemake_wrappers_for_tool(tool_name):
            path = str(wrapper.get("wrapperPath") or "").strip()
            if path:
                wrappers_by_path.setdefault(path, wrapper)
    if not wrappers_by_path and (static_wrappers or profile.pack_id):
        return static_wrappers

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


def _static_profile_snakemake_wrappers(profile: ToolProfile, *, limit: int) -> list[dict[str, Any]]:
    wrappers: list[dict[str, Any]] = []
    for wrapper_ref, wrapper_path, wrapper_identifier in _profile_wrapper_identifiers(profile):
        wrapper = {
            "wrapperRepository": SNAKEMAKE_WRAPPERS_REPOSITORY,
            "wrapperRef": wrapper_ref,
            "wrapperPath": wrapper_path,
            "wrapperIdentifier": wrapper_identifier,
            "wrapperUrl": f"{SNAKEMAKE_WRAPPERS_WEB_ROOT}/{wrapper_path}",
            "environmentUrl": wrapper_environment_url(wrapper_path),
            "sourceRef": {
                "type": "snakemake-wrapper",
                "packId": profile.pack_id,
                "profileId": profile.profile_id,
                "derivation": "bio-tool-pack-profile",
            },
            "wrapperContractHints": _profile_wrapper_contract_hints(profile, wrapper_path=wrapper_path),
        }
        wrappers.append(wrapper)
    return [_wrapper_evidence(wrapper) for wrapper in wrappers[: max(0, limit)]]


def _profile_wrapper_identifiers(profile: ToolProfile) -> list[tuple[str, str, str]]:
    identifiers: list[tuple[str, str, str]] = []
    seen_paths: set[str] = set()
    wrapper = str(profile.rule_template.get("wrapper") or "").strip()
    if wrapper:
        wrapper_ref, wrapper_path = _split_wrapper_identifier(wrapper)
        if wrapper_ref and wrapper_path:
            identifiers.append((wrapper_ref, wrapper_path, wrapper))
            seen_paths.add(wrapper_path)
    for wrapper_path in profile.preferred_wrapper_paths:
        path = str(wrapper_path or "").strip()
        if path and path not in seen_paths:
            identifiers.append((SNAKEMAKE_WRAPPERS_REF, path, f"{SNAKEMAKE_WRAPPERS_REF}/{path}"))
            seen_paths.add(path)
    return identifiers


def _profile_wrapper_contract_hints(profile: ToolProfile, *, wrapper_path: str) -> dict[str, Any]:
    template = profile.rule_template
    conda = template.get("environment", {}).get("conda", {}) if isinstance(template.get("environment"), dict) else {}
    channels = [str(item).strip() for item in conda.get("channels", []) if str(item or "").strip()]
    dependencies = _STATIC_WRAPPER_DEPENDENCIES.get(wrapper_path) or [
        _static_dependency(str(item or "").strip(), profile)
        for item in conda.get("dependencies", [])
        if str(item or "").strip()
    ]
    return {"environment": {"conda": {"channels": channels, "dependencies": dependencies}}}


def _static_dependency(dependency: str, profile: ToolProfile) -> str:
    if dependency == "{packageSpec}":
        return _profile_package_spec(profile)
    return dependency


def _split_wrapper_identifier(wrapper: str) -> tuple[str, str]:
    parts = [part for part in str(wrapper or "").strip().split("/") if part]
    if len(parts) < 2:
        return "", ""
    return parts[0], "/".join(parts[1:])


def _using_default_wrapper_lookup() -> bool:
    return getattr(find_snakemake_wrappers_for_tool, "__module__", "") == _DEFAULT_WRAPPER_LOOKUP_MODULE


def profile_external_candidate_fields(profile: ToolProfile) -> dict[str, Any]:
    wrappers = profile_snakemake_wrappers(profile)
    return {
        "externalRefs": [
            *[dict(ref) for ref in profile.source_refs],
            *_package_registry_refs(profile),
            *[_wrapper_external_ref(wrapper) for wrapper in wrappers],
        ],
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
    contract_hints = wrapper.get("wrapperContractHints")
    if isinstance(contract_hints, dict) and contract_hints:
        evidence["wrapperContractHints"] = dict(contract_hints)
    return evidence


def _package_registry_refs(profile: ToolProfile) -> list[dict[str, Any]]:
    package_name = _profile_package_name(profile)
    package_source = _profile_package_source(profile)
    if not package_name:
        return []
    biotools_id = _biotools_id(profile)
    refs = [
        {
            "type": "bioconda-package" if package_source == "bioconda" else "conda-package",
            "channel": package_source,
            "name": package_name,
            "url": f"https://anaconda.org/{package_source}/{package_name}",
            "verified": True,
        }
    ]
    if package_source == "bioconda":
        refs.append(
            {
                "type": "biocontainers-container",
                "registry": "quay.io",
                "namespace": "biocontainers",
                "name": package_name,
                "image": f"quay.io/biocontainers/{package_name}",
                "registryUrl": "https://biocontainers.pro/",
                "verified": False,
                "derivation": "bioconda-package-name",
            }
        )
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


def _profile_package_name(profile: ToolProfile) -> str:
    return str(profile.package_name or (profile.tool_names[0] if profile.tool_names else profile.profile_id)).strip()


def _profile_package_source(profile: ToolProfile) -> str:
    return str(profile.package_source or "").strip()


def _profile_package_spec(profile: ToolProfile) -> str:
    source = _profile_package_source(profile)
    package_name = _profile_package_name(profile)
    version = str(profile.package_version or "").strip()
    return f"{source}::{package_name}={version}" if version else f"{source}::{package_name}"


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
