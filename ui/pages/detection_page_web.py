"""Detection page implemented with Qt WebEngine (with graceful fallback)."""

from __future__ import annotations

import json
import logging
import os
import tarfile
import zipfile
from pathlib import Path

from PyQt6.QtCore import QObject, QUrl, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QColor, QDesktopServices
from PyQt6.QtWidgets import QFrame, QLabel, QVBoxLayout

from core.execution.tool_bridge_service import ToolBridgeService
from ui.qt_bootstrap import ensure_qt_webengine_ready
from ui.widgets import styles

logger = logging.getLogger(__name__)


class ToolBridge(QObject):
    """Bridge between Python and JavaScript via QWebChannel.

    薄壳层：仅负责信号转发和 JS 回调，后端逻辑委托给 ToolBridgeService。
    """

    tool_selected = pyqtSignal(str, arguments=["tool_id"])

    def __init__(self, plugin_registry, main_window=None, web_view=None):
        super().__init__()
        self.plugin_registry = plugin_registry
        self.main_window = main_window
        self.web_view = web_view

        sl = self._get_service_locator()
        self._service = ToolBridgeService(service_locator=sl, plugin_registry=plugin_registry)

    def _get_service_locator(self):
        if self.main_window and hasattr(self.main_window, "service_locator"):
            return self.main_window.service_locator
        return None

    @pyqtSlot(result=str)
    def get_tools(self) -> str:
        tools = self._service.get_tools()
        return json.dumps(tools, ensure_ascii=False)

    @pyqtSlot(str, result=str)
    def get_tool_descriptor(self, tool_id: str) -> str:
        desc = self._service.get_tool_descriptor(tool_id)
        return json.dumps(desc, ensure_ascii=False)

    @pyqtSlot(str)
    def select_tool(self, tool_id: str):
        self.tool_selected.emit(tool_id)

    @pyqtSlot(str, result=str)
    @pyqtSlot(str, str, result=str)
    @pyqtSlot(str, str, str, result=str)
    def browse_file(
        self,
        input_id: str,
        file_filter: str = "所有文件 (*.*)",
        validator: str = "",
    ) -> str:
        from PyQt6.QtWidgets import QFileDialog

        parent = self.main_window if self.main_window else None
        selected_filter = file_filter or "所有文件 (*.*)"
        file_path, _ = QFileDialog.getOpenFileName(parent, "选择文件", "", selected_filter)
        if not file_path:
            return json.dumps({"path": "", "error": ""}, ensure_ascii=False)

        error_message = ""
        if validator == "primer_genomes_bundle":
            error_message = self._validate_primer_genomes_bundle(file_path)

        return json.dumps({"path": file_path, "error": error_message}, ensure_ascii=False)

    @staticmethod
    def _validate_primer_genomes_bundle(file_path: str) -> str:
        path = str(file_path or "")
        lower_path = path.lower()
        allowed_fasta_suffixes = (".fasta", ".fna", ".fa")

        if lower_path.endswith(allowed_fasta_suffixes):
            return ""

        def _is_fasta_name(name: str) -> bool:
            lower_name = str(name or "").lower()
            return lower_name.endswith(allowed_fasta_suffixes)

        if lower_path.endswith(".zip"):
            try:
                with zipfile.ZipFile(path) as zf:
                    for member_name in zf.namelist():
                        if member_name.endswith("/"):
                            continue
                        if _is_fasta_name(member_name):
                            return ""
                return "压缩包中未找到 .fasta/.fna/.fa 文件"
            except Exception as exc:
                logger.warning("读取 ZIP 失败: %s", exc)
                return "压缩包读取失败，请检查文件是否损坏"

        if lower_path.endswith((".tar.gz", ".tgz", ".tar")):
            try:
                with tarfile.open(path) as tf:
                    for member in tf.getmembers():
                        if not member.isfile():
                            continue
                        if _is_fasta_name(member.name):
                            return ""
                return "压缩包中未找到 .fasta/.fna/.fa 文件"
            except Exception as exc:
                logger.warning("读取 TAR 失败: %s", exc)
                return "压缩包读取失败，请检查文件是否损坏"

        return "仅支持 .zip/.tar/.tar.gz/.tgz 或单个 .fasta/.fna/.fa 文件"

    @pyqtSlot(str, result=str)
    def browse_remote_file(self, input_id: str) -> str:
        """打开远程文件浏览器，供数据库路径选择使用。"""
        from ui.widgets.remote_file_dialog import RemoteFileDialog

        sl = self._get_service_locator()
        if sl is None:
            return json.dumps({"path": "", "error": "服务未初始化"})

        ssh = sl.ssh_service
        if not ssh or not getattr(ssh, "is_connected", False):
            return json.dumps({"path": "", "error": "SSH 未连接"})

        parent = self.main_window if self.main_window else None
        dialog = RemoteFileDialog(ssh, parent=parent)
        if dialog.exec() == dialog.DialogCode.Accepted:
            return json.dumps({"path": dialog.selected_path(), "error": ""})
        return json.dumps({"path": "", "error": ""})

    @pyqtSlot(result=str)
    def browse_directory(self) -> str:
        from PyQt6.QtWidgets import QFileDialog

        parent = self.main_window if self.main_window else None
        directory = QFileDialog.getExistingDirectory(parent, "选择文件夹")
        return json.dumps({"path": directory or "", "error": ""}, ensure_ascii=False)

    @pyqtSlot(str, result=str)
    def scan_local_database_resources(self, directory: str) -> str:
        root = Path(str(directory or "").strip())
        if not root.exists() or not root.is_dir():
            return json.dumps({"status": "error", "message": "文件夹不存在"}, ensure_ascii=False)

        fasta_suffixes = {".fasta", ".fa", ".fna", ".fas"}
        blast_suffixes = {".nin", ".nsq", ".nhr", ".ndb", ".njs", ".not", ".ntf", ".nto"}
        resources = []

        try:
            for item in sorted(root.iterdir(), key=lambda p: (p.is_file(), p.name.lower())):
                if item.name.startswith("."):
                    continue

                if item.is_dir():
                    child_files = [p for p in item.iterdir() if p.is_file()]
                    fasta_count = sum(1 for p in child_files if p.suffix.lower() in fasta_suffixes)
                    blast_count = sum(1 for p in child_files if p.suffix.lower() in blast_suffixes)
                    if fasta_count == 0 and blast_count == 0 and not child_files:
                        continue
                    resources.append(
                        {
                            "name": item.name,
                            "path": str(item),
                            "type": "directory",
                            "description": f"目录，包含 {len(child_files)} 个文件",
                            "stats": {
                                "fasta_count": fasta_count,
                                "blast_index_count": blast_count,
                            },
                        }
                    )
                    continue

                suffix = item.suffix.lower()
                if suffix not in fasta_suffixes and suffix not in blast_suffixes:
                    continue
                resources.append(
                    {
                        "name": item.name,
                        "path": str(item),
                        "type": "file",
                        "description": "FASTA 文件" if suffix in fasta_suffixes else "BLAST 索引文件",
                        "stats": {
                            "size_bytes": item.stat().st_size,
                        },
                    }
                )
        except Exception as exc:
            logger.exception("Failed to scan local database directory: %s", directory)
            return json.dumps({"status": "error", "message": str(exc)}, ensure_ascii=False)

        return json.dumps({"status": "ok", "directory": str(root), "resources": resources}, ensure_ascii=False)

    @pyqtSlot(str, str)
    def run_tool(self, tool_id: str, params_json: str):
        try:
            params = json.loads(params_json)
        except Exception:
            logger.exception("Invalid params_json for %s", tool_id)
            self._send_run_result({"status": "error", "message": "参数解析失败"})
            return

        result = self._service.execute_tool(tool_id, params)
        self._send_run_result(
            {
                "status": result.status,
                "execution_id": result.execution_id,
                "sample_id": result.sample_id,
                "message": result.message,
            }
        )

    def _send_run_result(self, result: dict) -> None:
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
        history = self._service.get_execution_history()
        return json.dumps(history, ensure_ascii=False)

    @pyqtSlot(str, result=str)
    def delete_execution_history(self, execution_id: str) -> str:
        result = self._service.delete_execution_history(execution_id)
        return json.dumps(result, ensure_ascii=False)

    @pyqtSlot(result=str)
    def get_integrated_workbench_config(self) -> str:
        config = self._service.get_integrated_workbench_config()
        return json.dumps(config, ensure_ascii=False)

    @pyqtSlot(str, result=str)
    def get_remote_primer_results(self, remote_result_dir: str) -> str:
        result = self._service.get_remote_primer_results(remote_result_dir)
        return json.dumps(result, ensure_ascii=False)

    @pyqtSlot(str, result=str)
    def get_primer_results_for_execution(self, execution_id: str) -> str:
        result = self._service.get_primer_results_for_execution(execution_id)
        return json.dumps(result, ensure_ascii=False)

    @pyqtSlot(str, result=str)
    def get_multiplex_results_for_execution(self, execution_id: str) -> str:
        result = self._service.get_multiplex_results_for_execution(execution_id)
        return json.dumps(result, ensure_ascii=False)

    @pyqtSlot(str, result=str)
    def get_targeted_seq_results_for_execution(self, execution_id: str) -> str:
        result = self._service.get_targeted_seq_results_for_execution(execution_id)
        return json.dumps(result, ensure_ascii=False)

    @pyqtSlot(str, result=str)
    def get_fastp_results_for_execution(self, execution_id: str) -> str:
        result = self._service.get_fastp_results_for_execution(execution_id)
        return json.dumps(result, ensure_ascii=False)

    @pyqtSlot(str, result=str)
    def get_execution_remote_status(self, execution_id: str) -> str:
        result = self._service.get_execution_remote_status(execution_id)
        return json.dumps(result, ensure_ascii=False)

    @pyqtSlot(result=str)
    def get_configured_databases(self) -> str:
        """返回设置中已配置的数据库路径，供 modal 下拉选择。"""
        try:
            from config import get_config
            cfg_dbs = get_config().get("databases", {})
            # {key: path} → [{key, path, label}]
            result = []
            for key, path in cfg_dbs.items():
                if path:
                    result.append({"key": key, "path": path, "label": f"{key}: {path}"})
            return json.dumps(result, ensure_ascii=False)
        except Exception:
            return "[]"

    @pyqtSlot(str, result=str)
    def open_local_file(self, local_path: str) -> str:
        path = Path(str(local_path or "").strip())
        if not path.exists():
            return json.dumps({"status": "error", "message": "本地结果文件不存在"}, ensure_ascii=False)

        try:
            if os.name == "nt":
                os.startfile(str(path))  # type: ignore[attr-defined]
            else:
                ok = QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
                if not ok:
                    raise RuntimeError("系统未能打开该文件")
        except Exception as exc:
            logger.exception("打开本地结果文件失败: %s", path)
            return json.dumps({"status": "error", "message": str(exc)}, ensure_ascii=False)

        return json.dumps({"status": "ok", "message": "文件已打开"}, ensure_ascii=False)



class DetectionPageWeb(QFrame):
    """Web-based detection page."""

    def __init__(self, main_window=None, enable_webengine: bool = True):
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
        self.web_view.setStyleSheet("background: #F1F5F9; border: none;")

        settings = self.web_view.settings()
        settings.setAttribute(QWebEngineSettings.WebAttribute.Accelerated2dCanvasEnabled, False)
        settings.setAttribute(QWebEngineSettings.WebAttribute.WebGLEnabled, False)
        self.web_view.page().setBackgroundColor(QColor("#F1F5F9"))
        self.web_view.loadFinished.connect(self._on_load_finished)

        render_process_terminated = getattr(self.web_view.page(), "renderProcessTerminated", None)
        if render_process_terminated is not None:
            render_process_terminated.connect(self._on_render_process_terminated)

        plugin_registry = self._get_plugin_registry()
        self.bridge = ToolBridge(plugin_registry, main_window, web_view=self.web_view)

        self.channel = QWebChannel()
        self.channel.registerObject("bridge", self.bridge)
        self.web_view.page().setWebChannel(self.channel)

        from core.utils import get_app_root
        assets_dir = get_app_root() / "ui" / "pages" / "detection_page_assets"
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
