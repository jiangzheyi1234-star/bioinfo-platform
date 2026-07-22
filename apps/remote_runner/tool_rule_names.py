from __future__ import annotations

import re
from typing import Any

from core.contracts.portable_relative_path import require_portable_relative_path

from .tools_errors import ToolRegistryError


RULE_IO_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def normalize_io_name(raw: Any) -> str:
    name = str(raw or "").strip()
    if not name:
        raise ToolRegistryError("TOOL_RULE_IO_NAME_REQUIRED")
    if not RULE_IO_NAME_RE.match(name):
        raise ToolRegistryError(f"TOOL_RULE_IO_NAME_INVALID: {name}")
    return name


def validate_relative_output_path(path: str) -> None:
    try:
        require_portable_relative_path(path, error_code="TOOL_RULE_OUTPUT_PATH_INVALID")
    except ValueError as exc:
        raise ToolRegistryError("TOOL_RULE_OUTPUT_PATH_INVALID") from exc


def validate_relative_log_path(path: str) -> None:
    try:
        validate_relative_output_path(path)
    except ToolRegistryError as exc:
        raise ToolRegistryError("TOOL_RULE_LOG_PATH_INVALID") from exc


def validate_relative_module_path(path: str) -> None:
    try:
        validate_relative_output_path(path)
    except ToolRegistryError as exc:
        raise ToolRegistryError("TOOL_RULE_MODULE_PATH_INVALID") from exc
