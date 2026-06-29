"""Scenario-level curated tool slice handoff contract."""

from __future__ import annotations

from typing import Any

from apps.api.workflow_scenario_pack_targets import SCENARIO_PRODUCT_TARGETS


SCENARIO_TOOL_SLICE_HANDOFF_SCHEMA_VERSION = "h2ometa.workflow-scenario-tool-slice-handoff.v1"
SCENARIO_TOOL_SLICE_PROMOTION_CONTRACT_SCHEMA_VERSION = (
    "h2ometa.workflow-scenario-tool-slice-promotion-contract.v1"
)
SCENARIO_TOOL_ACCEPTANCE_EVIDENCE_CONTRACT_SCHEMA_VERSION = (
    "h2ometa.workflow-scenario-tool-acceptance-evidence-contract.v1"
)
SCENARIO_TOOL_SLICE_MIN = 3
SCENARIO_TOOL_SLICE_MAX = 5
SCENARIO_TOOL_SLICE_EXCLUDED_ACTIONS = [
    "generic-bioconda-import",
    "request-side-rulespec",
    "unvalidated-tool-selection",
]
SCENARIO_TOOL_SLICE_REQUIRED_EVIDENCE = [
    "toolRevisionId",
    "capability-bundle-v1",
    "RuleSpec",
    "environment-lock",
    "smoke-fixture",
    "expected-output-artifacts",
]
SCENARIO_TOOL_ACCEPTANCE_POINTER_KEYS = {
    "toolRevisionId": "toolRevisionId",
    "capabilityBundle": "capability-bundle-v1",
    "ruleSpec": "RuleSpec",
    "environmentLock": "environment-lock",
    "smokeFixture": "smoke-fixture",
    "expectedOutputArtifacts": "expected-output-artifacts",
}


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
        "promotionContract": _tool_slice_promotion_contract(ready=ready),
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
    for tool in handoff["toolOptions"]:
        _validate_tool_acceptance_contract(tool)
    _validate_promotion_contract(handoff["promotionContract"])


def _tool_option(item: dict[str, Any]) -> dict[str, Any]:
    contract_state = str(item.get("contractState") or "")
    acceptance_evidence = str(item.get("acceptanceEvidence") or "")
    return {
        "toolId": str(item.get("toolId") or ""),
        "name": str(item.get("name") or ""),
        "kind": str(item.get("kind") or ""),
        "role": str(item.get("role") or ""),
        "contractState": contract_state,
        "acceptanceEvidence": acceptance_evidence,
        "acceptanceEvidenceContract": _tool_acceptance_contract(contract_state, acceptance_evidence),
    }


def _validate_checklist_targets(checklist: list[dict[str, str]]) -> None:
    for item in checklist:
        target = str(item.get("target") or "").strip()
        if not target:
            raise WorkflowScenarioToolSliceHandoffError("SCENARIO_TOOL_SLICE_HANDOFF_TARGET_REQUIRED")
        if target not in SCENARIO_PRODUCT_TARGETS:
            raise WorkflowScenarioToolSliceHandoffError(f"SCENARIO_TOOL_SLICE_HANDOFF_TARGET_UNSUPPORTED: {target}")


def _validate_promotion_contract(contract: dict[str, Any]) -> None:
    if contract.get("schemaVersion") != SCENARIO_TOOL_SLICE_PROMOTION_CONTRACT_SCHEMA_VERSION:
        raise WorkflowScenarioToolSliceHandoffError("SCENARIO_TOOL_SLICE_PROMOTION_CONTRACT_INVALID")
    if contract.get("requiredState") != "WorkflowReady":
        raise WorkflowScenarioToolSliceHandoffError("SCENARIO_TOOL_SLICE_PROMOTION_CONTRACT_INVALID")
    if contract.get("requiredEvidence") != SCENARIO_TOOL_SLICE_REQUIRED_EVIDENCE:
        raise WorkflowScenarioToolSliceHandoffError("SCENARIO_TOOL_SLICE_PROMOTION_CONTRACT_INVALID")
    scenario_run = contract.get("scenarioRunEvidence") if isinstance(contract.get("scenarioRunEvidence"), dict) else {}
    required_run_evidence = {
        "workflowRevision",
        "resultPackage",
        "validationCard",
        "evidenceBundle",
        "inputLineage",
        "outputChecksums",
    }
    if set(scenario_run.get("requiredEvidence") or []) != required_run_evidence:
        raise WorkflowScenarioToolSliceHandoffError("SCENARIO_TOOL_SLICE_PROMOTION_CONTRACT_INVALID")
    if contract.get("excludedActions") != SCENARIO_TOOL_SLICE_EXCLUDED_ACTIONS + ["tool-count-only-readiness"]:
        raise WorkflowScenarioToolSliceHandoffError("SCENARIO_TOOL_SLICE_PROMOTION_CONTRACT_INVALID")


