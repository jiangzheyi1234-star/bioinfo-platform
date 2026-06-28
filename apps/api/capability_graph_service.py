"""Unified capability graph snapshot for tool discovery and selection."""

from __future__ import annotations

import re
from typing import Any

from apps.api.bio_tool_pack_capability_graph import semantic_capability_graph
from apps.api.bio_tool_pack_manifest import complete_rule_template_semantics
from apps.api.tool_candidate_catalog import search_tool_candidates
from apps.api.tool_profile_model import ToolProfile
from apps.api.tool_profile_sources import all_tool_profiles
from apps.api.tool_registry_payload import registered_tools_from_runtime_payload
from core.contracts.capability_bundle import CAPABILITY_BUNDLE_VERSION, validate_capability_bundle_contract

_READY_STATES = {"WorkflowReady", "ProductionEnabled"}


class CapabilityGraphService:
    """Build a single tool capability view for UI, agents, and validation queues."""

    def snapshot(
        self,
        *,
        query: str = "",
        target_platform: str = "linux-64",
        page: int = 1,
        page_size: int = 50,
        registered_tools: list[dict[str, Any]] | None = None,
        catalog: dict[str, Any] | None = None,
        databases: list[dict[str, Any]] | None = None,
        target_acceptance: dict[str, Any] | None = None,
        prepare_job_queue: dict[str, Any] | None = None,
        agent_selectable_only: bool = False,
    ) -> dict[str, Any]:
        profiles = all_tool_profiles()
        registered = registered_tools or []
        candidate_catalog = catalog if isinstance(catalog, dict) else search_tool_candidates(
            query,
            target_platform=target_platform,
            page=page,
            page_size=page_size,
        )
        registered_tools_view = _registered_tools_view(registered)
        capability_bundle_results = _capability_bundle_results(
            profiles=profiles,
            registered_tools=registered_tools_view,
            databases=databases,
        )
        capability_bundles = [result["bundle"] for result in capability_bundle_results if result.get("agentSelectable")]
        bundle_ready_tools = [
            {**result["tool"], "capabilityBundle": result["bundle"]}
            for result in capability_bundle_results
            if result.get("agentSelectable")
        ]
        graph = semantic_capability_graph(
            profiles=profiles,
            registered_tools=bundle_ready_tools,
            agent_selectable_only=agent_selectable_only,
        )
        graph = _attach_bundle_summaries_to_graph(graph, capability_bundles)
        registered_tools_view = _attach_capability_bundle_status(registered_tools_view, capability_bundle_results)
        agent_selectable_tools = _agent_selectable_tools(registered_tools_view)
        snapshot = {
            "contractVersion": "capability-graph-snapshot-v1",
            "capabilityBundleVersion": CAPABILITY_BUNDLE_VERSION,
            "query": str(query or "").strip(),
            "targetPlatform": str(target_platform or "linux-64").strip() or "linux-64",
            "profileCount": len(profiles),
            "packIds": _pack_ids(profiles),
            "catalog": candidate_catalog,
            "semanticGraph": graph,
            "capabilityBundles": capability_bundles,
            "capabilityBundleGate": _capability_bundle_gate(capability_bundle_results),
            "registeredTools": registered_tools_view,
            "registeredToolCounts": _registered_tool_counts(registered),
            "agentSelectableTools": agent_selectable_tools,
            "agentSelectableProfileIds": graph.get("agentSelectableProfileIds", []),
            "selectionPolicy": {
                "sourceOfTruth": "CapabilityGraphSnapshot",
                "readinessSourceOfTruth": "registeredTool.toolContract",
                "bundleSourceOfTruth": CAPABILITY_BUNDLE_VERSION,
                "resourceAdmissionSourceOfTruth": "validated reference database registry",
                "canAddStepStates": ["WorkflowReady", "ProductionEnabled"],
                "blockedReason": "CAPABILITY_BUNDLE_NOT_SELECTABLE",
            },
        }
        if isinstance(target_acceptance, dict):
            snapshot["targetAcceptance"] = target_acceptance
            snapshot["targetSummary"] = _target_summary(target_acceptance)
            validation_queue = target_acceptance.get("validationQueue")
            if isinstance(validation_queue, dict):
                snapshot["validationQueue"] = validation_queue
            production_queue = target_acceptance.get("productionQueue")
            if isinstance(production_queue, dict):
                snapshot["productionQueue"] = production_queue
        if isinstance(prepare_job_queue, dict):
            snapshot["prepareJobQueue"] = prepare_job_queue
        return snapshot

    def snapshot_from_runtime(
        self,
        *,
        runtime: Any,
        query: str = "",
        target_platform: str = "linux-64",
        page: int = 1,
        page_size: int = 50,
        registered_tools: list[dict[str, Any]] | None = None,
        catalog: dict[str, Any] | None = None,
        databases: list[dict[str, Any]] | None = None,
        target_acceptance: dict[str, Any] | None = None,
        prepare_job_queue: dict[str, Any] | None = None,
        agent_selectable_only: bool = False,
    ) -> dict[str, Any]:
        registered = registered_tools
        if registered is None:
            registered = registered_tools_from_runtime_payload(runtime.list_tools())
        return self.snapshot(
            query=query,
            target_platform=target_platform,
            page=page,
            page_size=page_size,
            registered_tools=registered,
            catalog=catalog,
            databases=databases,
            target_acceptance=target_acceptance,
            prepare_job_queue=prepare_job_queue,
            agent_selectable_only=agent_selectable_only,
        )


