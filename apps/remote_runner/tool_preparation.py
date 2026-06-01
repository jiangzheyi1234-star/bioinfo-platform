from __future__ import annotations

from typing import Any, Callable

from .config import RemoteRunnerConfig
from .storage import upsert_tool
from .tool_contract import build_tool_contract, default_contract_status, normalize_contract_status
from .tool_contract_validation import run_tool_contract_validation
from .tool_revisions import publish_tool_revision
from .tools import (
    ToolRegistryError,
    _normalize_tool_manifest,
    normalize_rule_template,
    normalize_tool_capabilities,
)


PrepareEventCallback = Callable[[dict[str, Any]], None]


def prepare_registered_tool(cfg: RemoteRunnerConfig, payload: dict[str, Any]) -> dict[str, Any]:
    item = validate_registered_tool_for_publish(cfg, payload)
    published = publish_tool_revision(cfg, item)
    published["status"] = "published"
    published["message"] = str(item.get("message") or "Tool revision published.")
    return upsert_tool(cfg, published)


def validate_registered_tool_for_publish(
    cfg: RemoteRunnerConfig,
    payload: dict[str, Any],
    event_callback: PrepareEventCallback | None = None,
) -> dict[str, Any]:
    item = _normalized_executable_tool(payload)
    contract = build_tool_contract(item)
    if not bool(contract["requirements"]["snakemakeRenderable"]):
        raise ToolRegistryError(str((contract.get("reasons") or ["TOOL_CONTRACT_INCOMPLETE"])[0]))

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
