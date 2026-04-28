from __future__ import annotations

from pathlib import Path
from typing import Any

from .config import RemoteRunnerConfig
from .storage import delete_tool, fetch_tool, list_tools, update_tool_status, upsert_tool


class ToolRegistryError(ValueError):
    pass


ALLOWED_SOURCES = {"bioconda", "conda-forge"}


def list_registered_tools(cfg: RemoteRunnerConfig) -> list[dict[str, Any]]:
    return list_tools(cfg)


def add_registered_tool(cfg: RemoteRunnerConfig, payload: dict[str, Any]) -> dict[str, Any]:
    item = _normalize_tool_manifest(payload)
    _validate_rule_template(item.get("ruleTemplate") or {})
    return upsert_tool(cfg, item)


def remove_registered_tool(cfg: RemoteRunnerConfig, tool_id: str) -> None:
    normalized = str(tool_id or "").strip()
    if not normalized:
        raise ToolRegistryError("TOOL_ID_REQUIRED")
    try:
        delete_tool(cfg, normalized)
    except KeyError as exc:
        raise ToolRegistryError("TOOL_NOT_FOUND") from exc


def check_registered_tool(cfg: RemoteRunnerConfig, tool_id: str) -> dict[str, Any]:
    normalized = str(tool_id or "").strip()
    if not normalized:
        raise ToolRegistryError("TOOL_ID_REQUIRED")
    item = fetch_tool(cfg, normalized)
    if item is None:
        raise ToolRegistryError("TOOL_NOT_FOUND")

    if not bool(item.get("targetPlatformSupported")):
        return update_tool_status(
            cfg,
            tool_id=normalized,
            status="failed",
            message=f"{item.get('targetPlatform') or 'linux-64'} is not supported by this package.",
        )

    conda_command = str(cfg.managed_conda_command or "").strip()
    if not conda_command:
        return update_tool_status(
            cfg,
            tool_id=normalized,
            status="failed",
            message="Conda command is not configured on the remote runner.",
        )
    conda_path = Path(conda_command)
    if not conda_path.exists():
        return update_tool_status(
            cfg,
            tool_id=normalized,
            status="failed",
            message=f"Conda command does not exist: {conda_command}",
        )

    return update_tool_status(
        cfg,
        tool_id=normalized,
        status="declared",
        message="Tool manifest is valid and the workflow runtime is available.",
    )


def _normalize_tool_manifest(payload: dict[str, Any]) -> dict[str, Any]:
    source = str(payload.get("source") or "").strip()
    name = str(payload.get("name") or "").strip()
    if source not in ALLOWED_SOURCES:
        raise ToolRegistryError("TOOL_SOURCE_UNSUPPORTED")
    if not name:
        raise ToolRegistryError("TOOL_NAME_REQUIRED")

    package_spec = str(payload.get("packageSpec") or "").strip()
    if not package_spec:
        version = str(payload.get("version") or "").strip()
        package_spec = f"{source}::{name}={version}" if version else f"{source}::{name}"

    tool_id = str(payload.get("id") or f"{source}::{name}").strip()
    return {
        "id": tool_id,
        "name": name,
        "source": source,
        "sourceLabel": str(payload.get("sourceLabel") or source),
        "version": str(payload.get("version") or ""),
        "packageSpec": package_spec,
        "summary": str(payload.get("summary") or ""),
        "targetPlatform": str(payload.get("targetPlatform") or "linux-64"),
        "targetPlatformSupported": bool(payload.get("targetPlatformSupported")),
        "platforms": [str(item) for item in (payload.get("platforms") or []) if str(item).strip()],
        "sourceUrl": str(payload.get("sourceUrl") or ""),
        "testCommand": str(payload.get("testCommand") or ""),
        "ruleTemplate": dict(payload.get("ruleTemplate") or {}),
        "status": str(payload.get("status") or "declared"),
        "message": str(payload.get("message") or "Tool declared."),
    }


def _validate_rule_template(template: dict[str, Any]) -> None:
    if not template:
        return
    command = str(template.get("commandTemplate") or "").strip()
    if not command:
        raise ToolRegistryError("TOOL_RULE_COMMAND_REQUIRED")
    inputs = template.get("inputs") or [{"name": "primary"}]
    outputs = template.get("outputs") or []
    if not isinstance(inputs, list) or not inputs:
        raise ToolRegistryError("TOOL_RULE_INPUTS_INVALID")
    if not isinstance(outputs, list) or not outputs:
        raise ToolRegistryError("TOOL_RULE_OUTPUTS_INVALID")
    input_names = {str(item.get("name") or "").strip() for item in inputs if isinstance(item, dict)}
    output_names = {str(item.get("name") or "").strip() for item in outputs if isinstance(item, dict)}
    if "" in input_names or "" in output_names:
        raise ToolRegistryError("TOOL_RULE_IO_NAME_REQUIRED")
    if not output_names:
        raise ToolRegistryError("TOOL_RULE_OUTPUTS_INVALID")
