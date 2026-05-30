from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header, HTTPException

from .api_models import (
    RunCreateRequest,
    UploadCreateRequest,
)
from .config import dump_public_config, inspect_runtime_layout, inspect_workflow_runtime, load_remote_runner_config
from .database_routes import router as database_router
from .executor import start_run_execution
from .pipeline import (
    PipelineRegistryError,
    get_pipeline,
    inspect_pipeline_registry,
    list_pipelines,
    validate_run_spec_for_pipeline,
)
from .preflight import RunPreflightError, preflight_run_spec
from .storage import (
    canonical_payload_hash,
    create_run_record,
    fetch_log_lines,
    fetch_result,
    fetch_run,
    fetch_run_events,
    fetch_run_results,
    list_results,
    list_runs,
    persist_upload,
)
from .route_utils import require_auth as _require_auth
from .tool_routes import router as tool_router


app = FastAPI(title="H2OMeta Remote Runner", version="0.1.1-control-plane")
app.include_router(database_router)
app.include_router(tool_router)
_STARTED_AT = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
MAX_PREVIEW_BYTES = 256 * 1024
MAX_PREVIEW_TABLE_ROWS = 200


def _run_preflight_status_code(detail: str) -> int:
    if str(detail or "").startswith("WORKFLOW_TOOL_NOT_READY"):
        return 409
    return 422


def _build_health_payload(status: str, checks: dict[str, bool], cfg_mode: str, version: str) -> dict[str, Any]:
    return {
        "status": status,
        "service": "h2ometa-remote",
        "version": version,
        "startedAt": _STARTED_AT,
        "mode": cfg_mode,
        "checks": checks,
    }


def _with_workflow_runtime(payload: dict[str, Any], cfg) -> dict[str, Any]:
    workflow = inspect_workflow_runtime(cfg)
    payload["workflowRuntime"] = {
        "ok": bool(workflow["ok"]),
        "message": str(workflow["message"]),
        "provider": cfg.workflow_runtime_provider,
        "source": cfg.workflow_runtime_source,
        "version": cfg.workflow_runtime_version,
        "snakemakeCommand": cfg.snakemake_command,
        "snakemakeVersion": str(workflow.get("snakemakeVersion") or cfg.snakemake_version or ""),
        "workflowProfileConfigured": bool(workflow.get("workflowProfileConfigured")),
        "workflowProfileOk": bool(workflow.get("workflowProfileOk", True)),
        "workflowProfileMessage": str(workflow.get("workflowProfileMessage") or ""),
        "workflowProfileDir": str(workflow.get("workflowProfileDir") or cfg.workflow_profile_dir or ""),
        "workflowProfileName": str(workflow.get("workflowProfileName") or cfg.workflow_profile_name or ""),
        "workflowProfilePath": str(workflow.get("workflowProfilePath") or ""),
    }
    return payload


def _with_pipeline_registry(payload: dict[str, Any], cfg) -> dict[str, Any]:
    registry = inspect_pipeline_registry(cfg)
    payload["pipelineRegistry"] = registry
    return payload


def _raise_submission_readiness_failure(cfg) -> None:
    workflow = inspect_workflow_runtime(cfg)
    registry = inspect_pipeline_registry(cfg)
    detail_parts: list[str] = []
    reason_code = ""
    if not bool(workflow.get("ok")):
        reason_code = "WORKFLOW_RUNTIME_NOT_READY"
        detail_parts.append(str(workflow.get("message") or "Workflow runtime is not ready."))
    if not bool(registry.get("ok")):
        if not reason_code:
            reason_code = "PIPELINE_REGISTRY_NOT_READY"
        detail_parts.append(str(registry.get("message") or "Pipeline registry is not ready."))
    if detail_parts:
        raise HTTPException(status_code=503, detail=f"{reason_code}: {'; '.join(detail_parts)}")


@app.get("/health/startup")
async def health_startup(authorization: str | None = Header(default=None)) -> dict[str, Any]:
    cfg = load_remote_runner_config()
    _require_auth(authorization, cfg.token)
    checks = inspect_runtime_layout(cfg)
    status = "ok" if all(checks.values()) else "failed"
    return _build_health_payload(status, checks, cfg.mode, cfg.version)


@app.get("/health/live")
async def health_live(authorization: str | None = Header(default=None)) -> dict[str, Any]:
    cfg = load_remote_runner_config()
    _require_auth(authorization, cfg.token)
    checks = {"process": True, "pid": bool(os.getpid())}
    return _build_health_payload("ok", checks, cfg.mode, cfg.version)


