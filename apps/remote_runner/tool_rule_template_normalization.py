from __future__ import annotations

from typing import Any

from .rule_smoke import normalize_rule_smoke_test
from .tool_rule_command_tokens import validate_command_tokens
from .tool_rule_environment import normalize_rule_environment
from .tool_rule_names import (
    RULE_IO_NAME_RE,
    normalize_io_name,
    validate_relative_log_path,
    validate_relative_module_path,
    validate_relative_output_path,
)
from .tool_rule_resources import (
    normalize_rule_resources,
    normalize_rule_threads,
    normalize_scheduler_resources,
)
from .tools_errors import ToolRegistryError


def normalize_rule_template(raw: Any, *, required: bool = True) -> dict[str, Any]:
    if raw in (None, {}):
        if required:
            raise ToolRegistryError("TOOL_RULE_TEMPLATE_REQUIRED")
        return {}
    if not isinstance(raw, dict):
        raise ToolRegistryError("TOOL_RULE_TEMPLATE_INVALID")
    template = dict(raw)
    command = str(template.get("commandTemplate") or "").strip()
    wrapper = _normalize_rule_wrapper(template.get("wrapper"))
    script = _normalize_rule_script(template.get("script"))
    script_assets = _normalize_rule_script_assets(template.get("scriptAssets"), script=script)
    module = _normalize_rule_module(template.get("module"))
    module_assets = _normalize_rule_module_assets(template.get("moduleAssets"), module=module)
    actions = [bool(command), bool(wrapper), bool(script), bool(module)]
    if not any(actions):
        raise ToolRegistryError("TOOL_RULE_COMMAND_REQUIRED")
    if sum(actions) > 1:
        raise ToolRegistryError("TOOL_RULE_ACTION_CONFLICT")
    inputs = _normalize_rule_inputs(template.get("inputs"))
    outputs = _normalize_rule_outputs(template.get("outputs"))
    resource_parts = normalize_rule_resources(template.get("resources"))
    resources = resource_parts["workflowResources"]
    scheduler_resources = {
        **resource_parts["schedulerResources"],
        **normalize_scheduler_resources(template.get("schedulerResources") or template.get("runtimeResources")),
    }
    threads = normalize_rule_threads(template.get("threads"), fallback=resource_parts["threads"])
    log = _normalize_rule_log(template.get("log"))
    params_declared = "params" in template
    params = _normalize_rule_params(template.get("params")) if params_declared else {}
    environment = normalize_rule_environment(template.get("environment"))
    smoke_test = normalize_rule_smoke_test(
        template.get("smokeTest"),
        input_names={item["name"] for item in inputs},
        param_names=set(params),
        resource_names=set(resources),
    )
    if command:
        validate_command_tokens(
            command,
            input_names={item["name"] for item in inputs},
            output_names={item["name"] for item in outputs},
            param_names=set(params),
            threads_declared=threads is not None,
            scheduler_resource_names=set(scheduler_resources),
            log_names=_rule_log_names(log),
            has_log=bool(log),
        )
    normalized: dict[str, Any] = {"inputs": inputs, "outputs": outputs}
    if params_declared:
        normalized["params"] = dict(params)
    if command:
        normalized["commandTemplate"] = command
    if wrapper:
        normalized["wrapper"] = wrapper
    if script:
        normalized["script"] = script
        normalized["scriptAssets"] = script_assets
    if module:
        normalized["module"] = module
        normalized["moduleAssets"] = module_assets
    if threads is not None:
        normalized["threads"] = threads
    if scheduler_resources:
        normalized["schedulerResources"] = scheduler_resources
    if resources:
        normalized["resources"] = resources
    if log:
        normalized["log"] = log
    if environment:
        normalized["environment"] = environment
    if smoke_test:
        normalized["smokeTest"] = smoke_test
    return normalized


