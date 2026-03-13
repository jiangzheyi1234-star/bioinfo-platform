"""执行清理器 — 管理历史执行的磁盘占用

提供功能：
- 标记执行为"已归档"（删除文件，保留数据库记录）
- 保留最近 N 次执行策略
- 标记执行为"最终版本"（用于导出和论文）
- 查询各工具的磁盘占用统计

Author: H2OMeta Team
Date: 2024-03
"""

import logging
import sqlite3
import time
from dataclasses import dataclass
from shlex import quote
from typing import Optional

from PyQt6.QtCore import QObject, pyqtSignal

from core.data.project_manager import ProjectManager
from core.remote.ssh_service import SSHService

logger = logging.getLogger(__name__)


def _coerce_ssh_result(result: object) -> tuple[int, str, str]:
    """Normalize SSHService.run() results from tuple or object forms."""
    if isinstance(result, tuple):
        rc, stdout, stderr = result
        return int(rc), str(stdout), str(stderr)

    exit_code = getattr(result, "exit_code", None)
    stdout = getattr(result, "stdout", "")
    stderr = getattr(result, "stderr", "")
    if exit_code is None:
        raise TypeError("Unsupported SSH run result")
    return int(exit_code), str(stdout), str(stderr)


@dataclass
class ExecutionDiskUsage:
    """执行磁盘占用统计"""

    tool_id: str
    execution_count: int  # 执行次数
    total_size_mb: float  # 总磁盘占用（MB）
    archived_count: int  # 已归档次数


