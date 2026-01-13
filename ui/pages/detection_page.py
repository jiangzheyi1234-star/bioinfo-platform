from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QFrame, QHBoxLayout, QVBoxLayout, QWidget, QStackedWidget, QLabel,
    QPushButton, QButtonGroup
)

from ui.page_base import BasePage
from ui.widgets import styles


class DetectionPage(BasePage):
    """病原体检测页面：采用上下布局，上方功能导航区（选项卡式），下方内容展示区。"""

    def __init__(self):
        super().__init__("🧫 病原体检测")
        if hasattr(self, "label"):
            self.label.hide()

        self.setStyleSheet(f"background-color: {styles.COLOR_BG_APP};")
        self._build_ui()

    def _build_ui(self):
        # 页面整体布局参数
        self.layout.setContentsMargins(30, 15, 30, 20)
        self.layout.setSpacing(10)

        # 顶部标题
        header = QLabel("病原体检测")
        header.setStyleSheet(styles.PAGE_HEADER_TITLE)
        self.layout.addWidget(header)

        # 上方：选项卡式功能切换区 (Top Navigation)
        self.nav_bar = QWidget()
        nav_layout = QHBoxLayout(self.nav_bar)
        nav_layout.setContentsMargins(0, 0, 0, 0)
        nav_layout.setSpacing(5)  # 按钮间距紧凑

        # 使用 QButtonGroup 管理按钮的互斥高亮逻辑
        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)

        # 创建功能按钮（无图标、压缩尺寸、带高亮逻辑）
        self.btn_blast = self._create_nav_button("🧬 BLASTN 比对", 1)
        self.btn_other = self._create_nav_button("🔬 其他分析", 2)

        nav_layout.addWidget(self.btn_blast)
        nav_layout.addWidget(self.btn_other)
        nav_layout.addStretch()
        self.layout.addWidget(self.nav_bar)

        # 细分割线
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet("background-color: #e1eefb; max-height: 1px; border:none;")
        self.layout.addWidget(line)

        # 下方：对应功能的操作页面 (Content Area)
        self.content_stack = QStackedWidget()
        self.layout.addWidget(self.content_stack)

        # 初始化各个功能页面
        self._setup_stack_pages()

        # 默认选中第一个功能
        self.btn_blast.setChecked(True)
        self.content_stack.setCurrentIndex(1)

    def _create_nav_button(self, text: str, index: int):
        """创建具备高亮和切换功能的精简按钮"""
        btn = QPushButton(text)
        btn.setCheckable(True)  # 开启可选状态
        btn.setAutoExclusive(True)  # 开启自动互斥（同组内只能选一个）
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        
        # 样式：未选中时浅蓝色调，选中时蓝色高亮
        btn.setStyleSheet("""
            QPushButton {
                background-color: #f8fbff;
                border: 1px solid #dcebfa;
                border-radius: 6px;
                padding: 6px 20px;
                color: #4a6a8a;
                font-size: 13px;
                font-weight: 500;
            }
            QPushButton:hover {
                background-color: #f0f7ff;
                border-color: #1890ff;
            }
            QPushButton:checked {
                background-color: #1890ff;
                color: white;
                border-color: #1890ff;
            }
        """)
        
        # 点击后直接切换堆栈窗口，无需返回键逻辑
        btn.clicked.connect(lambda: self.content_stack.setCurrentIndex(index))
        self.nav_group.addButton(btn)
        return btn

    def _setup_stack_pages(self):
        """配置下方内容区的各个子页面"""
        # 页面 0: 占位/欢迎
        self.welcome_page = QLabel("请选择工具...")
        self.welcome_page.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.welcome_page.setStyleSheet("color: #90adca; font-size: 14px;")
        
        # 页面 1: BLAST 操作页
        self.blast_page = QWidget()
        self._init_blast_workflow_ui()
        
        # 页面 2: 其他分析页
        self.other_page = QWidget()
        self._init_other_workflow_ui()

        self.content_stack.addWidget(self.welcome_page)  # Index 0
        self.content_stack.addWidget(self.blast_page)    # Index 1
        self.content_stack.addWidget(self.other_page)    # Index 2

    def _init_blast_workflow_ui(self):
        """BLAST 操作界面的具体布局逻辑入口"""
        layout = QVBoxLayout(self.blast_page)
        layout.setContentsMargins(0, 10, 0, 0)
        layout.setSpacing(12)

        # BLAST 详情内容占位符
        placeholder = QLabel("BLAST 详情页（待实现）")
        placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        placeholder.setStyleSheet(styles.LABEL_MUTED)
        layout.addWidget(placeholder, 1)

    def _init_other_workflow_ui(self):
        """其他分析操作界面的具体布局逻辑入口"""
        layout = QVBoxLayout(self.other_page)
        layout.setContentsMargins(0, 10, 0, 0)
        layout.setSpacing(12)

        # 其他分析详情内容占位符
        placeholder = QLabel("其他分析详情页（待实现）")
        placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        placeholder.setStyleSheet(styles.LABEL_MUTED)
        layout.addWidget(placeholder, 1)