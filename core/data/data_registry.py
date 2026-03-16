"""数据注册表 — 基于 SQLite 的数据血缘追踪。

管理 samples、data_items、execution_io 表，
提供数据注册、兼容性查找和血缘追溯功能。
"""

import json
import logging
import sqlite3
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger(__name__)


@dataclass
class DataItem:
    """数据项数据类"""

    data_id: str
    sample_id: str
    file_path: str
    data_type: str       # 文件格式: fastq, fasta, kreport, tsv, gff...
    tier: str            # raw / intermediate / result
    produced_by: Optional[str] = None  # execution_id, None 表示原始上传
    created_at: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class SampleInfo:
    """样本信息数据类"""

    sample_id: str
    name: str
    source: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)


class DataRegistry:
    """数据注册表

    接收一个 SQLite Connection 作为参数，在该连接上操作
    samples、data_items、execution_io 三张表。
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        """初始化数据注册表

        Args:
            conn: 已连接的 SQLite 数据库，应已创建好 schema
        """
        self._conn = conn
        # 确保 row_factory 设置为 Row 以便字典式访问
        self._conn.row_factory = sqlite3.Row

    # ── 样本管理 ──────────────────────────────────────────────

    def add_sample(
        self,
        name: str,
        source: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> str:
        """添加样本

        Args:
            name: 样本名称
            source: 样本来源 (human / water / soil / ...)
            metadata: 额外元数据

        Returns:
            新样本的 sample_id

        Raises:
            ValueError: 样本名称为空
        """
        if not name or not name.strip():
            raise ValueError("样本名称不能为空")

        sample_id = f"smp_{uuid.uuid4().hex[:12]}"
        metadata_json = json.dumps(metadata or {}, ensure_ascii=False)

        self._conn.execute(
            "INSERT INTO samples (sample_id, name, source, metadata) VALUES (?, ?, ?, ?)",
            (sample_id, name.strip(), source, metadata_json),
        )
        self._conn.commit()

        logger.info("样本已添加: %s (%s)", name, sample_id)
        return sample_id

    def get_sample(self, sample_id: str) -> Optional[SampleInfo]:
        """获取样本信息

        Args:
            sample_id: 样本 ID

        Returns:
            样本信息，不存在时返回 None
        """
        row = self._conn.execute(
            "SELECT * FROM samples WHERE sample_id = ?", (sample_id,)
        ).fetchone()
        if row is None:
            return None
        return self._row_to_sample(row)

    def list_samples(self) -> list[SampleInfo]:
        """列出所有样本"""
        rows = self._conn.execute("SELECT * FROM samples").fetchall()
        return [self._row_to_sample(r) for r in rows]

    # ── 数据注册 ──────────────────────────────────────────────

    def register_input(
        self,
        file_path: str,
        sample_id: str,
        data_type: str,
        tier: str = "raw",
        metadata: Optional[dict[str, Any]] = None,
    ) -> str:
        """注册原始上传文件

        Args:
            file_path: 远端文件绝对路径
            sample_id: 所属样本 ID
            data_type: 文件格式 (fastq / fasta / ...)
            tier: 数据层级，默认 "raw"
            metadata: 额外元数据

        Returns:
            新数据项的 data_id

        Raises:
            ValueError: 参数校验失败
        """
        self._validate_register_params(file_path, sample_id, data_type, tier)

        data_id = f"dat_{uuid.uuid4().hex[:12]}"
        metadata_json = json.dumps(metadata or {}, ensure_ascii=False)

        self._conn.execute(
            "INSERT INTO data_items "
            "(data_id, sample_id, file_path, data_type, tier, produced_by, created_at, metadata) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (data_id, sample_id, file_path, data_type, tier, None, time.time(), metadata_json),
        )
        self._conn.commit()

        logger.info("输入数据已注册: %s (%s, %s)", file_path, data_type, data_id)
        return data_id

    def register_output(
        self,
        execution_id: str,
        file_path: str,
        data_type: str,
        sample_id: str,
        tier: str = "result",
        metadata: Optional[dict[str, Any]] = None,
    ) -> str:
        """注册工具输出文件

        同时记录 execution_io 中的 output 关系。

        Args:
            execution_id: 关联的执行 ID
            file_path: 远端文件绝对路径
            data_type: 文件格式
            sample_id: 所属样本 ID
            tier: 数据层级，默认 "result"
            metadata: 额外元数据

        Returns:
            新数据项的 data_id
        """
        self._validate_register_params(file_path, sample_id, data_type, tier)
        if not execution_id:
            raise ValueError("execution_id 不能为空")

        data_id = f"dat_{uuid.uuid4().hex[:12]}"
        metadata_json = json.dumps(metadata or {}, ensure_ascii=False)

        self._conn.execute(
            "INSERT INTO data_items "
            "(data_id, sample_id, file_path, data_type, tier, produced_by, created_at, metadata) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (data_id, sample_id, file_path, data_type, tier, execution_id, time.time(), metadata_json),
        )
        self._conn.execute(
            "INSERT INTO execution_io (execution_id, data_id, direction) VALUES (?, ?, ?)",
            (execution_id, data_id, "output"),
        )
        self._conn.commit()

        logger.info("输出数据已注册: %s (%s, %s)", file_path, data_type, data_id)
        return data_id

    def add_execution_io(
        self, execution_id: str, data_id: str, direction: str
    ) -> None:
        """记录执行的输入/输出关系

        Args:
            execution_id: 执行 ID
            data_id: 数据项 ID
            direction: 'input' 或 'output'

        Raises:
            ValueError: direction 不是 'input' 或 'output'
        """
        if direction not in ("input", "output"):
            raise ValueError(f"direction 必须是 'input' 或 'output'，收到: {direction}")

        self._conn.execute(
            "INSERT OR IGNORE INTO execution_io (execution_id, data_id, direction) "
            "VALUES (?, ?, ?)",
            (execution_id, data_id, direction),
        )
        self._conn.commit()

    # ── 查询 ──────────────────────────────────────────────────

    def get_item(self, data_id: str) -> Optional[DataItem]:
        """获取单个数据项

        Args:
            data_id: 数据项 ID

        Returns:
            数据项，不存在时返回 None
        """
        row = self._conn.execute(
            "SELECT * FROM data_items WHERE data_id = ?", (data_id,)
        ).fetchone()
        if row is None:
            return None
        return self._row_to_data_item(row)

    def find_compatible(
        self,
        sample_id: str,
        data_type: str,
        tier: Optional[str] = None,
    ) -> list[DataItem]:
        """按文件格式查找兼容数据

        这是数据关联的核心方法：给定样本和需要的文件格式，
        找到该样本下所有匹配格式的数据项。

        Args:
            sample_id: 样本 ID
            data_type: 需要的文件格式 (fastq / fasta / kreport / ...)
            tier: 可选的层级过滤 (raw / intermediate / result)

        Returns:
            匹配的数据项列表，按创建时间倒序（最新的在前）
        """
        if tier:
            rows = self._conn.execute(
                "SELECT * FROM data_items "
                "WHERE sample_id = ? AND data_type = ? AND tier = ? "
                "ORDER BY created_at DESC",
                (sample_id, data_type, tier),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM data_items "
                "WHERE sample_id = ? AND data_type = ? "
                "ORDER BY created_at DESC",
                (sample_id, data_type),
            ).fetchall()

        return [self._row_to_data_item(r) for r in rows]

    def find_by_sample(self, sample_id: str) -> list[DataItem]:
        """查找样本下的所有数据项

        Args:
            sample_id: 样本 ID

        Returns:
            该样本下所有数据项列表
        """
        rows = self._conn.execute(
            "SELECT * FROM data_items WHERE sample_id = ? ORDER BY created_at DESC",
            (sample_id,),
        ).fetchall()
        return [self._row_to_data_item(r) for r in rows]

    def get_lineage(self, data_id: str) -> list[DataItem]:
        """递归追溯数据血缘链

        从指定数据项出发，沿着 produced_by -> execution_io(input) 链条
        向上追溯所有祖先数据项。

        Args:
            data_id: 起始数据项 ID

        Returns:
            血缘链上的所有数据项（包含起始项），按血缘深度排列
        """
        sql = """\
