# ui/main_window.py
from PyQt6.QtWidgets import QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QListWidget, QStackedWidget, QListWidgetItem
from PyQt6.QtCore import Qt
from page import HomePage, DetectionPage
from ui.pages.settings_page import SettingsPage


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Metagenome Pathogen Analyzer")
        self.resize(1100, 700)

        # 整体布局：水平
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.main_layout = QHBoxLayout(self.central_widget)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)

        # --- 左侧导航栏 ---
        self.sidebar = QListWidget()
        self.sidebar.setFixedWidth(200)
        # 样式：参考你图中的深蓝色调
        self.sidebar.setStyleSheet("""
            QListWidget {
                background-color: #314659;
                border: none;
                outline: none;
            }
            QListWidget::item {
                color: #ffffff;
                height: 50px;
                padding-left: 15px;
                border-bottom: 1px solid #3e566b;
            }
            QListWidget::item:selected {
                background-color: #1890ff;
                border-left: 4px solid #ffffff;
            }
            QListWidget::item:hover {
                background-color: #435b70;
            }
        """)

        # --- 右侧内容区 ---
        self.content_stack = QStackedWidget()

        # 初始化页面
        self.page_home = HomePage()
        self.page_detect = DetectionPage()
        self.page_settings = SettingsPage()

        # 添加到堆栈容器
        self.content_stack.addWidget(self.page_home)  # 索引 0
        self.content_stack.addWidget(self.page_detect)  # 索引 1
        self.content_stack.addWidget(self.page_settings)  # 索引 2

        # 初始填充导航项
        self.add_nav_item("首页")
        self.add_nav_item("病原体监测")
        self.add_nav_item("设置")

        # 组合布局
        self.main_layout.addWidget(self.sidebar)
        self.main_layout.addWidget(self.content_stack)

        # 信号连接：列表切换带动内容切换
        self.sidebar.currentRowChanged.connect(self.content_stack.setCurrentIndex)
        self.sidebar.setCurrentRow(0)

    def add_nav_item(self, name):
        item = QListWidgetItem(name)
        item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.sidebar.addItem(item)