"""Run and result query routes for the local API."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query, Response

from apps.api.models import (
    ArtifactCacheLookupRequest,
    ArtifactCachePinReleaseRequest,
    ArtifactCachePinRetainRequest,
    ArtifactGcPreviewRequest,
    ArtifactGcRunRequest,
    ResultPackageExportRequest,
    ResultPackageRetireRequest,
    RunRetryRequest,
)
from apps.api.execution_query_service import (
    cancel_run_from_request,
    download_result_package_from_request,
    get_artifact_lifecycle_usage_from_request,
    get_result_from_request,
    get_result_preview_from_request,
    get_result_audit_from_request,
    export_result_package_from_request,
    get_run_events_from_request,
    get_run_execution_context_from_request,
    get_run_from_request,
    get_run_logs_from_request,
    get_run_results_from_request,
    get_run_rules_from_request,
    list_artifact_cache_entries_from_request,
    list_artifact_cache_pins_from_request,
    list_result_package_exports_from_request,
    list_results_from_request,
    list_runs_from_request,
    lookup_artifact_cache_from_request,
    preview_artifact_gc_from_request,
    release_artifact_cache_pin_from_request,
    retain_artifact_cache_pin_from_request,
    retire_result_package_from_request,
    retry_run_from_request,
    run_artifact_gc_from_request,
)


router = APIRouter()
DOWNLOAD_HEADER_ALLOWLIST = {
    "cache-control",
    "content-disposition",
    "x-content-type-options",
    "x-h2ometa-result-id",
    "x-h2ometa-package-export-id",
    "x-h2ometa-sha256",
    "x-h2ometa-manifest-sha256",
    "x-h2ometa-artifact-payload-mode",
}


@router.get("/api/v1/runs")
async def list_runs(refresh: bool = False) -> dict[str, Any]:
    return await list_runs_from_request(refresh)


@router.get("/api/v1/runs/{run_id}")
async def get_run(run_id: str) -> dict[str, Any]:
    return await get_run_from_request(run_id)


@router.post("/api/v1/runs/{run_id}/cancel")
async def cancel_run(run_id: str) -> dict[str, Any]:
    return await cancel_run_from_request(run_id)


@router.post("/api/v1/runs/{run_id}/retry", status_code=202)
async def retry_run(run_id: str, payload: RunRetryRequest) -> dict[str, Any]:
    return await retry_run_from_request(run_id, payload)


@router.get("/api/v1/runs/{run_id}/events")
async def get_run_events(run_id: str) -> dict[str, Any]:
    return await get_run_events_from_request(run_id)


@router.get("/api/v1/runs/{run_id}/execution-context")
async def get_run_execution_context(run_id: str) -> dict[str, Any]:
    return await get_run_execution_context_from_request(run_id)


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
async def export_result_package(
    result_id: str,
    request: ResultPackageExportRequest,
) -> dict[str, Any]:
    return await export_result_package_from_request(result_id, request)


@router.get("/api/v1/results/{result_id}/exports")
async def list_result_package_exports(
    result_id: str,
    serverId: str | None = None,
    lifecycleState: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
) -> dict[str, Any]:
    return await list_result_package_exports_from_request(
        result_id,
        server_id=serverId,
        lifecycle_state=lifecycleState,
        limit=limit,
    )


@router.get("/api/v1/results/{result_id}/exports/{package_export_id}/download")
async def download_result_package(
    result_id: str,
    package_export_id: str,
    serverId: str | None = None,
) -> Response:
    download = await download_result_package_from_request(
        result_id,
        package_export_id,
        server_id=serverId,
    )
    headers = _download_headers(download)
    return Response(
        content=download["content"],
        media_type=_download_media_type(download),
        headers=headers,
    )


@router.post("/api/v1/results/{result_id}/exports/{package_export_id}/retire")
async def retire_result_package(
    result_id: str,
    package_export_id: str,
    request: ResultPackageRetireRequest,
) -> dict[str, Any]:
    return await retire_result_package_from_request(result_id, package_export_id, request)


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


@router.get("/api/v1/artifacts/cache/pins")
async def list_artifact_cache_pins(
    serverId: str | None = None,
    cacheEntryId: str | None = None,
    state: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    return await list_artifact_cache_pins_from_request(
        server_id=serverId,
        cache_entry_id=cacheEntryId,
        state=state,
        limit=limit,
    )


@router.post("/api/v1/artifacts/cache/entries/{cache_entry_id}/retain")
async def retain_artifact_cache_pin(
    cache_entry_id: str,
    request: ArtifactCachePinRetainRequest,
) -> dict[str, Any]:
    return await retain_artifact_cache_pin_from_request(cache_entry_id, request)


@router.post("/api/v1/artifacts/cache/pins/{cache_pin_id}/release")
async def release_artifact_cache_pin(
    cache_pin_id: str,
    request: ArtifactCachePinReleaseRequest,
) -> dict[str, Any]:
    return await release_artifact_cache_pin_from_request(cache_pin_id, request)


@router.post("/api/v1/artifacts/cache/lookup")
async def lookup_artifact_cache(request: ArtifactCacheLookupRequest) -> dict[str, Any]:
    return await lookup_artifact_cache_from_request(request)


def _download_headers(download: dict[str, Any]) -> dict[str, str]:
    raw_headers = download.get("headers") if isinstance(download.get("headers"), dict) else {}
    return {
        str(key): str(value)
        for key, value in raw_headers.items()
        if str(key).lower() in DOWNLOAD_HEADER_ALLOWLIST and str(value)
    }


def _download_media_type(download: dict[str, Any]) -> str:
    media_type = str(download.get("mediaType") or "").strip()
    if media_type:
        return media_type
    headers = download.get("headers") if isinstance(download.get("headers"), dict) else {}
    return str(headers.get("content-type") or "application/zip")
