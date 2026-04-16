"""FastAPI app for desktop-shell migration."""

from __future__ import annotations

import asyncio
import os
from typing import Any

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from apps.api.models import (
    CreateProjectRequest,
    SSHConnectionRequest,
    SSHTerminalCreateRequest,
    UpdateProjectRequest,
    UpdateSettingsRequest,
)
from apps.api.runtime import get_runtime_service
from core.app_runtime import RuntimeServiceError

app = FastAPI(
    title="H2OMeta Local API",
    version="0.1.0",
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


@app.on_event("startup")
async def on_startup() -> None:
    _runtime()


@app.on_event("shutdown")
async def on_shutdown() -> None:
    runtime = get_runtime_service()
    runtime.shutdown()
    get_runtime_service.cache_clear()


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
    try:
        return {"item": _runtime().get_settings()}
    except RuntimeServiceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.put("/api/v1/settings")
async def update_settings(payload: UpdateSettingsRequest) -> dict[str, Any]:
    try:
        return {"item": _runtime().update_settings(payload.patch)}
    except (RuntimeServiceError, ValueError, TypeError, KeyError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/v1/ssh/status")
async def get_ssh_status() -> dict[str, Any]:
    try:
        return {"item": _runtime().get_ssh_status()}
    except RuntimeServiceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/v1/ssh/connect")
async def connect_ssh(payload: SSHConnectionRequest | None = None) -> dict[str, Any]:
    try:
        patch = payload.model_dump(exclude_none=True) if payload is not None else None
        return {"item": _runtime().connect_ssh(patch)}
    except (RuntimeServiceError, ValueError, TypeError, KeyError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/v1/ssh/disconnect")
async def disconnect_ssh() -> dict[str, Any]:
    try:
        return {"item": _runtime().disconnect_ssh()}
    except RuntimeServiceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/v1/ssh/terminal/sessions")
async def create_terminal_session(
    payload: SSHTerminalCreateRequest | None = None,
) -> dict[str, Any]:
    try:
        request = payload or SSHTerminalCreateRequest()
        return {
            "item": _runtime().create_terminal_session(
                cols=request.cols, rows=request.rows
            )
        }
    except (RuntimeServiceError, ValueError, TypeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.delete("/api/v1/ssh/terminal/sessions/{session_id}")
async def close_terminal_session(session_id: str) -> dict[str, Any]:
    try:
        return {"item": _runtime().close_terminal_session(session_id=session_id)}
    except (RuntimeServiceError, ValueError, TypeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.websocket("/api/v1/ssh/terminal/sessions/{session_id}/stream")
async def stream_terminal_session(
    websocket: WebSocket, session_id: str, cursor: int = 0
) -> None:
    await websocket.accept()
    try:
        session = _runtime().get_terminal_session(session_id=session_id)
    except (RuntimeServiceError, ValueError, TypeError) as exc:
        await websocket.send_json(
            {"type": "closed", "message": "终端会话不存在或已关闭"}
        )
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
                _runtime().send_terminal_input(session_id=session_id, data=data)
                continue
            if message_type == "resize":
                _runtime().resize_terminal_session(
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
    try:
        patch = payload.model_dump(exclude_none=True) if payload is not None else None
        return {"item": _runtime().test_ssh_connection(patch)}
    except (RuntimeServiceError, ValueError, TypeError, KeyError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/v1/projects")
async def list_projects(
    sort_by: str = "created_at", include_archived: bool = False
) -> dict[str, Any]:
    try:
        return {
            "items": _runtime().list_projects(
                sort_by=sort_by, include_archived=include_archived
            )
        }
    except RuntimeServiceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/v1/projects/current")
async def get_current_project() -> dict[str, Any]:
    try:
        return {"item": _runtime().get_current_project()}
    except RuntimeServiceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/v1/projects")
async def create_project(payload: CreateProjectRequest) -> dict[str, Any]:
    try:
        item = _runtime().create_project(
            name=payload.name,
            description=payload.description,
            open_after_create=payload.open_after_create,
        )
        return {"item": item}
    except (RuntimeServiceError, ValueError, KeyError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.patch("/api/v1/projects/{project_id}")
async def update_project(
    project_id: str, payload: UpdateProjectRequest
) -> dict[str, Any]:
    try:
        patch = payload.model_dump(exclude_none=True)
        return {"item": _runtime().update_project(project_id=project_id, patch=patch)}
    except (RuntimeServiceError, ValueError, KeyError, FileNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/v1/projects/{project_id}/archive")
async def archive_project(project_id: str) -> dict[str, Any]:
    try:
        return {"item": _runtime().archive_project(project_id=project_id)}
    except (RuntimeServiceError, ValueError, KeyError, FileNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/v1/projects/{project_id}/restore")
async def restore_project(project_id: str) -> dict[str, Any]:
    try:
        return {"item": _runtime().restore_project(project_id=project_id)}
    except (RuntimeServiceError, ValueError, KeyError, FileNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.delete("/api/v1/projects/{project_id}")
async def delete_project(project_id: str) -> dict[str, Any]:
    try:
        return {"item": _runtime().delete_project(project_id=project_id)}
    except (RuntimeServiceError, ValueError, KeyError, FileNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/v1/projects/{project_id}/open")
async def open_project(project_id: str) -> dict[str, Any]:
    try:
        return {"item": _runtime().open_project(project_id)}
    except (RuntimeServiceError, ValueError, KeyError, FileNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
