from __future__ import annotations

import re
from pathlib import Path
from typing import Any


def render_rule_output_lines(outputs: dict[str, Path], rule_template: dict[str, Any]) -> str:
    specs = _output_specs_by_name(rule_template)
    return "".join(
        f"        {_safe_snakemake_name(name)}={_render_output_value(path, specs.get(name, {}))},\n"
        for name, path in outputs.items()
    )


def output_artifact_flags(spec: dict[str, Any]) -> dict[str, bool]:
    flags: dict[str, bool] = {}
    for key in ["temp", "protected", "directory"]:
        if bool(spec.get(key)):
            flags[key] = True
    return flags


def _render_output_value(path: Path, spec: dict[str, Any]) -> str:
    rendered = repr(str(path))
    if bool(spec.get("directory")):
        rendered = f"directory({rendered})"
    if bool(spec.get("protected")):
        rendered = f"protected({rendered})"
    if bool(spec.get("temp")):
        rendered = f"temp({rendered})"
    return rendered


def _output_specs_by_name(rule_template: dict[str, Any]) -> dict[str, dict[str, Any]]:
    specs: dict[str, dict[str, Any]] = {}
    for item in rule_template.get("outputs") or []:
        if isinstance(item, dict):
            specs[str(item.get("name") or "")] = item
    return specs


def _safe_snakemake_name(value: str) -> str:
    name = re.sub(r"[^A-Za-z0-9_]+", "_", value).strip("_") or "output"
    if name in {"count", "index", "sort"}:
        return f"tool_{name}"
    if name[0].isdigit():
        return f"tool_{name}"
    return name
