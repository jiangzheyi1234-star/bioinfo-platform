"""FastAPI app for desktop-shell migration."""

from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Response, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from apps.api.models import (
    CreateProjectRequest,
    RunSubmitRequest,
    SSHConnectionRequest,
    SSHTerminalCreateRequest,
    UploadSubmitRequest,
    UpdateProjectRequest,
    UpdateSettingsRequest,
    WorkflowDraftRequest,
)
from apps.api.runtime import get_runtime_service
from apps.api.workflow_templates import (
    create_workflow_draft,
    get_workflow_template,
    list_workflow_drafts,
    list_workflow_modules,
    list_workflow_templates,
    validate_workflow_draft,
)
from core.app_runtime import RuntimeServiceError


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
        "http://localhost:3100",
        "http://127.0.0.1:3100",
        "tauri://localhost",
        "http://tauri.localhost",
        "https://tauri.localhost",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


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


def _terminal_state_event(snapshot: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "state",
        "connected": bool(snapshot.get("connected")),
        "input_enabled": bool(snapshot.get("input_enabled")),
        "message": str(snapshot.get("message") or ""),
    }


async def _send_terminal_snapshot(
    websocket: WebSocket,
    *,
    snapshot: dict[str, Any],
    last_state: tuple[bool, bool, str] | None,
) -> tuple[int, tuple[bool, bool, str]]:
    output = str(snapshot.get("output") or "")
    if output:
        await websocket.send_json({"type": "output", "data": output})
    state = (
        bool(snapshot.get("connected")),
        bool(snapshot.get("input_enabled")),
        str(snapshot.get("message") or ""),
    )
    if state != last_state and not bool(snapshot.get("closed")):
        await websocket.send_json(_terminal_state_event(snapshot))
    return int(snapshot.get("cursor") or 0), state


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
    item = await _run_sync(
        _runtime().get_settings,
        status_code=400,
        handled_errors=(RuntimeServiceError,),
    )
    return {"item": item}


@app.put("/api/v1/settings")
async def update_settings(payload: UpdateSettingsRequest) -> dict[str, Any]:
    item = await _run_sync(
        lambda: _runtime().update_settings(payload.patch),
        status_code=400,
        handled_errors=(RuntimeServiceError, ValueError, TypeError, KeyError),
    )
    return {"item": item}


@app.get("/api/v1/ssh/status")
async def get_ssh_status() -> dict[str, Any]:
    item = await _run_sync(
        _runtime().get_ssh_status,
        status_code=400,
        handled_errors=(RuntimeServiceError,),
    )
    return {"item": item}


@app.get("/api/v1/servers")
async def list_servers() -> dict[str, Any]:
    items = await _run_sync(
        _runtime().list_servers,
        status_code=400,
        handled_errors=(RuntimeServiceError,),
    )
    return {"data": {"items": items}}


@app.get("/api/v1/servers/{server_id}")
async def get_server(server_id: str) -> dict[str, Any]:
    data = await _run_sync(
        lambda: _runtime().get_server(server_id),
        status_code=404,
        handled_errors=(RuntimeServiceError,),
    )
    return {"data": data}


@app.get("/api/v1/servers/{server_id}/health")
async def get_server_health(server_id: str) -> dict[str, Any]:
    data = await _run_sync(
        lambda: _runtime().get_server_health(server_id),
        status_code=404,
        handled_errors=(RuntimeServiceError,),
    )
    return {"data": data}


@app.post("/api/v1/servers/{server_id}/health/refresh")
async def refresh_server_health(server_id: str) -> dict[str, Any]:
    return await _run_sync(
        lambda: _runtime().refresh_server_health(server_id),
        status_code=404,
        handled_errors=(RuntimeServiceError,),
    )


@app.post("/api/v1/servers/{server_id}/ensure-runner")
async def ensure_server_runner(server_id: str) -> dict[str, Any]:
    return await _run_sync(
        lambda: _runtime().ensure_remote_runner_ready(server_id),
        status_code=404,
        handled_errors=(RuntimeServiceError,),
    )


@app.post("/api/v1/servers/{server_id}/host-key/accept")
async def accept_server_host_key(server_id: str) -> dict[str, Any]:
    return await _run_sync(
        lambda: _runtime().accept_server_host_key(server_id),
        status_code=404,
        handled_errors=(RuntimeServiceError,),
    )


