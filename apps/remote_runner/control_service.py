from __future__ import annotations

from typing import Any, Literal

from .api_models import RunCreateRequest, UploadCreateRequest
from .config import RemoteRunnerConfig, dump_public_config
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
    list_results,
    list_runs,
    require_run,
    request_run_cancel,
)
from .submission_service import create_run_from_request as create_run_submission_from_request
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
