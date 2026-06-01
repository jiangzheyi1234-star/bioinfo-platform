from __future__ import annotations

import re
from pathlib import Path, PurePosixPath
from typing import Any

from .config import RemoteRunnerConfig
from .production_evidence import normalize_production_evidence_type, validate_production_evidence_run
from .rule_smoke import normalize_rule_smoke_test
from .storage import delete_tool, fetch_tool, list_tools, now_iso, upsert_tool
from .tool_contract import build_tool_contract, default_contract_status, normalize_contract_status
from .tool_package_identity import normalize_package_identity
from .tools_errors import ToolRegistryError


ALLOWED_SOURCES = {"bioconda", "conda-forge"}
RULE_IO_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
CAPABILITY_ID_RE = re.compile(r"^[A-Za-z0-9_.:-]+$")
EDAM_ID_RE = re.compile(r"^EDAM:[A-Za-z_]+_[0-9]{4,}$")
RULE_TOKEN_RE = re.compile(r"\{[^{}\s]+\}")
DATABASE_TOKEN_RE = re.compile(
    r"^database\.[A-Za-z_][A-Za-z0-9_]*\.(id|name|type|templateId|version|path|manifestPath|checksum)(:q)?$"
)
CONFIG_TOKEN_RE = re.compile(r"^config\.[A-Za-z_][A-Za-z0-9_]*(:q)?$")
SCHEDULER_RESOURCE_KEYS = {"mem_mb", "disk_mb", "runtime", "tmpdir"}


def list_registered_tools(cfg: RemoteRunnerConfig) -> list[dict[str, Any]]:
    return list_tools(cfg)


def add_registered_tool(cfg: RemoteRunnerConfig, payload: dict[str, Any]) -> dict[str, Any]:
    item = _normalize_tool_manifest(payload)
    item["ruleTemplate"] = normalize_rule_template(item.get("ruleTemplate"), required=False)
    item["capabilities"] = normalize_tool_capabilities(item.get("capabilities"))
    item["contractStatus"] = default_contract_status()
    return upsert_tool(cfg, item)


def update_registered_tool_rule_template(
    cfg: RemoteRunnerConfig,
    tool_id: str,
    rule_template: dict[str, Any] | None,
) -> dict[str, Any]:
    normalized = str(tool_id or "").strip()
    if not normalized:
        raise ToolRegistryError("TOOL_ID_REQUIRED")
    item = fetch_tool(cfg, normalized)
    if item is None:
        raise ToolRegistryError("TOOL_NOT_FOUND")
    item["ruleTemplate"] = normalize_rule_template(rule_template, required=True)
    item["ruleSpecDraft"] = {}
    item["contractStatus"] = default_contract_status()
    item["status"] = "declared"
    item["message"] = "RuleSpec saved."
    item["toolRevisionId"] = ""
    item["revision"] = 0
    item["publishedAt"] = None
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
        message = f"{item.get('targetPlatform') or 'linux-64'} is not supported by this package."
        item["contractStatus"] = _contract_failure_status("dryRun", "TOOL_PLATFORM_UNSUPPORTED", message)
        item["status"] = "failed"
        item["message"] = message
        return upsert_tool(cfg, item)

    try:
        item["ruleTemplate"] = normalize_rule_template(item.get("ruleTemplate"), required=True)
    except ToolRegistryError as exc:
        item["contractStatus"] = _contract_failure_status("dryRun", str(exc), str(exc))
        item["status"] = "failed"
        item["message"] = str(exc)
        return upsert_tool(cfg, item)

    contract = build_tool_contract(item)
    if not bool(contract["requirements"]["snakemakeRenderable"]):
        code = str((contract.get("reasons") or ["TOOL_CONTRACT_INCOMPLETE"])[0])
        item["contractStatus"] = _contract_failure_status("dryRun", code, code)
        item["status"] = "failed"
        item["message"] = code
        return upsert_tool(cfg, item)

    from .tool_contract_validation import run_tool_contract_validation

    result = run_tool_contract_validation(cfg, item)
    item["contractStatus"] = result["contractStatus"]
    item["status"] = "declared" if result["ok"] else "failed"
    item["message"] = str(result["message"] or "")
    return upsert_tool(cfg, item)


