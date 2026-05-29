from __future__ import annotations

import re
from typing import Any


def render_rule_param_lines(params: dict[str, Any]) -> str:
    if not params:
        return ""
    lines = ["    params:\n"]
    for name, value in params.items():
        lines.append(f"        {_safe_snakemake_name(name)}={value!r},\n")
    return "".join(lines)


def _safe_snakemake_name(value: str) -> str:
    name = re.sub(r"[^A-Za-z0-9_]+", "_", value).strip("_") or "param"
    if name in {"count", "index", "sort"}:
        return f"tool_{name}"
    if name[0].isdigit():
        return f"tool_{name}"
    return name
