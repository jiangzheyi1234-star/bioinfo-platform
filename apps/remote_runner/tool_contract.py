from __future__ import annotations

import re
from typing import Any


VALIDATION_KEYS = ("dryRun", "smokeRun", "outputValidation", "production")
VALIDATION_PASSED = "passed"
VALIDATION_NOT_RUN = "not_run"
MOVING_WRAPPER_REFS = {"bio", "master", "main", "latest", "head", "dev"}
WRAPPER_VERSION_RE = re.compile(r"^v?\d+(?:\.\d+){1,}(?:[-+._A-Za-z0-9]*)?$")
WRAPPER_COMMIT_RE = re.compile(r"^[0-9a-fA-F]{7,40}$")
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


def default_contract_status() -> dict[str, dict[str, str]]:
    return {key: {"status": VALIDATION_NOT_RUN, "message": ""} for key in VALIDATION_KEYS}


def normalize_contract_status(raw: Any) -> dict[str, dict[str, str]]:
    if not isinstance(raw, dict):
        return default_contract_status()
    normalized = default_contract_status()
    for key in VALIDATION_KEYS:
        value = raw.get(key)
        if not isinstance(value, dict):
            continue
        status = str(value.get("status") or VALIDATION_NOT_RUN).strip() or VALIDATION_NOT_RUN
        item = {"status": status, "message": str(value.get("message") or "")}
        code = str(value.get("code") or "").strip()
        if code:
            item["code"] = code
        checked_at = str(value.get("checkedAt") or "").strip()
        if checked_at:
            item["checkedAt"] = checked_at
        for evidence_key in (
            "runId",
            "logPath",
            "evidenceType",
            "databaseId",
            "templateId",
            "role",
            "artifactName",
            "artifactCount",
            "artifactNames",
        ):
            evidence_value = str(value.get(evidence_key) or "").strip()
            if evidence_value:
                item[evidence_key] = evidence_value
        normalized[key] = item
    return normalized


