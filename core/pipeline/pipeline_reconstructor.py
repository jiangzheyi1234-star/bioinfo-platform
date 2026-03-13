"""流水线重建器 — 从 SQLite execution_io 重建执行 DAG。

根据 executions + execution_io + data_items 表中的记录，
重建完整的分析流水线有向无环图 (DAG)，用于：
1. Snakefile 导出（可复现性）
2. DAG 可视化（只读状态视图）
3. Methods 自动生成（论文方法段落）
"""

import json
import logging
import sqlite3
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger(__name__)


@dataclass
class DAGNode:
    """DAG 节点 — 表示一次工具执行"""

    execution_id: str
    tool_id: str
    tool_version: str
    sample_id: str
    parameters: dict[str, Any]
    status: str
    created_at: float
    completed_at: Optional[float] = None
    error: Optional[str] = None
    input_data_ids: list[str] = field(default_factory=list)
    output_data_ids: list[str] = field(default_factory=list)


@dataclass
class DAGEdge:
    """DAG 边 — 表示数据从一个执行流向另一个执行"""

    from_execution_id: str
    to_execution_id: str
    data_id: str
    data_type: str
    file_path: str


@dataclass
class ExecutionDAG:
    """完整的执行 DAG"""

    nodes: list[DAGNode]
    edges: list[DAGEdge]
    sample_ids: list[str]

    @property
    def roots(self) -> list[DAGNode]:
        """没有入边的节点（流水线起点）"""
        to_ids = {e.to_execution_id for e in self.edges}
        return [n for n in self.nodes if n.execution_id not in to_ids]

    @property
    def leaves(self) -> list[DAGNode]:
        """没有出边的节点（流水线终点）"""
        from_ids = {e.from_execution_id for e in self.edges}
        return [n for n in self.nodes if n.execution_id not in from_ids]

    def topological_order(self) -> list[DAGNode]:
        """拓扑排序，返回节点的执行顺序"""
        # 构建邻接表和入度表
        adjacency: dict[str, list[str]] = {n.execution_id: [] for n in self.nodes}
        in_degree: dict[str, int] = {n.execution_id: 0 for n in self.nodes}
        node_map = {n.execution_id: n for n in self.nodes}

        for edge in self.edges:
            if edge.from_execution_id in adjacency:
                adjacency[edge.from_execution_id].append(edge.to_execution_id)
            if edge.to_execution_id in in_degree:
                in_degree[edge.to_execution_id] += 1

        # Kahn 算法
        queue = [eid for eid, deg in in_degree.items() if deg == 0]
        result: list[DAGNode] = []

        while queue:
            eid = queue.pop(0)
            result.append(node_map[eid])
            for neighbor in adjacency.get(eid, []):
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        return result

    def get_node(self, execution_id: str) -> Optional[DAGNode]:
        """按 execution_id 获取节点"""
        for n in self.nodes:
            if n.execution_id == execution_id:
                return n
        return None


class PipelineReconstructor:
    """流水线重建器

    从 SQLite 数据库中读取 executions、execution_io、data_items 表，
    重建完整的执行 DAG。

    典型用法::

        reconstructor = PipelineReconstructor(db_conn)
        dag = reconstructor.rebuild_dag()
        dag = reconstructor.rebuild_dag(sample_id="smp_abc123")
        order = dag.topological_order()
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self._conn.row_factory = sqlite3.Row

    def rebuild_dag(
        self, sample_id: Optional[str] = None
    ) -> ExecutionDAG:
        """从数据库重建执行 DAG

        Args:
            sample_id: 如果指定，只重建该样本的 DAG；否则重建整个项目的 DAG

        Returns:
            完整的执行 DAG
        """
        # 1. 查询执行记录
        if sample_id:
            rows = self._conn.execute(
                "SELECT * FROM executions WHERE sample_id = ? ORDER BY created_at",
                (sample_id,),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM executions ORDER BY created_at"
            ).fetchall()

        nodes: list[DAGNode] = []
        for row in rows:
            params_str = row["parameters"]
            parameters = json.loads(params_str) if params_str else {}
            node = DAGNode(
                execution_id=row["execution_id"],
                tool_id=row["tool_id"],
                tool_version=row["tool_version"] or "",
                sample_id=row["sample_id"],
                parameters=parameters,
                status=row["status"],
                created_at=row["created_at"],
                completed_at=row["completed_at"],
                error=row["error"],
            )
            # 查询输入输出数据
            node.input_data_ids = self._get_io_data_ids(
                row["execution_id"], "input"
            )
            node.output_data_ids = self._get_io_data_ids(
                row["execution_id"], "output"
            )
            nodes.append(node)

        # 2. 构建边：一个执行的输出是另一个执行的输入
        edges = self._build_edges(nodes)

        # 3. 收集样本 ID
        sample_ids = list({n.sample_id for n in nodes})

        dag = ExecutionDAG(nodes=nodes, edges=edges, sample_ids=sample_ids)
        logger.info(
            "DAG 重建完成: %d 节点, %d 边, %d 样本",
            len(nodes), len(edges), len(sample_ids),
        )
        return dag

    def get_execution_lineage(self, execution_id: str) -> list[dict[str, Any]]:
        """获取单个执行的完整血缘链

        沿 execution_io 向上递归追溯，返回从根到当前执行的完整链。

        Args:
            execution_id: 起始执行 ID

        Returns:
            血缘链列表，每项包含 execution_id, tool_id, depth
        """
        sql = """\