@app.get("/health/ready")
async def health_ready(authorization: str | None = Header(default=None)) -> dict[str, Any]:
    cfg = load_remote_runner_config()
    _require_auth(authorization, cfg.token)
    checks = inspect_runtime_layout(cfg)
    checks["auth"] = bool(cfg.token)
    workflow = inspect_workflow_runtime(cfg)
    checks["workflow_runtime"] = bool(workflow["ok"])
    checks["workflow_profile"] = bool(workflow.get("workflowProfileOk", True))
    registry = inspect_pipeline_registry(cfg)
    checks["pipeline_registry"] = bool(registry["ok"])
    status = "ok" if all(checks.values()) else "failed"
    return _with_pipeline_registry(_with_workflow_runtime(_build_health_payload(status, checks, cfg.mode, cfg.version), cfg), cfg)


@app.get("/health/meta")
async def health_meta(authorization: str | None = Header(default=None)) -> dict[str, Any]:
    cfg = load_remote_runner_config()
    _require_auth(authorization, cfg.token)
    return {"data": dump_public_config(cfg)}


@app.get("/api/v1/pipelines")
async def get_pipelines(authorization: str | None = Header(default=None)) -> dict[str, Any]:
    cfg = load_remote_runner_config()
    _require_auth(authorization, cfg.token)
    return {"data": {"items": [pipeline.to_public_dict() for pipeline in list_pipelines(cfg)]}}


