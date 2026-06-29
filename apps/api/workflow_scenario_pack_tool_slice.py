"""Scenario-level curated tool slice handoff contract."""

from __future__ import annotations

from typing import Any

from apps.api.workflow_scenario_pack_targets import SCENARIO_PRODUCT_TARGETS


SCENARIO_TOOL_SLICE_HANDOFF_SCHEMA_VERSION = "h2ometa.workflow-scenario-tool-slice-handoff.v1"
SCENARIO_TOOL_SLICE_MIN = 3
SCENARIO_TOOL_SLICE_MAX = 5
SCENARIO_TOOL_SLICE_EXCLUDED_ACTIONS = [
    "generic-bioconda-import",
    "request-side-rulespec",
    "unvalidated-tool-selection",
]


class WorkflowScenarioToolSliceHandoffError(ValueError):
    pass


def tool_slice_handoff(definition: dict[str, Any]) -> dict[str, Any]:
    ready = _gate_passed(definition, "SCENARIO_TOOL_SLICE_READY")
    tools = [item for item in definition.get("requiredWorkflowReadyTools") or [] if isinstance(item, dict)]
    return {
        "schemaVersion": SCENARIO_TOOL_SLICE_HANDOFF_SCHEMA_VERSION,
        "status": "ready" if ready else "operator_required",
        "operatorActionRequired": not ready,
        "noAutomaticExecution": True,
        "requiredState": "WorkflowReady",
        "sliceSize": {
            "min": SCENARIO_TOOL_SLICE_MIN,
            "max": SCENARIO_TOOL_SLICE_MAX,
            "actual": len(tools),
        },
        "toolOptions": [_tool_option(item) for item in tools],
        "checklist": _tool_slice_checklist(ready=ready),
        "evidencePolicy": {
            "requiresToolRevisionId": True,
            "requiresCapabilityBundle": True,
            "requiresRuleSpec": True,
            "requiresEnvironmentLock": True,
            "requiresSmokeFixture": True,
            "requiresOutputValidation": True,
            "productionEvidenceOptional": True,
        },
        "excludedActions": SCENARIO_TOOL_SLICE_EXCLUDED_ACTIONS,
    }


def validate_tool_slice_handoff(definition: dict[str, Any]) -> None:
    handoff = tool_slice_handoff(definition)
    if handoff["schemaVersion"] != SCENARIO_TOOL_SLICE_HANDOFF_SCHEMA_VERSION:
        raise WorkflowScenarioToolSliceHandoffError("SCENARIO_TOOL_SLICE_HANDOFF_SCHEMA_INVALID")
    gate_codes = {str(item.get("code") or "") for item in definition.get("gates") or [] if isinstance(item, dict)}
    if "SCENARIO_TOOL_SLICE_READY" not in gate_codes:
        raise WorkflowScenarioToolSliceHandoffError("SCENARIO_TOOL_SLICE_HANDOFF_GATE_REQUIRED")
    if not handoff["noAutomaticExecution"]:
        raise WorkflowScenarioToolSliceHandoffError("SCENARIO_TOOL_SLICE_HANDOFF_MANUAL_REQUIRED")
    if handoff["status"] == "operator_required" and not handoff["operatorActionRequired"]:
        raise WorkflowScenarioToolSliceHandoffError("SCENARIO_TOOL_SLICE_HANDOFF_MANUAL_REQUIRED")
    if handoff["status"] == "ready" and handoff["operatorActionRequired"]:
        raise WorkflowScenarioToolSliceHandoffError("SCENARIO_TOOL_SLICE_HANDOFF_MANUAL_REQUIRED")
    if handoff["sliceSize"]["actual"] < SCENARIO_TOOL_SLICE_MIN or handoff["sliceSize"]["actual"] > SCENARIO_TOOL_SLICE_MAX:
        raise WorkflowScenarioToolSliceHandoffError("SCENARIO_TOOL_SLICE_HANDOFF_SIZE_INVALID")
    checklist_codes = {item["code"] for item in handoff["checklist"]}
    required_codes = {
        "CURATE_TOOL_SLICE",
        "LOCK_TOOL_REVISION",
        "CONFIRM_RULE_SPEC",
        "LOCK_ENVIRONMENT",
        "RUN_SMOKE_FIXTURE",
        "VALIDATE_OUTPUTS",
    }
    if not required_codes <= checklist_codes:
        raise WorkflowScenarioToolSliceHandoffError("SCENARIO_TOOL_SLICE_HANDOFF_CHECKLIST_INCOMPLETE")
    if any(item["status"] not in {"operator_required", "passed"} for item in handoff["checklist"]):
        raise WorkflowScenarioToolSliceHandoffError("SCENARIO_TOOL_SLICE_HANDOFF_STATUS_INVALID")
    _validate_checklist_targets(handoff["checklist"])
    if handoff["excludedActions"] != SCENARIO_TOOL_SLICE_EXCLUDED_ACTIONS:
        raise WorkflowScenarioToolSliceHandoffError("SCENARIO_TOOL_SLICE_HANDOFF_EXCLUSIONS_INVALID")


