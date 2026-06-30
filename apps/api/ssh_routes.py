"""SSH control and terminal routes for the local API."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query, WebSocket

from apps.api.models import RunnerReleasePruneRunRequest, SSHConnectionRequest, SSHTerminalCreateRequest
from apps.api.ssh_control_service import (
    accept_server_host_key_from_request,
    close_terminal_session_from_request,
    connect_ssh_from_request,
    create_terminal_session_from_request,
    disconnect_ssh_from_request,
    ensure_server_runner_from_request,
    get_server_from_request,
    get_server_execution_diagnostics_from_request,
    get_server_health_from_request,
    get_server_operator_diagnostics_from_request,
    get_ssh_status_from_request,
    list_servers_from_request,
    list_ssh_listening_ports_from_request,
    list_ssh_remote_files_from_request,
    preview_server_runner_release_prune_from_request,
    refresh_server_health_from_request,
    rotate_server_token_from_request,
    run_server_runner_release_prune_from_request,
    stop_ssh_remote_service_from_request,
    stream_terminal_session_from_request,
    test_ssh_connection_from_request,
    upgrade_server_runner_from_request,
)


router = APIRouter()


@router.get("/api/v1/ssh/status")
async def get_ssh_status(refresh: bool = False) -> dict[str, Any]:
    return await get_ssh_status_from_request(refresh)


@router.get("/api/v1/servers")
async def list_servers(refresh: bool = False) -> dict[str, Any]:
    return await list_servers_from_request(refresh)


@router.get("/api/v1/servers/{server_id}")
async def get_server(server_id: str) -> dict[str, Any]:
    return await get_server_from_request(server_id)


@router.get("/api/v1/servers/{server_id}/health")
async def get_server_health(server_id: str) -> dict[str, Any]:
    return await get_server_health_from_request(server_id)


@router.get("/api/v1/servers/{server_id}/execution-diagnostics")
async def get_server_execution_diagnostics(server_id: str) -> dict[str, Any]:
    return await get_server_execution_diagnostics_from_request(server_id)


@router.get("/api/v1/servers/{server_id}/operator-diagnostics")
async def get_server_operator_diagnostics(
    server_id: str,
    run_id: str = "",
    scenario_id: str = "",
) -> dict[str, Any]:
    return await get_server_operator_diagnostics_from_request(
        server_id,
        run_id=run_id,
        scenario_id=scenario_id,
    )


@router.post("/api/v1/servers/{server_id}/health/refresh")
async def refresh_server_health(server_id: str) -> dict[str, Any]:
    return await refresh_server_health_from_request(server_id)


@router.post("/api/v1/servers/{server_id}/ensure-runner")
async def ensure_server_runner(server_id: str) -> dict[str, Any]:
    return await ensure_server_runner_from_request(server_id)


@router.post("/api/v1/servers/{server_id}/runner/upgrade")
async def upgrade_server_runner(server_id: str) -> dict[str, Any]:
    return await upgrade_server_runner_from_request(server_id)


@router.post("/api/v1/servers/{server_id}/runner/releases/prune/preview")
async def preview_server_runner_release_prune(server_id: str) -> dict[str, Any]:
    return await preview_server_runner_release_prune_from_request(server_id)


@router.post("/api/v1/servers/{server_id}/runner/releases/prune/run")
async def run_server_runner_release_prune(
    server_id: str,
    payload: RunnerReleasePruneRunRequest,
) -> dict[str, Any]:
    return await run_server_runner_release_prune_from_request(server_id, payload)


@router.post("/api/v1/servers/{server_id}/host-key/accept")
async def accept_server_host_key(server_id: str) -> dict[str, Any]:
    return await accept_server_host_key_from_request(server_id)


@router.post("/api/v1/servers/{server_id}/token/rotate")
async def rotate_server_token(server_id: str) -> dict[str, Any]:
    return await rotate_server_token_from_request(server_id)


@router.post("/api/v1/ssh/connect")
async def connect_ssh(payload: SSHConnectionRequest | None = None) -> dict[str, Any]:
    return await connect_ssh_from_request(payload)


@router.post("/api/v1/ssh/disconnect")
async def disconnect_ssh() -> dict[str, Any]:
    return await disconnect_ssh_from_request()


@router.post("/api/v1/ssh/remote-service/stop")
async def stop_ssh_remote_service() -> dict[str, Any]:
    return await stop_ssh_remote_service_from_request()


@router.get("/api/v1/ssh/listening-ports")
async def list_ssh_listening_ports() -> dict[str, Any]:
    return await list_ssh_listening_ports_from_request()


@router.get("/api/v1/ssh/files")
async def list_ssh_remote_files(
    path: str = "",
    directories_only: bool = True,
    limit: int = Query(default=500, ge=1, le=5000),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    return await list_ssh_remote_files_from_request(
        path,
        directories_only=directories_only,
        limit=limit,
        offset=offset,
    )


@router.post("/api/v1/ssh/terminal/sessions")
async def create_terminal_session(
    payload: SSHTerminalCreateRequest | None = None,
) -> dict[str, Any]:
    return await create_terminal_session_from_request(payload)


@router.delete("/api/v1/ssh/terminal/sessions/{session_id}")
async def close_terminal_session(session_id: str) -> dict[str, Any]:
    return await close_terminal_session_from_request(session_id)


@router.websocket("/api/v1/ssh/terminal/sessions/{session_id}/stream")
async def stream_terminal_session(
    websocket: WebSocket, session_id: str, cursor: int = Query(default=0, ge=0)
) -> None:
    await stream_terminal_session_from_request(
        websocket,
        session_id=session_id,
        cursor=cursor,
    )


@router.post("/api/v1/ssh/test")
async def test_ssh_connection(
    payload: SSHConnectionRequest | None = None,
) -> dict[str, Any]:
    return await test_ssh_connection_from_request(payload)
