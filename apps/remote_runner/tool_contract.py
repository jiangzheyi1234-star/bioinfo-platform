from __future__ import annotations

from typing import Any

from .tool_contract_environment import summarize_contract_environment
from .tool_contract_rule_summary import (
    has_rule_template_shape,
    selected_rule_entry,
    summarize_rule_template,
)
from .tool_contract_smoke_summary import summarize_smoke_test
from .tool_resource_codes import WAITING_RESOURCE_CODES
from .tool_contract_status import (
    VALIDATION_PASSED,
    default_contract_status,
    normalize_contract_status,
)

BUILDER_ELIGIBLE_STATES = {
    "WorkflowReady",
    "ProductionEnabled",
}


def package_version_from_spec(spec: str) -> str:
    package = str(spec or "").strip().rsplit("::", 1)[-1]
    if not package or any(operator in package for operator in (">", "<", "*")):
        return ""
    for operator in ("==", "="):
        if operator not in package:
            continue
        version = package.split(operator, 1)[1].split("=", 1)[0].strip()
        return version
    return ""


def build_tool_contract(tool: dict[str, Any]) -> dict[str, Any]:
    status = normalize_contract_status(tool.get("contractStatus"))
    package_spec = str(tool.get("packageSpec") or "").strip()
    target_platform = str(tool.get("targetPlatform") or "linux-64").strip() or "linux-64"
    platform_supported = bool(tool.get("targetPlatformSupported"))
    draft = tool.get("ruleSpecDraft") if isinstance(tool.get("ruleSpecDraft"), dict) else {}
    rule_entry = selected_rule_entry(tool)
    template = rule_entry["template"]
    template_summary = summarize_rule_template(template)
    smoke_test = summarize_smoke_test(template)
    has_draft = bool(draft) or has_rule_template_shape(template)
    requires_completion = bool(draft.get("requiresUserCompletion")) if isinstance(draft, dict) else False
    rule_confirmed = (
        bool(template)
        and not requires_completion
        and template_summary["hasSingleAction"]
        and template_summary["actionReady"]
        and template_summary["inputsReady"]
        and template_summary["outputsReady"]
        and template_summary["paramsReady"]
        and template_summary["threadsReady"]
        and template_summary["resourcesReady"]
        and template_summary["logReady"]
    )
    environment = summarize_contract_environment(template)
    environment_ready = bool(environment["specified"])
    renderable = bool(package_spec and platform_supported and rule_confirmed and environment_ready)
    validation = {
        "dryRun": status["dryRun"],
        "smokeRun": status["smokeRun"],
        "outputValidation": status["outputValidation"],
        "production": status["production"],
    }
    dry_run_passed = renderable and _passed(validation["dryRun"])
    waiting_resource = renderable and _waiting_resource_validation(validation["dryRun"])
    missing_resources = _missing_resources(template, validation["dryRun"]) if waiting_resource else []
    smoke_run_passed = dry_run_passed and bool(smoke_test["specified"]) and _passed(validation["smokeRun"])
    output_validated = smoke_run_passed and _passed(validation["outputValidation"])
    workflow_ready = output_validated
    production_enabled = workflow_ready and _passed(validation["production"])
    state = _state_for_contract(
        package_specified=bool(package_spec),
        rule_confirmed=rule_confirmed,
        environment_ready=environment_ready,
        renderable=renderable,
        waiting_resource=waiting_resource,
        smoke_test_specified=bool(smoke_test["specified"]),
        workflow_ready=workflow_ready,
        production_enabled=production_enabled,
        validation=validation,
    )
    requirements = {
        "packageSpecified": bool(package_spec),
        "platformSupported": platform_supported,
        "ruleSpecDrafted": has_draft,
        "ruleSpecConfirmed": rule_confirmed,
        "environmentSpecified": environment_ready,
        "snakemakeRenderable": renderable,
        "smokeTestSpecified": bool(smoke_test["specified"]),
        "dryRunPassed": dry_run_passed,
        "smokeRunPassed": smoke_run_passed,
        "outputValidated": output_validated,
        "productionEnabled": production_enabled,
    }
    contract = {
        "state": state,
        "workflowReady": state in BUILDER_ELIGIBLE_STATES,
        "package": {
            "name": str(tool.get("name") or ""),
            "packageSpec": package_spec,
            "source": str(tool.get("source") or ""),
            "version": str(tool.get("version") or package_version_from_spec(package_spec)),
            "targetPlatform": target_platform,
            "targetPlatformSupported": platform_supported,
        },
        "ruleSpec": {
            "source": str(rule_entry.get("source") or ""),
            "action": template_summary["action"],
            "inputs": template_summary["inputs"],
            "outputs": template_summary["outputs"],
            "params": template_summary["params"],
            "threads": template_summary["threads"],
            "schedulerResources": template_summary["schedulerResources"],
            "log": template_summary["log"],
            "wrapperLocked": template_summary["wrapperLocked"],
            "requiresUserCompletion": requires_completion,
        },
        "smokeTest": smoke_test,
        "environment": environment,
        "requirements": requirements,
        "validation": validation,
        "reasons": _contract_reasons(requirements, template_summary, smoke_test, environment),
    }
    if missing_resources:
        contract["missingResources"] = missing_resources
    return contract


