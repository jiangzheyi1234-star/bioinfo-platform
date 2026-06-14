from __future__ import annotations

from typing import Any

from apps.api.models import SSHConnectionRequest, SSHTerminalCreateRequest
from apps.api.response_cache import invalidate_response_cache
from apps.api.route_utils import (
    cached_runtime_payload,
    request_payload,
    run_runtime_payload,
    runtime_service,
)
from apps.api.ssh_terminal_service import TerminalWebSocket, stream_terminal_session_with_runtime


SSH_STATE_CACHE_PREFIXES = (
    "ssh_",
    "servers",
    "workflow_",
    "pipelines",
    "tools",
    "databases",
    "runs",
)


async def get_ssh_status_from_request(refresh: bool) -> dict[str, Any]:
    return await cached_runtime_payload(
        "ssh_status",
        15,
        runtime_service().get_ssh_status,
        wrapper="item",
        force_refresh=refresh,
    )


async def list_servers_from_request(refresh: bool) -> dict[str, Any]:
    return await cached_runtime_payload(
        "servers",
        15,
        runtime_service().list_servers,
        wrapper="data_items",
        force_refresh=refresh,
    )


async def get_server_from_request(server_id: str) -> dict[str, Any]:
    return await run_runtime_payload(
        lambda: runtime_service().get_server(server_id),
        wrapper="data",
    )


async def get_server_health_from_request(server_id: str) -> dict[str, Any]:
    return await run_runtime_payload(
        lambda: runtime_service().get_server_health(server_id),
        wrapper="data",
    )


async def refresh_server_health_from_request(server_id: str) -> dict[str, Any]:
    return await run_runtime_payload(
        lambda: runtime_service().refresh_server_health(server_id),
        wrapper="raw",
    )


async def get_server_execution_diagnostics_from_request(server_id: str) -> dict[str, Any]:
    return await run_runtime_payload(
        lambda: runtime_service().get_runner_execution_diagnostics(server_id),
        wrapper="data",
    )


async def ensure_server_runner_from_request(server_id: str) -> dict[str, Any]:
    result = await run_runtime_payload(
        lambda: runtime_service().ensure_remote_runner_ready(server_id),
        wrapper="raw",
    )
    await _invalidate_ssh_state_cache()
    return result


async def accept_server_host_key_from_request(server_id: str) -> dict[str, Any]:
    return await run_runtime_payload(
        lambda: runtime_service().accept_server_host_key(server_id),
        wrapper="raw",
    )


async def rotate_server_token_from_request(server_id: str) -> dict[str, Any]:
    return await run_runtime_payload(
        lambda: runtime_service().rotate_server_token(server_id),
        wrapper="raw",
    )


async def connect_ssh_from_request(
    request: SSHConnectionRequest | None,
) -> dict[str, Any]:
    patch = request_payload(request) if request is not None else None
    result = await run_runtime_payload(
        lambda: runtime_service().connect_ssh(patch),
        wrapper="item",
    )
    await _invalidate_ssh_state_cache()
    return result


async def disconnect_ssh_from_request() -> dict[str, Any]:
    result = await run_runtime_payload(
        runtime_service().disconnect_ssh,
        wrapper="item",
    )
    await _invalidate_ssh_state_cache()
    return result


async def stop_ssh_remote_service_from_request() -> dict[str, Any]:
    result = await run_runtime_payload(
        runtime_service().stop_remote_runner_service,
        wrapper="raw",
    )
    await _invalidate_ssh_state_cache()
    return result


async def list_ssh_listening_ports_from_request() -> dict[str, Any]:
    return await run_runtime_payload(
        runtime_service().list_remote_listening_ports,
        wrapper="raw",
    )


async def list_ssh_remote_files_from_request(
    path: str,
    *,
    directories_only: bool,
    limit: int,
    offset: int,
) -> dict[str, Any]:
    return await run_runtime_payload(
        lambda: runtime_service().list_remote_files(
            path,
            directories_only=directories_only,
            limit=limit,
            offset=offset,
        ),
        wrapper="raw",
    )


async def create_terminal_session_from_request(
    request: SSHTerminalCreateRequest | None,
) -> dict[str, Any]:
    terminal_request = request or SSHTerminalCreateRequest()
    return await run_runtime_payload(
        lambda: runtime_service().create_terminal_session(
            cols=terminal_request.cols,
            rows=terminal_request.rows,
        ),
        wrapper="item",
    )


async def close_terminal_session_from_request(session_id: str) -> dict[str, Any]:
    return await run_runtime_payload(
        lambda: runtime_service().close_terminal_session(session_id=session_id),
        wrapper="item",
    )


async def stream_terminal_session_from_request(
    websocket: TerminalWebSocket,
    *,
    session_id: str,
    cursor: int,
) -> None:
    await stream_terminal_session_with_runtime(
        websocket,
        session_id=session_id,
        cursor=cursor,
        runtime_provider=runtime_service,
    )


async def test_ssh_connection_from_request(
    request: SSHConnectionRequest | None,
) -> dict[str, Any]:
    patch = request_payload(request) if request is not None else None
    return await run_runtime_payload(
        lambda: runtime_service().test_ssh_connection(patch),
        wrapper="item",
    )


async def _invalidate_ssh_state_cache() -> None:
    await invalidate_response_cache(prefixes=SSH_STATE_CACHE_PREFIXES)