DEFAULT_CAPABILITY_GRAPH_SERVICE = CapabilityGraphService()


def _pack_ids(profiles: tuple[Any, ...]) -> list[str]:
    return sorted({str(profile.pack_id or "builtin").strip() for profile in profiles})


def _registered_tool_counts(tools: list[dict[str, Any]]) -> dict[str, int]:
    valid = [tool for tool in tools if isinstance(tool, dict)]
    workflow_ready = 0
    production_enabled = 0
    for tool in valid:
        contract = tool.get("toolContract") if isinstance(tool.get("toolContract"), dict) else {}
        state = str(contract.get("state") or "").strip()
        if contract.get("workflowReady") is True or state in {"WorkflowReady", "ProductionEnabled"}:
            workflow_ready += 1
        if contract.get("productionEnabled") is True or state == "ProductionEnabled":
            production_enabled += 1
    return {
        "total": len(valid),
        "workflowReady": workflow_ready,
        "productionEnabled": production_enabled,
    }


def _registered_tools_view(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [dict(tool) for tool in tools if isinstance(tool, dict)]


def _agent_selectable_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [tool for tool in tools if _tool_can_add_step(tool) and isinstance(tool.get("capabilityBundle"), dict)]


def _tool_can_add_step(tool: dict[str, Any]) -> bool:
    contract = tool.get("toolContract") if isinstance(tool.get("toolContract"), dict) else {}
    state = str(contract.get("state") or "").strip()
    has_revision = bool(str(tool.get("toolRevisionId") or contract.get("toolRevisionId") or "").strip())
    return has_revision and (contract.get("workflowReady") is True or state in _READY_STATES)


def _capability_bundle_results(
    *,
    profiles: tuple[ToolProfile, ...],
    registered_tools: list[dict[str, Any]],
    databases: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for tool in registered_tools:
        if not isinstance(tool, dict):
            continue
        profile = _matching_profile(tool, profiles)
        bundle, reasons = _capability_bundle_for_tool(tool=tool, profile=profile, databases=databases)
        results.append(
            {
                "tool": tool,
                "bundle": bundle,
                "reasons": reasons,
                "agentSelectable": not reasons,
            }
        )
    return results


def _capability_bundle_for_tool(
    *,
    tool: dict[str, Any],
    profile: ToolProfile | None,
    databases: list[dict[str, Any]] | None,
) -> tuple[dict[str, Any], list[str]]:
    contract = tool.get("toolContract") if isinstance(tool.get("toolContract"), dict) else {}
    rule_template = _bundle_rule_template(tool=tool, profile=profile)
    completed_template = complete_rule_template_semantics(rule_template)
    tool_id = str(tool.get("id") or tool.get("toolId") or "").strip()
    tool_name = str(tool.get("name") or _tool_name_from_identifier(tool_id)).strip()
    tool_revision_id = str(tool.get("toolRevisionId") or contract.get("toolRevisionId") or "").strip()
    package = contract.get("package") if isinstance(contract.get("package"), dict) else {}
    package_spec = str(tool.get("packageSpec") or package.get("packageSpec") or "").strip()
    source = str(tool.get("source") or package.get("source") or _source_from_package_spec(package_spec)).strip()
    version = str(tool.get("version") or package.get("version") or _version_from_package_spec(package_spec)).strip()
    inputs = _bundle_ports(completed_template.get("inputs"))
    outputs = _bundle_ports(completed_template.get("outputs"))
    parameters = _bundle_parameters(completed_template.get("params"))
    environment_lock = _environment_lock(
        rule_template=completed_template,
        package_spec=package_spec,
        target_platform=str(tool.get("targetPlatform") or package.get("targetPlatform") or "linux-64").strip() or "linux-64",
    )
    validation_evidence = _validation_evidence(tool, rule_template=completed_template)
    risk = _risk_summary(rule_template=completed_template)
    permissions = _permissions_summary(rule_template=completed_template)
    resource_admission = _database_resource_admission(rule_template=completed_template, databases=databases)
    approval = _approval_summary(
        tool=tool,
        risk=risk,
        permissions=permissions,
        resource_admission=resource_admission,
    )
    profile_id = profile.profile_id if profile is not None else _tool_name_from_identifier(tool_name or tool_id)
    pack_id = profile.pack_id if profile is not None else str(tool.get("packId") or "registered-tool").strip()
    capability_id = _capability_id(pack_id=pack_id, profile_id=profile_id, tool_revision_id=tool_revision_id)
    bundle = {
        "capabilityBundleVersion": CAPABILITY_BUNDLE_VERSION,
        "capabilityId": capability_id,
        "toolId": tool_id,
        "toolName": tool_name,
        "profileId": profile_id,
        "packId": pack_id,
        "toolRevisionId": tool_revision_id,
        "source": source,
        "version": version,
        "inputs": inputs,
        "outputs": outputs,
        "parameters": parameters,
        "environmentLock": environment_lock,
        "risk": risk,
        "permissions": permissions,
        "approval": approval,
        "admissionEvidence": _admission_evidence(resource_admission),
        "validationEvidence": validation_evidence,
        "selectionSummary": {
            "label": tool_name or profile_id,
            "workflowStage": profile.workflow_stage if profile is not None else "",
            "operation": profile.operation if profile is not None else "",
            "reason": "Tool revision has a validated capability bundle.",
        },
    }
    validate_capability_bundle_contract(bundle)
    reasons = _bundle_blocking_reasons(
        tool=tool,
        contract=contract,
        tool_revision_id=tool_revision_id,
        inputs=inputs,
        outputs=outputs,
        environment_lock=environment_lock,
        approval=approval,
        validation_evidence=validation_evidence,
        version=version,
    )
    bundle["agentSelectable"] = not reasons
    bundle["blockedReasons"] = reasons
    bundle["nextAction"] = _bundle_next_action(reasons)
    return bundle, reasons


def _bundle_blocking_reasons(
    *,
    tool: dict[str, Any],
    contract: dict[str, Any],
    tool_revision_id: str,
    inputs: list[dict[str, Any]],
    outputs: list[dict[str, Any]],
    environment_lock: dict[str, Any],
    approval: dict[str, Any],
    validation_evidence: dict[str, Any],
    version: str,
) -> list[str]:
    reasons: list[str] = []
    state = str(contract.get("state") or "").strip()
    if state not in _READY_STATES and contract.get("workflowReady") is not True:
        reasons.append("WORKFLOW_TOOL_NOT_READY")
    if not tool_revision_id or tool_revision_id in {str(tool.get("id") or ""), str(tool.get("toolId") or "")}:
        reasons.append("EXACT_TOOL_REVISION_REQUIRED")
    if not version:
        reasons.append("TOOL_VERSION_REQUIRED")
    if not inputs:
        reasons.append("CAPABILITY_INPUT_SCHEMA_REQUIRED")
    if not outputs:
        reasons.append("CAPABILITY_OUTPUT_SCHEMA_REQUIRED")
    if not _ports_have_schema(inputs):
        reasons.append("CAPABILITY_INPUT_PORT_SCHEMA_INCOMPLETE")
    if not _ports_have_schema(outputs):
        reasons.append("CAPABILITY_OUTPUT_PORT_SCHEMA_INCOMPLETE")
    if not environment_lock.get("dependencies"):
        reasons.append("ENVIRONMENT_LOCK_REQUIRED")
    if any("{packageSpec}" in str(value) for value in environment_lock.get("dependencies") or []):
        reasons.append("ENVIRONMENT_LOCK_UNRESOLVED")
    if not validation_evidence.get("fixture", {}).get("inputs"):
        reasons.append("SMOKE_FIXTURE_REQUIRED")
    if not validation_evidence.get("fixture", {}).get("expectedArtifacts"):
        reasons.append("EXPECTED_ARTIFACT_REQUIRED")
    if validation_evidence.get("status") != "passed":
        reasons.append("VALIDATION_EVIDENCE_REQUIRED")
    if not str(validation_evidence.get("validationResultId") or "").strip():
        reasons.append("VALIDATION_RESULT_ID_REQUIRED")
    if not str(validation_evidence.get("evidenceId") or "").strip():
        reasons.append("VALIDATION_EVIDENCE_ID_REQUIRED")
    if approval.get("required") is True and approval.get("approved") is not True:
        if approval.get("reason") == "database-resource-required":
            reasons.append("DATABASE_RESOURCE_REQUIRED")
        else:
            reasons.append("CAPABILITY_APPROVAL_REQUIRED")
    return _unique_strings(reasons)


def _attach_capability_bundle_status(
    tools: list[dict[str, Any]],
    results: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    by_revision = {
        str(result["bundle"].get("toolRevisionId") or ""): result
        for result in results
        if isinstance(result.get("bundle"), dict)
    }
    attached: list[dict[str, Any]] = []
    for tool in tools:
        next_tool = dict(tool)
        revision_id = str(next_tool.get("toolRevisionId") or "").strip()
        result = by_revision.get(revision_id)
        if result is not None:
            next_tool["capabilityBundleStatus"] = {
                "version": CAPABILITY_BUNDLE_VERSION,
                "agentSelectable": bool(result.get("agentSelectable")),
                "blockedReasons": list(result.get("reasons") or []),
                "nextAction": _bundle_next_action(list(result.get("reasons") or [])),
            }
            if result.get("agentSelectable"):
                next_tool["capabilityBundle"] = result["bundle"]
        attached.append(next_tool)
    return attached


def _attach_bundle_summaries_to_graph(graph: dict[str, Any], bundles: list[dict[str, Any]]) -> dict[str, Any]:
    by_profile = {str(bundle.get("profileId") or ""): bundle for bundle in bundles}
    nodes: list[dict[str, Any]] = []
    for node in graph.get("nodes") or []:
        next_node = dict(node)
        if next_node.get("kind") == "ToolProfile":
            bundle = by_profile.get(str(next_node.get("profileId") or ""))
            if bundle is not None:
                next_node["capabilityBundle"] = _bundle_selection_summary(bundle)
                next_node["capabilityId"] = bundle["capabilityId"]
        nodes.append(next_node)
    return {**graph, "nodes": nodes}


def _capability_bundle_gate(results: list[dict[str, Any]]) -> dict[str, Any]:
    blocked: list[dict[str, Any]] = []
    for result in results:
        if result.get("agentSelectable") or not isinstance(result.get("bundle"), dict):
            continue
        blocked_tool = {
            "toolId": str(result["tool"].get("id") or result["tool"].get("toolId") or ""),
            "toolRevisionId": str(result["bundle"].get("toolRevisionId") or ""),
            "capabilityId": str(result["bundle"].get("capabilityId") or ""),
            "blockedReasons": list(result.get("reasons") or []),
            "nextAction": _bundle_next_action(list(result.get("reasons") or [])),
        }
        admission_evidence = result["bundle"].get("admissionEvidence")
        if admission_evidence:
            blocked_tool["admissionEvidence"] = admission_evidence
        blocked.append(blocked_tool)
    selectable = [result for result in results if result.get("agentSelectable")]
    return {
        "capabilityBundleVersion": CAPABILITY_BUNDLE_VERSION,
        "total": len(results),
        "selectable": len(selectable),
        "blocked": len(blocked),
        "blockedTools": blocked,
    }


def _bundle_selection_summary(bundle: dict[str, Any]) -> dict[str, Any]:
    return {
        "capabilityBundleVersion": bundle.get("capabilityBundleVersion"),
        "capabilityId": bundle.get("capabilityId"),
        "toolRevisionId": bundle.get("toolRevisionId"),
        "source": bundle.get("source"),
        "version": bundle.get("version"),
        "risk": bundle.get("risk"),
        "permissions": bundle.get("permissions"),
        "approval": bundle.get("approval"),
        "validationEvidence": bundle.get("validationEvidence"),
        "selectionSummary": bundle.get("selectionSummary"),
    }


def _bundle_rule_template(*, tool: dict[str, Any], profile: ToolProfile | None) -> dict[str, Any]:
    if profile is not None:
        return dict(profile.rule_template)
    template = tool.get("ruleTemplate") if isinstance(tool.get("ruleTemplate"), dict) else {}
    return dict(template)


def _bundle_ports(value: Any) -> list[dict[str, Any]]:
    ports: list[dict[str, Any]] = []
    for item in value or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        port = {
            "name": name,
            "type": str(item.get("type") or "").strip(),
            "kind": str(item.get("kind") or "").strip(),
            "mimeType": str(item.get("mimeType") or "").strip(),
            "data": str(item.get("data") or "").strip(),
            "format": str(item.get("format") or "").strip(),
            "operation": str(item.get("operation") or "").strip(),
            "resource": str(item.get("resource") or "").strip(),
            "required": bool(item.get("required")),
        }
        path = str(item.get("path") or "").strip()
        if path:
            port["path"] = path
        ports.append(port)
    return ports


def _ports_have_schema(ports: list[dict[str, Any]]) -> bool:
    return all(port.get("name") and any(port.get(key) for key in ("type", "kind", "data", "format", "mimeType")) for port in ports)


def _bundle_parameters(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _environment_lock(*, rule_template: dict[str, Any], package_spec: str, target_platform: str) -> dict[str, Any]:
    environment = rule_template.get("environment") if isinstance(rule_template.get("environment"), dict) else {}
    conda = environment.get("conda") if isinstance(environment.get("conda"), dict) else {}
    dependencies = [
        str(item).replace("{packageSpec}", package_spec).strip()
        for item in conda.get("dependencies") or []
        if str(item or "").strip()
    ]
    lock = {
        "manager": "conda" if conda else "",
        "targetPlatform": target_platform,
        "channels": [str(item).strip() for item in conda.get("channels") or [] if str(item or "").strip()],
        "dependencies": dependencies,
    }
    if package_spec:
        lock["packageSpec"] = package_spec
    return lock


def _validation_evidence(tool: dict[str, Any], *, rule_template: dict[str, Any]) -> dict[str, Any]:
    contract = tool.get("toolContract") if isinstance(tool.get("toolContract"), dict) else {}
    validation = contract.get("validation") if isinstance(contract.get("validation"), dict) else {}
    contract_status = tool.get("contractStatus") if isinstance(tool.get("contractStatus"), dict) else {}
    validation_summary = tool.get("validationSummary") if isinstance(tool.get("validationSummary"), dict) else {}
    stages = []
    for stage in ("dryRun", "smokeRun", "outputValidation"):
        raw = validation.get(stage) if isinstance(validation.get(stage), dict) else contract_status.get(stage)
        status = raw if isinstance(raw, dict) else {}
        stages.append(
            {
                "id": stage,
                "status": str(status.get("status") or "").strip(),
                "code": str(status.get("code") or "").strip(),
                "checkedAt": str(status.get("checkedAt") or "").strip(),
                "logPath": str(status.get("logPath") or "").strip(),
            }
        )
    latest_status = str(validation_summary.get("latestStatus") or "").strip()
    passed = latest_status == "passed" or all(stage["status"] == "passed" for stage in stages)
    return {
        "status": "passed" if passed else latest_status or "missing",
        "validationResultId": str(
            validation_summary.get("latestResultId")
            or validation_summary.get("validationResultId")
            or tool.get("validationResultId")
            or ""
        ).strip(),
        "evidenceId": str(validation_summary.get("evidenceId") or tool.get("evidenceId") or "").strip(),
        "jobId": str(validation_summary.get("latestJobId") or "").strip(),
        "checkedAt": str(validation_summary.get("updatedAt") or "").strip(),
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


def _risk_summary(*, rule_template: dict[str, Any]) -> dict[str, Any]:
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


def _permissions_summary(*, rule_template: dict[str, Any]) -> dict[str, Any]:
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
    *,
    tool: dict[str, Any],
    risk: dict[str, Any],
    permissions: dict[str, Any],
    resource_admission: dict[str, Any] | None,
) -> dict[str, Any]:
    policy = tool.get("capabilityApproval") if isinstance(tool.get("capabilityApproval"), dict) else {}
    risk_level = str(risk.get("level") or "low").strip()
    requires_approval = (
        risk_level in {"medium", "high"}
        or bool(permissions.get("network"))
        or bool(permissions.get("databases"))
    )
    resource_ready = bool(resource_admission and resource_admission.get("complete"))
    approved = bool(policy.get("approved")) if requires_approval else True
    if requires_approval and not approved and resource_ready:
        approved = True
    reason = str(policy.get("reason") or "").strip()
    policy_version = str(policy.get("policyVersion") or "").strip()
    if not reason:
        if not requires_approval:
            reason = "low-risk-auto-approved"
        elif resource_ready:
            reason = "validated-database-resource"
        elif resource_admission and resource_admission.get("missingResources"):
            reason = "database-resource-required"
        else:
            reason = "approval-required"
    if not policy_version and requires_approval and resource_ready:
        policy_version = "capability-admission-v1"
    return {
        "required": requires_approval,
        "approved": approved,
        "policyVersion": policy_version,
        "reason": reason,
    }


def _admission_evidence(resource_admission: dict[str, Any] | None) -> dict[str, Any]:
    if not resource_admission:
        return {}
    return {
        "policyVersion": "capability-admission-v1",
        "databaseResources": list(resource_admission.get("resources") or []),
        "missingResources": list(resource_admission.get("missingResources") or []),
    }


def _database_resource_admission(
    *,
    rule_template: dict[str, Any],
    databases: list[dict[str, Any]] | None,
) -> dict[str, Any] | None:
    resource_specs = _database_resource_specs(rule_template)
    if not resource_specs:
        return None
    if databases is None:
        return None
    resources: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []
    for resource_key, spec in resource_specs.items():
        candidates = [
            _database_evidence(database, resource_key=resource_key, spec=spec)
            for database in databases
            if _database_matches_resource_spec(database, spec)
        ]
        available = [candidate for candidate in candidates if candidate["status"] == "available"]
        summary = {
            "resourceKey": resource_key,
            "configKey": str(spec.get("configKey") or resource_key).strip(),
            "required": bool(spec.get("required", True)),
            "acceptedTemplates": [str(item).strip() for item in spec.get("acceptedTemplates") or [] if str(item).strip()],
            "acceptedCapabilities": [
                str(item).strip() for item in spec.get("acceptedCapabilities") or [] if str(item).strip()
            ],
            "candidateCount": len(candidates),
            "availableCount": len(available),
            "databaseIds": [candidate["databaseId"] for candidate in available],
            "databases": available,
        }
        resources.append(summary)
        if summary["required"] and not available:
            missing.append(
                {
                    "resourceKey": resource_key,
                    "configKey": summary["configKey"],
                    "acceptedTemplates": summary["acceptedTemplates"],
                    "acceptedCapabilities": summary["acceptedCapabilities"],
                    "nextAction": "add-database",
                }
            )
    return {
        "complete": not missing,
        "resources": resources,
        "missingResources": missing,
    }


def _database_resource_specs(rule_template: dict[str, Any]) -> dict[str, dict[str, Any]]:
    resources = rule_template.get("resources") if isinstance(rule_template.get("resources"), dict) else {}
    return {
        str(key): dict(value)
        for key, value in resources.items()
        if isinstance(value, dict) and str(value.get("type") or "") == "database"
    }


def _database_matches_resource_spec(database: dict[str, Any], spec: dict[str, Any]) -> bool:
    metadata = database.get("metadata") if isinstance(database.get("metadata"), dict) else {}
    template_id = str(metadata.get("templateId") or "").strip().lower()
    accepted_templates = [str(item).strip().lower() for item in spec.get("acceptedTemplates") or [] if str(item).strip()]
    if accepted_templates and template_id not in accepted_templates:
        return False
    accepted_capabilities = [str(item).strip() for item in spec.get("acceptedCapabilities") or [] if str(item).strip()]
    if accepted_capabilities:
        capabilities = [str(item).strip() for item in metadata.get("capabilities") or [] if str(item).strip()]
        if not any(capability in capabilities for capability in accepted_capabilities):
            return False
    return bool(template_id or not accepted_templates)


def _database_evidence(database: dict[str, Any], *, resource_key: str, spec: dict[str, Any]) -> dict[str, Any]:
    metadata = database.get("metadata") if isinstance(database.get("metadata"), dict) else {}
    evidence = {
        "resourceKey": resource_key,
        "configKey": str(spec.get("configKey") or resource_key).strip(),
        "databaseId": str(database.get("id") or database.get("databaseId") or "").strip(),
        "name": str(database.get("name") or "").strip(),
        "templateId": str(metadata.get("templateId") or "").strip(),
        "status": str(database.get("status") or "").strip(),
        "version": str(database.get("version") or "").strip(),
        "lastCheckedAt": str(database.get("lastCheckedAt") or database.get("last_checked_at") or "").strip(),
        "pathMode": str(database.get("pathMode") or metadata.get("pathMode") or "").strip(),
    }
    read_lengths = metadata.get("availableReadLengths")
    if isinstance(read_lengths, list):
        evidence["availableReadLengths"] = [int(item) for item in read_lengths if str(item).isdigit()]
    return evidence


def _matching_profile(tool: dict[str, Any], profiles: tuple[ToolProfile, ...]) -> ToolProfile | None:
    draft = tool.get("ruleSpecDraft") if isinstance(tool.get("ruleSpecDraft"), dict) else {}
    lock = draft.get("lock") if isinstance(draft.get("lock"), dict) else {}
    locked_profile_id = _normalize_name(lock.get("profileId"))
    if locked_profile_id:
        for profile in profiles:
            if _normalize_name(profile.profile_id) == locked_profile_id:
                return profile
    names = {
        _normalize_name(value)
        for value in (tool.get("name"), tool.get("id"), tool.get("toolId"), tool.get("toolRevisionId"))
        if _normalize_name(value)
    }
    for profile in profiles:
        profile_names = {_normalize_name(value) for value in (profile.profile_id, *profile.tool_names)}
        if names & profile_names:
            return profile
    return None


def _capability_id(*, pack_id: str, profile_id: str, tool_revision_id: str) -> str:
    revision = tool_revision_id.replace(":", "_").replace("/", "_")
    return f"{CAPABILITY_BUNDLE_VERSION}:{pack_id}:{profile_id}:{revision}"


def _source_from_package_spec(package_spec: str) -> str:
    return package_spec.split("::", 1)[0] if "::" in package_spec else ""


def _version_from_package_spec(package_spec: str) -> str:
    text = package_spec.rsplit("::", 1)[-1]
    if "==" in text:
        return text.split("==", 1)[1].strip()
    if "=" in text:
        return text.split("=", 1)[1].strip()
    return ""


def _tool_name_from_identifier(value: Any) -> str:
    text = str(value or "").strip()
    if "::" in text:
        text = text.rsplit("::", 1)[-1]
    if "@" in text:
        text = text.split("@", 1)[0]
    if "#" in text:
        text = text.split("#", 1)[0]
    return text


def _normalize_name(value: Any) -> str:
    return re.sub(r"[^a-z0-9.+-]+", "-", _tool_name_from_identifier(value).strip().lower()).strip("-")


def _bundle_next_action(reasons: list[str]) -> str:
    if not reasons:
        return "add-step"
    if any(reason in reasons for reason in ("VALIDATION_EVIDENCE_REQUIRED", "VALIDATION_RESULT_ID_REQUIRED", "VALIDATION_EVIDENCE_ID_REQUIRED")):
        return "run-validation"
    if "DATABASE_RESOURCE_REQUIRED" in reasons:
        return "add-database"
    if "CAPABILITY_APPROVAL_REQUIRED" in reasons:
        return "request-approval"
    if any(reason.startswith("CAPABILITY_") or reason in {"SMOKE_FIXTURE_REQUIRED", "EXPECTED_ARTIFACT_REQUIRED"} for reason in reasons):
        return "complete-capability-bundle"
    if "ENVIRONMENT_LOCK_REQUIRED" in reasons or "ENVIRONMENT_LOCK_UNRESOLVED" in reasons:
        return "lock-environment"
    return "prepare-tool"


def _unique_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        unique.append(text)
    return unique


def _target_summary(target_acceptance: dict[str, Any]) -> dict[str, Any]:
    targets = target_acceptance.get("targets") if isinstance(target_acceptance.get("targets"), dict) else {}
    return {
        "complete": bool(target_acceptance.get("complete")),
        "blockedTargets": list(target_acceptance.get("blockedTargets") or []),
        "targets": targets,
    }
