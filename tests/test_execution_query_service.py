from __future__ import annotations

import sqlite3
import time

from core.data.execution_query_service import ExecutionQueryService
from core.data.project_manager import _SCHEMA_SQL
from core.execution.tool_bridge_service import ToolBridgeService


def _setup_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(_SCHEMA_SQL)
    return conn


def test_get_execution_history_for_ui_returns_joined_rows() -> None:
    conn = _setup_conn()
    conn.execute(
        "INSERT INTO samples (sample_id, name, source, metadata) VALUES (?, ?, ?, ?)",
        ("smp_1", "样本1", "test", "{}"),
    )
    conn.execute(
        "INSERT INTO executions (execution_id, sample_id, tool_id, parameters, status, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("exec_1", "smp_1", "fastp", "{}", "completed", time.time()),
    )
    conn.commit()

    service = ExecutionQueryService(conn)
    rows = service.get_execution_history_for_ui(limit=10)

    assert len(rows) == 1
    assert rows[0]["execution_id"] == "exec_1"
    assert rows[0]["sample_name"] == "样本1"
    conn.close()


def test_archive_execution_rejects_running() -> None:
    conn = _setup_conn()
    conn.execute(
        "INSERT INTO executions (execution_id, tool_id, parameters, status, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        ("exec_running", "fastp", "{}", "running", time.time()),
    )
    conn.commit()

    service = ExecutionQueryService(conn)
    result = service.archive_execution("exec_running")

    assert result["status"] == "error"
    conn.close()


def test_tool_bridge_get_execution_history_returns_empty_without_project() -> None:
    service = ToolBridgeService()

    assert service.get_execution_history() == []
