"""Acceptance metrics for the Bio Agent Tool Catalog v1 target."""

from __future__ import annotations

from typing import Any

from apps.api.tool_candidate_catalog import search_tool_candidates
from apps.api.tool_profile_external_refs import profile_snakemake_wrappers
from apps.api.tool_profile_catalog import catalog_tool_profiles
from apps.api.tool_profile_model import ToolProfile
from apps.api.tool_profile_prepare_payload import profile_prepare_payload
from apps.api.tool_profile_registry import TOOL_PROFILES
from apps.api.tool_profile_semantics import enrich_rule_template_semantics
from apps.api.tool_validation_plan import workflow_ready_validation_plan


CATALOG_TARGETS = {
    "discovered": 500,
    "addableDraft": 100,
    "snakemakeRenderable": 30,
    "workflowReady": 30,
    "productionEnabled": 10,
}


def bio_agent_catalog_target_acceptance(
    *,
    target_platform: str = "linux-64",
    registered_tools: list[dict[str, Any]] | None = None,
    latest_prepare_jobs_by_tool_id: dict[str, Any] | None = None,
    catalog: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized_target_platform = str(target_platform or "linux-64").strip() or "linux-64"
    registered = registered_tools or []
    registered_counts = _registered_tool_counts(registered)
    catalog_payload = catalog if isinstance(catalog, dict) else search_tool_candidates(
        "",
        target_platform=normalized_target_platform,
        page=1,
        page_size=100,
    )
    profile_catalog = catalog_tool_profiles(query="", page=1, page_size=100)
    quality_counts = _record_value(catalog_payload.get("qualityCounts"))
    addable_counts = _record_value(catalog_payload.get("addableDraftCounts"))
    targets = {
        "discovered": _target_result(actual=_count_value(quality_counts.get("discovered")), target=CATALOG_TARGETS["discovered"]),
        "addableDraft": _target_result(actual=_count_value(addable_counts.get("total")), target=CATALOG_TARGETS["addableDraft"]),
        "snakemakeRenderable": _target_result(
            actual=max(
                _count_value(quality_counts.get("draftRunnable")),
                _contract_state_count(profile_catalog, "SnakemakeRenderable"),
            ),
            target=CATALOG_TARGETS["snakemakeRenderable"],
        ),
        "workflowReady": _target_result(
            actual=max(_count_value(quality_counts.get("workflowReady")), registered_counts["workflowReady"]),
            target=CATALOG_TARGETS["workflowReady"],
        ),
        "productionEnabled": _target_result(
            actual=max(_count_value(quality_counts.get("productionEnabled")), registered_counts["productionEnabled"]),
            target=CATALOG_TARGETS["productionEnabled"],
        ),
    }
    blocked_targets = [name for name, result in targets.items() if result["passed"] is not True]
    validation_queue = _validation_queue(
        registered_tools=registered,
        remaining=targets["workflowReady"]["remaining"],
        latest_prepare_jobs_by_tool_id=latest_prepare_jobs_by_tool_id or {},
        catalog_items=_payload_items(catalog_payload),
    )
    production_queue = _production_queue(
        registered_tools=registered,
        remaining=targets["productionEnabled"]["remaining"],
    )
    return {
        "targetName": "Bio Agent Tool Catalog & Recommendation v1",
        "targetPlatform": normalized_target_platform,
        "complete": not blocked_targets,
        "blockedTargets": blocked_targets,
        "nextActions": [_next_action(name, targets[name]) for name in blocked_targets],
        "validationQueue": validation_queue,
        "productionQueue": production_queue,
        "targets": targets,
        "catalog": {
            "total": _count_value(catalog_payload.get("total")),
            "sourceCounts": _record_value(catalog_payload.get("sourceCounts")),
            "addableDraftCounts": addable_counts,
            "qualityCounts": quality_counts,
            "registeredToolCounts": registered_counts,
        },
    }


def _target_result(*, actual: int, target: int) -> dict[str, Any]:
    return {
        "target": target,
        "actual": actual,
        "passed": actual >= target,
        "remaining": max(0, target - actual),
    }


def _next_action(target_name: str, result: dict[str, Any]) -> dict[str, Any]:
    remaining = _count_value(result.get("remaining"))
    if target_name == "workflowReady":
        return {
            "target": target_name,
            "remaining": remaining,
            "action": "prepare-and-validate-tool-contracts",
            "requiredState": "WorkflowReady",
            "evidence": "Snakemake dry-run, smoke run, and output validation evidence",
        }
    if target_name == "productionEnabled":
        return {
            "target": target_name,
            "remaining": remaining,
            "action": "promote-workflow-ready-tools-with-production-evidence",
            "requiredState": "ProductionEnabled",
            "evidence": "Scoped production attestation for tool revision, platform, environment, data scope, and policy",
        }
    return {
        "target": target_name,
        "remaining": remaining,
        "action": "expand-catalog-source-coverage",
        "requiredState": target_name,
        "evidence": "Catalog source counts and candidate quality counts",
    }


def _contract_state_count(catalog: dict[str, Any], state: str) -> int:
    items = catalog.get("items")
    if not isinstance(items, list):
        return 0
    return sum(1 for item in items if isinstance(item, dict) and item.get("contractState") == state)


def _payload_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    items = payload.get("items") if isinstance(payload, dict) else None
    return [item for item in items if isinstance(item, dict)] if isinstance(items, list) else []


def _registered_tool_counts(tools: list[dict[str, Any]]) -> dict[str, int]:
    valid_tools = [tool for tool in tools if isinstance(tool, dict)]
    return {
        "total": len(valid_tools),
        "workflowReady": sum(1 for tool in valid_tools if _registered_tool_workflow_ready(tool)),
        "productionEnabled": sum(1 for tool in valid_tools if _registered_tool_production_enabled(tool)),
    }


def _production_queue(*, registered_tools: list[dict[str, Any]], remaining: int) -> dict[str, Any]:
    candidates = [
        _production_queue_item(tool)
        for tool in registered_tools
        if isinstance(tool, dict) and _registered_tool_workflow_ready(tool) and not _registered_tool_production_enabled(tool)
    ]
    candidates.sort(key=lambda item: str(item["toolId"]))
    bounded_remaining = max(0, int(remaining or 0))
    return {
        "target": "productionEnabled",
        "requiredState": "ProductionEnabled",
        "remaining": bounded_remaining,
        "available": len(candidates),
        "items": candidates[:bounded_remaining],
    }


def _production_queue_item(tool: dict[str, Any]) -> dict[str, Any]:
    contract = tool.get("toolContract") if isinstance(tool.get("toolContract"), dict) else {}
    tool_id = str(tool.get("id") or tool.get("toolId") or tool.get("name") or "").strip()
    return {
        "toolId": tool_id,
        "toolRevisionId": str(tool.get("toolRevisionId") or contract.get("toolRevisionId") or "").strip(),
        "toolName": str(tool.get("name") or _tool_name_from_identifier(tool_id)).strip(),
        "currentState": str(contract.get("state") or "WorkflowReady"),
        "requiredState": "ProductionEnabled",
        "action": "submit-production-evidence",
        "executionGate": _production_execution_gate(contract),
        "productionPlan": _production_plan(),
    }


def _production_execution_gate(contract: dict[str, Any]) -> dict[str, Any]:
    return {
        "currentState": str(contract.get("state") or "WorkflowReady"),
        "requiredState": "ProductionEnabled",
        "canPromote": False,
        "nextAction": "submit-production-evidence",
        "reason": "PRODUCTION_EVIDENCE_REQUIRED",
        "sourceOfTruth": "registeredTool.toolContract",
    }


def _production_plan() -> dict[str, Any]:
    return {
        "planVersion": "tool-production-plan-v1",
        "requiredState": "ProductionEnabled",
        "submit": {
            "method": "POST",
            "pathTemplate": "/api/v1/tools/{toolId}/production",
            "payloadRef": "productionEvidence",
        },
        "acceptedEvidenceTypes": ["real-data-acceptance"],
        "requiredEvidenceFields": ["runId", "evidenceType", "artifactName"],
        "scopedAttestation": [
            "toolRevisionId",
            "targetPlatform",
            "environmentLock",
            "databaseId",
            "inputScope",
            "artifactDigest",
            "policyVersion",
        ],
        "readinessBoundary": "ProductionEnabled is granted only after real run evidence validates artifacts and scoped production requirements.",
    }


def validation_queue_tool_ids(
    *,
    registered_tools: list[dict[str, Any]] | None = None,
    catalog_items: list[dict[str, Any]] | None = None,
) -> list[str]:
    workflow_ready_names = _workflow_ready_tool_names(registered_tools or [])
    ids: list[str] = []
    for profile in TOOL_PROFILES:
        if _profile_registered_workflow_ready(profile, workflow_ready_names):
            continue
        prepare_payload = profile_prepare_payload(profile)
        tool_id = str(prepare_payload.get("id") or "").strip()
        if tool_id and tool_id not in ids:
            ids.append(tool_id)
    for item in catalog_items or []:
        if not _catalog_candidate_needs_validation(item, workflow_ready_names):
            continue
        prepare_payload = item.get("preparePayload") if isinstance(item.get("preparePayload"), dict) else {}
        tool_id = str(prepare_payload.get("id") or "").strip()
        if tool_id and tool_id not in ids:
            ids.append(tool_id)
    return ids


def _validation_queue(
    *,
    registered_tools: list[dict[str, Any]],
    remaining: int,
    latest_prepare_jobs_by_tool_id: dict[str, Any],
    catalog_items: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    workflow_ready_names = _workflow_ready_tool_names(registered_tools)
    candidates = [
        _validation_queue_item(profile, latest_prepare_jobs_by_tool_id=latest_prepare_jobs_by_tool_id)
        for profile in TOOL_PROFILES
        if not _profile_registered_workflow_ready(profile, workflow_ready_names)
    ]
    candidates.extend(
        _catalog_validation_queue_item(item, latest_prepare_jobs_by_tool_id=latest_prepare_jobs_by_tool_id)
        for item in catalog_items or []
        if _catalog_candidate_needs_validation(item, workflow_ready_names)
    )
    candidates.sort(key=lambda item: (-_count_value(item["priority"]["score"]), str(item["candidateId"])))
    bounded_remaining = max(0, int(remaining or 0))
    return {
        "target": "workflowReady",
        "requiredState": "WorkflowReady",
        "remaining": bounded_remaining,
        "available": len(candidates),
        "items": candidates[:bounded_remaining],
    }


def _catalog_candidate_needs_validation(item: dict[str, Any], workflow_ready_names: set[str]) -> bool:
    if str(item.get("candidateKind") or "") == "h2ometa-tool-profile":
        return False
    if _catalog_candidate_contract_state(item) != "SnakemakeRenderable":
        return False
    prepare_payload = item.get("preparePayload")
    if not isinstance(prepare_payload, dict):
        return False
    return not any(_normalized_tool_name(name) in workflow_ready_names for name in _catalog_candidate_tool_names(item))


def _catalog_candidate_contract_state(item: dict[str, Any]) -> str:
    state = str(item.get("contractState") or "").strip()
    if state == "SnakemakeRenderable":
        return state
    if str(item.get("qualityTier") or "").strip() == "draft-runnable":
        return "SnakemakeRenderable"
    if state:
        return state
    return "Discovered"


def _catalog_candidate_tool_names(item: dict[str, Any]) -> list[str]:
    names: list[str] = []
    raw_names = item.get("toolNames")
    if isinstance(raw_names, list):
        names.extend(str(value).strip() for value in raw_names if str(value or "").strip())
    prepare_payload = item.get("preparePayload") if isinstance(item.get("preparePayload"), dict) else {}
    for value in (
        item.get("name"),
        item.get("toolName"),
        item.get("candidateId"),
        prepare_payload.get("name"),
        prepare_payload.get("id"),
    ):
        name = _tool_name_from_identifier(value)
        if name:
            names.append(name)
    return _unique_strings(names)


def _catalog_validation_queue_item(item: dict[str, Any], *, latest_prepare_jobs_by_tool_id: dict[str, Any]) -> dict[str, Any]:
    prepare_payload = dict(item.get("preparePayload") or {})
    evidence = _catalog_validation_evidence(item=item, prepare_payload=prepare_payload)
    priority = _validation_priority(evidence=evidence, prepare_payload=prepare_payload)
    candidate_id = str(item.get("candidateId") or prepare_payload.get("id") or "").strip()
    queue_item = {
        "candidateId": candidate_id,
        "candidateKind": str(item.get("candidateKind") or "tool-candidate"),
        "toolNames": _catalog_candidate_tool_names(item),
        "currentState": _catalog_candidate_contract_state(item),
        "requiredState": "WorkflowReady",
        "action": "prepare-tool",
        "priority": priority,
        "evidence": evidence,
        "executionGate": _validation_execution_gate(),
        "validationPlan": _validation_plan(),
        "preparePayload": prepare_payload,
    }
    source_ref = item.get("sourceRef")
    if isinstance(source_ref, dict):
        queue_item["sourceRef"] = dict(source_ref)
    quality_tier = str(item.get("qualityTier") or "").strip()
    if quality_tier:
        queue_item["qualityTier"] = quality_tier
    latest_prepare_job = _safe_latest_prepare_job(latest_prepare_jobs_by_tool_id.get(str(prepare_payload.get("id") or "")))
    if latest_prepare_job is not None:
        queue_item["latestPrepareJob"] = latest_prepare_job
    if _active_prepare_job(latest_prepare_job):
        queue_item["action"] = "wait-for-tool-validation"
        queue_item["executionGate"] = _active_prepare_job_execution_gate(latest_prepare_job)
        queue_item.pop("preparePayload", None)
    return queue_item


def _validation_queue_item(profile: ToolProfile, *, latest_prepare_jobs_by_tool_id: dict[str, Any]) -> dict[str, Any]:
    prepare_payload = profile_prepare_payload(profile)
    evidence = _validation_evidence(profile=profile, prepare_payload=prepare_payload)
    priority = _validation_priority(evidence=evidence, prepare_payload=prepare_payload)
    item = {
        "candidateId": f"h2ometa-tool-profile::{profile.profile_id}",
        "candidateKind": "h2ometa-tool-profile",
        "profileId": profile.profile_id,
        "profileVersion": profile.version,
        "toolNames": list(profile.tool_names),
        "currentState": "SnakemakeRenderable",
        "requiredState": "WorkflowReady",
        "action": "prepare-tool",
        "priority": priority,
        "evidence": evidence,
        "executionGate": _validation_execution_gate(),
        "validationPlan": _validation_plan(),
        "preparePayload": prepare_payload,
    }
    latest_prepare_job = _safe_latest_prepare_job(latest_prepare_jobs_by_tool_id.get(str(prepare_payload.get("id") or "")))
    if latest_prepare_job is not None:
        item["latestPrepareJob"] = latest_prepare_job
    if _active_prepare_job(latest_prepare_job):
        item["action"] = "wait-for-tool-validation"
        item["executionGate"] = _active_prepare_job_execution_gate(latest_prepare_job)
        item.pop("preparePayload", None)
    return item


def _safe_latest_prepare_job(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    status = str(value.get("status") or "").strip()
    succeeded = status == "succeeded"
    result_state = str(value.get("resultState") or "").strip() if succeeded else ""
    item = {
        "jobId": str(value.get("jobId") or "").strip(),
        "toolId": str(value.get("toolId") or "").strip(),
        "status": status,
        "stage": str(value.get("stage") or "").strip(),
        "message": str(value.get("message") or "").strip(),
        "errorCode": str(value.get("errorCode") or "").strip(),
        "updatedAt": str(value.get("updatedAt") or "").strip(),
        "resultState": result_state,
        "workflowReady": succeeded and bool(value.get("workflowReady")),
        "productionEnabled": succeeded and bool(value.get("productionEnabled")),
    }
    for key in ("createdAt", "startedAt", "finishedAt", "cancelledAt"):
        if value.get(key) is not None:
            item[key] = value.get(key)
    return item


def _validation_execution_gate() -> dict[str, Any]:
    return {
        "currentState": "SnakemakeRenderable",
        "requiredState": "WorkflowReady",
        "canAddStep": False,
        "nextAction": "prepare-tool",
        "reason": "WORKFLOW_TOOL_NOT_READY",
        "sourceOfTruth": "registeredTool.toolContract",
    }


def _active_prepare_job(value: dict[str, Any] | None) -> bool:
    if not isinstance(value, dict):
        return False
    return str(value.get("status") or "").strip() in {"queued", "running"}


def _active_prepare_job_execution_gate(latest_prepare_job: dict[str, Any]) -> dict[str, Any]:
    return {
        "currentState": "SnakemakeRenderable",
        "requiredState": "WorkflowReady",
        "canAddStep": False,
        "nextAction": "wait-for-tool-validation",
        "reason": "TOOL_PREPARE_JOB_ACTIVE",
        "sourceOfTruth": "toolPrepareJob",
        "jobId": str(latest_prepare_job.get("jobId") or ""),
        "toolId": str(latest_prepare_job.get("toolId") or ""),
    }


def _validation_plan() -> dict[str, Any]:
    return workflow_ready_validation_plan()


def _validation_evidence(*, profile: ToolProfile, prepare_payload: dict[str, Any]) -> dict[str, Any]:
    wrappers = profile_snakemake_wrappers(profile)
    semantic = _semantic_port_summary(prepare_payload)
    return {
        "snakemakeWrapperCount": len(wrappers),
        "snakemakeWrapperPaths": [str(item.get("wrapperPath") or "") for item in wrappers if str(item.get("wrapperPath") or "")],
        **_wrapper_contract_hint_summary(wrappers),
        **semantic,
        **_required_resource_summary(prepare_payload),
    }


def _catalog_validation_evidence(*, item: dict[str, Any], prepare_payload: dict[str, Any]) -> dict[str, Any]:
    wrapper_paths: list[str] = []
    wrappers = item.get("snakemakeWrappers")
    if isinstance(wrappers, list):
        wrapper_paths.extend(
            str(wrapper.get("wrapperPath") or "").strip()
            for wrapper in wrappers
            if isinstance(wrapper, dict) and str(wrapper.get("wrapperPath") or "").strip()
        )
    wrapper_path = str(item.get("wrapperPath") or "").strip()
    if wrapper_path:
        wrapper_paths.append(wrapper_path)
    wrapper_count = _count_value(item.get("snakemakeWrapperCount"))
    if wrapper_count <= 0:
        wrapper_count = len(wrapper_paths)
    return {
        "snakemakeWrapperCount": wrapper_count,
        "snakemakeWrapperPaths": _unique_strings(wrapper_paths),
        "wrapperContractHintCount": _count_value(item.get("wrapperContractHintCount")),
        "wrapperContractHintFields": _string_list(item.get("wrapperContractHintFields")),
        "wrapperCondaDependencies": _string_list(item.get("wrapperCondaDependencies")),
        **_semantic_port_summary(prepare_payload),
        **_required_resource_summary(prepare_payload),
    }


def _wrapper_contract_hint_summary(wrappers: list[dict[str, Any]]) -> dict[str, Any]:
    hint_count = 0
    fields: set[str] = set()
    dependencies: set[str] = set()
    for wrapper in wrappers:
        hints = wrapper.get("wrapperContractHints") if isinstance(wrapper, dict) else None
        if not isinstance(hints, dict) or not hints:
            continue
        hint_count += 1
        fields.update(_contract_hint_fields(hints))
        dependencies.update(_contract_hint_conda_dependencies(hints))
    return {
        "wrapperContractHintCount": hint_count,
        "wrapperContractHintFields": sorted(fields),
        "wrapperCondaDependencies": sorted(dependencies),
    }


def _contract_hint_fields(hints: dict[str, Any]) -> set[str]:
    return {
        key
        for key in ("name", "description", "url", "authors", "input", "output", "params", "notes", "environment")
        if hints.get(key)
    }


def _contract_hint_conda_dependencies(hints: dict[str, Any]) -> set[str]:
    environment = hints.get("environment") if isinstance(hints.get("environment"), dict) else {}
    conda = environment.get("conda") if isinstance(environment.get("conda"), dict) else {}
    dependencies = conda.get("dependencies") if isinstance(conda.get("dependencies"), list) else []
    return {str(dependency).strip() for dependency in dependencies if str(dependency or "").strip()}


def _validation_priority(*, evidence: dict[str, Any], prepare_payload: dict[str, Any]) -> dict[str, Any]:
    score = 0
    reasons: list[str] = []
    if _count_value(evidence.get("snakemakeWrapperCount")) > 0:
        score += 40
        reasons.append("snakemake-wrapper-evidence")
    if evidence.get("semanticPortFields"):
        score += 30
        reasons.append("edam-port-semantics")
    rule_draft = prepare_payload.get("ruleSpecDraft") if isinstance(prepare_payload.get("ruleSpecDraft"), dict) else {}
    if rule_draft.get("requiresUserCompletion") is False:
        score += 20
        reasons.append("ready-prepare-payload")
    if _semantic_format_count(evidence) >= 2:
        score += 10
        reasons.append("multi-port-format-coverage")
    if evidence.get("requiredResourceKeys"):
        reasons.append("required-resources-pending")
    else:
        score += 15
        reasons.append("self-contained-smoke")
    return {"score": score, "reasons": reasons}


def _semantic_port_summary(prepare_payload: dict[str, Any]) -> dict[str, Any]:
    template = prepare_payload.get("ruleTemplate") if isinstance(prepare_payload.get("ruleTemplate"), dict) else {}
    enriched = enrich_rule_template_semantics(template)
    fields: set[str] = set()
    data_terms: set[str] = set()
    format_terms: set[str] = set()
    for section in ("inputs", "outputs"):
        for port in enriched.get(section) or []:
            if not isinstance(port, dict):
                continue
            data = str(port.get("data") or port.get("edamData") or "").strip()
            format_id = str(port.get("format") or port.get("edamFormat") or "").strip()
            if data:
                fields.add("data")
                data_terms.add(data)
            if format_id:
                fields.add("format")
                format_terms.add(format_id)
    return {
        "semanticPortFields": sorted(fields),
        "semanticData": sorted(data_terms),
        "semanticFormats": sorted(format_terms),
    }


def _semantic_format_count(evidence: dict[str, Any]) -> int:
    formats = evidence.get("semanticFormats")
    return len(formats) if isinstance(formats, list) else 0


def _required_resource_summary(prepare_payload: dict[str, Any]) -> dict[str, Any]:
    template = prepare_payload.get("ruleTemplate") if isinstance(prepare_payload.get("ruleTemplate"), dict) else {}
    resources = template.get("resources") if isinstance(template.get("resources"), dict) else {}
    required_keys: list[str] = []
    for key, value in resources.items():
        if not isinstance(value, dict) or not value.get("required"):
            continue
        required_keys.append(str(key))
    return {"requiredResourceKeys": sorted(required_keys)}


def _workflow_ready_tool_names(tools: list[dict[str, Any]]) -> set[str]:
    names: set[str] = set()
    for tool in tools:
        if not isinstance(tool, dict) or not _registered_tool_workflow_ready(tool):
            continue
        for value in (tool.get("name"), tool.get("id"), tool.get("toolRevisionId")):
            normalized = _normalized_tool_name(_tool_name_from_identifier(value))
            if normalized:
                names.add(normalized)
    return names


def _profile_registered_workflow_ready(profile: ToolProfile, names: set[str]) -> bool:
    return any(_normalized_tool_name(name) in names for name in (profile.profile_id, *profile.tool_names))


def _registered_tool_workflow_ready(tool: dict[str, Any]) -> bool:
    contract = tool.get("toolContract") if isinstance(tool.get("toolContract"), dict) else {}
    state = str(contract.get("state") or "")
    return bool(contract.get("workflowReady")) or state in {"WorkflowReady", "ProductionEnabled"}


def _tool_name_from_identifier(value: Any) -> str:
    text = str(value or "").strip()
    if "::" in text:
        text = text.rsplit("::", 1)[-1]
    if "@" in text:
        text = text.split("@", 1)[0]
    return text


def _normalized_tool_name(value: Any) -> str:
    return str(value or "").strip().lower()


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return _unique_strings(str(item).strip() for item in value if str(item or "").strip())


def _unique_strings(values: Any) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        unique.append(text)
    return unique


def _registered_tool_production_enabled(tool: dict[str, Any]) -> bool:
    contract = tool.get("toolContract") if isinstance(tool.get("toolContract"), dict) else {}
    requirements = contract.get("requirements") if isinstance(contract.get("requirements"), dict) else {}
    return (
        bool(contract.get("productionEnabled"))
        or bool(requirements.get("productionEnabled"))
        or str(contract.get("state") or "") == "ProductionEnabled"
    )


def _record_value(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _count_value(value: Any) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0
