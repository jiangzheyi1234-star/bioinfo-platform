from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Query
from fastapi.responses import FileResponse

from .api_models import (
    ArtifactCacheLookupRequest,
    ArtifactCachePinReleaseRequest,
    ArtifactCachePinRetainRequest,
    ArtifactGcPreviewRequest,
    ArtifactGcRunRequest,
    ResultPackageByteDeleteRequest,
    ResultPackageExportRequest,
    ResultPackageRetireRequest,
    RunRetryRequest,
)
from .control_service import (
    cancel_run_from_request,
    delete_result_package_bytes_from_request,
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
from .route_headers import AuthorizationHeader


router = APIRouter()


@router.get("/api/v1/runs")
async def get_runs(authorization: AuthorizationHeader = None) -> dict[str, Any]:
    return await list_runs_from_request(authorization)


@router.get("/api/v1/runs/{run_id}")
async def get_run(run_id: str, authorization: AuthorizationHeader = None) -> dict[str, Any]:
    return await get_run_from_request(run_id, authorization)


@router.post("/api/v1/runs/{run_id}/cancel")
async def cancel_run_api(run_id: str, authorization: AuthorizationHeader = None) -> dict[str, Any]:
    return await cancel_run_from_request(run_id, authorization)


@router.post("/api/v1/runs/{run_id}/retry", status_code=202)
async def retry_run_api(
    run_id: str,
    payload: RunRetryRequest,
    authorization: AuthorizationHeader = None,
) -> dict[str, Any]:
    return await retry_run_from_request(run_id, payload, authorization)


@router.get("/api/v1/runs/{run_id}/events")
async def get_run_events_api(run_id: str, authorization: AuthorizationHeader = None) -> dict[str, Any]:
    return await get_run_events_from_request(run_id, authorization)


@router.get("/api/v1/runs/{run_id}/execution-context")
async def get_run_execution_context_api(run_id: str, authorization: AuthorizationHeader = None) -> dict[str, Any]:
    return await get_run_execution_context_from_request(run_id, authorization)


@router.get("/api/v1/runs/{run_id}/logs")
async def get_run_logs_api(
    run_id: str,
    stream: Literal["stdout", "stderr"] = "stdout",
    cursor: str | None = None,
    authorization: AuthorizationHeader = None,
) -> dict[str, Any]:
    return await get_run_logs_from_request(run_id, stream, cursor, authorization)


@router.get("/api/v1/runs/{run_id}/results")
async def get_run_results_api(run_id: str, authorization: AuthorizationHeader = None) -> dict[str, Any]:
    return await get_run_results_from_request(run_id, authorization)


@router.get("/api/v1/runs/{run_id}/rules")
async def get_run_rules_api(run_id: str, authorization: AuthorizationHeader = None) -> dict[str, Any]:
    return await get_run_rules_from_request(run_id, authorization)


@router.get("/api/v1/results")
async def list_results_api(authorization: AuthorizationHeader = None) -> dict[str, Any]:
    return await list_results_from_request(authorization)


@router.get("/api/v1/results/{result_id}")
async def get_result_api(result_id: str, authorization: AuthorizationHeader = None) -> dict[str, Any]:
    return await get_result_from_request(result_id, authorization)


@router.get("/api/v1/results/{result_id}/preview")
async def get_result_preview_api(
    result_id: str,
    artifact_id: str | None = None,
    authorization: AuthorizationHeader = None,
) -> dict[str, Any]:
    return await get_result_preview_from_request(result_id, artifact_id, authorization)


@router.get("/api/v1/results/{result_id}/audit")
async def get_result_audit_api(result_id: str, authorization: AuthorizationHeader = None) -> dict[str, Any]:
    return await get_result_audit_from_request(result_id, authorization)


@router.post("/api/v1/results/{result_id}/export")
async def export_result_package_api(
    result_id: str,
    request: ResultPackageExportRequest,
    authorization: AuthorizationHeader = None,
) -> dict[str, Any]:
    return await export_result_package_from_request(result_id, request, authorization)


@router.get("/api/v1/results/{result_id}/exports")
async def list_result_package_exports_api(
    result_id: str,
    lifecycleState: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    authorization: AuthorizationHeader = None,
) -> dict[str, Any]:
    return await list_result_package_exports_from_request(
        result_id,
        authorization,
        lifecycle_state=lifecycleState,
        limit=limit,
    )


@router.get("/api/v1/results/{result_id}/exports/{package_export_id}/download")
async def download_result_package_api(
    result_id: str,
    package_export_id: str,
    authorization: AuthorizationHeader = None,
) -> FileResponse:
    download = await download_result_package_from_request(result_id, package_export_id, authorization)
    return FileResponse(
        download["path"],
        media_type=download["mediaType"],
        filename=download["filename"],
        headers=download["headers"],
    )


@router.post("/api/v1/results/{result_id}/exports/{package_export_id}/retire")
async def retire_result_package_api(
    result_id: str,
    package_export_id: str,
    request: ResultPackageRetireRequest,
    authorization: AuthorizationHeader = None,
) -> dict[str, Any]:
    return await retire_result_package_from_request(result_id, package_export_id, request, authorization)


@router.post("/api/v1/results/{result_id}/exports/{package_export_id}/bytes/delete")
async def delete_result_package_bytes_api(
    result_id: str,
    package_export_id: str,
    request: ResultPackageByteDeleteRequest,
    authorization: AuthorizationHeader = None,
) -> dict[str, Any]:
    return await delete_result_package_bytes_from_request(result_id, package_export_id, request, authorization)


@router.get("/api/v1/artifacts/lifecycle/usage")
async def get_artifact_lifecycle_usage_api(
    quotaBytes: int | None = None,
    authorization: AuthorizationHeader = None,
) -> dict[str, Any]:
    return await get_artifact_lifecycle_usage_from_request(quotaBytes, authorization)


@router.post("/api/v1/artifacts/lifecycle/gc/preview")
async def preview_artifact_gc_api(
    request: ArtifactGcPreviewRequest,
    authorization: AuthorizationHeader = None,
) -> dict[str, Any]:
    return await preview_artifact_gc_from_request(request, authorization)


@router.post("/api/v1/artifacts/lifecycle/gc/run")
async def run_artifact_gc_api(
    request: ArtifactGcRunRequest,
    authorization: AuthorizationHeader = None,
) -> dict[str, Any]:
    return await run_artifact_gc_from_request(request, authorization)


@router.get("/api/v1/artifacts/cache/entries")
async def list_artifact_cache_entries_api(
    workflowRevisionId: str | None = None,
    limit: int = 100,
    authorization: AuthorizationHeader = None,
) -> dict[str, Any]:
    return await list_artifact_cache_entries_from_request(workflowRevisionId, limit, authorization)


@router.get("/api/v1/artifacts/cache/pins")
async def list_artifact_cache_pins_api(
    cacheEntryId: str | None = None,
    state: str | None = None,
    limit: int = 100,
    authorization: AuthorizationHeader = None,
) -> dict[str, Any]:
    return await list_artifact_cache_pins_from_request(cacheEntryId, state, limit, authorization)


@router.post("/api/v1/artifacts/cache/entries/{cache_entry_id}/retain")
async def retain_artifact_cache_pin_api(
    cache_entry_id: str,
    request: ArtifactCachePinRetainRequest,
    authorization: AuthorizationHeader = None,
) -> dict[str, Any]:
    return await retain_artifact_cache_pin_from_request(cache_entry_id, request, authorization)


@router.post("/api/v1/artifacts/cache/pins/{cache_pin_id}/release")
async def release_artifact_cache_pin_api(
    cache_pin_id: str,
    request: ArtifactCachePinReleaseRequest,
    authorization: AuthorizationHeader = None,
) -> dict[str, Any]:
    return await release_artifact_cache_pin_from_request(cache_pin_id, request, authorization)


@router.post("/api/v1/artifacts/cache/lookup")
async def lookup_artifact_cache_api(
    request: ArtifactCacheLookupRequest,
    authorization: AuthorizationHeader = None,
) -> dict[str, Any]:
    return await lookup_artifact_cache_from_request(request, authorization)