def mark_registered_tool_production_enabled(
    cfg: RemoteRunnerConfig,
    tool_id: str,
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized = str(tool_id or "").strip()
    if not normalized:
        raise ToolRegistryError("TOOL_ID_REQUIRED")
    item = fetch_tool(cfg, normalized)
    if item is None:
        raise ToolRegistryError("TOOL_NOT_FOUND")

    status = normalize_contract_status(item.get("contractStatus"))
    item["contractStatus"] = status
    contract = build_tool_contract(item)
    output_status = str(status.get("outputValidation", {}).get("status") or "")
    if not bool((contract.get("requirements") or {}).get("outputValidated")) and output_status != "passed":
        raise ToolRegistryError("TOOL_PRODUCTION_REQUIRES_OUTPUT_VALIDATION")
    if not bool(contract.get("workflowReady")):
        raise ToolRegistryError("TOOL_PRODUCTION_REQUIRES_WORKFLOW_READY")

    accepted = dict(evidence or {})
    run_id = str(accepted.get("runId") or "").strip()
    if not run_id:
        raise ToolRegistryError("TOOL_PRODUCTION_EVIDENCE_RUN_ID_REQUIRED")
    message = str(accepted.get("message") or "").strip()
    if not message:
        raise ToolRegistryError("TOOL_PRODUCTION_EVIDENCE_MESSAGE_REQUIRED")
    evidence_type = normalize_production_evidence_type(accepted.get("evidenceType"))
    accepted["evidenceType"] = evidence_type
    artifact_summary = validate_production_evidence_run(cfg, accepted, tool_id=normalized)
    production = {
        "status": "passed",
        "code": "PRODUCTION_ACCEPTED",
        "message": message,
        "checkedAt": now_iso(),
        "runId": run_id,
    }
    for key in (
        "logPath",
        "evidenceType",
        "databaseId",
        "templateId",
        "role",
        "artifactName",
    ):
        value = str(accepted.get(key) or "").strip()
        if value:
            production[key] = value
    production.update(artifact_summary)
    status["production"] = production
    item["contractStatus"] = status
    item["status"] = "declared"
    item["message"] = message
    return upsert_tool(cfg, item)


def _contract_failure_status(key: str, code: str, message: str) -> dict[str, dict[str, str]]:
    return {
        **default_contract_status(),
        key: {
            "status": "failed",
            "code": code,
            "message": message,
            "checkedAt": now_iso(),
        },
    }


def _normalize_tool_manifest(payload: dict[str, Any]) -> dict[str, Any]:
    source = str(payload.get("source") or "").strip()
    name = str(payload.get("name") or "").strip()
    if source not in ALLOWED_SOURCES:
        raise ToolRegistryError("TOOL_SOURCE_UNSUPPORTED")
    if not name:
        raise ToolRegistryError("TOOL_NAME_REQUIRED")

    package_identity = normalize_package_identity(
        source=source,
        name=name,
        version=str(payload.get("version") or ""),
        package_spec=str(payload.get("packageSpec") or ""),
    )

    tool_id = str(payload.get("id") or f"{source}::{name}").strip()
    return {
        "id": tool_id,
        "name": name,
        "source": source,
        "sourceLabel": str(payload.get("sourceLabel") or source),
        "version": package_identity["version"],
        "packageSpec": package_identity["packageSpec"],
        "summary": str(payload.get("summary") or ""),
        "targetPlatform": str(payload.get("targetPlatform") or "linux-64"),
        "targetPlatformSupported": bool(payload.get("targetPlatformSupported")),
        "platforms": [str(item) for item in (payload.get("platforms") or []) if str(item).strip()],
        "sourceUrl": str(payload.get("sourceUrl") or ""),
        "testCommand": str(payload.get("testCommand") or ""),
        "ruleTemplate": payload.get("ruleTemplate") or {},
        "ruleSpecDraft": payload.get("ruleSpecDraft") or {},
        "capabilities": payload.get("capabilities") or [],
        "snakemakeWrappers": list(payload.get("snakemakeWrappers") or []),
        "status": str(payload.get("status") or "declared"),
        "message": str(payload.get("message") or "Tool declared."),
    }


def normalize_tool_capabilities(raw: Any) -> list[dict[str, Any]]:
    if raw in (None, []):
        return []
    if not isinstance(raw, list):
        raise ToolRegistryError("TOOL_CAPABILITIES_INVALID")
    capabilities: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            raise ToolRegistryError("TOOL_CAPABILITY_INVALID")
        capability_id = str(item.get("id") or item.get("capabilityId") or "").strip()
        if not capability_id or not CAPABILITY_ID_RE.match(capability_id):
            raise ToolRegistryError("TOOL_CAPABILITY_ID_INVALID")
        if capability_id in seen:
            raise ToolRegistryError(f"TOOL_CAPABILITY_DUPLICATE: {capability_id}")
        seen.add(capability_id)
        normalized = {
            **item,
            "id": capability_id,
            "label": str(item.get("label") or item.get("name") or capability_id),
            "operation": _normalize_edam_ref(item.get("operation"), field="operation"),
            "topics": _normalize_edam_refs(item.get("topics"), field="topics"),
            "inputs": _normalize_capability_slots(item.get("inputs"), direction="input"),
            "outputs": _normalize_capability_slots(item.get("outputs"), direction="output"),
        }
        if "capabilityId" in normalized:
            del normalized["capabilityId"]
        capabilities.append(normalized)
    return capabilities


def _normalize_capability_slots(raw: Any, *, direction: str) -> list[dict[str, Any]]:
    if raw in (None, []):
        return []
    if not isinstance(raw, list):
        raise ToolRegistryError(f"TOOL_CAPABILITY_{direction.upper()}S_INVALID")
    slots: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            raise ToolRegistryError(f"TOOL_CAPABILITY_{direction.upper()}_INVALID")
        name = _normalize_io_name(item.get("name") or item.get("slot"))
        if name in seen:
            raise ToolRegistryError(f"TOOL_CAPABILITY_SLOT_DUPLICATE: {name}")
        seen.add(name)
        slots.append(
            {
                **item,
                "name": name,
                "data": _normalize_edam_ref(item.get("data"), field="data"),
                "format": _normalize_edam_ref(item.get("format"), field="format"),
                "required": bool(item.get("required", True)),
                "primary": bool(item.get("primary", len(slots) == 0)),
            }
        )
    return slots


def _normalize_edam_refs(raw: Any, *, field: str) -> list[str]:
    if raw in (None, []):
        return []
    if not isinstance(raw, list):
        raise ToolRegistryError(f"TOOL_CAPABILITY_EDAM_{field.upper()}_INVALID")
    return [_normalize_edam_ref(item, field=field) for item in raw]


def _normalize_edam_ref(raw: Any, *, field: str) -> str:
    value = str(raw or "").strip()
    if not value:
        return ""
    if not EDAM_ID_RE.match(value):
        raise ToolRegistryError(f"TOOL_CAPABILITY_EDAM_{field.upper()}_INVALID: {value}")
    return value


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
    resource_parts = _normalize_rule_resources(template.get("resources"))
    resources = resource_parts["workflowResources"]
    scheduler_resources = {
        **resource_parts["schedulerResources"],
        **_normalize_scheduler_resources(template.get("schedulerResources") or template.get("runtimeResources")),
    }
    threads = _normalize_rule_threads(template.get("threads"), fallback=resource_parts["threads"])
    log = _normalize_rule_log(template.get("log"))
    params_declared = "params" in template
    params = _normalize_rule_params(template.get("params")) if params_declared else {}
    environment = _normalize_rule_environment(template.get("environment"))
    smoke_test = normalize_rule_smoke_test(
        template.get("smokeTest"),
        input_names={item["name"] for item in inputs},
        param_names=set(params),
        resource_names=set(resources),
    )
    if command:
        _validate_command_tokens(
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
        _validate_relative_output_path(script)
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
    _validate_relative_module_path(snakefile)
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
    _validate_relative_module_path(path)
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
        if not path:
            raise ToolRegistryError("TOOL_RULE_OUTPUT_SPEC_INVALID")
        _validate_relative_output_path(path)
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


def _normalize_rule_resources(raw: Any) -> dict[str, Any]:
    if raw in (None, {}):
        return {"workflowResources": {}, "schedulerResources": {}, "threads": None}
    if not isinstance(raw, dict):
        raise ToolRegistryError("WORKFLOW_RESOURCE_SPEC_INVALID")
    workflow_resources: dict[str, dict[str, Any]] = {}
    scheduler_resources: dict[str, str | int | float] = {}
    threads: int | None = None
    for key, value in raw.items():
        resource_key = str(key or "").strip()
        if not resource_key or not RULE_IO_NAME_RE.match(resource_key):
            raise ToolRegistryError("WORKFLOW_RESOURCE_KEY_REQUIRED")
        if resource_key == "threads":
            threads = _normalize_rule_threads(value)
            continue
        if _is_scheduler_resource(resource_key, value):
            scheduler_resources[resource_key] = _normalize_scheduler_resource_value(resource_key, value)
            continue
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
        workflow_resources[resource_key] = {**value, "configKey": config_key}
    return {"workflowResources": workflow_resources, "schedulerResources": scheduler_resources, "threads": threads}


def _normalize_rule_threads(raw: Any, *, fallback: int | None = None) -> int | None:
    if raw in (None, ""):
        return fallback
    value = _rule_default_value(raw)
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ToolRegistryError("TOOL_RULE_THREADS_INVALID")
    return value


def _normalize_scheduler_resources(raw: Any) -> dict[str, str | int | float]:
    if raw in (None, {}):
        return {}
    if not isinstance(raw, dict):
        raise ToolRegistryError("TOOL_RULE_SCHEDULER_RESOURCES_INVALID")
    resources: dict[str, str | int | float] = {}
    for key, value in raw.items():
        resource_key = str(key or "").strip()
        if not resource_key or not RULE_IO_NAME_RE.match(resource_key):
            raise ToolRegistryError("TOOL_RULE_SCHEDULER_RESOURCE_KEY_REQUIRED")
        resources[resource_key] = _normalize_scheduler_resource_value(resource_key, value)
    return resources


def _is_scheduler_resource(key: str, value: Any) -> bool:
    if key in SCHEDULER_RESOURCE_KEYS:
        return True
    if not isinstance(value, dict):
        return False
    resource_type = str(value.get("type") or "").strip()
    if resource_type in {"compute", "scheduler"}:
        return True
    has_database_markers = any(marker in value for marker in ["acceptedTemplates", "acceptedCapabilities", "configKey"])
    return "default" in value and not has_database_markers


def _normalize_scheduler_resource_value(key: str, raw: Any) -> str | int | float:
    value = _rule_default_value(raw)
    if isinstance(value, bool) or not isinstance(value, (str, int, float)) or value == "":
        raise ToolRegistryError(f"TOOL_RULE_SCHEDULER_RESOURCE_VALUE_INVALID: {key}")
    return value


def _rule_default_value(raw: Any) -> Any:
    if isinstance(raw, dict):
        if "default" in raw:
            return raw["default"]
        if "value" in raw:
            return raw["value"]
        raise ToolRegistryError("TOOL_RULE_RUNTIME_DEFAULT_REQUIRED")
    return raw


def _normalize_rule_log(raw: Any) -> str | dict[str, str]:
    if raw in (None, "", {}):
        return ""
    if isinstance(raw, str):
        value = raw.strip()
        _validate_relative_log_path(value)
        return value
    if not isinstance(raw, dict):
        raise ToolRegistryError("TOOL_RULE_LOG_INVALID")
    logs: dict[str, str] = {}
    for key, value in raw.items():
        name = _normalize_io_name(key)
        path = str(value or "").strip()
        if not path:
            raise ToolRegistryError(f"TOOL_RULE_LOG_PATH_REQUIRED: {name}")
        _validate_relative_log_path(path)
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
        name = _normalize_io_name(key)
        params[name] = value
    return params


def _normalize_rule_environment(raw: Any) -> dict[str, Any]:
    if raw in (None, {}):
        return {}
    if not isinstance(raw, dict):
        raise ToolRegistryError("TOOL_RULE_ENVIRONMENT_INVALID")
    conda = raw.get("conda")
    if conda in (None, {}):
        return {}
    if not isinstance(conda, dict):
        raise ToolRegistryError("TOOL_RULE_ENVIRONMENT_CONDA_INVALID")
    channels = _normalize_string_list(conda.get("channels"), error_code="TOOL_RULE_ENVIRONMENT_CHANNELS_INVALID")
    dependencies = _normalize_string_list(
        conda.get("dependencies"),
        error_code="TOOL_RULE_ENVIRONMENT_DEPENDENCIES_INVALID",
    )
    normalized_conda: dict[str, Any] = {}
    if channels:
        normalized_conda["channels"] = channels
    if dependencies:
        normalized_conda["dependencies"] = dependencies
    return {"conda": normalized_conda} if normalized_conda else {}


def _normalize_string_list(raw: Any, *, error_code: str) -> list[str]:
    if raw in (None, []):
        return []
    if not isinstance(raw, list):
        raise ToolRegistryError(error_code)
    values: list[str] = []
    seen: set[str] = set()
    for item in raw:
        value = str(item or "").strip()
        if not value:
            raise ToolRegistryError(error_code)
        if value not in seen:
            values.append(value)
            seen.add(value)
    return values


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


def _validate_relative_log_path(path: str) -> None:
    try:
        _validate_relative_output_path(path)
    except ToolRegistryError as exc:
        raise ToolRegistryError("TOOL_RULE_LOG_PATH_INVALID") from exc


def _validate_relative_module_path(path: str) -> None:
    try:
        _validate_relative_output_path(path)
    except ToolRegistryError as exc:
        raise ToolRegistryError("TOOL_RULE_MODULE_PATH_INVALID") from exc


def _validate_command_tokens(
    command: str,
    *,
    input_names: set[str],
    output_names: set[str],
    param_names: set[str],
    threads_declared: bool,
    scheduler_resource_names: set[str],
    log_names: set[str],
    has_log: bool,
) -> None:
    if "{resource." in command:
        raise ToolRegistryError("TOOL_RULE_RESOURCE_TOKEN_UNSUPPORTED")
    for match in RULE_TOKEN_RE.finditer(command):
        token = match.group(0)
        body = token[1:-1]
        if body in {"input", "input:q", "output", "output:q", "output_dir", "output_dir:q"}:
            continue
        if body in {"threads", "threads:q"} and threads_declared:
            continue
        if body in {"log", "log:q"} and has_log:
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
        if body.startswith("params."):
            name = body.removeprefix("params.").removesuffix(":q")
            if name in param_names:
                continue
            raise ToolRegistryError(f"TOOL_RULE_TOKEN_UNSUPPORTED: {token}")
        if body.startswith("resources."):
            name = body.removeprefix("resources.").removesuffix(":q")
            if name in scheduler_resource_names:
                continue
            raise ToolRegistryError(f"TOOL_RULE_TOKEN_UNSUPPORTED: {token}")
        if body.startswith("log."):
            name = body.removeprefix("log.").removesuffix(":q")
            if name in log_names:
                continue
            raise ToolRegistryError(f"TOOL_RULE_TOKEN_UNSUPPORTED: {token}")
        if DATABASE_TOKEN_RE.match(body) or CONFIG_TOKEN_RE.match(body):
            continue
        raise ToolRegistryError(f"TOOL_RULE_TOKEN_UNSUPPORTED: {token}")
