from __future__ import annotations

import re
from pathlib import Path

from core.contracts.portable_relative_path import require_portable_relative_path


def safe_identifier(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("._") or "tool"


def safe_snakemake_name(value: str) -> str:
    name = re.sub(r"[^A-Za-z0-9_]+", "_", value).strip("_") or "output"
    if name in {"count", "index", "sort"}:
        return f"tool_{name}"
    if name[0].isdigit():
        return f"tool_{name}"
    return name


def safe_relative_output_path(value: str) -> Path:
    if not value:
        raise ValueError("TOOL_OUTPUT_PATH_REQUIRED")
    normalized = require_portable_relative_path(
        value, error_code="TOOL_OUTPUT_PATH_INVALID"
    )
    return Path(*normalized.split("/"))
