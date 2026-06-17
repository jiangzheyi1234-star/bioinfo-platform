"""Stable identity helpers for profile-backed tools."""

from __future__ import annotations

from apps.api.tool_candidate_dependencies import normalize_package_name
from apps.api.tool_profile_model import ToolProfile


def profile_tool_name(profile: ToolProfile) -> str:
    return normalize_package_name(profile.profile_id) or normalize_package_name(
        profile.tool_names[0] if profile.tool_names else profile.package_name
    )


def profile_tool_id(profile: ToolProfile, *, source: str) -> str:
    return f"{source}::{profile_tool_name(profile)}"
