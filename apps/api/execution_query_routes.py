"""Run and result query routes for the local API."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from apps.api.models import ArtifactCacheLookupRequest, ArtifactGcPreviewRequest, ArtifactGcRunRequest
from apps.api.execution_query_service import (
    cancel_run_from_request,
    get_artifact_lifecycle_usage_from_request,
    get_result_from_request,
    get_result_preview_from_request,
    get_result_audit_from_request,
    export_result_package_from_request,
    get_run_events_from_request,
    get_run_from_request,
    get_run_logs_from_request,
    get_run_results_from_request,
    get_run_rules_from_request,
    list_artifact_cache_entries_from_request,
    list_results_from_request,
    list_runs_from_request,
    lookup_artifact_cache_from_request,
    preview_artifact_gc_from_request,
    run_artifact_gc_from_request,
)


router = APIRouter()


@router.get("/api/v1/runs")
async def list_runs(refresh: bool = False) -> dict[str, Any]:
    return await list_runs_from_request(refresh)


@router.get("/api/v1/runs/{run_id}")
async def get_run(run_id: str) -> dict[str, Any]:
    return await get_run_from_request(run_id)


@router.post("/api/v1/runs/{run_id}/cancel")
async def cancel_run(run_id: str) -> dict[str, Any]:
    return await cancel_run_from_request(run_id)


@router.get("/api/v1/runs/{run_id}/events")
async def get_run_events(run_id: str) -> dict[str, Any]:
    return await get_run_events_from_request(run_id)


@router.get("/api/v1/runs/{run_id}/logs")
async def get_run_logs(
    run_id: str,
    stream: str = "stdout",
    cursor: str | None = None,
) -> dict[str, Any]:
    return await get_run_logs_from_request(run_id, stream=stream, cursor=cursor)


@router.get("/api/v1/runs/{run_id}/results")
async def get_run_results(run_id: str) -> dict[str, Any]:
    return await get_run_results_from_request(run_id)


@router.get("/api/v1/runs/{run_id}/rules")
async def get_run_rules(run_id: str) -> dict[str, Any]:
    return await get_run_rules_from_request(run_id)


@router.get("/api/v1/results")
async def list_results() -> dict[str, Any]:
    return await list_results_from_request()


@router.get("/api/v1/results/{result_id}")
async def get_result(result_id: str) -> dict[str, Any]:
    return await get_result_from_request(result_id)


@router.get("/api/v1/results/{result_id}/preview")
async def get_result_preview(result_id: str, artifact_id: str | None = None) -> dict[str, Any]:
    return await get_result_preview_from_request(result_id, artifact_id=artifact_id)


@router.get("/api/v1/results/{result_id}/audit")
async def get_result_audit(result_id: str) -> dict[str, Any]:
    return await get_result_audit_from_request(result_id)


@router.post("/api/v1/results/{result_id}/export")
async def export_result_package(result_id: str) -> dict[str, Any]:
    return await export_result_package_from_request(result_id)


@router.get("/api/v1/artifacts/lifecycle/usage")
async def get_artifact_lifecycle_usage(
    serverId: str | None = None,
    quotaBytes: int | None = None,
) -> dict[str, Any]:
    return await get_artifact_lifecycle_usage_from_request(server_id=serverId, quota_bytes=quotaBytes)


@router.post("/api/v1/artifacts/lifecycle/gc/preview")
async def preview_artifact_gc(request: ArtifactGcPreviewRequest) -> dict[str, Any]:
    return await preview_artifact_gc_from_request(request)


@router.post("/api/v1/artifacts/lifecycle/gc/run")
async def run_artifact_gc(request: ArtifactGcRunRequest) -> dict[str, Any]:
    return await run_artifact_gc_from_request(request)


@router.get("/api/v1/artifacts/cache/entries")
async def list_artifact_cache_entries(
    serverId: str | None = None,
    workflowRevisionId: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    return await list_artifact_cache_entries_from_request(
        server_id=serverId,
        workflow_revision_id=workflowRevisionId,
        limit=limit,
    )


@router.post("/api/v1/artifacts/cache/lookup")
async def lookup_artifact_cache(request: ArtifactCacheLookupRequest) -> dict[str, Any]:
    return await lookup_artifact_cache_from_request(request)
