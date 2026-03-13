"""项目导出器 — 三种格式导出分析结果。

导出格式:
1. Paper Export: methods.txt + parameters.csv — 论文方法段落 + 参数表
2. Reproducibility Export: Snakefile + config.yaml — 可复现性工作流
3. Archive Export: 完整项目快照 (.zip)
"""

import csv
import json
import logging
import shutil
import sqlite3
import time
from io import StringIO
from pathlib import Path
from typing import Any, Optional

from core.pipeline.pipeline_reconstructor import PipelineReconstructor

logger = logging.getLogger(__name__)


class ProjectExporter:
    """项目导出器

    典型用法::

        exporter = ProjectExporter(db_conn, plugin_descriptors)
        exporter.export_for_paper(output_dir)
        exporter.export_for_reproducibility(output_dir)
        exporter.export_archive(output_dir, project_dir)
    """

    def __init__(
        self,
        conn: sqlite3.Connection,
        plugin_descriptors: Optional[dict[str, dict[str, Any]]] = None,
        project_name: str = "H2OMeta Project",
    ) -> None:
        """
        Args:
            conn: 项目 SQLite 数据库连接
            plugin_descriptors: {tool_id: descriptor} 映射，用于 methods 模板
            project_name: 项目名称
        """
        self._conn = conn
        self._conn.row_factory = sqlite3.Row
        self._plugins = plugin_descriptors or {}
        self._project_name = project_name
        self._reconstructor = PipelineReconstructor(conn)

    # ── Paper Export ──────────────────────────────────────────

    def export_for_paper(self, output_dir: str | Path) -> dict[str, str]:
        """导出论文所需文件

        生成:
          - methods.txt: 各工具的 Methods 段落（可直接粘贴到论文中）
          - parameters.csv: 完整参数表

        Args:
            output_dir: 输出目录

        Returns:
            {filename: filepath} 已生成文件映射
        """
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        result: dict[str, str] = {}

        # 1. 生成 methods.txt
        methods_path = output_dir / "methods.txt"
        methods_text = self.generate_methods()
        methods_path.write_text(methods_text, encoding="utf-8")
        result["methods.txt"] = str(methods_path)

        # 2. 生成 parameters.csv
        params_path = output_dir / "parameters.csv"
        params_csv = self.generate_parameters_csv()
        params_path.write_text(params_csv, encoding="utf-8")
        result["parameters.csv"] = str(params_path)

        logger.info("论文导出完成: %s", output_dir)
        return result

    def generate_methods(self) -> str:
        """生成 Methods 段落文本

        按执行顺序（拓扑排序）拼接各工具的 methods_template。
        """
        dag = self._reconstructor.rebuild_dag()
        ordered = dag.topological_order()

        if not ordered:
            return "# No analysis executions found.\n"

        lines: list[str] = [
            "# Methods",
            "",
            f"## Analysis Pipeline — {self._project_name}",
            "",
        ]

        # 按工具去重（同一工具只描述一次，使用第一次执行的参数）
        seen_tools: set[str] = set()
        for node in ordered:
            if node.tool_id in seen_tools:
                continue
            if node.status != "completed":
                continue
            seen_tools.add(node.tool_id)

            descriptor = self._plugins.get(node.tool_id, {})
            methods_template = descriptor.get("methods_template", "")

            if methods_template:
                # 构建模板变量
                template_vars = dict(node.parameters)
                template_vars["version"] = node.tool_version
                template_vars["tool_id"] = node.tool_id
                template_vars["tool_name"] = descriptor.get("name", node.tool_id)

                # 数据库信息
                for db_def in descriptor.get("databases", []):
                    db_name = db_def.get("description", db_def.get("id", ""))
                    template_vars["db_name"] = db_name

                try:
                    text = methods_template.format(**template_vars)
                except (KeyError, IndexError):
                    # 模板中有未知变量，使用原始模板
                    text = methods_template

                lines.append(text.strip())
                lines.append("")
            else:
                lines.append(
                    f"{node.tool_id} v{node.tool_version} was used "
                    f"with default parameters."
                )
                lines.append("")

        return "\n".join(lines) + "\n"

    def generate_parameters_csv(self) -> str:
        """生成参数 CSV 表

        列: tool_id, tool_version, parameter_name, parameter_value, sample_id
        """
        rows = self._conn.execute(
            "SELECT execution_id, sample_id, tool_id, tool_version, parameters "
            "FROM executions WHERE status = 'completed' ORDER BY created_at"
        ).fetchall()

        output = StringIO()
        writer = csv.writer(output)
        writer.writerow([
            "tool_id", "tool_version", "parameter_name",
            "parameter_value", "sample_id", "execution_id",
        ])

        for row in rows:
            params = json.loads(row["parameters"]) if row["parameters"] else {}
            for param_name, param_value in params.items():
                writer.writerow([
                    row["tool_id"],
                    row["tool_version"] or "",
                    param_name,
                    str(param_value),
                    row["sample_id"],
                    row["execution_id"],
                ])

        return output.getvalue()

    # ── Reproducibility Export ────────────────────────────────

    def export_for_reproducibility(
        self,
        output_dir: str | Path,
        sample_id: Optional[str] = None,
    ) -> dict[str, str]:
        """导出可复现性文件

        生成:
          - Snakefile: 工作流定义
          - config.yaml: 参数配置

        Args:
            output_dir: 输出目录
            sample_id: 如果指定，只导出该样本的流水线

        Returns:
            {filename: filepath} 已生成文件映射
        """
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        result: dict[str, str] = {}

        # 1. 生成 Snakefile
        dag = self._reconstructor.rebuild_dag(sample_id=sample_id)
        snakefile_content = self._reconstructor.generate_snakefile(
            dag, self._plugins,
        )
        snakefile_path = output_dir / "Snakefile"
        snakefile_path.write_text(snakefile_content, encoding="utf-8")
        result["Snakefile"] = str(snakefile_path)

        # 2. 生成 config.yaml
        config_content = self._generate_config_yaml(dag)
        config_path = output_dir / "config.yaml"
        config_path.write_text(config_content, encoding="utf-8")
        result["config.yaml"] = str(config_path)

        logger.info("可复现性导出完成: %s", output_dir)
        return result

    def _generate_config_yaml(self, dag) -> str:
        """生成 config.yaml 内容"""
        import yaml

        config: dict[str, Any] = {
            "project": self._project_name,
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "samples": {},
            "tools": {},
        }

        # 样本信息
        for sample_id in dag.sample_ids:
            row = self._conn.execute(
                "SELECT * FROM samples WHERE sample_id = ?", (sample_id,)
            ).fetchone()
            if row:
                config["samples"][sample_id] = {
                    "name": row["name"],
                    "source": row["source"] or "",
                }

        # 工具参数
        for node in dag.topological_order():
            if node.tool_id not in config["tools"]:
                config["tools"][node.tool_id] = {
                    "version": node.tool_version,
                    "parameters": node.parameters,
                }

        return yaml.dump(
            config, default_flow_style=False,
            allow_unicode=True, sort_keys=False,
        )

    # ── Archive Export ────────────────────────────────────────

    def export_archive(
        self,
        output_dir: str | Path,
        project_dir: str | Path,
    ) -> str:
        """导出完整项目归档

        打包内容:
          - project.db (SQLite 数据库副本)
          - methods.txt + parameters.csv
          - Snakefile + config.yaml
          - metadata.json (项目元数据)

        Args:
            output_dir: 输出目录
            project_dir: 项目本地目录（包含 project.db）

        Returns:
            归档文件路径 (.zip)
        """
        output_dir = Path(output_dir)
        project_dir = Path(project_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        # 创建临时打包目录
        archive_name = f"{self._project_name}_{int(time.time())}"
        staging_dir = output_dir / archive_name
        staging_dir.mkdir(parents=True, exist_ok=True)

        try:
            # 1. 复制 project.db
            db_src = project_dir / "project.db"
            if db_src.exists():
                shutil.copy2(str(db_src), str(staging_dir / "project.db"))

            # 2. 生成论文导出文件
            self.export_for_paper(staging_dir)

            # 3. 生成可复现性导出文件
            self.export_for_reproducibility(staging_dir)

            # 4. 生成 metadata.json
            metadata = {
                "project_name": self._project_name,
                "exported_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "h2ometa_version": "2.0.0",
                "tools_used": self._get_tools_summary(),
                "samples_count": self._get_samples_count(),
                "executions_count": self._get_executions_count(),
            }
            metadata_path = staging_dir / "metadata.json"
            metadata_path.write_text(
                json.dumps(metadata, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            # 5. 打包为 zip
            archive_path = shutil.make_archive(
                str(output_dir / archive_name), "zip", str(staging_dir),
            )

            logger.info("项目归档完成: %s", archive_path)
            return archive_path

        finally:
            # 清理临时目录
            shutil.rmtree(str(staging_dir), ignore_errors=True)

    # ── 内部方法 ──────────────────────────────────────────────

    def _get_tools_summary(self) -> list[dict[str, str]]:
        """获取已使用工具摘要"""
        rows = self._conn.execute(
            "SELECT DISTINCT tool_id, tool_version FROM executions "
            "WHERE status = 'completed' ORDER BY tool_id"
        ).fetchall()
        return [
            {"tool_id": row["tool_id"], "version": row["tool_version"] or ""}
            for row in rows
        ]

    def _get_samples_count(self) -> int:
        """获取样本总数"""
        row = self._conn.execute("SELECT COUNT(*) AS cnt FROM samples").fetchone()
        return row["cnt"] if row else 0

    def _get_executions_count(self) -> int:
        """获取执行总数"""
        row = self._conn.execute("SELECT COUNT(*) AS cnt FROM executions").fetchone()
        return row["cnt"] if row else 0
