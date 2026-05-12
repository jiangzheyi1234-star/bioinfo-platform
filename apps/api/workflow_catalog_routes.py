"""Frontend-oriented workflow catalog and run detail routes."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException

from apps.api.response_cache import cached_response
from apps.api.runtime import get_runtime_service
from apps.remote_runner.pipeline import PipelineRegistryError, validate_pipeline_manifest
from core.app_runtime.errors import RuntimeServiceError


router = APIRouter()


@router.get("/api/v1/workflow-catalog")
async def get_workflow_catalog(refresh: bool = False, remote: bool = False) -> dict[str, Any]:
    return await cached_response(
        f"workflow_catalog:{'remote' if remote else 'bundled'}",
        30,
        lambda: _load_workflow_catalog(include_remote=remote),
        force_refresh=refresh,
    )


async def _load_workflow_catalog(*, include_remote: bool = False) -> dict[str, Any]:
    runtime = get_runtime_service()
    catalog: list[dict[str, Any]] = []

    if not include_remote:
        manifests, errors = _list_bundled_pipeline_manifests()
        catalog.extend(_catalog_item_from_pipeline(item) for item in manifests)
        catalog.sort(key=lambda item: (not item["runnable"], item["name"].lower()))
        return {"data": {"items": catalog, "serverReady": False, "pipelineError": "; ".join(errors)}}

    try:
        pipelines_payload = await asyncio.to_thread(runtime.list_pipelines)
        pipelines = pipelines_payload.get("data", {}).get("items", [])
    except RuntimeServiceError as exc:
        return {
            "data": {
                "items": catalog,
                "serverReady": False,
                "pipelineError": str(exc) or "Remote pipeline registry is unavailable.",
            }
        }

    catalog.extend(_catalog_item_from_pipeline(item) for item in pipelines)
    catalog.sort(key=lambda item: (not item["runnable"], item["name"].lower()))
    return {"data": {"items": catalog, "serverReady": True, "pipelineError": ""}}


def _list_bundled_pipeline_manifests() -> tuple[list[dict[str, Any]], list[str]]:
    root = Path(__file__).resolve().parents[1] / "remote_runner" / "pipelines"
    items: list[dict[str, Any]] = []
    errors: list[str] = []
    for manifest_path in sorted(root.glob("*/pipeline.json")):
        try:
            raw = json.loads(manifest_path.read_text(encoding="utf-8"))
            validate_pipeline_manifest(raw, manifest_path)
        except (json.JSONDecodeError, PipelineRegistryError) as exc:
            errors.append(f"{manifest_path.parent.name}: {exc}")
            continue
        raw["enabled"] = bool(raw.get("enabled", True))
        items.append(raw)
    return items, errors


@router.get("/api/v1/runs/{run_id}/detail")
async def get_run_detail(run_id: str, refresh: bool = False) -> dict[str, Any]:
    return await cached_response(
        f"run_detail:{run_id}",
        3,
        lambda: _load_run_detail(run_id),
        force_refresh=refresh,
    )


async def _load_run_detail(run_id: str) -> dict[str, Any]:
    runtime = get_runtime_service()
    try:
        run = await asyncio.to_thread(runtime.get_run, run_id)
        events = await asyncio.to_thread(runtime.get_run_events, run_id)
        stdout = await asyncio.to_thread(runtime.get_run_logs, run_id=run_id, stream="stdout", cursor=None)
        stderr = await asyncio.to_thread(runtime.get_run_logs, run_id=run_id, stream="stderr", cursor=None)
        results = await asyncio.to_thread(runtime.get_run_results, run_id)
    except RuntimeServiceError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    result_data = _unwrap_data(results, {})
    if isinstance(result_data, dict) and not result_data.get("resultId"):
        result_data = {**result_data, "resultId": str(result_data.get("runId") or run_id)}
    previews: list[dict[str, Any]] = []
    for artifact in _preferred_preview_artifacts(list(result_data.get("artifacts") or [])):
        result_id = str(result_data.get("resultId") or "")
        artifact_id = str(artifact.get("artifactId") or "")
        if not result_id or not artifact_id:
            continue
        try:
            preview = await asyncio.to_thread(
                runtime.get_result_preview,
                result_id=result_id,
                artifact_id=artifact_id,
            )
            previews.append(_unwrap_data(preview, {}))
        except RuntimeServiceError:
            continue

    return {
        "data": {
            "run": _unwrap_data(run, {}),
            "events": _unwrap_data(events, {}).get("items", _unwrap_data(events, [])),
            "logs": {
                "stdout": _unwrap_data(stdout, {}),
                "stderr": _unwrap_data(stderr, {}),
            },
            "results": result_data,
            "previews": previews,
        }
    }


def _preferred_preview_artifacts(artifacts: list[Any]) -> list[dict[str, Any]]:
    valid = [item for item in artifacts if isinstance(item, dict)]
    priority = {
        "summary.tsv": 0,
        "qc-summary.tsv": 1,
        "run-report.html": 2,
        "raw-log.txt": 4,
    }

    def score(item: dict[str, Any]) -> tuple[int, str]:
        name = Path(str(item.get("path") or "")).name
        if name in priority:
            return priority[name], name
        mime_type = str(item.get("mimeType") or "")
        if "tab-separated" in mime_type:
            return 3, name
        if mime_type.startswith("text/"):
            return 5, name
        return 9, name

    return sorted(valid, key=score)[:3]


def _catalog_item_from_pipeline(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(item.get("pipelineId") or ""),
        "kind": "pipeline",
        "name": str(item.get("name") or ""),
        "version": str(item.get("version") or ""),
        "category": str(item.get("category") or ""),
        "description": str(item.get("description") or ""),
        "engine": "snakemake",
        "status": str(item.get("status") or "installed"),
        "runnable": bool(item.get("enabled", True)),
        "source": "remote-runner",
        "inputSchema": item.get("inputsSchema") or {},
        "paramsSchema": item.get("paramsSchema") or {},
        "outputSchema": item.get("outputSchema") or {},
        "uiSchema": item.get("uiSchema") or {},
        "tags": list(item.get("tags") or []),
        "moduleCount": None,
        "inputCount": _schema_count(item.get("inputsSchema")),
        "outputCount": _artifact_count(item.get("outputSchema")),
    }


def _schema_count(schema: Any) -> int:
    if not isinstance(schema, dict):
        return 0
    if schema.get("type") == "array":
        return int(schema.get("minItems") or 0)
    properties = schema.get("properties")
    return len(properties) if isinstance(properties, dict) else 0


def _artifact_count(schema: Any) -> int:
    if not isinstance(schema, dict):
        return 0
    artifacts = schema.get("artifacts")
    return len(artifacts) if isinstance(artifacts, list) else 0


def _unwrap_data(payload: Any, default: Any) -> Any:
    if isinstance(payload, dict) and "data" in payload:
        return payload["data"]
    return payload if payload is not None else default
