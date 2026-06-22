from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter

from .control_service import (
    cancel_run_from_request,
    get_result_from_request,
    get_result_preview_from_request,
    get_run_events_from_request,
    get_run_from_request,
    get_run_logs_from_request,
    get_run_results_from_request,
    get_run_rules_from_request,
    list_results_from_request,
    list_runs_from_request,
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


@router.get("/api/v1/runs/{run_id}/events")
async def get_run_events_api(run_id: str, authorization: AuthorizationHeader = None) -> dict[str, Any]:
    return await get_run_events_from_request(run_id, authorization)


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
