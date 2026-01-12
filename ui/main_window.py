from PyQt6.QtWidgets import QMainWindow, QWidget, QHBoxLayout, QListWidget, QStackedWidget, QListWidgetItem
from ui.pages.settings_page import SettingsPage

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
        self.content.addWidget(QWidget()) # Index 0: 首页
        self.content.addWidget(QWidget()) # Index 1: 监测
        self.content.addWidget(SettingsPage()) # Index 2: 设置 (已预实例化)

        # 严格三项导航
        self.sidebar.addItem(QListWidgetItem("   项目首页"))
        self.sidebar.addItem(QListWidgetItem("   病原体监测"))
        self.sidebar.addItem(QListWidgetItem("   系统设置"))

        self.sidebar.currentRowChanged.connect(self.content.setCurrentIndex)
        layout.addWidget(self.sidebar); layout.addWidget(self.content)
        self.sidebar.setCurrentRow(0)