from __future__ import annotations

import re
from pathlib import Path, PurePosixPath
from typing import Any

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
    posix_path = PurePosixPath(path.replace("\\", "/"))
    if Path(path).is_absolute() or posix_path.is_absolute() or path in {".", ".."}:
        raise ToolRegistryError("TOOL_RULE_OUTPUT_PATH_INVALID")
    if any(part in {"", ".", ".."} for part in posix_path.parts):
        raise ToolRegistryError("TOOL_RULE_OUTPUT_PATH_INVALID")


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