def _tool_option(item: dict[str, Any]) -> dict[str, str]:
    return {
        "toolId": str(item.get("toolId") or ""),
        "name": str(item.get("name") or ""),
        "kind": str(item.get("kind") or ""),
        "role": str(item.get("role") or ""),
        "contractState": str(item.get("contractState") or ""),
        "acceptanceEvidence": str(item.get("acceptanceEvidence") or ""),
    }


def _validate_checklist_targets(checklist: list[dict[str, str]]) -> None:
    for item in checklist:
        target = str(item.get("target") or "").strip()
        if not target:
            raise WorkflowScenarioToolSliceHandoffError("SCENARIO_TOOL_SLICE_HANDOFF_TARGET_REQUIRED")
        if target not in SCENARIO_PRODUCT_TARGETS:
            raise WorkflowScenarioToolSliceHandoffError(f"SCENARIO_TOOL_SLICE_HANDOFF_TARGET_UNSUPPORTED: {target}")


def _tool_slice_checklist(*, ready: bool) -> list[dict[str, str]]:
    status = "passed" if ready else "operator_required"
    return [
        {
            "code": "CURATE_TOOL_SLICE",
            "label": "收敛 3-5 个具名工具",
            "status": status,
            "target": "/workflows/tools",
            "evidence": "scenario toolOptions are named and role-scoped",
        },
        {
            "code": "LOCK_TOOL_REVISION",
            "label": "锁定 toolRevisionId 和 capability bundle",
            "status": status,
            "target": "/workflows/tools",
            "evidence": "exact toolRevisionId with capability-bundle-v1",
        },
        {
            "code": "CONFIRM_RULE_SPEC",
            "label": "确认 RuleSpec 输入输出和资源",
            "status": status,
            "target": "/workflows/tools",
            "evidence": "saved tool contract contains a renderable RuleSpec",
        },
        {
            "code": "LOCK_ENVIRONMENT",
            "label": "锁定环境和 wrapper ref",
            "status": status,
            "target": "/workflows/tools",
            "evidence": "versioned package identity or pinned wrapper ref",
        },
        {
            "code": "RUN_SMOKE_FIXTURE",
            "label": "用 fixture 完成 smoke run",
            "status": status,
            "target": "/workflows/tools",
            "evidence": "dry-run and smoke-run validation evidence",
        },
        {
            "code": "VALIDATE_OUTPUTS",
            "label": "校验输出 artifact",
            "status": status,
            "target": "/workflows/tools",
            "evidence": "expected artifacts and output validation passed",
        },
    ]


def _gate_passed(definition: dict[str, Any], code: str) -> bool:
    for item in definition.get("gates") or []:
        if isinstance(item, dict) and item.get("code") == code:
            return bool(item.get("passed"))
    return False
