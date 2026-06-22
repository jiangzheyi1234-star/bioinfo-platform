from __future__ import annotations

from typing import Any

from apps.api.models import ArtifactCacheLookupRequest, ArtifactGcPreviewRequest, ArtifactGcRunRequest
from apps.api.response_cache import invalidate_response_cache
from apps.api.route_utils import cached_runtime_payload, request_payload, run_runtime_payload, runtime_service


async def list_runs_from_request(refresh: bool) -> dict[str, Any]:
    return await cached_runtime_payload(
        "runs",
        10,
        runtime_service().list_runs,
        wrapper="data_items",
        force_refresh=refresh,
    )


async def get_run_from_request(run_id: str) -> dict[str, Any]:
    return await run_runtime_payload(
        lambda: runtime_service().get_run(run_id),
        wrapper="raw",
    )


async def cancel_run_from_request(run_id: str) -> dict[str, Any]:
    result = await run_runtime_payload(
        lambda: runtime_service().cancel_run(run_id),
        wrapper="raw",
    )
    await invalidate_response_cache("runs", prefixes=(f"run_detail:{run_id}",))
    return result


async def get_run_events_from_request(run_id: str) -> dict[str, Any]:
    return await run_runtime_payload(
        lambda: runtime_service().get_run_events(run_id),
        wrapper="raw",
    )


async def get_run_logs_from_request(
    run_id: str,
    *,
    stream: str,
    cursor: str | None,
) -> dict[str, Any]:
    return await run_runtime_payload(
        lambda: runtime_service().get_run_logs(
            run_id=run_id,
            stream=stream,
            cursor=cursor,
        ),
        wrapper="raw",
    )


async def get_run_results_from_request(run_id: str) -> dict[str, Any]:
    return await run_runtime_payload(
        lambda: runtime_service().get_run_results(run_id),
        wrapper="raw",
    )


async def get_run_rules_from_request(run_id: str) -> dict[str, Any]:
    return await run_runtime_payload(
        lambda: runtime_service().get_run_rules(run_id),
        wrapper="raw",
    )


async def list_results_from_request() -> dict[str, Any]:
    return await run_runtime_payload(
        runtime_service().list_results,
        wrapper="raw",
    )


async def get_result_from_request(result_id: str) -> dict[str, Any]:
    return await run_runtime_payload(
        lambda: runtime_service().get_result(result_id),
        wrapper="raw",
    )


async def get_result_preview_from_request(
    result_id: str,
    *,
    artifact_id: str | None,
) -> dict[str, Any]:
    return await run_runtime_payload(
        lambda: runtime_service().get_result_preview(
            result_id=result_id,
            artifact_id=artifact_id,
        ),
        wrapper="raw",
    )


async def get_result_audit_from_request(result_id: str) -> dict[str, Any]:
    return await run_runtime_payload(
        lambda: runtime_service().get_result_audit(result_id),
        wrapper="raw",
    )


async def export_result_package_from_request(result_id: str) -> dict[str, Any]:
    return await run_runtime_payload(
        lambda: runtime_service().export_result_package(result_id),
        wrapper="raw",
    )


async def get_artifact_lifecycle_usage_from_request(
    *,
    server_id: str | None = None,
    quota_bytes: int | None = None,
) -> dict[str, Any]:
    return await run_runtime_payload(
        lambda: runtime_service().get_artifact_lifecycle_usage(
            server_id=server_id,
            quota_bytes=quota_bytes,
        ),
        wrapper="raw",
    )


async def preview_artifact_gc_from_request(request: ArtifactGcPreviewRequest) -> dict[str, Any]:
    payload = request_payload(request)
    server_id = str(payload.pop("serverId", "") or "").strip() or None
    return await run_runtime_payload(
        lambda: runtime_service().preview_artifact_gc(payload, server_id=server_id),
        wrapper="raw",
    )


async def run_artifact_gc_from_request(request: ArtifactGcRunRequest) -> dict[str, Any]:
    payload = request_payload(request)
    server_id = str(payload.pop("serverId", "") or "").strip() or None
    result = await run_runtime_payload(
        lambda: runtime_service().run_artifact_gc(payload, server_id=server_id),
        wrapper="raw",
    )
    await invalidate_response_cache("runs")
    return result


async def list_artifact_cache_entries_from_request(
    *,
    server_id: str | None = None,
    workflow_revision_id: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    return await run_runtime_payload(
        lambda: runtime_service().list_artifact_cache_entries(
            server_id=server_id,
            workflow_revision_id=workflow_revision_id,
            limit=limit,
        ),
        wrapper="raw",
    )


async def lookup_artifact_cache_from_request(request: ArtifactCacheLookupRequest) -> dict[str, Any]:
    payload = request_payload(request)
    server_id = str(payload.pop("serverId", "") or "").strip() or None
    return await run_runtime_payload(
        lambda: runtime_service().lookup_artifact_cache(payload, server_id=server_id),
        wrapper="raw",
    )