class ExecutionCleaner(QObject):
    """执行清理器

    管理历史执行的磁盘占用，支持：
    - 归档旧执行（删除远端文件，保留数据库记录）
    - 标记最终版本（用于导出）
    - 统计磁盘占用
    """

    # 信号定义
    archive_started = pyqtSignal(str)  # execution_id
    archive_completed = pyqtSignal(str)  # execution_id
    archive_failed = pyqtSignal(str, str)  # execution_id, error

    def __init__(
        self,
        projects: ProjectManager,
        ssh: SSHService,
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self._projects = projects
        self._ssh = ssh

    # ── 公开 API ──────────────────────────────────────────────

    def archive_execution(self, execution_id: str) -> None:
        """归档执行（删除远端文件，保留数据库记录）

        Args:
            execution_id: 执行 ID

        Raises:
            ValueError: 执行不存在或已归档
        """
        db = self._projects.db
        if db is None:
            raise RuntimeError("未打开项目")

        # 查询执行记录
        row = db.execute(
            "SELECT execution_id, sample_id, tool_id, archived_at "
            "FROM executions WHERE execution_id = ?",
            (execution_id,),
        ).fetchone()

        if row is None:
            raise ValueError(f"执行不存在: {execution_id}")

        if row["archived_at"] is not None:
            raise ValueError(f"执行已归档: {execution_id}")

        sample_id = row["sample_id"]
        tool_id = row["tool_id"]

        self.archive_started.emit(execution_id)

        try:
            # 构建输出目录路径
            project = self._projects.current_project
            if project is None:
                raise RuntimeError("未打开项目")

            output_dir = (
                f"{project.remote_base}/intermediate/{sample_id}/{tool_id}_{execution_id}"
            )

            # 删除远端目录
            rc, _, stderr = _coerce_ssh_result(
                self._ssh.run(f"rm -rf {quote(output_dir)}", timeout=30)
            )
            if rc != 0:
                raise RuntimeError(f"Failed to delete remote directory: {stderr}")

            # 更新数据库
            db.execute(
                "UPDATE executions SET archived_at = ? WHERE execution_id = ?",
                (time.time(), execution_id),
            )
            db.commit()

            logger.info("执行已归档: %s", execution_id)
            self.archive_completed.emit(execution_id)

        except Exception as e:
            error_msg = str(e)
            logger.error("归档执行失败: %s - %s", execution_id, error_msg)
            self.archive_failed.emit(execution_id, error_msg)
            raise

    def mark_as_final(self, execution_id: str) -> None:
        """标记执行为最终版本（用于导出和论文）

        Args:
            execution_id: 执行 ID

        Raises:
            ValueError: 执行不存在
        """
        db = self._projects.db
        if db is None:
            raise RuntimeError("未打开项目")

        # 查询执行记录
        row = db.execute(
            "SELECT execution_id FROM executions WHERE execution_id = ?",
            (execution_id,),
        ).fetchone()

        if row is None:
            raise ValueError(f"执行不存在: {execution_id}")

        # 更新数据库
        db.execute(
            "UPDATE executions SET is_final_version = 1 WHERE execution_id = ?",
            (execution_id,),
        )
        db.commit()

        logger.info("执行已标记为最终版本: %s", execution_id)

    def unmark_as_final(self, execution_id: str) -> None:
        """取消标记执行为最终版本

        Args:
            execution_id: 执行 ID
        """
        db = self._projects.db
        if db is None:
            raise RuntimeError("未打开项目")

        db.execute(
            "UPDATE executions SET is_final_version = 0 WHERE execution_id = ?",
            (execution_id,),
        )
        db.commit()

        logger.info("执行已取消标记为最终版本: %s", execution_id)

    def keep_recent_n(
        self, sample_id: str, tool_id: str, keep_count: int = 3
    ) -> list[str]:
        """保留最近 N 次执行，归档其余执行

        Args:
            sample_id: 样本 ID
            tool_id: 工具 ID
            keep_count: 保留的执行次数（默认 3）

        Returns:
            已归档的执行 ID 列表

        Raises:
            ValueError: keep_count 必须 >= 1
        """
        if keep_count < 1:
            raise ValueError("keep_count 必须 >= 1")

        db = self._projects.db
        if db is None:
            raise RuntimeError("未打开项目")

        # 查询所有未归档的执行，按创建时间倒序
        rows = db.execute(
            "SELECT execution_id FROM executions "
            "WHERE sample_id = ? AND tool_id = ? AND archived_at IS NULL "
            "ORDER BY created_at DESC",
            (sample_id, tool_id),
        ).fetchall()

        # 跳过最近的 N 次，归档其余
        archived_ids = []
        for row in rows[keep_count:]:
            execution_id = row["execution_id"]
            try:
                self.archive_execution(execution_id)
                archived_ids.append(execution_id)
            except Exception as e:
                logger.error("归档执行失败: %s - %s", execution_id, e)

        return archived_ids

    def get_disk_usage(self, sample_id: Optional[str] = None) -> list[ExecutionDiskUsage]:
        """统计各工具的磁盘占用

        Args:
            sample_id: 可选的样本 ID 过滤

        Returns:
            磁盘占用统计列表
        """
        db = self._projects.db
        if db is None:
            raise RuntimeError("未打开项目")

        # 查询执行统计
        if sample_id:
            rows = db.execute(
                "SELECT tool_id, "
                "COUNT(*) as execution_count, "
                "SUM(CASE WHEN archived_at IS NOT NULL THEN 1 ELSE 0 END) as archived_count "
                "FROM executions "
                "WHERE sample_id = ? "
                "GROUP BY tool_id",
                (sample_id,),
            ).fetchall()
        else:
            rows = db.execute(
                "SELECT tool_id, "
                "COUNT(*) as execution_count, "
                "SUM(CASE WHEN archived_at IS NOT NULL THEN 1 ELSE 0 END) as archived_count "
                "FROM executions "
                "GROUP BY tool_id"
            ).fetchall()

        # 构建统计结果（磁盘占用需要通过 SSH 查询，这里暂时返回 0）
        results = []
        for row in rows:
            results.append(
                ExecutionDiskUsage(
                    tool_id=row["tool_id"],
                    execution_count=row["execution_count"],
                    total_size_mb=0.0,  # TODO: 通过 SSH du 命令查询实际磁盘占用
                    archived_count=row["archived_count"],
                )
            )

        return results