def _state_for_contract(
    *,
    package_specified: bool,
    rule_confirmed: bool,
    environment_ready: bool,
    renderable: bool,
    waiting_resource: bool,
    smoke_test_specified: bool,
    workflow_ready: bool,
    production_enabled: bool,
    validation: dict[str, dict[str, str]],
) -> str:
    if not package_specified:
        return "Discovered"
    if production_enabled:
        return "ProductionEnabled"
    if workflow_ready:
        return "WorkflowReady"
    if waiting_resource:
        return "waiting_resource"
    dry_run_passed = _passed(validation["dryRun"])
    smoke_run_passed = dry_run_passed and smoke_test_specified and _passed(validation["smokeRun"])
    if renderable and smoke_run_passed:
        return "SmokeRunPassed"
    if renderable and dry_run_passed:
        return "DryRunPassed"
    if renderable:
        return "SnakemakeRenderable"
    if rule_confirmed and environment_ready:
        return "EnvSpecified"
    if rule_confirmed:
        return "RuleSpecConfirmed"
    return "AddedDependency"


def _contract_reasons(
    requirements: dict[str, bool],
    template_summary: dict[str, Any],
    smoke_test: dict[str, Any],
    environment: dict[str, Any],
) -> list[str]:
    reasons: list[str] = []
    if not requirements["packageSpecified"]:
        reasons.append("TOOL_PACKAGE_SPEC_REQUIRED")
    if not requirements["platformSupported"]:
        reasons.append("TOOL_PLATFORM_UNSUPPORTED")
    if template_summary["actionCount"] > 1:
        reasons.append("TOOL_RULE_ACTION_CONFLICT")
    elif not template_summary["hasSingleAction"]:
        reasons.append("TOOL_RULE_COMMAND_REQUIRED")
    elif template_summary["action"] == "wrapper" and not template_summary["wrapperLocked"]:
        reasons.append("TOOL_RULE_WRAPPER_LOCK_REQUIRED")
    if not template_summary["inputsReady"]:
        reasons.append("TOOL_RULE_INPUTS_REQUIRED")
    if not template_summary["outputsReady"]:
        reasons.append("TOOL_RULE_OUTPUTS_REQUIRED")
    if not template_summary["paramsReady"]:
        reasons.append("TOOL_RULE_PARAMS_REQUIRED")
    if not template_summary["threadsReady"]:
        reasons.append("TOOL_RULE_THREADS_REQUIRED")
    if not template_summary["resourcesReady"]:
        reasons.append("TOOL_RULE_RESOURCES_REQUIRED")
    if not template_summary["logReady"]:
        reasons.append("TOOL_RULE_LOG_REQUIRED")
    if requirements["snakemakeRenderable"] and not smoke_test.get("specified"):
        reasons.append("TOOL_RULE_SMOKE_TEST_REQUIRED")
    if not requirements["environmentSpecified"]:
        reasons.append("TOOL_RULE_ENVIRONMENT_REQUIRED")
        if environment.get("declared"):
            if not environment.get("locked"):
                reasons.append("TOOL_RULE_ENVIRONMENT_LOCK_REQUIRED")
            if not environment.get("channelPriorityStrict"):
                reasons.append("TOOL_RULE_ENVIRONMENT_CHANNEL_PRIORITY_REQUIRED")
    return reasons


def _passed(status: dict[str, str]) -> bool:
    return str(status.get("status") or "") == VALIDATION_PASSED


def _waiting_resource_validation(status: dict[str, str]) -> bool:
    if str(status.get("status") or "") != "failed":
        return False
    return str(status.get("code") or "").strip() in WAITING_RESOURCE_CODES


def _missing_resources(template: dict[str, Any], dry_run: dict[str, str]) -> list[dict[str, Any]]:
    resource_key = str(dry_run.get("resourceKey") or "").strip() or _resource_key_from_message(
        str(dry_run.get("message") or "")
    )
    if not resource_key:
        return []
    resources = template.get("resources") if isinstance(template.get("resources"), dict) else {}
    spec = resources.get(resource_key) if isinstance(resources.get(resource_key), dict) else {}
    resource: dict[str, Any] = {
        "key": resource_key,
        "resourceType": str(spec.get("type") or dry_run.get("resourceType") or "database"),
        "configKey": str(spec.get("configKey") or dry_run.get("configKey") or resource_key),
        "candidates": [],
    }
    accepted_templates = [str(item).strip() for item in spec.get("acceptedTemplates") or [] if str(item).strip()]
    if accepted_templates:
        resource["acceptedTemplates"] = accepted_templates
    accepted_capabilities = [str(item).strip() for item in spec.get("acceptedCapabilities") or [] if str(item).strip()]
    if accepted_capabilities:
        resource["acceptedCapabilities"] = accepted_capabilities
    return [resource]


def _resource_key_from_message(message: str) -> str:
    _prefix, separator, remainder = str(message or "").rpartition(":")
    return remainder.strip() if separator else ""
