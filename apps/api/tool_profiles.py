"""H2OMeta tool profile overlays for discovered conda tools."""

from __future__ import annotations

import re
from copy import deepcopy
from typing import Any

from .tool_profile_registry import TOOL_PROFILES, ToolProfile


PROFILE_CONTRACT_SOURCE = "h2ometa-tool-profile-registry"
PROFILE_WRAPPER_REPOSITORY = "snakemake/snakemake-wrappers"


def resolve_tool_profile(tool: dict[str, Any], *, wrappers: list[dict[str, Any]] | None = None) -> dict[str, Any] | None:
    profile = _profile_for_tool(tool.get("name"))
    if profile is None:
        return None

    package_spec = _clean(tool.get("packageSpec")) or _package_spec_from_identity(tool)
    matched_wrapper = _matched_wrapper(profile, wrappers or [])
    lock: dict[str, Any] = {
        "type": "h2ometa-tool-profile",
        "profileId": profile.profile_id,
        "profileVersion": profile.version,
        "packageSpec": package_spec,
        "version": _package_version(package_spec) or _clean(tool.get("latestVersion") or tool.get("version")),
        "source": _clean(tool.get("source")) or "bioconda",
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
    return sorted(profile.profile_id for profile in TOOL_PROFILES)


def _profile_rule_template(profile: ToolProfile, package_spec: str) -> dict[str, Any]:
    template = deepcopy(profile.rule_template)
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


def _package_spec_from_identity(tool: dict[str, Any]) -> str:
    source = _clean(tool.get("source")) or "bioconda"
    name = _clean(tool.get("name")) or "tool"
    version = _clean(tool.get("latestVersion") or tool.get("version"))
    return f"{source}::{name}={version}" if version else f"{source}::{name}"


def _package_version(package_spec: str) -> str:
    package = _clean(package_spec).rsplit("::", 1)[-1]
    if not package or any(operator in package for operator in (">", "<", "*")):
        return ""
    for operator in ("==", "="):
        if operator in package:
            return package.split(operator, 1)[1].split("=", 1)[0].strip()
    return ""


def _normalize_tool_name(value: Any) -> str:
    return re.sub(r"[^a-z0-9.+-]+", "-", _clean(value).lower()).strip("-")


def _clean(value: Any) -> str:
    return str(value or "").strip()


_PROFILE_BY_TOOL_NAME: dict[str, ToolProfile] | None = None


def _profile_for_tool(name: Any) -> ToolProfile | None:
    return _profile_by_tool_name().get(_normalize_tool_name(name))


def _profile_by_tool_name() -> dict[str, ToolProfile]:
    global _PROFILE_BY_TOOL_NAME
    if _PROFILE_BY_TOOL_NAME is None:
        _PROFILE_BY_TOOL_NAME = {
            _normalize_tool_name(tool_name): profile
            for profile in TOOL_PROFILES
            for tool_name in profile.tool_names
        }
    return _PROFILE_BY_TOOL_NAME