@app.post("/api/v1/servers/{server_id}/token/rotate")
async def rotate_server_token(server_id: str) -> dict[str, Any]:
    return await _run_sync(
        lambda: _runtime().rotate_server_token(server_id),
        status_code=404,
        handled_errors=(RuntimeServiceError,),
    )


@app.post("/api/v1/ssh/connect")
async def connect_ssh(payload: SSHConnectionRequest | None = None) -> dict[str, Any]:
    patch = payload.model_dump(exclude_none=True) if payload is not None else None
    item = await _run_sync(
        lambda: _runtime().connect_ssh(patch),
        status_code=400,
        handled_errors=(RuntimeServiceError, ValueError, TypeError, KeyError),
    )
    return {"item": item}


@app.post("/api/v1/ssh/disconnect")
async def disconnect_ssh() -> dict[str, Any]:
    item = await _run_sync(
        _runtime().disconnect_ssh,
        status_code=400,
        handled_errors=(RuntimeServiceError,),
    )
    return {"item": item}


@app.get("/api/v1/ssh/listening-ports")
async def list_ssh_listening_ports() -> dict[str, Any]:
    return await _run_sync(
        _runtime().list_remote_listening_ports,
        status_code=400,
        handled_errors=(RuntimeServiceError,),
    )


@app.post("/api/v1/ssh/terminal/sessions")
async def create_terminal_session(
    payload: SSHTerminalCreateRequest | None = None,
) -> dict[str, Any]:
    request = payload or SSHTerminalCreateRequest()
    item = await _run_sync(
        lambda: _runtime().create_terminal_session(cols=request.cols, rows=request.rows),
        status_code=400,
        handled_errors=(RuntimeServiceError, ValueError, TypeError),
    )
    return {"item": item}



@app.delete("/api/v1/ssh/terminal/sessions/{session_id}")
async def close_terminal_session(session_id: str) -> dict[str, Any]:
    item = await _run_sync(
        lambda: _runtime().close_terminal_session(session_id=session_id),
        status_code=400,
        handled_errors=(RuntimeServiceError, ValueError, TypeError),
    )
    return {"item": item}


@app.websocket("/api/v1/ssh/terminal/sessions/{session_id}/stream")
async def stream_terminal_session(
    websocket: WebSocket, session_id: str, cursor: int = 0
) -> None:
    await websocket.accept()
    try:
        session = _runtime().get_terminal_session(session_id=session_id)
    except (RuntimeServiceError, ValueError, TypeError):
        await websocket.send_json({"type": "closed", "message": "终端会话不存在"})
        await asyncio.sleep(0.1)
        await websocket.close(code=1000)
        return

    if session is None:
        await websocket.send_json({"type": "closed", "message": "终端会话已关闭"})
        await asyncio.sleep(0.1)
        await websocket.close(code=1000)
        return

    async def pump_output() -> None:
        current_cursor = max(0, int(cursor or 0))
        version = -1
        last_state: tuple[bool, bool, str] | None = None

        await websocket.send_json({"type": "ready", "session_id": session_id})
        snapshot, version = await asyncio.to_thread(
            session.wait_for_update,
            cursor=current_cursor,
            version=version,
            timeout=0.0,
        )
        current_cursor, last_state = await _send_terminal_snapshot(
            websocket,
            snapshot=snapshot,
            last_state=last_state,
        )
        if bool(snapshot.get("closed")):
            await websocket.send_json(
                {"type": "closed", "message": str(snapshot.get("message") or "")}
            )
            return

        while True:
            snapshot, next_version = await asyncio.to_thread(
                session.wait_for_update,
                cursor=current_cursor,
                version=version,
                timeout=30.0,
            )
            if (
                next_version == version
                and int(snapshot.get("cursor") or 0) == current_cursor
                and not bool(snapshot.get("closed"))
            ):
                continue
            version = next_version
            current_cursor, last_state = await _send_terminal_snapshot(
                websocket,
                snapshot=snapshot,
                last_state=last_state,
            )
            if bool(snapshot.get("closed")):
                await websocket.send_json(
                    {"type": "closed", "message": str(snapshot.get("message") or "")}
                )
                return

    async def receive_input() -> None:
        while True:
            payload = await websocket.receive_json()
            if not isinstance(payload, dict):
                await websocket.send_json(
                    {"type": "error", "message": "invalid terminal payload"}
                )
                continue
            message_type = str(payload.get("type") or "").strip().lower()
            if message_type == "input":
                data = str(payload.get("data") or "")
                if not data:
                    continue
                await asyncio.to_thread(
                    _runtime().send_terminal_input, session_id=session_id, data=data
                )
                continue
            if message_type == "resize":
                await asyncio.to_thread(
                    _runtime().resize_terminal_session,
                    session_id=session_id,
                    cols=int(payload.get("cols") or 120),
                    rows=int(payload.get("rows") or 28),
                )
                continue
            if message_type == "ping":
                await websocket.send_json({"type": "pong"})
                continue
            await websocket.send_json(
                {
                    "type": "error",
                    "message": f"unsupported terminal message type: {message_type or '<empty>'}",
                }
            )

    tasks = {
        asyncio.create_task(pump_output()),
        asyncio.create_task(receive_input()),
    }
    try:
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_EXCEPTION)
        for task in done:
            exc = task.exception()
            if exc is not None:
                raise exc
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
    except WebSocketDisconnect:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
    except asyncio.CancelledError:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
    except Exception as exc:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await websocket.send_json(
            {"type": "error", "message": str(exc) or "terminal stream failed"}
        )
        await websocket.close(code=1011)