def _validate_tool_acceptance_contract(tool: dict[str, Any]) -> None:
    contract = tool.get("acceptanceEvidenceContract") if isinstance(tool.get("acceptanceEvidenceContract"), dict) else {}
    ready = str(tool.get("contractState") or "") == "workflow_ready"
    if contract.get("schemaVersion") != SCENARIO_TOOL_ACCEPTANCE_EVIDENCE_CONTRACT_SCHEMA_VERSION:
        raise WorkflowScenarioToolSliceHandoffError("SCENARIO_TOOL_ACCEPTANCE_EVIDENCE_CONTRACT_INVALID")
    if contract.get("requiredEvidence") != SCENARIO_TOOL_SLICE_REQUIRED_EVIDENCE:
        raise WorkflowScenarioToolSliceHandoffError("SCENARIO_TOOL_ACCEPTANCE_EVIDENCE_CONTRACT_INVALID")
    _validate_tool_acceptance_pointers(contract, ready=ready)
    if contract.get("target") != "/workflows/tools":
        raise WorkflowScenarioToolSliceHandoffError("SCENARIO_TOOL_ACCEPTANCE_EVIDENCE_CONTRACT_INVALID")
    if contract.get("rejectedEvidence") != ["pending-string-only-evidence", "tool-count-only-readiness"]:
        raise WorkflowScenarioToolSliceHandoffError("SCENARIO_TOOL_ACCEPTANCE_EVIDENCE_CONTRACT_INVALID")
    if ready and (contract.get("status") != "accepted" or not str(contract.get("evidenceRef") or "").strip()):
        raise WorkflowScenarioToolSliceHandoffError("SCENARIO_TOOL_ACCEPTANCE_EVIDENCE_CONTRACT_INVALID")
    if not ready and (contract.get("status") != "operator_required" or str(contract.get("evidenceRef") or "").strip()):
        raise WorkflowScenarioToolSliceHandoffError("SCENARIO_TOOL_ACCEPTANCE_EVIDENCE_CONTRACT_INVALID")


def _validate_tool_acceptance_pointers(contract: dict[str, Any], *, ready: bool) -> None:
    pointers = contract.get("evidencePointers") if isinstance(contract.get("evidencePointers"), dict) else {}
    if set(pointers) != set(SCENARIO_TOOL_ACCEPTANCE_POINTER_KEYS):
        raise WorkflowScenarioToolSliceHandoffError("SCENARIO_TOOL_ACCEPTANCE_EVIDENCE_CONTRACT_INVALID")
    for key, evidence_name in SCENARIO_TOOL_ACCEPTANCE_POINTER_KEYS.items():
        pointer = pointers.get(key) if isinstance(pointers.get(key), dict) else {}
        if pointer.get("evidence") != evidence_name:
            raise WorkflowScenarioToolSliceHandoffError("SCENARIO_TOOL_ACCEPTANCE_EVIDENCE_CONTRACT_INVALID")
        ref = str(pointer.get("ref") or "")
        if ready and (pointer.get("status") != "accepted" or not ref.strip()):
            raise WorkflowScenarioToolSliceHandoffError("SCENARIO_TOOL_ACCEPTANCE_EVIDENCE_CONTRACT_INVALID")
        if not ready and (pointer.get("status") != "operator_required" or ref.strip()):
            raise WorkflowScenarioToolSliceHandoffError("SCENARIO_TOOL_ACCEPTANCE_EVIDENCE_CONTRACT_INVALID")


def _tool_acceptance_contract(contract_state: str, acceptance_evidence: str) -> dict[str, Any]:
    ready = contract_state == "workflow_ready"
    return {
        "schemaVersion": SCENARIO_TOOL_ACCEPTANCE_EVIDENCE_CONTRACT_SCHEMA_VERSION,
        "status": "accepted" if ready else "operator_required",
        "evidenceRef": acceptance_evidence if ready else "",
        "requiredEvidence": SCENARIO_TOOL_SLICE_REQUIRED_EVIDENCE,
        "evidencePointers": _tool_acceptance_pointers(ready=ready, evidence_ref=acceptance_evidence),
        "target": "/workflows/tools",
        "rejectedEvidence": ["pending-string-only-evidence", "tool-count-only-readiness"],
    }


def _tool_acceptance_pointers(*, ready: bool, evidence_ref: str) -> dict[str, dict[str, str]]:
    return {
        key: {
            "status": "accepted" if ready else "operator_required",
            "ref": evidence_ref if ready else "",
            "evidence": evidence_name,
        }
        for key, evidence_name in SCENARIO_TOOL_ACCEPTANCE_POINTER_KEYS.items()
    }


def _tool_slice_promotion_contract(*, ready: bool) -> dict[str, Any]:
    status = "passed" if ready else "operator_required"
    return {
        "schemaVersion": SCENARIO_TOOL_SLICE_PROMOTION_CONTRACT_SCHEMA_VERSION,
        "requiredState": "WorkflowReady",
        "requiredEvidence": SCENARIO_TOOL_SLICE_REQUIRED_EVIDENCE,
        "perToolChecklist": [
            {
                "code": "TOOL_REVISION_LOCKED",
                "status": status,
                "target": "/workflows/tools",
                "evidence": "toolRevisionId is immutable and points to the accepted wrapper",
            },
            {
                "code": "RULESPEC_RENDERABLE",
                "status": status,
                "target": "/workflows/tools",
                "evidence": "RuleSpec renders a Snakemake rule without request-side mutation",
            },
            {
                "code": "SMOKE_FIXTURE_PASSED",
                "status": status,
                "target": "/workflows/tools",
                "evidence": "dry-run, smoke run, and expected output artifact checks passed",
            },
        ],
        "scenarioRunEvidence": {
            "requiredEvidence": [
                "workflowRevision",
                "resultPackage",
                "validationCard",
                "evidenceBundle",
                "inputLineage",
                "outputChecksums",
            ],
            "target": "/workflows/results",
        },
        "excludedActions": SCENARIO_TOOL_SLICE_EXCLUDED_ACTIONS + ["tool-count-only-readiness"],
    }


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
