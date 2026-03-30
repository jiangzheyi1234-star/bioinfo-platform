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
from core.execution.result_parsers import (
    build_multiplex_columns as _parse_build_multiplex_columns,
)
from core.execution.result_parsers import (
    parse_multiplex_result_text as _parse_multiplex_result_text,
)
from core.execution.result_parsers import (
    parse_primer_result_text as _parse_primer_result_text,
)
from core.execution.single_tool_result_parsers import parse_fastp_json, parse_prokka_stats_text
from core.execution.single_tool_view_builder import build_artifact_result_view, build_single_tool_view
from core.execution.workbench_view_builders import build_multiplex_view, build_primer_view

if TYPE_CHECKING:
    from core.plugins.plugin_registry import PluginRegistry
    from core.service_locator import ServiceLocator

logger = logging.getLogger(__name__)


_DETECTION_WORKFLOW_SPECS: dict[str, dict[str, Any]] = {
    "unknown_sample_detection": {
        "feature": {
            "id": "unknown_sample_detection",
            "name": "未知样品检测",
            "badge": "mNGS",
            "description": "二代宏基因组鸟枪法测序 → fastp 质控 → hostile 去宿主 → Centrifuge 分类 + BLAST 补充鉴定 → PDF 检测报告。",
            "status": "active",
        },
        "view": {
            "feature_id": "unknown_sample_detection",
            "tool_ids": ["unknown_sample_detection"],
            "title": "未知样品病原体检测 (mNGS)",
            "description": "二代宏基因组鸟枪法测序全流程：fastp 质控 → hostile 去宿主 → Centrifuge 分类 → BLAST 补充鉴定 → 合并结果 PDF 报告。",
            "table_title": "检出微生物列表",
            "table_subtitle": "按 Reads 数降序排列，包含细菌、病毒、真菌、寄生虫等各类微生物。",
            "status": {
                "state": "ready",
                "label": "等待运行",
                "detail": "提交二代宏基因组双端 FASTQ 后，系统自动执行 QC → 去宿主 → 分类 → 报告全流程。",
            },
            "parameters": [
                {"label": "输入", "value": "二代宏基因组双端 FASTQ (PE150)"},
                {"label": "质控", "value": "fastp 接头去除 + 低质量过滤"},
                {"label": "去宿主", "value": "hostile (human-t2t-hla)"},
                {"label": "分类引擎", "value": "Centrifuge + HPVC 数据库"},
                {"label": "补充鉴定", "value": "BLAST + core_nt (未分类 reads)"},
                {"label": "输出", "value": "物种表 + 饼图 + PDF 检测报告"},
            ],
            "summary": [
                {"label": "原始 Reads", "value": "—", "tone": "primary"},
                {"label": "QC 后", "value": "—", "tone": "info"},
                {"label": "去宿主后", "value": "—", "tone": "info"},
                {"label": "宿主占比", "value": "—", "tone": "warning"},
                {"label": "已分类", "value": "—", "tone": "success"},
                {"label": "物种数", "value": "—", "tone": "success"},
                {"label": "Top 物种", "value": "—", "tone": "accent"},
            ],
            "columns": [
                {"key": "rank", "label": "#"},
                {"key": "name", "label": "微生物名称"},
                {"key": "category", "label": "类型"},
                {"key": "reads", "label": "Reads"},
                {"key": "rpm", "label": "RPM"},
                {"key": "percentage", "label": "相对丰度 (%)"},
                {"key": "source", "label": "检出来源"},
            ],
            "rows": [],
            "artifacts": [],
        },
        "legacy_workflow": "unknown_detection",
    },
    "wastewater_metagenomics_basic": {
        "feature": {
            "id": "wastewater_metagenomics_basic",
            "name": "废水宏基因组基础分析",
            "badge": "ENV",
            "description": "面向废水监测的读长宏基因组闭环：fastp → 可选 hostile → Kraken2 → Bracken → Krona。",
            "status": "active",
        },
        "view": {
            "feature_id": "wastewater_metagenomics_basic",
            "tool_ids": ["wastewater_metagenomics_basic"],
            "title": "废水宏基因组基础分析",
            "description": "面向废水监测的 read-based 宏基因组分析：fastp 质控 → 可选 hostile 去宿主 → Kraken2 分类 → Bracken 丰度重估计 → Krona 可视化。",
            "table_title": "废水样本微生物组成",
            "table_subtitle": "基于 Kraken2/Bracken 的读长分类结果，按丰度降序排列。",
            "status": {
                "state": "ready",
                "label": "等待运行",
                "detail": "提交双端 FASTQ 后，系统自动完成 QC、分类、丰度重估计与 Krona 输出。",
            },
            "parameters": [
                {"label": "输入", "value": "废水样本双端 FASTQ"},
                {"label": "质控", "value": "fastp"},
                {"label": "可选去宿主", "value": "hostile (可关闭)"},
                {"label": "分类/丰度", "value": "Kraken2 + Bracken"},
                {"label": "输出", "value": "kreport + Bracken 表 + Krona HTML"},
            ],
            "summary": [
                {"label": "总 Reads", "value": "—", "tone": "primary"},
                {"label": "已分类", "value": "—", "tone": "info"},
                {"label": "物种数", "value": "—", "tone": "success"},
                {"label": "Top 物种", "value": "—", "tone": "accent"},
            ],
            "columns": [
                {"key": "rank", "label": "序号"},
                {"key": "name", "label": "微生物名称"},
                {"key": "reads", "label": "Reads 数"},
                {"key": "percentage", "label": "占比 (%)"},
            ],
            "rows": [],
            "artifacts": [],
        },
    },
    "animal_metagenomics_basic": {
        "feature": {
            "id": "animal_metagenomics_basic",
            "name": "动物源宏基因组基础分析",
            "badge": "Animal",
            "description": "面向动物样本的读长宏基因组闭环：fastp → hostile → Kraken2 → Bracken → Krona。",
            "status": "active",
        },
        "view": {
            "feature_id": "animal_metagenomics_basic",
            "tool_ids": ["animal_metagenomics_basic"],
            "title": "动物源宏基因组基础分析",
            "description": "面向动物所病原筛查的 read-based 宏基因组分析：fastp 质控 → hostile 宿主去除 → Kraken2 分类 → Bracken 丰度重估计 → Krona 可视化。",
            "table_title": "动物样本微生物组成",
            "table_subtitle": "基于 Kraken2/Bracken 的读长分类结果，适用于动物源样本的基础检出与丰度查看。",
            "status": {
                "state": "ready",
                "label": "等待运行",
                "detail": "提交双端 FASTQ 与宿主索引后，系统自动完成 QC、去宿主、分类、丰度重估计与 Krona 输出。",
            },
            "parameters": [
                {"label": "输入", "value": "动物样本双端 FASTQ"},
                {"label": "质控", "value": "fastp"},
                {"label": "宿主去除", "value": "hostile (宿主索引必填)"},
                {"label": "分类/丰度", "value": "Kraken2 + Bracken"},
                {"label": "输出", "value": "kreport + Bracken 表 + Krona HTML"},
            ],
            "summary": [
                {"label": "总 Reads", "value": "—", "tone": "primary"},
                {"label": "已分类", "value": "—", "tone": "info"},
                {"label": "物种数", "value": "—", "tone": "success"},
                {"label": "Top 物种", "value": "—", "tone": "accent"},
            ],
            "columns": [
                {"key": "rank", "label": "序号"},
                {"key": "name", "label": "微生物名称"},
                {"key": "reads", "label": "Reads 数"},
                {"key": "percentage", "label": "占比 (%)"},
            ],
            "rows": [],
            "artifacts": [],
        },
    },
}
_DETECTION_WORKFLOW_ORDER = tuple(_DETECTION_WORKFLOW_SPECS)
_KRAKEN_MNGS_WORKFLOW_IDS = ("wastewater_metagenomics_basic", "animal_metagenomics_basic")
_TARGETED_RESULT_TOOL_IDS = ("centrifuge", "kraken2", *_DETECTION_WORKFLOW_ORDER)


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
        return {
            "title": "集成分析工作台",
            "subtitle": "集中承载多个分析能力，统一查看流程状态与分析结果。",
            "features": [
                {
                    "id": "primer_design",
                    "name": "病原体引物设计",
                    "badge": "",
                    "description": "上传病原体基因组，自动筛选保守特异靶点并设计引物对，输出每病原体的推荐引物。",
                    "status": "active",
                },
                {
                    "id": "targeted_sequencing",
                    "name": "靶向测序分析",
                    "badge": "tNGS",
                    "description": "纳米孔靶向扩增测序 → Centrifuge + HPVC 快速鉴定，输出病原体物种组成表与检测报告。",
                    "status": "active",
                },
                {
                    "id": "unknown_sample_detection",
                    "name": "未知样品检测",
                    "badge": "mNGS",
                    "description": "二代宏基因组鸟枪法测序 → fastp 质控 → hostile 去宿主 → Centrifuge 分类 + BLAST 补充鉴定 → PDF 检测报告。",
                    "status": "active",
                },
                {
                    "id": "target_screening",
                    "name": "基因组分析",
                    "badge": "",
                    "description": "按同一工作台布局接入基因组分析能力。",
                    "status": "placeholder",
                },
            ],
            "views": {
                "primer_design": {
                    "tool_ids": ["primer_design"],
                    "title": "病原体引物设计",
                    "description": "上传病原体基因组序列，系统自动完成保守靶点筛选、特异性过滤和候选引物设计，最终输出每病原体的推荐引物对。",
                    "status": {
                        "state": "ready",
                        "label": "结果已就绪",
                        "detail": "支持查看推荐结果，并可继续接入远程任务执行链路。",
                    },
                    "parameters": [
                        {"label": "输入", "value": "病原体基因组 FASTA"},
                        {"label": "靶点筛选", "value": "保守性 + 特异性"},
                        {"label": "输出", "value": "每病原体首选引物对"},
                    ],
                    "summary": [
                        {"label": "目标病原体", "value": "5", "tone": "primary"},
                        {"label": "候选引物对", "value": "18", "tone": "info"},
                        {"label": "通过二聚体过滤", "value": "9", "tone": "success"},
                        {"label": "最终推荐", "value": "5", "tone": "accent"},
                    ],
                    "columns": [
                        {"key": "pathogen", "label": "病原体"},
                        {"key": "region_id", "label": "区域 ID"},
                        {"key": "forward_primer", "label": "Forward Primer"},
                        {"key": "reverse_primer", "label": "Reverse Primer"},
                        {"key": "position", "label": "位置"},
                        {"key": "amplicon", "label": "扩增子"},
                    ],
                    "rows": [
                        {
                            "pathogen": "Mycobacterium tuberculosis",
                            "region_id": "MTB_region_01",
                            "forward_primer": "AGTGACCGTTCGATGATGAC",
                            "reverse_primer": "CTTGATCGGCTTCTTCAGGT",
                            "position": "1520-1688",
                            "amplicon": "169 bp",
                        },
                        {
                            "pathogen": "Influenza A virus",
                            "region_id": "FLUA_region_02",
                            "forward_primer": "TGGACTAGCGAAAGCAGGTA",
                            "reverse_primer": "CACCTTGTCTTTGCCAGTTC",
                            "position": "845-1016",
                            "amplicon": "172 bp",
                        },
                        {
                            "pathogen": "Rubella virus",
                            "region_id": "RUB_region_01",
                            "forward_primer": "GGATGGTGATGACACCAAGA",
                            "reverse_primer": "TTCCACCTTGAGGTTGTTGA",
                            "position": "221-373",
                            "amplicon": "153 bp",
                        },
                    ],
                    "artifacts": [
                        {"name": "primer_result_final_2.txt", "remote_path": "", "local_path": "", "available": False},
                        {"name": "primer_result_final.txt", "remote_path": "", "local_path": "", "available": False},
                        {"name": "dimer_score.txt", "remote_path": "", "local_path": "", "available": False},
                        {"name": "运行日志 / 原始结果包", "remote_path": "", "local_path": "", "available": False},
                    ],
                },
                "targeted_sequencing": {
                    "tool_ids": ["centrifuge", "kraken2"],
                    "title": "靶向测序分析 (tNGS)",
                    "description": "上传纳米孔靶向扩增测序 FASTQ，Centrifuge + HPVC 数据库快速鉴定病原体组成。",
                    "table_title": "病原体物种组成",
                    "table_subtitle": "运行 Centrifuge 分析后，物种组成表将在此呈现。",
                    "status": {
                        "state": "ready",
                        "label": "等待运行",
                        "detail": "使用 HPVC 病原体数据库，上传 FASTQ 文件后即可开始分析。",
                    },
                    "parameters": [
                        {"label": "输入", "value": "纳米孔靶向扩增 FASTQ"},
                        {"label": "分析引擎", "value": "Centrifuge + HPVC"},
                        {"label": "输出", "value": "病原体物种表 + 饼图 + TXT 报告"},
                    ],
                    "summary": [
                        {"label": "总 Reads", "value": "—", "tone": "primary"},
                        {"label": "已分类", "value": "—", "tone": "info"},
                        {"label": "物种数", "value": "—", "tone": "success"},
                        {"label": "Top 物种", "value": "—", "tone": "accent"},
                    ],
                    "columns": [
                        {"key": "rank", "label": "#"},
                        {"key": "name", "label": "物种名称"},
                        {"key": "reads", "label": "Reads"},
                        {"key": "percentage", "label": "占比 (%)"},
                    ],
                    "rows": [],
                    "artifacts": [],
                },
                "unknown_sample_detection": {
                    "tool_ids": ["unknown_sample_detection"],
                    "title": "未知样品病原体检测 (mNGS)",
                    "description": "二代宏基因组鸟枪法测序全流程：fastp 质控 → hostile 去宿主 → Centrifuge 分类 → BLAST 补充鉴定 → 合并结果 PDF 报告。",
                    "table_title": "检出微生物列表",
                    "table_subtitle": "按 Reads 数降序排列，包含细菌、病毒、真菌、寄生虫等各类微生物。",
                    "status": {
                        "state": "ready",
                        "label": "等待运行",
                        "detail": "提交二代宏基因组双端 FASTQ 后，系统自动执行 QC → 去宿主 → 分类 → 报告全流程。",
                    },
                    "parameters": [
                        {"label": "输入", "value": "二代宏基因组双端 FASTQ (PE150)"},
                        {"label": "质控", "value": "fastp 接头去除 + 低质量过滤"},
                        {"label": "去宿主", "value": "hostile (human-t2t-hla)"},
                        {"label": "分类引擎", "value": "Centrifuge + HPVC 数据库"},
                        {"label": "补充鉴定", "value": "BLAST + core_nt (未分类 reads)"},
                        {"label": "输出", "value": "物种表 + 饼图 + PDF 检测报告"},
                    ],
                    "summary": [
                        {"label": "原始 Reads", "value": "—", "tone": "primary"},
                        {"label": "QC 后", "value": "—", "tone": "info"},
                        {"label": "去宿主后", "value": "—", "tone": "info"},
                        {"label": "宿主占比", "value": "—", "tone": "warning"},
                        {"label": "已分类", "value": "—", "tone": "success"},
                        {"label": "物种数", "value": "—", "tone": "success"},
                        {"label": "Top 物种", "value": "—", "tone": "accent"},
                    ],
                    "columns": [
                        {"key": "rank", "label": "#"},
                        {"key": "name", "label": "微生物名称"},
                        {"key": "category", "label": "类型"},
                        {"key": "reads", "label": "Reads"},
                        {"key": "rpm", "label": "RPM"},
                        {"key": "percentage", "label": "相对丰度 (%)"},
                        {"key": "source", "label": "检出来源"},
                    ],
                    "rows": [],
                    "artifacts": [],
                },
            },
        }

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
    def _parse_bracken_abundance_rows(tsv_path: Path, top_n: int = 20) -> list[dict[str, str]]:
        if not tsv_path.exists():
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

    def find_registered_output(self, execution_id: str, basename: str) -> str:
        registry = self._get_data_registry()
        if registry is not None:
            for item in registry.find_by_execution(execution_id):
                if Path(item.file_path).name == basename:
                    return item.file_path

        pm = self._get_project_manager()
        if pm is None or pm.current_project is None:
            return ""

        row = pm.db.execute(
            """
            SELECT d.file_path
            FROM execution_io ei
            JOIN data_items d ON d.data_id = ei.data_id
            WHERE ei.execution_id = ?
              AND ei.direction = 'output'
            ORDER BY d.created_at DESC
            """,
            (execution_id,),
        ).fetchall()
        for item in row:
            file_path = str(item["file_path"])
            if Path(file_path).name == basename:
                return file_path
        return ""

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

    def _read_local_artifact_text(self, artifacts: list[dict], name: str) -> str:
        return self._artifact_store.read_local_artifact_text(artifacts, name)

    def _count_local_artifact_lines(self, artifacts: list[dict], name: str) -> int | None:
        return self._artifact_store.count_local_artifact_lines(artifacts, name)

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
        return self._artifact_store.list_local_execution_artifacts(execution_id)

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
        return self.get_primer_view_for_execution(execution["execution_id"])

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
        artifacts = self.list_local_execution_artifacts(normalized_execution_id)

        pm = self._get_project_manager()
        if pm is None or pm.current_project is None:
            return None

        self.normalize_project_remote_base(pm)

        try:
            row = pm.db.execute(
                """
                SELECT tool_id, sample_id
                FROM executions
                WHERE execution_id = ?
                LIMIT 1
                """,
                (normalized_execution_id,),
            ).fetchone()
        except Exception:
            logger.exception("Failed to query execution %s", normalized_execution_id)
            return None

        if not row or row["tool_id"] != "primer_design":
            return None

        remote_dir = f"{pm.current_project.remote_base}/intermediate/{row['sample_id']}/primer_design_{normalized_execution_id}"
        if not artifacts:
            artifacts = self._cache_remote_artifacts("primer_design", remote_dir)

        exec_row = pm.db.execute(
            """
            SELECT e.parameters, e.created_at, e.completed_at, e.tool_id, s.name AS sample_name
            FROM executions e
            LEFT JOIN samples s ON s.sample_id = e.sample_id
            WHERE e.execution_id = ?
            LIMIT 1
            """,
            (normalized_execution_id,),
        ).fetchone()
        params = self.safe_json_loads(exec_row["parameters"] if exec_row else "")
        mode = params.get("mode", "quick")
        ts = (exec_row["completed_at"] if exec_row else None) or (exec_row["created_at"] if exec_row else None) or time.time()
        return self._build_primer_view_from_artifacts(
            artifacts=artifacts,
                        remote_result_dir=remote_dir,
            description=(
                "用途：将病原体靶向引物集合优化为可同池扩增的多重引物池，输出可交付的池方案与合成清单。"
                "\n实现：基于候选引物进行迭代替换优化，并按交叉二聚体、Tm 一致性、扩增子长度差异与覆盖校验综合筛选。"
            ),
            status={
                "state": "completed",
                "label": "结果可用",
                "detail": "流程已完成：已生成 multiplex_panel、synthesis_order、validation_report，可直接查看与交付。",
            },            parameters=[
                {
                    "label": "结果目录",
                    "value": remote_dir,
                    "description": "Multiplex 任务在服务器端的结果目录，用于加载该次任务产物。",
                },
                {
                    "label": "主结果",
                    "value": "multiplex_panel.txt",
                    "description": "主结果文件，包含入池引物对及相关评分信息。",
                },
                {
                    "label": "合成订单",
                    "value": "synthesis_order.txt",
                    "description": "合成下单文件，用于导出引物采购/合成名单。",
                },
            ],
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
        return self.get_multiplex_view_for_execution(execution["execution_id"])

    def get_multiplex_view_for_execution(self, execution_id: str) -> dict | None:
        normalized_execution_id = str(execution_id or "").strip()
        if not normalized_execution_id:
            return None
        artifacts = self.list_local_execution_artifacts(normalized_execution_id)

        pm = self._get_project_manager()
        if pm is None or pm.current_project is None:
            return None

        self.normalize_project_remote_base(pm)

        try:
            row = pm.db.execute(
                """
                SELECT tool_id, sample_id
                FROM executions
                WHERE execution_id = ?
                LIMIT 1
                """,
                (normalized_execution_id,),
            ).fetchone()
        except Exception:
            logger.exception("Failed to query execution %s", normalized_execution_id)
            return None

        if not row or row["tool_id"] != "multiplex_primer_panel":
            return None

        remote_dir = (
            f"{pm.current_project.remote_base}/intermediate/"
            f"{row['sample_id']}/multiplex_primer_panel_{normalized_execution_id}"
        )
        if not artifacts:
            artifacts = self._cache_remote_artifacts("multiplex_primer_panel", remote_dir)
            artifacts = self._persist_execution_artifacts(
                execution_id=normalized_execution_id,
                tool_id="multiplex_primer_panel",
                output_dir=remote_dir,
                artifacts=artifacts,
            )

        return self._build_multiplex_view_from_artifacts(
            artifacts=artifacts,
            remote_result_dir=remote_dir,
            description=(
                "用途：用于靶向病原体多重 PCR 方案设计，输出可直接用于实验与交付的池化结果和合成清单。"
                "\n实现：流程内自动执行候选引物合并、迭代优化、交叉二聚体评估、扩增子冲突检查以及 Tm/GC 一致性校验。"
            ),
            status={
                "state": "completed",
                "label": "结果可用",
                "detail": "从历史任务加载的多重引物池结果。",
            },
            parameters=[
                {"label": "任务 ID", "value": normalized_execution_id},
                {"label": "主结果", "value": "multiplex_panel.txt"},
            ],
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
        else:
            default_remote_view = self.build_primer_view_from_result_dir(self.get_default_primer_result_dir())
            if default_remote_view is not None:
                default_remote_view["status"] = {
                    "state": "completed",
                    "label": "已加载默认远程结果",
                    "detail": "未找到历史执行记录，已自动读取服务器默认 primer 结果目录。",
                }
                views["primer_design"] = default_remote_view

        live_multiplex_view = self.get_live_multiplex_primer_panel_view()
        if live_multiplex_view is not None:
            views["multiplex_primer_panel"] = live_multiplex_view

        for workflow_id in _DETECTION_WORKFLOW_ORDER:
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

            tool_id = str(execution_row["tool_id"] or "")
            if tool_id == "primer_design":
                return self.get_primer_results_for_execution(normalized_id)
            if tool_id == "multiplex_primer_panel":
                return self.get_multiplex_results_for_execution(normalized_id)
            if tool_id == "fastp":
                return self.get_fastp_results_for_execution(normalized_id)
            if tool_id in ("centrifuge", "kraken2", *_DETECTION_WORKFLOW_ORDER):
                return self.get_targeted_seq_results_for_execution(normalized_id)

            view = self._build_single_tool_view_for_execution(normalized_id)
            if view is None:
                return {
                    "status": "error",
                    "message": f"工具 {tool_id} 暂无可展示的结果视图，请先查看结果文件。",
                }
            return {"status": "ok", "view": view}
        except Exception as exc:
            logger.exception("Failed to build results for execution %s", normalized_id)
            return {"status": "error", "message": str(exc)}

    def get_primer_results_for_execution(self, execution_id: str) -> dict:
        view = self.get_primer_view_for_execution(execution_id)
        if view is None:
            return {
                "status": "error",
                "message": "未能从该任务读取引物结果，请确认任务已完成且 primer_result_final_2.txt 已生成。",
            }
        return {"status": "ok", "view": view}

    def get_multiplex_results_for_execution(self, execution_id: str) -> dict:
        view = self.get_multiplex_view_for_execution(execution_id)
        if view is None:
            return {
                "status": "error",
                "message": "未能从该任务读取 multiplex 结果，请确认任务已完成且 multiplex_panel.txt 已生成。",
            }
        return {"status": "ok", "view": view}

    def get_targeted_seq_results_for_execution(self, execution_id: str) -> dict:
        workflow_id = self._resolve_detection_workflow_id_for_execution(execution_id)
        if workflow_id is not None:
            view = self._build_detection_workflow_view_for_execution(workflow_id, execution_id)
        else:
            view = self._build_targeted_seq_view_for_execution(execution_id)
        if view is None:
            return {
                "status": "error",
                "message": "未能从该任务读取分类结果，请确认任务已完成且 kreport 文件已生成。",
            }
        return {"status": "ok", "view": view}

    def get_fastp_results_for_execution(self, execution_id: str) -> dict:
        """从 fastp 已完成的 execution 构建 QC 结果 view。"""
        view = self._build_fastp_view_for_execution(execution_id)
        if view is None:
            return {
                "status": "error",
                "message": "未能从该任务读取 fastp 质控结果，请确认任务已完成且 fastp.json 已生成。",
            }
        return {"status": "ok", "view": view}

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
        for workflow_id in _DETECTION_WORKFLOW_ORDER:
            spec = _DETECTION_WORKFLOW_SPECS[workflow_id]
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
        if tool_id in _DETECTION_WORKFLOW_ORDER:
            return tool_id

        if tool_id not in ("centrifuge", "kraken2"):
            return None

        try:
            params = json.loads(row["parameters"] or "{}")
        except Exception:
            params = {}
        legacy_workflow = _DETECTION_WORKFLOW_SPECS["unknown_sample_detection"].get("legacy_workflow")
        if params.get("workflow") == legacy_workflow:
            return "unknown_sample_detection"
        return None

    def _build_detection_workflow_view_for_execution(self, workflow_id: str, execution_id: str) -> dict | None:
        spec = _DETECTION_WORKFLOW_SPECS.get(workflow_id)
        if spec is None:
            return None

        view = self._build_targeted_seq_view_for_execution(execution_id)
        if view is None:
            return None

        default_view = spec["view"]
        view["feature_id"] = workflow_id
        view["tool_ids"] = list(default_view.get("tool_ids", [workflow_id]))
        view["title"] = default_view.get("title", view.get("title"))
        view["description"] = default_view.get("description", view.get("description"))
        view["table_title"] = default_view.get("table_title", view.get("table_title"))
        view["table_subtitle"] = default_view.get("table_subtitle", view.get("table_subtitle"))

        if workflow_id == "unknown_sample_detection":
            view["columns"] = copy.deepcopy(default_view.get("columns", []))
            total_reads = 0
            try:
                for item in view.get("summary", []):
                    if "Reads" in item.get("label", "") and item["value"] != "—":
                        total_reads = int(str(item["value"]).replace(",", "").split("(")[0].strip())
                        break
            except (ValueError, KeyError):
                total_reads = 0

            for row_data in view.get("rows", []):
                if "rpm" not in row_data and total_reads > 0:
                    try:
                        raw_reads = int(str(row_data.get("reads", "0")).replace(",", ""))
                        row_data["rpm"] = f"{raw_reads / total_reads * 1_000_000:,.1f}"
                    except (ValueError, TypeError):
                        row_data["rpm"] = "—"
                elif "rpm" not in row_data:
                    row_data["rpm"] = "—"
                row_data.setdefault("category", "—")
                row_data.setdefault("source", "Centrifuge")

        return view

    def _get_live_detection_workflow_view(self, workflow_id: str) -> dict | None:
        pm = self._get_project_manager()
        if pm is None or pm.current_project is None:
            return None

        spec = _DETECTION_WORKFLOW_SPECS.get(workflow_id)
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
        return self._build_targeted_seq_view_for_execution(target_eid)

    def _build_single_tool_view_for_execution(self, execution_id: str) -> dict | None:
        execution_row = self._get_execution_result_row(execution_id)
        if execution_row is None:
            return None

        tool_id = str(execution_row["tool_id"] or "").strip()
        if not tool_id:
            raise RuntimeError(f"执行记录缺少 tool_id: {execution_id}")
        if tool_id == "prokka":
            return self._build_prokka_view_for_execution(execution_id, execution_row)

        descriptor = self.get_tool_descriptor(tool_id)
        if not descriptor:
            raise RuntimeError(f"工具描述符不存在: {tool_id}")

        artifacts = self.list_local_execution_artifacts(str(execution_row["execution_id"] or ""))
        artifacts = self._normalize_artifacts(artifacts)
        if not artifacts:
            raise RuntimeError(f"执行结果缺少工件清单: tool={tool_id}, execution_id={execution_id}")

        manifest = self._load_manifest(str(execution_row["execution_id"] or ""))
        remote_result_dir = str((manifest or {}).get("output_dir") or "").strip()
        sample_name = str(execution_row["sample_name"] or execution_row["sample_id"] or "")
        completed_at = execution_row["completed_at"] or execution_row["created_at"]
        params = self.safe_json_loads(execution_row["parameters"] or "")
        parameter_items = [
            {"label": str(key), "value": str(value)}
            for key, value in params.items()
            if value not in ("", None)
        ]

        return build_artifact_result_view(
            feature_id=tool_id,
            tool_ids=[tool_id],
            title=str(descriptor.get("name") or tool_id),
            description=str(descriptor.get("description") or f"{tool_id} 结果"),
            status={
                "state": "completed",
                "label": "结果已就绪",
                "detail": "当前工具尚未声明结构化结果面板，以下展示已同步结果文件。",
            },
            artifacts=artifacts,
            parameters=parameter_items,
            sample_name=sample_name,
            execution_id=str(execution_row["execution_id"] or ""),
            updated_at=self._format_execution_time(completed_at),
            tool_version=str(execution_row["tool_version"] or ""),
            remote_result_dir=remote_result_dir,
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

        descriptor = self.get_tool_descriptor("prokka")
        if not descriptor:
            raise RuntimeError("工具描述符不存在: prokka")

        manifest = self._load_manifest(str(row["execution_id"] or ""))
        remote_result_dir = str((manifest or {}).get("output_dir") or "").strip()
        params = self.safe_json_loads(row["parameters"] or "")
        parameter_items = [
            {"label": str(key), "value": str(value)}
            for key, value in params.items()
            if value not in ("", None)
        ]
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
        completed_at = row["completed_at"] or row["created_at"]
        return build_single_tool_view(
            feature_id="prokka",
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
            parameters=parameter_items,
            table_title="注释统计",
            table_subtitle="Prokka 输出的主要注释统计摘要。",
            sample_name=str(row["sample_name"] or sample_id),
            execution_id=str(row["execution_id"] or ""),
            updated_at=self._format_execution_time(completed_at),
            tool_version=str(row["tool_version"] or ""),
            remote_result_dir=remote_result_dir,
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

        sample_id = row["sample_id"]
        remote_dir = f"{pm.current_project.remote_base}/intermediate/{sample_id}/fastp_{normalized_id}"

        results_dir = self._execution_results_dir(normalized_id)
        if results_dir is None:
            return None
        results_dir.mkdir(parents=True, exist_ok=True)

        json_name = f"{sample_id}.fastp.json"
        html_name = f"{sample_id}.fastp.html"
        artifacts = self._normalize_artifacts(self.list_local_execution_artifacts(normalized_id))
        json_artifact = self._artifact_by_name(artifacts, json_name)
        html_artifact = self._artifact_by_name(artifacts, html_name)
        local_json = Path(str((json_artifact or {}).get("local_path") or results_dir / json_name))

        if not local_json.exists():
            ssh = self._get_ssh_service()
            if ssh is None or not getattr(ssh, "is_connected", False):
                return None
            try:
                ssh.download(f"{remote_dir}/{json_name}", str(local_json))
            except Exception as exc:
                logger.warning("下载 %s 失败: %s", json_name, exc)
                return None

        if not local_json.exists():
            return None

        try:
            fastp_data = parse_fastp_json(local_json)
        except Exception:
            return None

        summary = fastp_data.get("summary", {})
        before = summary.get("before_filtering", {})
        after = summary.get("after_filtering", {})
        filtering = fastp_data.get("filtering_result", {})

        total_before = before.get("total_reads", 0)
        total_after = after.get("total_reads", 0)
        q30_before = before.get("q30_rate", 0)
        q30_after = after.get("q30_rate", 0)
        gc_after = after.get("gc_content", 0)
        passed = filtering.get("passed_filter_reads", 0)
        low_quality = filtering.get("low_quality_reads", 0)
        too_short = filtering.get("too_short_reads", 0)
        too_many_n = filtering.get("too_many_N_reads", 0)

        pct_pass = f"{passed / total_before * 100:.1f}%" if total_before > 0 else "—"
        execution_row = self._get_execution_result_row(normalized_id)
        sample_name = sample_id
        completed_at = ""
        tool_version = ""
        if execution_row is not None:
            sample_name = str(execution_row["sample_name"] or sample_id)
            completed_at = self._format_execution_time(execution_row["completed_at"] or execution_row["created_at"])
            tool_version = str(execution_row["tool_version"] or "")
        return build_single_tool_view(
            feature_id="fastp",
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
                {"metric": "GC 含量", "before": f"{before.get('gc_content', 0):.2%}", "after": f"{gc_after:.2%}"},
                {"metric": "低质量 Reads", "before": "—", "after": f"{low_quality:,}"},
                {"metric": "过短 Reads", "before": "—", "after": f"{too_short:,}"},
                {"metric": "高 N Reads", "before": "—", "after": f"{too_many_n:,}"},
                {"metric": "通过率", "before": "—", "after": pct_pass},
            ],
            artifacts=[
                {
                    "name": json_name,
                    "remote_path": f"{remote_dir}/{json_name}",
                    "local_path": str(local_json),
                    "available": True,
                },
                {
                    "name": html_name,
                    "remote_path": f"{remote_dir}/{html_name}",
                    "local_path": str((html_artifact or {}).get("local_path") or ""),
                    "available": bool((html_artifact or {}).get("available")),
                },
            ],
            parameters=[
                {"label": "输入", "value": f"双端 FASTQ ({total_before:,} reads)"},
                {"label": "输出", "value": f"清洁 reads ({total_after:,} reads)"},
                {"label": "工具", "value": "fastp"},
            ],
            table_title="质控过滤统计",
            table_subtitle="fastp 接头去除 + 低质量过滤详情。",
            sample_name=sample_name,
            execution_id=normalized_id,
            updated_at=completed_at,
            tool_version=tool_version,
            remote_result_dir=remote_dir,
        )

    def _build_targeted_seq_view_for_execution(self, execution_id: str) -> dict | None:
        """从 execution 记录构建靶向测序结果 view（含饼图 + 表格 + 报告）。"""
        from core.pipeline.chart_data_parser import ChartDataParser

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
            logger.exception("Failed to query execution %s", normalized_id)
            return None

        if not row or row["tool_id"] not in _TARGETED_RESULT_TOOL_IDS:
            return None

        tool_id = row["tool_id"]
        sample_id = row["sample_id"]
        remote_dir = f"{pm.current_project.remote_base}/intermediate/{sample_id}/{tool_id}_{normalized_id}"

        # 下载 kreport 到本地缓存
        results_dir = self._execution_results_dir(normalized_id)
        if results_dir is None:
            return None
        results_dir.mkdir(parents=True, exist_ok=True)

        kreport_name = f"{sample_id}.kreport"
        coverage_depth_name = f"{sample_id}.coverage_depth.tsv"
        amplicon_perf_name = f"{sample_id}.amplicon_performance.tsv"
        fastp_json_name = f"{sample_id}.fastp.json"
        bracken_name = f"{sample_id}.bracken.tsv"
        bracken_kreport_name = f"{sample_id}.bracken.kreport"
        krona_name = f"{sample_id}.krona.html"
        local_kreport = results_dir / kreport_name
        local_coverage_depth = results_dir / coverage_depth_name
        local_amplicon_perf = results_dir / amplicon_perf_name
        local_fastp_json = results_dir / fastp_json_name
        local_bracken = results_dir / bracken_name
        local_bracken_kreport = results_dir / bracken_kreport_name
        local_krona = results_dir / krona_name
        if not local_kreport.exists():
            ssh = self._get_ssh_service()
            if ssh is None or not getattr(ssh, "is_connected", False):
                return None
            try:
                ssh.download(f"{remote_dir}/{kreport_name}", str(local_kreport))
            except Exception as exc:
                logger.warning("下载 kreport 失败: %s", exc)
                return None

        if not local_kreport.exists():
            return None

        # 解析数据
        if (not local_coverage_depth.exists()) or (not local_amplicon_perf.exists()):
            ssh = self._get_ssh_service()
            if ssh is not None and getattr(ssh, "is_connected", False):
                if not local_coverage_depth.exists():
                    try:
                        ssh.download(f"{remote_dir}/{coverage_depth_name}", str(local_coverage_depth))
                    except Exception:
                        pass
                if not local_amplicon_perf.exists():
                    try:
                        ssh.download(f"{remote_dir}/{amplicon_perf_name}", str(local_amplicon_perf))
                    except Exception:
                        pass
                if tool_id in _KRAKEN_MNGS_WORKFLOW_IDS:
                    if not local_fastp_json.exists():
                        try:
                            ssh.download(f"{remote_dir}/{fastp_json_name}", str(local_fastp_json))
                        except Exception:
                            pass
                    if not local_bracken.exists():
                        try:
                            ssh.download(f"{remote_dir}/{bracken_name}", str(local_bracken))
                        except Exception:
                            pass
                    if not local_bracken_kreport.exists():
                        try:
                            ssh.download(f"{remote_dir}/{bracken_kreport_name}", str(local_bracken_kreport))
                        except Exception:
                            pass
                    if not local_krona.exists():
                        try:
                            ssh.download(f"{remote_dir}/{krona_name}", str(local_krona))
                        except Exception:
                            pass

        chart_data = ChartDataParser.parse_kreport(str(local_kreport))
        sunburst_chart = ChartDataParser.parse_kreport_tree(str(local_kreport))
        summary_data = ChartDataParser.parse_kreport_summary(str(local_kreport))
        bracken_rows = self._parse_bracken_abundance_rows(local_bracken)
        read_flow_chart = self._build_read_flow_chart(
            local_fastp_json if local_fastp_json.exists() else None,
            summary_data,
        )
        coverage_chart = {"type": "coverage_depth", "title": "Coverage Depth", "data": []}
        amplicon_chart = {"type": "amplicon_performance", "title": "Amplicon Performance", "data": []}
        if local_coverage_depth.exists():
            coverage_chart = ChartDataParser.parse_coverage_depth(str(local_coverage_depth))
        if local_amplicon_perf.exists():
            amplicon_chart = ChartDataParser.parse_amplicon_performance(str(local_amplicon_perf))

        abundance_bar_data = chart_data.get("data", [])[:20]
        abundance_bar_title = "物种丰度 (Top 20)"
        if bracken_rows:
            abundance_bar_data = [
                {
                    "name": row["name"],
                    "reads": int(row["reads"].replace(",", "")),
                    "value": float(row["percentage"].rstrip("%")),
                }
                for row in bracken_rows
            ]
            abundance_bar_title = "Bracken 丰度 (Top 20)"

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
        if sunburst_chart.get("data"):
            charts.append(sunburst_chart)
        if coverage_chart.get("data"):
            charts.append({
                "type": "coverage_depth",
                "title": "Coverage Depth",
                "data": coverage_chart.get("data", []),
            })
        if amplicon_chart.get("data"):
            charts.append({
                "type": "amplicon_performance",
                "title": "Amplicon Performance",
                "data": amplicon_chart.get("data", []),
            })

        # 构建表格行
        rows = []
        for i, item in enumerate(chart_data.get("data", []), 1):
            rows.append({
                "rank": str(i),
                "name": item["name"],
                "reads": f'{item.get("reads", 0):,}',
                "percentage": f'{item["value"]:.2f}%',
            })
        columns = [
            {"key": "rank", "label": "序号"},
            {"key": "name", "label": "病原体名称"},
            {"key": "reads", "label": "Reads 数"},
            {"key": "percentage", "label": "占比 (%)"},
        ]
        table_title = "病原体物种组成"
        table_badge = kreport_name
        table_subtitle = "基于 kreport 解析的物种组成，按丰度降序排列。"
        if bracken_rows:
            rows = bracken_rows
            columns = [
                {"key": "rank", "label": "序号"},
                {"key": "name", "label": "物种名称"},
                {"key": "reads", "label": "Bracken Reads"},
                {"key": "percentage", "label": "相对丰度 (%)"},
            ]
            table_title = "Bracken 丰度结果"
            table_badge = bracken_name
            table_subtitle = "优先展示 Bracken 重估后的物种丰度结果。"

        # 摘要卡片
        total = summary_data["total_reads"]
        classified = summary_data["classified_reads"]
        unclassified = summary_data["unclassified_reads"]
        pct = f"{classified / total * 100:.1f}%" if total > 0 else "0%"
        domains = summary_data.get("domain_breakdown", [])
        domain_text = " / ".join(f"{d['name']} {d['percentage']}%" for d in domains[:3]) if domains else "N/A"

        summary = [
            {"label": "总 Reads", "value": f"{total:,}", "tone": "primary"},
            {"label": "已分类", "value": f"{classified:,} ({pct})", "tone": "info"},
            {"label": "物种数", "value": str(summary_data["species_count"]), "tone": "success"},
            {"label": "Top 物种", "value": summary_data["top_species"], "tone": "accent"},
        ]

        classifier_label = "Centrifuge" if tool_id in ("centrifuge", "unknown_sample_detection") else "Kraken2"

        # 生成报告（TXT + PDF）
        report_path = self._generate_targeted_seq_report(
            summary_data, chart_data.get("data", []), results_dir,
            classifier_name=classifier_label,
        )

        # 尝试生成 PDF 报告（合并 BLAST 结果如果有的话）
        pdf_path = self._generate_detection_pdf(
            summary_data, chart_data.get("data", []),
            results_dir, remote_dir, sample_id, normalized_id,
            classifier_name=classifier_label,
        )

        # 构建 artifacts
        artifacts = [
            {
                "name": kreport_name,
                "remote_path": f"{remote_dir}/{kreport_name}",
                "local_path": str(local_kreport),
                "available": True,
            },
        ]
        if local_coverage_depth.exists():
            artifacts.append({
                "name": coverage_depth_name,
                "remote_path": f"{remote_dir}/{coverage_depth_name}",
                "local_path": str(local_coverage_depth),
                "available": True,
            })
        if local_amplicon_perf.exists():
            artifacts.append({
                "name": amplicon_perf_name,
                "remote_path": f"{remote_dir}/{amplicon_perf_name}",
                "local_path": str(local_amplicon_perf),
                "available": True,
            })
        if local_fastp_json.exists():
            artifacts.append({
                "name": fastp_json_name,
                "remote_path": f"{remote_dir}/{fastp_json_name}",
                "local_path": str(local_fastp_json),
                "available": True,
            })
        if local_bracken.exists():
            artifacts.append({
                "name": bracken_name,
                "remote_path": f"{remote_dir}/{bracken_name}",
                "local_path": str(local_bracken),
                "available": True,
            })
        if local_bracken_kreport.exists():
            artifacts.append({
                "name": bracken_kreport_name,
                "remote_path": f"{remote_dir}/{bracken_kreport_name}",
                "local_path": str(local_bracken_kreport),
                "available": True,
            })
        if local_krona.exists():
            artifacts.append({
                "name": krona_name,
                "remote_path": f"{remote_dir}/{krona_name}",
                "local_path": str(local_krona),
                "available": True,
            })
        if report_path and report_path.exists():
            artifacts.append({
                "name": "targeted_seq_report.txt",
                "remote_path": "",
                "local_path": str(report_path),
                "available": True,
            })
        if pdf_path and pdf_path.exists():
            artifacts.append({
                "name": "病原体检测报告.pdf",
                "remote_path": "",
                "local_path": str(pdf_path),
                "available": True,
                "is_pdf_report": True,
            })

        available_tool_ids = ["centrifuge", "kraken2"] if tool_id in ("centrifuge", "kraken2") else [tool_id]
        if tool_id in available_tool_ids:
            ordered_tool_ids = [tool_id] + [tid for tid in available_tool_ids if tid != tool_id]
        else:
            ordered_tool_ids = available_tool_ids

        return {
            "tool_ids": ordered_tool_ids,
            "title": "靶向测序分析",
            "table_title": table_title,
            "table_subtitle": table_subtitle,
            "table_badge": table_badge,
            "description": f"纳米孔靶向测序 {classifier_label} 分析结果",
            "status": {"state": "completed", "label": "分析完成", "detail": "已生成病原体组成饼图和检测报告。"},
            "parameters": [{"label": "执行 ID", "value": normalized_id}],
            "summary": summary,
            "columns": columns,
            "rows": rows,
            "artifacts": artifacts,
            "charts": charts,
            "chart": {
                "type": "pie",
                "title": "病原体组成",
                "data": chart_data.get("data", []),
            },
        }

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
            # 尝试从远程下载
            remote_base = pm.current_project.remote_base
            remote_blast = f"{remote_base}/intermediate/{sample_id}/blastn_{blast_exec_id}/{sample_id}_blast.tsv"
            ssh = self._get_ssh_service()
            if ssh and getattr(ssh, "is_connected", False):
                try:
                    results_dir.mkdir(parents=True, exist_ok=True)
                    ssh.download(remote_blast, str(blast_tsv))
                except Exception:
                    pass

        if not blast_tsv.exists():
            return None

        return BlastResultParser.parse(str(blast_tsv))
