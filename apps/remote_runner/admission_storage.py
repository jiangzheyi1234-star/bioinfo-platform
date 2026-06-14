from __future__ import annotations

import sqlite3
import uuid
from typing import Any

from .resource_pool import ResourceRequest


def admission_wait_reason(
    connection: sqlite3.Connection,
    *,
    worker_id: str,
    slot_id: str,
    request: ResourceRequest,
    capacity: ResourceRequest,
    max_active_slots: int,
) -> dict[str, Any] | None:
    active_count = connection.execute(
        "SELECT COUNT(*) AS count FROM run_resource_allocations WHERE state = 'allocated'",
    ).fetchone()["count"]
    if int(active_count) >= max(1, int(max_active_slots)):
        return {"code": "ADMISSION_SLOT_UNAVAILABLE", "maxActiveSlots": max(1, int(max_active_slots))}
    slot_active = connection.execute(
        """
        SELECT 1 FROM run_resource_allocations
        WHERE state = 'allocated' AND worker_id = ? AND slot_id = ?
        LIMIT 1
        """,
        (worker_id, slot_id),
    ).fetchone()
    if slot_active is not None:
        return {"code": "ADMISSION_SLOT_BUSY", "slotId": slot_id}
    active = connection.execute(
        """
        SELECT
            COALESCE(SUM(cpu), 0) AS cpu,
            COALESCE(SUM(memory_mb), 0) AS memory_mb,
            COALESCE(SUM(disk_mb), 0) AS disk_mb,
            COALESCE(SUM(gpu), 0) AS gpu
        FROM run_resource_allocations
        WHERE state = 'allocated'
        """
    ).fetchone()
    available = {
        "cpu": max(0, int(capacity.cpu) - int(active["cpu"])),
        "memory_mb": max(0, int(capacity.memory_mb) - int(active["memory_mb"])),
        "disk_mb": max(0, int(capacity.disk_mb) - int(active["disk_mb"])),
        "gpu": max(0, int(capacity.gpu) - int(active["gpu"])),
    }
    for field in ("cpu", "memory_mb", "disk_mb", "gpu"):
        requested = int(getattr(request, field))
        if requested > available[field]:
            return {
                "code": "ADMISSION_RESOURCES_UNAVAILABLE",
                "resource": field,
                "available": available[field],
                "requested": requested,
            }
    return None


def record_resource_allocation(
    connection: sqlite3.Connection,
    *,
    run_id: str,
    attempt_id: str,
    worker_id: str,
    session_id: str,
    slot_id: str,
    request: ResourceRequest,
    created_at: str,
) -> None:
    connection.execute(
        """
        INSERT INTO run_resource_allocations (
            allocation_id, run_id, attempt_id, worker_id, session_id, slot_id,
            cpu, memory_mb, disk_mb, gpu, state, created_at, released_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'allocated', ?, NULL, ?)
        ON CONFLICT(attempt_id) DO UPDATE SET
            state = 'allocated',
            updated_at = excluded.updated_at
        """,
        (
            f"alloc_{uuid.uuid4().hex[:12]}",
            run_id,
            attempt_id,
            worker_id,
            session_id,
            slot_id,
            int(request.cpu),
            int(request.memory_mb),
            int(request.disk_mb),
            int(request.gpu),
            created_at,
            created_at,
        ),
    )


def release_resource_allocation(connection: sqlite3.Connection, *, attempt_id: str, released_at: str) -> None:
    connection.execute(
        """
        UPDATE run_resource_allocations
        SET state = 'released',
            released_at = COALESCE(released_at, ?),
            updated_at = ?
        WHERE attempt_id = ? AND state = 'allocated'
        """,
        (released_at, released_at, attempt_id),
    )


def mark_worker_slot_running(
    connection: sqlite3.Connection,
    *,
    worker_id: str,
    session_id: str,
    slot_id: str,
    attempt_id: str,
    updated_at: str,
) -> None:
    if not session_id:
        return
    connection.execute(
        """
        UPDATE run_worker_slots
        SET state = 'running', current_attempt_id = ?, heartbeat_at = ?, updated_at = ?
        WHERE worker_id = ? AND slot_id = ? AND session_id = ?
        """,
        (attempt_id, updated_at, updated_at, worker_id, slot_id, session_id),
    )


def mark_worker_slot_idle(
    connection: sqlite3.Connection,
    *,
    worker_id: str,
    session_id: str,
    slot_id: str,
    updated_at: str,
) -> None:
    if not session_id:
        return
    connection.execute(
        """
        UPDATE run_worker_slots
        SET state = 'idle', current_attempt_id = NULL, heartbeat_at = ?, updated_at = ?
        WHERE worker_id = ? AND slot_id = ? AND session_id = ?
        """,
        (updated_at, updated_at, worker_id, slot_id, session_id),
    )
