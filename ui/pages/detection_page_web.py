"""Detection page implemented with Qt WebEngine (with graceful fallback)."""

from __future__ import annotations

import copy
import json
import logging
import shlex
import time
from pathlib import Path

from PyQt6.QtCore import QObject, QUrl, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QFrame, QLabel, QVBoxLayout

from ui.qt_bootstrap import ensure_qt_webengine_ready
from ui.widgets import styles

logger = logging.getLogger(__name__)


class ToolBridge(QObject):
    """Bridge between Python and JavaScript via QWebChannel."""

    tool_selected = pyqtSignal(str, arguments=["tool_id"])

    def __init__(self, plugin_registry, main_window=None, web_view=None):
        super().__init__()
        self.plugin_registry = plugin_registry
        self.main_window = main_window
        self.web_view = web_view  # 用于 _send_run_result JS 回调

    @staticmethod
    def _base_integrated_workbench_config() -> dict:
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
    def _parse_primer_result_text(content: str) -> list[dict[str, str]]:
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

    def _get_service_locator(self):
        if self.main_window and hasattr(self.main_window, "service_locator"):
            return self.main_window.service_locator
        return None

    def _find_latest_completed_execution(self, tool_ids: list[str]) -> dict | None:
        sl = self._get_service_locator()
        if sl is None:
            return None

        pm = getattr(sl, "project_manager", None)
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

    def _find_registered_output(self, execution_id: str, basename: str) -> str:
        sl = self._get_service_locator()
        registry = getattr(sl, "data_registry", None) if sl is not None else None
        if registry is None:
            return ""

        for item in registry.find_by_execution(execution_id):
            if Path(item.file_path).name == basename:
                return item.file_path
        return ""

    def _read_remote_file(self, file_path: str) -> str:
        if not file_path:
            return ""

        sl = self._get_service_locator()
        ssh = getattr(sl, "ssh_service", None) if sl is not None else None
        if ssh is None or not getattr(ssh, "is_connected", False):
            return ""

        try:
            rc, out, _ = ssh.run(f"cat {shlex.quote(file_path)} 2>/dev/null", timeout=15)
            if rc == 0:
                return out
        except Exception:
            logger.exception("读取远端文件失败: %s", file_path)
        return ""

    def _count_remote_lines(self, file_path: str) -> int | None:
        if not file_path:
            return None

        sl = self._get_service_locator()
        ssh = getattr(sl, "ssh_service", None) if sl is not None else None
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
    def _safe_json_loads(raw: str) -> dict:
        if not raw:
            return {}
        try:
            data = json.loads(raw)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _get_default_primer_result_dir(self) -> str:
        default_root = ""

        try:
            from config import get_config

            runtime_cfg = get_config().get("runtime", {})
            configured_root = str(runtime_cfg.get("primer_result_root", "") or "").strip()
            if configured_root:
                default_root = configured_root.rstrip("/")
        except Exception:
            logger.debug("无法从配置读取 runtime.primer_result_root，回退到插件默认值")

        if self.plugin_registry is not None:
            try:
                desc = self.plugin_registry.get_descriptor("primer_design")
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

    def _get_live_primer_design_view(self) -> dict | None:
        base = copy.deepcopy(self._base_integrated_workbench_config()["views"]["primer_design"])
        execution = self._find_latest_completed_execution(list(base.get("tool_ids", [])))
        if not execution:
            return None

        final_path = self._find_registered_output(execution["execution_id"], "primer_result_final_2.txt")
        if not final_path:
            return None

        rows = self._parse_primer_result_text(self._read_remote_file(final_path))
        if not rows:
            return None

        output_dir = str(Path(final_path).parent).replace("\\", "/")
        all_candidates_count = self._count_remote_lines(f"{output_dir}/primer_result.txt") or len(rows)
        filtered_count = self._count_remote_lines(f"{output_dir}/primer_result_final.txt") or len(rows)
        dimer_count = self._count_remote_lines(f"{output_dir}/dimer_score.txt") or len(rows)
        params = self._safe_json_loads(execution.get("parameters") or "")
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

    def _build_primer_view_from_result_dir(self, remote_result_dir: str) -> dict | None:
        base = copy.deepcopy(self._base_integrated_workbench_config()["views"]["primer_design"])
        normalized_dir = (remote_result_dir or "").strip().rstrip("/")
        if not normalized_dir:
            return None

        final_path = f"{normalized_dir}/primer_result_final_2.txt"
        rows = self._parse_primer_result_text(self._read_remote_file(final_path))
        if not rows:
            return None

        all_candidates_count = self._count_remote_lines(f"{normalized_dir}/primer_result.txt") or len(rows)
        filtered_count = self._count_remote_lines(f"{normalized_dir}/primer_result_final.txt") or len(rows)
        dimer_count = self._count_remote_lines(f"{normalized_dir}/dimer_score.txt") or len(rows)

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

    @pyqtSlot(result=str)
    def get_tools(self) -> str:
        if not self.plugin_registry:
            logger.warning("PluginRegistry not initialized")
            return json.dumps([], ensure_ascii=False)

        tools: list[dict] = []
        try:
            for tool_id in self.plugin_registry.list_all_ids():
                desc = self.plugin_registry.get_descriptor(tool_id)
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

        return json.dumps(tools, ensure_ascii=False)

    @pyqtSlot(str, result=str)
    def get_tool_descriptor(self, tool_id: str) -> str:
        if not self.plugin_registry:
            logger.warning("PluginRegistry not initialized")
            return json.dumps({}, ensure_ascii=False)

        try:
            desc = self.plugin_registry.get_descriptor(tool_id)
            return json.dumps(desc, ensure_ascii=False)
        except Exception:
            logger.exception("Failed to get descriptor for %s", tool_id)
            return json.dumps({}, ensure_ascii=False)

    @pyqtSlot(str)
    def select_tool(self, tool_id: str):
        self.tool_selected.emit(tool_id)

    @pyqtSlot(str, result=str)
    def browse_file(self, input_id: str) -> str:
        from PyQt6.QtWidgets import QFileDialog

        parent = self.main_window if self.main_window else None
        file_path, _ = QFileDialog.getOpenFileName(parent, "选择文件", "", "所有文件 (*.*)")
        return file_path or ""

    @pyqtSlot(str, str)
    def run_tool(self, tool_id: str, params_json: str):
        """执行工具 — 真正调用 ToolEngine.execute()。"""
        try:
            params = json.loads(params_json)
        except Exception:
            logger.exception("Invalid params_json for %s", tool_id)
            self._send_run_result({"status": "error", "message": "参数解析失败"})
            return

        try:
            if not self.main_window or not hasattr(self.main_window, "service_locator"):
                self._send_run_result({"status": "error", "message": "服务未就绪"})
                return

            sl = self.main_window.service_locator

            # 1. 获取 tool_engine
            tool_engine = getattr(sl, "tool_engine", None)
            if tool_engine is None:
                self._send_run_result({"status": "error", "message": "ToolEngine 未初始化"})
                return

            # 2. 获取当前项目
            pm = getattr(sl, "project_manager", None)
            if pm is None or pm.current_project is None:
                self._send_run_result({"status": "no_project", "message": "请先选择或创建项目"})
                return

            # 3. 获取工具描述符（用于输入/参数/数据库字段对齐）
            descriptor = self.plugin_registry.get_descriptor(tool_id)

            # 4. 样本选择：优先最近样本，无样本时自动创建
            sample_id = self._ensure_sample_id(sl, pm, params, descriptor)
            if not sample_id:
                self._send_run_result({"status": "no_sample", "message": "无法确定样本，请先创建项目样本"})
                return

            # 5. 输入导入：本地路径 -> 远端 raw -> data_id 列表
            input_data_ids = self._import_inputs(sl, pm, sample_id, descriptor, params)

            # 6. 参数/数据库路径组装
            run_params = self._extract_run_params(descriptor, params)
            database_paths = self._build_database_paths(tool_id, descriptor)
            database_paths.update(self._extract_database_paths(descriptor, params))
            self._validate_required_databases(descriptor, database_paths)

            # 7. 调用 tool_engine.execute()
            execution_id = tool_engine.execute(
                tool_id=tool_id,
                input_data_ids=input_data_ids,
                parameters=run_params,
                sample_id=sample_id,
                triggered_by="manual",
                database_paths=database_paths,
            )

            logger.info("工具已提交执行: tool=%s execution_id=%s sample=%s", tool_id, execution_id, sample_id)
            self._send_run_result(
                {
                    "status": "ok",
                    "execution_id": execution_id,
                    "sample_id": sample_id,
                    "message": f"任务已提交 ({execution_id[:16]}...)",
                }
            )

        except ValueError as e:
            logger.warning("run_tool ValueError: %s", e)
            self._send_run_result({"status": "error", "message": str(e)})
        except Exception:
            logger.exception("Failed to start tool %s", tool_id)
            self._send_run_result({"status": "error", "message": "内部错误，请查看日志"})

    def _get_latest_sample_id(self, pm) -> str:
        """从 project_manager 的 DB 查询当前项目下最近一条样本 ID。"""
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

    def _build_database_paths(self, tool_id: str, descriptor: dict | None = None) -> dict:
        """读取 config.databases，按工具 YAML 中的 databases 声明组装路径映射。"""
        try:
            from config import get_config

            cfg_databases = get_config().get("databases", {})

            if not self.plugin_registry:
                return {}

            desc = descriptor or self.plugin_registry.get_descriptor(tool_id)
            db_decls = desc.get("databases", [])  # list[{id, param_name, ...}]

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

    def _ensure_sample_id(self, sl, pm, params: dict, descriptor: dict) -> str:
        """为检测执行选择或创建样本。"""
        explicit_sample_id = str(params.get("__sample_id", "")).strip()
        if explicit_sample_id:
            return explicit_sample_id

        sample_id = self._get_latest_sample_id(pm)
        if sample_id:
            return sample_id

        registry = getattr(sl, "data_registry", None)
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

    def _import_inputs(self, sl, pm, sample_id: str, descriptor: dict, params: dict) -> list[str]:
        """按插件 inputs 声明顺序导入本地输入文件。"""
        registry = getattr(sl, "data_registry", None)
        ssh = getattr(sl, "ssh_service", None)
        if registry is None or ssh is None or not getattr(ssh, "is_connected", False):
            raise ValueError("数据注册器或 SSH 未就绪")

        from core.data_importer import DataImporter

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
    def _extract_run_params(descriptor: dict, params: dict) -> dict:
        """只提取 tool.yaml parameters 声明的用户参数。"""
        run_params: dict = {}
        for p in descriptor.get("parameters", []):
            name = str(p.get("name", ""))
            if name and name in params:
                run_params[name] = params[name]
        return run_params

    @staticmethod
    def _extract_database_paths(descriptor: dict, params: dict) -> dict:
        """从前端参数中提取数据库路径（兼容 param_name/name 两种 key）。"""
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
    def _validate_required_databases(descriptor: dict, database_paths: dict) -> None:
        for decl in descriptor.get("databases", []):
            if not bool(decl.get("required", False)):
                continue
            var_name = str(decl.get("param_name", decl.get("name", ""))).strip()
            if var_name and not str(database_paths.get(var_name, "")).strip():
                raise ValueError(f"缺少必需数据库路径: {var_name}")

    def _send_run_result(self, result: dict) -> None:
        """通过 JS 回调向前端发送执行结果。"""
        if self.web_view is None:
            return
        try:
            result_json = json.dumps(result, ensure_ascii=False)
            js = f"if (typeof window._onRunResult === 'function') {{ window._onRunResult({result_json}); }}"
            self.web_view.page().runJavaScript(js)
        except Exception:
            logger.exception("发送 JS 回调失败")

    @pyqtSlot(result=str)
    def get_execution_history(self) -> str:
        if not self.main_window or not hasattr(self.main_window, "service_locator"):
            return json.dumps([], ensure_ascii=False)

        try:
            pm = self.main_window.service_locator.project_manager
            if not pm or not pm.current_project:
                return json.dumps([], ensure_ascii=False)

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
            history = [
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
            return json.dumps(history, ensure_ascii=False)
        except Exception:
            logger.exception("Failed to get execution history")
            return json.dumps([], ensure_ascii=False)

    @pyqtSlot(result=str)
    def get_integrated_workbench_config(self) -> str:
        """Return a stable initial config for the integrated analysis console."""
        config = self._base_integrated_workbench_config()
        live_primer_view = self._get_live_primer_design_view()
        if live_primer_view is not None:
            config["views"]["primer_design"] = live_primer_view
        else:
            default_remote_view = self._build_primer_view_from_result_dir(self._get_default_primer_result_dir())
            if default_remote_view is not None:
                default_remote_view["status"] = {
                    "state": "completed",
                    "label": "已加载默认远程结果",
                    "detail": "未找到历史执行记录，已自动读取服务器默认 primer 结果目录。",
                }
                config["views"]["primer_design"] = default_remote_view
        return json.dumps(config, ensure_ascii=False)

    @pyqtSlot(str, result=str)
    def get_remote_primer_results(self, remote_result_dir: str) -> str:
        view = self._build_primer_view_from_result_dir(remote_result_dir)
        if view is None:
            return json.dumps(
                {
                    "status": "error",
                    "message": "未能从该远程目录读取 primer_result_final_2.txt，请检查 SSH 连接和目录路径。",
                },
                ensure_ascii=False,
            )
        return json.dumps({"status": "ok", "view": view}, ensure_ascii=False)


class DetectionPageWeb(QFrame):
    """Web-based detection page."""

    def __init__(self, main_window=None, enable_webengine: bool = True):
        # Compatibility attr expected by legacy smoke tests.
        self.execution_history = []

        QFrame.__init__(self)
        self.setStyleSheet(f"background-color: {styles.COLOR_BG_PAGE};")
        self.main_window = main_window

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        if not enable_webengine:
            placeholder = QLabel("检测页 WebEngine 已在当前运行模式下禁用。")
            placeholder.setWordWrap(True)
            layout.addWidget(placeholder)
            self.web_view = None
            self.bridge = None
            self.channel = None
            return

        ensure_qt_webengine_ready()
        try:
            # Import can fail when QtWebEngine is imported too late in some environments.
            from PyQt6.QtWebChannel import QWebChannel
            from PyQt6.QtWebEngineCore import QWebEngineSettings
            from PyQt6.QtWebEngineWidgets import QWebEngineView
        except ImportError as exc:
            logger.warning("QtWebEngine unavailable: %s", exc)
            placeholder = QLabel("检测页 WebEngine 不可用，请通过 ui.main 启动应用或先初始化 QtWebEngine。")
            placeholder.setWordWrap(True)
            layout.addWidget(placeholder)
            self.web_view = None
            self.bridge = None
            self.channel = None
            return

        self.web_view = QWebEngineView()
        self.web_view.setStyleSheet("background: #fafbfc; border: none;")

        settings = self.web_view.settings()
        settings.setAttribute(QWebEngineSettings.WebAttribute.Accelerated2dCanvasEnabled, False)
        settings.setAttribute(QWebEngineSettings.WebAttribute.WebGLEnabled, False)
        self.web_view.page().setBackgroundColor(QColor("#fafbfc"))
        self.web_view.loadFinished.connect(self._on_load_finished)

        render_process_terminated = getattr(self.web_view.page(), "renderProcessTerminated", None)
        if render_process_terminated is not None:
            render_process_terminated.connect(self._on_render_process_terminated)

        plugin_registry = self._get_plugin_registry()
        self.bridge = ToolBridge(plugin_registry, main_window, web_view=self.web_view)

        self.channel = QWebChannel()
        self.channel.registerObject("bridge", self.bridge)
        self.web_view.page().setWebChannel(self.channel)

        assets_dir = Path(__file__).parent / "detection_page_assets"
        html_path = assets_dir / "index_galaxy.html"

        if html_path.exists():
            self.web_view.setUrl(QUrl.fromLocalFile(str(html_path)))
        else:
            logger.error("HTML file not found: %s", html_path)

        layout.addWidget(self.web_view)

    def _on_load_finished(self, ok: bool) -> None:
        if not ok:
            logger.error("Detection page failed to load in QWebEngineView")

    def _on_render_process_terminated(self, termination_status, exit_code: int) -> None:
        logger.error(
            "Detection page render process terminated: status=%s exit_code=%s",
            termination_status,
            exit_code,
        )

    def _get_plugin_registry(self):
        if self.main_window and hasattr(self.main_window, "service_locator"):
            return self.main_window.service_locator.plugin_registry
        logger.warning("Cannot get PluginRegistry")
        return None
