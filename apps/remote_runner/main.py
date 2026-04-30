from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from .config import dump_public_config, inspect_runtime_layout, inspect_workflow_runtime, load_remote_runner_config
from .databases import (
    DatabaseRegistryError,
    add_reference_database,
    check_reference_database,
    list_database_templates,
    list_reference_databases,
    remove_reference_database,
)
from .executor import start_run_execution
from .pipeline import (
    PipelineRegistryError,
    get_pipeline,
    inspect_pipeline_registry,
    list_pipelines,
    validate_run_spec_for_pipeline,
)
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
from .tools import (
    ToolRegistryError,
    add_registered_tool,
    check_registered_tool,
    list_registered_tools,
    remove_registered_tool,
)


app = FastAPI(title="H2OMeta Remote Runner", version="0.1.1-control-plane")
_STARTED_AT = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
MAX_PREVIEW_BYTES = 256 * 1024
MAX_PREVIEW_TABLE_ROWS = 200


class UploadCreateRequest(BaseModel):
    filename: str = Field(min_length=1)
    contentBase64: str = Field(min_length=1)
    mimeType: str = "application/octet-stream"


class RunCreateRequest(BaseModel):
    serverId: str | None = None
    requestId: str | None = None
    runSpec: dict[str, Any] = Field(default_factory=dict)


class ToolManifestRequest(BaseModel):
    id: str | None = None
    name: str = Field(min_length=1)
    source: str = Field(min_length=1)
    sourceLabel: str | None = None
    version: str | None = None
    packageSpec: str | None = None
    summary: str | None = None
    targetPlatform: str | None = None
    targetPlatformSupported: bool = False
    platforms: list[str] = Field(default_factory=list)
    sourceUrl: str | None = None
    testCommand: str | None = None
    ruleTemplate: dict[str, Any] | None = None


class DatabaseManifestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str | None = None
    name: str = Field(min_length=1)
    templateId: str | None = None
    type: str | None = None
    version: str | None = None
    path: str = Field(min_length=1)
    description: str | None = None
    source: str | None = None
    manifestPath: str | None = None
    sizeBytes: int | None = Field(default=None, ge=0)
    checksum: str | None = None
    metadata: dict[str, Any] | None = None


def _require_auth(authorization: str | None, token: str) -> None:
    expected = f"Bearer {token}"
    if not token or authorization != expected:
        raise HTTPException(status_code=401, detail="runner authentication failed")


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
    }
    return payload


def _with_pipeline_registry(payload: dict[str, Any], cfg) -> dict[str, Any]:
    registry = inspect_pipeline_registry(cfg)
    payload["pipelineRegistry"] = registry
    return payload


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


@app.get("/api/v1/tools")
async def get_tools(authorization: str | None = Header(default=None)) -> dict[str, Any]:
    cfg = load_remote_runner_config()
    _require_auth(authorization, cfg.token)
    return {"data": {"items": list_registered_tools(cfg)}}


@app.post("/api/v1/tools", status_code=201)
async def add_tool(payload: ToolManifestRequest, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    cfg = load_remote_runner_config()
    _require_auth(authorization, cfg.token)
    try:
        item = add_registered_tool(cfg, payload.model_dump(exclude_none=True))
    except ToolRegistryError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"data": item}


@app.delete("/api/v1/tools/{tool_id}")
async def delete_tool_api(tool_id: str, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    cfg = load_remote_runner_config()
    _require_auth(authorization, cfg.token)
    try:
        remove_registered_tool(cfg, tool_id)
    except ToolRegistryError as exc:
        detail = str(exc)
        raise HTTPException(status_code=404 if detail == "TOOL_NOT_FOUND" else 400, detail=detail) from exc
    return {"data": {"id": tool_id, "deleted": True}}


@app.post("/api/v1/tools/{tool_id}/check")
async def check_tool_api(tool_id: str, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    cfg = load_remote_runner_config()
    _require_auth(authorization, cfg.token)
    try:
        item = check_registered_tool(cfg, tool_id)
    except ToolRegistryError as exc:
        detail = str(exc)
        raise HTTPException(status_code=404 if detail == "TOOL_NOT_FOUND" else 400, detail=detail) from exc
    return {"data": item}


@app.get("/api/v1/databases")
async def get_databases(authorization: str | None = Header(default=None)) -> dict[str, Any]:
    cfg = load_remote_runner_config()
    _require_auth(authorization, cfg.token)
    return {"data": {"items": list_reference_databases(cfg)}}


@app.get("/api/v1/database-templates")
async def get_database_templates(authorization: str | None = Header(default=None)) -> dict[str, Any]:
    cfg = load_remote_runner_config()
    _require_auth(authorization, cfg.token)
    return {"data": {"items": list_database_templates()}}


@app.post("/api/v1/databases", status_code=201)
async def add_database(payload: DatabaseManifestRequest, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    cfg = load_remote_runner_config()
    _require_auth(authorization, cfg.token)
    try:
        item = add_reference_database(cfg, payload.model_dump(exclude_none=True))
    except DatabaseRegistryError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"data": item}


@app.delete("/api/v1/databases/{database_id}")
async def delete_database_api(database_id: str, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    cfg = load_remote_runner_config()
    _require_auth(authorization, cfg.token)
    try:
        remove_reference_database(cfg, database_id)
    except DatabaseRegistryError as exc:
        detail = str(exc)
        raise HTTPException(status_code=404 if detail == "DATABASE_NOT_FOUND" else 400, detail=detail) from exc
    return {"data": {"id": database_id, "deleted": True}}


@app.post("/api/v1/databases/{database_id}/check")
async def check_database_api(database_id: str, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    cfg = load_remote_runner_config()
    _require_auth(authorization, cfg.token)
    try:
        item = check_reference_database(cfg, database_id)
    except DatabaseRegistryError as exc:
        detail = str(exc)
        raise HTTPException(status_code=404 if detail == "DATABASE_NOT_FOUND" else 400, detail=detail) from exc
    return {"data": item}


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
    run_spec = dict(payload.runSpec or {})
    request_id = str(payload.requestId or x_request_id or f"req_{int(time.time() * 1000)}")
    server_id = str(payload.serverId or run_spec.get("serverId") or "srv_local_default")
    idem_key = str(idempotency_key or f"idem_{request_id}")
    try:
        pipeline = get_pipeline(cfg, str(run_spec.get("pipelineId") or ""))
        validate_run_spec_for_pipeline(pipeline, run_spec)
    except PipelineRegistryError as exc:
        detail = str(exc)
        status_code = 404 if detail == "PIPELINE_NOT_FOUND" else 400
        raise HTTPException(status_code=status_code, detail=detail) from exc
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