@app.post("/api/v1/ssh/test")
async def test_ssh_connection(
    payload: SSHConnectionRequest | None = None,
) -> dict[str, Any]:
    patch = payload.model_dump(exclude_none=True) if payload is not None else None
    item = await _run_sync(
        lambda: _runtime().test_ssh_connection(patch),
        status_code=400,
        handled_errors=(RuntimeServiceError, ValueError, TypeError, KeyError),
    )
    return {"item": item}


@app.get("/api/v1/projects")
async def list_projects(
    sort_by: str = "created_at", include_archived: bool = False
) -> dict[str, Any]:
    items = await _run_sync(
        lambda: _runtime().list_projects(
            sort_by=sort_by, include_archived=include_archived
        ),
        status_code=400,
        handled_errors=(RuntimeServiceError,),
    )
    return {"items": items}


@app.get("/api/v1/runs")
async def list_runs() -> dict[str, Any]:
    items = await _run_sync(
        _runtime().list_runs,
        status_code=400,
        handled_errors=(RuntimeServiceError,),
    )
    return {"data": {"items": items}}


@app.post("/api/v1/uploads")
async def upload_file(payload: UploadSubmitRequest) -> dict[str, Any]:
    data = await _run_sync(
        lambda: _runtime().upload_file(payload.model_dump(exclude_none=True)),
        status_code=400,
        handled_errors=(RuntimeServiceError,),
    )
    return {"data": data}


@app.post("/api/v1/runs", status_code=202)
async def submit_run(payload: RunSubmitRequest, response: Response) -> dict[str, Any]:
    result = await _run_sync(
        lambda: _runtime().submit_run(payload.model_dump(exclude_none=True)),
        status_code=400,
        handled_errors=(RuntimeServiceError,),
    )
    response.headers["Location"] = result["location"]
    response.headers["Retry-After"] = str(result["retryAfter"])
    response.headers["X-Request-Id"] = result["requestId"]
    return result


@app.get("/api/v1/pipelines")
async def list_pipelines() -> dict[str, Any]:
    return await _run_sync(
        _runtime().list_pipelines,
        status_code=400,
        handled_errors=(RuntimeServiceError,),
    )


