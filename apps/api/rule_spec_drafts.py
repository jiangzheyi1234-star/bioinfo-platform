"""RuleSpec draft builders for discovered tool dependencies."""

from __future__ import annotations

import re
from typing import Any


def build_dependency_rule_spec_draft(tool: dict[str, Any]) -> dict[str, Any]:
    name = _clean_name(tool.get("name")) or "tool"
    source = _clean_name(tool.get("source")) or "conda"
    package_spec = _clean_name(tool.get("packageSpec")) or f"{source}::{name}"
    command = _command_name(name)
    output_path = f"{_safe_slug(name)}.out"
    return {
        "source": "conda-package",
        "status": "needs-user-completion",
        "requiresUserCompletion": True,
        "reason": "NO_OFFICIAL_WRAPPER_MATCH",
        "lock": {
            "type": "conda-package",
            "source": source,
            "packageSpec": package_spec,
            "version": _clean_name(tool.get("latestVersion") or tool.get("version")),
        },
        "ruleTemplate": {
            "commandTemplate": f"{command} {{input.primary:q}} > {{output.primary:q}}",
            "inputs": [{"name": "primary", "type": "file", "required": True}],
            "outputs": [
                {
                    "name": "primary",
                    "path": output_path,
                    "kind": "file",
                    "mimeType": "application/octet-stream",
                }
            ],
            "params": {},
            "threads": 1,
            "log": f"logs/{_safe_slug(name)}.log",
        },
        "notes": [
            "This draft records the package dependency and a safe editable rule shape.",
            "Confirm the command, inputs, outputs, and parameters before using it in a DAG.",
        ],
    }


def build_wrapper_rule_spec_draft(
    *,
    wrapper_repository: str,
    wrapper_ref: str,
    wrapper_path: str,
    wrapper_identifier: str,
) -> dict[str, Any]:
    return {
        "source": "snakemake-wrapper",
        "status": "needs-user-completion",
        "requiresUserCompletion": True,
        "lock": {
            "type": "snakemake-wrapper",
            "wrapperRepository": wrapper_repository,
            "wrapperRef": wrapper_ref,
            "wrapperPath": wrapper_path,
            "wrapperIdentifier": wrapper_identifier,
        },
        "ruleTemplate": {
            "source": "snakemake-wrapper",
            "wrapper": wrapper_identifier,
        },
        "notes": [
            "The wrapper reference is locked for reproducibility.",
            "Confirm wrapper-specific input, output, params, threads, and log fields before execution.",
        ],
    }


def _clean_name(value: Any) -> str:
    return str(value or "").strip()


def _command_name(name: str) -> str:
    candidate = re.sub(r"[^A-Za-z0-9_.+-]+", "-", name.strip()).strip("-")
    return candidate or "tool"


def _safe_slug(name: str) -> str:
    candidate = re.sub(r"[^A-Za-z0-9_]+", "_", name.strip().lower()).strip("_")
    return candidate or "tool"
