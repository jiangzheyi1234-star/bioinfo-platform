"""ToolBridge 后端服务层 — 工作台工具执行编排、结果查询。

职责：
  - 工具执行编排（参数组装、输入导入、调用 tool_engine）
  - 远程文件读取与结果解析
  - 执行历史查询
  - 引物设计结果聚合

此模块无 Qt 依赖，可独立测试。
"""

from __future__ import annotations

import copy
import csv
import datetime
import json
import logging
import shlex
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

from core.data.database_service import DatabaseService
from core.data.execution_query_service import ExecutionQueryService
from core.execution.artifact_store import ArtifactStore
from core.execution.execution_status_service import ExecutionStatusService
from core.execution.tool_bridge_specs import (
    DETECTION_WORKFLOW_ORDER,
    DETECTION_WORKFLOW_SPECS,
    TARGETED_RESULT_TOOL_IDS,
    build_integrated_workbench_config,
)
from core.execution.result_parsers import (
    build_multiplex_columns as _parse_build_multiplex_columns,
)
from core.execution.result_parsers import (
    parse_multiplex_result_text as _parse_multiplex_result_text,
)
from core.execution.result_parsers import (
    parse_primer_result_text as _parse_primer_result_text,
)
from core.execution.single_tool_result_parsers import (
    parse_busco_summary_text,
    parse_fastp_json,
    parse_generic_result_table,
    parse_json_object,
    parse_prokka_stats_text,
    summarize_table_row,
)
from core.execution.single_tool_view_builder import (
    build_artifact_result_view,
    build_single_tool_view,
    normalize_result_view,
    section_from_view,
)
from core.execution.workbench_view_builders import build_multiplex_view, build_primer_view

if TYPE_CHECKING:
    from core.plugins.plugin_registry import PluginRegistry
    from core.service_locator import ServiceLocator

logger = logging.getLogger(__name__)
_TOOL_ARCHETYPES: dict[str, str] = {
    "fastp": "qc_report",
    "hostile": "qc_report",
    "kraken2": "taxonomy_profile",
    "centrifuge": "taxonomy_profile",
    "metaphlan": "taxonomy_profile",
    "bracken": "taxonomy_profile",
    "gtdbtk": "taxonomy_profile",
    "krona": "html_report",
    "prokka": "annotation_table",
    "bakta": "annotation_table",
    "prodigal": "annotation_table",
    "eggnog": "annotation_table",
    "blastn": "annotation_table",
    "abricate": "annotation_table",
    "amrfinderplus": "annotation_table",
    "rgi": "annotation_table",
    "integron_finder": "annotation_table",
    "isescan": "annotation_table",
    "genomad": "annotation_table",
    "quast": "quality_assessment",
    "busco": "quality_assessment",
    "checkm2": "quality_assessment",
    "gunc": "quality_assessment",
    "concoct": "artifact_collection",
    "das_tool": "artifact_collection",
    "maxbin2": "artifact_collection",
    "metabat2": "artifact_collection",
    "semibin2": "artifact_collection",
    "unknown_sample_detection": "workflow_product",
    "wastewater_metagenomics_basic": "workflow_product",
    "animal_metagenomics_basic": "workflow_product",
    "primer_design": "workflow_product",
    "multiplex_primer_panel": "workflow_product",
}
_WORKFLOW_PRODUCT_TOOL_IDS = (*DETECTION_WORKFLOW_ORDER, "primer_design", "multiplex_primer_panel")
_QUALITY_SUMMARY_KEYS: dict[str, list[tuple[str, str, str]]] = {
    "quast": [("Contigs", "# contigs", "primary"), ("总长度", "Total length", "info"), ("N50", "N50", "success")],
    "checkm2": [("Completeness", "Completeness", "success"), ("Contamination", "Contamination", "warning"), ("GC", "GC_Content", "info")],
    "gunc": [("Mapped Genes", "n_genes_mapped", "primary"), ("CSS", "clade_separation_score", "info"), ("Contamination", "contamination_portion", "warning")],
}
@dataclass
class ToolCheckResult:
    tool_id: str
    env_name: str
    ok: bool


@dataclass
class ExecutionResult:
    status: str
    message: str = ""
    execution_id: str = ""
    sample_id: str = ""


@dataclass
class PrimerView:
    description: str = ""
    status: dict = field(default_factory=dict)
    parameters: list = field(default_factory=list)
    summary: list = field(default_factory=list)
    rows: list = field(default_factory=list)
    artifacts: list = field(default_factory=list)
    remote_result_dir: str = ""


