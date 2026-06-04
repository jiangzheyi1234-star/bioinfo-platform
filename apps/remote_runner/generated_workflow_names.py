from __future__ import annotations

import re
from pathlib import Path, PurePosixPath


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
    posix_path = PurePosixPath(value.replace("\\", "/"))
    parts = list(posix_path.parts)
    if Path(value).is_absolute() or posix_path.is_absolute() or any(part in {"", ".", ".."} for part in parts):
        raise ValueError("TOOL_OUTPUT_PATH_INVALID")
    if not parts:
        raise ValueError("TOOL_OUTPUT_PATH_REQUIRED")
    return Path(*parts)