WITH RECURSIVE lineage AS (
    SELECT d.* FROM data_items d WHERE d.data_id = ?
    UNION ALL
    SELECT d2.*
    FROM lineage l
    JOIN execution_io ei_out ON ei_out.data_id = l.data_id AND ei_out.direction = 'output'
    JOIN execution_io ei_in ON ei_in.execution_id = ei_out.execution_id AND ei_in.direction = 'input'
    JOIN data_items d2 ON d2.data_id = ei_in.data_id
)
SELECT * FROM lineage
"""
        rows = self._conn.execute(sql, (data_id,)).fetchall()
        return [self._row_to_data_item(r) for r in rows]

    def find_by_execution(self, execution_id: str) -> list[DataItem]:
        """查询特定执行的输出数据

        Args:
            execution_id: 执行 ID

        Returns:
            该执行产生的所有数据项列表
        """
        rows = self._conn.execute(
            "SELECT d.* FROM data_items d "
            "JOIN execution_io ei ON ei.data_id = d.data_id "
            "WHERE ei.execution_id = ? AND ei.direction = 'output' "
            "ORDER BY d.created_at DESC",
            (execution_id,),
        ).fetchall()
        return [self._row_to_data_item(r) for r in rows]

    def update_item_metadata(self, data_id: str, metadata: dict[str, Any]) -> None:
        """合并更新数据项 metadata。"""
        item = self.get_item(data_id)
        if item is None:
            raise KeyError(f"数据项不存在: {data_id}")

        merged = dict(item.metadata or {})
        merged.update(metadata or {})
        self._conn.execute(
            "UPDATE data_items SET metadata = ? WHERE data_id = ?",
            (json.dumps(merged, ensure_ascii=False), data_id),
        )
        self._conn.commit()

    def list_executions(
        self, sample_id: str, tool_id: str, status: Optional[str] = None
    ) -> list[dict]:
        """列出同一工具的所有历史执行

        Args:
            sample_id: 样本 ID
            tool_id: 工具 ID
            status: 可选的状态过滤 (completed / failed / ...)

        Returns:
            执行记录列表，每条记录包含：
            - execution_id: 执行 ID
            - created_at: 创建时间
            - completed_at: 完成时间
            - status: 状态
            - parameters: 参数 JSON 字符串
            - is_final_version: 是否为最终版本
            - archived_at: 归档时间
        """
        if status:
            rows = self._conn.execute(
                "SELECT execution_id, created_at, completed_at, status, "
                "parameters, is_final_version, archived_at "
                "FROM executions "
                "WHERE sample_id = ? AND tool_id = ? AND status = ? "
                "ORDER BY created_at DESC",
                (sample_id, tool_id, status),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT execution_id, created_at, completed_at, status, "
                "parameters, is_final_version, archived_at "
                "FROM executions "
                "WHERE sample_id = ? AND tool_id = ? "
                "ORDER BY created_at DESC",
                (sample_id, tool_id),
            ).fetchall()

        return [dict(row) for row in rows]

    def find_compatible_by_execution(
        self,
        sample_id: str,
        data_type: str,
        execution_id: str,
        tier: Optional[str] = None,
    ) -> list[DataItem]:
        """按执行 ID 查找兼容数据（用于指定版本）

        Args:
            sample_id: 样本 ID
            data_type: 需要的文件格式
            execution_id: 执行 ID（用于过滤特定版本的输出）
            tier: 可选的层级过滤

        Returns:
            匹配的数据项列表
        """
        if tier:
            rows = self._conn.execute(
                "SELECT d.* FROM data_items d "
                "WHERE d.sample_id = ? AND d.data_type = ? AND d.tier = ? "
                "AND d.produced_by = ? "
                "ORDER BY d.created_at DESC",
                (sample_id, data_type, tier, execution_id),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT d.* FROM data_items d "
                "WHERE d.sample_id = ? AND d.data_type = ? "
                "AND d.produced_by = ? "
                "ORDER BY d.created_at DESC",
                (sample_id, data_type, execution_id),
            ).fetchall()

        return [self._row_to_data_item(r) for r in rows]

    # ── 内部方法 ──────────────────────────────────────────────

    @staticmethod
    def _validate_register_params(
        file_path: str, sample_id: str, data_type: str, tier: str
    ) -> None:
        """校验注册参数"""
        if not file_path:
            raise ValueError("file_path 不能为空")
        if not sample_id:
            raise ValueError("sample_id 不能为空")
        if not data_type:
            raise ValueError("data_type 不能为空")
        if tier not in ("raw", "intermediate", "result"):
            raise ValueError(f"tier 必须是 raw/intermediate/result，收到: {tier}")

    @staticmethod
    def _row_to_data_item(row: sqlite3.Row) -> DataItem:
        """将数据库行转换为 DataItem"""
        metadata_str = row["metadata"]
        metadata = json.loads(metadata_str) if metadata_str else {}
        return DataItem(
            data_id=row["data_id"],
            sample_id=row["sample_id"],
            file_path=row["file_path"],
            data_type=row["data_type"],
            tier=row["tier"],
            produced_by=row["produced_by"],
            created_at=row["created_at"],
            metadata=metadata,
        )

    @staticmethod
    def _row_to_sample(row: sqlite3.Row) -> SampleInfo:
        """将数据库行转换为 SampleInfo"""
        metadata_str = row["metadata"]
        metadata = json.loads(metadata_str) if metadata_str else {}
        return SampleInfo(
            sample_id=row["sample_id"],
            name=row["name"],
            source=row["source"],
            metadata=metadata,
        )
