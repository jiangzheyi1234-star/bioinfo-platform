"""Detection page implemented with Qt WebEngine (with graceful fallback)."""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

from PyQt6.QtCore import QObject, QUrl, pyqtSignal, pyqtSlot
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


class DetectionPageWeb(QFrame):
    """Web-based detection page."""

    def __init__(self, main_window=None):
        # Compatibility attr expected by legacy smoke tests.
        self.execution_history = []

        QFrame.__init__(self)
        self.setStyleSheet(f"background-color: {styles.COLOR_BG_PAGE};")
        self.main_window = main_window

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

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

        settings = self.web_view.settings()
        settings.setAttribute(QWebEngineSettings.WebAttribute.Accelerated2dCanvasEnabled, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.WebGLEnabled, True)

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

    def _get_plugin_registry(self):
        if self.main_window and hasattr(self.main_window, "service_locator"):
            return self.main_window.service_locator.plugin_registry
        logger.warning("Cannot get PluginRegistry")
        return None
