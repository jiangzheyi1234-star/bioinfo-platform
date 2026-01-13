from PyQt6.QtWidgets import QMainWindow, QWidget, QHBoxLayout, QListWidget, QStackedWidget, QListWidgetItem
from ui.pages.settings_page import SettingsPage
from core.ssh_service import SSHService

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("H2OMeta 宏基因组平台")
        self.resize(1100, 750)
        # 全局背景浅蓝色
        self.setStyleSheet("background-color: #f4f9ff;")
        self.init_ui()

    def init_ui(self):
        central = QWidget(); self.setCentralWidget(central)
        layout = QHBoxLayout(central); layout.setContentsMargins(0, 0, 0, 0); layout.setSpacing(0)

        # 侧边栏
        self.sidebar = QListWidget()
        self.sidebar.setFixedWidth(200)
        self.sidebar.setStyleSheet("""
            QListWidget { background: white; border: none; border-right: 1px solid #e1eefb; padding-top: 30px; outline: none; }
            QListWidget::item { height: 50px; padding-left: 20px; margin: 5px 12px; border-radius: 8px; color: #595959; }
            QListWidget::item:hover { background: #f0f7ff; color: #1890ff; }
            QListWidget::item:selected { background: #e6f7ff; color: #1890ff; border-left: 4px solid #1890ff; font-weight: bold; }
        """)

        # 预加载所有页面
        self.content = QStackedWidget()
        self.content.addWidget(QWidget())  # Index 0: 首页
        self.content.addWidget(QWidget())  # Index 1: 监测
        # 实例化设置页并挂到主窗口上，方便后续访问
        self.settings_page = SettingsPage()
        self.content.addWidget(self.settings_page)  # Index 2: 设置

        # 在设置页创建好之后，基于其 get_active_client 创建共享的 SSHService
        self.ssh_service = SSHService(self.settings_page.get_active_client)

        # 严格三项导航
        self.sidebar.addItem(QListWidgetItem("   项目首页"))
        self.sidebar.addItem(QListWidgetItem("   病原体监测"))
        self.sidebar.addItem(QListWidgetItem("   系统设置"))

        self.sidebar.currentRowChanged.connect(self.content.setCurrentIndex)
        layout.addWidget(self.sidebar); layout.addWidget(self.content)
        self.sidebar.setCurrentRow(0)

    def get_ssh_service(self) -> SSHService:
        """对外提供 SSHService，便于其他模块复用同一个 SSH 连接。"""
        return self.ssh_service
