from __future__ import annotations

import base64
import binascii
from typing import Any

from .tools_errors import ToolRegistryError


def normalize_rule_smoke_test(
    raw: Any,
    *,
    input_names: set[str],
    param_names: set[str],
    resource_names: set[str],
) -> dict[str, Any]:
    if raw in (None, {}):
        return {}
    if not isinstance(raw, dict):
        raise ToolRegistryError("TOOL_RULE_SMOKE_TEST_INVALID")
    inputs = _normalize_smoke_inputs(raw.get("inputs"), input_names=input_names)
    params = _normalize_smoke_params(raw.get("params"), param_names=param_names)
    resource_bindings = _normalize_smoke_resource_bindings(raw.get("resourceBindings"), resource_names=resource_names)
    normalized: dict[str, Any] = {}
    if inputs:
        normalized["inputs"] = inputs
    if params:
        normalized["params"] = params
    if resource_bindings:
        normalized["resourceBindings"] = resource_bindings
    timeout = raw.get("timeoutSeconds")
    if timeout not in (None, ""):
        try:
            timeout_seconds = int(timeout)
        except (TypeError, ValueError) as exc:
            raise ToolRegistryError("TOOL_RULE_SMOKE_TIMEOUT_INVALID") from exc
        if timeout_seconds < 1 or timeout_seconds > 3600:
            raise ToolRegistryError("TOOL_RULE_SMOKE_TIMEOUT_INVALID")
        normalized["timeoutSeconds"] = timeout_seconds
    return normalized


def _normalize_smoke_inputs(raw: Any, *, input_names: set[str]) -> dict[str, dict[str, Any]]:
    if raw in (None, {}):
        return {}
    if not isinstance(raw, dict):
        raise ToolRegistryError("TOOL_RULE_SMOKE_INPUTS_INVALID")
    inputs: dict[str, dict[str, Any]] = {}
    for raw_name, raw_item in raw.items():
        name = str(raw_name or "").strip()
        if name not in input_names:
            raise ToolRegistryError(f"TOOL_RULE_SMOKE_INPUT_UNKNOWN: {name}")
        if not isinstance(raw_item, dict):
            raise ToolRegistryError(f"TOOL_RULE_SMOKE_INPUT_INVALID: {name}")
        content = raw_item.get("content")
        content_base64 = raw_item.get("contentBase64")
        if content is None and content_base64 is None:
            raise ToolRegistryError(f"TOOL_RULE_SMOKE_INPUT_CONTENT_REQUIRED: {name}")
        if content is not None and not isinstance(content, str):
            raise ToolRegistryError(f"TOOL_RULE_SMOKE_INPUT_CONTENT_INVALID: {name}")
        if content_base64 is not None:
            encoded = str(content_base64 or "").strip()
            try:
                base64.b64decode(encoded.encode("utf-8"), validate=True)
            except (ValueError, binascii.Error) as exc:
                raise ToolRegistryError(f"TOOL_RULE_SMOKE_INPUT_BASE64_INVALID: {name}") from exc
        filename = str(raw_item.get("filename") or f"{name}.txt").strip()
        if not filename or "/" in filename or "\\" in filename or filename in {".", ".."}:
            raise ToolRegistryError(f"TOOL_RULE_SMOKE_INPUT_FILENAME_INVALID: {name}")
        inputs[name] = {
            "filename": filename,
            "mimeType": str(raw_item.get("mimeType") or "text/plain"),
            **({"content": content} if content is not None else {}),
            **({"contentBase64": str(content_base64)} if content_base64 is not None else {}),
        }
    return inputs


def _normalize_smoke_params(raw: Any, *, param_names: set[str]) -> dict[str, str | int | float | bool]:
    if raw in (None, {}):
        return {}
    if not isinstance(raw, dict):
        raise ToolRegistryError("TOOL_RULE_SMOKE_PARAMS_INVALID")
    params: dict[str, str | int | float | bool] = {}
    for raw_name, value in raw.items():
        name = str(raw_name or "").strip()
        if name not in param_names:
            raise ToolRegistryError(f"TOOL_RULE_SMOKE_PARAM_UNKNOWN: {name}")
        if isinstance(value, (str, int, float, bool)):
            params[name] = value
            continue
        raise ToolRegistryError(f"TOOL_RULE_SMOKE_PARAM_INVALID: {name}")
    return params


def _normalize_smoke_resource_bindings(raw: Any, *, resource_names: set[str]) -> dict[str, str | dict[str, str]]:
    if raw in (None, {}):
        return {}
    if not isinstance(raw, dict):
        raise ToolRegistryError("TOOL_RULE_SMOKE_RESOURCE_BINDINGS_INVALID")
    bindings: dict[str, str | dict[str, str]] = {}
    for raw_name, raw_value in raw.items():
        name = str(raw_name or "").strip()
        if name not in resource_names:
            raise ToolRegistryError(f"TOOL_RULE_SMOKE_RESOURCE_UNKNOWN: {name}")
        if isinstance(raw_value, str):
            database_id = raw_value.strip()
            if not database_id:
                raise ToolRegistryError(f"TOOL_RULE_SMOKE_RESOURCE_DATABASE_REQUIRED: {name}")
            bindings[name] = database_id
            continue
        if isinstance(raw_value, dict):
            database_id = str(raw_value.get("databaseId") or raw_value.get("id") or "").strip()
            if not database_id:
                raise ToolRegistryError(f"TOOL_RULE_SMOKE_RESOURCE_DATABASE_REQUIRED: {name}")
            bindings[name] = {"databaseId": database_id}
            continue
        raise ToolRegistryError(f"TOOL_RULE_SMOKE_RESOURCE_BINDING_INVALID: {name}")
    return bindings
