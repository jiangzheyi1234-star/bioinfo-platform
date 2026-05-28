from __future__ import annotations

import re
from pathlib import Path, PurePosixPath
from typing import Any

from .config import RemoteRunnerConfig
from .storage import delete_tool, fetch_tool, list_tools, update_tool_status, upsert_tool


class ToolRegistryError(ValueError):
    pass


ALLOWED_SOURCES = {"bioconda", "conda-forge"}
RULE_IO_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
RULE_TOKEN_RE = re.compile(r"\{[^{}\s]+\}")
DATABASE_TOKEN_RE = re.compile(
    r"^database\.[A-Za-z_][A-Za-z0-9_]*\.(id|name|type|templateId|version|path|manifestPath|checksum)(:q)?$"
)
CONFIG_TOKEN_RE = re.compile(r"^config\.[A-Za-z_][A-Za-z0-9_]*(:q)?$")


def list_registered_tools(cfg: RemoteRunnerConfig) -> list[dict[str, Any]]:
    return list_tools(cfg)


def add_registered_tool(cfg: RemoteRunnerConfig, payload: dict[str, Any]) -> dict[str, Any]:
    item = _normalize_tool_manifest(payload)
    item["ruleTemplate"] = normalize_rule_template(item.get("ruleTemplate"), required=False)
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
    try:
        normalize_rule_template(item.get("ruleTemplate"), required=True)
    except ToolRegistryError as exc:
        return update_tool_status(
            cfg,
            tool_id=normalized,
            status="failed",
            message=str(exc),
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
        "ruleTemplate": payload.get("ruleTemplate") or {},
        "status": str(payload.get("status") or "declared"),
        "message": str(payload.get("message") or "Tool declared."),
    }


def normalize_rule_template(raw: Any, *, required: bool = True) -> dict[str, Any]:
    if raw in (None, {}):
        if required:
            raise ToolRegistryError("TOOL_RULE_TEMPLATE_REQUIRED")
        return {}
    if not isinstance(raw, dict):
        raise ToolRegistryError("TOOL_RULE_TEMPLATE_INVALID")
    template = dict(raw)
    command = str(template.get("commandTemplate") or "").strip()
    if not command:
        raise ToolRegistryError("TOOL_RULE_COMMAND_REQUIRED")
    inputs = _normalize_rule_inputs(template.get("inputs"))
    outputs = _normalize_rule_outputs(template.get("outputs"))
    resources = _normalize_rule_resources(template.get("resources"))
    params = template.get("params") or {}
    if not isinstance(params, dict):
        raise ToolRegistryError("TOOL_RULE_PARAMS_INVALID")
    _validate_command_tokens(
        command,
        input_names={item["name"] for item in inputs},
        output_names={item["name"] for item in outputs},
    )
    normalized: dict[str, Any] = {
        "commandTemplate": command,
        "inputs": inputs,
        "outputs": outputs,
        "params": dict(params),
    }
    if resources:
        normalized["resources"] = resources
    return normalized


def _normalize_rule_inputs(raw: Any) -> list[dict[str, Any]]:
    if raw is None:
        raw = [{"name": "primary", "type": "file", "required": True}]
    if not isinstance(raw, list) or not raw:
        raise ToolRegistryError("TOOL_RULE_INPUTS_INVALID")
    inputs: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            raise ToolRegistryError("TOOL_RULE_INPUTS_INVALID")
        name = _normalize_io_name(item.get("name"))
        if name in seen:
            raise ToolRegistryError(f"TOOL_RULE_IO_NAME_DUPLICATE: {name}")
        seen.add(name)
        inputs.append(
            {
                **item,
                "name": name,
                "type": str(item.get("type") or "file"),
                "required": bool(item.get("required", True)),
            }
        )
    return inputs


