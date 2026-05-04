"""FastAPI app for desktop-shell migration."""

from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Response, WebSocket
from fastapi.middleware.cors import CORSMiddleware

from apps.api.models import (
    CreateProjectRequest,
    DatabaseManifestRequest,
    DatabaseUpdateRequest,
    RunSubmitRequest,
    SSHConnectionRequest,
    SSHTerminalCreateRequest,
    ToolManifestRequest,
    UploadSubmitRequest,
    UpdateProjectRequest,
    UpdateSettingsRequest,
    WorkflowDraftRequest,
)
from apps.api.runtime import get_runtime_service
from apps.api.ssh_terminal_routes import stream_terminal_session_with_runtime
from apps.api.tool_capability_routes import router as tool_capability_router
from apps.api.workflow_templates import (
    create_workflow_draft,
    get_workflow_template,
    list_workflow_drafts,
    list_workflow_modules,
    list_workflow_templates,
    validate_workflow_draft,
)
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


def _runtime():
    return get_runtime_service()


async def _run_sync(
    func,
    *,
    status_code: int,
    handled_errors: tuple[type[Exception], ...],
):
    try:
        return await asyncio.to_thread(func)
    except handled_errors as exc:
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc


async def _run_runtime_payload(
    func,
    *,
    status_code: int,
    handled_errors: tuple[type[Exception], ...],
    wrapper: str = "raw",
):
    value = await _run_sync(
        func, status_code=status_code, handled_errors=handled_errors
    )
    if wrapper == "raw":
        return value
    if wrapper == "item":
        return {"item": value}
    if wrapper == "data":
        return {"data": value}
    if wrapper == "items":
        return {"items": value}
    if wrapper == "data_items":
        return {"data": {"items": value}}
    raise ValueError(f"Unsupported runtime wrapper: {wrapper}")


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


@app.get("/api/v1/settings")
async def get_settings() -> dict[str, Any]:
    return await _run_runtime_payload(
        _runtime().get_settings,
        status_code=400,
        handled_errors=(RuntimeServiceError,),
        wrapper="item",
    )


@app.put("/api/v1/settings")
async def update_settings(payload: UpdateSettingsRequest) -> dict[str, Any]:
    return await _run_runtime_payload(
        lambda: _runtime().update_settings(payload.patch),
        status_code=400,
        handled_errors=(RuntimeServiceError, ValueError, TypeError, KeyError),
        wrapper="item",
    )


@app.get("/api/v1/ssh/status")
async def get_ssh_status() -> dict[str, Any]:
    return await _run_runtime_payload(
        _runtime().get_ssh_status,
        status_code=400,
        handled_errors=(RuntimeServiceError,),
        wrapper="item",
    )


