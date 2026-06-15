from __future__ import annotations

from typing import Any

from apps.api.bioconda_tool_index import bioconda_index_status, refresh_bioconda_index
from apps.api.bio_tool_pack_store import (
    disable_bio_tool_pack,
    enable_bio_tool_pack,
    import_bio_tool_pack_manifest,
    list_bio_tool_packs,
    review_bio_tool_pack_manifest,
)
from apps.api.capability_graph_service import DEFAULT_CAPABILITY_GRAPH_SERVICE
from apps.api.route_utils import run_sync, runtime_service
from apps.api.snakemake_wrappers import catalog_snakemake_wrappers
from apps.api.tool_candidate_catalog import search_tool_candidates
from apps.api.tool_candidate_target_acceptance import bio_agent_catalog_target_acceptance, validation_queue_tool_ids
from apps.api.tool_capabilities import search_tool_capabilities
from apps.api.tool_profile_catalog import catalog_tool_profiles
from apps.api.tool_registry_payload import registered_tools_from_runtime_payload


ACTIVE_PREPARE_JOB_STATUSES = ("queued", "running")
TERMINAL_PREPARE_JOB_STATUSES = ("cancelled", "exhausted", "failed", "succeeded", "waiting_resource")


async def search_tool_capabilities_from_request(
    *,
    q: str,
    target_platform: str,
    limit: int,
    page: int,
    page_size: int | None,
) -> dict[str, Any]:
    resolved_page_size = page_size or limit
    return await run_sync(
        lambda: search_tool_capabilities(
            q,
            target_platform=target_platform,
            limit=resolved_page_size,
            page=page,
            page_size=resolved_page_size,
        ),
    )


def _search_tool_candidates_with_tool_index(
    *,
    runtime: Any,
    query: str,
    target_platform: str,
    page: int,
    page_size: int,
) -> dict[str, Any]:
    local_catalog = search_tool_candidates(
        query,
        target_platform=target_platform,
        page=page,
        page_size=page_size,
    )
    bounded_page = max(1, int(page or 1))
    bounded_page_size = max(1, min(int(page_size or 50), 100))
    tool_index_page = _tool_index_page_from_runtime_payload(
        runtime.list_tool_index(
            query=query,
            limit=bounded_page_size,
            offset=(bounded_page - 1) * bounded_page_size,
        )
    )
    tool_index_quality_counts = _tool_index_quality_counts(
        runtime=runtime,
        query=query,
        discovered=_count_value(tool_index_page.get("total")),
    )
    return _merge_tool_index_into_candidate_catalog(
        local_catalog,
        tool_index_page=tool_index_page,
        tool_index_quality_counts=tool_index_quality_counts,
    )


def _tool_index_quality_counts(*, runtime: Any, query: str, discovered: int) -> dict[str, int]:
    return {
        "discovered": discovered,
        "draftRunnable": _tool_index_state_count(runtime, query=query, state="SnakemakeRenderable"),
        "workflowReady": _tool_index_state_count(runtime, query=query, state="WorkflowReady"),
        "productionEnabled": _tool_index_state_count(runtime, query=query, state="ProductionEnabled"),
    }


def _tool_index_state_count(runtime: Any, *, query: str, state: str) -> int:
    page = _tool_index_page_from_runtime_payload(
        runtime.list_tool_index(
            query=query,
            limit=1,
            offset=0,
            state=state,
        )
    )
    return _count_value(page.get("total"))