def build_tool_contract(tool: dict[str, Any]) -> dict[str, Any]:
    status = normalize_contract_status(tool.get("contractStatus"))
    package_spec = str(tool.get("packageSpec") or "").strip()
    target_platform = str(tool.get("targetPlatform") or "linux-64").strip() or "linux-64"
    platform_supported = bool(tool.get("targetPlatformSupported"))
    draft = tool.get("ruleSpecDraft") if isinstance(tool.get("ruleSpecDraft"), dict) else {}
    rule_entry = _selected_rule_entry(tool)
    template = rule_entry["template"]
    template_summary = _template_summary(template)
    smoke_test = _smoke_test_summary(template)
    has_draft = bool(draft) or _has_rule_template_shape(template)
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
    environment = _environment_summary(template)
    environment_ready = bool(environment["specified"])
    renderable = bool(package_spec and platform_supported and rule_confirmed and environment_ready)
    validation = {
        "dryRun": status["dryRun"],
        "smokeRun": status["smokeRun"],
        "outputValidation": status["outputValidation"],
        "production": status["production"],
    }
    dry_run_passed = renderable and _passed(validation["dryRun"])
    smoke_run_passed = dry_run_passed and bool(smoke_test["specified"]) and _passed(validation["smokeRun"])
    output_validated = smoke_run_passed and _passed(validation["outputValidation"])
    workflow_ready = output_validated
    production_enabled = workflow_ready and _passed(validation["production"])
    state = _state_for_contract(
        package_specified=bool(package_spec),
        has_draft=has_draft,
        rule_confirmed=rule_confirmed,
        environment_ready=environment_ready,
        renderable=renderable,
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
    return {
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


def _state_for_contract(
    *,
    package_specified: bool,
    has_draft: bool,
    rule_confirmed: bool,
    environment_ready: bool,
    renderable: bool,
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
    dry_run_passed = _passed(validation["dryRun"])
    smoke_run_passed = dry_run_passed and smoke_test_specified and _passed(validation["smokeRun"])
    output_validated = smoke_run_passed and _passed(validation["outputValidation"])
    if renderable and output_validated:
        return "OutputValidated"
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
    if has_draft:
        return "RuleSpecDrafted"
    return "AddedDependency"


def _selected_rule_entry(tool: dict[str, Any]) -> dict[str, Any]:
    manifest = tool.get("ruleTemplate") if isinstance(tool.get("ruleTemplate"), dict) else {}
    if _has_rule_template_shape(manifest):
        return {"source": "manifest", "template": manifest}
    return {"source": "", "template": {}}


def _template_summary(template: dict[str, Any]) -> dict[str, Any]:
    actions = _rule_action_fields(template)
    action = actions[0] if len(actions) == 1 else ""
    wrapper = _string(template.get("wrapper"))
    wrapper_locked = _wrapper_ref_locked(wrapper) if action == "wrapper" else False
    inputs = [item for item in template.get("inputs") or [] if isinstance(item, dict)]
    outputs = [item for item in template.get("outputs") or [] if isinstance(item, dict)]
    params = template.get("params") if isinstance(template.get("params"), dict) else {}
    params_ready = isinstance(template.get("params"), dict)
    threads_ready = _threads_ready(template)
    scheduler_resources = _scheduler_resource_count(template)
    log_ready = _log_ready(template.get("log"))
    return {
        "action": action,
        "actionCount": len(actions),
        "hasSingleAction": len(actions) == 1,
        "actionReady": len(actions) == 1 and (action != "wrapper" or wrapper_locked),
        "wrapperLocked": wrapper_locked,
        "inputs": len(inputs),
        "outputs": len(outputs),
        "params": len(params),
        "threads": 1 if threads_ready else 0,
        "schedulerResources": scheduler_resources,
        "log": 1 if log_ready else 0,
        "inputsReady": bool(inputs) and all(_string(item.get("name")) for item in inputs),
        "outputsReady": bool(outputs) and all(_output_ready(item) for item in outputs),
        "paramsReady": params_ready,
        "threadsReady": threads_ready,
        "resourcesReady": scheduler_resources > 0,
        "logReady": log_ready,
    }


def _environment_summary(template: dict[str, Any]) -> dict[str, Any]:
    conda = template.get("environment", {}).get("conda") if isinstance(template.get("environment"), dict) else {}
    conda = conda if isinstance(conda, dict) else {}
    channels = _string_list(conda.get("channels"))
    dependencies = _string_list(conda.get("dependencies"))
    declared = bool(channels or dependencies)
    locked = bool(dependencies) and all(_dependency_locked(item) for item in dependencies)
    channel_priority = _channel_priority_strict(channels)
    return {
        "specified": bool(channels and dependencies and locked and channel_priority),
        "declared": declared,
        "locked": locked,
        "channelPriorityStrict": channel_priority,
        "channels": channels,
        "dependencies": dependencies,
    }


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


def _smoke_test_summary(template: dict[str, Any]) -> dict[str, Any]:
    inputs = [item for item in template.get("inputs") or [] if isinstance(item, dict)]
    required_inputs = [item for item in inputs if bool(item.get("required", True))]
    input_names = [_string(item.get("name")) for item in required_inputs if _string(item.get("name"))]
    raw_smoke = template.get("smokeTest")
    smoke_specified = isinstance(raw_smoke, dict)
    smoke = raw_smoke if smoke_specified else {}
    smoke_inputs = smoke.get("inputs") if isinstance(smoke.get("inputs"), dict) else {}
    missing_inputs = [name for name in input_names if not _smoke_input_ready(smoke_inputs.get(name))]
    return {
        "specified": smoke_specified and not missing_inputs,
        "inputs": len(smoke_inputs),
        "requiredInputs": len(input_names),
        "missingInputs": missing_inputs,
    }


def _smoke_input_ready(raw: Any) -> bool:
    if not isinstance(raw, dict):
        return False
    return isinstance(raw.get("content"), str) or bool(_string(raw.get("contentBase64")))


def _has_rule_template_shape(template: dict[str, Any]) -> bool:
    return bool(
        _rule_action_fields(template)
        or isinstance(template.get("inputs"), list)
        or isinstance(template.get("outputs"), list)
        or isinstance(template.get("params"), dict)
    )


def _rule_action_fields(template: dict[str, Any]) -> list[str]:
    actions: list[str] = []
    for field in ("commandTemplate", "wrapper", "script"):
        if _string(template.get(field)):
            actions.append(field)
    module = template.get("module")
    if isinstance(module, dict) and (_string(module.get("snakefile")) or _string(module.get("rule"))):
        actions.append("module")
    return actions


def _wrapper_ref_locked(wrapper: str) -> bool:
    parts = [part for part in wrapper.split("/") if part]
    if len(parts) < 2:
        return False
    ref = parts[0].strip()
    if not ref or ref.lower() in MOVING_WRAPPER_REFS:
        return False
    return bool(WRAPPER_VERSION_RE.match(ref) or WRAPPER_COMMIT_RE.match(ref))


def _output_ready(item: dict[str, Any]) -> bool:
    return bool(
        _string(item.get("name"))
        and _string(item.get("path"))
        and _string(item.get("kind"))
        and _string(item.get("mimeType"))
    )


def _threads_ready(template: dict[str, Any]) -> bool:
    return _positive_int(template.get("threads")) or _positive_int(_resource_default(template.get("resources"), "threads"))


def _scheduler_resource_count(template: dict[str, Any]) -> int:
    names: set[str] = set()
    for field in ("schedulerResources", "runtimeResources"):
        raw = template.get(field)
        if isinstance(raw, dict):
            names.update(name for name, value in raw.items() if _string(name) and _scheduler_value_ready(value))
    resources = template.get("resources")
    if isinstance(resources, dict):
        for name, value in resources.items():
            if name == "threads":
                continue
            if _scheduler_value_ready(value) and not _workflow_resource_value(value):
                names.add(str(name))
    return len(names)


def _scheduler_value_ready(value: Any) -> bool:
    if isinstance(value, (str, int, float)) and not isinstance(value, bool):
        return bool(str(value).strip())
    if isinstance(value, dict):
        if _workflow_resource_value(value):
            return False
        return any(_scheduler_value_ready(value.get(key)) for key in ("default", "value"))
    return False


def _workflow_resource_value(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    return any(key in value for key in ("acceptedTemplates", "acceptedCapabilities", "configKey")) or str(value.get("type") or "") == "database"


def _resource_default(resources: Any, name: str) -> Any:
    if not isinstance(resources, dict):
        return None
    value = resources.get(name)
    if isinstance(value, dict):
        return value.get("default", value.get("value"))
    return value


def _positive_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 1


def _log_ready(raw: Any) -> bool:
    if isinstance(raw, str):
        return bool(raw.strip())
    if isinstance(raw, dict):
        return bool(raw) and all(_string(name) and _string(path) for name, path in raw.items())
    return False


def _dependency_locked(value: str) -> bool:
    spec = value.strip()
    if not spec or any(operator in spec for operator in (">", "<", "*")):
        return False
    package = spec.rsplit("::", 1)[-1]
    if "==" in package:
        name, version = package.split("==", 1)
    elif "=" in package:
        name, version = package.split("=", 1)
    else:
        return False
    return bool(name.strip() and version.strip())


def _channel_priority_strict(channels: list[str]) -> bool:
    if not channels:
        return False
    try:
        conda_forge_index = channels.index("conda-forge")
    except ValueError:
        return False
    if "bioconda" not in channels:
        return True
    return conda_forge_index < channels.index("bioconda")


def _string_list(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        return []
    return [value for value in (_string(item) for item in raw) if value]


def _string(raw: Any) -> str:
    return str(raw or "").strip()


def _passed(status: dict[str, str]) -> bool:
    return str(status.get("status") or "") == VALIDATION_PASSED
