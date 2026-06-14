"""Aggregate built-in and enabled Bio Tool Pack profiles."""

from __future__ import annotations

from .bio_tool_pack_store import enabled_bio_tool_pack_profiles
from .tool_profile_definitions import TOOL_PROFILES
from .tool_profile_model import ToolProfile


def all_tool_profiles() -> tuple[ToolProfile, ...]:
    return (*TOOL_PROFILES, *enabled_bio_tool_pack_profiles())