def _merge_tool_index_into_candidate_catalog(
    catalog: dict[str, Any],
    *,
    tool_index_page: dict[str, Any],
    tool_index_quality_counts: dict[str, int],
) -> dict[str, Any]:
    local_items = catalog.get("items") if isinstance(catalog.get("items"), list) else []
    index_items = tool_index_page.get("items") if isinstance(tool_index_page.get("items"), list) else []
    source_counts = _record_counts(catalog.get("sourceCounts"))
    addable_counts = _record_counts(catalog.get("addableDraftCounts"))
    quality_counts = _record_counts(catalog.get("qualityCounts"))
    index_total = _count_value(tool_index_page.get("total"))
    source_counts["registeredToolIndex"] = index_total
    addable_counts["registeredToolIndex"] = 0
    addable_counts["total"] = _count_value(addable_counts.get("total"))
    merged_quality_counts = {
        key: _count_value(quality_counts.get(key)) + _count_value(tool_index_quality_counts.get(key))
        for key in ("discovered", "draftRunnable", "workflowReady", "productionEnabled")
    }
    return {
        **catalog,
        "items": [_registered_tool_index_candidate(item) for item in index_items if isinstance(item, dict)] + local_items,
        "total": _count_value(catalog.get("total")) + index_total,
        "hasMore": bool(catalog.get("hasMore")) or bool(tool_index_page.get("hasMore")),
        "sourceCounts": source_counts,
        "addableDraftCounts": addable_counts,
        "qualityCounts": merged_quality_counts,
    }


def _tool_index_page_from_runtime_payload(payload: Any) -> dict[str, Any]:
    data = payload.get("data") if isinstance(payload, dict) else None
    page = data if isinstance(data, dict) else payload
    if not isinstance(page, dict):
        raise ValueError("Invalid tool index payload: expected an object")
    items = page.get("items") if isinstance(page.get("items"), list) else []
    return {
        "items": [item for item in items if isinstance(item, dict)],
        "total": _count_value(page.get("total")),
        "hasMore": bool(page.get("hasMore")),
    }


def _registered_tool_index_candidate(item: dict[str, Any]) -> dict[str, Any]:
    facets = item.get("facets") if isinstance(item.get("facets"), dict) else {}
    state = str(item.get("state") or facets.get("state") or "").strip()
    tool_id = str(item.get("toolId") or item.get("id") or "").strip()
    revision_id = str(item.get("latestStableRevisionId") or item.get("toolRevisionId") or "").strip()
    return {
        "candidateId": f"registered-tool-index::{tool_id}",
        "candidateKind": "registered-tool-index",
        "toolId": tool_id,
        "toolRevisionId": revision_id,
        "name": str(item.get("name") or tool_id).strip(),
        "source": str(item.get("source") or "").strip(),
        "packageSpec": str(item.get("packageSpec") or "").strip(),
        "sourceRef": {
            "type": "registered-tool-index",
            "toolId": tool_id,
            "toolRevisionId": revision_id,
        },
        "qualityTier": _tool_index_quality_tier(state),
        "toolContract": {
            "state": state,
            "workflowReady": state in {"WorkflowReady", "ProductionEnabled"},
            "productionEnabled": state == "ProductionEnabled",
        },
        "validationSummary": item.get("validationSummary") if isinstance(item.get("validationSummary"), dict) else {},
        "qualityScore": _count_value(item.get("qualityScore")),
        "upgradeAvailable": bool(item.get("upgradeAvailable")),
    }


def _tool_index_quality_tier(state: str) -> str:
    if state == "ProductionEnabled":
        return "production-enabled"
    if state == "WorkflowReady":
        return "workflow-ready"
    if state == "SnakemakeRenderable":
        return "draft-runnable"
    return "discovered"


def _record_counts(value: Any) -> dict[str, int]:
    return {str(key): _count_value(count) for key, count in value.items()} if isinstance(value, dict) else {}


def _count_value(value: Any) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


async def prepare_tool_validation_queue_from_request(*, target_platform: str, max_items: int) -> dict[str, Any]:
    runtime = runtime_service()
    return await run_sync(
        lambda: {
            "data": _prepare_tool_validation_queue(
                runtime=runtime,
                target_platform=target_platform,
                max_items=max_items,
            )
        },
    )


def _target_acceptance_with_runtime_state(*, runtime: Any, target_platform: str) -> dict[str, Any]:
    registered_tools = _registered_tools_with_tool_index(
        runtime=runtime,
        registered_tools=registered_tools_from_runtime_payload(runtime.list_tools()),
    )
    snapshot = _capability_snapshot_with_runtime_state(
        runtime=runtime,
        query="",
        target_platform=target_platform,
        page=1,
        page_size=100,
        registered_tools=registered_tools,
        include_acceptance=False,
    )
    return _target_acceptance_from_snapshot(
        runtime=runtime,
        target_platform=target_platform,
        registered_tools=registered_tools,
        snapshot=snapshot,
    )


