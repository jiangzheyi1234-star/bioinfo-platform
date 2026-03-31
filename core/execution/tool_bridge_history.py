from __future__ import annotations

import logging
import shlex
import time
from typing import TYPE_CHECKING, Any

from core.data.execution_query_service import ExecutionQueryService
from core.execution.execution_status_service import ExecutionStatusService

if TYPE_CHECKING:
    from core.execution.tool_bridge_service import ToolBridgeService

logger = logging.getLogger(__name__)


class ToolBridgeHistoryHelper:
    """History/query/status helpers extracted from ToolBridgeService."""

    def __init__(self, owner: ToolBridgeService) -> None:
        self._owner = owner

    def find_latest_completed_execution(self, tool_ids: list[str]) -> dict | None:
        pm = self._owner._get_project_manager()
        if pm is None or pm.current_project is None or not tool_ids:
            return None

        placeholders = ",".join("?" for _ in tool_ids)
        query = (
            "SELECT e.execution_id, e.tool_id, e.sample_id, e.parameters, e.created_at, "
            "e.completed_at, s.name AS sample_name "
            "FROM executions e "
            "LEFT JOIN samples s ON s.sample_id = e.sample_id "
            f"WHERE e.status = 'completed' AND e.tool_id IN ({placeholders}) "
            "ORDER BY COALESCE(e.completed_at, e.created_at) DESC LIMIT 1"
        )
        row = pm.db.execute(query, tuple(tool_ids)).fetchone()
        return dict(row) if row else None

    def find_execution_input(self, execution_id: str, data_type: str = "") -> str:
        pm = self._owner._get_project_manager()
        if pm is None or pm.current_project is None:
            return ""

        query = (
            "SELECT d.file_path "
            "FROM execution_io ei "
            "JOIN data_items d ON d.data_id = ei.data_id "
            "WHERE ei.execution_id = ? AND ei.direction = 'input' "
        )
        params: list[str] = [execution_id]
        if data_type:
            query += "AND d.data_type = ? "
            params.append(data_type)
        query += "ORDER BY d.created_at ASC LIMIT 1"

        row = pm.db.execute(query, tuple(params)).fetchone()
        return str(row["file_path"]) if row else ""

    def read_remote_file(self, file_path: str) -> str:
        if not file_path:
            return ""
        ssh = self._owner._get_ssh_service()
        if ssh is None or not getattr(ssh, "is_connected", False):
            return ""
        try:
            rc, out, _ = ssh.run(f"cat {shlex.quote(file_path)} 2>/dev/null", timeout=15)
            if rc == 0:
                return out
        except Exception:
            logger.exception("读取远端文件失败: %s", file_path)
        return ""

    def count_remote_lines(self, file_path: str) -> int | None:
        if not file_path:
            return None
        ssh = self._owner._get_ssh_service()
        if ssh is None or not getattr(ssh, "is_connected", False):
            return None
        try:
            rc, out, _ = ssh.run(f"wc -l < {shlex.quote(file_path)} 2>/dev/null", timeout=10)
            if rc == 0:
                return int((out or "0").strip())
        except Exception:
            logger.exception("统计远端文件行数失败: %s", file_path)
        return None

    def get_execution_history(self) -> list[dict]:
        pm = self._owner._get_project_manager()
        if not pm or not pm.current_project:
            return []
        try:
            db = pm.db
            superseded_ids = self._get_superseded_running_execution_ids(db)
            query_service = ExecutionQueryService(db)
            rows = query_service.get_execution_history_for_ui(limit=50)
            history = []
            for row in rows:
                execution_id = row["execution_id"]
                status = row["status"]
                error = row["error"]
                if execution_id in superseded_ids and status == "running":
                    status = "failed"
                    error = error or "Superseded by a later completed execution"
                history.append(
                    {
                        "execution_id": execution_id,
                        "sample_id": row["sample_id"],
                        "sample_name": row["sample_name"],
                        "tool_id": row["tool_id"],
                        "status": status,
                        "parameters": row["parameters"],
                        "created_at": row["created_at"],
                        "completed_at": row["completed_at"],
                        "error": error,
                    }
                )
            return history
        except Exception:
            logger.exception("Failed to get execution history")
            return []

    @staticmethod
    def _get_superseded_running_execution_ids(db) -> set[str]:
        rows = db.execute(
            """
            SELECT older.execution_id
            FROM executions AS older
            WHERE older.status = 'running'
              AND older.archived_at IS NULL
              AND EXISTS (
                SELECT 1
                FROM executions AS newer
                WHERE newer.tool_id = older.tool_id
                  AND newer.sample_id = older.sample_id
                  AND newer.status = 'completed'
                  AND newer.archived_at IS NULL
                  AND newer.created_at > older.created_at
              )
            """
        ).fetchall()
        return {row[0] for row in rows}

    def delete_execution_history(self, execution_id: str) -> dict[str, str]:
        pm = self._owner._get_project_manager()
        if not pm or not pm.current_project:
            return {"status": "error", "message": "请先打开项目"}
        try:
            query_service = ExecutionQueryService(pm.db)
            result = query_service.archive_execution(execution_id, now=time.time())
            if result.get("status") == "ok":
                logger.info("任务历史已归档: %s", execution_id)
            return result
        except Exception:
            logger.exception("Failed to delete execution history: %s", execution_id)
            return {"status": "error", "message": "删除任务记录失败"}

    def get_execution_remote_status(self, execution_id: str) -> dict:
        pm = self._owner._get_project_manager()
        if pm is None or pm.current_project is None:
            return {"status": "error", "message": "未打开项目"}
        ssh = self._owner._get_ssh_service()
        return self._owner._execution_status_service.get_execution_remote_status(execution_id, pm, ssh)

    def _get_execution_result_row(self, execution_id: str):
        normalized_id = str(execution_id or "").strip()
        if not normalized_id:
            return None
        pm = self._owner._get_project_manager()
        if pm is None or pm.current_project is None:
            return None
        try:
            return pm.db.execute(
                """
                SELECT e.execution_id, e.tool_id, e.sample_id, e.parameters, e.status,
                       e.created_at, e.completed_at, e.tool_version, s.name AS sample_name
                FROM executions e
                LEFT JOIN samples s ON s.sample_id = e.sample_id
                WHERE e.execution_id = ?
                LIMIT 1
                """,
                (normalized_id,),
            ).fetchone()
        except Exception:
            logger.exception("Failed to query execution result row: %s", normalized_id)
            return None

    def _get_cached_remote_status(self, execution_id: str, local_status: str) -> dict[str, Any] | None:
        return self._owner._execution_status_service._get_cached_remote_status(execution_id, local_status)

    def _set_cached_remote_status(self, execution_id: str, data: dict[str, Any]) -> None:
        self._owner._execution_status_service._set_cached_remote_status(execution_id, data)

    @staticmethod
    def _parse_remote_status_block(output: str) -> dict[str, str]:
        return ExecutionStatusService.parse_remote_status_block(output)
