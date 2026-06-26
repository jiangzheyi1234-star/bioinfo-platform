from __future__ import annotations

from typing import Any
from urllib.parse import quote

from apps.api.models import (
    ArtifactCacheLookupRequest,
    ArtifactCachePinReleaseRequest,
    ArtifactCachePinRetainRequest,
    ArtifactLifecycleControllerRunOnceRequest,
    ArtifactGcPreviewRequest,
    ArtifactGcRunRequest,
    ResultPackageByteDeleteRequest,
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
from apps.api.response_cache import invalidate_response_cache
from apps.api.route_utils import cached_runtime_payload, request_payload, run_runtime_payload, run_sync, runtime_service


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


async def retry_run_from_request(run_id: str, request: RunRetryRequest) -> dict[str, Any]:
    result = await run_runtime_payload(
        lambda: runtime_service().retry_run(run_id, request_payload(request)),
        wrapper="raw",
    )
    await invalidate_response_cache("runs", prefixes=(f"run_detail:{run_id}",))
    return result


async def retry_run_rules_from_request(run_id: str, request: RunRuleRetryRequest) -> dict[str, Any]:
    result = await run_runtime_payload(
        lambda: runtime_service().retry_run_rules(run_id, request_payload(request)),
        wrapper="raw",
    )
    await invalidate_response_cache("runs", prefixes=(f"run_detail:{run_id}",))
    return result


async def apply_rule_output_invalidation_from_request(
    run_id: str,
    request: RunRuleOutputInvalidationApplyRequest,
) -> dict[str, Any]:
    result = await run_runtime_payload(
        lambda: runtime_service().apply_rule_output_invalidation(run_id, request_payload(request)),
        wrapper="raw",
    )
    await invalidate_response_cache("runs", prefixes=(f"run_detail:{run_id}",))
    return result


async def prepare_rule_cache_restore_pins_from_request(
    run_id: str,
    request: RunRuleCacheRestorePinPrepareRequest,
) -> dict[str, Any]:
    return await run_runtime_payload(
        lambda: runtime_service().prepare_rule_cache_restore_pins(run_id, request_payload(request)),
        wrapper="raw",
    )


async def apply_rule_cache_restore_pins_from_request(
    run_id: str,
    request: RunRuleCacheRestorePinApplyRequest,
) -> dict[str, Any]:
    result = await run_runtime_payload(
        lambda: runtime_service().apply_rule_cache_restore_pins(run_id, request_payload(request)),
        wrapper="raw",
    )
    await invalidate_response_cache("runs", prefixes=(f"run_detail:{run_id}",))
    return result


async def prepare_rule_cache_restore_staged_files_from_request(
    run_id: str,
    request: RunRuleCacheRestoreStagedFilePrepareRequest,
) -> dict[str, Any]:
    return await run_runtime_payload(
        lambda: runtime_service().prepare_rule_cache_restore_staged_files(run_id, request_payload(request)),
        wrapper="raw",
    )


async def apply_rule_cache_restore_staged_files_from_request(
    run_id: str,
    request: RunRuleCacheRestoreStagedFileApplyRequest,
) -> dict[str, Any]:
    result = await run_runtime_payload(
        lambda: runtime_service().apply_rule_cache_restore_staged_files(run_id, request_payload(request)),
        wrapper="raw",
    )
    await invalidate_response_cache("runs", prefixes=(f"run_detail:{run_id}",))
    return result


async def prepare_rule_cache_restore_final_outputs_from_request(
    run_id: str,
    request: RunRuleCacheRestoreFinalOutputPrepareRequest,
) -> dict[str, Any]:
    return await run_runtime_payload(
        lambda: runtime_service().prepare_rule_cache_restore_final_outputs(run_id, request_payload(request)),
        wrapper="raw",
    )


async def apply_rule_cache_restore_final_outputs_from_request(
    run_id: str,
    request: RunRuleCacheRestoreFinalOutputApplyRequest,
) -> dict[str, Any]:
    result = await run_runtime_payload(
        lambda: runtime_service().apply_rule_cache_restore_final_outputs(run_id, request_payload(request)),
        wrapper="raw",
    )
    await invalidate_response_cache("runs", prefixes=(f"run_detail:{run_id}",))
    return result


async def prepare_rule_cache_restore_adoption_from_request(
    run_id: str,
    request: RunRuleCacheRestoreAdoptionPrepareRequest,
) -> dict[str, Any]:
    return await run_runtime_payload(
        lambda: runtime_service().prepare_rule_cache_restore_adoption(run_id, request_payload(request)),
        wrapper="raw",
    )


async def apply_rule_cache_restore_adoption_from_request(
    run_id: str,
    request: RunRuleCacheRestoreAdoptionApplyRequest,
) -> dict[str, Any]:
    result = await run_runtime_payload(
        lambda: runtime_service().apply_rule_cache_restore_adoption(run_id, request_payload(request)),
        wrapper="raw",
    )
    await invalidate_response_cache("runs", prefixes=(f"run_detail:{run_id}",))
    return result


async def resume_run_from_request(run_id: str, request: RunResumeRequest) -> dict[str, Any]:
    result = await run_runtime_payload(
        lambda: runtime_service().resume_run(run_id, request_payload(request)),
        wrapper="raw",
    )
    await invalidate_response_cache("runs", prefixes=(f"run_detail:{run_id}",))
    return result


async def get_run_events_from_request(run_id: str) -> dict[str, Any]:
    return await run_runtime_payload(
        lambda: runtime_service().get_run_events(run_id),
        wrapper="raw",
    )


async def get_run_execution_context_from_request(run_id: str) -> dict[str, Any]:
    return await run_runtime_payload(
        lambda: runtime_service().get_run_execution_context(run_id),
        wrapper="raw",
    )


async def get_run_attempts_from_request(run_id: str) -> dict[str, Any]:
    return await run_runtime_payload(
        lambda: runtime_service().get_run_attempts(run_id),
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


async def get_run_failure_locator_from_request(run_id: str) -> dict[str, Any]:
    return await run_runtime_payload(
        lambda: runtime_service().get_run_failure_locator(run_id),
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
    result = await run_runtime_payload(
        lambda: runtime_service().get_result_audit(result_id),
        wrapper="raw",
    )
    _strip_result_artifact_audit_paths(result)
    return result


async def export_result_package_from_request(
    result_id: str,
    request: ResultPackageExportRequest,
) -> dict[str, Any]:
    payload = request_payload(request)
    server_id = payload.pop("serverId", None)
    result = await run_runtime_payload(
        lambda: runtime_service().export_result_package(
            result_id,
            payload=payload,
            server_id=server_id,
        ),
        wrapper="raw",
    )
    _attach_result_package_download(result)
    return result


async def list_result_package_exports_from_request(
    result_id: str,
    *,
    server_id: str | None = None,
    lifecycle_state: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    result = await run_runtime_payload(
        lambda: runtime_service().list_result_package_exports(
            result_id,
            server_id=server_id,
            lifecycle_state=lifecycle_state,
            limit=limit,
        ),
        wrapper="raw",
    )
    _attach_result_package_downloads(result)
    return result


async def download_result_package_from_request(
    result_id: str,
    package_export_id: str,
    *,
    server_id: str | None = None,
) -> dict[str, Any]:
    return await run_sync(
        lambda: runtime_service().download_result_package(
            result_id,
            package_export_id,
            server_id=server_id,
        )
    )


async def retire_result_package_from_request(
    result_id: str,
    package_export_id: str,
    request: ResultPackageRetireRequest,
) -> dict[str, Any]:
    payload = request_payload(request)
    server_id = payload.pop("serverId", None)
    result = await run_runtime_payload(
        lambda: runtime_service().retire_result_package(
            result_id,
            package_export_id,
            payload=payload,
            server_id=server_id,
        ),
        wrapper="raw",
    )
    _strip_result_package_paths(result)
    return result


async def delete_result_package_bytes_from_request(
    result_id: str,
    package_export_id: str,
    request: ResultPackageByteDeleteRequest,
) -> dict[str, Any]:
    payload = request_payload(request)
    server_id = payload.pop("serverId", None)
    result = await run_runtime_payload(
        lambda: runtime_service().delete_result_package_bytes(
            result_id,
            package_export_id,
            payload=payload,
            server_id=server_id,
        ),
        wrapper="raw",
    )
    _strip_result_package_paths(result)
    return result


async def preview_result_package_byte_gc_from_request(
    request: ResultPackageByteGcPreviewRequest,
) -> dict[str, Any]:
    payload = request_payload(request)
    server_id = payload.pop("serverId", None)
    result = await run_runtime_payload(
        lambda: runtime_service().preview_result_package_byte_gc(
            payload,
            server_id=server_id,
        ),
        wrapper="raw",
    )
    _strip_result_package_byte_gc_preview_secrets(result)
    return result


def _attach_result_package_download(result: dict[str, Any]) -> None:
    data = result.get("data") if isinstance(result, dict) else None
    if not isinstance(data, dict):
        return
    result_id = str(data.get("resultId") or "").strip()
    package_export_id = str(data.get("packageExportId") or "").strip()
    lifecycle_state = str(data.get("lifecycleState") or "").strip()
    byte_state = str(data.get("packageBytesState") or "").strip()
    if (
        lifecycle_state == "active"
        and byte_state == "available"
        and result_id
        and package_export_id
        and not isinstance(data.get("download"), dict)
    ):
        data["download"] = {
            "href": _result_package_download_href(result_id, package_export_id),
            "filename": _result_package_download_filename(data, package_export_id),
        }
    if lifecycle_state != "active" or byte_state != "available":
        data.pop("download", None)
    evidence_event_id = data.pop("evidenceEventId", None)
    if "evidenceId" not in data and evidence_event_id:
        data["evidenceId"] = evidence_event_id
    data.pop("manifest", None)
    data.pop("packagePath", None)
    data.pop("packageUri", None)


def _attach_result_package_downloads(result: dict[str, Any]) -> None:
    data = result.get("data") if isinstance(result, dict) else None
    items = data.get("items") if isinstance(data, dict) else None
    if not isinstance(items, list):
        return
    for item in items:
        if isinstance(item, dict):
            _attach_result_package_download({"data": item})


def _strip_result_package_paths(result: dict[str, Any]) -> None:
    data = result.get("data") if isinstance(result, dict) else None
    if isinstance(data, dict):
        data.pop("manifest", None)
        data.pop("packagePath", None)
        data.pop("packageUri", None)


def _strip_result_package_byte_gc_preview_secrets(result: dict[str, Any]) -> None:
    data = result.get("data") if isinstance(result, dict) else None
    if isinstance(data, dict):
        _strip_result_package_byte_gc_secret_keys(data)


def _strip_result_package_byte_gc_secret_keys(value: Any) -> None:
    secret_keys = {
        "manifest",
        "manifestSha256",
        "packageExportId",
        "packagePath",
        "packageSha256",
        "packageUri",
        "path",
        "resultId",
        "runId",
        "sha256",
        "storageUri",
    }
    if isinstance(value, dict):
        for key in list(value):
            if key in secret_keys:
                value.pop(key, None)
            else:
                _strip_result_package_byte_gc_secret_keys(value[key])
    elif isinstance(value, list):
        for item in value:
            _strip_result_package_byte_gc_secret_keys(item)


def _strip_result_artifact_audit_paths(result: dict[str, Any]) -> None:
    data = result.get("data") if isinstance(result, dict) else None
    artifacts = data.get("artifacts") if isinstance(data, dict) else None
    if not isinstance(artifacts, list):
        return
    for item in artifacts:
        if isinstance(item, dict):
            item.pop("path", None)
            item.pop("storageUri", None)
            item.pop("externalUri", None)
            item.pop("packagePath", None)
            item.pop("packageUri", None)


def _result_package_download_href(result_id: str, package_export_id: str) -> str:
    return (
        f"/api/v1/results/{quote(result_id, safe='')}/exports/"
        f"{quote(package_export_id, safe='')}/download"
    )


def _result_package_download_filename(data: dict[str, Any], package_export_id: str) -> str:
    path = str(data.get("packagePath") or "").replace("\\", "/")
    filename = path.rsplit("/", 1)[-1] if path else ""
    return filename or f"{package_export_id}.zip"


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


async def list_artifact_lifecycle_controller_ticks_from_request(
    *,
    server_id: str | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    return await run_runtime_payload(
        lambda: runtime_service().list_artifact_lifecycle_controller_ticks(
            server_id=server_id,
            limit=limit,
        ),
        wrapper="raw",
    )


async def run_artifact_lifecycle_controller_once_from_request(
    request: ArtifactLifecycleControllerRunOnceRequest,
    *,
    server_id: str | None = None,
) -> dict[str, Any]:
    payload = request_payload(request)
    server_id_hint = str(payload.pop("serverId", None) or server_id or "").strip() or None
    result = await run_runtime_payload(
        lambda: runtime_service().run_artifact_lifecycle_controller_once(
            payload,
            server_id=server_id_hint,
        ),
        wrapper="raw",
    )
    await invalidate_response_cache("runs")
    return result


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


async def list_artifact_cache_pins_from_request(
    *,
    server_id: str | None = None,
    cache_entry_id: str | None = None,
    state: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    return await run_runtime_payload(
        lambda: runtime_service().list_artifact_cache_pins(
            server_id=server_id,
            cache_entry_id=cache_entry_id,
            state=state,
            limit=limit,
        ),
        wrapper="raw",
    )


async def retain_artifact_cache_pin_from_request(
    cache_entry_id: str,
    request: ArtifactCachePinRetainRequest,
) -> dict[str, Any]:
    payload = request_payload(request)
    server_id = str(payload.pop("serverId", "") or "").strip() or None
    return await run_runtime_payload(
        lambda: runtime_service().retain_artifact_cache_pin(
            cache_entry_id,
            payload,
            server_id=server_id,
        ),
        wrapper="raw",
    )


async def release_artifact_cache_pin_from_request(
    cache_pin_id: str,
    request: ArtifactCachePinReleaseRequest,
) -> dict[str, Any]:
    payload = request_payload(request)
    server_id = str(payload.pop("serverId", "") or "").strip() or None
    return await run_runtime_payload(
        lambda: runtime_service().release_artifact_cache_pin(
            cache_pin_id,
            payload,
            server_id=server_id,
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
