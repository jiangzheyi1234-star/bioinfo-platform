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
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

from core.data.database_service import DatabaseService
from core.execution.artifact_store import ArtifactStore
from core.execution.execution_status_service import ExecutionStatusService
from core.execution.tool_bridge_artifacts import ToolBridgeArtifactHelper
from core.execution.tool_bridge_history import ToolBridgeHistoryHelper
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
from core.execution.tool_bridge_execution_ops import (
    _descriptor_consumes_database_var as _tb_descriptor_consumes_database_var,
    _get_superseded_running_execution_ids as _tb_get_superseded_running_execution_ids,
    _parameter_items_from_dict as _tb_parameter_items_from_dict,
    _parse_execution_parameters as _tb_parse_execution_parameters,
    _resolve_result_archetype as _tb_resolve_result_archetype,
    _strict_json_loads as _tb_strict_json_loads,
    build_database_paths as _tb_build_database_paths,
    count_remote_lines as _tb_count_remote_lines,
    delete_execution_history as _tb_delete_execution_history,
    ensure_sample_id as _tb_ensure_sample_id,
    execute_tool as _tb_execute_tool,
    extract_database_paths as _tb_extract_database_paths,
    extract_run_params as _tb_extract_run_params,
    find_execution_input as _tb_find_execution_input,
    find_latest_completed_execution as _tb_find_latest_completed_execution,
    get_default_primer_result_dir as _tb_get_default_primer_result_dir,
    get_execution_history as _tb_get_execution_history,
    get_latest_sample_id as _tb_get_latest_sample_id,
    get_tool_descriptor as _tb_get_tool_descriptor,
    get_tools as _tb_get_tools,
    import_inputs as _tb_import_inputs,
    normalize_project_remote_base as _tb_normalize_project_remote_base,
    read_remote_file as _tb_read_remote_file,
    safe_json_loads as _tb_safe_json_loads,
    set_plugin_registry as _tb_set_plugin_registry,
    set_service_locator as _tb_set_service_locator,
    validate_required_databases as _tb_validate_required_databases,
)
from core.execution.tool_bridge_workbench_ops import (
    _build_detection_workflow_view_for_execution as _tb_build_detection_workflow_view_for_execution,
    _build_multiplex_view_from_artifacts as _tb_build_multiplex_view_from_artifacts,
    _build_primer_view_from_artifacts as _tb_build_primer_view_from_artifacts,
    _ensure_detection_workbench_entries as _tb_ensure_detection_workbench_entries,
    _get_live_detection_workflow_view as _tb_get_live_detection_workflow_view,
    _get_live_targeted_seq_view as _tb_get_live_targeted_seq_view,
    _get_live_unknown_sample_detection_view as _tb_get_live_unknown_sample_detection_view,
    build_multiplex_view_from_result_dir as _tb_build_multiplex_view_from_result_dir,
    build_primer_view_from_result_dir as _tb_build_primer_view_from_result_dir,
    get_integrated_workbench_config as _tb_get_integrated_workbench_config,
    get_live_multiplex_primer_panel_view as _tb_get_live_multiplex_primer_panel_view,
    get_live_primer_design_view as _tb_get_live_primer_design_view,
    get_multiplex_view_for_execution as _tb_get_multiplex_view_for_execution,
    get_primer_view_for_execution as _tb_get_primer_view_for_execution,
    get_remote_primer_results as _tb_get_remote_primer_results,
)
from core.execution.workbench_view_builders import build_multiplex_view, build_primer_view
from core.pipeline.chart_data_parser import ChartDataParser

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

    set_service_locator = _tb_set_service_locator
    set_plugin_registry = _tb_set_plugin_registry
    find_latest_completed_execution = _tb_find_latest_completed_execution
    find_execution_input = _tb_find_execution_input
    read_remote_file = _tb_read_remote_file
    count_remote_lines = _tb_count_remote_lines
    safe_json_loads = staticmethod(_tb_safe_json_loads)
    _strict_json_loads = staticmethod(_tb_strict_json_loads)
    get_default_primer_result_dir = _tb_get_default_primer_result_dir
    _build_primer_view_from_artifacts = _tb_build_primer_view_from_artifacts
    _build_multiplex_view_from_artifacts = _tb_build_multiplex_view_from_artifacts
    get_live_primer_design_view = _tb_get_live_primer_design_view
    build_primer_view_from_result_dir = _tb_build_primer_view_from_result_dir
    get_primer_view_for_execution = _tb_get_primer_view_for_execution
    build_multiplex_view_from_result_dir = _tb_build_multiplex_view_from_result_dir
    get_live_multiplex_primer_panel_view = _tb_get_live_multiplex_primer_panel_view
    get_multiplex_view_for_execution = _tb_get_multiplex_view_for_execution
    get_tools = _tb_get_tools
    get_tool_descriptor = _tb_get_tool_descriptor
    _parse_execution_parameters = staticmethod(_tb_parse_execution_parameters)
    _parameter_items_from_dict = staticmethod(_tb_parameter_items_from_dict)
    _resolve_result_archetype = staticmethod(_tb_resolve_result_archetype)
    execute_tool = _tb_execute_tool
    normalize_project_remote_base = _tb_normalize_project_remote_base
    _descriptor_consumes_database_var = staticmethod(_tb_descriptor_consumes_database_var)
    get_latest_sample_id = _tb_get_latest_sample_id
    build_database_paths = _tb_build_database_paths
    ensure_sample_id = _tb_ensure_sample_id
    import_inputs = _tb_import_inputs
    extract_run_params = staticmethod(_tb_extract_run_params)
    extract_database_paths = staticmethod(_tb_extract_database_paths)
    validate_required_databases = staticmethod(_tb_validate_required_databases)
    get_execution_history = _tb_get_execution_history
    _get_superseded_running_execution_ids = staticmethod(_tb_get_superseded_running_execution_ids)
    delete_execution_history = _tb_delete_execution_history
    get_integrated_workbench_config = _tb_get_integrated_workbench_config
    get_remote_primer_results = _tb_get_remote_primer_results
    _ensure_detection_workbench_entries = _tb_ensure_detection_workbench_entries
    _build_detection_workflow_view_for_execution = _tb_build_detection_workflow_view_for_execution
    _get_live_detection_workflow_view = _tb_get_live_detection_workflow_view
    _get_live_unknown_sample_detection_view = _tb_get_live_unknown_sample_detection_view
    _get_live_targeted_seq_view = _tb_get_live_targeted_seq_view

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
        self._artifact_helper = ToolBridgeArtifactHelper(self)
        self._history_helper = ToolBridgeHistoryHelper(self)

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

    def _get_current_project_dir(self) -> Path | None:
        return self._artifact_helper._get_current_project_dir()

    def _execution_results_dir(self, execution_id: str) -> Path | None:
        return self._artifact_helper._execution_results_dir(execution_id)

    def _manifest_path(self, cache_key: str) -> Path | None:
        return self._artifact_helper._manifest_path(cache_key)

    def _load_manifest(self, cache_key: str) -> dict | None:
        return self._artifact_helper._load_manifest(cache_key)

    def _normalize_artifacts(self, artifacts: list[dict] | None) -> list[dict]:
        return self._artifact_helper._normalize_artifacts(artifacts)

    def _artifact_by_name(self, artifacts: list[dict], name: str) -> dict | None:
        return self._artifact_helper._artifact_by_name(artifacts, name)

    def _local_artifact_path(self, artifacts: list[dict], name: str) -> Path | None:
        return self._artifact_helper._local_artifact_path(artifacts, name)

    def _read_local_artifact_text(self, artifacts: list[dict], name: str) -> str:
        return self._artifact_helper._read_local_artifact_text(artifacts, name)

    def _count_local_artifact_lines(self, artifacts: list[dict], name: str) -> int | None:
        return self._artifact_helper._count_local_artifact_lines(artifacts, name)

    @staticmethod
    def _available_artifacts(artifacts: list[dict]) -> list[dict]:
        return ToolBridgeArtifactHelper._available_artifacts(artifacts)

    @staticmethod
    def _local_result_dir_for_execution(execution_id: str, artifacts: list[dict]) -> str:
        return ToolBridgeArtifactHelper._local_result_dir_for_execution(execution_id, artifacts)

    def _artifact_from_result_views(
        self,
        descriptor: dict[str, Any],
        artifacts: list[dict],
        *,
        sample_id: str = "",
        preferred_types: tuple[str, ...] = (),
    ) -> dict[str, Any] | None:
        return self._artifact_helper._artifact_from_result_views(
            descriptor,
            artifacts,
            sample_id=sample_id,
            preferred_types=preferred_types,
        )

    @staticmethod
    def _first_available_artifact_with_suffix(artifacts: list[dict], suffixes: tuple[str, ...]) -> dict[str, Any] | None:
        return ToolBridgeArtifactHelper._first_available_artifact_with_suffix(artifacts, suffixes)

    @staticmethod
    def _parse_table_file(path: Path) -> tuple[list[dict[str, str]], list[dict[str, Any]], dict[str, Any]]:
        return ToolBridgeArtifactHelper._parse_table_file(path)

    @staticmethod
    def _summarize_row_count(rows: list[dict[str, Any]], *, label: str) -> list[dict[str, str]]:
        return ToolBridgeArtifactHelper._summarize_row_count(rows, label=label)

    def _remote_cache_key(self, tool_id: str, remote_result_dir: str) -> str:
        return self._artifact_helper._remote_cache_key(tool_id, remote_result_dir)

    def _remote_file_exists(self, ssh: Any, remote_path: str) -> bool:
        return self._artifact_helper._remote_file_exists(ssh, remote_path)

    def _cache_remote_artifacts(self, tool_id: str, remote_result_dir: str) -> list[dict]:
        return self._artifact_helper._cache_remote_artifacts(tool_id, remote_result_dir)

    def list_local_execution_artifacts(self, execution_id: str) -> list[dict]:
        return self._artifact_helper.list_local_execution_artifacts(execution_id)

    def _persist_execution_artifacts(
        self,
        execution_id: str,
        tool_id: str,
        output_dir: str,
        artifacts: list[dict],
    ) -> list[dict]:
        return self._artifact_helper._persist_execution_artifacts(
            execution_id,
            tool_id,
            output_dir,
            artifacts,
        )

    def download_execution_artifacts(self, execution_id: str) -> list[dict]:
        return self._artifact_helper.download_execution_artifacts(execution_id)

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
        return ToolBridgeArtifactHelper._parse_execution_parameters_strict(raw, execution_id)

    def _build_parameter_items(self, raw_parameters: Any, execution_id: str) -> list[dict[str, str]]:
        return self._artifact_helper._build_parameter_items(raw_parameters, execution_id)

    def _build_execution_result_context(
        self,
        execution_row: Any,
        artifacts: list[dict] | None = None,
    ) -> dict[str, Any]:
        return self._artifact_helper._build_execution_result_context(execution_row, artifacts)

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
        return self._history_helper.get_execution_remote_status(execution_id)

    def _get_execution_result_row(self, execution_id: str):
        return self._history_helper._get_execution_result_row(execution_id)

    @staticmethod
    def _format_execution_time(timestamp: Any) -> str:
        return ToolBridgeArtifactHelper._format_execution_time(timestamp)

    def _get_cached_remote_status(self, execution_id: str, local_status: str) -> dict[str, Any] | None:
        return self._history_helper._get_cached_remote_status(execution_id, local_status)

    def _set_cached_remote_status(self, execution_id: str, data: dict[str, Any]) -> None:
        self._history_helper._set_cached_remote_status(execution_id, data)

    @staticmethod
    def _parse_remote_status_block(output: str) -> dict[str, str]:
        return ToolBridgeHistoryHelper._parse_remote_status_block(output)

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
        fastp_chart = ChartDataParser.parse_fastp_json(str(local_json))
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
            charts=[fastp_chart],
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
