from PyQt6.QtWidgets import QMainWindow, QWidget, QHBoxLayout, QListWidget, QStackedWidget, QListWidgetItem
from ui.pages import SettingsPage, DetectionPage

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
        
        # 首页占位
        self.home_page = QWidget()
        self.content.addWidget(self.home_page)  # Index 0

        # 病原体检测页 - 传递 MainWindow 实例
        self.detection_page = DetectionPage(main_window=self)
        self.content.addWidget(self.detection_page)  # Index 1

        # 设置页
        self.settings_page = SettingsPage()
        self.content.addWidget(self.settings_page)  # Index 2

        # 导航与堆栈严格对应
        self.sidebar.addItem(QListWidgetItem("   项目首页"))    # idx 0
        self.sidebar.addItem(QListWidgetItem("   病原体检测"))  # idx 1
        self.sidebar.addItem(QListWidgetItem("   系统设置"))    # idx 2

        self.sidebar.currentRowChanged.connect(self.content.setCurrentIndex)
        layout.addWidget(self.sidebar); layout.addWidget(self.content)
        self.sidebar.setCurrentRow(0)

    def get_ssh_service(self):
        """获取 SSH 服务实例，优先从设置页面获取"""
        if hasattr(self, 'settings_page') and self.settings_page:
            return self.settings_page.get_active_client()
        return None