"""SSH terminal stream helpers for the local API."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect

from core.app_runtime.errors import RuntimeServiceError


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


async def stream_terminal_session_with_runtime(
    websocket: WebSocket,
    *,
    session_id: str,
    cursor: int,
    runtime_provider: Callable[[], Any],
) -> None:
    await websocket.accept()
    try:
        session = runtime_provider().get_terminal_session(session_id=session_id)
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
                    runtime_provider().send_terminal_input,
                    session_id=session_id,
                    data=data,
                )
                continue
            if message_type == "resize":
                await asyncio.to_thread(
                    runtime_provider().resize_terminal_session,
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
