"""Tool profile registry data model."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ToolProfile:
    profile_id: str
    version: int
    tool_names: tuple[str, ...]
    rule_template: dict[str, Any]
    preferred_wrapper_paths: tuple[str, ...] = ()
    package_name: str = ""
    package_source: str = ""
    package_version: str = ""
    pack_id: str = ""
    workflow_stage: str = ""
    operation: str = ""
    license: str = ""
    citations: tuple[str, ...] = ()
    source_refs: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    report_schemas: tuple[dict[str, Any], ...] = field(default_factory=tuple)