def _normalize_rule_outputs(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list) or not raw:
        raise ToolRegistryError("TOOL_RULE_OUTPUTS_INVALID")
    outputs: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            raise ToolRegistryError("TOOL_RULE_OUTPUTS_INVALID")
        name = _normalize_io_name(item.get("name"))
        if name in seen:
            raise ToolRegistryError(f"TOOL_RULE_IO_NAME_DUPLICATE: {name}")
        seen.add(name)
        path = str(item.get("path") or "").strip()
        kind = str(item.get("kind") or "").strip()
        mime_type = str(item.get("mimeType") or "").strip()
        if not path or not kind or not mime_type:
            raise ToolRegistryError("TOOL_RULE_OUTPUT_SPEC_INVALID")
        _validate_relative_output_path(path)
        outputs.append({**item, "name": name, "path": path, "kind": kind, "mimeType": mime_type})
    return outputs


def _normalize_rule_resources(raw: Any) -> dict[str, dict[str, Any]]:
    if raw in (None, {}):
        return {}
    if not isinstance(raw, dict):
        raise ToolRegistryError("WORKFLOW_RESOURCE_SPEC_INVALID")
    resources: dict[str, dict[str, Any]] = {}
    for key, value in raw.items():
        resource_key = str(key or "").strip()
        if not resource_key or not RULE_IO_NAME_RE.match(resource_key):
            raise ToolRegistryError("WORKFLOW_RESOURCE_KEY_REQUIRED")
        if not isinstance(value, dict):
            raise ToolRegistryError(f"WORKFLOW_RESOURCE_SPEC_INVALID: {resource_key}")
        config_key = str(value.get("configKey") or resource_key).strip()
        if not config_key or not RULE_IO_NAME_RE.match(config_key):
            raise ToolRegistryError(f"WORKFLOW_RESOURCE_CONFIG_KEY_REQUIRED: {resource_key}")
        accepted_templates = value.get("acceptedTemplates") or []
        if accepted_templates and (
            not isinstance(accepted_templates, list)
            or any(not str(item).strip() for item in accepted_templates)
        ):
            raise ToolRegistryError(f"WORKFLOW_RESOURCE_ACCEPTED_TEMPLATES_INVALID: {resource_key}")
        resources[resource_key] = {**value, "configKey": config_key}
    return resources


def _normalize_io_name(raw: Any) -> str:
    name = str(raw or "").strip()
    if not name:
        raise ToolRegistryError("TOOL_RULE_IO_NAME_REQUIRED")
    if not RULE_IO_NAME_RE.match(name):
        raise ToolRegistryError(f"TOOL_RULE_IO_NAME_INVALID: {name}")
    return name


def _validate_relative_output_path(path: str) -> None:
    posix_path = PurePosixPath(path.replace("\\", "/"))
    if Path(path).is_absolute() or posix_path.is_absolute() or path in {".", ".."}:
        raise ToolRegistryError("TOOL_RULE_OUTPUT_PATH_INVALID")
    if any(part in {"", ".", ".."} for part in posix_path.parts):
        raise ToolRegistryError("TOOL_RULE_OUTPUT_PATH_INVALID")


def _validate_command_tokens(command: str, *, input_names: set[str], output_names: set[str]) -> None:
    if "{resource." in command:
        raise ToolRegistryError("TOOL_RULE_RESOURCE_TOKEN_UNSUPPORTED")
    for match in RULE_TOKEN_RE.finditer(command):
        token = match.group(0)
        body = token[1:-1]
        if body in {"input", "input:q", "output", "output:q", "output_dir", "output_dir:q"}:
            continue
        if body.startswith("input."):
            name = body.removeprefix("input.").removesuffix(":q")
            if name in input_names:
                continue
            raise ToolRegistryError(f"TOOL_RULE_TOKEN_UNSUPPORTED: {token}")
        if body.startswith("output."):
            name = body.removeprefix("output.").removesuffix(":q")
            if name in output_names:
                continue
            raise ToolRegistryError(f"TOOL_RULE_TOKEN_UNSUPPORTED: {token}")
        if DATABASE_TOKEN_RE.match(body) or CONFIG_TOKEN_RE.match(body):
            continue
        raise ToolRegistryError(f"TOOL_RULE_TOKEN_UNSUPPORTED: {token}")
