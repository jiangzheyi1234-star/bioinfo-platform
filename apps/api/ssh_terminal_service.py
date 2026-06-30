"""SSH terminal stream service helpers for the local API."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any, Protocol

from fastapi import WebSocketDisconnect

from apps.api.models import (
    TERMINAL_CLIENT_MESSAGE_ADAPTER,
    TerminalInputMessage,
    TerminalResizeMessage,
    TerminalSessionSnapshot,
)
from apps.api.route_utils import run_sync


class TerminalWebSocket(Protocol):
    async def accept(self) -> None: ...

    async def send_json(self, data: Any) -> None: ...

    async def receive_json(self) -> Any: ...


def _terminal_state_event(snapshot: TerminalSessionSnapshot) -> dict[str, Any]:
    return {
        "type": "state",
        "connected": snapshot.connected,
        "input_enabled": snapshot.input_enabled,
        "message": snapshot.message,
    }


def _terminal_output_event(snapshot: TerminalSessionSnapshot) -> dict[str, Any]:
    return {
        "type": "output",
        "data": snapshot.output,
        "cursor": snapshot.cursor,
        "base_cursor": snapshot.base_cursor,
        "truncated": snapshot.truncated,
    }


async def _send_terminal_snapshot(
    websocket: TerminalWebSocket,
    *,
    snapshot: TerminalSessionSnapshot,
    last_state: tuple[bool, bool, str] | None,
) -> tuple[int, tuple[bool, bool, str]]:
    if snapshot.output:
        await websocket.send_json(_terminal_output_event(snapshot))
    state = snapshot.state_key
    if state != last_state and not snapshot.closed:
        await websocket.send_json(_terminal_state_event(snapshot))
    return snapshot.cursor, state


async def _wait_for_terminal_snapshot(
    session: Any,
    *,
    cursor: int,
    version: int,
    timeout: float,
) -> tuple[TerminalSessionSnapshot, int]:
    raw_snapshot, next_version = await run_sync(
        lambda: session.wait_for_update(
            cursor=cursor,
            version=version,
            timeout=timeout,
        )
    )
    return TerminalSessionSnapshot.model_validate(raw_snapshot), next_version


async def stream_terminal_session_with_runtime(
    websocket: TerminalWebSocket,
    *,
    session_id: str,
    cursor: int,
    runtime_provider: Callable[[], Any],
) -> None:
    session = runtime_provider().get_terminal_session(session_id=session_id)
    await websocket.accept()

    async def pump_output() -> None:
        current_cursor = cursor
        version = -1
        last_state: tuple[bool, bool, str] | None = None

        await websocket.send_json({"type": "ready", "session_id": session_id})
        snapshot, version = await _wait_for_terminal_snapshot(
            session,
            cursor=current_cursor,
            version=version,
            timeout=0.0,
        )
        current_cursor, last_state = await _send_terminal_snapshot(
            websocket,
            snapshot=snapshot,
            last_state=last_state,
        )
        if snapshot.closed:
            await websocket.send_json({"type": "closed", "message": snapshot.message})
            return

        while True:
            snapshot, next_version = await _wait_for_terminal_snapshot(
                session,
                cursor=current_cursor,
                version=version,
                timeout=30.0,
            )
            if (
                next_version == version
                and snapshot.cursor == current_cursor
                and not snapshot.closed
            ):
                continue
            version = next_version
            current_cursor, last_state = await _send_terminal_snapshot(
                websocket,
                snapshot=snapshot,
                last_state=last_state,
            )
            if snapshot.closed:
                await websocket.send_json({"type": "closed", "message": snapshot.message})
                return

    async def receive_input() -> None:
        while True:
            message = TERMINAL_CLIENT_MESSAGE_ADAPTER.validate_python(
                await websocket.receive_json()
            )
            if isinstance(message, TerminalInputMessage):
                await run_sync(
                    lambda: runtime_provider().send_terminal_input(
                        session_id=session_id,
                        data=message.data,
                    )
                )
                continue
            if isinstance(message, TerminalResizeMessage):
                await run_sync(
                    lambda: runtime_provider().resize_terminal_session(
                        session_id=session_id,
                        cols=message.cols,
                        rows=message.rows,
                    )
                )
                continue
            await websocket.send_json({"type": "pong"})

    tasks = {
        asyncio.create_task(pump_output()),
        asyncio.create_task(receive_input()),
    }
    try:
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_EXCEPTION)
        for task in done:
            exc = task.exception()
            if exc is not None:
                raise exc
    except WebSocketDisconnect:
        pass
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