@app.get("/api/v1/pipelines/{pipeline_id}")
async def get_pipeline_api(pipeline_id: str, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    cfg = load_remote_runner_config()
    _require_auth(authorization, cfg.token)
    try:
        return {"data": get_pipeline(cfg, pipeline_id).to_public_dict()}
    except PipelineRegistryError as exc:
        detail = str(exc)
        status_code = 400 if detail == "PIPELINE_ID_REQUIRED" else 404
        raise HTTPException(status_code=status_code, detail=detail) from exc


@app.post("/api/v1/uploads")
async def create_upload(
    payload: UploadCreateRequest,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    cfg = load_remote_runner_config()
    _require_auth(authorization, cfg.token)
    try:
        item = persist_upload(
            cfg,
            filename=payload.filename,
            content_base64=payload.contentBase64,
            mime_type=payload.mimeType,
        )
    except ValueError as exc:
        detail = str(exc)
        status_code = 413 if detail == "UPLOAD_TOO_LARGE" else 400
        raise HTTPException(status_code=status_code, detail=detail) from exc
    return {"data": item}


@app.post("/api/v1/runs", status_code=202)
async def create_run(
    payload: RunCreateRequest,
    authorization: str | None = Header(default=None),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    x_request_id: str | None = Header(default=None, alias="X-Request-Id"),
) -> dict[str, Any]:
    cfg = load_remote_runner_config()
    _require_auth(authorization, cfg.token)
    _raise_submission_readiness_failure(cfg)
    run_spec = dict(payload.runSpec or {})
    request_id = str(payload.requestId or x_request_id or f"req_{int(time.time() * 1000)}")
    server_id = str(payload.serverId)
    idem_key = str(idempotency_key or f"idem_{request_id}")
    try:
        pipeline = get_pipeline(cfg, str(run_spec.get("pipelineId") or ""))
        validate_run_spec_for_pipeline(pipeline, run_spec)
    except PipelineRegistryError as exc:
        detail = str(exc)
        status_code = 404 if detail == "PIPELINE_NOT_FOUND" else 400
        raise HTTPException(status_code=status_code, detail=detail) from exc
    try:
        preflight_run_spec(cfg, pipeline, run_spec)
    except RunPreflightError as exc:
        detail = str(exc)
        raise HTTPException(status_code=_run_preflight_status_code(detail), detail=detail) from exc
    if not str(run_spec.get("pipelineVersion") or "").strip():
        run_spec["pipelineVersion"] = pipeline.version
    payload_hash = canonical_payload_hash({"serverId": server_id, "runSpec": run_spec})
    try:
        run, idem_status = create_run_record(
            cfg,
            server_id=server_id,
            request_id=request_id,
            run_spec=run_spec,
            idempotency_key=idem_key,
            payload_hash=payload_hash,
        )
    except ValueError as exc:
        if str(exc) == "IDEMPOTENCY_KEY_REUSED_WITH_DIFFERENT_PAYLOAD":
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if idem_status == "accepted":
        start_run_execution(
            cfg,
            run_id=run["runId"],
            request_id=request_id,
            run_spec=run_spec,
        )
    return {
        "data": {
            "requestId": run["requestId"],
            "runId": run["runId"],
            "status": run["status"],
            "stage": run["stage"],
            "message": run["message"],
            "lastUpdatedAt": run["lastUpdatedAt"],
        },
        "location": f"/api/v1/runs/{run['runId']}",
        "retryAfter": 2,
        "requestId": run["requestId"],
    }


@app.get("/api/v1/runs")
async def get_runs(authorization: str | None = Header(default=None)) -> dict[str, Any]:
    cfg = load_remote_runner_config()
    _require_auth(authorization, cfg.token)
    return {"data": {"items": list_runs(cfg)}}


@app.get("/api/v1/runs/{run_id}")
async def get_run(run_id: str, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    cfg = load_remote_runner_config()
    _require_auth(authorization, cfg.token)
    run = fetch_run(cfg, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="RUN_NOT_FOUND")
    return {"data": run}


@app.get("/api/v1/runs/{run_id}/events")
async def get_run_events_api(run_id: str, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    cfg = load_remote_runner_config()
    _require_auth(authorization, cfg.token)
    return {"data": {"items": fetch_run_events(cfg, run_id)}}


@app.get("/api/v1/runs/{run_id}/logs")
async def get_run_logs_api(
    run_id: str,
    stream: str = "stdout",
    cursor: str | None = None,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    cfg = load_remote_runner_config()
    _require_auth(authorization, cfg.token)
    normalized_stream = "stderr" if str(stream or "").lower() == "stderr" else "stdout"
    return {"data": fetch_log_lines(cfg, run_id, normalized_stream, cursor)}


@app.get("/api/v1/runs/{run_id}/results")
async def get_run_results_api(run_id: str, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    cfg = load_remote_runner_config()
    _require_auth(authorization, cfg.token)
    try:
        return {"data": fetch_run_results(cfg, run_id)}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="RUN_NOT_FOUND") from exc


@app.get("/api/v1/results")
async def list_results_api(authorization: str | None = Header(default=None)) -> dict[str, Any]:
    cfg = load_remote_runner_config()
    _require_auth(authorization, cfg.token)
    return {"data": {"items": list_results(cfg)}}


@app.get("/api/v1/results/{result_id}")
async def get_result_api(result_id: str, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    cfg = load_remote_runner_config()
    _require_auth(authorization, cfg.token)
    try:
        return {"data": fetch_result(cfg, result_id)}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="RESULT_NOT_FOUND") from exc


@app.get("/api/v1/results/{result_id}/preview")
async def get_result_preview_api(
    result_id: str,
    artifact_id: str | None = None,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    cfg = load_remote_runner_config()
    _require_auth(authorization, cfg.token)
    try:
        result = fetch_result(cfg, result_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="RESULT_NOT_FOUND") from exc
    artifacts = result["artifacts"]
    artifact = next((item for item in artifacts if item["artifactId"] == artifact_id), None) if artifact_id else (artifacts[0] if artifacts else None)
    if artifact is None:
        raise HTTPException(status_code=404, detail="RESULT_NOT_FOUND")
    path = artifact["path"]
    preview: dict[str, Any]
    if artifact["mimeType"] == "text/tab-separated-values":
        raw, truncated = _read_preview_text(Path(path))
        rows = raw.splitlines()
        columns = rows[0].split("\t") if rows else []
        preview_rows = [row.split("\t") for row in rows[1 : 1 + MAX_PREVIEW_TABLE_ROWS]]
        preview = {
            "kind": "table",
            "columns": columns,
            "rows": preview_rows,
            "truncated": truncated or max(0, len(rows) - 1) > MAX_PREVIEW_TABLE_ROWS,
        }
    elif artifact["mimeType"].startswith("text/html"):
        content, truncated = _read_preview_text(Path(path))
        preview = {"kind": "html", "content": content, "truncated": truncated}
    else:
        content, truncated = _read_preview_text(Path(path))
        preview = {"kind": "text", "content": content, "truncated": truncated}
    return {
        "data": {
            "resultId": result_id,
            "artifactId": artifact["artifactId"],
            "artifact": artifact,
            "preview": preview,
        }
    }


def _read_preview_text(path: Path, *, limit: int = MAX_PREVIEW_BYTES) -> tuple[str, bool]:
    with path.open("rb") as handle:
        payload = handle.read(limit + 1)
    truncated = len(payload) > limit
    return payload[:limit].decode("utf-8", errors="ignore"), truncated
