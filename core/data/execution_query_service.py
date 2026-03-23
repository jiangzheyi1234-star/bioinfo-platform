"""Execution query helpers for UI/service consumers."""

from __future__ import annotations

import sqlite3
import time
from typing import Any


class ExecutionQueryService:
    """Read/write helpers around execution history tables."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def list_recent_executions(self, *, limit: int = 50, archived: bool = False) -> list[dict[str, Any]]:
        if archived:
            sql = (
                "SELECT execution_id, sample_id, tool_id, status, parameters, created_at, "
                "completed_at, error, archived_at "
                "FROM executions "
                "WHERE archived_at IS NOT NULL "
                "ORDER BY created_at DESC LIMIT ?"
            )
            rows = self._conn.execute(sql, (limit,)).fetchall()
        else:
            sql = (
                "SELECT execution_id, sample_id, tool_id, status, parameters, created_at, "
                "completed_at, error, archived_at "
                "FROM executions "
                "WHERE archived_at IS NULL "
                "ORDER BY created_at DESC LIMIT ?"
            )
            rows = self._conn.execute(sql, (limit,)).fetchall()
        return [dict(row) for row in rows]

    def get_execution_history_for_ui(self, *, limit: int = 50) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            """
            SELECT e.execution_id, e.sample_id, s.name AS sample_name,
                   e.tool_id, e.status, e.parameters,
                   e.created_at, e.completed_at, e.error
            FROM executions e
            LEFT JOIN samples s ON e.sample_id = s.sample_id
            WHERE e.archived_at IS NULL
            ORDER BY e.created_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]

    def list_recent_execution_rows(self, *, limit: int = 100) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            """
            SELECT execution_id, tool_id, status, triggered_by,
                   created_at, completed_at, error
            FROM executions
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]

    def get_execution_tool_map(self, execution_ids: list[str]) -> dict[str, str]:
        if not execution_ids:
            return {}
        placeholders = ",".join(["?"] * len(execution_ids))
        rows = self._conn.execute(
            f"SELECT execution_id, tool_id FROM executions WHERE execution_id IN ({placeholders})",
            tuple(execution_ids),
        ).fetchall()
        return {str(row["execution_id"]): str(row["tool_id"] or "") for row in rows}

    def list_running_executions(self, *, limit: int = 20) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            """
            SELECT execution_id, sample_id, tool_id
            FROM executions
            WHERE status = 'running' AND archived_at IS NULL
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]

    def list_failed_executions(self, *, limit: int = 20) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            """
            SELECT execution_id, sample_id, tool_id
            FROM executions
            WHERE status = 'failed' AND archived_at IS NULL
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]

    def relink_failed_to_running(self, execution_ids: list[str]) -> int:
        if not execution_ids:
            return 0
        rows = [(execution_id,) for execution_id in execution_ids]
        self._conn.executemany(
            """
            UPDATE executions
            SET status = 'running', error = NULL, completed_at = NULL
            WHERE execution_id = ?
            """,
            rows,
        )
        self._conn.commit()
        return len(rows)

    def archive_execution(self, execution_id: str, *, now: float | None = None) -> dict[str, str]:
        if now is None:
            now = time.time()
        row = self._conn.execute(
            "SELECT status, archived_at FROM executions WHERE execution_id = ?",
            (execution_id,),
        ).fetchone()
        if row is None:
            return {"status": "error", "message": "任务记录不存在"}
        if row["archived_at"] is not None:
            return {"status": "ok", "message": "任务记录已删除"}
        if row["status"] in {"pending", "running", "retrying"}:
            return {"status": "error", "message": "运行中的任务不能删除"}

        self._conn.execute(
            "UPDATE executions SET archived_at = ? WHERE execution_id = ?",
            (now, execution_id),
        )
        self._conn.commit()
        return {"status": "ok", "message": "任务记录已删除"}
