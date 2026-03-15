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
import json
import logging
import shlex
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

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
                    "name": "引物设计",
                    "badge": "",
                    "description": "面向 Linux 命令行引物设计流程的结果查看与执行入口。",
                    "status": "active",
                },
                {
                    "id": "sequence_alignment",
                    "name": "靶向分析",
                    "badge": "",
                    "description": "按同一工作台布局接入靶向分析能力。",
                    "status": "placeholder",
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
                    "title": "多病原体引物设计",
                    "description": "上传或选择待分析序列后，在 Linux 端执行引物设计流程，并在此查看推荐结果。",
                    "status": {
                        "state": "ready",
                        "label": "结果已就绪",
                        "detail": "支持查看推荐结果，并可继续接入远程任务执行链路。",
                    },
                    "parameters": [
                        {"label": "输入序列", "value": "FASTA / FNA 序列集合"},
                        {"label": "运行模式", "value": "quick / advanced"},
                        {"label": "候选产物长度", "value": "100-300 bp"},
                        {"label": "Tm 范围", "value": "57-63 ℃"},
                        {"label": "GC 范围", "value": "30-70 %"},
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
                        "primer_result_final_2.txt（首选展示）",
                        "primer_result_final.txt",
                        "dimer_score.txt",
                        "运行日志 / 原始结果包",
                    ],
                }
            },
        }

    @staticmethod
    def parse_primer_result_text(content: str) -> list[dict[str, str]]:
        rows: list[dict[str, str]] = []
        for line in content.splitlines():
            parts = line.strip().split("\t")
            if len(parts) < 6:
                continue
            rows.append(
                {
                    "pathogen": parts[0],
                    "region_id": parts[1],
                    "forward_primer": parts[2],
                    "reverse_primer": parts[3],
                    "position": parts[4],
                    "amplicon": parts[5],
                }
            )
        return rows

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
        if registry is None:
            return ""

        for item in registry.find_by_execution(execution_id):
            if Path(item.file_path).name == basename:
                return item.file_path
        return ""

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

    def get_live_primer_design_view(self) -> dict | None:
        base = copy.deepcopy(self.base_integrated_workbench_config()["views"]["primer_design"])
        execution = self.find_latest_completed_execution(list(base.get("tool_ids", [])))
        if not execution:
            return None

        final_path = self.find_registered_output(execution["execution_id"], "primer_result_final_2.txt")
        if not final_path:
            return None

        rows = self.parse_primer_result_text(self.read_remote_file(final_path))
        if not rows:
            return None

        output_dir = str(Path(final_path).parent).replace("\\", "/")
        all_candidates_count = self.count_remote_lines(f"{output_dir}/primer_result.txt") or len(rows)
        filtered_count = self.count_remote_lines(f"{output_dir}/primer_result_final.txt") or len(rows)
        dimer_count = self.count_remote_lines(f"{output_dir}/dimer_score.txt") or len(rows)
        params = self.safe_json_loads(execution.get("parameters") or "")
        mode = params.get("mode", "quick")
        ts = execution.get("completed_at") or execution.get("created_at") or time.time()

        base["description"] = (
            f"最新结果来自样本 {execution.get('sample_name') or execution.get('sample_id') or '-'}，"
            f"执行 ID：{execution['execution_id']}。"
        )
        base["status"] = {
            "state": "completed",
            "label": "已加载最新结果",
            "detail": f"完成时间：{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(ts))} · 模式：{mode}",
        }
        base["parameters"] = [
            {"label": "样本", "value": execution.get("sample_name") or execution.get("sample_id") or "-"},
            {"label": "工具 ID", "value": execution.get("tool_id") or "primer_design"},
            {"label": "运行模式", "value": str(mode)},
            {"label": "执行 ID", "value": execution["execution_id"]},
            {"label": "输出目录", "value": output_dir},
        ]
        base["summary"] = [
            {"label": "目标病原体", "value": str(len(rows)), "tone": "primary"},
            {"label": "候选引物对", "value": str(all_candidates_count), "tone": "info"},
            {"label": "通过二聚体过滤", "value": str(filtered_count), "tone": "success"},
            {"label": "二聚体分析记录", "value": str(dimer_count), "tone": "accent"},
        ]
        base["rows"] = rows
        base["artifacts"] = [
            f"{output_dir}/primer_result_final_2.txt",
            f"{output_dir}/primer_result_final.txt",
            f"{output_dir}/primer_result.txt",
            f"{output_dir}/dimer_score.txt",
        ]
        base["remote_result_dir"] = output_dir
        return base

    def build_primer_view_from_result_dir(self, remote_result_dir: str) -> dict | None:
        base = copy.deepcopy(self.base_integrated_workbench_config()["views"]["primer_design"])
        normalized_dir = (remote_result_dir or "").strip().rstrip("/")
        if not normalized_dir:
            return None

        final_path = f"{normalized_dir}/primer_result_final_2.txt"
        rows = self.parse_primer_result_text(self.read_remote_file(final_path))
        if not rows:
            return None

        all_candidates_count = self.count_remote_lines(f"{normalized_dir}/primer_result.txt") or len(rows)
        filtered_count = self.count_remote_lines(f"{normalized_dir}/primer_result_final.txt") or len(rows)
        dimer_count = self.count_remote_lines(f"{normalized_dir}/dimer_score.txt") or len(rows)

        base["description"] = f"当前结果来自远程目录：{normalized_dir}"
        base["status"] = {
            "state": "completed",
            "label": "已加载远程结果",
            "detail": "直接从服务器结果目录读取，并同步载入主结果文件。",
        }
        base["parameters"] = [
            {"label": "结果目录", "value": normalized_dir},
            {"label": "结果来源", "value": "远程目录直接读取"},
            {"label": "主文件", "value": "primer_result_final_2.txt"},
        ]
        base["summary"] = [
            {"label": "目标病原体", "value": str(len(rows)), "tone": "primary"},
            {"label": "候选引物对", "value": str(all_candidates_count), "tone": "info"},
            {"label": "通过二聚体过滤", "value": str(filtered_count), "tone": "success"},
            {"label": "二聚体分析记录", "value": str(dimer_count), "tone": "accent"},
        ]
        base["rows"] = rows
        base["artifacts"] = [
            f"{normalized_dir}/primer_result_final_2.txt",
            f"{normalized_dir}/primer_result_final.txt",
            f"{normalized_dir}/primer_result.txt",
            f"{normalized_dir}/dimer_score.txt",
        ]
        base["remote_result_dir"] = normalized_dir
        return base

    def get_primer_view_for_execution(self, execution_id: str) -> dict | None:
        normalized_execution_id = str(execution_id or "").strip()
        if not normalized_execution_id:
            return None

        final_path = self.find_registered_output(normalized_execution_id, "primer_result_final_2.txt")
        if final_path:
            return self.build_primer_view_from_result_dir(str(Path(final_path).parent).replace("\\", "/"))

        pm = self._get_project_manager()
        if pm is None or pm.current_project is None:
            return None

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
        return self.build_primer_view_from_result_dir(remote_dir)

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
            or current_remote_base == "/h2ometa"
            or current_remote_base.startswith("/h2ometa/")
            or current_remote_base == "~/h2ometa"
            or current_remote_base.startswith("~/h2ometa/")
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

        sample_id = self.get_latest_sample_id(pm)
        if sample_id:
            return sample_id

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

        return registry.add_sample(sample_name, source="detection_page")

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
            local_path = str(params.get(name, "")).strip()

            if not local_path:
                if required:
                    raise ValueError(f"缺少必需输入: {name}")
                continue

            data_id = importer.import_file(
                local_path=local_path,
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
            cursor = db.cursor()
            cursor.execute(
                """
                SELECT execution_id, sample_id, tool_id, status,
                       created_at, completed_at, error
                FROM executions
                ORDER BY created_at DESC
                LIMIT 50
                """
            )
            return [
                {
                    "execution_id": row[0],
                    "sample_id": row[1],
                    "tool_id": row[2],
                    "status": row[3],
                    "created_at": row[4],
                    "completed_at": row[5],
                    "error": row[6],
                }
                for row in cursor.fetchall()
            ]
        except Exception:
            logger.exception("Failed to get execution history")
            return []

    def get_integrated_workbench_config(self) -> dict:
        config = self.base_integrated_workbench_config()
        live_primer_view = self.get_live_primer_design_view()
        if live_primer_view is not None:
            config["views"]["primer_design"] = live_primer_view
        else:
            default_remote_view = self.build_primer_view_from_result_dir(self.get_default_primer_result_dir())
            if default_remote_view is not None:
                default_remote_view["status"] = {
                    "state": "completed",
                    "label": "已加载默认远程结果",
                    "detail": "未找到历史执行记录，已自动读取服务器默认 primer 结果目录。",
                }
                config["views"]["primer_design"] = default_remote_view
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
