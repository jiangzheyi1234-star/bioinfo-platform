from __future__ import annotations

from typing import Any

from apps.api.response_cache import invalidate_response_cache
from apps.api.route_utils import cached_runtime_payload, run_runtime_payload, runtime_service


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
