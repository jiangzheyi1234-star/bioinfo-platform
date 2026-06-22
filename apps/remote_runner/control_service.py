from __future__ import annotations

from typing import Any, Literal

from .api_models import (
    ArtifactCacheLookupRequest,
    ArtifactGcPreviewRequest,
    ArtifactGcRunRequest,
    RunCreateRequest,
    UploadCreateRequest,
    WorkflowTriggerCreateRequest,
    WorkflowTriggerEventRequest,
)
from .config import RemoteRunnerConfig, dump_public_config
from .execution_diagnostics import build_execution_diagnostics
from .artifact_cache_storage import list_artifact_cache_entries, lookup_artifact_cache_entry
from .artifact_lifecycle_service import build_artifact_lifecycle_usage, preview_artifact_gc, run_artifact_gc
from .artifact_product_service import build_result_artifact_audit, export_result_package
from .governance_audit import record_governance_audit_event
from .health_service import (
    build_health_live_payload,
    build_health_ready_payload,
    build_health_startup_payload,
)
from .pipeline import get_pipeline, list_pipelines
from .result_preview_service import build_result_preview_data
from .route_utils import authorized_config, data_response, run_sync
from .run_worker_storage import build_run_worker_health
from .storage import (
    fetch_log_lines,
    fetch_result,
    fetch_run_events,
    fetch_run_results,
    fetch_run_rules,
    list_results,
    list_runs,
    require_run,
    request_run_cancel,
)
from .submission_service import create_run_from_request as create_run_submission_from_request
from .trigger_service import (
    create_workflow_trigger_from_request,
    list_workflow_trigger_events_from_storage,
    list_workflow_triggers_from_storage,
    submit_workflow_trigger_event_from_request,
)
from .upload_service import persist_upload_from_request


async def _authorized_config_from_request(authorization: str | None) -> RemoteRunnerConfig:
    return await run_sync(authorized_config, authorization)


async def health_startup_from_request(authorization: str | None) -> dict[str, Any]:
    cfg = await _authorized_config_from_request(authorization)
    return await run_sync(build_health_startup_payload, cfg)


async def health_live_from_request(authorization: str | None) -> dict[str, Any]:
    cfg = await _authorized_config_from_request(authorization)
    return await run_sync(build_health_live_payload, cfg)


async def health_ready_from_request(authorization: str | None) -> dict[str, Any]:
    cfg = await _authorized_config_from_request(authorization)
    return await run_sync(build_health_ready_payload, cfg)


async def health_meta_from_request(authorization: str | None) -> dict[str, Any]:
    cfg = await _authorized_config_from_request(authorization)
    public_config = await run_sync(dump_public_config, cfg)
    return data_response(public_config)


async def health_workers_from_request(authorization: str | None) -> dict[str, Any]:
    cfg = await _authorized_config_from_request(authorization)
    worker_health = await run_sync(build_run_worker_health, cfg)
    return data_response(worker_health)


async def execution_diagnostics_from_request(authorization: str | None) -> dict[str, Any]:
    cfg = await _authorized_config_from_request(authorization)
    diagnostics = await run_sync(build_execution_diagnostics, cfg)
    return data_response(diagnostics)


async def list_pipelines_from_request(authorization: str | None) -> dict[str, Any]:
    cfg = await _authorized_config_from_request(authorization)
    pipelines = await run_sync(list_pipelines, cfg)
    return data_response(
        {"items": [pipeline.to_public_dict() for pipeline in pipelines]}
    )


async def get_pipeline_from_request(
    pipeline_id: str,
    authorization: str | None,
) -> dict[str, Any]:
    cfg = await _authorized_config_from_request(authorization)
    pipeline = await run_sync(get_pipeline, cfg, pipeline_id)
    return data_response(pipeline.to_public_dict())


async def create_upload_from_request(
    payload: UploadCreateRequest,
    authorization: str | None,
) -> dict[str, Any]:
    cfg = await _authorized_config_from_request(authorization)
    upload = await run_sync(persist_upload_from_request, cfg, payload)
    return data_response(upload)


async def create_run_from_request(
    payload: RunCreateRequest,
    authorization: str | None,
    *,
    idempotency_key: str | None,
    x_request_id: str | None,
) -> dict[str, Any]:
    cfg = await _authorized_config_from_request(authorization)
    return await run_sync(
        create_run_submission_from_request,
        cfg,
        payload,
        idempotency_key=idempotency_key,
        x_request_id=x_request_id,
    )


async def create_workflow_trigger_request(
    payload: WorkflowTriggerCreateRequest,
    authorization: str | None,
) -> dict[str, Any]:
    cfg = await _authorized_config_from_request(authorization)
    return await run_sync(
        create_workflow_trigger_from_request,
        cfg,
        payload,
        actor="remote-runner-api",
    )


async def list_workflow_triggers_request(authorization: str | None) -> dict[str, Any]:
    cfg = await _authorized_config_from_request(authorization)
    return await run_sync(list_workflow_triggers_from_storage, cfg)


async def submit_workflow_trigger_event_request(
    trigger_id: str,
    payload: WorkflowTriggerEventRequest,
    authorization: str | None,
) -> dict[str, Any]:
    cfg = await _authorized_config_from_request(authorization)
    return await run_sync(submit_workflow_trigger_event_from_request, cfg, trigger_id, payload)


