"""H2OMeta tool profile overlays for discovered conda tools."""

from __future__ import annotations

import re
from typing import Any

from .tool_profile_model import ToolProfile
from .tool_profile_semantics import enrich_rule_template_semantics
from .tool_profile_sources import all_tool_profiles


PROFILE_CONTRACT_SOURCE = "h2ometa-tool-profile-registry"
PROFILE_WRAPPER_REPOSITORY = "snakemake/snakemake-wrappers"


def resolve_tool_profile(tool: dict[str, Any], *, wrappers: list[dict[str, Any]] | None = None) -> dict[str, Any] | None:
    profile = _profile_for_tool(tool.get("name"))
    if profile is None:
        return None
    return resolve_tool_profile_record(profile, tool, wrappers=wrappers)


def resolve_tool_profile_record(
    profile: ToolProfile,
    tool: dict[str, Any],
    *,
    wrappers: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    package_identity = _profile_package_identity(profile)
    package_spec = package_identity["packageSpec"]
    matched_wrapper = _matched_wrapper(profile, wrappers or [])
    lock: dict[str, Any] = {
        "type": "h2ometa-tool-profile",
        "profileId": profile.profile_id,
        "profileVersion": profile.version,
        "packageSpec": package_spec,
        "version": package_identity["version"],
        "source": package_identity["source"],
        "packageName": package_identity["packageName"],
    }
    profile_wrapper = _profile_wrapper_lock(profile)
    if profile_wrapper:
        lock.update(profile_wrapper)
    if matched_wrapper:
        lock["matchedWrapper"] = {
            "wrapperRepository": _clean(matched_wrapper.get("wrapperRepository")),
            "wrapperRef": _clean(matched_wrapper.get("wrapperRef")),
            "wrapperPath": _clean(matched_wrapper.get("wrapperPath")),
            "wrapperIdentifier": _clean(matched_wrapper.get("wrapperIdentifier")),
        }

    notes = [
        "H2OMeta profile supplied inputs, outputs, params, runtime, environment, resources, and smoke fixtures.",
        "Database requirements are declared through RuleSpec.resources and resolved through workflow resourceBindings.",
    ]
    if matched_wrapper:
        notes.append("A matching Snakemake wrapper was found and recorded for provenance.")

    return {
        "source": "h2ometa-tool-profile",
        "contractSource": PROFILE_CONTRACT_SOURCE,
        "status": "ready-for-validation",
        "requiresUserCompletion": False,
        "lock": lock,
        "ruleTemplate": _profile_rule_template(profile, package_spec),
        "notes": notes,
    }


def known_tool_profile_ids() -> list[str]:
    return sorted(profile.profile_id for profile in all_tool_profiles())


def _profile_rule_template(profile: ToolProfile, package_spec: str) -> dict[str, Any]:
    template = enrich_rule_template_semantics(profile.rule_template)
    conda = template.setdefault("environment", {}).setdefault("conda", {})
    dependencies = conda.get("dependencies")
    if isinstance(dependencies, list):
        conda["dependencies"] = [
            package_spec if str(dependency).strip() == "{packageSpec}" else dependency
            for dependency in dependencies
        ]
    elif package_spec:
        conda["dependencies"] = [package_spec]
    return template


def _matched_wrapper(profile: ToolProfile, wrappers: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not wrappers:
        return None
    preferred = set(profile.preferred_wrapper_paths)
    for wrapper in wrappers:
        if _clean(wrapper.get("wrapperPath")) in preferred:
            return wrapper
    return wrappers[0]


def _profile_wrapper_lock(profile: ToolProfile) -> dict[str, str]:
    wrapper = _clean(profile.rule_template.get("wrapper"))
    if not wrapper:
        return {}
    wrapper_ref, wrapper_path = _split_wrapper_identifier(wrapper)
    if not wrapper_ref or not wrapper_path:
        return {}
    return {
        "wrapperRepository": PROFILE_WRAPPER_REPOSITORY,
        "wrapperRef": wrapper_ref,
        "wrapperPath": wrapper_path,
        "wrapperIdentifier": wrapper,
    }


def _split_wrapper_identifier(wrapper: str) -> tuple[str, str]:
    parts = [part for part in _clean(wrapper).split("/") if part]
    if len(parts) < 2:
        return "", ""
    return parts[0], "/".join(parts[1:])


def _profile_package_identity(profile: ToolProfile) -> dict[str, str]:
    source = _clean(profile.package_source)
    package_name = _clean(profile.package_name)
    version = _clean(profile.package_version)
    if not source:
        raise ValueError("BIO_TOOL_PROFILE_PACKAGE_SOURCE_REQUIRED")
    if not package_name:
        raise ValueError("BIO_TOOL_PROFILE_PACKAGE_NAME_REQUIRED")
    if not version:
        raise ValueError("BIO_TOOL_PROFILE_PACKAGE_VERSION_REQUIRED")
    return {
        "source": source,
        "packageName": package_name,
        "version": version,
        "packageSpec": f"{source}::{package_name}={version}",
    }


def _normalize_tool_name(value: Any) -> str:
    return re.sub(r"[^a-z0-9.+-]+", "-", _clean(value).lower()).strip("-")


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _profile_for_tool(name: Any) -> ToolProfile | None:
    normalized = _normalize_tool_name(name)
    for profile in all_tool_profiles():
        if normalized in {_normalize_tool_name(tool_name) for tool_name in profile.tool_names}:
            return profile
    return None
