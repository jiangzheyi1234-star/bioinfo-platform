"""Prepare-job payloads for curated H2OMeta tool profiles."""

from __future__ import annotations

from typing import Any

from apps.api.tool_profile_model import ToolProfile
from apps.api.tool_profiles import resolve_tool_profile


def profile_prepare_payload(profile: ToolProfile) -> dict[str, Any]:
    tool_name = str(profile.tool_names[0] if profile.tool_names else profile.profile_id).strip()
    source = "bioconda"
    package_spec = f"{source}::{tool_name}"
    draft = resolve_tool_profile(
        {
            "id": package_spec,
            "name": tool_name,
            "source": source,
            "packageSpec": package_spec,
        }
    )
    return {
        "id": package_spec,
        "name": tool_name,
        "source": source,
        "sourceLabel": "Bioconda",
        "packageSpec": package_spec,
        "targetPlatform": "linux-64",
        "targetPlatformSupported": True,
        "ruleTemplate": dict((draft or {}).get("ruleTemplate") or {}),
        "ruleSpecDraft": dict(draft or {}),
    }
