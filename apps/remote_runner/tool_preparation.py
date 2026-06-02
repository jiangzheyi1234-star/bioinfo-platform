from __future__ import annotations

from typing import Any, Callable

from .config import RemoteRunnerConfig
from .tool_contract import build_tool_contract, default_contract_status, normalize_contract_status
from .tool_contract_validation import WAITING_RESOURCE_CODES, run_tool_contract_validation
from .tools_errors import ToolPrepareWaitingResourceError
from .tools import (
    ToolRegistryError,
    _normalize_tool_manifest,
    _rule_spec_draft_requires_completion,
    normalize_rule_template,
    normalize_tool_capabilities,
)


PrepareEventCallback = Callable[[dict[str, Any]], None]


def validate_registered_tool_for_publish(
    cfg: RemoteRunnerConfig,
    payload: dict[str, Any],
    event_callback: PrepareEventCallback | None = None,
) -> dict[str, Any]:
    try:
        item = _normalized_executable_tool(payload)
    except ToolRegistryError as exc:
        _emit_prepare_event(
            event_callback,
            "profile_schema_validation",
            str(exc),
            level="error",
            details={"code": str(exc)},
        )
        raise
    _emit_prepare_event(
        event_callback,
        "profile_schema_validation",
        "Profile schema validation passed.",
        level="success",
    )

    contract = build_tool_contract(item)
    if not bool(contract["requirements"]["snakemakeRenderable"]):
        code = str((contract.get("reasons") or ["TOOL_CONTRACT_INCOMPLETE"])[0])
        _emit_prepare_event(
            event_callback,
            "static_rulespec_validation",
            code,
            level="error",
            details={"code": code},
        )
        raise ToolRegistryError(code)
    _emit_prepare_event(
        event_callback,
        "static_rulespec_validation",
        "Static RuleSpec validation passed.",
        level="success",
    )
    _emit_prepare_event(event_callback, "environment_resolution", "Resolving tool execution environment.")

    result = (
        run_tool_contract_validation(cfg, item, event_callback=event_callback)
        if event_callback is not None
        else run_tool_contract_validation(cfg, item)
    )
    item["contractStatus"] = result["contractStatus"]
    item["status"] = "declared" if result["ok"] else "failed"
    item["message"] = str(result["message"] or "")
    contract = build_tool_contract(item)
    if not bool(result["ok"]) or not bool(contract.get("workflowReady")):
        waiting_resource = _waiting_resource_error(item)
        if waiting_resource is not None:
            raise waiting_resource
        raise ToolRegistryError(_validation_failure_code(item))
    return item


def _normalized_executable_tool(payload: dict[str, Any]) -> dict[str, Any]:
    item = _normalize_tool_manifest(payload)
    item["ruleTemplate"] = normalize_rule_template(item.get("ruleTemplate"), required=True)
    if _rule_spec_draft_requires_completion(item.get("ruleSpecDraft")):
        raise ToolRegistryError("TOOL_RULE_SPEC_REQUIRES_USER_COMPLETION")
    item["capabilities"] = normalize_tool_capabilities(item.get("capabilities"))
    item["contractStatus"] = default_contract_status()
    return item


def _validation_failure_code(item: dict[str, Any]) -> str:
    status = normalize_contract_status(item.get("contractStatus"))
    for key in ("dryRun", "smokeRun", "outputValidation"):
        value = status.get(key, {})
        if value.get("status") == "failed":
            return str(value.get("code") or value.get("message") or "TOOL_CONTRACT_VALIDATION_FAILED")
    return str(item.get("message") or "TOOL_CONTRACT_VALIDATION_FAILED")


def _waiting_resource_error(item: dict[str, Any]) -> ToolPrepareWaitingResourceError | None:
    status = normalize_contract_status(item.get("contractStatus"))
    dry_run = status.get("dryRun", {})
    code = str(dry_run.get("code") or "").strip()
    if code not in WAITING_RESOURCE_CODES:
        return None
    resource_key = str(dry_run.get("resourceKey") or "").strip() or _resource_key_from_message(str(dry_run.get("message") or ""))
    return ToolPrepareWaitingResourceError(
        code=code,
        message=str(dry_run.get("message") or code),
        details=_waiting_resource_details(item, resource_key),
    )


def _resource_key_from_message(message: str) -> str:
    _prefix, separator, remainder = str(message or "").rpartition(":")
    return remainder.strip() if separator else ""


def _waiting_resource_details(item: dict[str, Any], resource_key: str) -> dict[str, Any]:
    template = item.get("ruleTemplate") if isinstance(item.get("ruleTemplate"), dict) else {}
    resources = template.get("resources") if isinstance(template.get("resources"), dict) else {}
    spec = resources.get(resource_key) if isinstance(resources.get(resource_key), dict) else {}
    details: dict[str, Any] = {"resourceType": "database"}
    if resource_key:
        details["resourceKey"] = resource_key
    config_key = str(spec.get("configKey") or resource_key or "").strip()
    if config_key:
        details["configKey"] = config_key
    accepted_templates = [str(value).strip() for value in spec.get("acceptedTemplates") or [] if str(value).strip()]
    if accepted_templates:
        details["acceptedTemplates"] = accepted_templates
    accepted_capabilities = [str(value).strip() for value in spec.get("acceptedCapabilities") or [] if str(value).strip()]
    if accepted_capabilities:
        details["acceptedCapabilities"] = accepted_capabilities
    return details


def _emit_prepare_event(
    callback: PrepareEventCallback | None,
    stage: str,
    message: str,
    *,
    level: str = "info",
    details: dict[str, Any] | None = None,
) -> None:
    if callback is None:
        return
    callback(
        {
            "stage": stage,
            "message": message,
            "level": level,
            "details": details or {},
        }
    )
