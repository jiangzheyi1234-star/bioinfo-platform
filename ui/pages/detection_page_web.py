"""
病原检测页 - Web 版本
使用 QWebEngineView 实现响应式卡片布局
"""
from pathlib import Path
from PyQt6.QtCore import QObject, pyqtSlot, pyqtSignal, QUrl
from PyQt6.QtWidgets import QVBoxLayout, QFrame
# 延迟导入 QWebEngineView 和 QWebChannel，避免在模块加载时导入
import json
import logging

from ui.widgets import styles

logger = logging.getLogger(__name__)


class ToolBridge(QObject):
    """Python 与 JavaScript 通信桥接"""

    # Signal: Python → JavaScript
    tool_selected = pyqtSignal(str, arguments=['tool_id'])

    def __init__(self, plugin_registry, main_window=None):
        super().__init__()
        self.plugin_registry = plugin_registry
        self.main_window = main_window

    @pyqtSlot(result=str)
    def get_tools(self) -> str:
        """获取所有工具列表（JSON）"""
        if not self.plugin_registry:
            logger.warning("PluginRegistry 未初始化")
            return json.dumps([], ensure_ascii=False)

        tools = []
        try:
            for tool_id in self.plugin_registry.list_all_ids():
                desc = self.plugin_registry.get_descriptor(tool_id)
                tools.append({
                    'id': tool_id,
                    'name': desc.get('name', tool_id),
                    'category': desc.get('category', 'unknown'),
                    'description': desc.get('description', ''),
                    'version': desc.get('version', 'unknown'),
                    'inputs_count': len(desc.get('inputs', [])),
                    'params_count': len(desc.get('parameters', [])),
                    'db_count': len(desc.get('databases', []))
                })
        except Exception as e:
            logger.error(f"获取工具列表失败: {e}")

        logger.info(f"加载了 {len(tools)} 个工具")
        return json.dumps(tools, ensure_ascii=False)

    @pyqtSlot(str, result=str)
    def get_tool_descriptor(self, tool_id: str) -> str:
        """获取工具的完整描述符（JSON）"""
        if not self.plugin_registry:
            logger.warning("PluginRegistry 未初始化")
            return json.dumps({}, ensure_ascii=False)

        try:
            desc = self.plugin_registry.get_descriptor(tool_id)
            logger.info(f"获取工具描述符: {tool_id}")
            return json.dumps(desc, ensure_ascii=False)
        except Exception as e:
            logger.error(f"获取工具描述符失败: {e}")
            return json.dumps({}, ensure_ascii=False)

    @pyqtSlot(str)
    def select_tool(self, tool_id: str):
        """选择工具"""
        logger.info(f"选择工具: {tool_id}")
        self.tool_selected.emit(tool_id)

    @pyqtSlot(str, result=str)
    def browse_file(self, input_id: str) -> str:
        """浏览文件对话框"""
        from PyQt6.QtWidgets import QFileDialog

        logger.info(f"浏览文件: {input_id}")

        # 获取主窗口作为父窗口
        parent = self.main_window if self.main_window else None

        file_path, _ = QFileDialog.getOpenFileName(
            parent,
            "选择文件",
            "",
            "所有文件 (*.*)"
        )

        if file_path:
            logger.info(f"选择了文件: {file_path}")
            return file_path
        return ""

    @pyqtSlot(str, str)
    def run_tool(self, tool_id: str, params_json: str):
        """运行工具"""
        try:
            params = json.loads(params_json)
            logger.info(f"运行工具: {tool_id}, 参数: {params}")

            # TODO: 调用 ToolEngine 执行
            # 这里需要集成到实际的执行系统
            if self.main_window and hasattr(self.main_window, 'service_locator'):
                tool_engine = self.main_window.service_locator.tool_engine
                if tool_engine:
                    logger.info("TODO: 调用 ToolEngine 执行工具")
                    # tool_engine.execute(tool_id, params)
                else:
                    logger.warning("ToolEngine 未初始化")
            else:
                logger.warning("无法获取 ServiceLocator")

        except Exception as e:
            logger.error(f"运行工具失败: {e}")


class DetectionPageWeb(QFrame):
    """病原检测页 - Web 版本"""

    def __init__(self, main_window=None):
        # 在 __init__ 中导入，此时 QApplication 已经创建
        from PyQt6.QtWebEngineWidgets import QWebEngineView
        from PyQt6.QtWebChannel import QWebChannel
        from PyQt6.QtWebEngineCore import QWebEngineSettings

        # 不调用 super().__init__() 来避免创建默认布局
        QFrame.__init__(self)
        self.setStyleSheet(f"background-color: {styles.COLOR_BG_PAGE};")

        self.main_window = main_window

        # 创建 WebView
        self.web_view = QWebEngineView()

        # 优化渲染，防止黑色闪烁
        settings = self.web_view.settings()
        settings.setAttribute(QWebEngineSettings.WebAttribute.Accelerated2dCanvasEnabled, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.WebGLEnabled, True)

        # 创建通信桥接
        plugin_registry = self._get_plugin_registry()
        self.bridge = ToolBridge(plugin_registry, main_window)

        # 设置 QWebChannel
        self.channel = QWebChannel()
        self.channel.registerObject('bridge', self.bridge)
        self.web_view.page().setWebChannel(self.channel)

        # 加载 HTML（使用 Galaxy 风格）
        assets_dir = Path(__file__).parent / "detection_page_assets"
        html_path = assets_dir / "index_galaxy.html"

        if not html_path.exists():
            logger.error(f"HTML 文件不存在: {html_path}")
        else:
            logger.info(f"加载 HTML (Galaxy 风格): {html_path}")
            self.web_view.setUrl(QUrl.fromLocalFile(str(html_path)))

        # 布局
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.web_view)

    def _get_plugin_registry(self):
        """获取 PluginRegistry 实例"""
        if self.main_window and hasattr(self.main_window, "service_locator"):
            return self.main_window.service_locator.plugin_registry
        logger.warning("无法获取 PluginRegistry")
        return None

