from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from .config import dump_public_config, inspect_runtime_layout, load_remote_runner_config
from .executor import start_run_execution
from .storage import (
    canonical_payload_hash,
    create_run_record,
    fetch_log_lines,
    fetch_result,
    fetch_run,
    fetch_run_events,
    fetch_run_results,
    fetch_upload,
    list_results,
    list_runs,
    persist_upload,
)


app = FastAPI(title="H2OMeta Remote Runner", version="0.1.0-control-plane")
_STARTED_AT = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


class UploadCreateRequest(BaseModel):
    filename: str = Field(min_length=1)
    contentBase64: str = Field(min_length=1)
    mimeType: str = "application/octet-stream"


class RunCreateRequest(BaseModel):
    serverId: str | None = None
    requestId: str | None = None
    runSpec: dict[str, Any] = Field(default_factory=dict)


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
    status = "ok" if all(checks.values()) else "failed"
    return _build_health_payload(status, checks, cfg.mode, cfg.version)


@app.get("/health/meta")
async def health_meta(authorization: str | None = Header(default=None)) -> dict[str, Any]:
    cfg = load_remote_runner_config()
    _require_auth(authorization, cfg.token)
    return {"data": dump_public_config(cfg)}


@app.post("/api/v1/uploads")
async def create_upload(
    payload: UploadCreateRequest,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    cfg = load_remote_runner_config()
    _require_auth(authorization, cfg.token)
    item = persist_upload(
        cfg,
        filename=payload.filename,
        content_base64=payload.contentBase64,
        mime_type=payload.mimeType,
    )
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
        rows = Path(path).read_text(encoding="utf-8").splitlines()
        preview = {"kind": "table", "columns": rows[0].split("\t"), "rows": [row.split("\t") for row in rows[1:]]}
    elif artifact["mimeType"].startswith("text/html"):
        preview = {"kind": "html", "content": Path(path).read_text(encoding="utf-8")}
    else:
        preview = {"kind": "text", "content": Path(path).read_text(encoding="utf-8")}
    return {
        "data": {
            "resultId": result_id,
            "artifactId": artifact["artifactId"],
            "artifact": artifact,
            "preview": preview,
        }
    }