def _normalize_rule_wrapper(raw: Any) -> str:
    wrapper = str(raw or "").strip()
    if not wrapper:
        return ""
    if any(char.isspace() for char in wrapper):
        raise ToolRegistryError("TOOL_RULE_WRAPPER_INVALID")
    return wrapper


def _normalize_rule_script(raw: Any) -> str:
    script = str(raw or "").strip()
    if not script:
        return ""
    if any(char.isspace() for char in script) or "://" in script or script.startswith("~"):
        raise ToolRegistryError("TOOL_RULE_SCRIPT_INVALID")
    try:
        validate_relative_output_path(script)
    except ToolRegistryError as exc:
        raise ToolRegistryError("TOOL_RULE_SCRIPT_INVALID") from exc
    return script


def _normalize_rule_script_assets(raw: Any, *, script: str) -> list[dict[str, str]]:
    if raw in (None, []):
        if script:
            raise ToolRegistryError("TOOL_RULE_SCRIPT_ASSET_REQUIRED")
        return []
    if not script:
        raise ToolRegistryError("TOOL_RULE_SCRIPT_ASSET_UNSUPPORTED")
    if not isinstance(raw, list):
        raise ToolRegistryError("TOOL_RULE_SCRIPT_ASSETS_INVALID")
    assets: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            raise ToolRegistryError("TOOL_RULE_SCRIPT_ASSET_INVALID")
        path = _normalize_rule_script_asset_path(item.get("path"))
        content = item.get("content")
        if not isinstance(content, str):
            raise ToolRegistryError(f"TOOL_RULE_SCRIPT_ASSET_CONTENT_INVALID: {path}")
        if path in seen:
            raise ToolRegistryError(f"TOOL_RULE_SCRIPT_ASSET_DUPLICATE: {path}")
        seen.add(path)
        assets.append({"path": path, "content": content})
    if script not in seen:
        raise ToolRegistryError("TOOL_RULE_SCRIPT_ASSET_REQUIRED")
    return assets


def _normalize_rule_script_asset_path(raw: Any) -> str:
    path = _normalize_rule_script(raw)
    if not path:
        raise ToolRegistryError("TOOL_RULE_SCRIPT_ASSET_PATH_REQUIRED")
    return path


def _normalize_rule_module(raw: Any) -> dict[str, str]:
    if raw in (None, "", {}):
        return {}
    if not isinstance(raw, dict):
        raise ToolRegistryError("TOOL_RULE_MODULE_INVALID")
    snakefile = str(raw.get("snakefile") or "").strip()
    rule = str(raw.get("rule") or raw.get("useRule") or "").strip()
    if not snakefile:
        raise ToolRegistryError("TOOL_RULE_MODULE_SNAKEFILE_REQUIRED")
    if not rule:
        raise ToolRegistryError("TOOL_RULE_MODULE_RULE_REQUIRED")
    validate_relative_module_path(snakefile)
    if not RULE_IO_NAME_RE.match(rule):
        raise ToolRegistryError(f"TOOL_RULE_MODULE_RULE_INVALID: {rule}")
    name = str(raw.get("name") or "").strip()
    if name and not RULE_IO_NAME_RE.match(name):
        raise ToolRegistryError(f"TOOL_RULE_MODULE_NAME_INVALID: {name}")
    normalized = {"snakefile": snakefile, "rule": rule}
    if name:
        normalized["name"] = name
    return normalized


