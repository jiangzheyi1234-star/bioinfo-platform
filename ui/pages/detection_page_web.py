"""Detection page implemented with Qt WebEngine (with graceful fallback)."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from PyQt6.QtCore import QObject, QUrl, pyqtSignal, pyqtSlot
from PyQt6.QtWidgets import QFrame, QLabel, QVBoxLayout

from ui.qt_bootstrap import ensure_qt_webengine_ready
from ui.widgets import styles

logger = logging.getLogger(__name__)


class ToolBridge(QObject):
    """Bridge between Python and JavaScript via QWebChannel."""

    tool_selected = pyqtSignal(str, arguments=["tool_id"])

    def __init__(self, plugin_registry, main_window=None):
        super().__init__()
        self.plugin_registry = plugin_registry
        self.main_window = main_window

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
        try:
            params = json.loads(params_json)
        except Exception:
            logger.exception("Invalid params_json for %s", tool_id)
            return

        try:
            if self.main_window and hasattr(self.main_window, "service_locator"):
                tool_engine = self.main_window.service_locator.tool_engine
                if tool_engine:
                    logger.info("Tool execution hook pending: %s %s", tool_id, params)
        except Exception:
            logger.exception("Failed to start tool %s", tool_id)

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
        self.bridge = ToolBridge(plugin_registry, main_window)

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
