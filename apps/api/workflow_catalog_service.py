"""Service functions for workflow catalog and run detail payloads."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from apps.api.response_cache import cached_response
from apps.api.route_utils import run_sync, runtime_service
from core.contracts.pipeline_manifest import validate_pipeline_manifest


async def get_workflow_catalog_from_request(refresh: bool) -> dict[str, Any]:
    return await cached_response(
        "workflow_catalog:bundled",
        30,
        load_workflow_catalog,
        force_refresh=refresh,
    )


async def get_run_detail_from_request(run_id: str, refresh: bool) -> dict[str, Any]:
    return await cached_response(
        f"run_detail:{run_id}",
        3,
        lambda: load_run_detail(run_id),
        force_refresh=refresh,
    )


async def load_workflow_catalog() -> dict[str, Any]:
    manifests = list_bundled_pipeline_manifests()
    catalog = [_catalog_item_from_pipeline(item) for item in manifests]
    catalog.sort(key=lambda item: (not item["runnable"], item["name"].lower()))
    return {
        "data": {
            "items": catalog,
            "serverReady": False,
        }
    }


def list_bundled_pipeline_manifests() -> list[dict[str, Any]]:
    root = Path(__file__).resolve().parents[1] / "remote_runner" / "pipelines"
    items: list[dict[str, Any]] = []
    for manifest_path in sorted(root.glob("*/pipeline.json")):
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
        validate_pipeline_manifest(raw, manifest_path)
        raw["enabled"] = bool(raw.get("enabled", True))
        items.append(raw)
    return items


async def load_run_detail(run_id: str) -> dict[str, Any]:
    runtime = runtime_service()
    run = await run_sync(lambda: runtime.get_run(run_id))
    events = await run_sync(lambda: runtime.get_run_events(run_id))
    stdout = await run_sync(
        lambda: runtime.get_run_logs(
            run_id=run_id,
            stream="stdout",
            cursor=None,
        )
    )
    stderr = await run_sync(
        lambda: runtime.get_run_logs(
            run_id=run_id,
            stream="stderr",
            cursor=None,
        )
    )
    results = await run_sync(lambda: runtime.get_run_results(run_id))

    result_data = _unwrap_data(results, {})
    if isinstance(result_data, dict) and not result_data.get("resultId"):
        result_data = {**result_data, "resultId": str(result_data.get("runId") or run_id)}

    return {
        "data": {
            "run": _unwrap_data(run, {}),
            "events": _unwrap_data(events, {}).get("items", _unwrap_data(events, [])),
            "logs": {
                "stdout": _unwrap_data(stdout, {}),
                "stderr": _unwrap_data(stderr, {}),
            },
            "results": result_data,
            "previews": await _load_previews(runtime, result_data),
        }
    }


async def _load_previews(runtime: Any, result_data: Any) -> list[dict[str, Any]]:
    previews: list[dict[str, Any]] = []
    for artifact in _preferred_preview_artifacts(list(result_data.get("artifacts") or [])):
        result_id = str(result_data.get("resultId") or "")
        artifact_id = str(artifact.get("artifactId") or "")
        if not result_id or not artifact_id:
            continue
        preview = await run_sync(
            lambda: runtime.get_result_preview(
                result_id=result_id,
                artifact_id=artifact_id,
            )
        )
        previews.append(_unwrap_data(preview, {}))
    return previews


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
        "resources": item.get("resources") or {},
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
