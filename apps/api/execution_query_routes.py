"""Run and result query routes for the local API."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from apps.api.execution_query_service import (
    cancel_run_from_request,
    get_result_from_request,
    get_result_preview_from_request,
    get_run_events_from_request,
    get_run_from_request,
    get_run_logs_from_request,
    get_run_results_from_request,
    list_results_from_request,
    list_runs_from_request,
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


@router.get("/api/v1/results")
async def list_results() -> dict[str, Any]:
    return await list_results_from_request()


@router.get("/api/v1/results/{result_id}")
async def get_result(result_id: str) -> dict[str, Any]:
    return await get_result_from_request(result_id)


@router.get("/api/v1/results/{result_id}/preview")
async def get_result_preview(result_id: str, artifact_id: str | None = None) -> dict[str, Any]:
    return await get_result_preview_from_request(result_id, artifact_id=artifact_id)