@app.get("/api/v1/servers")
async def list_servers() -> dict[str, Any]:
    return await _run_runtime_payload(
        _runtime().list_servers,
        status_code=400,
        handled_errors=(RuntimeServiceError,),
        wrapper="data_items",
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
    return await _run_runtime_payload(
        lambda: _runtime().ensure_remote_runner_ready(server_id),
        status_code=404,
        handled_errors=(RuntimeServiceError,),
        wrapper="data",
    )


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
    return await _run_runtime_payload(
        lambda: _runtime().connect_ssh(patch),
        status_code=400,
        handled_errors=(RuntimeServiceError, ValueError, TypeError, KeyError),
        wrapper="item",
    )


@app.post("/api/v1/ssh/disconnect")
async def disconnect_ssh() -> dict[str, Any]:
    return await _run_runtime_payload(
        _runtime().disconnect_ssh,
        status_code=400,
        handled_errors=(RuntimeServiceError,),
        wrapper="item",
    )


@app.post("/api/v1/ssh/remote-service/stop")
async def stop_ssh_remote_service() -> dict[str, Any]:
    return await _run_runtime_payload(
        _runtime().stop_remote_runner_service,
        status_code=400,
        handled_errors=(RuntimeServiceError,),
        wrapper="data",
    )


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


@app.get("/api/v1/projects")
async def list_projects(
    sort_by: str = "created_at", include_archived: bool = False
) -> dict[str, Any]:
    return await _run_runtime_payload(
        lambda: _runtime().list_projects(
            sort_by=sort_by, include_archived=include_archived
        ),
        status_code=400,
        handled_errors=(RuntimeServiceError,),
        wrapper="items",
    )


@app.get("/api/v1/runs")
async def list_runs() -> dict[str, Any]:
    return await _run_runtime_payload(
        _runtime().list_runs,
        status_code=400,
        handled_errors=(RuntimeServiceError,),
        wrapper="data_items",
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
    result = await _run_runtime_payload(
        lambda: _runtime().submit_run(payload.model_dump(exclude_none=True)),
        status_code=400,
        handled_errors=(RuntimeServiceError,),
        wrapper="raw",
    )
    response.headers["Location"] = result["location"]
    response.headers["Retry-After"] = str(result["retryAfter"])
    response.headers["X-Request-Id"] = result["requestId"]
    return result


@app.get("/api/v1/pipelines")
async def list_pipelines() -> dict[str, Any]:
    return await _run_runtime_payload(
        _runtime().list_pipelines,
        status_code=400,
        handled_errors=(RuntimeServiceError,),
    )


@app.get("/api/v1/pipelines/{pipeline_id}")
async def get_pipeline(pipeline_id: str) -> dict[str, Any]:
    return await _run_runtime_payload(
        lambda: _runtime().get_pipeline(pipeline_id),
        status_code=404,
        handled_errors=(RuntimeServiceError,),
        wrapper="data",
    )


@app.get("/api/v1/workflow-templates")
async def get_workflow_templates() -> dict[str, Any]:
    return list_workflow_templates()


@app.get("/api/v1/workflow-templates/{template_id}")
async def get_workflow_template_api(template_id: str) -> dict[str, Any]:
    try:
        return get_workflow_template(template_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/v1/workflow-modules")
async def get_workflow_modules() -> dict[str, Any]:
    return list_workflow_modules()


@app.get("/api/v1/tools")
async def list_tools_api() -> dict[str, Any]:
    return await _run_runtime_payload(
        _runtime().list_tools,
        status_code=400,
        handled_errors=(RuntimeServiceError,),
        wrapper="data",
    )


@app.post("/api/v1/tools", status_code=201)
async def add_tool_api(payload: ToolManifestRequest) -> dict[str, Any]:
    return await _run_runtime_payload(
        lambda: _runtime().add_tool(payload.model_dump(exclude_none=True)),
        status_code=400,
        handled_errors=(RuntimeServiceError, ValueError, TypeError, KeyError),
        wrapper="data",
    )


@app.delete("/api/v1/tools/{tool_id}")
async def delete_tool_api(tool_id: str) -> dict[str, Any]:
    return await _run_runtime_payload(
        lambda: _runtime().delete_tool(tool_id),
        status_code=404,
        handled_errors=(RuntimeServiceError,),
        wrapper="data",
    )


@app.post("/api/v1/tools/{tool_id}/check")
async def check_tool_api(tool_id: str) -> dict[str, Any]:
    return await _run_runtime_payload(
        lambda: _runtime().check_tool(tool_id),
        status_code=400,
        handled_errors=(RuntimeServiceError,),
        wrapper="data",
    )


@app.get("/api/v1/databases")
async def list_databases_api() -> dict[str, Any]:
    return await _run_runtime_payload(
        _runtime().list_databases,
        status_code=400,
        handled_errors=(RuntimeServiceError,),
        wrapper="data",
    )


@app.get("/api/v1/database-templates")
async def list_database_templates_api() -> dict[str, Any]:
    return await _run_runtime_payload(
        _runtime().list_database_templates,
        status_code=400,
        handled_errors=(RuntimeServiceError,),
        wrapper="data",
    )


@app.post("/api/v1/databases", status_code=201)
async def add_database_api(payload: DatabaseManifestRequest) -> dict[str, Any]:
    try:
        return await asyncio.to_thread(lambda: _runtime().add_database(payload.model_dump(exclude_none=True)))
    except RuntimeServiceError as exc:
        detail = str(exc)
        if detail.startswith("DATABASE_CANDIDATES:"):
            try:
                import json

                payload_detail = json.loads(detail.removeprefix("DATABASE_CANDIDATES:"))
            except Exception:
                payload_detail = detail
            raise HTTPException(status_code=409, detail=payload_detail) from exc
        raise HTTPException(status_code=400, detail=detail) from exc
    except (ValueError, TypeError, KeyError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.delete("/api/v1/databases/{database_id}")
async def delete_database_api(database_id: str) -> dict[str, Any]:
    return await _run_runtime_payload(
        lambda: _runtime().delete_database(database_id),
        status_code=404,
        handled_errors=(RuntimeServiceError,),
        wrapper="data",
    )


@app.patch("/api/v1/databases/{database_id}")
async def update_database_api(database_id: str, payload: DatabaseUpdateRequest) -> dict[str, Any]:
    return await _run_runtime_payload(
        lambda: _runtime().update_database(database_id, payload.model_dump(exclude_none=True)),
        status_code=400,
        handled_errors=(RuntimeServiceError, ValueError, TypeError, KeyError),
        wrapper="data",
    )


@app.post("/api/v1/databases/{database_id}/check")
async def check_database_api(database_id: str) -> dict[str, Any]:
    return await _run_runtime_payload(
        lambda: _runtime().check_database(database_id),
        status_code=400,
        handled_errors=(RuntimeServiceError,),
        wrapper="data",
    )


@app.post("/api/v1/workflow-drafts/validate")
async def validate_workflow_draft_api(payload: WorkflowDraftRequest) -> dict[str, Any]:
    try:
        return validate_workflow_draft(payload.model_dump(exclude_none=True))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/v1/workflow-drafts")
async def get_workflow_drafts() -> dict[str, Any]:
    return list_workflow_drafts()


@app.post("/api/v1/workflow-drafts", status_code=201)
async def create_workflow_draft_api(payload: WorkflowDraftRequest) -> dict[str, Any]:
    try:
        return create_workflow_draft(payload.model_dump(exclude_none=True))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


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


@app.get("/api/v1/projects/current")
async def get_current_project() -> dict[str, Any]:
    return await _run_runtime_payload(
        _runtime().get_current_project,
        status_code=400,
        handled_errors=(RuntimeServiceError,),
        wrapper="item",
    )


@app.get("/api/v1/projects/{project_id}")
async def get_project(project_id: str) -> dict[str, Any]:
    return await _run_runtime_payload(
        lambda: _runtime().get_project(project_id),
        status_code=404,
        handled_errors=(RuntimeServiceError,),
        wrapper="data",
    )


@app.post("/api/v1/projects")
async def create_project(payload: CreateProjectRequest) -> dict[str, Any]:
    return await _run_runtime_payload(
        lambda: _runtime().create_project(
            name=payload.name,
            description=payload.description,
            open_after_create=payload.open_after_create,
        ),
        status_code=400,
        handled_errors=(RuntimeServiceError, ValueError, KeyError),
        wrapper="item",
    )


@app.patch("/api/v1/projects/{project_id}")
async def update_project(
    project_id: str, payload: UpdateProjectRequest
) -> dict[str, Any]:
    patch = payload.model_dump(exclude_none=True)
    return await _run_runtime_payload(
        lambda: _runtime().update_project(project_id=project_id, patch=patch),
        status_code=400,
        handled_errors=(RuntimeServiceError, ValueError, KeyError, FileNotFoundError),
        wrapper="item",
    )


@app.post("/api/v1/projects/{project_id}/archive")
async def archive_project(project_id: str) -> dict[str, Any]:
    return await _run_runtime_payload(
        lambda: _runtime().archive_project(project_id=project_id),
        status_code=400,
        handled_errors=(RuntimeServiceError, ValueError, KeyError, FileNotFoundError),
        wrapper="item",
    )


@app.post("/api/v1/projects/{project_id}/restore")
async def restore_project(project_id: str) -> dict[str, Any]:
    return await _run_runtime_payload(
        lambda: _runtime().restore_project(project_id=project_id),
        status_code=400,
        handled_errors=(RuntimeServiceError, ValueError, KeyError, FileNotFoundError),
        wrapper="item",
    )


@app.delete("/api/v1/projects/{project_id}")
async def delete_project(project_id: str) -> dict[str, Any]:
    return await _run_runtime_payload(
        lambda: _runtime().delete_project(project_id=project_id),
        status_code=400,
        handled_errors=(RuntimeServiceError, ValueError, KeyError, FileNotFoundError),
        wrapper="item",
    )


@app.post("/api/v1/projects/{project_id}/open")
async def open_project(project_id: str) -> dict[str, Any]:
    return await _run_runtime_payload(
        lambda: _runtime().open_project(project_id),
        status_code=400,
        handled_errors=(RuntimeServiceError, ValueError, KeyError, FileNotFoundError),
        wrapper="item",
    )