@app.get("/api/v1/pipelines/{pipeline_id}")
async def get_pipeline(pipeline_id: str) -> dict[str, Any]:
    return await _run_sync(
        lambda: _runtime().get_pipeline(pipeline_id),
        status_code=404,
        handled_errors=(RuntimeServiceError,),
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
    return await _run_sync(
        lambda: _runtime().get_run(run_id),
        status_code=404,
        handled_errors=(RuntimeServiceError,),
    )


@app.get("/api/v1/runs/{run_id}/events")
async def get_run_events(run_id: str) -> dict[str, Any]:
    return await _run_sync(
        lambda: _runtime().get_run_events(run_id),
        status_code=404,
        handled_errors=(RuntimeServiceError,),
    )


@app.get("/api/v1/runs/{run_id}/logs")
async def get_run_logs(run_id: str, stream: str = "stdout", cursor: str | None = None) -> dict[str, Any]:
    return await _run_sync(
        lambda: _runtime().get_run_logs(run_id=run_id, stream=stream, cursor=cursor),
        status_code=404,
        handled_errors=(RuntimeServiceError,),
    )


@app.get("/api/v1/runs/{run_id}/results")
async def get_run_results(run_id: str) -> dict[str, Any]:
    return await _run_sync(
        lambda: _runtime().get_run_results(run_id),
        status_code=404,
        handled_errors=(RuntimeServiceError,),
    )


@app.get("/api/v1/results")
async def list_results() -> dict[str, Any]:
    return await _run_sync(
        _runtime().list_results,
        status_code=400,
        handled_errors=(RuntimeServiceError,),
    )


@app.get("/api/v1/results/{result_id}")
async def get_result(result_id: str) -> dict[str, Any]:
    return await _run_sync(
        lambda: _runtime().get_result(result_id),
        status_code=404,
        handled_errors=(RuntimeServiceError,),
    )


@app.get("/api/v1/results/{result_id}/preview")
async def get_result_preview(result_id: str, artifact_id: str | None = None) -> dict[str, Any]:
    return await _run_sync(
        lambda: _runtime().get_result_preview(
            result_id=result_id, artifact_id=artifact_id
        ),
        status_code=404,
        handled_errors=(RuntimeServiceError,),
    )


@app.get("/api/v1/projects/current")
async def get_current_project() -> dict[str, Any]:
    item = await _run_sync(
        _runtime().get_current_project,
        status_code=400,
        handled_errors=(RuntimeServiceError,),
    )
    return {"item": item}


@app.get("/api/v1/projects/{project_id}")
async def get_project(project_id: str) -> dict[str, Any]:
    data = await _run_sync(
        lambda: _runtime().get_project(project_id),
        status_code=404,
        handled_errors=(RuntimeServiceError,),
    )
    return {"data": data}


@app.post("/api/v1/projects")
async def create_project(payload: CreateProjectRequest) -> dict[str, Any]:
    item = await _run_sync(
        lambda: _runtime().create_project(
            name=payload.name,
            description=payload.description,
            open_after_create=payload.open_after_create,
        ),
        status_code=400,
        handled_errors=(RuntimeServiceError, ValueError, KeyError),
    )
    return {"item": item}


@app.patch("/api/v1/projects/{project_id}")
async def update_project(
    project_id: str, payload: UpdateProjectRequest
) -> dict[str, Any]:
    patch = payload.model_dump(exclude_none=True)
    item = await _run_sync(
        lambda: _runtime().update_project(project_id=project_id, patch=patch),
        status_code=400,
        handled_errors=(RuntimeServiceError, ValueError, KeyError, FileNotFoundError),
    )
    return {"item": item}


@app.post("/api/v1/projects/{project_id}/archive")
async def archive_project(project_id: str) -> dict[str, Any]:
    item = await _run_sync(
        lambda: _runtime().archive_project(project_id=project_id),
        status_code=400,
        handled_errors=(RuntimeServiceError, ValueError, KeyError, FileNotFoundError),
    )
    return {"item": item}


@app.post("/api/v1/projects/{project_id}/restore")
async def restore_project(project_id: str) -> dict[str, Any]:
    item = await _run_sync(
        lambda: _runtime().restore_project(project_id=project_id),
        status_code=400,
        handled_errors=(RuntimeServiceError, ValueError, KeyError, FileNotFoundError),
    )
    return {"item": item}


@app.delete("/api/v1/projects/{project_id}")
async def delete_project(project_id: str) -> dict[str, Any]:
    item = await _run_sync(
        lambda: _runtime().delete_project(project_id=project_id),
        status_code=400,
        handled_errors=(RuntimeServiceError, ValueError, KeyError, FileNotFoundError),
    )
    return {"item": item}


@app.post("/api/v1/projects/{project_id}/open")
async def open_project(project_id: str) -> dict[str, Any]:
    item = await _run_sync(
        lambda: _runtime().open_project(project_id),
        status_code=400,
        handled_errors=(RuntimeServiceError, ValueError, KeyError, FileNotFoundError),
    )
    return {"item": item}
