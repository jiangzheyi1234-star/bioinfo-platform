"""Resolve discovered tool metadata into editable RuleSpec drafts."""

from __future__ import annotations

import re
from typing import Any

from apps.api.tool_profiles import resolve_tool_profile


class ToolContractResolver:
    def resolve_snakemake_wrapper(
        self,
        *,
        wrapper_repository: str,
        wrapper_ref: str,
        wrapper_path: str,
        wrapper_identifier: str,
    ) -> dict[str, Any]:
        lock = {
            "type": "snakemake-wrapper",
            "wrapperRepository": wrapper_repository,
            "wrapperRef": wrapper_ref,
            "wrapperPath": wrapper_path,
            "wrapperIdentifier": wrapper_identifier,
        }
        return {
            "source": "snakemake-wrapper",
            "contractSource": "snakemake-wrapper-importer",
            "status": "needs-user-completion",
            "reason": "WRAPPER_CONTRACT_UNRESOLVED",
            "requiresUserCompletion": True,
            "lock": lock,
            "ruleTemplate": {
                "source": "snakemake-wrapper",
                "wrapper": wrapper_identifier,
            },
            "notes": [
                "The wrapper reference is locked for reproducibility.",
                "Confirm wrapper-specific input, output, params, threads, and log fields before execution.",
            ],
        }

    def resolve_dependency(self, tool: dict[str, Any], *, wrappers: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        profile = resolve_tool_profile(tool, wrappers=wrappers)
        if profile is not None:
            return profile
        name = _clean_name(tool.get("name")) or "tool"
        source = _clean_name(tool.get("source")) or "conda"
        package_spec = _clean_name(tool.get("packageSpec")) or f"{source}::{name}"
        command = _command_name(name)
        output_path = f"{_safe_slug(name)}.out"
        return {
            "source": "conda-package",
            "contractSource": "command-template-builder",
            "status": "needs-user-completion",
            "requiresUserCompletion": True,
            "reason": "NO_TOOL_CONTRACT_SOURCE",
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

DEFAULT_TOOL_CONTRACT_RESOLVER = ToolContractResolver()


def _clean_name(value: Any) -> str:
    return str(value or "").strip()


def _command_name(name: str) -> str:
    candidate = re.sub(r"[^A-Za-z0-9_.+-]+", "-", name.strip()).strip("-")
    return candidate or "tool"


def _safe_slug(name: str) -> str:
    candidate = re.sub(r"[^A-Za-z0-9_]+", "_", name.strip().lower()).strip("_")
    return candidate or "tool"