async def get_capability_graph_snapshot_from_request(
    *,
    q: str,
    target_platform: str,
    page: int,
    page_size: int,
    agent_selectable_only: bool,
) -> dict[str, Any]:
    runtime = runtime_service()
    return await run_sync(
        lambda: {
            "data": _capability_snapshot_with_runtime_state(
                runtime=runtime,
                query=q,
                target_platform=target_platform,
                page=page,
                page_size=page_size,
                agent_selectable_only=agent_selectable_only,
            )
        }
    )


def _capability_snapshot_with_runtime_state(
    *,
    runtime: Any,
    query: str,
    target_platform: str,
    page: int,
    page_size: int,
    registered_tools: list[dict[str, Any]] | None = None,
    agent_selectable_only: bool = False,
    include_acceptance: bool = True,
) -> dict[str, Any]:
    registered = registered_tools
    if registered is None:
        registered = _registered_tools_with_tool_index(
            runtime=runtime,
            registered_tools=registered_tools_from_runtime_payload(runtime.list_tools()),
        )
    databases = _runtime_database_items(runtime)
    catalog = _search_tool_candidates_with_tool_index(
        runtime=runtime,
        query=query,
        target_platform=target_platform,
        page=page,
        page_size=page_size,
    )
    prepare_job_queue = (
        _prepare_job_queue_from_runtime_payload(runtime.list_tool_prepare_job_queue(status="", limit=50, offset=0))
        if include_acceptance
        else None
    )
    base_snapshot = DEFAULT_CAPABILITY_GRAPH_SERVICE.snapshot_from_runtime(
        runtime=runtime,
        query=query,
        target_platform=target_platform,
        page=page,
        page_size=page_size,
        registered_tools=registered,
        catalog=catalog,
        databases=databases,
        prepare_job_queue=prepare_job_queue,
        agent_selectable_only=agent_selectable_only,
    )
    if not include_acceptance:
        return base_snapshot
    target_acceptance = _target_acceptance_from_snapshot(
        runtime=runtime,
        target_platform=target_platform,
        registered_tools=registered,
        snapshot=base_snapshot,
        prepare_job_queue=prepare_job_queue,
    )
    return DEFAULT_CAPABILITY_GRAPH_SERVICE.snapshot_from_runtime(
        runtime=runtime,
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


def _target_acceptance_from_snapshot(
    *,
    runtime: Any,
    target_platform: str,
    registered_tools: list[dict[str, Any]],
    snapshot: dict[str, Any],
    prepare_job_queue: dict[str, Any] | None = None,
) -> dict[str, Any]:
    catalog = snapshot["catalog"]
    latest_prepare_jobs = _latest_prepare_jobs_from_runtime_payload(
        runtime.list_latest_tool_prepare_jobs(
            validation_queue_tool_ids(registered_tools=registered_tools, catalog_items=_catalog_items(catalog))
        )
    )
    acceptance = bio_agent_catalog_target_acceptance(
        target_platform=target_platform,
        registered_tools=registered_tools,
        latest_prepare_jobs_by_tool_id=latest_prepare_jobs,
        catalog=catalog,
    )
    acceptance["capabilityGraphSnapshot"] = _snapshot_summary(snapshot)
    acceptance["prepareJobQueue"] = prepare_job_queue or _prepare_job_queue_from_runtime_payload(
        runtime.list_tool_prepare_job_queue(status="", limit=50, offset=0)
    )
    return acceptance


def _snapshot_summary(snapshot: dict[str, Any]) -> dict[str, Any]:
    graph = snapshot.get("semanticGraph") if isinstance(snapshot.get("semanticGraph"), dict) else {}
    catalog = snapshot.get("catalog") if isinstance(snapshot.get("catalog"), dict) else {}
    return {
        "contractVersion": snapshot.get("contractVersion"),
        "profileCount": _count_value(snapshot.get("profileCount")),
        "packIds": list(snapshot.get("packIds") or []),
        "catalogTotal": _count_value(catalog.get("total")),
        "agentSelectableProfileIds": list(graph.get("agentSelectableProfileIds") or []),
        "selectionPolicy": dict(snapshot.get("selectionPolicy") or {}),
    }


def _catalog_items(catalog: dict[str, Any]) -> list[dict[str, Any]]:
    items = catalog.get("items") if isinstance(catalog, dict) else None
    return [item for item in items if isinstance(item, dict)] if isinstance(items, list) else []


def _runtime_database_items(runtime: Any) -> list[dict[str, Any]] | None:
    list_databases = getattr(runtime, "list_databases", None)
    if not callable(list_databases):
        return None
    payload = list_databases()
    data = payload.get("data") if isinstance(payload, dict) else None
    raw_items = data.get("items") if isinstance(data, dict) else payload
    if not isinstance(raw_items, list):
        return None
    return [dict(item) for item in raw_items if isinstance(item, dict)]


def _registered_tools_with_tool_index(*, runtime: Any, registered_tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    for tool in [*_workflow_ready_tools_from_tool_index(runtime), *registered_tools]:
        tool_id = str(tool.get("id") or tool.get("toolId") or "").strip()
        if tool_id:
            by_id[tool_id] = tool
    return list(by_id.values())


def _workflow_ready_tools_from_tool_index(runtime: Any) -> list[dict[str, Any]]:
    tools: list[dict[str, Any]] = []
    for state in ("WorkflowReady", "ProductionEnabled"):
        page = _tool_index_page_from_runtime_payload(
            runtime.list_tool_index(
                query="",
                limit=100,
                offset=0,
                state=state,
            )
        )
        items = page.get("items") if isinstance(page.get("items"), list) else []
        tools.extend(_tool_index_registered_tool(item) for item in items if isinstance(item, dict))
    return tools


def _tool_index_registered_tool(item: dict[str, Any]) -> dict[str, Any]:
    facets = item.get("facets") if isinstance(item.get("facets"), dict) else {}
    state = str(item.get("state") or facets.get("state") or "WorkflowReady").strip() or "WorkflowReady"
    tool_id = str(item.get("toolId") or item.get("id") or "").strip()
    package_spec = str(item.get("packageSpec") or "").strip()
    return {
        "id": tool_id,
        "toolId": tool_id,
        "toolRevisionId": str(item.get("latestStableRevisionId") or item.get("toolRevisionId") or "").strip(),
        "name": str(item.get("name") or _tool_name_from_identifier(tool_id)).strip(),
        "source": str(item.get("source") or (package_spec.split("::", 1)[0] if "::" in package_spec else "")).strip(),
        "packageSpec": package_spec,
        "version": _tool_version_from_package_spec(package_spec),
        "targetPlatform": str(facets.get("targetPlatform") or "linux-64"),
        "validationSummary": item.get("validationSummary") if isinstance(item.get("validationSummary"), dict) else {},
        "toolContract": {
            "state": state,
            "workflowReady": state in {"WorkflowReady", "ProductionEnabled"},
            "productionEnabled": state == "ProductionEnabled",
            "package": {
                "packageSpec": package_spec,
                "source": str(item.get("source") or (package_spec.split("::", 1)[0] if "::" in package_spec else "")).strip(),
                "version": _tool_version_from_package_spec(package_spec),
                "targetPlatform": str(facets.get("targetPlatform") or "linux-64"),
                "targetPlatformSupported": True,
            },
        },
    }


def _tool_name_from_identifier(value: Any) -> str:
    text = str(value or "").strip()
    if "::" in text:
        text = text.rsplit("::", 1)[-1]
    if "@" in text:
        text = text.split("@", 1)[0]
    return text


def _tool_version_from_package_spec(package_spec: str) -> str:
    text = str(package_spec or "").strip().rsplit("::", 1)[-1]
    if "==" in text:
        return text.split("==", 1)[1].strip()
    if "=" in text:
        return text.split("=", 1)[1].strip()
    return ""


def _prepare_tool_validation_queue(*, runtime: Any, target_platform: str, max_items: int) -> dict[str, Any]:
    requested = _bounded_validation_batch_size(max_items)
    acceptance = _target_acceptance_with_runtime_state(runtime=runtime, target_platform=target_platform)
    queue = acceptance.get("validationQueue") if isinstance(acceptance.get("validationQueue"), dict) else {}
    items = queue.get("items") if isinstance(queue.get("items"), list) else []
    candidate_items = [item for item in items if isinstance(item, dict)]
    latest_jobs_by_tool_id = _latest_prepare_jobs_for_queue_items(runtime, candidate_items)
    queued: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    seen_tool_ids: set[str] = set()
    considered: list[dict[str, Any]] = []
    for item in candidate_items:
        if len(queued) >= requested:
            break
        considered.append(item)
        tool_id = _queue_item_tool_id(item)
        if tool_id in seen_tool_ids:
            skipped.append(_skipped_validation_item(item, tool_id=tool_id, reason="DUPLICATE_TOOL_ID"))
            continue
        seen_tool_ids.add(tool_id)
        latest_prepare_job = latest_jobs_by_tool_id.get(tool_id) or _safe_item_latest_prepare_job(item)
        if _active_prepare_job(latest_prepare_job):
            skipped.append(
                _skipped_validation_item(
                    _queue_item_with_latest_prepare_job(item, latest_prepare_job),
                    tool_id=tool_id,
                    reason="ACTIVE_PREPARE_JOB",
                )
            )
            continue
        terminal_block_reason = _terminal_prepare_job_block_reason(latest_prepare_job)
        if terminal_block_reason:
            skipped.append(
                _skipped_validation_item(
                    _queue_item_with_latest_prepare_job(item, latest_prepare_job),
                    tool_id=tool_id,
                    reason=terminal_block_reason,
                )
            )
            continue
        prepare_payload = item.get("preparePayload") if isinstance(item.get("preparePayload"), dict) else None
        if prepare_payload is None:
            skipped.append(_skipped_validation_item(item, tool_id=tool_id, reason="MISSING_PREPARE_PAYLOAD"))
            continue
        queued.append(_queued_validation_item(item, runtime.create_tool_prepare_job(prepare_payload)))
    return {
        "targetPlatform": str(acceptance.get("targetPlatform") or target_platform),
        "requested": requested,
        "consideredCount": len(considered),
        "activeStatuses": list(ACTIVE_PREPARE_JOB_STATUSES),
        "terminalStatuses": list(TERMINAL_PREPARE_JOB_STATUSES),
        "queuedCount": len(queued),
        "skippedCount": len(skipped),
        "queued": queued,
        "skipped": skipped,
        "batchPlan": _validation_batch_plan(
            target_platform=str(acceptance.get("targetPlatform") or target_platform),
            requested=requested,
            queued=queued,
            skipped=skipped,
        ),
        "targets": acceptance.get("targets") if isinstance(acceptance.get("targets"), dict) else {},
        "remainingWorkflowReady": _remaining_workflow_ready(acceptance),
    }


def _bounded_validation_batch_size(value: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = 3
    return min(30, max(1, parsed))


def _validation_batch_plan(
    *,
    target_platform: str,
    requested: int,
    queued: list[dict[str, Any]],
    skipped: list[dict[str, Any]],
) -> dict[str, Any]:
    status = "queued" if queued else "blocked" if skipped else "empty"
    return {
        "planVersion": "tool-validation-batch-plan-v1",
        "status": status,
        "targetPlatform": target_platform,
        "requested": requested,
        "queuedCount": len(queued),
        "skippedCount": len(skipped),
        "jobIds": [str(item.get("jobId") or "") for item in queued if str(item.get("jobId") or "")],
        "poll": {
            "method": "GET",
            "path": "/api/v1/tools/prepare-jobs",
            "query": {"status": "", "limit": 50, "offset": 0},
        },
        "terminalStatuses": list(TERMINAL_PREPARE_JOB_STATUSES),
        "activeStatuses": list(ACTIVE_PREPARE_JOB_STATUSES),
    }


def _latest_prepare_jobs_for_queue_items(runtime: Any, items: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    tool_ids = [_queue_item_tool_id(item) for item in items]
    latest_jobs = _latest_prepare_jobs_from_runtime_payload(runtime.list_latest_tool_prepare_jobs(tool_ids))
    return {tool_id: _safe_prepare_job_summary(job) for tool_id, job in latest_jobs.items() if isinstance(job, dict)}


def _safe_prepare_job_summary(value: dict[str, Any]) -> dict[str, Any]:
    status = str(value.get("status") or "").strip()
    succeeded = status == "succeeded"
    return {
        "jobId": str(value.get("jobId") or "").strip(),
        "toolId": str(value.get("toolId") or "").strip(),
        "status": status,
        "stage": str(value.get("stage") or "").strip(),
        "message": str(value.get("message") or "").strip(),
        "errorCode": str(value.get("errorCode") or "").strip(),
        "updatedAt": str(value.get("updatedAt") or "").strip(),
        "resultState": str(value.get("resultState") or "").strip() if succeeded else "",
        "workflowReady": succeeded and bool(value.get("workflowReady")),
        "productionEnabled": succeeded and bool(value.get("productionEnabled")),
        "validationResultId": str(value.get("validationResultId") or "").strip(),
        "evidenceId": str(value.get("evidenceId") or "").strip(),
    }


def _queue_item_with_latest_prepare_job(item: dict[str, Any], latest_prepare_job: dict[str, Any]) -> dict[str, Any]:
    next_item = dict(item)
    next_item["latestPrepareJob"] = latest_prepare_job
    return next_item


def _safe_item_latest_prepare_job(item: dict[str, Any]) -> dict[str, Any] | None:
    value = item.get("latestPrepareJob")
    if not isinstance(value, dict):
        return None
    return _safe_prepare_job_summary(value)


def _active_prepare_job(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    return str(value.get("status") or "").strip() in ACTIVE_PREPARE_JOB_STATUSES


def _terminal_prepare_job_block_reason(value: Any) -> str:
    if not isinstance(value, dict):
        return ""
    status = str(value.get("status") or "").strip()
    if status == "waiting_resource":
        return "WAITING_RESOURCE"
    if status == "exhausted":
        return "PREPARE_JOB_EXHAUSTED"
    return ""


def _remaining_workflow_ready(acceptance: dict[str, Any]) -> int:
    targets = acceptance.get("targets") if isinstance(acceptance.get("targets"), dict) else {}
    workflow_ready = targets.get("workflowReady") if isinstance(targets.get("workflowReady"), dict) else {}
    try:
        return max(0, int(workflow_ready.get("remaining") or 0))
    except (TypeError, ValueError):
        return 0


def _queue_item_tool_id(item: dict[str, Any]) -> str:
    prepare_payload = item.get("preparePayload") if isinstance(item.get("preparePayload"), dict) else {}
    latest_prepare_job = item.get("latestPrepareJob") if isinstance(item.get("latestPrepareJob"), dict) else {}
    return str(prepare_payload.get("id") or latest_prepare_job.get("toolId") or "").strip()


def _skipped_validation_item(item: dict[str, Any], *, tool_id: str, reason: str) -> dict[str, Any]:
    skipped = {
        "candidateId": str(item.get("candidateId") or ""),
        "profileId": str(item.get("profileId") or ""),
        "toolId": tool_id,
        "reason": reason,
    }
    latest_prepare_job = item.get("latestPrepareJob")
    if isinstance(latest_prepare_job, dict):
        skipped["latestPrepareJob"] = dict(latest_prepare_job)
    return skipped


def _queued_validation_item(item: dict[str, Any], response: Any) -> dict[str, Any]:
    job = _prepare_job_from_runtime_payload(response)
    job_id = str(job.get("jobId") or "")
    return {
        "candidateId": str(item.get("candidateId") or ""),
        "profileId": str(item.get("profileId") or ""),
        "toolId": str(job.get("toolId") or _queue_item_tool_id(item)),
        "jobId": job_id,
        "status": str(job.get("status") or ""),
        "stage": str(job.get("stage") or ""),
        "message": str(job.get("message") or ""),
        "createdAt": str(job.get("createdAt") or ""),
        "updatedAt": str(job.get("updatedAt") or ""),
        "pollPath": f"/api/v1/tools/prepare-jobs/{job_id}",
        "resultState": "",
        "workflowReady": False,
    }


def _prepare_job_from_runtime_payload(payload: Any) -> dict[str, Any]:
    if isinstance(payload, dict):
        data = payload.get("data")
        job = data if isinstance(data, dict) else payload
    else:
        job = None
    if not isinstance(job, dict):
        raise ValueError("Invalid tool prepare job payload: expected an object")
    return job


def _latest_prepare_jobs_from_runtime_payload(payload: Any) -> dict[str, Any]:
    if isinstance(payload, dict):
        data = payload.get("data")
        jobs = data.get("byToolId") if isinstance(data, dict) else payload.get("byToolId")
    else:
        jobs = None
    if not isinstance(jobs, dict):
        raise ValueError("Invalid tool prepare jobs payload: expected a byToolId object")
    if any(not isinstance(value, dict) for value in jobs.values()):
        raise ValueError("Invalid tool prepare jobs payload: job summaries must be objects")
    return jobs


def _prepare_job_queue_from_runtime_payload(payload: Any) -> dict[str, Any]:
    if isinstance(payload, dict):
        data = payload.get("data")
        page = data if isinstance(data, dict) else payload
    else:
        page = None
    if not isinstance(page, dict):
        raise ValueError("Invalid tool prepare queue payload: expected an object")
    items = page.get("items") if isinstance(page.get("items"), list) else []
    status_counts = _record_counts(page.get("statusCounts"))
    for status in (*ACTIVE_PREPARE_JOB_STATUSES, *TERMINAL_PREPARE_JOB_STATUSES):
        status_counts.setdefault(status, 0)
    return {
        "items": [dict(item) for item in items if isinstance(item, dict)],
        "total": _count_value(page.get("total")),
        "limit": _count_value(page.get("limit")),
        "offset": _count_value(page.get("offset")),
        "statusCounts": status_counts,
    }


async def get_tool_capabilities_index_status_from_request() -> dict[str, Any]:
    return await run_sync(lambda: {"data": bioconda_index_status()})


async def list_snakemake_wrapper_catalog_from_request(
    *,
    q: str,
    page: int,
    page_size: int,
) -> dict[str, Any]:
    return await run_sync(
        lambda: {
            "data": catalog_snakemake_wrappers(
                query=q,
                page=page,
                page_size=page_size,
            )
        },
    )


async def list_tool_profile_catalog_from_request(
    *,
    q: str,
    page: int,
    page_size: int,
) -> dict[str, Any]:
    return await run_sync(
        lambda: {
            "data": catalog_tool_profiles(
                query=q,
                page=page,
                page_size=page_size,
            )
        },
    )


async def list_bio_tool_packs_from_request() -> dict[str, Any]:
    return await run_sync(lambda: {"data": list_bio_tool_packs()})


async def review_bio_tool_pack_from_request(payload: dict[str, Any]) -> dict[str, Any]:
    return await run_sync(lambda: {"data": review_bio_tool_pack_manifest(payload)})


async def import_bio_tool_pack_from_request(
    payload: dict[str, Any],
    *,
    enable: bool,
) -> dict[str, Any]:
    return await run_sync(lambda: {"data": import_bio_tool_pack_manifest(payload, enable=enable)})


async def enable_bio_tool_pack_from_request(pack_id: str) -> dict[str, Any]:
    return await run_sync(lambda: {"data": enable_bio_tool_pack(pack_id)})


async def disable_bio_tool_pack_from_request(pack_id: str) -> dict[str, Any]:
    return await run_sync(lambda: {"data": disable_bio_tool_pack(pack_id)})


async def refresh_tool_capabilities_index_from_request() -> dict[str, Any]:
    return await run_sync(_refresh_bioconda_index_status)


def _refresh_bioconda_index_status() -> dict[str, Any]:
    refresh_bioconda_index()
    return {"data": bioconda_index_status()}