class ToolBridgeService:
    """工作台工具执行编排服务。

    从 ToolBridge (UI层) 提取的后端逻辑，处理：
      - 工具执行编排
      - 远程文件读取
      - 结果解析
      - 执行历史查询
    """

    def __init__(
        self,
        service_locator: ServiceLocator | None = None,
        plugin_registry: PluginRegistry | None = None,
    ):
        self._service_locator = service_locator
        self._plugin_registry = plugin_registry
        self._manifest_name = "artifacts_manifest.json"
        self._result_artifact_names = {
            "primer_design": [
                "primer_result_final_2.txt",
                "primer_result_final.txt",
                "primer_result.txt",
                "dimer_score.txt",
            ],
            "multiplex_primer_panel": [
                "multiplex_panel.txt",
                "synthesis_order.txt",
                "pool_cross_dimer.txt",
                "insilico_pcr_result.txt",
                "optimization_log.txt",
            ],
            "targeted_sequencing": [
                "targeted_seq_report.txt",
            ],
        }
        self._execution_status_service = ExecutionStatusService()
        self._remote_status_cache = self._execution_status_service.cache
        self._database_service = DatabaseService()
        self._artifact_store = ArtifactStore(self._get_current_project_dir, manifest_name=self._manifest_name)

    def set_service_locator(self, sl: ServiceLocator | None) -> None:
        self._service_locator = sl

    def set_plugin_registry(self, pr: PluginRegistry | None) -> None:
        self._plugin_registry = pr

    @staticmethod
    def base_integrated_workbench_config() -> dict:
        return build_integrated_workbench_config()

    @staticmethod
    def parse_primer_result_text(content: str) -> list[dict[str, str]]:
        return _parse_primer_result_text(content)

    @staticmethod
    def parse_multiplex_result_text(content: str) -> list[dict[str, str]]:
        return _parse_multiplex_result_text(content)

    @staticmethod
    def _build_multiplex_columns(rows: list[dict[str, str]]) -> list[dict[str, str]]:
        return _parse_build_multiplex_columns(rows)

    @staticmethod
    def _parse_bracken_abundance_rows(tsv_path: Path | None, top_n: int = 20) -> list[dict[str, str]]:
        if tsv_path is None or not tsv_path.exists():
            return []
        try:
            with tsv_path.open("r", encoding="utf-8", newline="") as fh:
                reader = csv.DictReader(fh, delimiter="\t")
                items: list[dict[str, Any]] = []
                for row in reader:
                    try:
                        reads = int(float(str(row.get("new_est_reads", "0") or "0")))
                    except ValueError:
                        reads = 0
                    try:
                        fraction = float(str(row.get("fraction_total_reads", "0") or "0"))
                    except ValueError:
                        fraction = 0.0
                    items.append(
                        {
                            "name": str(row.get("name", "") or "").strip() or "未命名",
                            "reads": reads,
                            "percentage": fraction * 100,
                        }
                    )
        except Exception:
            logger.exception("Failed to parse Bracken abundance file: %s", tsv_path)
            return []

        items.sort(key=lambda item: item["reads"], reverse=True)
        rows: list[dict[str, str]] = []
        for idx, item in enumerate(items[:top_n], 1):
            rows.append(
                {
                    "rank": str(idx),
                    "name": item["name"],
                    "reads": f'{item["reads"]:,}',
                    "percentage": f'{item["percentage"]:.2f}%',
                }
            )
        return rows

    @staticmethod
    def _build_read_flow_chart(fastp_json_path: Path | None, kreport_summary: dict[str, Any]) -> dict[str, Any] | None:
        stages: list[dict[str, Any]] = []
        if fastp_json_path is not None and fastp_json_path.exists():
            try:
                payload = json.loads(fastp_json_path.read_text(encoding="utf-8"))
                summary = payload.get("summary", {})
                before = summary.get("before_filtering", {})
                after = summary.get("after_filtering", {})
                raw_reads = int(before.get("total_reads", 0) or 0)
                qc_reads = int(after.get("total_reads", 0) or 0)
                if raw_reads > 0:
                    stages.append({"name": "原始 Reads", "value": raw_reads})
                if qc_reads > 0:
                    stages.append({"name": "QC 后", "value": qc_reads})
            except Exception:
                logger.exception("Failed to parse fastp summary for funnel chart: %s", fastp_json_path)

        classified = int(kreport_summary.get("classified_reads", 0) or 0)
        unclassified = int(kreport_summary.get("unclassified_reads", 0) or 0)
        total = int(kreport_summary.get("total_reads", 0) or 0)
        if total > 0:
            stages.append({"name": "送分类 Reads", "value": total})
        if classified > 0:
            stages.append({"name": "已分类", "value": classified})
        if unclassified > 0:
            stages.append({"name": "未分类", "value": unclassified})

        if len(stages) < 2:
            return None
        return {"type": "funnel", "title": "分析流程摘要", "data": stages}

    def _get_project_manager(self):
        if self._service_locator is None:
            return None
        return getattr(self._service_locator, "project_manager", None)

    def _ensure_default_project(self, pm) -> None:
        """没有打开项目时，自动创建并打开默认项目。"""
        try:
            existing = pm.list_projects()
            for p in existing:
                if p.name == "默认项目":
                    pm.open_project(p.project_id)
                    logger.info("自动打开已有默认项目: %s", p.project_id)
                    return

            project_id = pm.create_project("默认项目", description="自动创建的默认项目")
            pm.open_project(project_id)
            logger.info("自动创建并打开默认项目: %s", project_id)
        except Exception:
            logger.exception("自动创建默认项目失败")

    def _get_ssh_service(self):
        if self._service_locator is None:
            return None
        return getattr(self._service_locator, "ssh_service", None)

    def _get_data_registry(self):
        if self._service_locator is None:
            return None
        return getattr(self._service_locator, "data_registry", None)

    def _get_tool_engine(self):
        if self._service_locator is None:
            return None
        return getattr(self._service_locator, "tool_engine", None)

    def find_latest_completed_execution(self, tool_ids: list[str]) -> dict | None:
        pm = self._get_project_manager()
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
        pm = self._get_project_manager()
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

        ssh = self._get_ssh_service()
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

        ssh = self._get_ssh_service()
        if ssh is None or not getattr(ssh, "is_connected", False):
            return None

        try:
            rc, out, _ = ssh.run(f"wc -l < {shlex.quote(file_path)} 2>/dev/null", timeout=10)
            if rc == 0:
                return int((out or "0").strip())
        except Exception:
            logger.exception("统计远端文件行数失败: %s", file_path)
        return None

    @staticmethod
    def safe_json_loads(raw: str) -> dict:
        if not raw:
            return {}
        try:
            data = json.loads(raw)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    @staticmethod
    def _strict_json_loads(raw: str, *, context: str) -> dict[str, Any]:
        if not raw:
            return {}
        try:
            data = json.loads(raw)
        except Exception as exc:
            raise RuntimeError(f"{context} JSON 解析失败") from exc
        if not isinstance(data, dict):
            raise RuntimeError(f"{context} 必须是 JSON object")
        return data

    def get_default_primer_result_dir(self) -> str:
        default_root = ""

        try:
            from config import get_config

            runtime_cfg = get_config().get("runtime", {})
            configured_root = str(runtime_cfg.get("primer_result_root", "") or "").strip()
            if configured_root:
                default_root = configured_root.rstrip("/")
        except Exception:
            logger.debug("无法从配置读取 runtime.primer_result_root，回退到插件默认值")

        if self._plugin_registry is not None:
            try:
                desc = self._plugin_registry.get_descriptor("primer_design")
                for param in desc.get("parameters", []):
                    if param.get("name") == "workflow_root":
                        configured_root = str(param.get("default") or "").strip()
                        if configured_root and not default_root:
                            default_root = configured_root.rstrip("/")
                        break
            except Exception:
                logger.debug("无法从 primer_design 插件描述符读取 workflow_root，使用默认结果目录")

        if default_root:
            return f"{default_root.rstrip('/')}/my_result"
        return "my_result"

    def _get_current_project_dir(self) -> Path | None:
        pm = self._get_project_manager()
        if pm is None:
            return None
        project_dir = getattr(pm, "current_project_dir", None)
        return Path(project_dir) if project_dir else None

    def _execution_results_dir(self, execution_id: str) -> Path | None:
        project_dir = self._get_current_project_dir()
        if project_dir is None or not execution_id:
            return None
        return project_dir / "results" / execution_id

    def _manifest_path(self, cache_key: str) -> Path | None:
        return self._artifact_store.manifest_path(cache_key)

    def _load_manifest(self, cache_key: str) -> dict | None:
        return self._artifact_store.load_manifest(cache_key)

    def _normalize_artifacts(self, artifacts: list[dict] | None) -> list[dict]:
        return self._artifact_store.normalize_artifacts(artifacts)

    def _artifact_by_name(self, artifacts: list[dict], name: str) -> dict | None:
        return self._artifact_store.artifact_by_name(artifacts, name)

    def _local_artifact_path(self, artifacts: list[dict], name: str) -> Path | None:
        artifact = self._artifact_by_name(artifacts, name)
        if artifact is None:
            return None
        local_path = str(artifact.get("local_path") or "").strip()
        if not local_path:
            return None
        path = Path(local_path)
        return path if path.exists() else None

    def _read_local_artifact_text(self, artifacts: list[dict], name: str) -> str:
        return self._artifact_store.read_local_artifact_text(artifacts, name)

    def _count_local_artifact_lines(self, artifacts: list[dict], name: str) -> int | None:
        return self._artifact_store.count_local_artifact_lines(artifacts, name)

    @staticmethod
    def _available_artifacts(artifacts: list[dict]) -> list[dict]:
        return [artifact for artifact in artifacts if artifact.get("available")]

    @staticmethod
    def _local_result_dir_for_execution(execution_id: str, artifacts: list[dict]) -> str:
        for artifact in artifacts:
            local_path = str(artifact.get("local_path") or "").strip()
            if not local_path:
                continue
            return str(Path(local_path).parent)
        return ""

    def _artifact_from_result_views(
        self,
        descriptor: dict[str, Any],
        artifacts: list[dict],
        *,
        sample_id: str = "",
        preferred_types: tuple[str, ...] = (),
    ) -> dict[str, Any] | None:
        result_views = list(descriptor.get("result_views", []) or [])
        for view in result_views:
            if preferred_types and str(view.get("type") or "").strip() not in preferred_types:
                continue
            data_source = str(view.get("data_source") or "").strip().replace("{sample_id}", sample_id)
            if not data_source:
                continue
            artifact = self._artifact_by_name(artifacts, Path(data_source).name)
            if artifact and artifact.get("available"):
                return artifact
        return None

    @staticmethod
    def _first_available_artifact_with_suffix(artifacts: list[dict], suffixes: tuple[str, ...]) -> dict[str, Any] | None:
        normalized_suffixes = tuple(item.lower() for item in suffixes)
        for artifact in artifacts:
            if not artifact.get("available"):
                continue
            name = str(artifact.get("name") or "").lower()
            if name.endswith(normalized_suffixes):
                return artifact
        return None

    @staticmethod
    def _parse_table_file(path: Path) -> tuple[list[dict[str, str]], list[dict[str, Any]], dict[str, Any]]:
        payload = parse_generic_result_table(path)
        return (
            list(payload.get("columns") or []),
            list(payload.get("rows") or []),
            dict(payload.get("metrics") or {}),
        )

    @staticmethod
    def _summarize_row_count(rows: list[dict[str, Any]], *, label: str) -> list[dict[str, str]]:
        return [{"label": label, "value": str(len(rows)), "tone": "primary"}]

    def _remote_cache_key(self, tool_id: str, remote_result_dir: str) -> str:
        return self._artifact_store.remote_cache_key(tool_id, remote_result_dir)

    def _remote_file_exists(self, ssh: Any, remote_path: str) -> bool:
        return self._artifact_store.remote_file_exists(ssh, remote_path)

    def _cache_remote_artifacts(self, tool_id: str, remote_result_dir: str) -> list[dict]:
        return self._artifact_store.cache_remote_artifacts(
            tool_id=tool_id,
            remote_result_dir=remote_result_dir,
            result_artifact_names=self._result_artifact_names,
            ssh=self._get_ssh_service(),
        )

    def list_local_execution_artifacts(self, execution_id: str) -> list[dict]:
        normalized_execution_id = str(execution_id or "").strip()
        if not normalized_execution_id:
            return []
        return self._artifact_store.list_local_execution_artifacts(normalized_execution_id)

    def _persist_execution_artifacts(
        self,
        execution_id: str,
        tool_id: str,
        output_dir: str,
        artifacts: list[dict],
    ) -> list[dict]:
        """Persist downloaded artifacts under results/<execution_id>/ and write manifest."""
        return self._artifact_store.persist_execution_artifacts(
            execution_id=execution_id,
            tool_id=tool_id,
            output_dir=output_dir,
            artifacts=artifacts,
        )

    def download_execution_artifacts(self, execution_id: str) -> list[dict]:
        return self.list_local_execution_artifacts(execution_id)

    def _build_primer_view_from_artifacts(
        self,
        artifacts: list[dict],
        remote_result_dir: str,
        description: str,
        status: dict,
        parameters: list[dict],
    ) -> dict | None:
        base = self.base_integrated_workbench_config()["views"]["primer_design"]
        primer_result_text = self._read_local_artifact_text(artifacts, "primer_result_final_2.txt")
        parsed_rows = self.parse_primer_result_text(primer_result_text)
        if not parsed_rows:
            return None

        all_candidates_count = self._count_local_artifact_lines(artifacts, "primer_result.txt") or len(parsed_rows)
        filtered_count = self._count_local_artifact_lines(artifacts, "primer_result_final.txt") or len(parsed_rows)
        dimer_count = self._count_local_artifact_lines(artifacts, "dimer_score.txt") or len(parsed_rows)
        return build_primer_view(
            base_view=base,
            primer_result_final_2_text=primer_result_text,
            all_candidates_count=all_candidates_count,
            filtered_count=filtered_count,
            dimer_count=dimer_count,
            description=description,
            status=status,
            parameters=parameters,
            artifacts=artifacts,
            remote_result_dir=remote_result_dir,
        )

    def _build_multiplex_view_from_artifacts(
        self,
        artifacts: list[dict],
        remote_result_dir: str,
        description: str,
        status: dict,
        parameters: list[dict],
    ) -> dict | None:
        multiplex_text = self._read_local_artifact_text(artifacts, "multiplex_panel.txt")
        parsed_rows = self.parse_multiplex_result_text(multiplex_text)
        if not parsed_rows:
            return None
        synthesis_count = self._count_local_artifact_lines(artifacts, "synthesis_order.txt")
        optimization_count = self._count_local_artifact_lines(artifacts, "optimization_log.txt")
        return build_multiplex_view(
            multiplex_panel_text=multiplex_text,
            synthesis_count=synthesis_count,
            optimization_count=optimization_count,
            description=description,
            status=status,
            parameters=parameters,
            artifacts=artifacts,
            remote_result_dir=remote_result_dir,
        )

    def get_live_primer_design_view(self) -> dict | None:
        execution = self.find_latest_completed_execution(["primer_design"])
        if not execution:
            return None
        try:
            return self._build_result_view_for_execution(str(execution["execution_id"] or ""), execution)
        except Exception:
            logger.exception("Failed to build live primer workflow view: %s", execution["execution_id"])
            return None

    def build_primer_view_from_result_dir(self, remote_result_dir: str) -> dict | None:
        normalized_dir = (remote_result_dir or "").strip().rstrip("/")
        if not normalized_dir:
            return None
        artifacts = self._cache_remote_artifacts("primer_design", normalized_dir)
        return self._build_primer_view_from_artifacts(
            artifacts=artifacts,
            remote_result_dir=normalized_dir,
            description=f"当前结果来自远程目录：{normalized_dir}",
            status={
                "state": "completed",
                "label": "已加载远程结果",
                "detail": "结果文件已同步到当前项目本地，并从本地结果构建视图。",
            },
            parameters=[
                {"label": "结果目录", "value": normalized_dir},
                {"label": "结果来源", "value": "远程目录同步到本地"},
                {"label": "主文件", "value": "primer_result_final_2.txt"},
            ],
        )

    def get_primer_view_for_execution(self, execution_id: str) -> dict | None:
        normalized_execution_id = str(execution_id or "").strip()
        if not normalized_execution_id:
            return None
        row = self._get_execution_result_row(normalized_execution_id)
        if row is None or str(row["tool_id"] or "") != "primer_design":
            return None
        artifacts = self._normalize_artifacts(self.list_local_execution_artifacts(normalized_execution_id))
        description = (
            "用途：基于本地已同步的 primer 结果展示推荐引物、靶区位置与产物信息。"
            "\n实现：仅读取当前项目内缓存的结果工件，不在结果展示阶段触发远端查询。"
        )
        status = {
            "state": "completed",
            "label": "结果可用",
            "detail": "已从本地结果缓存加载 primer 产物，可直接查看与导出。",
        }
        if not artifacts:
            return None
        ctx = self._build_execution_result_context(row, artifacts)
        parameters = [
            {
                "label": "任务 ID",
                "value": normalized_execution_id,
                "description": "当前本地结果对应的执行记录 ID。",
            },
            {
                "label": "主结果",
                "value": "primer_result_final_2.txt",
                "description": "主结果文件，包含推荐引物对及位点信息。",
            },
        ]
        if ctx["remote_result_dir"]:
            parameters.insert(
                0,
                {
                    "label": "结果目录",
                    "value": ctx["remote_result_dir"],
                    "description": "执行时记录的远端结果目录；结果展示优先使用本地已同步工件。",
                },
            )
        if ctx["local_result_dir"]:
            parameters.append(
                {
                    "label": "本地结果目录",
                    "value": ctx["local_result_dir"],
                    "description": "当前项目中缓存该次执行结果的本地目录。",
                }
            )
        return self._build_primer_view_from_artifacts(
            artifacts=artifacts,
            remote_result_dir=ctx["remote_result_dir"],
            description=description,
            status=status,
            parameters=parameters,
        )

    def build_multiplex_view_from_result_dir(self, remote_result_dir: str) -> dict | None:
        normalized_dir = (remote_result_dir or "").strip().rstrip("/")
        if not normalized_dir:
            return None
        artifacts = self._cache_remote_artifacts("multiplex_primer_panel", normalized_dir)
        return self._build_multiplex_view_from_artifacts(
            artifacts=artifacts,
            remote_result_dir=normalized_dir,
            description=f"查看最终多重引物池结果与相关报告：{normalized_dir}",
            status={
                "state": "completed",
                "label": "结果可用",
                "detail": "结果文件已同步到当前项目本地，可直接打开本地文件。",
            },
            parameters=[
                {
                    "label": "结果目录",
                    "value": normalized_dir,
                    "description": "指定要读取的远程结果目录，用于回显历史 multiplex 结果。",
                },
                {
                    "label": "主结果",
                    "value": "multiplex_panel.txt",
                    "description": "主结果文件，展示入池引物与扩增子组合。",
                },
                {
                    "label": "合成订单",
                    "value": "synthesis_order.txt",
                    "description": "合成订单文件，可直接用于合成委托。",
                },
            ],
        )

    def get_live_multiplex_primer_panel_view(self) -> dict | None:
        execution = self.find_latest_completed_execution(["multiplex_primer_panel"])
        if not execution:
            return None
        try:
            return self._build_result_view_for_execution(str(execution["execution_id"] or ""), execution)
        except Exception:
            logger.exception("Failed to build live multiplex workflow view: %s", execution["execution_id"])
            return None

    def get_multiplex_view_for_execution(self, execution_id: str) -> dict | None:
        normalized_execution_id = str(execution_id or "").strip()
        if not normalized_execution_id:
            return None
        row = self._get_execution_result_row(normalized_execution_id)
        if row is None or str(row["tool_id"] or "") != "multiplex_primer_panel":
            return None
        artifacts = self._normalize_artifacts(self.list_local_execution_artifacts(normalized_execution_id))
        description = (
            "用途：用于查看本地已同步的多重引物池结果、合成清单与相关评分。"
            "\n实现：仅消费当前项目中的本地结果工件，不在结果展示阶段访问远端环境。"
        )
        status = {
            "state": "completed",
            "label": "结果可用",
            "detail": "已从本地结果缓存加载 multiplex 产物。",
        }
        if not artifacts:
            return None
        ctx = self._build_execution_result_context(row, artifacts)
        parameters = [{"label": "任务 ID", "value": normalized_execution_id}]
        if ctx["remote_result_dir"]:
            parameters.insert(0, {"label": "结果目录", "value": ctx["remote_result_dir"]})
        if ctx["local_result_dir"]:
            parameters.append({"label": "本地结果目录", "value": ctx["local_result_dir"]})
        parameters.extend(
            [
                {"label": "主结果", "value": "multiplex_panel.txt"},
                {"label": "合成订单", "value": "synthesis_order.txt"},
            ]
        )
        return self._build_multiplex_view_from_artifacts(
            artifacts=artifacts,
            remote_result_dir=ctx["remote_result_dir"],
            description=description,
            status=status,
            parameters=parameters,
        )

    def get_tools(self) -> list[dict]:
        if not self._plugin_registry:
            logger.warning("PluginRegistry not initialized")
            return []

        tools: list[dict] = []
        try:
            for tool_id in self._plugin_registry.list_all_ids():
                desc = self._plugin_registry.get_descriptor(tool_id)
                tools.append(
                    {
                        "id": tool_id,
                        "name": desc.get("name", tool_id),
                        "category": desc.get("category", "unknown"),
                        "description": desc.get("description", ""),
                        "version": desc.get("version", "unknown"),
                        "inputs_count": len(desc.get("inputs", [])),
                        "params_count": len(desc.get("parameters", [])),
                        "db_count": len(desc.get("databases", [])),
                    }
                )
        except Exception:
            logger.exception("Failed to get tools")

        return tools

    def get_tool_descriptor(self, tool_id: str) -> dict:
        if not self._plugin_registry:
            logger.warning("PluginRegistry not initialized")
            return {}

        try:
            return self._plugin_registry.get_descriptor(tool_id)
        except Exception:
            logger.exception("Failed to get descriptor for %s", tool_id)
            return {}

    @staticmethod
    def _parse_execution_parameters(raw: str, *, execution_id: str, tool_id: str) -> dict[str, Any]:
        text = str(raw or "").strip()
        if not text:
            return {}
        try:
            payload = json.loads(text)
        except Exception as exc:
            raise RuntimeError(f"执行参数不是合法 JSON: tool={tool_id}, execution_id={execution_id}") from exc
        if not isinstance(payload, dict):
            raise RuntimeError(f"执行参数必须是对象: tool={tool_id}, execution_id={execution_id}")
        return payload

    @staticmethod
    def _parameter_items_from_dict(params: dict[str, Any]) -> list[dict[str, str]]:
        return [
            {"label": str(key), "value": str(value)}
            for key, value in params.items()
            if value not in ("", None)
        ]

    @staticmethod
    def _resolve_result_archetype(tool_id: str) -> str:
        normalized = str(tool_id or "").strip()
        if not normalized:
            raise RuntimeError("执行记录缺少 tool_id")
        archetype = _TOOL_ARCHETYPES.get(normalized)
        if archetype is None:
            raise RuntimeError(f"未定义结果 archetype: tool={normalized}")
        return archetype

    def execute_tool(self, tool_id: str, params: dict) -> ExecutionResult:
        try:
            if self._service_locator is None:
                return ExecutionResult(status="error", message="服务未就绪")

            # 没有项目时自动创建默认项目，触发 ToolEngine 初始化
            pm = self._get_project_manager()
            if pm is not None and pm.current_project is None:
                self._ensure_default_project(pm)

            # open_project 的信号可能已同步触发了 _rebuild_engine，
            # 但以防万一（跨线程队列连接），手动确保 engine 就绪
            tool_engine = self._get_tool_engine()
            if tool_engine is None and pm is not None and pm.current_project is not None:
                sl = self._service_locator
                if hasattr(sl, "_rebuild_registry_and_engine"):
                    sl._rebuild_registry_and_engine()
                tool_engine = self._get_tool_engine()

            if tool_engine is None:
                return ExecutionResult(status="error", message="ToolEngine 未初始化，请先连接 SSH 或创建项目")

            pm = self._get_project_manager()
            if pm is None or pm.current_project is None:
                return ExecutionResult(status="no_project", message="请先选择或创建项目")

            if hasattr(pm, "backup_current_project"):
                try:
                    pm.backup_current_project(reason="before_run")
                except Exception:
                    logger.exception("Failed to backup project state before running %s", tool_id)

            descriptor = self._plugin_registry.get_descriptor(tool_id)

            sample_id = self.ensure_sample_id(pm, params, descriptor)
            if not sample_id:
                return ExecutionResult(status="no_sample", message="无法确定样本，请先创建项目样本")

            self.normalize_project_remote_base(pm)
            input_data_ids = self.import_inputs(pm, sample_id, descriptor, params)

            run_params = self.extract_run_params(descriptor, params)
            database_paths = self.build_database_paths(tool_id, descriptor)
            database_paths.update(self.extract_database_paths(descriptor, params))
            self.validate_required_databases(tool_id, descriptor, database_paths)

            execution_id = tool_engine.execute(
                tool_id=tool_id,
                input_data_ids=input_data_ids,
                parameters=run_params,
                sample_id=sample_id,
                triggered_by="manual",
                database_paths=database_paths,
            )

            logger.info("工具已提交执行: tool=%s execution_id=%s sample=%s", tool_id, execution_id, sample_id)
            return ExecutionResult(
                status="ok",
                execution_id=execution_id,
                sample_id=sample_id,
                message=f"任务已提交 ({execution_id[:16]}...)",
            )

        except ValueError as e:
            logger.warning("execute_tool ValueError: %s", e)
            return ExecutionResult(status="error", message=str(e))
        except Exception:
            logger.exception("Failed to start tool %s", tool_id)
            return ExecutionResult(status="error", message="内部错误，请查看日志")

    def normalize_project_remote_base(self, pm) -> None:
        project = getattr(pm, "current_project", None)
        if project is None:
            return

        project_id = str(getattr(project, "project_id", "") or "").strip()
        current_remote_base = str(getattr(project, "remote_base", "") or "").strip()
        if not project_id:
            return

        needs_fix = (
            not current_remote_base
            or current_remote_base.startswith("~")
            or current_remote_base == "/h2ometa"
            or current_remote_base.startswith("/h2ometa/")
        )
        if not needs_fix:
            return

        ssh = self._get_ssh_service()
        if ssh is None or not getattr(ssh, "is_connected", False):
            return

        remote_home = ""
        try:
            rc, out, _ = ssh.run('printf "%s" "$HOME"', timeout=10)
            if rc == 0:
                remote_home = str(out or "").strip()
        except Exception:
            logger.exception("Failed to resolve remote HOME for project %s", project_id)

        if not remote_home or remote_home == "/":
            return

        normalized = f"{remote_home.rstrip('/')}/.h2ometa/projects/{project_id}"
        project.remote_base = normalized

        try:
            if hasattr(pm, "update_current_project_remote_base"):
                pm.update_current_project_remote_base(normalized)
            elif hasattr(pm, "_index") and project_id in pm._index:
                pm._index[project_id]["remote_base"] = normalized
                save_index = getattr(pm, "_save_index", None)
                if callable(save_index):
                    save_index()
        except Exception:
            logger.exception("Failed to persist normalized remote_base for project %s", project_id)

    @staticmethod
    def _descriptor_consumes_database_var(tool_id: str, descriptor: dict, param_name: str, db_id: str) -> None:
        command_template = str(descriptor.get("command_template", "") or "")
        marker = f"{{{{ {param_name} }}}}"
        compact_marker = f"{{{{{param_name}}}}}"
        if marker in command_template or compact_marker in command_template:
            return
        raise ValueError(
            f"工具 {tool_id} 声明了数据库绑定但命令模板未消费该变量: "
            f"db_id={db_id}, param={param_name}"
        )

    def get_latest_sample_id(self, pm) -> str:
        try:
            db = pm.db
            cursor = db.cursor()
            cursor.execute("SELECT sample_id FROM samples ORDER BY rowid DESC LIMIT 1")
            row = cursor.fetchone()
            if row:
                return row[0]
        except Exception:
            logger.exception("查询最近样本 ID 失败")
        return ""

    def build_database_paths(self, tool_id: str, descriptor: dict | None = None) -> dict:
        from config import get_config

        if self._plugin_registry is None:
            raise ValueError(f"工具 {tool_id} 无法解析数据库绑定: 插件注册表未初始化")

        cfg = get_config()
        db_cfg = cfg.get("databases", {}) if isinstance(cfg.get("databases", {}), dict) else {}
        db_root = str(db_cfg.get("db_root", "") or "").strip()
        overrides = db_cfg.get("overrides", {})
        if not isinstance(overrides, dict):
            overrides = {}

        desc = descriptor or self._plugin_registry.get_descriptor(tool_id)
        db_decls = desc.get("databases", [])
        if not isinstance(db_decls, list):
            raise ValueError(f"工具 {tool_id} 的 databases 声明格式错误")

        paths: dict[str, str] = {}
        for decl in db_decls:
            if not isinstance(decl, dict):
                raise ValueError(f"工具 {tool_id} 的数据库声明格式错误: {decl!r}")

            db_id = str(decl.get("id", "")).strip()
            param_name = str(decl.get("param_name", "")).strip()
            if not db_id:
                raise ValueError(f"工具 {tool_id} 的数据库声明缺少 id")
            if not param_name:
                raise ValueError(f"工具 {tool_id} 的数据库声明缺少 param_name: db_id={db_id}")
            self._descriptor_consumes_database_var(tool_id, desc, param_name, db_id)

            info = self._database_service.get_info(db_id)
            if info is None:
                raise ValueError(f"工具 {tool_id} 引用未注册数据库: db_id={db_id}")

            resolved = self._database_service.resolve_binding_value(db_id, db_root, overrides=overrides)
            if resolved:
                paths[param_name] = resolved
                logger.debug(
                    "数据库路径已匹配(binding): tool=%s, db_id=%s → %s=%s",
                    tool_id,
                    db_id,
                    param_name,
                    resolved,
                )

        return paths

    def ensure_sample_id(self, pm, params: dict, descriptor: dict) -> str:
        explicit_sample_id = str(params.get("__sample_id", "")).strip()
        if explicit_sample_id:
            return explicit_sample_id

        registry = self._get_data_registry()
        if registry is None:
            return ""

        sample_name = str(params.get("__sample_name", "")).strip()
        if not sample_name:
            for inp in descriptor.get("inputs", []):
                path = str(params.get(inp.get("name", ""), "")).strip()
                if path:
                    sample_name = Path(path).stem
                    break
        if not sample_name:
            sample_name = f"detection_{time.strftime('%Y%m%d_%H%M%S')}"

        sample_metadata: dict[str, str] = {}
        for inp in descriptor.get("inputs", []):
            input_name = str(inp.get("name", "")).strip()
            path = str(params.get(input_name, "")).strip()
            if not path:
                continue
            sample_metadata[f"input_{input_name}"] = path

        return registry.add_sample(
            sample_name,
            source="detection_page",
            metadata=sample_metadata,
        )

    def import_inputs(self, pm, sample_id: str, descriptor: dict, params: dict) -> list[str]:
        registry = self._get_data_registry()
        ssh = self._get_ssh_service()
        if registry is None or ssh is None or not getattr(ssh, "is_connected", False):
            raise ValueError("数据注册器或 SSH 未就绪")

        from core.data.data_importer import DataImporter

        importer = DataImporter(ssh_service=ssh, registry=registry)
        input_data_ids: list[str] = []

        for inp in descriptor.get("inputs", []):
            name = str(inp.get("name", ""))
            required = bool(inp.get("required", True))
            input_path = str(params.get(name, "")).strip()

            if not input_path:
                if required:
                    raise ValueError(f"缺少必需输入: {name}")
                continue

            if input_path.startswith("/"):
                data_id = registry.register_input(
                    file_path=input_path,
                    sample_id=sample_id,
                    data_type=str(inp.get("type", "unknown")),
                    tier="intermediate",
                    metadata={"source": "remote_upstream", "input_name": name},
                )
                input_data_ids.append(data_id)
                continue

            data_id = importer.import_file(
                local_path=input_path,
                sample_id=sample_id,
                data_type=str(inp.get("type", "unknown")),
                project_remote_base=pm.current_project.remote_base,
            )
            input_data_ids.append(data_id)

        return input_data_ids

    @staticmethod
    def extract_run_params(descriptor: dict, params: dict) -> dict:
        run_params: dict = {}
        for p in descriptor.get("parameters", []):
            name = str(p.get("name", ""))
            if name and name in params:
                run_params[name] = params[name]
        return run_params

    @staticmethod
    def extract_database_paths(descriptor: dict, params: dict) -> dict:
        db_paths: dict = {}
        for decl in descriptor.get("databases", []):
            var_name = str(decl.get("param_name", "")).strip()
            if not var_name:
                continue

            value = str(params.get(var_name, "")).strip()
            if value:
                db_paths[var_name] = value

        return db_paths

    @staticmethod
    def validate_required_databases(tool_id: str, descriptor: dict, database_paths: dict) -> None:
        for decl in descriptor.get("databases", []):
            if not isinstance(decl, dict):
                raise ValueError(f"工具 {tool_id} 的数据库声明格式错误: {decl!r}")
            if not bool(decl.get("required", False)):
                continue
            db_id = str(decl.get("id", "")).strip()
            var_name = str(decl.get("param_name", "")).strip()
            if not db_id:
                raise ValueError(f"工具 {tool_id} 的数据库声明缺少 id")
            if not var_name:
                raise ValueError(f"工具 {tool_id} 的数据库声明缺少 param_name: db_id={db_id}")
            if not str(database_paths.get(var_name, "")).strip():
                raise ValueError(f"工具 {tool_id} 缺少必需数据库: db_id={db_id}, param={var_name}")

    def get_execution_history(self) -> list[dict]:
        pm = self._get_project_manager()
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
        pm = self._get_project_manager()
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

    def get_integrated_workbench_config(self) -> dict:
        config = self.base_integrated_workbench_config()
        features = config.setdefault("features", [])
        views = config.setdefault("views", {})
        self._ensure_detection_workbench_entries(features, views)

        for feature in features:
            if feature.get("id") == "primer_design":
                feature["name"] = "病原体引物设计"
                feature["description"] = "上传病原体基因组，自动筛选保守特异靶点并设计引物对，输出每病原体的推荐引物。"

        primer_view = views.get("primer_design")
        if isinstance(primer_view, dict):
            primer_view["title"] = "病原体引物设计"
            primer_view["description"] = "上传病原体基因组序列，系统自动完成保守靶点筛选、特异性过滤和候选引物设计，最终输出每病原体的推荐引物对。"

        if not any(feature.get("id") == "multiplex_primer_panel" for feature in features):
            features.insert(
                1,
                {
                    "id": "multiplex_primer_panel",
                    "name": "多重引物池设计",
                    "badge": "",
                    "description": "一体化完成候选引物生成与多重引物池优化，自动消解交叉二聚体冲突并输出池结果与合成订单。",
                    "status": "active",
                },
            )

        views.setdefault(
            "multiplex_primer_panel",
            {
                "tool_ids": ["multiplex_primer_panel"],
                "title": "多重引物池设计",
                "description": "用途：用于靶向病原体多重 PCR 方案设计，输出可直接用于实验与交付的池化结果和合成清单。\n实现：流程内自动执行候选引物合并、迭代优化、交叉二聚体评估、扩增子冲突检查、Tm/GC 一致性检查和覆盖验证。",
                "status": {
                    "state": "ready",
                    "label": "等待运行",
                    "detail": "系统按你的流程自动执行 16 个步骤（候选生成→池优化→冲突评估→最终报告），完成后可直接查看 multiplex_panel 与 synthesis_order。",
                },
                "parameters": [
                    {"label": "输入", "value": "病原体序列（流程内自动生成候选引物）", "description": "你只需提供病原体序列，系统会在流程内自动完成候选引物设计并进入多重池优化。"},
                    {"label": "约束", "value": "cross-dimer / Tm / amplicon length", "description": "联合约束引物间互作、退火温度一致性和扩增子长度范围。"},
                    {"label": "输出", "value": "multiplex_panel.txt / synthesis_order.txt", "description": "输出最终入池方案与可直接使用的合成订单。"},
                    {"label": "优化轮次", "value": "运行后生成", "description": "表示算法迭代优化的次数，用于消解冲突并满足约束；该值由实际任务日志统计。"},
                ],
                "summary": [
                    {"label": "入池病原体", "value": "0/0", "tone": "primary"},
                    {"label": "订单条目", "value": "0", "tone": "primary"},
                    {"label": "质量", "value": "-", "tone": "accent"},
                    {"label": "优化轮次", "value": "ready", "tone": "accent"},
                ],
                "columns": self._build_multiplex_columns([]),
                "rows": [],
                "artifacts": [
                    "multiplex_panel.txt",
                    "synthesis_order.txt",
                    "pool_cross_dimer.txt",
                    "optimization_log.txt",
                ],
            },
        )

        live_primer_view = self.get_live_primer_design_view()
        if live_primer_view is not None:
            views["primer_design"] = live_primer_view

        live_multiplex_view = self.get_live_multiplex_primer_panel_view()
        if live_multiplex_view is not None:
            views["multiplex_primer_panel"] = live_multiplex_view

        for workflow_id in DETECTION_WORKFLOW_ORDER:
            live_detection_view = self._get_live_detection_workflow_view(workflow_id)
            if live_detection_view is not None:
                views[workflow_id] = live_detection_view

        # 靶向测序分析 — 自动加载最新完成的 centrifuge/kraken2 结果
        live_targeted_view = self._get_live_targeted_seq_view()
        if live_targeted_view is not None:
            views["targeted_sequencing"] = live_targeted_view

        return config

    def get_remote_primer_results(self, remote_result_dir: str) -> dict:
        view = self.build_primer_view_from_result_dir(remote_result_dir)
        if view is None:
            return {
                "status": "error",
                "message": "未能从该远程目录读取 primer_result_final_2.txt，请检查 SSH 连接和目录路径。",
            }
        return {"status": "ok", "view": view}

    def get_results_for_execution(self, execution_id: str) -> dict:
        normalized_id = str(execution_id or "").strip()
        if not normalized_id:
            return {"status": "error", "message": "execution_id 不能为空"}

        try:
            execution_row = self._get_execution_result_row(normalized_id)
            if execution_row is None:
                return {"status": "error", "message": "未找到对应任务记录"}
            if execution_row["status"] != "completed":
                return {"status": "error", "message": "该任务尚未完成，当前只能查看状态"}
            view = self._build_result_view_for_execution(normalized_id, execution_row)
            return {"status": "ok", "view": view}
        except Exception as exc:
            logger.exception("Failed to build results for execution %s", normalized_id)
            return {"status": "error", "message": str(exc)}

    def _require_tool_descriptor(self, tool_id: str) -> dict:
        descriptor = self.get_tool_descriptor(tool_id)
        if not descriptor:
            raise RuntimeError(f"工具描述符不存在: {tool_id}")
        return descriptor

    @staticmethod
    def _parse_execution_parameters_strict(raw: Any, execution_id: str) -> dict[str, Any]:
        if raw in ("", None):
            return {}
        if isinstance(raw, dict):
            return dict(raw)
        try:
            data = json.loads(str(raw))
        except Exception as exc:
            raise RuntimeError(f"执行参数 JSON 解析失败: execution_id={execution_id}") from exc
        if not isinstance(data, dict):
            raise RuntimeError(f"执行参数必须是对象: execution_id={execution_id}")
        return data

    def _build_parameter_items(self, raw_parameters: Any, execution_id: str) -> list[dict[str, str]]:
        params = self._parse_execution_parameters_strict(raw_parameters, execution_id)
        return [
            {"label": str(key), "value": str(value)}
            for key, value in params.items()
            if value not in ("", None)
        ]

    def _build_execution_result_context(
        self,
        execution_row: Any,
        artifacts: list[dict] | None = None,
    ) -> dict[str, Any]:
        execution_id = str(execution_row["execution_id"] or "")
        tool_id = str(execution_row["tool_id"] or "")
        artifacts = self._normalize_artifacts(artifacts or self.list_local_execution_artifacts(execution_id))
        if not artifacts:
            raise RuntimeError(
                f"执行结果缺少工件清单: tool={tool_id}, execution_id={execution_id}"
            )
        manifest = self._load_manifest(execution_id) or {}
        return {
            "execution_id": execution_id,
            "tool_id": tool_id,
            "sample_id": str(execution_row["sample_id"] or ""),
            "sample_name": str(execution_row["sample_name"] or execution_row["sample_id"] or ""),
            "updated_at": self._format_execution_time(execution_row["completed_at"] or execution_row["created_at"]),
            "tool_version": str(execution_row["tool_version"] or ""),
            "artifacts": artifacts,
            "remote_result_dir": str(manifest.get("output_dir") or "").strip(),
            "local_result_dir": self._local_result_dir_for_execution(execution_id, artifacts),
            "parameters": self._parameter_items_from_dict(
                self._parse_execution_parameters_strict(execution_row["parameters"], execution_id)
            ),
        }

    @staticmethod
    def _normalize_result_view_kwargs(context: dict[str, Any]) -> dict[str, Any]:
        return {
            "sample_name": context["sample_name"],
            "execution_id": context["execution_id"],
            "updated_at": context["updated_at"],
            "tool_version": context["tool_version"],
            "remote_result_dir": context["remote_result_dir"],
            "local_result_dir": context["local_result_dir"],
        }

    @staticmethod
    def _descriptor_data_source_name(view_config: dict[str, Any], sample_id: str) -> str:
        template = str(view_config.get("data_source") or "").strip()
        if not template:
            return ""
        return template.replace("{sample_id}", sample_id)

    def _find_result_artifact(
        self,
        artifacts: list[dict],
        descriptor: dict,
        sample_id: str,
        *,
        preferred_view_types: tuple[str, ...] = ("table",),
        allowed_suffixes: tuple[str, ...] = (),
    ) -> dict | None:
        result_views = list(descriptor.get("result_views") or [])
        for view_config in result_views:
            view_type = str(view_config.get("type") or "").strip()
            if preferred_view_types and view_type not in preferred_view_types:
                continue
            artifact_name = self._descriptor_data_source_name(view_config, sample_id)
            artifact = self._artifact_by_name(artifacts, artifact_name)
            if artifact is not None:
                return artifact
        for artifact in artifacts:
            name = str(artifact.get("name") or "").lower()
            if allowed_suffixes and not any(name.endswith(suffix) for suffix in allowed_suffixes):
                continue
            if artifact.get("available") and artifact.get("local_path"):
                return artifact
        return None

    @staticmethod
    def _parse_float(value: Any) -> float | None:
        try:
            text = str(value).strip().rstrip("%")
            if not text:
                return None
            number = float(text)
            if 0 <= number <= 1 and "fraction" in str(value):
                return number * 100
            return number
        except Exception:
            return None

    @staticmethod
    def _row_lookup(row: dict[str, Any]) -> dict[str, Any]:
        return {str(key).lower(): value for key, value in row.items()}

    def _summarize_metric_rows(
        self,
        rows: list[dict[str, Any]],
        preferred_keys: list[str] | list[tuple[str, str, str]],
        metrics: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        if metrics:
            metric_candidates = [(str(key), str(key), "info") for key in metrics.keys()]
            summary = summarize_table_row(metrics, metric_candidates[:4])
            if summary:
                return summary
        if not rows:
            return []
        first_row = self._row_lookup(rows[0])
        summary = []
        if preferred_keys and isinstance(preferred_keys[0], tuple):
            return summarize_table_row(first_row, list(preferred_keys))[:4]
        for key in preferred_keys:
            key_text = str(key).lower()
            if key_text not in first_row:
                continue
            label = str(key).upper() if key_text == "n50" else str(key).replace("_", " ").title()
            summary.append({"label": label, "value": str(first_row[key_text]), "tone": "info"})
        return summary[:4]

    def _build_generic_summary(
        self,
        archetype: str,
        rows: list[dict[str, Any]],
        artifacts: list[dict],
        *,
        tool_id: str = "",
    ) -> list[dict[str, Any]]:
        available_count = len([item for item in artifacts if item.get("available")])
        if archetype == "taxonomy_profile":
            first_row = rows[0] if rows else {}
            lookup = self._row_lookup(first_row)
            top_name = (
                lookup.get("name")
                or lookup.get("clade_name")
                or lookup.get("taxonomy")
                or lookup.get("classification")
                or "—"
            )
            top_value = (
                lookup.get("percentage")
                or lookup.get("fraction_total_reads")
                or lookup.get("relative_abundance")
                or lookup.get("abundance")
                or "—"
            )
            return [
                {"label": "分类记录", "value": str(len(rows)), "tone": "primary"},
                {"label": "Top 分类", "value": str(top_name), "tone": "accent"},
                {"label": "Top 丰度", "value": str(top_value), "tone": "info"},
                {"label": "结果文件", "value": str(available_count), "tone": "success"},
            ]

        if archetype == "quality_assessment":
            summary = self._summarize_metric_rows(rows, _QUALITY_SUMMARY_KEYS.get(tool_id, []))
            if summary:
                summary.append({"label": "结果文件", "value": str(available_count), "tone": "info"})
                return summary[:4]
            return [
                {"label": "质量记录", "value": str(len(rows)), "tone": "primary"},
                {"label": "结果文件", "value": str(available_count), "tone": "info"},
            ]

        if archetype == "qc_report":
            first_row = rows[0] if rows else {}
            lookup = self._row_lookup(first_row)
            preferred_keys = ("total_reads", "host_reads", "non_host_reads", "host_fraction")
            summary = []
            labels = {
                "total_reads": "总 Reads",
                "host_reads": "宿主 Reads",
                "non_host_reads": "非宿主 Reads",
                "host_fraction": "宿主占比",
            }
            for key in preferred_keys:
                if key in lookup:
                    summary.append({"label": labels[key], "value": str(lookup[key]), "tone": "info"})
            if summary:
                return summary[:4]
            return [
                {"label": "结果文件", "value": str(available_count), "tone": "primary"},
                {"label": "统计记录", "value": str(len(rows)), "tone": "info"},
            ]

        if archetype == "annotation_table":
            return [
                {"label": "结果条目", "value": str(len(rows)), "tone": "primary"},
                {"label": "结果文件", "value": str(available_count), "tone": "info"},
            ]

        return [
            {"label": "结果文件", "value": str(available_count), "tone": "primary"},
            {"label": "结果记录", "value": str(len(rows)), "tone": "info"},
        ]

    def _build_taxonomy_charts(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not rows:
            return []
        name_candidates = ("name", "clade_name", "taxonomy", "classification")
        value_candidates = ("percentage", "fraction_total_reads", "relative_abundance", "abundance", "reads", "new_est_reads")
        first_lookup = self._row_lookup(rows[0])
        name_key = next((key for key in name_candidates if key in first_lookup), "")
        value_key = next((key for key in value_candidates if key in first_lookup), "")
        if not name_key or not value_key:
            return []
        chart_rows = []
        for row in rows[:20]:
            lookup = self._row_lookup(row)
            numeric = self._parse_float(lookup.get(value_key))
            if numeric is None:
                continue
            if "fraction" in value_key and numeric <= 1:
                numeric *= 100
            chart_rows.append(
                {
                    "name": str(lookup.get(name_key) or "—"),
                    "value": round(numeric, 4),
                }
            )
        if not chart_rows:
            return []
        return [{"type": "abundance_bar", "title": "分类丰度", "data": chart_rows}]

    def _build_descriptor_driven_view_for_execution(
        self,
        *,
        execution_id: str,
        execution_row: Any,
        feature_id: str,
        tool_id: str,
        archetype: str,
    ) -> dict:
        descriptor = self._require_tool_descriptor(feature_id if feature_id in _WORKFLOW_PRODUCT_TOOL_IDS else tool_id)
        context = self._build_execution_result_context(execution_row)
        artifacts = context["artifacts"]
        sample_id = context["sample_id"]
        preferred_types = ("table",)
        if archetype == "qc_report":
            preferred_types = ("table",)
        elif archetype == "taxonomy_profile":
            preferred_types = ("table", "stacked_bar")
        table_artifact = self._find_result_artifact(
            artifacts,
            descriptor,
            sample_id,
            preferred_view_types=preferred_types,
            allowed_suffixes=(".tsv", ".csv", ".txt", ".json"),
        )
        table_payload = {"columns": [], "rows": []}
        table_title = str(descriptor.get("name") or tool_id)
        if table_artifact is not None:
            local_path = str(table_artifact.get("local_path") or "").strip()
            if local_path:
                table_payload = parse_generic_result_table(Path(local_path))
            for view_config in descriptor.get("result_views") or []:
                if self._descriptor_data_source_name(view_config, sample_id) == str(table_artifact.get("name") or ""):
                    table_title = str(view_config.get("title") or table_title)
                    break
        charts = self._build_taxonomy_charts(table_payload["rows"]) if archetype == "taxonomy_profile" else []
        return build_single_tool_view(
            feature_id=feature_id,
            tool_id=tool_id,
            archetype=archetype,
            tool_ids=[tool_id],
            title=str(descriptor.get("name") or tool_id),
            description=str(descriptor.get("description") or f"{tool_id} 结果"),
            status={
                "state": "completed",
                "label": "结果已就绪",
                "detail": "当前结果已同步到本地，可查看结构化摘要与结果文件。",
            },
            summary=self._build_generic_summary(archetype, table_payload["rows"], artifacts, tool_id=tool_id),
            charts=charts,
            table={
                "title": table_title,
                "subtitle": f"当前结果来自 {str(table_artifact.get('name') or '结构化产物')}" if table_artifact else "未发现结构化结果表，已保留结果文件。",
                "columns": table_payload["columns"],
                "rows": table_payload["rows"],
            },
            artifacts=artifacts,
            parameters=context["parameters"],
            sample_name=context["sample_name"],
            execution_id=execution_id,
            updated_at=context["updated_at"],
            tool_version=context["tool_version"],
            remote_result_dir=context["remote_result_dir"],
            local_result_dir=context["local_result_dir"],
        )

    def get_execution_remote_status(self, execution_id: str) -> dict:
        pm = self._get_project_manager()
        if pm is None or pm.current_project is None:
            return {"status": "error", "message": "未打开项目"}
        ssh = self._get_ssh_service()
        return self._execution_status_service.get_execution_remote_status(execution_id, pm, ssh)

    def _get_execution_result_row(self, execution_id: str):
        normalized_id = str(execution_id or "").strip()
        if not normalized_id:
            return None
        pm = self._get_project_manager()
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

    @staticmethod
    def _format_execution_time(timestamp: Any) -> str:
        if timestamp in (None, ""):
            return ""
        try:
            return datetime.datetime.fromtimestamp(float(timestamp)).strftime("%Y-%m-%d %H:%M")
        except Exception:
            return ""

    def _get_cached_remote_status(self, execution_id: str, local_status: str) -> dict[str, Any] | None:
        return self._execution_status_service._get_cached_remote_status(execution_id, local_status)

    def _set_cached_remote_status(self, execution_id: str, data: dict[str, Any]) -> None:
        self._execution_status_service._set_cached_remote_status(execution_id, data)

    @staticmethod
    def _parse_remote_status_block(output: str) -> dict[str, str]:
        return ExecutionStatusService.parse_remote_status_block(output)

    def _ensure_detection_workbench_entries(self, features: list[dict], views: dict[str, dict]) -> None:
        placeholder_index = next(
            (idx for idx, feature in enumerate(features) if feature.get("id") == "target_screening"),
            len(features),
        )
        for workflow_id in DETECTION_WORKFLOW_ORDER:
            spec = DETECTION_WORKFLOW_SPECS[workflow_id]
            if not any(feature.get("id") == workflow_id for feature in features):
                features.insert(placeholder_index, copy.deepcopy(spec["feature"]))
                placeholder_index += 1
            views.setdefault(workflow_id, copy.deepcopy(spec["view"]))
            if isinstance(views.get(workflow_id), dict):
                views[workflow_id].setdefault("feature_id", workflow_id)

    def _resolve_detection_workflow_id_for_execution(self, execution_id: str) -> str | None:
        normalized_id = str(execution_id or "").strip()
        if not normalized_id:
            return None

        pm = self._get_project_manager()
        if pm is None or pm.current_project is None:
            return None

        try:
            row = pm.db.execute(
                "SELECT tool_id, parameters FROM executions WHERE execution_id = ? LIMIT 1",
                (normalized_id,),
            ).fetchone()
        except Exception:
            return None
        if not row:
            return None

        tool_id = str(row["tool_id"] or "")
        if tool_id in DETECTION_WORKFLOW_ORDER:
            return tool_id

        if tool_id not in ("centrifuge", "kraken2"):
            return None

        try:
            params = json.loads(row["parameters"] or "{}")
        except Exception:
            params = {}
        legacy_workflow = DETECTION_WORKFLOW_SPECS["unknown_sample_detection"].get("legacy_workflow")
        if params.get("workflow") == legacy_workflow:
            return "unknown_sample_detection"
        return None

    def _build_detection_workflow_view_for_execution(self, workflow_id: str, execution_id: str) -> dict | None:
        spec = DETECTION_WORKFLOW_SPECS.get(workflow_id)
        if spec is None:
            return None
        row = self._get_execution_result_row(execution_id)
        if row is None:
            return None
        try:
            view = self._build_result_view_for_execution(execution_id, row)
            if str(view.get("feature_id") or "") != workflow_id:
                raise RuntimeError(
                    f"workflow 结果路由不匹配: expected={workflow_id}, actual={view.get('feature_id')}, execution_id={execution_id}"
                )
            return view
        except Exception:
            logger.exception("Failed to build detection workflow result view: %s / %s", workflow_id, execution_id)
            return None

    def _get_live_detection_workflow_view(self, workflow_id: str) -> dict | None:
        pm = self._get_project_manager()
        if pm is None or pm.current_project is None:
            return None

        spec = DETECTION_WORKFLOW_SPECS.get(workflow_id)
        if spec is None:
            return None

        target_eid = None
        if workflow_id == "unknown_sample_detection":
            try:
                rows = pm.db.execute(
                    "SELECT execution_id, tool_id, parameters FROM executions "
                    "WHERE tool_id IN ('unknown_sample_detection', 'centrifuge', 'kraken2') "
                    "AND status = 'completed' "
                    "ORDER BY rowid DESC",
                ).fetchall()
            except Exception:
                rows = []

            for row in rows or []:
                if row["tool_id"] == workflow_id:
                    target_eid = row["execution_id"]
                    break

            if target_eid is None:
                legacy_workflow = spec.get("legacy_workflow")
                for row in rows or []:
                    try:
                        params = json.loads(row["parameters"] or "{}")
                    except Exception:
                        continue
                    if params.get("workflow") == legacy_workflow:
                        target_eid = row["execution_id"]
                        break
        else:
            try:
                row = pm.db.execute(
                    "SELECT execution_id FROM executions WHERE tool_id = ? AND status = 'completed' ORDER BY rowid DESC LIMIT 1",
                    (workflow_id,),
                ).fetchone()
            except Exception:
                row = None
            if row:
                target_eid = row["execution_id"]

        if target_eid is None:
            return None
        return self._build_detection_workflow_view_for_execution(workflow_id, target_eid)

    def _get_live_unknown_sample_detection_view(self) -> dict | None:
        return self._get_live_detection_workflow_view("unknown_sample_detection")

    def _get_live_targeted_seq_view(self) -> dict | None:
        """查找最新的 centrifuge/kraken2 已完成执行，构建靶向测序 view。

        排除标记为 unknown_detection workflow 的 execution，
        只加载靶向测序（无 workflow 标记 或 workflow=targeted）的结果。
        """
        pm = self._get_project_manager()
        if pm is None or pm.current_project is None:
            return None
        try:
            rows = pm.db.execute(
                "SELECT execution_id, parameters FROM executions "
                "WHERE tool_id IN ('centrifuge', 'kraken2') AND status = 'completed' "
                "ORDER BY rowid DESC",
            ).fetchall()
        except Exception:
            return None

        import json as _json
        target_eid = None
        for r in (rows or []):
            try:
                params = _json.loads(r["parameters"] or "{}")
            except Exception:
                params = {}
            wf = params.get("workflow", "")
            if wf != "unknown_detection":
                target_eid = r["execution_id"]
                break

        if target_eid is None:
            return None
        try:
            row = self._get_execution_result_row(target_eid)
            if row is None:
                return None
            return self._build_result_view_for_execution(target_eid, row)
        except Exception:
            logger.exception("Failed to build live targeted sequencing view: %s", target_eid)
            return None

    def _build_result_view_for_execution(self, execution_id: str, execution_row: Any | None = None) -> dict:
        row = execution_row or self._get_execution_result_row(execution_id)
        if row is None:
            raise RuntimeError(f"未找到执行记录: {execution_id}")

        tool_id = str(row["tool_id"] or "").strip()
        feature_id = self._resolve_detection_workflow_id_for_execution(execution_id) or tool_id
        archetype = self._resolve_result_archetype(feature_id if feature_id in _TOOL_ARCHETYPES else tool_id)
        if archetype == "qc_report":
            return self._build_qc_report_view_for_execution(execution_id, row)
        if archetype == "taxonomy_profile":
            return self._build_taxonomy_profile_view_for_execution(execution_id, row)
        if archetype == "html_report":
            return self._build_html_report_view_for_execution(execution_id, row)
        if archetype == "annotation_table":
            return self._build_annotation_table_view_for_execution(execution_id, row)
        if archetype == "quality_assessment":
            return self._build_quality_assessment_view_for_execution(execution_id, row)
        if archetype == "workflow_product":
            return self._build_workflow_product_view_for_execution(
                execution_id=execution_id,
                execution_row=row,
                feature_id=feature_id,
            )
        if archetype == "artifact_collection":
            return self._build_artifact_collection_view_for_execution(execution_id, row)
        raise RuntimeError(
            f"未支持的结果 archetype: tool={tool_id}, feature_id={feature_id}, archetype={archetype}, execution_id={execution_id}"
        )

    def _build_artifact_backed_view_for_execution(
        self,
        execution_row: Any,
        *,
        archetype: str,
        description: str,
        status_detail: str,
    ) -> dict:
        tool_id = str(execution_row["tool_id"] or "")
        descriptor = self._require_tool_descriptor(tool_id)
        ctx = self._build_execution_result_context(execution_row)
        artifacts = ctx["artifacts"]
        return build_artifact_result_view(
            feature_id=tool_id,
            tool_id=tool_id,
            archetype=archetype,
            tool_ids=[tool_id],
            title=str(descriptor.get("name") or tool_id),
            description=description,
            status={
                "state": "completed",
                "label": "结果已就绪",
                "detail": status_detail,
            },
            artifacts=artifacts,
            parameters=ctx["parameters"],
            sample_name=ctx["sample_name"],
            execution_id=ctx["execution_id"],
            updated_at=ctx["updated_at"],
            tool_version=ctx["tool_version"],
            remote_result_dir=ctx["remote_result_dir"],
            local_result_dir=ctx["local_result_dir"],
        )

    def _build_artifact_collection_view_for_execution(self, execution_id: str, execution_row: Any) -> dict:
        tool_id = str(execution_row["tool_id"] or "")
        descriptor = self._require_tool_descriptor(tool_id)
        return self._build_artifact_backed_view_for_execution(
            execution_row,
            archetype="artifact_collection",
            description=str(descriptor.get("description") or f"{tool_id} 结果"),
            status_detail="该工具以文件集结果为主，以下展示已同步产物。",
        )

    def _build_generic_table_view_for_execution(
        self,
        execution_row: Any,
        *,
        archetype: str,
        summary_keys: list[str] | list[tuple[str, str, str]] | None = None,
        row_count_label: str = "结果条目",
        table_subtitle: str = "",
    ) -> dict:
        tool_id = str(execution_row["tool_id"] or "")
        execution_id = str(execution_row["execution_id"] or "")
        descriptor = self._require_tool_descriptor(tool_id)
        artifacts = self._normalize_artifacts(self.list_local_execution_artifacts(execution_id))
        if not artifacts:
            raise RuntimeError(f"执行结果缺少工件清单: tool={tool_id}, execution_id={execution_id}")
        ctx = self._build_execution_result_context(execution_row, artifacts)

        artifact = self._artifact_from_result_views(
            descriptor,
            artifacts,
            sample_id=ctx["sample_id"],
            preferred_types=("table", "html", "krona"),
        )
        if artifact is None:
            artifact = self._first_available_artifact_with_suffix(artifacts, (".tsv", ".csv", ".txt", ".json"))
        if artifact is None:
            return self._build_artifact_collection_view_for_execution(execution_id, execution_row)

        local_path = str(artifact.get("local_path") or "").strip()
        if not local_path:
            raise RuntimeError(f"结果文件缺少本地路径: tool={tool_id}, execution_id={execution_id}, name={artifact.get('name')}")

        columns, rows, metrics = self._parse_table_file(Path(local_path))
        summary = self._summarize_metric_rows(rows, preferred_keys=summary_keys or [], metrics=metrics) if summary_keys else []
        if not summary:
            summary = self._summarize_row_count(rows, label=row_count_label)
        return build_single_tool_view(
            feature_id=tool_id,
            tool_id=tool_id,
            archetype=archetype,
            tool_ids=[tool_id],
            title=str(descriptor.get("name") or tool_id),
            description=str(descriptor.get("description") or f"{tool_id} 结果"),
            status={"state": "completed", "label": "结果已就绪", "detail": "已加载结构化结果表。"},
            summary=summary,
            columns=columns,
            rows=rows,
            artifacts=artifacts,
            parameters=ctx["parameters"],
            table_title=str((descriptor.get("result_views") or [{}])[0].get("title") or "分析结果"),
            table_subtitle=table_subtitle or f"已从 {artifact.get('name')} 构建结果表。",
            sample_name=ctx["sample_name"],
            execution_id=ctx["execution_id"],
            updated_at=ctx["updated_at"],
            tool_version=ctx["tool_version"],
            remote_result_dir=ctx["remote_result_dir"],
            local_result_dir=ctx["local_result_dir"],
        )

    def _build_qc_report_view_for_execution(self, execution_id: str, execution_row: Any) -> dict:
        tool_id = str(execution_row["tool_id"] or "")
        if tool_id == "fastp":
            view = self._build_fastp_view_for_execution(execution_id)
            if view is None:
                raise RuntimeError(f"fastp 结果不可用: execution_id={execution_id}")
            return view
        return self._build_generic_table_view_for_execution(
            execution_row,
            archetype="qc_report",
            summary_keys=["total_reads", "host_reads", "non_host_reads", "host_fraction"],
            row_count_label="QC 指标",
            table_subtitle="已从结果文件构建 QC / 去宿主结果表。",
        )

    def _build_html_report_view_for_execution(self, execution_id: str, execution_row: Any) -> dict:
        tool_id = str(execution_row["tool_id"] or "")
        descriptor = self._require_tool_descriptor(tool_id)
        ctx = self._build_execution_result_context(execution_row)
        html_artifact = self._find_result_artifact(
            ctx["artifacts"],
            descriptor,
            ctx["sample_id"],
            preferred_view_types=("html", "krona"),
            allowed_suffixes=(".html",),
        )
        if html_artifact is None:
            raise RuntimeError(f"HTML 结果缺失: tool={tool_id}, execution_id={execution_id}")
        return self._build_artifact_backed_view_for_execution(
            execution_row,
            archetype="html_report",
            description=str(descriptor.get("description") or f"{tool_id} HTML 报告"),
            status_detail="已同步主 HTML 报告，可在页面预览或在系统中打开。",
        )

    def _build_annotation_table_view_for_execution(self, execution_id: str, execution_row: Any) -> dict:
        tool_id = str(execution_row["tool_id"] or "")
        if tool_id == "prokka":
            view = self._build_prokka_view_for_execution(execution_id, execution_row)
            if view is None:
                raise RuntimeError(f"Prokka 结果不可用: execution_id={execution_id}")
            return view
        return self._build_generic_table_view_for_execution(
            execution_row,
            archetype="annotation_table",
            summary_keys=["name", "gene", "product", "contig", "query_id"],
            row_count_label="注释条目",
            table_subtitle="已从结果文件构建注释 / 命中结果表。",
        )

    def _build_quality_assessment_view_for_execution(self, execution_id: str, execution_row: Any) -> dict:
        tool_id = str(execution_row["tool_id"] or "")
        return self._build_generic_table_view_for_execution(
            execution_row,
            archetype="quality_assessment",
            summary_keys=_QUALITY_SUMMARY_KEYS.get(tool_id, []),
            row_count_label="质量指标",
            table_subtitle="已从质量评估文件构建结果表。",
        )

    def _build_workflow_product_view_for_execution(
        self,
        execution_id: str,
        execution_row: Any,
        *,
        feature_id: str | None = None,
    ) -> dict:
        resolved_feature_id = feature_id or self._resolve_detection_workflow_id_for_execution(execution_id) or str(execution_row["tool_id"] or "")
        if resolved_feature_id == "primer_design":
            return self._build_primer_workflow_view_for_execution(execution_id)
        if resolved_feature_id == "multiplex_primer_panel":
            return self._build_multiplex_workflow_view_for_execution(execution_id)
        if resolved_feature_id in DETECTION_WORKFLOW_ORDER:
            return self._build_detection_workflow_result_view(execution_id, execution_row, feature_id=resolved_feature_id)
        raise RuntimeError(
            f"未支持的 workflow_product: tool={execution_row['tool_id']}, feature_id={resolved_feature_id}, execution_id={execution_id}"
        )

    def _build_single_section_workflow_view(
        self,
        execution_id: str,
        *,
        feature_id: str,
        source_view: dict[str, Any],
        section_id: str,
    ) -> dict:
        row = self._get_execution_result_row(execution_id)
        if row is None:
            raise RuntimeError(f"未找到执行记录: {execution_id}")
        descriptor = self._require_tool_descriptor(feature_id)
        context = self._build_execution_result_context(row)
        normalize_kwargs = self._normalize_result_view_kwargs(context)
        section_view = normalize_result_view(
            source_view,
            feature_id=feature_id,
            tool_id=feature_id,
            archetype="annotation_table",
            **normalize_kwargs,
        )
        return normalize_result_view(
            source_view,
            feature_id=feature_id,
            tool_id=feature_id,
            archetype="workflow_product",
            title=str(descriptor.get("name") or feature_id),
            description=str(descriptor.get("description") or f"{feature_id} 工作流结果"),
            sections=[
                section_from_view(
                    section_view,
                    section_id=section_id,
                    title="产品结果",
                    archetype="annotation_table",
                )
            ],
            **normalize_kwargs,
        )

    def _build_primer_workflow_view_for_execution(self, execution_id: str) -> dict:
        primer_view = self.get_primer_view_for_execution(execution_id)
        if primer_view is None:
            raise RuntimeError(f"引物设计结果不可用: execution_id={execution_id}")
        return self._build_single_section_workflow_view(
            execution_id,
            feature_id="primer_design",
            source_view=primer_view,
            section_id="primer_result",
        )

    def _build_multiplex_workflow_view_for_execution(self, execution_id: str) -> dict:
        multiplex_view = self.get_multiplex_view_for_execution(execution_id)
        if multiplex_view is None:
            raise RuntimeError(f"多重引物池结果不可用: execution_id={execution_id}")
        return self._build_single_section_workflow_view(
            execution_id,
            feature_id="multiplex_primer_panel",
            source_view=multiplex_view,
            section_id="multiplex_result",
        )

    def _build_prokka_view_for_execution(self, execution_id: str, execution_row: Any | None = None) -> dict | None:
        row = execution_row or self._get_execution_result_row(execution_id)
        if row is None:
            return None
        artifacts = self._normalize_artifacts(self.list_local_execution_artifacts(str(row["execution_id"] or "")))
        if not artifacts:
            raise RuntimeError(f"Prokka 执行结果缺少工件清单: {execution_id}")

        sample_id = str(row["sample_id"] or "")
        stats_name = f"{sample_id}.prokka.txt"
        stats_text = self._read_local_artifact_text(artifacts, stats_name)
        if not stats_text:
            raise RuntimeError(f"Prokka 结果缺少主统计文件: {stats_name}")
        stats = parse_prokka_stats_text(stats_text)
        if not stats:
            raise RuntimeError(f"Prokka 统计文件无法解析: {stats_name}")

        descriptor = self._require_tool_descriptor("prokka")
        ctx = self._build_execution_result_context(row, artifacts)
        table_columns = [
            {"key": "organism", "label": "物种"},
            {"key": "contigs", "label": "Contigs"},
            {"key": "bases", "label": "Bases"},
            {"key": "cds", "label": "CDS"},
            {"key": "rrna", "label": "rRNA"},
            {"key": "trna", "label": "tRNA"},
        ]
        table_rows = [
            {
                "organism": stats.get("organism", sample_id or "-"),
                "contigs": stats.get("contigs", "-"),
                "bases": stats.get("bases", "-"),
                "cds": stats.get("cds", "-"),
                "rrna": stats.get("rrna", "-"),
                "trna": stats.get("trna", "-"),
            }
        ]
        return build_single_tool_view(
            feature_id="prokka",
            tool_id="prokka",
            archetype="annotation_table",
            tool_ids=["prokka"],
            title=str(descriptor.get("name") or "Prokka"),
            description=str(descriptor.get("description") or "快速原核基因组注释结果"),
            status={
                "state": "completed",
                "label": "结果已就绪",
                "detail": "注释统计和主要产物已同步到本地。",
            },
            summary=[
                {"label": "CDS", "value": stats.get("cds", "-"), "tone": "primary"},
                {"label": "rRNA", "value": stats.get("rrna", "-"), "tone": "info"},
                {"label": "tRNA", "value": stats.get("trna", "-"), "tone": "info"},
                {"label": "Contigs", "value": stats.get("contigs", "-"), "tone": "success"},
            ],
            columns=table_columns,
            rows=table_rows,
            artifacts=artifacts,
            parameters=ctx["parameters"],
            table_title="注释统计",
            table_subtitle="Prokka 输出的主要注释统计摘要。",
            sample_name=ctx["sample_name"],
            execution_id=ctx["execution_id"],
            updated_at=ctx["updated_at"],
            tool_version=ctx["tool_version"],
            remote_result_dir=ctx["remote_result_dir"],
            local_result_dir=ctx["local_result_dir"],
        )

    def _build_fastp_view_for_execution(self, execution_id: str) -> dict | None:
        """从 fastp 已完成的 execution 构建 QC 结果 view，展示在未知样品检测卡片中。"""
        normalized_id = str(execution_id or "").strip()
        if not normalized_id:
            return None

        pm = self._get_project_manager()
        if pm is None or pm.current_project is None:
            return None
        self.normalize_project_remote_base(pm)

        try:
            row = pm.db.execute(
                "SELECT tool_id, sample_id FROM executions WHERE execution_id = ? LIMIT 1",
                (normalized_id,),
            ).fetchone()
        except Exception:
            return None
        if not row or row["tool_id"] != "fastp":
            return None
        execution_row = self._get_execution_result_row(normalized_id)
        if execution_row is None:
            return None
        base_view = self._build_fastp_view_from_artifacts(
            execution_row,
            feature_id="fastp",
            include_context_parameters=False,
            table_title="质控过滤统计",
            table_subtitle="fastp 接头去除 + 低质量过滤详情。",
        )
        if base_view is None:
            return None
        original_reads = next((item["value"] for item in base_view["summary"] if item["label"] == "原始 Reads"), "—")
        passed_reads = next((item["value"] for item in base_view["summary"] if item["label"] == "通过 QC"), "—")
        base_view["parameters"] = [
            {"label": "输入", "value": f"双端 FASTQ ({original_reads} reads)"},
            {"label": "输出", "value": f"清洁 reads ({passed_reads})"},
            {"label": "工具", "value": "fastp"},
        ] + list(base_view.get("provenance", {}).get("parameters") or [])
        return base_view

    def _build_taxonomy_profile_view_for_execution(self, execution_id: str, execution_row: Any) -> dict:
        tool_id = str(execution_row["tool_id"] or "")
        if tool_id in ("kraken2", "centrifuge"):
            view = self._build_targeted_seq_view_for_execution(execution_id)
            if view is None:
                raise RuntimeError(f"分类结果不可用: tool={tool_id}, execution_id={execution_id}")
            return view
        return self._build_generic_table_view_for_execution(
            execution_row,
            archetype="taxonomy_profile",
            summary_keys=["name", "abundance", "relative_abundance", "fraction_total_reads"],
            row_count_label="分类条目",
            table_subtitle="已从分类结果文件构建结果表。",
        )

    def _resolve_targeted_seq_local_paths(
        self,
        sample_id: str,
        artifacts: list[dict[str, Any]],
    ) -> dict[str, Path | None]:
        suffixes = {
            "kreport": ".kreport",
            "coverage_depth": ".coverage_depth.tsv",
            "amplicon_performance": ".amplicon_performance.tsv",
            "fastp_json": ".fastp.json",
            "bracken": ".bracken.tsv",
            "bracken_kreport": ".bracken.kreport",
            "krona": ".krona.html",
        }
        return {
            key: self._local_artifact_path(artifacts, f"{sample_id}{suffix}")
            for key, suffix in suffixes.items()
        }

    @staticmethod
    def _build_targeted_seq_abundance_payload(
        chart_data: dict[str, Any],
        bracken_rows: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], str]:
        if bracken_rows:
            return (
                [
                    {
                        "name": row["name"],
                        "reads": int(row["reads"].replace(",", "")),
                        "value": float(row["percentage"].rstrip("%")),
                    }
                    for row in bracken_rows
                ],
                "Bracken 丰度 (Top 20)",
            )
        return list(chart_data.get("data", [])[:20]), "物种丰度 (Top 20)"

    @staticmethod
    def _build_targeted_seq_table_payload(
        chart_data: dict[str, Any],
        bracken_rows: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], list[dict[str, str]], str, str]:
        if bracken_rows:
            return (
                bracken_rows,
                [
                    {"key": "rank", "label": "序号"},
                    {"key": "name", "label": "物种名称"},
                    {"key": "reads", "label": "Bracken Reads"},
                    {"key": "percentage", "label": "相对丰度 (%)"},
                ],
                "Bracken 丰度结果",
                "优先展示 Bracken 重估后的物种丰度结果。",
            )
        rows = [
            {
                "rank": str(i),
                "name": item["name"],
                "reads": f'{item.get("reads", 0):,}',
                "percentage": f'{item["value"]:.2f}%',
            }
            for i, item in enumerate(chart_data.get("data", []), 1)
        ]
        return (
            rows,
            [
                {"key": "rank", "label": "序号"},
                {"key": "name", "label": "病原体名称"},
                {"key": "reads", "label": "Reads 数"},
                {"key": "percentage", "label": "占比 (%)"},
            ],
            "病原体物种组成",
            "基于 kreport 解析的物种组成，按丰度降序排列。",
        )

    @staticmethod
    def _build_targeted_seq_summary(summary_data: dict[str, Any]) -> list[dict[str, Any]]:
        total = summary_data["total_reads"]
        classified = summary_data["classified_reads"]
        pct = f"{classified / total * 100:.1f}%" if total > 0 else "0%"
        return [
            {"label": "总 Reads", "value": f"{total:,}", "tone": "primary"},
            {"label": "已分类", "value": f"{classified:,} ({pct})", "tone": "info"},
            {"label": "物种数", "value": str(summary_data["species_count"]), "tone": "success"},
            {"label": "Top 物种", "value": summary_data["top_species"], "tone": "accent"},
        ]

    @staticmethod
    def _append_chart_if_present(charts: list[dict[str, Any]], chart: dict[str, Any], *, title: str | None = None) -> None:
        if not chart.get("data"):
            return
        if title is not None:
            charts.append({"type": chart.get("type"), "title": title, "data": chart.get("data", [])})
            return
        charts.append(chart)

    def _build_targeted_seq_view_for_execution(self, execution_id: str) -> dict | None:
        """从 execution 记录构建 taxonomy profile 结果 view（纯本地 artifact 读路径）。"""
        from core.pipeline.chart_data_parser import ChartDataParser

        normalized_id = str(execution_id or "").strip()
        if not normalized_id:
            return None
        execution_row = self._get_execution_result_row(normalized_id)
        if execution_row is None:
            return None
        if str(execution_row["tool_id"] or "") not in TARGETED_RESULT_TOOL_IDS:
            return None
        artifacts = self._normalize_artifacts(self.list_local_execution_artifacts(normalized_id))
        if not artifacts:
            return None
        ctx = self._build_execution_result_context(execution_row, artifacts)
        tool_id = ctx["tool_id"]
        sample_id = ctx["sample_id"]
        remote_dir = ctx["remote_result_dir"]
        local_paths = self._resolve_targeted_seq_local_paths(sample_id, artifacts)
        local_kreport = local_paths["kreport"]
        if local_kreport is None:
            return None

        chart_data = ChartDataParser.parse_kreport(str(local_kreport))
        sunburst_chart = ChartDataParser.parse_kreport_tree(str(local_kreport))
        summary_data = ChartDataParser.parse_kreport_summary(str(local_kreport))
        bracken_rows = self._parse_bracken_abundance_rows(local_paths["bracken"])
        read_flow_chart = self._build_read_flow_chart(
            local_paths["fastp_json"],
            summary_data,
        )
        coverage_chart = {"type": "coverage_depth", "title": "Coverage Depth", "data": []}
        amplicon_chart = {"type": "amplicon_performance", "title": "Amplicon Performance", "data": []}
        if local_paths["coverage_depth"] is not None:
            coverage_chart = ChartDataParser.parse_coverage_depth(str(local_paths["coverage_depth"]))
        if local_paths["amplicon_performance"] is not None:
            amplicon_chart = ChartDataParser.parse_amplicon_performance(str(local_paths["amplicon_performance"]))
        abundance_bar_data, abundance_bar_title = self._build_targeted_seq_abundance_payload(chart_data, bracken_rows)

        charts = [
            {
                "type": "pie",
                "title": "病原体组成",
                "data": chart_data.get("data", []),
            },
            {
                "type": "abundance_bar",
                "title": abundance_bar_title,
                "data": abundance_bar_data,
            },
        ]
        if read_flow_chart is not None:
            charts.insert(0, read_flow_chart)
        self._append_chart_if_present(charts, sunburst_chart)
        self._append_chart_if_present(charts, coverage_chart, title="Coverage Depth")
        self._append_chart_if_present(charts, amplicon_chart, title="Amplicon Performance")
        rows, columns, table_title, table_subtitle = self._build_targeted_seq_table_payload(chart_data, bracken_rows)
        summary = self._build_targeted_seq_summary(summary_data)

        classifier_label = "Centrifuge" if tool_id in ("centrifuge", "unknown_sample_detection") else "Kraken2"
        return build_single_tool_view(
            feature_id=str(tool_id),
            tool_id=str(tool_id),
            archetype="taxonomy_profile",
            tool_ids=[tool_id],
            title=str(self._require_tool_descriptor(tool_id).get("name") or tool_id),
            description=f"{classifier_label} 分类结果",
            status={"state": "completed", "label": "分析完成", "detail": "已加载分类图表和结果表。"},
            summary=summary,
            charts=charts,
            columns=columns,
            rows=rows,
            artifacts=self._available_artifacts(artifacts),
            parameters=ctx["parameters"],
            table_title=table_title,
            table_subtitle=table_subtitle,
            sample_name=ctx["sample_name"],
            execution_id=ctx["execution_id"],
            updated_at=ctx["updated_at"],
            tool_version=ctx["tool_version"],
            remote_result_dir=remote_dir,
            local_result_dir=ctx["local_result_dir"],
        )

    def _build_fastp_view_from_artifacts(
        self,
        execution_row: Any,
        *,
        feature_id: str = "fastp",
        include_context_parameters: bool = True,
        table_title: str | None = None,
        table_subtitle: str | None = None,
    ) -> dict | None:
        execution_id = str(execution_row["execution_id"] or "")
        sample_id = str(execution_row["sample_id"] or "")
        artifacts = self._normalize_artifacts(self.list_local_execution_artifacts(execution_id))
        if not artifacts:
            return None

        json_name = f"{sample_id}.fastp.json"
        html_name = f"{sample_id}.fastp.html"
        local_json = self._local_artifact_path(artifacts, json_name)
        if local_json is None:
            return None

        ctx = self._build_execution_result_context(execution_row, artifacts)
        remote_dir = ctx["remote_result_dir"]
        html_artifact = self._artifact_by_name(artifacts, html_name)
        fastp_data = parse_fastp_json(local_json)
        summary = fastp_data.get("summary", {})
        before = summary.get("before_filtering", {})
        after = summary.get("after_filtering", {})
        filtering = fastp_data.get("filtering_result", {})

        total_before = int(before.get("total_reads", 0) or 0)
        total_after = int(after.get("total_reads", 0) or 0)
        q30_before = float(before.get("q30_rate", 0) or 0)
        q30_after = float(after.get("q30_rate", 0) or 0)
        gc_after = float(after.get("gc_content", 0) or 0)
        passed = int(filtering.get("passed_filter_reads", 0) or 0)
        low_quality = int(filtering.get("low_quality_reads", 0) or 0)
        too_short = int(filtering.get("too_short_reads", 0) or 0)
        too_many_n = int(filtering.get("too_many_N_reads", 0) or 0)

        pct_pass = f"{passed / total_before * 100:.1f}%" if total_before > 0 else "—"
        return build_single_tool_view(
            feature_id=feature_id,
            tool_id="fastp",
            archetype="qc_report",
            tool_ids=["fastp"],
            title="fastp 质控报告",
            description=f"样品 {sample_id} 的 QC 质控统计。",
            status={
                "state": "completed",
                "label": "QC 完成",
                "detail": f"通过率 {pct_pass}，Q30 {q30_after:.1%}",
            },
            summary=[
                {"label": "原始 Reads", "value": f"{total_before:,}", "tone": "primary"},
                {"label": "通过 QC", "value": f"{total_after:,} ({pct_pass})", "tone": "success"},
                {"label": "Q30 (过滤后)", "value": f"{q30_after:.2%}", "tone": "info"},
                {"label": "GC 含量", "value": f"{gc_after:.2%}", "tone": "info"},
            ],
            columns=[
                {"key": "metric", "label": "指标"},
                {"key": "before", "label": "过滤前"},
                {"key": "after", "label": "过滤后"},
            ],
            rows=[
                {"metric": "总 Reads", "before": f"{total_before:,}", "after": f"{total_after:,}"},
                {"metric": "Q30", "before": f"{q30_before:.2%}", "after": f"{q30_after:.2%}"},
                {"metric": "GC 含量", "before": f"{float(before.get('gc_content', 0) or 0):.2%}", "after": f"{gc_after:.2%}"},
                {"metric": "低质量 Reads", "before": "—", "after": f"{low_quality:,}"},
                {"metric": "过短 Reads", "before": "—", "after": f"{too_short:,}"},
                {"metric": "高 N Reads", "before": "—", "after": f"{too_many_n:,}"},
                {"metric": "通过率", "before": "—", "after": pct_pass},
            ],
            artifacts=[
                {
                    "name": json_name,
                    "remote_path": str((self._artifact_by_name(artifacts, json_name) or {}).get("remote_path") or f"{remote_dir}/{json_name}"),
                    "local_path": str(local_json),
                    "available": True,
                },
                {
                    "name": html_name,
                    "remote_path": str((html_artifact or {}).get("remote_path") or f"{remote_dir}/{html_name}"),
                    "local_path": str((html_artifact or {}).get("local_path") or ""),
                    "available": bool((html_artifact or {}).get("available")),
                },
            ],
            provenance={
                "execution_id": ctx["execution_id"],
                "parameters": list(ctx["parameters"]),
                "tool_version": ctx["tool_version"],
                "remote_result_dir": remote_dir,
                "local_result_dir": ctx["local_result_dir"],
            },
            parameters=list(ctx["parameters"]) if include_context_parameters else [],
            table_title=table_title or "分析结果",
            table_subtitle=table_subtitle or "",
            sample_name=ctx["sample_name"],
            execution_id=ctx["execution_id"],
            updated_at=ctx["updated_at"],
        )

    @staticmethod
    def _infer_total_reads_from_summary(summary: list[dict[str, Any]]) -> int:
        for item in summary:
            if "Reads" not in str(item.get("label") or ""):
                continue
            try:
                return int(str(item.get("value") or "0").replace(",", "").split("(")[0].strip())
            except ValueError:
                continue
        return 0

    def _finalize_unknown_detection_table(self, workflow_view: dict[str, Any], spec: dict[str, Any]) -> None:
        workflow_view["table"]["columns"] = copy.deepcopy(spec.get("view", {}).get("columns", []))
        workflow_view["columns"] = list(workflow_view["table"]["columns"])
        total_reads = self._infer_total_reads_from_summary(list(workflow_view.get("summary") or []))
        for row_data in workflow_view.get("rows", []):
            if "rpm" not in row_data:
                if total_reads > 0:
                    try:
                        raw_reads = int(str(row_data.get("reads", "0")).replace(",", ""))
                        row_data["rpm"] = f"{raw_reads / total_reads * 1_000_000:,.1f}"
                    except (TypeError, ValueError):
                        row_data["rpm"] = "—"
                else:
                    row_data["rpm"] = "—"
            row_data.setdefault("category", "—")
            row_data.setdefault("source", "Centrifuge")
        workflow_view["table"]["rows"] = list(workflow_view["rows"])

    def _build_detection_workflow_result_view(self, execution_id: str, execution_row: Any, *, feature_id: str) -> dict:
        tool_id = str(execution_row["tool_id"] or "")
        artifacts = self._normalize_artifacts(self.list_local_execution_artifacts(execution_id))
        if not artifacts:
            raise RuntimeError(f"执行结果缺少工件清单: tool={tool_id}, execution_id={execution_id}")
        ctx = self._build_execution_result_context(execution_row, artifacts)
        spec = DETECTION_WORKFLOW_SPECS.get(feature_id, {})

        fastp_view = self._build_fastp_view_from_artifacts(execution_row, feature_id="fastp")
        taxonomy_view = self._build_targeted_seq_view_for_execution(execution_id)
        if taxonomy_view is None:
            raise RuntimeError(f"工作流缺少分类结果: tool={tool_id}, execution_id={execution_id}")
        normalized_taxonomy = normalize_result_view(
            taxonomy_view,
            feature_id=feature_id,
            tool_id=tool_id,
            archetype="taxonomy_profile",
            **self._normalize_result_view_kwargs(ctx),
        )

        descriptor = self._require_tool_descriptor(feature_id)
        sections = []
        if fastp_view is not None:
            sections.append(section_from_view(fastp_view, section_id="fastp", title="质控结果", archetype="qc_report"))
        sections.append(section_from_view(normalized_taxonomy, section_id="taxonomy", title="分类结果", archetype="taxonomy_profile"))

        workflow_summary = []
        if fastp_view is not None:
            workflow_summary.extend(list(fastp_view.get("summary") or [])[:2])
        workflow_summary.extend(list(normalized_taxonomy.get("summary") or [])[:3])
        workflow_view = build_single_tool_view(
            feature_id=feature_id,
            tool_id=feature_id,
            archetype="workflow_product",
            tool_ids=[feature_id],
            title=str(spec.get("view", {}).get("title") or descriptor.get("name") or feature_id),
            description=str(spec.get("view", {}).get("description") or descriptor.get("description") or f"{feature_id} 工作流结果"),
            status={"state": "completed", "label": "结果已就绪", "detail": "已复用子工具结果构建工作流结果视图。"},
            summary=workflow_summary,
            charts=list(normalized_taxonomy.get("charts") or []),
            table=dict(normalized_taxonomy.get("table") or {}),
            artifacts=artifacts,
            provenance={
                "execution_id": ctx["execution_id"],
                "parameters": list(spec.get("view", {}).get("parameters") or []) + list(ctx["parameters"]),
                "tool_version": ctx["tool_version"],
                "remote_result_dir": ctx["remote_result_dir"],
                "local_result_dir": ctx["local_result_dir"],
            },
            sample_name=ctx["sample_name"],
            execution_id=ctx["execution_id"],
            updated_at=ctx["updated_at"],
            sections=sections,
        )
        workflow_view["table"]["title"] = str(spec.get("view", {}).get("table_title") or workflow_view["table"].get("title") or "分析结果")
        workflow_view["table"]["subtitle"] = str(spec.get("view", {}).get("table_subtitle") or workflow_view["table"].get("subtitle") or "")
        workflow_view["table_title"] = workflow_view["table"]["title"]
        workflow_view["table_subtitle"] = workflow_view["table"]["subtitle"]
        workflow_view["parameters"] = list(workflow_view["provenance"]["parameters"])

        if feature_id == "unknown_sample_detection":
            self._finalize_unknown_detection_table(workflow_view, spec)

        return workflow_view

    def _generate_targeted_seq_report(
        self,
        summary: dict,
        species_list: list[dict],
        output_dir: Path,
        *,
        classifier_name: str = "Classifier",
    ) -> Path | None:
        """生成靶向测序病原体检测报告 .txt 文件（UTF-8 BOM）。"""
        total = summary.get("total_reads", 0)
        classified = summary.get("classified_reads", 0)
        unclassified = summary.get("unclassified_reads", 0)
        pct = f"{classified / total * 100:.1f}" if total > 0 else "0.0"
        unpct = f"{unclassified / total * 100:.1f}" if total > 0 else "0.0"
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")

        lines = [
            "=" * 52,
            "        靶向测序病原体检测报告",
            "=" * 52,
            f"生成时间：{now}",
            f"分类工具：{classifier_name}",
            f"总 Reads：{total:,}",
            f"已分类：{classified:,} ({pct}%)",
            f"未分类：{unclassified:,} ({unpct}%)",
            f"检出物种数：{summary.get('species_count', 0)}",
        ]

        # 域级别分布
        domains = summary.get("domain_breakdown", [])
        if domains:
            lines.append("")
            lines.append("域级别分布：")
            for d in domains:
                lines.append(f"  {d['name']:<20}{d['reads']:>10,}  ({d['percentage']:.2f}%)")

        lines.extend([
            "",
            f"{'序号':<6}{'病原体名称':<30}{'Reads数':<12}{'占比(%)':<10}",
            "-" * 58,
        ])
        for i, item in enumerate(species_list, 1):
            name = item.get("name", "")
            reads = item.get("reads", 0)
            value = item.get("value", 0)
            lines.append(f"{i:<6}{name:<30}{reads:<12,}{value:<10.2f}")

        lines.extend([
            "=" * 52,
            "",
            "注意事项：",
            "  1. 本报告由 H2OMeta 平台自动生成，仅供科研参考。",
            "  2. 低丰度物种（<1%）可能为环境或试剂污染，需结合阴性对照判断。",
            "  3. 临床诊断需结合患者症状、流行病学史及其他实验室检测结果。",
            "  4. 物种名称遵循 NCBI Taxonomy 命名体系。",
        ])

        report_path = output_dir / "targeted_seq_report.txt"
        try:
            report_path.write_text(
                "\n".join(lines) + "\n", encoding="utf-8-sig",
            )
            return report_path
        except Exception:
            logger.exception("生成靶向测序报告失败: %s", report_path)
            return None

    def _generate_detection_pdf(
        self,
        summary: dict,
        kreport_species: list[dict],
        output_dir: Path,
        remote_dir: str,
        sample_id: str,
        execution_id: str,
        *,
        classifier_name: str = "Classifier",
    ) -> Path | None:
        """生成病原体检测 PDF 报告，尝试合并 BLAST 结果。"""
        from core.pipeline.detection_merger import DetectionMerger
        from core.pipeline.report_generator import ReportGenerator

        # 尝试查找同样品的 BLAST 结果
        blast_species = self._try_load_blast_results(sample_id, execution_id)

        # 合并
        merged = DetectionMerger.merge(
            kreport_species, blast_species, classifier_name=classifier_name,
        )
        if not merged:
            return None

        # 获取项目/样品名
        pm = self._get_project_manager()
        project_name = ""
        sample_name = sample_id
        if pm and pm.current_project:
            project_name = pm.current_project.name or ""
            try:
                row = pm.db.execute(
                    "SELECT name FROM samples WHERE sample_id = ? LIMIT 1",
                    (sample_id,),
                ).fetchone()
                if row:
                    sample_name = row["name"] or sample_id
            except Exception:
                pass

        analysis_method = f"{classifier_name} + BLASTn" if blast_species else classifier_name
        pdf_path = output_dir / "detection_report.pdf"
        return ReportGenerator.generate_detection_report(
            species_list=merged,
            summary=summary,
            output_path=str(pdf_path),
            project_name=project_name,
            sample_name=sample_name,
            analysis_method=analysis_method,
        )

    def _try_load_blast_results(
        self, sample_id: str, current_exec_id: str,
    ) -> list[dict] | None:
        """查找同样品最新的 blastn 执行结果，解析并返回。"""
        from core.pipeline.blast_result_parser import BlastResultParser

        pm = self._get_project_manager()
        if pm is None or pm.current_project is None:
            return None

        try:
            row = pm.db.execute(
                "SELECT execution_id FROM executions "
                "WHERE sample_id = ? AND tool_id = 'blastn' AND status = 'completed' "
                "ORDER BY rowid DESC LIMIT 1",
                (sample_id,),
            ).fetchone()
        except Exception:
            return None

        if not row:
            return None

        blast_exec_id = row["execution_id"]
        results_dir = self._execution_results_dir(blast_exec_id)
        if results_dir is None:
            return None

        # 查找 blast 结果 TSV
        blast_tsv = results_dir / f"{sample_id}_blast.tsv"

        if not blast_tsv.exists():
            return None

        return BlastResultParser.parse(str(blast_tsv))
