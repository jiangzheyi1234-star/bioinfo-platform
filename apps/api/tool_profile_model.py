"""Tool profile registry data model."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ToolProfile:
    profile_id: str
    version: int
    tool_names: tuple[str, ...]
    rule_template: dict[str, Any]
    preferred_wrapper_paths: tuple[str, ...] = ()
