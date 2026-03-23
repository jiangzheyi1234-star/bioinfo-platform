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
import datetime
import hashlib
import json
import logging
import shlex
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

from core.data.execution_query_service import ExecutionQueryService

if TYPE_CHECKING:
    from core.plugins.plugin_registry import PluginRegistry
    from core.service_locator import ServiceLocator

logger = logging.getLogger(__name__)


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
        rows: list[dict[str, str]] = []
        for line in content.splitlines():
            parts = line.strip().split("\t")
            if len(parts) < 6:
                continue
            if parts[0].lower() == "pathogen":
                continue
            if len(parts) >= 10:
                position = parts[8]
                amplicon = parts[9]
            else:
                position = parts[4]
                amplicon = parts[5]
            rows.append(
                {
                    "pathogen": parts[0],
                    "region_id": parts[1],
                    "forward_primer": parts[2],
                    "reverse_primer": parts[3],
                    "position": position,
                    "amplicon": amplicon,
                }
            )
        return rows

    @staticmethod
    def parse_multiplex_result_text(content: str) -> list[dict[str, str]]:
        rows: list[dict[str, str]] = []
        for line in content.splitlines():
            parts = line.strip().split("\t")
            if len(parts) < 4:
                continue
            if parts[0].lower() == "pathogen":
                continue
            if len(parts) <= 10:
                rows.append(
                    {
                        "pathogen": parts[0],
                        "region_id": parts[1],
                        "forward_primer": parts[2],
                        "reverse_primer": parts[3],
                        "tm_f": parts[4] if len(parts) > 4 else "",
                        "tm_r": parts[5] if len(parts) > 5 else "",
                        "gc_f": parts[6] if len(parts) > 6 else "",
                        "gc_r": parts[7] if len(parts) > 7 else "",
                        "amplicon_length": parts[8] if len(parts) > 8 else "",
                        "target_sequence": "",
                        "conservation_score": "",
                        "specificity_score": "",
                        "amplicon_seq": "",
                        "pool_id": "",
                        "pool_dimer_score": parts[9] if len(parts) > 9 else (parts[5] if len(parts) > 5 else ""),
                        "pool_score": parts[9] if len(parts) > 9 else (parts[5] if len(parts) > 5 else ""),
                    }
                )
                continue
            rows.append(
                {
                    "pathogen": parts[0],
                    "region_id": parts[1],
                    "forward_primer": parts[2],
                    "reverse_primer": parts[3],
                    "tm_f": parts[4] if len(parts) > 4 else "",
                    "tm_r": parts[5] if len(parts) > 5 else "",
                    "gc_f": parts[6] if len(parts) > 6 else "",
                    "gc_r": parts[7] if len(parts) > 7 else "",
                    "amplicon_length": parts[8] if len(parts) > 8 else (parts[4] if len(parts) > 4 else ""),
                    "target_sequence": parts[9] if len(parts) > 9 else "",
                    "conservation_score": parts[10] if len(parts) > 10 else "",
                    "specificity_score": parts[11] if len(parts) > 11 else "",
                    "amplicon_seq": parts[12] if len(parts) > 12 else "",
                    "pool_id": parts[13] if len(parts) > 13 else "",
                    "pool_dimer_score": parts[14] if len(parts) > 14 else (parts[9] if len(parts) > 9 else ""),
                    "pool_score": parts[14] if len(parts) > 14 else (parts[9] if len(parts) > 9 else (parts[5] if len(parts) > 5 else "")),
                    "pool_status": parts[15] if len(parts) > 15 else "",
                }
            )
        return rows

    @staticmethod
    def _build_multiplex_columns(rows: list[dict[str, str]]) -> list[dict[str, str]]:
        """Hide multiplex columns that are empty across all rows."""
        base_columns = [
            {"key": "pathogen", "label": "Pathogen"},
            {"key": "region_id", "label": "Region ID"},
            {"key": "forward_primer", "label": "Forward Primer"},
            {"key": "reverse_primer", "label": "Reverse Primer"},
            {"key": "amplicon_length", "label": "Amplicon Length"},
        ]
        optional_columns = [
            {"key": "target_sequence", "label": "Target Sequence"},
            {"key": "conservation_score", "label": "Conservation Score"},
            {"key": "specificity_score", "label": "Specificity Score"},
            {"key": "pool_dimer_score", "label": "Pool Dimer Score"},
            {"key": "pool_status", "label": "Pool Status"},
        ]

        if not rows:
            return base_columns + [{"key": "pool_dimer_score", "label": "Pool Dimer Score"}]

        visible_optional: list[dict[str, str]] = []
        for col in optional_columns:
            key = col["key"]
            if any(str(row.get(key, "")).strip() for row in rows):
                visible_optional.append(col)
        return base_columns + visible_optional

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
        project_dir = self._get_current_project_dir()
        if project_dir is None or not cache_key:
            return None
        return project_dir / "results" / cache_key / self._manifest_name

    def _load_manifest(self, cache_key: str) -> dict | None:
        manifest_path = self._manifest_path(cache_key)
        if manifest_path is None or not manifest_path.exists():
            return None
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            return payload if isinstance(payload, dict) else None
        except Exception:
            logger.exception("读取结果文件清单失败: %s", manifest_path)
            return None

    def _normalize_artifacts(self, artifacts: list[dict] | None) -> list[dict]:
        normalized: list[dict] = []
        for item in artifacts or []:
            if not isinstance(item, dict):
                continue
            local_path = str(item.get("local_path") or "").strip()
            available = bool(item.get("available"))
            if local_path:
                available = Path(local_path).exists()
            normalized.append(
                {
                    "name": str(item.get("name") or "").strip(),
                    "remote_path": str(item.get("remote_path") or "").strip(),
                    "local_path": local_path,
                    "available": available,
                    "error": str(item.get("error") or "").strip(),
                }
            )
        return normalized

    def _artifact_by_name(self, artifacts: list[dict], name: str) -> dict | None:
        for artifact in artifacts:
            if artifact.get("name") == name:
                return artifact
        return None

    def _read_local_artifact_text(self, artifacts: list[dict], name: str) -> str:
        artifact = self._artifact_by_name(artifacts, name)
        if artifact is None:
            return ""
        local_path = str(artifact.get("local_path") or "").strip()
        if not local_path:
            return ""
        path = Path(local_path)
        if not path.exists():
            return ""
        try:
            return path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            logger.exception("读取本地结果文件失败: %s", local_path)
            return ""

    def _count_local_artifact_lines(self, artifacts: list[dict], name: str) -> int | None:
        content = self._read_local_artifact_text(artifacts, name)
        if not content:
            return None
        return len([line for line in content.splitlines() if line.strip()])

    def _remote_cache_key(self, tool_id: str, remote_result_dir: str) -> str:
        digest = hashlib.sha1(remote_result_dir.encode("utf-8")).hexdigest()[:12]
        return f"{tool_id}_{digest}"

    def _remote_file_exists(self, ssh: Any, remote_path: str) -> bool:
        quoted_path = shlex.quote(str(remote_path or ""))
        if not quoted_path:
            return False
        try:
            rc, _, _ = ssh.run(f"test -f {quoted_path}", timeout=10)
            return rc == 0
        except Exception:
            logger.debug("检查远端结果文件是否存在失败: %s", remote_path, exc_info=True)
            return False

    def _cache_remote_artifacts(self, tool_id: str, remote_result_dir: str) -> list[dict]:
        normalized_dir = (remote_result_dir or "").strip().rstrip("/")
        if not normalized_dir:
            return []

        cache_key = self._remote_cache_key(tool_id, normalized_dir)
        manifest = self._load_manifest(cache_key)
        if manifest:
            return self._normalize_artifacts(manifest.get("artifacts"))

        ssh = self._get_ssh_service()
        manifest_path = self._manifest_path(cache_key)
        if ssh is None or not getattr(ssh, "is_connected", False) or manifest_path is None:
            return []

        results_dir = manifest_path.parent
        results_dir.mkdir(parents=True, exist_ok=True)
        artifacts: list[dict] = []
        for name in self._result_artifact_names.get(tool_id, []):
            remote_path = f"{normalized_dir}/{name}"
            local_path = results_dir / name
            available = False
            error = ""
            try:
                if self._remote_file_exists(ssh, remote_path):
                    ssh.download(remote_path, str(local_path))
                    available = local_path.exists()
                else:
                    error = "remote_file_not_found"
                    logger.debug("远端结果文件不存在，跳过缓存: %s", remote_path)
            except Exception as exc:
                error = str(exc)
                logger.warning("缓存远端结果文件失败: %s (%s)", remote_path, exc)
            item = {
                "name": name,
                "remote_path": remote_path,
                "local_path": str(local_path),
                "available": available,
            }
            if error:
                item["error"] = error
            artifacts.append(item)

        try:
            manifest_path.write_text(
                json.dumps(
                    {
                        "execution_id": cache_key,
                        "tool_id": tool_id,
                        "output_dir": normalized_dir,
                        "artifacts": artifacts,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
        except OSError:
            logger.exception("写入远端结果缓存清单失败: %s", manifest_path)
        return self._normalize_artifacts(artifacts)

    def list_local_execution_artifacts(self, execution_id: str) -> list[dict]:
        manifest = self._load_manifest(str(execution_id or "").strip())
        if manifest:
            return self._normalize_artifacts(manifest.get("artifacts"))
        return []

    def _persist_execution_artifacts(
        self,
        execution_id: str,
        tool_id: str,
        output_dir: str,
        artifacts: list[dict],
    ) -> list[dict]:
        """Persist downloaded artifacts under results/<execution_id>/ and write manifest."""
        normalized_execution_id = str(execution_id or "").strip()
        if not normalized_execution_id:
            return self._normalize_artifacts(artifacts)

        results_dir = self._execution_results_dir(normalized_execution_id)
        if results_dir is None:
            return self._normalize_artifacts(artifacts)
        results_dir.mkdir(parents=True, exist_ok=True)

        persisted: list[dict] = []
        for item in self._normalize_artifacts(artifacts):
            name = str(item.get("name") or "").strip()
            local_path = str(item.get("local_path") or "").strip()
            available = bool(item.get("available"))
            copied_path = ""
            error = str(item.get("error") or "").strip()
            if name and local_path and available and Path(local_path).exists():
                src = Path(local_path)
                dst = results_dir / name
                try:
                    if src.resolve() != dst.resolve():
                        shutil.copy2(src, dst)
                    copied_path = str(dst)
                except Exception as exc:
                    logger.warning("Failed to copy artifact to execution dir: %s -> %s (%s)", src, dst, exc)
                    error = error or str(exc)
                    copied_path = local_path
            else:
                copied_path = local_path

            persisted_item = {
                "name": name,
                "remote_path": str(item.get("remote_path") or "").strip(),
                "local_path": copied_path,
                "available": bool(copied_path) and Path(copied_path).exists(),
            }
            if error:
                persisted_item["error"] = error
            persisted.append(persisted_item)

        manifest_path = results_dir / self._manifest_name
        try:
            manifest_path.write_text(
                json.dumps(
                    {
                        "execution_id": normalized_execution_id,
                        "tool_id": tool_id,
                        "output_dir": output_dir,
                        "artifacts": persisted,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
        except OSError:
            logger.exception("Failed to write execution artifacts manifest: %s", manifest_path)

        return self._normalize_artifacts(persisted)

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
        base = copy.deepcopy(self.base_integrated_workbench_config()["views"]["primer_design"])
        rows = self.parse_primer_result_text(self._read_local_artifact_text(artifacts, "primer_result_final_2.txt"))
        if not rows:
            return None

        all_candidates_count = self._count_local_artifact_lines(artifacts, "primer_result.txt") or len(rows)
        filtered_count = self._count_local_artifact_lines(artifacts, "primer_result_final.txt") or len(rows)
        dimer_count = self._count_local_artifact_lines(artifacts, "dimer_score.txt") or len(rows)
        base["description"] = description
        base["status"] = status
        base["parameters"] = parameters
        base["summary"] = [
            {"label": "目标病原体", "value": str(len(rows)), "tone": "primary"},
            {"label": "候选引物对", "value": str(all_candidates_count), "tone": "info"},
            {"label": "通过二聚体过滤", "value": str(filtered_count), "tone": "success"},
            {"label": "二聚体分析记录", "value": str(dimer_count), "tone": "accent"},
        ]
        base["rows"] = rows
        base["artifacts"] = artifacts
        base["remote_result_dir"] = remote_result_dir
        return base

    def _build_multiplex_view_from_artifacts(
        self,
        artifacts: list[dict],
        remote_result_dir: str,
        description: str,
        status: dict,
        parameters: list[dict],
    ) -> dict | None:
        rows = self.parse_multiplex_result_text(self._read_local_artifact_text(artifacts, "multiplex_panel.txt"))
        if not rows:
            return None

        # Separate valid primers from no_candidate / suboptimal entries
        valid_rows = [r for r in rows if r.get("pool_id") != "no_candidate" and r.get("forward_primer", "").strip()]
        no_candidate_rows = [r for r in rows if r.get("pool_id") == "no_candidate" or not r.get("forward_primer", "").strip()]
        suboptimal_rows = [r for r in valid_rows if r.get("pool_status") == "suboptimal"]
        optimal_rows = [r for r in valid_rows if r.get("pool_status") != "suboptimal"]

        synthesis_count = self._count_local_artifact_lines(artifacts, "synthesis_order.txt")
        optimization_count = self._count_local_artifact_lines(artifacts, "optimization_log.txt")
        optimization_rounds = max((optimization_count or 1) - 1, 0)
        parameter_items = list(parameters)
        parameter_items.append(
            {
                "label": "优化轮次",
                "value": str(optimization_rounds),
                "description": "指算法为消解引物冲突并满足约束而进行的迭代次数；轮次越多表示优化过程越复杂，不代表结果更差。",
            }
        )

        # Summary: 4 cards showing actionable info
        total_pathogens = len(rows)
        coverage_str = f"{len(valid_rows)}/{total_pathogens}"
        # tone for coverage: success if full, warning if partial
        coverage_tone = "success" if len(valid_rows) == total_pathogens else "warning"

        # Compute Tm range and recommended annealing temperature from valid primers
        all_tms: list[float] = []
        all_amplicon_lengths: list[int] = []
        for r in valid_rows:
            for k in ("tm_f", "tm_r"):
                try:
                    all_tms.append(float(r.get(k) or 0))
                except ValueError:
                    pass
            try:
                al = int(r.get("amplicon_length") or 0)
                if al > 0:
                    all_amplicon_lengths.append(al)
            except ValueError:
                pass

        summary = [
            {"label": "入池病原体", "value": coverage_str, "tone": coverage_tone},
            {"label": "订单条目", "value": str(max((synthesis_count or 1) - 1, 0)), "tone": "primary"},
        ]
        if suboptimal_rows:
            summary.append({"label": "需验证", "value": str(len(suboptimal_rows)), "tone": "warning"})
        else:
            summary.append({"label": "质量", "value": "全部 optimal", "tone": "success"})

        # 4th card: Tm range — directly tells researcher what annealing T to use
        if all_tms:
            tm_min = min(all_tms)
            tm_max = max(all_tms)
            tm_mean = sum(all_tms) / len(all_tms)
            summary.append({"label": "Tm 范围", "value": f"{tm_min:.1f}-{tm_max:.1f}℃", "tone": "accent"})
        else:
            summary.append({"label": "优化轮次", "value": str(optimization_rounds), "tone": "accent"})

        # Extra metrics appended to parameters (visible in expanded detail)
        if all_tms:
            parameter_items.append({
                "label": "推荐退火温度",
                "value": f"{tm_mean - 5:.1f}℃",
                "description": f"基于池内引物平均 Tm ({tm_mean:.1f}℃) 减 5℃ 计算。实际需根据聚合酶和缓冲体系微调。",
            })
        if all_amplicon_lengths:
            parameter_items.append({
                "label": "扩增子范围",
                "value": f"{min(all_amplicon_lengths)}-{max(all_amplicon_lengths)} bp",
                "description": "池内扩增子长度的最小-最大范围。差异越大越利于凝胶电泳区分。",
            })
        if suboptimal_rows:
            subopt_names = ", ".join(r.get("pathogen", "") for r in suboptimal_rows[:5])
            suffix = f" 等 {len(suboptimal_rows)} 个" if len(suboptimal_rows) > 5 else ""
            parameter_items.append({
                "label": "需实验验证",
                "value": subopt_names + suffix,
                "description": "这些病原体的引物在池优化中存在轻微冲突（二聚体/Tm偏差/长度重叠），建议通过调整退火温度或引物浓度在实验端验证。",
            })

        # Build amplicon length bar chart for visual assessment
        chart_data = None
        if valid_rows:
            chart_items = []
            for r in rows:
                pathogen = r.get("pathogen", "")
                try:
                    amp_len = int(r.get("amplicon_length") or 0)
                except ValueError:
                    amp_len = 0
                row_status = r.get("pool_status", "optimal")
                if r.get("pool_id") == "no_candidate" or not r.get("forward_primer", "").strip():
                    row_status = "no_candidate"
                    amp_len = 0
                chart_items.append({
                    "name": pathogen,
                    "value": amp_len,
                    "status": row_status,
                    "region_id": r.get("region_id", ""),
                })
            chart_data = {
                "type": "bar",
                "title": "扩增子长度分布",
                "data": chart_items,
            }

        return {
            "tool_ids": ["multiplex_primer_panel"],
            "title": "多重引物池设计",
            "description": description,
            "status": status,
            "parameters": parameter_items,
            "summary": summary,
            "columns": self._build_multiplex_columns(rows),
            "rows": rows,
            "chart": chart_data,
            "artifacts": artifacts,
            "remote_result_dir": remote_result_dir,
        }

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
            self.validate_required_databases(descriptor, database_paths)

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
        try:
            from config import get_config

            cfg_databases = get_config().get("databases", {})

            if not self._plugin_registry:
                return {}

            desc = descriptor or self._plugin_registry.get_descriptor(tool_id)
            db_decls = desc.get("databases", [])

            paths: dict = {}
            for decl in db_decls:
                var_name = decl.get("param_name", decl.get("name", ""))
                db_id = decl.get("id", "")

                if not var_name:
                    continue

                resolved_path = ""
                for cfg_key, cfg_path in cfg_databases.items():
                    if not cfg_path:
                        continue
                    if db_id == cfg_key or db_id.startswith(cfg_key):
                        resolved_path = cfg_path
                        break

                if not resolved_path:
                    for cfg_key, cfg_path in cfg_databases.items():
                        if not cfg_path:
                            continue
                        if tool_id == cfg_key or tool_id.startswith(cfg_key):
                            resolved_path = cfg_path
                            break

                if resolved_path:
                    paths[var_name] = resolved_path
                    logger.debug(
                        "数据库路径已匹配: tool=%s, id=%s → %s=%s",
                        tool_id,
                        db_id,
                        var_name,
                        resolved_path,
                    )
                else:
                    logger.debug("数据库路径未配置: tool=%s, id=%s, var=%s", tool_id, db_id, var_name)

            return paths
        except Exception:
            logger.exception("构建数据库路径失败 (tool=%s)", tool_id)
            return {}

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
            var_name = str(decl.get("param_name", decl.get("name", ""))).strip()
            legacy_name = str(decl.get("name", "")).strip()
            if not var_name:
                continue

            value = str(params.get(var_name, "")).strip()
            if not value and legacy_name:
                value = str(params.get(legacy_name, "")).strip()
            if value:
                db_paths[var_name] = value

        return db_paths

    @staticmethod
    def validate_required_databases(descriptor: dict, database_paths: dict) -> None:
        for decl in descriptor.get("databases", []):
            if not bool(decl.get("required", False)):
                continue
            var_name = str(decl.get("param_name", decl.get("name", ""))).strip()
            if var_name and not str(database_paths.get(var_name, "")).strip():
                raise ValueError(f"缺少必需数据库路径: {var_name}")

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

        # 未知样品检测 — 复用靶向测序的结果加载逻辑
        live_detection_view = self._get_live_unknown_sample_detection_view()
        if live_detection_view is not None:
            views["unknown_sample_detection"] = live_detection_view

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
        view = self._build_targeted_seq_view_for_execution(execution_id)
        if view is None:
            return {
                "status": "error",
                "message": "未能从该任务读取靶向测序结果，请确认任务已完成且 kreport 文件已生成。",
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

        row = pm.db.execute(
            """
            SELECT execution_id, sample_id, tool_id, status, created_at, completed_at, error
            FROM executions
            WHERE execution_id = ? AND archived_at IS NULL
            LIMIT 1
            """,
            (execution_id,),
        ).fetchone()
        if row is None:
            return {"status": "error", "message": "未找到该任务记录"}

        sample_id = row["sample_id"]
        tool_id = row["tool_id"]
        remote_base = str(pm.current_project.remote_base or "").strip()
        if not remote_base:
            remote_base = f"~/.h2ometa/projects/{pm.current_project.project_id}"
        task_dir = f"{remote_base}/intermediate/{sample_id}/{tool_id}_{execution_id}"
        job_id = f"h2o_{execution_id}"

        data = {
            "execution_id": execution_id,
            "tool_id": tool_id,
            "sample_id": sample_id,
            "local_status": row["status"],
            "created_at": row["created_at"],
            "completed_at": row["completed_at"],
            "local_error": row["error"] or "",
            "task_dir": task_dir,
            "ssh_connected": False,
            "screen_running": None,
            "remote_status": "",
            "exit_code": "",
            "heartbeat": "",
            "heartbeat_age_sec": None,
            "log_tail": "",
        }

        ssh = self._get_ssh_service()
        if ssh is None or not getattr(ssh, "is_connected", False):
            return {"status": "ok", "data": data, "message": "SSH 未连接，仅显示本地状态"}

        data["ssh_connected"] = True
        status_cmd = (
            "{ "
            "echo __STATUS__; cat " + shlex.quote(f"{task_dir}/status.txt") + " 2>/dev/null || true; "
            "echo __EXIT__; cat " + shlex.quote(f"{task_dir}/exit_code.txt") + " 2>/dev/null || true; "
            "echo __HEARTBEAT__; cat " + shlex.quote(f"{task_dir}/heartbeat.txt") + " 2>/dev/null || true; "
            "}"
        )
        try:
            rc, out, _ = ssh.run(status_cmd, timeout=10)
            if rc == 0:
                parsed = self._parse_remote_status_block(out)
                data["remote_status"] = parsed.get("status", "")
                data["exit_code"] = parsed.get("exit", "")
                data["heartbeat"] = parsed.get("heartbeat", "")
        except Exception:
            logger.debug("Failed reading status block for %s", execution_id, exc_info=True)

        if data["heartbeat"]:
            try:
                hb = int(data["heartbeat"])
                data["heartbeat_age_sec"] = max(0, int(time.time()) - hb)
            except Exception:
                data["heartbeat_age_sec"] = None

        try:
            rc, _, _ = ssh.run(
                f"screen -ls | grep -Fq -- {shlex.quote(job_id)}",
                timeout=10,
            )
            data["screen_running"] = rc == 0
        except Exception:
            logger.debug("Failed checking screen status for %s", execution_id, exc_info=True)

        try:
            rc, out, _ = ssh.run(
                f"tail -n 20 {shlex.quote(f'{task_dir}/task.log')} 2>/dev/null",
                timeout=10,
            )
            if rc == 0:
                data["log_tail"] = out
        except Exception:
            logger.debug("Failed reading task.log tail for %s", execution_id, exc_info=True)

        return {"status": "ok", "data": data}

    @staticmethod
    def _parse_remote_status_block(output: str) -> dict[str, str]:
        result = {"status": "", "exit": "", "heartbeat": ""}
        current = ""
        bucket: dict[str, list[str]] = {"status": [], "exit": [], "heartbeat": []}
        marker_map = {
            "__STATUS__": "status",
            "__EXIT__": "exit",
            "__HEARTBEAT__": "heartbeat",
        }
        for raw in (output or "").splitlines():
            line = raw.strip("\r\n")
            marker = marker_map.get(line.strip())
            if marker is not None:
                current = marker
                continue
            if current:
                bucket[current].append(line)
        for key in ("status", "exit", "heartbeat"):
            text = "\n".join(bucket[key]).strip()
            if text:
                result[key] = text.splitlines()[0].strip()
        return result

    def _get_live_unknown_sample_detection_view(self) -> dict | None:
        """查找最新的 unknown_sample_detection 已完成执行，构建未知样品检测 view。

        优先匹配 tool_id='unknown_sample_detection'（一键管线），
        兼容旧版 centrifuge/kraken2 + workflow=unknown_detection 标记。
        """
        pm = self._get_project_manager()
        if pm is None or pm.current_project is None:
            return None
        try:
            rows = pm.db.execute(
                "SELECT execution_id, tool_id, parameters FROM executions "
                "WHERE tool_id IN ('unknown_sample_detection', 'centrifuge', 'kraken2') "
                "AND status = 'completed' "
                "ORDER BY rowid DESC",
            ).fetchall()
        except Exception:
            return None

        # 优先找 unknown_sample_detection 工具的执行
        target_eid = None
        for r in (rows or []):
            if r["tool_id"] == "unknown_sample_detection":
                target_eid = r["execution_id"]
                break

        # 兼容旧版：查找带 workflow=unknown_detection 标记的 centrifuge/kraken2 执行
        if target_eid is None:
            import json as _json
            for r in (rows or []):
                try:
                    params = _json.loads(r["parameters"] or "{}")
                except Exception:
                    continue
                if params.get("workflow") == "unknown_detection":
                    target_eid = r["execution_id"]
                    break

        if target_eid is None:
            return None

        view = self._build_targeted_seq_view_for_execution(target_eid)
        if view is None:
            return None

        # 覆盖标题和描述，适配 mNGS 未知样品检测
        view["title"] = "未知样品病原体检测 (mNGS)"
        view["description"] = "fastp 质控 → hostile 去宿主 → Centrifuge 分类 → BLAST 补充鉴定 → 合并结果"
        view["table_title"] = "检出微生物列表"
        view["table_subtitle"] = "按 Reads 数降序排列，包含多来源合并结果。"
        view["tool_ids"] = ["unknown_sample_detection"]

        # 覆盖列定义为 mNGS 标准列
        view["columns"] = [
            {"key": "rank", "label": "#"},
            {"key": "name", "label": "微生物名称"},
            {"key": "category", "label": "类型"},
            {"key": "reads", "label": "Reads"},
            {"key": "rpm", "label": "RPM"},
            {"key": "percentage", "label": "相对丰度 (%)"},
            {"key": "source", "label": "检出来源"},
        ]

        # 为每行补充 mNGS 特有字段
        total_reads = 0
        try:
            for s in view.get("summary", []):
                if "Reads" in s.get("label", "") and s["value"] != "—":
                    total_reads = int(str(s["value"]).replace(",", "").split("(")[0].strip())
                    break
        except (ValueError, KeyError):
            pass

        classifier_name = "Centrifuge"
        for row_data in view.get("rows", []):
            if "rpm" not in row_data and total_reads > 0:
                try:
                    raw_reads = int(str(row_data.get("reads", "0")).replace(",", ""))
                    rpm = raw_reads / total_reads * 1_000_000
                    row_data["rpm"] = f"{rpm:,.1f}"
                except (ValueError, TypeError):
                    row_data["rpm"] = "—"
            elif "rpm" not in row_data:
                row_data["rpm"] = "—"
            if "category" not in row_data:
                row_data["category"] = "—"
            if "source" not in row_data:
                row_data["source"] = classifier_name

        return view

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

    def _build_fastp_view_for_execution(self, execution_id: str) -> dict | None:
        """从 fastp 已完成的 execution 构建 QC 结果 view，展示在未知样品检测卡片中。"""
        import json as _json

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

        local_json = results_dir / "fastp.json"
        if not local_json.exists():
            ssh = self._get_ssh_service()
            if ssh is None or not getattr(ssh, "is_connected", False):
                return None
            try:
                ssh.download(f"{remote_dir}/fastp.json", str(local_json))
            except Exception as exc:
                logger.warning("下载 fastp.json 失败: %s", exc)
                return None

        if not local_json.exists():
            return None

        try:
            with open(local_json, encoding="utf-8") as f:
                fastp_data = _json.load(f)
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

        view = {
            "tool_ids": ["fastp"],
            "title": "fastp 质控报告",
            "description": f"样品 {sample_id} 的 QC 质控统计。",
            "table_title": "质控过滤统计",
            "table_subtitle": "fastp 接头去除 + 低质量过滤详情。",
            "status": {
                "state": "completed",
                "label": "QC 完成",
                "detail": f"通过率 {pct_pass}，Q30 {q30_after:.1%}",
            },
            "parameters": [
                {"label": "输入", "value": f"双端 FASTQ ({total_before:,} reads)"},
                {"label": "输出", "value": f"清洁 reads ({total_after:,} reads)"},
                {"label": "工具", "value": "fastp"},
            ],
            "summary": [
                {"label": "原始 Reads", "value": f"{total_before:,}", "tone": "primary"},
                {"label": "通过 QC", "value": f"{total_after:,} ({pct_pass})", "tone": "success"},
                {"label": "Q30 (过滤后)", "value": f"{q30_after:.2%}", "tone": "info"},
                {"label": "GC 含量", "value": f"{gc_after:.2%}", "tone": "info"},
            ],
            "columns": [
                {"key": "metric", "label": "指标"},
                {"key": "before", "label": "过滤前"},
                {"key": "after", "label": "过滤后"},
            ],
            "rows": [
                {"metric": "总 Reads", "before": f"{total_before:,}", "after": f"{total_after:,}"},
                {"metric": "Q30", "before": f"{q30_before:.2%}", "after": f"{q30_after:.2%}"},
                {"metric": "GC 含量", "before": f"{before.get('gc_content', 0):.2%}", "after": f"{gc_after:.2%}"},
                {"metric": "低质量 Reads", "before": "—", "after": f"{low_quality:,}"},
                {"metric": "过短 Reads", "before": "—", "after": f"{too_short:,}"},
                {"metric": "高 N Reads", "before": "—", "after": f"{too_many_n:,}"},
                {"metric": "通过率", "before": "—", "after": pct_pass},
            ],
            "artifacts": [
                {
                    "name": "fastp.json",
                    "remote_path": f"{remote_dir}/fastp.json",
                    "local_path": str(local_json),
                    "available": True,
                },
                {
                    "name": "fastp.html",
                    "remote_path": f"{remote_dir}/fastp.html",
                    "local_path": "",
                    "available": False,
                },
            ],
        }
        return view

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

        if not row or row["tool_id"] not in ("centrifuge", "kraken2", "unknown_sample_detection"):
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
        local_kreport = results_dir / kreport_name
        local_coverage_depth = results_dir / coverage_depth_name
        local_amplicon_perf = results_dir / amplicon_perf_name
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

        chart_data = ChartDataParser.parse_kreport(str(local_kreport))
        summary_data = ChartDataParser.parse_kreport_summary(str(local_kreport))
        coverage_chart = {"type": "coverage_depth", "title": "Coverage Depth", "data": []}
        amplicon_chart = {"type": "amplicon_performance", "title": "Amplicon Performance", "data": []}
        if local_coverage_depth.exists():
            coverage_chart = ChartDataParser.parse_coverage_depth(str(local_coverage_depth))
        if local_amplicon_perf.exists():
            amplicon_chart = ChartDataParser.parse_amplicon_performance(str(local_amplicon_perf))

        charts = [
            {
                "type": "pie",
                "title": "病原体组成",
                "data": chart_data.get("data", []),
            },
            {
                "type": "abundance_bar",
                "title": "物种丰度 (Top 20)",
                "data": chart_data.get("data", [])[:20],
            },
        ]
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
            "table_title": "病原体物种组成",
            "table_subtitle": "基于 kreport 解析的物种组成，按丰度降序排列。",
            "description": f"纳米孔靶向测序 {classifier_label} 分析结果",
            "status": {"state": "completed", "label": "分析完成", "detail": "已生成病原体组成饼图和检测报告。"},
            "parameters": [{"label": "执行 ID", "value": normalized_id}],
            "summary": summary,
            "columns": [
                {"key": "rank", "label": "序号"},
                {"key": "name", "label": "病原体名称"},
                {"key": "reads", "label": "Reads 数"},
                {"key": "percentage", "label": "占比 (%)"},
            ],
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