def _normalize_rule_module_assets(raw: Any, *, module: dict[str, str]) -> list[dict[str, str]]:
    if raw in (None, []):
        if module:
            raise ToolRegistryError("TOOL_RULE_MODULE_ASSET_REQUIRED")
        return []
    if not module:
        raise ToolRegistryError("TOOL_RULE_MODULE_ASSET_UNSUPPORTED")
    if not isinstance(raw, list):
        raise ToolRegistryError("TOOL_RULE_MODULE_ASSETS_INVALID")
    assets: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            raise ToolRegistryError("TOOL_RULE_MODULE_ASSET_INVALID")
        path = _normalize_rule_module_asset_path(item.get("path"))
        content = item.get("content")
        if not isinstance(content, str):
            raise ToolRegistryError(f"TOOL_RULE_MODULE_ASSET_CONTENT_INVALID: {path}")
        if path in seen:
            raise ToolRegistryError(f"TOOL_RULE_MODULE_ASSET_DUPLICATE: {path}")
        seen.add(path)
        assets.append({"path": path, "content": content})
    if module["snakefile"] not in seen:
        raise ToolRegistryError("TOOL_RULE_MODULE_ASSET_REQUIRED")
    return assets


def _normalize_rule_module_asset_path(raw: Any) -> str:
    path = str(raw or "").strip().replace("\\", "/")
    if not path:
        raise ToolRegistryError("TOOL_RULE_MODULE_ASSET_PATH_REQUIRED")
    validate_relative_module_path(path)
    return path


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
        name = normalize_io_name(item.get("name"))
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
        name = normalize_io_name(item.get("name"))
        if name in seen:
            raise ToolRegistryError(f"TOOL_RULE_IO_NAME_DUPLICATE: {name}")
        seen.add(name)
        path = str(item.get("path") or "").strip()
        kind = str(item.get("kind") or "").strip()
        mime_type = str(item.get("mimeType") or "").strip()
        if not path:
            raise ToolRegistryError("TOOL_RULE_OUTPUT_SPEC_INVALID")
        validate_relative_output_path(path)
        temp = _normalize_rule_output_flag(item, name=name, field="temp")
        protected = _normalize_rule_output_flag(item, name=name, field="protected")
        directory = _normalize_rule_output_flag(item, name=name, field="directory")
        if temp and protected:
            raise ToolRegistryError(f"TOOL_RULE_OUTPUT_FLAGS_INVALID: {name}")
        normalized = {**item, "name": name, "path": path}
        if kind:
            normalized["kind"] = kind
        elif "kind" in normalized:
            del normalized["kind"]
        if mime_type:
            normalized["mimeType"] = mime_type
        elif "mimeType" in normalized:
            del normalized["mimeType"]
        for flag_name, enabled in [("temp", temp), ("protected", protected), ("directory", directory)]:
            if enabled:
                normalized[flag_name] = True
            elif flag_name in normalized:
                del normalized[flag_name]
        outputs.append(normalized)
    return outputs


def _normalize_rule_output_flag(item: dict[str, Any], *, name: str, field: str) -> bool:
    value = item.get(field, False)
    if not isinstance(value, bool):
        raise ToolRegistryError(f"TOOL_RULE_OUTPUT_FLAG_INVALID: {name}.{field}")
    return value


def _normalize_rule_log(raw: Any) -> str | dict[str, str]:
    if raw in (None, "", {}):
        return ""
    if isinstance(raw, str):
        value = raw.strip()
        validate_relative_log_path(value)
        return value
    if not isinstance(raw, dict):
        raise ToolRegistryError("TOOL_RULE_LOG_INVALID")
    logs: dict[str, str] = {}
    for key, value in raw.items():
        name = normalize_io_name(key)
        path = str(value or "").strip()
        if not path:
            raise ToolRegistryError(f"TOOL_RULE_LOG_PATH_REQUIRED: {name}")
        validate_relative_log_path(path)
        logs[name] = path
    return logs


def _rule_log_names(log: str | dict[str, str]) -> set[str]:
    return set(log) if isinstance(log, dict) else set()


def _normalize_rule_params(raw: Any) -> dict[str, Any]:
    if raw in (None, {}):
        return {}
    if not isinstance(raw, dict):
        raise ToolRegistryError("TOOL_RULE_PARAMS_INVALID")
    params: dict[str, Any] = {}
    for key, value in raw.items():
        name = normalize_io_name(key)
        params[name] = value
    return params