async def list_workflow_trigger_events_request(
    trigger_id: str,
    authorization: str | None,
) -> dict[str, Any]:
    cfg = await _authorized_config_from_request(authorization)
    return await run_sync(list_workflow_trigger_events_from_storage, cfg, trigger_id)


async def list_runs_from_request(authorization: str | None) -> dict[str, Any]:
    cfg = await _authorized_config_from_request(authorization)
    runs = await run_sync(list_runs, cfg)
    return data_response({"items": runs})


async def get_run_from_request(run_id: str, authorization: str | None) -> dict[str, Any]:
    cfg = await _authorized_config_from_request(authorization)
    run = await run_sync(require_run, cfg, run_id)
    return data_response(run)


async def cancel_run_from_request(run_id: str, authorization: str | None) -> dict[str, Any]:
    cfg = await _authorized_config_from_request(authorization)
    result = await run_sync(request_run_cancel, cfg, run_id, actor="remote-runner-api")
    await run_sync(
        record_governance_audit_event,
        cfg,
        action="run.cancel",
        subject_kind="run",
        subject_id=run_id,
        details={
            "status": result["status"],
            "stage": result["stage"],
            "commandId": result["commandId"],
            "attemptId": str(result.get("attemptId") or ""),
            "cancelRequestedAt": result["cancelRequestedAt"],
        },
    )
    return data_response(result)


async def get_run_events_from_request(run_id: str, authorization: str | None) -> dict[str, Any]:
    cfg = await _authorized_config_from_request(authorization)
    events = await run_sync(fetch_run_events, cfg, run_id)
    return data_response({"items": events})


async def get_run_logs_from_request(
    run_id: str,
    stream: Literal["stdout", "stderr"],
    cursor: str | None,
    authorization: str | None,
) -> dict[str, Any]:
    cfg = await _authorized_config_from_request(authorization)
    log_lines = await run_sync(fetch_log_lines, cfg, run_id, stream, cursor)
    return data_response(log_lines)


async def get_run_results_from_request(run_id: str, authorization: str | None) -> dict[str, Any]:
    cfg = await _authorized_config_from_request(authorization)
    results = await run_sync(fetch_run_results, cfg, run_id)
    return data_response(results)


async def get_run_rules_from_request(run_id: str, authorization: str | None) -> dict[str, Any]:
    cfg = await _authorized_config_from_request(authorization)
    rules = await run_sync(fetch_run_rules, cfg, run_id)
    return data_response(rules)


async def list_results_from_request(authorization: str | None) -> dict[str, Any]:
    cfg = await _authorized_config_from_request(authorization)
    results = await run_sync(list_results, cfg)
    return data_response({"items": results})


async def get_result_from_request(result_id: str, authorization: str | None) -> dict[str, Any]:
    cfg = await _authorized_config_from_request(authorization)
    result = await run_sync(fetch_result, cfg, result_id)
    return data_response(result)


async def get_result_preview_from_request(
    result_id: str,
    artifact_id: str | None,
    authorization: str | None,
) -> dict[str, Any]:
    cfg = await _authorized_config_from_request(authorization)
    preview = await run_sync(build_result_preview_data, cfg, result_id, artifact_id)
    return data_response(preview)


async def get_result_audit_from_request(result_id: str, authorization: str | None) -> dict[str, Any]:
    cfg = await _authorized_config_from_request(authorization)
    audit = await run_sync(build_result_artifact_audit, cfg, result_id)
    return data_response(audit)


async def export_result_package_from_request(result_id: str, authorization: str | None) -> dict[str, Any]:
    cfg = await _authorized_config_from_request(authorization)
    package = await run_sync(export_result_package, cfg, result_id)
    return data_response(package)


async def get_artifact_lifecycle_usage_from_request(
    quota_bytes: int | None,
    authorization: str | None,
) -> dict[str, Any]:
    cfg = await _authorized_config_from_request(authorization)
    usage = await run_sync(build_artifact_lifecycle_usage, cfg, quota_bytes=quota_bytes)
    return data_response(usage)


async def preview_artifact_gc_from_request(
    request: ArtifactGcPreviewRequest,
    authorization: str | None,
) -> dict[str, Any]:
    cfg = await _authorized_config_from_request(authorization)
    plan = await run_sync(preview_artifact_gc, cfg, request.model_dump(mode="json", exclude_none=True))
    return data_response(plan)


async def run_artifact_gc_from_request(
    request: ArtifactGcRunRequest,
    authorization: str | None,
) -> dict[str, Any]:
    cfg = await _authorized_config_from_request(authorization)
    result = await run_sync(run_artifact_gc, cfg, request.model_dump(mode="json", exclude_none=True))
    return data_response(result)


async def list_artifact_cache_entries_from_request(
    workflow_revision_id: str | None,
    limit: int,
    authorization: str | None,
) -> dict[str, Any]:
    cfg = await _authorized_config_from_request(authorization)
    entries = await run_sync(
        list_artifact_cache_entries,
        cfg,
        workflow_revision_id=workflow_revision_id,
        limit=limit,
    )
    return data_response(entries)


async def lookup_artifact_cache_from_request(
    request: ArtifactCacheLookupRequest,
    authorization: str | None,
) -> dict[str, Any]:
    cfg = await _authorized_config_from_request(authorization)
    result = await run_sync(
        lookup_artifact_cache_entry,
        cfg,
        request.model_dump(mode="json", exclude_none=True),
    )
    return data_response(result)
