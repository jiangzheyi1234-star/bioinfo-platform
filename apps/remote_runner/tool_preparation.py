from __future__ import annotations

from typing import Any, Callable

from .config import RemoteRunnerConfig
from .tool_contract import build_tool_contract, default_contract_status, normalize_contract_status
from .tool_contract_validation import run_tool_contract_validation
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
