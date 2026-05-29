from __future__ import annotations

import re


PARAM_TOKEN_RE = re.compile(r"\{params\.([A-Za-z_][A-Za-z0-9_]*)(?::q)?\}")
INPUT_TOKEN_RE = re.compile(r"\{input\.([A-Za-z_][A-Za-z0-9_]*)(?::q)?\}")


def command_param_names(command_template: str) -> set[str]:
    return {match.group(1) for match in PARAM_TOKEN_RE.finditer(command_template)}


def command_input_names(command_template: str) -> set[str]:
    return {_safe_snakemake_name(match.group(1)) for match in INPUT_TOKEN_RE.finditer(command_template)}


def validate_command_input_tokens_bound(*, rule_template: dict[str, object], inputs: dict[str, str]) -> None:
    provided = {_safe_snakemake_name(name) for name in inputs}
    for name in command_input_names(str(rule_template.get("commandTemplate") or "")):
        if name not in provided:
            raise ValueError(f"WORKFLOW_STEP_INPUT_TOKEN_UNBOUND: {name}")


def _safe_snakemake_name(value: str) -> str:
    name = re.sub(r"[^A-Za-z0-9_]+", "_", value).strip("_") or "output"
    if name in {"count", "index", "sort"}:
        return f"tool_{name}"
    if name[0].isdigit():
        return f"tool_{name}"
    return name
