"""FastAPI app for desktop-shell migration."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Response, WebSocket
from fastapi.middleware.cors import CORSMiddleware

from apps.api.models import (
    RunSubmitRequest,
    SSHConnectionRequest,
    SSHTerminalCreateRequest,
    ToolManifestRequest,
    ToolRuleTemplateRequest,
    UploadSubmitRequest,
)
from apps.api.database_routes import router as database_router
from apps.api.problem_details import ensure_request_id, problem_http_exception
from apps.api.response_cache import invalidate_response_cache
from apps.api.route_utils import (
    cached_runtime_payload as _cached_runtime_payload,
    run_runtime_payload as _run_runtime_payload,
    runtime_service as _runtime,
)
from apps.api.run_submission_status import classify_run_submission_status
from apps.api.runtime import get_runtime_service
from apps.api.ssh_terminal_routes import stream_terminal_session_with_runtime
from apps.api.tool_capability_routes import router as tool_capability_router
from apps.api.tool_contract_routes import router as tool_contract_router
from apps.api.workflow_catalog_routes import router as workflow_catalog_router
from apps.api.workflow_design_routes import router as workflow_design_router
from apps.api.workflow_sample_data_routes import router as workflow_sample_data_router
from core.app_runtime.errors import RuntimeServiceError


@asynccontextmanager
async def lifespan(app: FastAPI):
    get_runtime_service()
    try:
        yield
    finally:
        runtime = get_runtime_service()
        runtime.shutdown()
        get_runtime_service.cache_clear()


app = FastAPI(
    title="H2OMeta Local API",
    version="0.1.0",
    lifespan=lifespan,
)

TERMINAL_RUNTIME_BUILD_ID = "terminal-websocket-v1"

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:3765",
        "http://127.0.0.1:3765",
        "tauri://localhost",
        "http://tauri.localhost",
        "https://tauri.localhost",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(tool_capability_router)
app.include_router(tool_contract_router)
app.include_router(workflow_catalog_router)
app.include_router(workflow_design_router)
app.include_router(workflow_sample_data_router)
app.include_router(database_router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "build_id": TERMINAL_RUNTIME_BUILD_ID}


@app.get("/api/v1/version")
async def get_version() -> dict[str, Any]:
    return {
        "item": {
            "build_id": os.environ.get(
                "H2OMETA_RUNTIME_BUILD_ID", TERMINAL_RUNTIME_BUILD_ID
            ),
            "terminal_transport": "websocket",
            "backend_source": os.environ.get("H2OMETA_BACKEND_SOURCE", "unknown"),
        }
    }


@app.get("/api/v1/ssh/status")
async def get_ssh_status(refresh: bool = False) -> dict[str, Any]:
    return await _cached_runtime_payload(
        "ssh_status",
        15,
        _runtime().get_ssh_status,
        status_code=400,
        handled_errors=(RuntimeServiceError,),
        wrapper="item",
        force_refresh=refresh,
    )


@app.get("/api/v1/servers")
async def list_servers(refresh: bool = False) -> dict[str, Any]:
    return await _cached_runtime_payload(
        "servers",
        15,
        _runtime().list_servers,
        status_code=400,
        handled_errors=(RuntimeServiceError,),
        wrapper="data_items",
        force_refresh=refresh,
    )


@app.get("/api/v1/servers/{server_id}")
async def get_server(server_id: str) -> dict[str, Any]:
    return await _run_runtime_payload(
        lambda: _runtime().get_server(server_id),
        status_code=404,
        handled_errors=(RuntimeServiceError,),
        wrapper="data",
    )


@app.get("/api/v1/servers/{server_id}/health")
async def get_server_health(server_id: str) -> dict[str, Any]:
    return await _run_runtime_payload(
        lambda: _runtime().get_server_health(server_id),
        status_code=404,
        handled_errors=(RuntimeServiceError,),
        wrapper="data",
    )


@app.post("/api/v1/servers/{server_id}/health/refresh")
async def refresh_server_health(server_id: str) -> dict[str, Any]:
    return await _run_runtime_payload(
        lambda: _runtime().refresh_server_health(server_id),
        status_code=404,
        handled_errors=(RuntimeServiceError,),
        wrapper="data",
    )


@app.post("/api/v1/servers/{server_id}/ensure-runner")
async def ensure_server_runner(server_id: str) -> dict[str, Any]:
    result = await _run_runtime_payload(
        lambda: _runtime().ensure_remote_runner_ready(server_id),
        status_code=404,
        handled_errors=(RuntimeServiceError,),
        wrapper="data",
    )
    await invalidate_response_cache(prefixes=("ssh_", "servers", "workflow_", "pipelines", "tools", "databases", "runs"))
    return result


@app.post("/api/v1/servers/{server_id}/host-key/accept")
async def accept_server_host_key(server_id: str) -> dict[str, Any]:
    return await _run_runtime_payload(
        lambda: _runtime().accept_server_host_key(server_id),
        status_code=404,
        handled_errors=(RuntimeServiceError,),
        wrapper="data",
    )


@app.post("/api/v1/servers/{server_id}/token/rotate")
async def rotate_server_token(server_id: str) -> dict[str, Any]:
    return await _run_runtime_payload(
        lambda: _runtime().rotate_server_token(server_id),
        status_code=404,
        handled_errors=(RuntimeServiceError,),
        wrapper="data",
    )


@app.post("/api/v1/ssh/connect")
async def connect_ssh(payload: SSHConnectionRequest | None = None) -> dict[str, Any]:
    patch = payload.model_dump(exclude_none=True) if payload is not None else None
    result = await _run_runtime_payload(
        lambda: _runtime().connect_ssh(patch),
        status_code=400,
        handled_errors=(RuntimeServiceError, ValueError, TypeError, KeyError),
        wrapper="item",
    )
    await invalidate_response_cache(prefixes=("ssh_", "servers", "workflow_", "pipelines", "tools", "databases", "runs"))
    return result


@app.post("/api/v1/ssh/disconnect")
async def disconnect_ssh() -> dict[str, Any]:
    result = await _run_runtime_payload(
        _runtime().disconnect_ssh,
        status_code=400,
        handled_errors=(RuntimeServiceError,),
        wrapper="item",
    )
    await invalidate_response_cache(prefixes=("ssh_", "servers", "workflow_", "pipelines", "tools", "databases", "runs"))
    return result


@app.post("/api/v1/ssh/remote-service/stop")
async def stop_ssh_remote_service() -> dict[str, Any]:
    result = await _run_runtime_payload(
        _runtime().stop_remote_runner_service,
        status_code=400,
        handled_errors=(RuntimeServiceError,),
        wrapper="data",
    )
    await invalidate_response_cache(prefixes=("ssh_", "servers", "workflow_", "pipelines", "tools", "databases", "runs"))
    return result


@app.get("/api/v1/ssh/listening-ports")
async def list_ssh_listening_ports() -> dict[str, Any]:
    return await _run_runtime_payload(
        _runtime().list_remote_listening_ports,
        status_code=400,
        handled_errors=(RuntimeServiceError,),
        wrapper="data",
    )


@app.get("/api/v1/ssh/files")
async def list_ssh_remote_files(
    path: str = "",
    directories_only: bool = True,
    limit: int = 500,
    offset: int = 0,
) -> dict[str, Any]:
    bounded_limit = max(1, min(int(limit), 5000))
    bounded_offset = max(0, int(offset))
    return await _run_runtime_payload(
        lambda: _runtime().list_remote_files(
            path,
            directories_only=directories_only,
            limit=bounded_limit,
            offset=bounded_offset,
        ),
        status_code=400,
        handled_errors=(RuntimeServiceError,),
        wrapper="raw",
    )


@app.post("/api/v1/ssh/terminal/sessions")
async def create_terminal_session(
    payload: SSHTerminalCreateRequest | None = None,
) -> dict[str, Any]:
    request = payload or SSHTerminalCreateRequest()
    return await _run_runtime_payload(
        lambda: _runtime().create_terminal_session(cols=request.cols, rows=request.rows),
        status_code=400,
        handled_errors=(RuntimeServiceError, ValueError, TypeError),
        wrapper="item",
    )


@app.delete("/api/v1/ssh/terminal/sessions/{session_id}")
async def close_terminal_session(session_id: str) -> dict[str, Any]:
    return await _run_runtime_payload(
        lambda: _runtime().close_terminal_session(session_id=session_id),
        status_code=400,
        handled_errors=(RuntimeServiceError, ValueError, TypeError),
        wrapper="item",
    )


@app.websocket("/api/v1/ssh/terminal/sessions/{session_id}/stream")
async def stream_terminal_session(
    websocket: WebSocket, session_id: str, cursor: int = 0
) -> None:
    await stream_terminal_session_with_runtime(
        websocket,
        session_id=session_id,
        cursor=cursor,
        runtime_provider=_runtime,
    )


@app.post("/api/v1/ssh/test")
async def test_ssh_connection(
    payload: SSHConnectionRequest | None = None,
) -> dict[str, Any]:
    patch = payload.model_dump(exclude_none=True) if payload is not None else None
    return await _run_runtime_payload(
        lambda: _runtime().test_ssh_connection(patch),
        status_code=400,
        handled_errors=(RuntimeServiceError, ValueError, TypeError, KeyError),
        wrapper="item",
    )


@app.get("/api/v1/runs")
async def list_runs(refresh: bool = False) -> dict[str, Any]:
    return await _cached_runtime_payload(
        "runs",
        10,
        _runtime().list_runs,
        status_code=400,
        handled_errors=(RuntimeServiceError,),
        wrapper="data_items",
        force_refresh=refresh,
    )


@app.post("/api/v1/uploads")
async def upload_file(payload: UploadSubmitRequest) -> dict[str, Any]:
    return await _run_runtime_payload(
        lambda: _runtime().upload_file(payload.model_dump(exclude_none=True)),
        status_code=400,
        handled_errors=(RuntimeServiceError,),
        wrapper="data",
    )


@app.post("/api/v1/runs", status_code=202)
async def submit_run(payload: RunSubmitRequest, response: Response) -> dict[str, Any]:
    request_id = ensure_request_id(payload.requestId)
    try:
        result = await _run_runtime_payload(
            lambda: _runtime().submit_run(payload.model_dump(exclude_none=True) | {"requestId": request_id}),
            status_code=400,
            handled_errors=(RuntimeServiceError,),
            wrapper="raw",
        )
    except HTTPException as exc:
        detail = str(exc.detail)
        if isinstance(exc.detail, dict):
            detail = str(exc.detail.get("detail") or exc.detail.get("title") or detail)
        status_code = classify_run_submission_status(detail=detail, fallback=exc.status_code)
        raise problem_http_exception(
            status=status_code,
            title="Run submission failed",
            detail=detail,
            code="RUNNER_NOT_READY" if status_code >= 500 else "RUN_SUBMIT_FAILED",
            request_id=request_id,
            instance="/api/v1/runs",
        ) from exc
    response.headers["Location"] = result["location"]
    response.headers["Retry-After"] = str(result["retryAfter"])
    response.headers["X-Request-Id"] = str(result.get("requestId") or request_id)
    await invalidate_response_cache("runs")
    return result


@app.get("/api/v1/tools")
async def list_tools_api(refresh: bool = False) -> dict[str, Any]:
    return await _cached_runtime_payload(
        "tools",
        30,
        _runtime().list_tools,
        status_code=400,
        handled_errors=(RuntimeServiceError,),
        wrapper="data",
        force_refresh=refresh,
    )


@app.post("/api/v1/tools", status_code=201)
async def add_tool_api(payload: ToolManifestRequest) -> dict[str, Any]:
    result = await _run_runtime_payload(
        lambda: _runtime().add_tool(payload.model_dump(exclude_none=True)),
        status_code=400,
        handled_errors=(RuntimeServiceError, ValueError, TypeError, KeyError),
        wrapper="data",
    )
    await invalidate_response_cache("tools", "workflow_catalog")
    return result


@app.post("/api/v1/tools/prepare-jobs", status_code=202)
async def create_tool_prepare_job_api(payload: ToolManifestRequest) -> dict[str, Any]:
    result = await _run_runtime_payload(
        lambda: _runtime().create_tool_prepare_job(payload.model_dump(exclude_none=True)),
        status_code=400,
        handled_errors=(RuntimeServiceError, ValueError, TypeError, KeyError),
        wrapper="data",
    )
    await invalidate_response_cache("tools", "workflow_catalog")
    return result


@app.get("/api/v1/tools/prepare-jobs/{job_id}")
async def get_tool_prepare_job_api(job_id: str) -> dict[str, Any]:
    return await _run_runtime_payload(
        lambda: _runtime().get_tool_prepare_job(job_id),
        status_code=404,
        handled_errors=(RuntimeServiceError, ValueError, TypeError, KeyError),
        wrapper="data",
    )


@app.post("/api/v1/tools/prepare-jobs/{job_id}/cancel")
async def cancel_tool_prepare_job_api(job_id: str) -> dict[str, Any]:
    result = await _run_runtime_payload(
        lambda: _runtime().cancel_tool_prepare_job(job_id),
        status_code=404,
        handled_errors=(RuntimeServiceError, ValueError, TypeError, KeyError),
        wrapper="data",
    )
    await invalidate_response_cache("tools", "workflow_catalog")
    return result


@app.patch("/api/v1/tools/{tool_id}/rule-template")
async def update_tool_rule_template_api(tool_id: str, payload: ToolRuleTemplateRequest) -> dict[str, Any]:
    result = await _run_runtime_payload(
        lambda: _runtime().update_tool_rule_template(tool_id, payload.model_dump(exclude_none=True)),
        status_code=400,
        handled_errors=(RuntimeServiceError, ValueError, TypeError, KeyError),
        wrapper="data",
    )
    await invalidate_response_cache("tools", "workflow_catalog")
    return result


@app.delete("/api/v1/tools/{tool_id}")
async def delete_tool_api(tool_id: str) -> dict[str, Any]:
    result = await _run_runtime_payload(
        lambda: _runtime().delete_tool(tool_id),
        status_code=404,
        handled_errors=(RuntimeServiceError,),
        wrapper="data",
    )
    await invalidate_response_cache("tools", "workflow_catalog")
    return result


@app.get("/api/v1/runs/{run_id}")
async def get_run(run_id: str) -> dict[str, Any]:
    return await _run_runtime_payload(
        lambda: _runtime().get_run(run_id),
        status_code=404,
        handled_errors=(RuntimeServiceError,),
        wrapper="data",
    )


@app.get("/api/v1/runs/{run_id}/events")
async def get_run_events(run_id: str) -> dict[str, Any]:
    return await _run_runtime_payload(
        lambda: _runtime().get_run_events(run_id),
        status_code=404,
        handled_errors=(RuntimeServiceError,),
        wrapper="data",
    )


@app.get("/api/v1/runs/{run_id}/logs")
async def get_run_logs(run_id: str, stream: str = "stdout", cursor: str | None = None) -> dict[str, Any]:
    return await _run_runtime_payload(
        lambda: _runtime().get_run_logs(run_id=run_id, stream=stream, cursor=cursor),
        status_code=404,
        handled_errors=(RuntimeServiceError,),
        wrapper="data",
    )


@app.get("/api/v1/runs/{run_id}/results")
async def get_run_results(run_id: str) -> dict[str, Any]:
    return await _run_runtime_payload(
        lambda: _runtime().get_run_results(run_id),
        status_code=404,
        handled_errors=(RuntimeServiceError,),
        wrapper="data",
    )


@app.get("/api/v1/results")
async def list_results() -> dict[str, Any]:
    return await _run_runtime_payload(
        _runtime().list_results,
        status_code=400,
        handled_errors=(RuntimeServiceError,),
        wrapper="data",
    )


@app.get("/api/v1/results/{result_id}")
async def get_result(result_id: str) -> dict[str, Any]:
    return await _run_runtime_payload(
        lambda: _runtime().get_result(result_id),
        status_code=404,
        handled_errors=(RuntimeServiceError,),
        wrapper="data",
    )


@app.get("/api/v1/results/{result_id}/preview")
async def get_result_preview(result_id: str, artifact_id: str | None = None) -> dict[str, Any]:
    return await _run_runtime_payload(
        lambda: _runtime().get_result_preview(
            result_id=result_id, artifact_id=artifact_id
        ),
        status_code=404,
        handled_errors=(RuntimeServiceError,),
        wrapper="data",
    )
