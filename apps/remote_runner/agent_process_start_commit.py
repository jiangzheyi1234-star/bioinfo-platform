"""Commit one governed process start before releasing its OS launch gate."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Mapping
from typing import Any

from .agent_process_lifecycle_read_model import AgentProcessPlatform
from .agent_process_lifecycle_storage import (
    mark_agent_process_started_for_connection,
)


class AgentProcessGateReleaseError(RuntimeError):
    """Path-free signal that a durable start has uncertain gate-release state."""

    code = "AGENT_PROCESS_GATE_RELEASE_STATE_UNKNOWN"

    def __init__(self) -> None:
        super().__init__(self.code)


def commit_agent_process_started_and_release(
    connection: sqlite3.Connection,
    *,
    process_instance_id: str,
    gate_token: bytes,
    expected_platform: AgentProcessPlatform,
    process_pid: int,
    process_group_id: int,
    process_incarnation: Mapping[str, object],
    release_callback: Callable[[], None],
    occurred_at: str | None = None,
) -> dict[str, Any]:
    """Durably record a start, then attempt gate release at most once.

    The connection must initially be outside a transaction. The callback is
    invoked only after a successful commit of a newly applied transition. Exact
    replay returns the durable record without invoking it again. A callback
    failure happens after durability and must be reconciled as an uncertain gate
    release; this function never pretends the database and OS act atomically.
    """

    if connection.in_transaction:
        raise RuntimeError("AGENT_PROCESS_START_COMMIT_REQUIRES_IDLE_CONNECTION")
    if not callable(release_callback):
        raise TypeError("AGENT_PROCESS_RELEASE_CALLBACK_REQUIRED")

    try:
        connection.execute("BEGIN IMMEDIATE")
        transition = mark_agent_process_started_for_connection(
            connection,
            process_instance_id=process_instance_id,
            gate_token=gate_token,
            expected_platform=expected_platform,
            process_pid=process_pid,
            process_group_id=process_group_id,
            process_incarnation=process_incarnation,
            occurred_at=occurred_at,
        )
        transition_applied = transition.get("transactionApplied") is True
        _commit(connection)
    except BaseException:
        if connection.in_transaction:
            connection.rollback()
        raise

    gate_released = False
    if transition_applied:
        try:
            release_callback()
        except Exception:
            raise AgentProcessGateReleaseError() from None
        gate_released = True
    return {
        "durableTransitionApplied": transition_applied,
        "event": transition["event"],
        "gateReleased": gate_released,
        "process": transition["process"],
    }


def _commit(connection: sqlite3.Connection) -> None:
    """Small injection seam for proving commit failure cannot release a gate."""

    connection.commit()


__all__ = [
    "AgentProcessGateReleaseError",
    "commit_agent_process_started_and_release",
]
