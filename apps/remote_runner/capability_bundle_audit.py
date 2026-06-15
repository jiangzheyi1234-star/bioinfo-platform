from __future__ import annotations

from typing import Any


CAPABILITY_BUNDLE_VERSION = "capability-bundle-v1"


def capability_bundle_audit_for_tool(
    tool: dict[str, Any],
    *,
    step_id: str = "",
    resource_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    tool_id = str(tool.get("id") or tool.get("toolId") or "").strip()
    tool_revision_id = str(tool.get("toolRevisionId") or "").strip()
    tool_name = str(tool.get("name") or _tool_name_from_identifier(tool_id)).strip()
    version = str(tool.get("version") or _version_from_package_spec(str(tool.get("packageSpec") or ""))).strip()
    risk = _risk_summary(tool)
    permissions = _permissions_summary(tool)
    approval = _approval_summary(tool, risk=risk, permissions=permissions, resource_context=resource_context)
    validation_evidence = _validation_evidence(tool)
    return {
        "capabilityBundleVersion": CAPABILITY_BUNDLE_VERSION,
        "capabilityId": _capability_id(tool_id=tool_id, tool_revision_id=tool_revision_id),
        "toolId": tool_id,
        "toolRevisionId": tool_revision_id,
        "toolName": tool_name,
        "toolVersion": version,
        "stepId": str(step_id or "").strip(),
        "selectionRationale": {
            "sourceOfTruth": "capability-bundle-v1",
            "reason": "Workflow step resolved from exact validated ToolRevision.",
            "requiredState": "WorkflowReady",
            "nextAction": "execute-workflow-step",
        },
        "risk": risk,
        "permissions": permissions,
        "approval": approval,
        "admissionEvidence": _admission_evidence(resource_context, permissions=permissions),
        "validationEvidence": validation_evidence,
        "environmentLock": _environment_lock(tool),
        "nextAction": "execute-workflow-step",
    }


def capability_bundle_manifest_entry(
    tool: dict[str, Any],
    *,
    step_id: str = "",
    resource_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    audit = capability_bundle_audit_for_tool(tool, step_id=step_id, resource_context=resource_context)
    return {
        "capabilityBundleVersion": audit["capabilityBundleVersion"],
        "capabilityId": audit["capabilityId"],
        "toolRevisionId": audit["toolRevisionId"],
        "toolVersion": audit["toolVersion"],
        "selectionRationale": audit["selectionRationale"],
        "risk": audit["risk"],
        "permissions": audit["permissions"],
        "approval": audit["approval"],
        "admissionEvidence": audit["admissionEvidence"],
        "validationEvidence": audit["validationEvidence"],
        "nextAction": audit["nextAction"],
    }


def _environment_lock(tool: dict[str, Any]) -> dict[str, Any]:
    lock = tool.get("environmentLock") if isinstance(tool.get("environmentLock"), dict) else {}
    if lock:
        return dict(lock)
    package_spec = str(tool.get("packageSpec") or "").strip()
    target_platform = str(tool.get("targetPlatform") or "linux-64").strip() or "linux-64"
    rule_template = tool.get("ruleTemplate") if isinstance(tool.get("ruleTemplate"), dict) else {}
    environment = rule_template.get("environment") if isinstance(rule_template.get("environment"), dict) else {}
    conda = environment.get("conda") if isinstance(environment.get("conda"), dict) else {}
    dependencies = [
        str(item).replace("{packageSpec}", package_spec).strip()
        for item in conda.get("dependencies") or []
        if str(item or "").strip()
    ]
    return {
        "manager": "conda" if conda else "",
        "targetPlatform": target_platform,
        "channels": [str(item).strip() for item in conda.get("channels") or [] if str(item or "").strip()],
        "dependencies": dependencies,
        "packageSpec": package_spec,
    }


def _validation_evidence(tool: dict[str, Any]) -> dict[str, Any]:
    status = tool.get("contractStatus") if isinstance(tool.get("contractStatus"), dict) else {}
    validation_summary = tool.get("validationSummary") if isinstance(tool.get("validationSummary"), dict) else {}
    rule_template = tool.get("ruleTemplate") if isinstance(tool.get("ruleTemplate"), dict) else {}
    stages = []
    for stage_id in ("dryRun", "smokeRun", "outputValidation"):
        stage = status.get(stage_id) if isinstance(status.get(stage_id), dict) else {}
        stages.append(
            {
                "id": stage_id,
                "status": str(stage.get("status") or "").strip(),
                "code": str(stage.get("code") or "").strip(),
                "checkedAt": str(stage.get("checkedAt") or "").strip(),
                "logPath": str(stage.get("logPath") or "").strip(),
            }
        )
    passed = all(stage["status"] == "passed" for stage in stages)
    return {
        "status": "passed" if passed else str(validation_summary.get("latestStatus") or "missing"),
        "validationResultId": str(validation_summary.get("latestResultId") or tool.get("validationResultId") or "").strip(),
        "evidenceId": str(validation_summary.get("evidenceId") or tool.get("evidenceId") or "").strip(),
        "stages": stages,
        "fixture": _fixture_summary(rule_template),
    }


def _fixture_summary(rule_template: dict[str, Any]) -> dict[str, Any]:
    smoke_test = rule_template.get("smokeTest") if isinstance(rule_template.get("smokeTest"), dict) else {}
    inputs = smoke_test.get("inputs") if isinstance(smoke_test.get("inputs"), dict) else {}
    outputs = rule_template.get("outputs") if isinstance(rule_template.get("outputs"), list) else []
    return {
        "inputs": [
            {
                "name": str(name),
                "filename": str(value.get("filename") or value.get("name") or name),
                "mimeType": str(value.get("mimeType") or ""),
            }
            for name, value in inputs.items()
            if isinstance(value, dict) and (value.get("content") or value.get("contentBase64"))
        ],
        "expectedArtifacts": [
            {
                "name": str(item.get("name") or ""),
                "path": str(item.get("path") or ""),
                "mimeType": str(item.get("mimeType") or ""),
            }
            for item in outputs
            if isinstance(item, dict) and str(item.get("path") or "").strip()
        ],
    }


def _risk_summary(tool: dict[str, Any]) -> dict[str, Any]:
    rule_template = tool.get("ruleTemplate") if isinstance(tool.get("ruleTemplate"), dict) else {}
    resources = rule_template.get("resources") if isinstance(rule_template.get("resources"), dict) else {}
    database_keys = [
        str(key)
        for key, value in resources.items()
        if isinstance(value, dict) and str(value.get("type") or "") == "database"
    ]
    return {
        "level": "medium" if database_keys else "low",
        "reasons": ["requires-database"] if database_keys else ["local-file-transform"],
    }


def _permissions_summary(tool: dict[str, Any]) -> dict[str, Any]:
    rule_template = tool.get("ruleTemplate") if isinstance(tool.get("ruleTemplate"), dict) else {}
    resources = rule_template.get("resources") if isinstance(rule_template.get("resources"), dict) else {}
    databases = [
        str(key)
        for key, value in resources.items()
        if isinstance(value, dict) and str(value.get("type") or "") == "database"
    ]
    return {
        "network": False,
        "filesystem": ["read-inputs", "write-declared-outputs", "write-logs"],
        "databases": databases,
    }


def _approval_summary(
    tool: dict[str, Any],
    *,
    risk: dict[str, Any],
    permissions: dict[str, Any],
    resource_context: dict[str, Any] | None,
) -> dict[str, Any]:
    policy = tool.get("capabilityApproval") if isinstance(tool.get("capabilityApproval"), dict) else {}
    required = (
        str(risk.get("level") or "low") in {"medium", "high"}
        or bool(permissions.get("network"))
        or bool(permissions.get("databases"))
    )
    resource_ready = _resource_context_satisfies_permissions(resource_context, permissions=permissions)
    approved = bool(policy.get("approved")) if required else True
    if required and not approved and resource_ready:
        approved = True
    reason = str(policy.get("reason") or "").strip()
    if not reason:
        if not required:
            reason = "low-risk-auto-approved"
        elif resource_ready:
            reason = "validated-database-resource"
        else:
            reason = "approval-required"
    policy_version = str(policy.get("policyVersion") or "").strip()
    if not policy_version and required and resource_ready:
        policy_version = "capability-admission-v1"
    return {
        "required": required,
        "approved": approved,
        "policyVersion": policy_version,
        "reason": reason,
    }


def _resource_context_satisfies_permissions(
    resource_context: dict[str, Any] | None,
    *,
    permissions: dict[str, Any],
) -> bool:
    database_keys = [str(item).strip() for item in permissions.get("databases") or [] if str(item).strip()]
    if not database_keys:
        return False
    resources = resource_context if isinstance(resource_context, dict) else {}
    return all(isinstance(resources.get(key), dict) and bool(resources[key].get("databaseId")) for key in database_keys)


def _admission_evidence(
    resource_context: dict[str, Any] | None,
    *,
    permissions: dict[str, Any],
) -> dict[str, Any]:
    database_keys = [str(item).strip() for item in permissions.get("databases") or [] if str(item).strip()]
    resources = resource_context if isinstance(resource_context, dict) else {}
    database_resources = []
    for key in database_keys:
        resource = resources.get(key) if isinstance(resources.get(key), dict) else {}
        if not resource:
            continue
        database_resources.append(
            {
                "resourceKey": key,
                "configKey": str(resource.get("configKey") or key),
                "databaseId": str(resource.get("databaseId") or ""),
                "name": str(resource.get("name") or ""),
                "templateId": str(resource.get("templateId") or ""),
                "status": "available",
                "version": str(resource.get("version") or ""),
                "pathMode": str(resource.get("pathMode") or ""),
            }
        )
    if not database_resources:
        return {}
    return {
        "policyVersion": "capability-admission-v1",
        "databaseResources": database_resources,
        "missingResources": [
            {"resourceKey": key, "nextAction": "add-database"}
            for key in database_keys
            if key not in {resource["resourceKey"] for resource in database_resources}
        ],
    }


def _capability_id(*, tool_id: str, tool_revision_id: str) -> str:
    normalized = (tool_revision_id or tool_id).replace(":", "_").replace("/", "_")
    return f"{CAPABILITY_BUNDLE_VERSION}:tool:{normalized}"


def _tool_name_from_identifier(value: Any) -> str:
    text = str(value or "").strip()
    if "::" in text:
        text = text.rsplit("::", 1)[-1]
    if "@" in text:
        text = text.split("@", 1)[0]
    if "#" in text:
        text = text.split("#", 1)[0]
    return text


def _version_from_package_spec(package_spec: str) -> str:
    text = str(package_spec or "").strip().rsplit("::", 1)[-1]
    if "==" in text:
        return text.split("==", 1)[1].strip()
    if "=" in text:
        return text.split("=", 1)[1].strip()
    return ""