WITH RECURSIVE lineage AS (
    SELECT e.execution_id, e.tool_id, e.tool_version, e.sample_id,
           e.parameters, e.status, e.created_at, 0 AS depth
    FROM executions e
    WHERE e.execution_id = ?

    UNION ALL

    SELECT e2.execution_id, e2.tool_id, e2.tool_version, e2.sample_id,
           e2.parameters, e2.status, e2.created_at, l.depth + 1
    FROM lineage l
    JOIN execution_io ei_in ON ei_in.execution_id = l.execution_id
        AND ei_in.direction = 'input'
    JOIN data_items d ON d.data_id = ei_in.data_id
    JOIN executions e2 ON e2.execution_id = d.produced_by
)
SELECT DISTINCT * FROM lineage ORDER BY depth DESC
"""
        rows = self._conn.execute(sql, (execution_id,)).fetchall()
        result = []
        for row in rows:
            params_str = row["parameters"]
            result.append({
                "execution_id": row["execution_id"],
                "tool_id": row["tool_id"],
                "tool_version": row["tool_version"],
                "sample_id": row["sample_id"],
                "parameters": json.loads(params_str) if params_str else {},
                "status": row["status"],
                "created_at": row["created_at"],
                "depth": row["depth"],
            })
        return result

    def generate_snakefile(
        self,
        dag: ExecutionDAG,
        plugin_descriptors: Optional[dict[str, dict[str, Any]]] = None,
    ) -> str:
        """将 DAG 转换为 Snakefile

        Args:
            dag: 执行 DAG
            plugin_descriptors: {tool_id: descriptor} 映射，用于获取 conda_env

        Returns:
            Snakefile 内容字符串
        """
        ordered = dag.topological_order()
        if not ordered:
            return "# 空流水线 — 没有执行记录\n"

        lines: list[str] = [
            "# Auto-generated Snakefile from H2OMeta execution history",
            "# DO NOT EDIT — regenerate from project database",
            "",
        ]

        # 收集所有输出文件作为 all 规则的目标
        all_outputs: list[str] = []
        for node in dag.leaves:
            for data_id in node.output_data_ids:
                item = self._get_data_item(data_id)
                if item:
                    all_outputs.append(item["file_path"])

        if all_outputs:
            lines.append("rule all:")
            lines.append("    input:")
            for path in all_outputs:
                lines.append(f'        "{path}",')
            lines.append("")

        # 为每个执行节点生成 rule
        for node in ordered:
            rule_name = f"{node.tool_id}_{node.execution_id[-8:]}"

            # 收集输入和输出文件路径
            input_files: list[str] = []
            for data_id in node.input_data_ids:
                item = self._get_data_item(data_id)
                if item:
                    input_files.append(item["file_path"])

            output_files: list[str] = []
            for data_id in node.output_data_ids:
                item = self._get_data_item(data_id)
                if item:
                    output_files.append(item["file_path"])

            lines.append(f"rule {rule_name}:")

            # input
            lines.append("    input:")
            if input_files:
                for path in input_files:
                    lines.append(f'        "{path}",')
            else:
                lines.append("        # 无输入文件（原始数据）")
            lines.append("")

            # output
            lines.append("    output:")
            if output_files:
                for path in output_files:
                    lines.append(f'        "{path}",')
            else:
                lines.append("        # 无输出文件记录")
            lines.append("")

            # conda
            conda_env = None
            if plugin_descriptors and node.tool_id in plugin_descriptors:
                conda_env = plugin_descriptors[node.tool_id].get("conda_env")
            if conda_env:
                lines.append(f'    conda: "{conda_env}"')
                lines.append("")

            # params
            if node.parameters:
                lines.append("    params:")
                for k, v in node.parameters.items():
                    lines.append(f"        {k}={json.dumps(v)},")
                lines.append("")

            # shell
            lines.append("    shell:")
            lines.append(f'        """')
            lines.append(f"        # {node.tool_id} v{node.tool_version}")
            lines.append(f"        # execution_id: {node.execution_id}")
            lines.append(f'        echo "执行 {node.tool_id}..."')
            lines.append(f'        """')
            lines.append("")

        return "\n".join(lines) + "\n"

    # ── 内部方法 ──────────────────────────────────────────────

    def _get_io_data_ids(
        self, execution_id: str, direction: str
    ) -> list[str]:
        """获取执行的输入或输出数据 ID 列表"""
        rows = self._conn.execute(
            "SELECT data_id FROM execution_io "
            "WHERE execution_id = ? AND direction = ?",
            (execution_id, direction),
        ).fetchall()
        return [row["data_id"] for row in rows]

    def _build_edges(self, nodes: list[DAGNode]) -> list[DAGEdge]:
        """根据数据流向构建 DAG 边

        如果节点 A 的某个输出数据是节点 B 的某个输入数据，
        则存在边 A → B。
        """
        # 构建 output_data_id → execution_id 的映射
        output_to_exec: dict[str, str] = {}
        for node in nodes:
            for data_id in node.output_data_ids:
                output_to_exec[data_id] = node.execution_id

        edges: list[DAGEdge] = []
        for node in nodes:
            for data_id in node.input_data_ids:
                if data_id in output_to_exec:
                    from_exec = output_to_exec[data_id]
                    item = self._get_data_item(data_id)
                    edges.append(DAGEdge(
                        from_execution_id=from_exec,
                        to_execution_id=node.execution_id,
                        data_id=data_id,
                        data_type=item["data_type"] if item else "unknown",
                        file_path=item["file_path"] if item else "",
                    ))

        return edges

    def _get_data_item(self, data_id: str) -> Optional[dict[str, Any]]:
        """获取数据项信息"""
        row = self._conn.execute(
            "SELECT * FROM data_items WHERE data_id = ?", (data_id,)
        ).fetchone()
        if row is None:
            return None
        return dict(row)
