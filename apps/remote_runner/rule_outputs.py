from __future__ import annotations

from dataclasses import dataclass
import re
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class SnakemakeExpression:
    expression: str

    def __str__(self) -> str:
        return self.expression


def render_rule_output_lines(outputs: dict[str, Path | SnakemakeExpression], rule_template: dict[str, Any]) -> str:
    specs = rule_output_specs_by_name(rule_template)
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


def output_spec_metadata(spec: dict[str, Any], *, path: Path | None = None) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    if path is not None:
        metadata["path"] = str(path)
    for key in ["kind", "mimeType", "type", "data", "format"]:
        value = str(spec.get(key) or "").strip()
        if value:
            metadata[key] = value
    metadata.update(output_artifact_flags(spec))
    return metadata


def rule_output_metadata(outputs: dict[str, Path], rule_template: dict[str, Any]) -> dict[str, dict[str, Any]]:
    specs = rule_output_specs_by_name(rule_template)
    return {name: output_spec_metadata(specs.get(name, {}), path=path) for name, path in outputs.items()}


def output_is_exposable(spec: dict[str, Any]) -> bool:
    return not bool(spec.get("temp"))


def validate_exposed_output_spec(step_id: str, output_name: str, spec: dict[str, Any]) -> None:
    if not output_is_exposable(spec):
        raise ValueError(f"WORKFLOW_OUTPUT_TEMP_EXPOSED: {step_id}.{output_name}")


def rule_output_specs_by_name(rule_template: dict[str, Any]) -> dict[str, dict[str, Any]]:
    specs: dict[str, dict[str, Any]] = {}
    for item in rule_template.get("outputs") or []:
        if isinstance(item, dict):
            specs[str(item.get("name") or "")] = item
    return specs


def _render_output_value(path: Path | SnakemakeExpression, spec: dict[str, Any]) -> str:
    rendered = str(path) if isinstance(path, SnakemakeExpression) else repr(path.as_posix())
    if bool(spec.get("directory")):
        rendered = f"directory({rendered})"
    if bool(spec.get("protected")):
        rendered = f"protected({rendered})"
    if bool(spec.get("temp")):
        rendered = f"temp({rendered})"
    return rendered


def _safe_snakemake_name(value: str) -> str:
    name = re.sub(r"[^A-Za-z0-9_]+", "_", value).strip("_") or "output"
    if name in {"count", "index", "sort"}:
        return f"tool_{name}"
    if name[0].isdigit():
        return f"tool_{name}"
    return name
