"""Run and result query routes for the local API."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query, Response

from core.contracts.remote_endpoints import (
    ARTIFACT_CACHE_ENTRIES_READ,
    ARTIFACT_CACHE_LOOKUP,
    ARTIFACT_CACHE_PINS_READ,
    ARTIFACT_CACHE_PIN_RELEASE,
    ARTIFACT_CACHE_PIN_RETAIN,
    ARTIFACT_LIFECYCLE_CONTROLLER_TICKS_READ,
    ARTIFACT_LIFECYCLE_USAGE_READ,
    REMOTE_ENDPOINTS,
    RESULT_AUDIT_READ,
    RESULT_LIST,
    RESULT_PACKAGE_EXPORT_LIST,
    RESULT_PREVIEW_READ,
    RESULT_READ,
    RUN_ATTEMPTS_READ,
    RUN_EVENTS_READ,
    RUN_EXECUTION_CONTEXT_READ,
    RUN_FAILURE_LOCATOR_READ,
    RUN_LIST,
    RUN_LOGS_READ,
    RUN_READ,
    RUN_RESULTS_READ,
    RUN_RULES_READ,
    WORKFLOW_REVISION_READ,
)
from apps.api.models import (
    ArtifactCacheLookupRequest,
    ArtifactCachePinReleaseRequest,
    ArtifactCachePinRetainRequest,
    ArtifactLifecycleControllerRunOnceRequest,
    ArtifactGcPreviewRequest,
    ArtifactGcRunRequest,
    ResultPackageByteGcRunRequest,
    ResultPackageByteGcPreviewRequest,
    ResultPackageExportRequest,
    ResultPackageRetireRequest,
    RunResumeRequest,
    RunRuleCacheRestoreAdoptionApplyRequest,
    RunRuleCacheRestoreAdoptionPrepareRequest,
    RunRuleCacheRestoreFinalOutputApplyRequest,
    RunRuleCacheRestoreFinalOutputPrepareRequest,
    RunRuleCacheRestorePinApplyRequest,
    RunRuleCacheRestorePinPrepareRequest,
    RunRuleCacheRestoreStagedFileApplyRequest,
    RunRuleCacheRestoreStagedFilePrepareRequest,
    RunRuleOutputInvalidationApplyRequest,
    RunRetryRequest,
    RunRuleRetryRequest,
)
from apps.api.execution_query_service import (
    apply_rule_cache_restore_adoption_from_request,
    apply_rule_cache_restore_final_outputs_from_request,
    apply_rule_cache_restore_pins_from_request,
    apply_rule_cache_restore_staged_files_from_request,
    apply_rule_output_invalidation_from_request,
    cancel_run_from_request,
    download_result_package_from_request,
    get_artifact_lifecycle_usage_from_request,
    list_artifact_lifecycle_controller_ticks_from_request,
    run_artifact_lifecycle_controller_once_from_request,
    get_result_from_request,
    get_result_preview_from_request,
    get_result_audit_from_request,
    export_result_package_from_request,
    get_run_events_from_request,
    get_run_attempts_from_request,
    get_run_execution_context_from_request,
    get_run_failure_locator_from_request,
    get_run_from_request,
    get_run_logs_from_request,
    get_run_results_from_request,
    get_run_rules_from_request,
    get_workflow_revision_from_request,
    list_artifact_cache_entries_from_request,
    list_artifact_cache_pins_from_request,
    list_result_package_exports_from_request,
    list_results_from_request,
    list_runs_from_request,
    lookup_artifact_cache_from_request,
    preview_result_package_byte_gc_from_request,
    run_result_package_byte_gc_from_request,
    prepare_rule_cache_restore_adoption_from_request,
    prepare_rule_cache_restore_final_outputs_from_request,
    prepare_rule_cache_restore_pins_from_request,
    prepare_rule_cache_restore_staged_files_from_request,
    preview_artifact_gc_from_request,
    release_artifact_cache_pin_from_request,
    retain_artifact_cache_pin_from_request,
    resume_run_from_request,
    retire_result_package_from_request,
    retry_run_rules_from_request,
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


@router.get("/api/v1/runs", operation_id=REMOTE_ENDPOINTS[RUN_LIST].operation_id)
async def list_runs(refresh: bool = False) -> dict[str, Any]:
    return await list_runs_from_request(refresh)


@router.get("/api/v1/runs/{run_id}", operation_id=REMOTE_ENDPOINTS[RUN_READ].operation_id)
async def get_run(run_id: str) -> dict[str, Any]:
    return await get_run_from_request(run_id)


@router.get(
    "/api/v1/workflow-revisions/{workflow_revision_id}",
    operation_id=REMOTE_ENDPOINTS[WORKFLOW_REVISION_READ].operation_id,
)
async def get_workflow_revision(
    workflow_revision_id: str,
    serverId: str | None = None,
) -> dict[str, Any]:
    return await get_workflow_revision_from_request(workflow_revision_id, server_id=serverId)


@router.post("/api/v1/runs/{run_id}/cancel")
async def cancel_run(run_id: str) -> dict[str, Any]:
    return await cancel_run_from_request(run_id)


@router.post("/api/v1/runs/{run_id}/retry", status_code=202)
async def retry_run(run_id: str, payload: RunRetryRequest) -> dict[str, Any]:
    return await retry_run_from_request(run_id, payload)


@router.post("/api/v1/runs/{run_id}/rules/retry", status_code=202)
async def retry_run_rules(run_id: str, payload: RunRuleRetryRequest) -> dict[str, Any]:
    return await retry_run_rules_from_request(run_id, payload)


@router.post("/api/v1/runs/{run_id}/rules/output-invalidation/apply")
async def apply_rule_output_invalidation(
    run_id: str,
    payload: RunRuleOutputInvalidationApplyRequest,
) -> dict[str, Any]:
    return await apply_rule_output_invalidation_from_request(run_id, payload)


@router.post("/api/v1/runs/{run_id}/rules/cache-restore/pins/prepare")
async def prepare_rule_cache_restore_pins(
    run_id: str,
    payload: RunRuleCacheRestorePinPrepareRequest,
) -> dict[str, Any]:
    return await prepare_rule_cache_restore_pins_from_request(run_id, payload)


@router.post("/api/v1/runs/{run_id}/rules/cache-restore/pins/apply")
async def apply_rule_cache_restore_pins(
    run_id: str,
    payload: RunRuleCacheRestorePinApplyRequest,
) -> dict[str, Any]:
    return await apply_rule_cache_restore_pins_from_request(run_id, payload)


@router.post("/api/v1/runs/{run_id}/rules/cache-restore/staged-files/prepare")
async def prepare_rule_cache_restore_staged_files(
    run_id: str,
    payload: RunRuleCacheRestoreStagedFilePrepareRequest,
) -> dict[str, Any]:
    return await prepare_rule_cache_restore_staged_files_from_request(run_id, payload)


@router.post("/api/v1/runs/{run_id}/rules/cache-restore/staged-files/apply")
async def apply_rule_cache_restore_staged_files(
    run_id: str,
    payload: RunRuleCacheRestoreStagedFileApplyRequest,
) -> dict[str, Any]:
    return await apply_rule_cache_restore_staged_files_from_request(run_id, payload)


@router.post("/api/v1/runs/{run_id}/rules/cache-restore/final-outputs/prepare")
async def prepare_rule_cache_restore_final_outputs(
    run_id: str,
    payload: RunRuleCacheRestoreFinalOutputPrepareRequest,
) -> dict[str, Any]:
    return await prepare_rule_cache_restore_final_outputs_from_request(run_id, payload)


@router.post("/api/v1/runs/{run_id}/rules/cache-restore/final-outputs/apply")
async def apply_rule_cache_restore_final_outputs(
    run_id: str,
    payload: RunRuleCacheRestoreFinalOutputApplyRequest,
) -> dict[str, Any]:
    return await apply_rule_cache_restore_final_outputs_from_request(run_id, payload)


@router.post("/api/v1/runs/{run_id}/rules/cache-restore/adoption/prepare")
async def prepare_rule_cache_restore_adoption(
    run_id: str,
    payload: RunRuleCacheRestoreAdoptionPrepareRequest,
) -> dict[str, Any]:
    return await prepare_rule_cache_restore_adoption_from_request(run_id, payload)


@router.post("/api/v1/runs/{run_id}/rules/cache-restore/adoption/apply")
async def apply_rule_cache_restore_adoption(
    run_id: str,
    payload: RunRuleCacheRestoreAdoptionApplyRequest,
) -> dict[str, Any]:
    return await apply_rule_cache_restore_adoption_from_request(run_id, payload)


@router.post("/api/v1/runs/{run_id}/resume", status_code=202)
async def resume_run(run_id: str, payload: RunResumeRequest) -> dict[str, Any]:
    return await resume_run_from_request(run_id, payload)


@router.get("/api/v1/runs/{run_id}/events", operation_id=REMOTE_ENDPOINTS[RUN_EVENTS_READ].operation_id)
async def get_run_events(run_id: str) -> dict[str, Any]:
    return await get_run_events_from_request(run_id)


@router.get(
    "/api/v1/runs/{run_id}/execution-context",
    operation_id=REMOTE_ENDPOINTS[RUN_EXECUTION_CONTEXT_READ].operation_id,
)
async def get_run_execution_context(run_id: str) -> dict[str, Any]:
    return await get_run_execution_context_from_request(run_id)


@router.get("/api/v1/runs/{run_id}/attempts", operation_id=REMOTE_ENDPOINTS[RUN_ATTEMPTS_READ].operation_id)
async def get_run_attempts(run_id: str) -> dict[str, Any]:
    return await get_run_attempts_from_request(run_id)


@router.get("/api/v1/runs/{run_id}/logs", operation_id=REMOTE_ENDPOINTS[RUN_LOGS_READ].operation_id)
async def get_run_logs(
    run_id: str,
    stream: str = "stdout",
    cursor: str | None = None,
) -> dict[str, Any]:
    return await get_run_logs_from_request(run_id, stream=stream, cursor=cursor)


@router.get("/api/v1/runs/{run_id}/results", operation_id=REMOTE_ENDPOINTS[RUN_RESULTS_READ].operation_id)
async def get_run_results(run_id: str) -> dict[str, Any]:
    return await get_run_results_from_request(run_id)


@router.get("/api/v1/runs/{run_id}/rules", operation_id=REMOTE_ENDPOINTS[RUN_RULES_READ].operation_id)
async def get_run_rules(run_id: str) -> dict[str, Any]:
    return await get_run_rules_from_request(run_id)


@router.get(
    "/api/v1/runs/{run_id}/failure-locator",
    operation_id=REMOTE_ENDPOINTS[RUN_FAILURE_LOCATOR_READ].operation_id,
)
async def get_run_failure_locator(run_id: str) -> dict[str, Any]:
    return await get_run_failure_locator_from_request(run_id)


@router.get("/api/v1/results", operation_id=REMOTE_ENDPOINTS[RESULT_LIST].operation_id)
async def list_results() -> dict[str, Any]:
    return await list_results_from_request()


@router.get("/api/v1/results/{result_id}", operation_id=REMOTE_ENDPOINTS[RESULT_READ].operation_id)
async def get_result(result_id: str) -> dict[str, Any]:
    return await get_result_from_request(result_id)


@router.get("/api/v1/results/{result_id}/preview", operation_id=REMOTE_ENDPOINTS[RESULT_PREVIEW_READ].operation_id)
async def get_result_preview(result_id: str, artifact_id: str | None = None) -> dict[str, Any]:
    return await get_result_preview_from_request(result_id, artifact_id=artifact_id)


@router.get("/api/v1/results/{result_id}/audit", operation_id=REMOTE_ENDPOINTS[RESULT_AUDIT_READ].operation_id)
async def get_result_audit(result_id: str) -> dict[str, Any]:
    return await get_result_audit_from_request(result_id)


@router.post("/api/v1/results/{result_id}/export")
async def export_result_package(
    result_id: str,
    request: ResultPackageExportRequest,
) -> dict[str, Any]:
    return await export_result_package_from_request(result_id, request)


@router.get(
    "/api/v1/results/{result_id}/exports",
    operation_id=REMOTE_ENDPOINTS[RESULT_PACKAGE_EXPORT_LIST].operation_id,
)
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


@router.post("/api/v1/result-package-exports/bytes/gc/preview")
async def preview_result_package_byte_gc(
    request: ResultPackageByteGcPreviewRequest,
) -> dict[str, Any]:
    return await preview_result_package_byte_gc_from_request(request)


@router.post("/api/v1/result-package-exports/bytes/gc/run")
async def run_result_package_byte_gc(
    request: ResultPackageByteGcRunRequest,
) -> dict[str, Any]:
    return await run_result_package_byte_gc_from_request(request)


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


@router.get(
    "/api/v1/artifacts/lifecycle/usage",
    operation_id=REMOTE_ENDPOINTS[ARTIFACT_LIFECYCLE_USAGE_READ].operation_id,
)
async def get_artifact_lifecycle_usage(
    serverId: str | None = None,
    quotaBytes: int | None = None,
) -> dict[str, Any]:
    return await get_artifact_lifecycle_usage_from_request(server_id=serverId, quota_bytes=quotaBytes)


@router.get(
    "/api/v1/artifacts/lifecycle/controller/ticks",
    operation_id=REMOTE_ENDPOINTS[ARTIFACT_LIFECYCLE_CONTROLLER_TICKS_READ].operation_id,
)
async def list_artifact_lifecycle_controller_ticks(
    serverId: str | None = None,
    limit: int = Query(default=20, ge=1, le=100),
) -> dict[str, Any]:
    return await list_artifact_lifecycle_controller_ticks_from_request(server_id=serverId, limit=limit)


@router.post("/api/v1/artifacts/lifecycle/controller/run-once", status_code=202)
async def run_artifact_lifecycle_controller_once(
    request: ArtifactLifecycleControllerRunOnceRequest,
    serverId: str | None = None,
) -> dict[str, Any]:
    return await run_artifact_lifecycle_controller_once_from_request(request, server_id=serverId)


@router.post("/api/v1/artifacts/lifecycle/gc/preview")
async def preview_artifact_gc(request: ArtifactGcPreviewRequest) -> dict[str, Any]:
    return await preview_artifact_gc_from_request(request)


@router.post("/api/v1/artifacts/lifecycle/gc/run")
async def run_artifact_gc(request: ArtifactGcRunRequest) -> dict[str, Any]:
    return await run_artifact_gc_from_request(request)


@router.get(
    "/api/v1/artifacts/cache/entries",
    operation_id=REMOTE_ENDPOINTS[ARTIFACT_CACHE_ENTRIES_READ].operation_id,
)
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


@router.get(
    "/api/v1/artifacts/cache/pins",
    operation_id=REMOTE_ENDPOINTS[ARTIFACT_CACHE_PINS_READ].operation_id,
)
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


@router.post(
    "/api/v1/artifacts/cache/entries/{cache_entry_id}/retain",
    operation_id=REMOTE_ENDPOINTS[ARTIFACT_CACHE_PIN_RETAIN].operation_id,
)
async def retain_artifact_cache_pin(
    cache_entry_id: str,
    request: ArtifactCachePinRetainRequest,
) -> dict[str, Any]:
    return await retain_artifact_cache_pin_from_request(cache_entry_id, request)


@router.post(
    "/api/v1/artifacts/cache/pins/{cache_pin_id}/release",
    operation_id=REMOTE_ENDPOINTS[ARTIFACT_CACHE_PIN_RELEASE].operation_id,
)
async def release_artifact_cache_pin(
    cache_pin_id: str,
    request: ArtifactCachePinReleaseRequest,
) -> dict[str, Any]:
    return await release_artifact_cache_pin_from_request(cache_pin_id, request)


@router.post(
    "/api/v1/artifacts/cache/lookup",
    operation_id=REMOTE_ENDPOINTS[ARTIFACT_CACHE_LOOKUP].operation_id,
)
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
