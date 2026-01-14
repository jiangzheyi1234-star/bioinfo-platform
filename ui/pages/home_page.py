# ui/pages/home_page.py
from PyQt6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QWidget, QStackedWidget, QLabel, 
    QPushButton, QButtonGroup, QFileDialog, QLineEdit, QProgressBar, QFrame
)
from PyQt6.QtCore import Qt
from ui.page_base import BasePage
from ui.widgets import styles
from core.db_builder_worker import DbBuilderWorker
import os

class HomePage(BasePage):
    def __init__(self, main_window=None):
        super().__init__(" 项目首页")
        if hasattr(self, "label"): self.label.hide()
        self.main_window = main_window
        self.setStyleSheet(f"background-color: {styles.COLOR_BG_APP};")
        self._build_ui()

    def get_ssh_client(self):
        return self.main_window.get_ssh_service() if self.main_window else None

    def _build_ui(self):
        """完全参考 DetectionPage 的结构"""
        self.layout.setContentsMargins(30, 15, 30, 20)
        self.layout.setSpacing(10)

        # 1. 顶部标题
        header = QLabel("项目概览与自定义管理")
        header.setStyleSheet(styles.PAGE_HEADER_TITLE)
        self.layout.addWidget(header)

        # 2. 上方选项卡导航 (模仿 DetectionPage)
        self.nav_bar = QWidget()
        nav_layout = QHBoxLayout(self.nav_bar)
        nav_layout.setContentsMargins(0, 0, 0, 0)
        nav_layout.setSpacing(5)

        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)

        self.btn_db = self._create_nav_button("️ 自定义建库", 1)
        self.btn_info = self._create_nav_button(" 系统概览", 2)

        nav_layout.addWidget(self.btn_db)
        nav_layout.addWidget(self.btn_info)
        nav_layout.addStretch()
        self.layout.addWidget(self.nav_bar)

        # 细分割线
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet("background-color: #e1eefb; max-height: 1px; border:none;")
        self.layout.addWidget(line)

        # 3. 下方内容区
        self.content_stack = QStackedWidget()
        self._setup_stack_pages()
        self.layout.addWidget(self.content_stack)

        self.btn_db.setChecked(True)
        self.content_stack.setCurrentIndex(1)

    def _create_nav_button(self, text, index):
        """直接复用 DetectionPage 的按钮逻辑和样式"""
        btn = QPushButton(text)
        btn.setCheckable(True)
        btn.setAutoExclusive(True)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setStyleSheet("""
            QPushButton {
                background-color: #f8fbff; border: 1px solid #dcebfa; border-radius: 6px;
                padding: 6px 20px; color: #4a6a8a; font-size: 13px; font-weight: 500;
            }
            QPushButton:hover { background-color: #f0f7ff; border-color: #1890ff; }
            QPushButton:checked { background-color: #1890ff; color: white; border-color: #1890ff; }
        """)
        btn.clicked.connect(lambda: self.content_stack.setCurrentIndex(index))
        self.nav_group.addButton(btn)
        return btn

    def _setup_stack_pages(self):
        # 页面 0: 欢迎
        self.welcome_page = QLabel("请选择功能模块...")
        self.welcome_page.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        # 页面 1: 建库工作流 (参考 DetectionPage 的三步走)
        self.db_page = QWidget()
        self._init_db_workflow_ui()

        # 页面 2: 概览
        self.info_page = QLabel("系统运行状态监测（待实现）")
        self.info_label_style = "color: #90adca; font-size: 14px;"
        self.info_page.setStyleSheet(self.info_label_style)
        self.info_page.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.content_stack.addWidget(self.welcome_page)
        self.content_stack.addWidget(self.db_page)
        self.content_stack.addWidget(self.info_page)

    def _init_db_workflow_ui(self):
        """参考 DetectionPage 的卡片式三步工作流"""
        layout = QVBoxLayout(self.db_page)
        layout.setContentsMargins(0, 10, 0, 0)
        layout.setSpacing(18)

        # 上方：步骤 1 和 步骤 2 (横向)
        top_row = QHBoxLayout()
        top_row.setSpacing(18)

        # 步骤 1: 文件选择卡片
        self.card_file = QFrame()
        self.card_file.setStyleSheet(styles.CARD_FRAME("Card1"))
        v1 = QVBoxLayout(self.card_file)
        v1.addWidget(QLabel("步骤 1：选择参考序列", styleSheet=styles.CARD_TITLE))
        self.file_path_edit = QLineEdit()
        self.file_path_edit.setReadOnly(True)
        self.file_path_edit.setStyleSheet(styles.INPUT_LINEEDIT)
        self.btn_browse = QPushButton("浏览文件")
        self.btn_browse.setStyleSheet(styles.BUTTON_LINK_PRIMARY)
        self.btn_browse.clicked.connect(self._on_browse_fasta)
        v1.addWidget(self.file_path_edit)
        v1.addWidget(self.btn_browse)
        v1.addStretch()

        # 步骤 2: 命名卡片
        self.card_name = QFrame()
        self.card_name.setStyleSheet(styles.CARD_FRAME("Card2"))
        v2 = QVBoxLayout(self.card_name)
        v2.addWidget(QLabel("步骤 2：数据库命名", styleSheet=styles.CARD_TITLE))
        self.db_name_input = QLineEdit()
        self.db_name_input.setPlaceholderText("例如: virus_db_v1")
        self.db_name_input.setStyleSheet(styles.INPUT_LINEEDIT)
        v2.addWidget(self.db_name_input)
        v2.addWidget(QLabel("仅限英文、数字和下划线", styleSheet=styles.LABEL_HINT))
        v2.addStretch()

        top_row.addWidget(self.card_file, 1)
        top_row.addWidget(self.card_name, 1)
        layout.addLayout(top_row)

        # 下方：步骤 3 运行卡片
        self.card_run = QFrame()
        self.card_run.setStyleSheet(styles.CARD_FRAME("Card3"))
        v3 = QVBoxLayout(self.card_run)
        v3.addWidget(QLabel("步骤 3：构建与验证", styleSheet=styles.CARD_TITLE))
        
        self.status_label = QLabel("等待参数准备...")
        self.status_label.setStyleSheet(styles.LABEL_HINT)
        v3.addWidget(self.status_label)

        self.pbar = QProgressBar()
        self.pbar.setFixedHeight(6)
        self.pbar.setTextVisible(False)
        self.pbar.setStyleSheet("QProgressBar { border-radius: 3px; background: #eee; } QProgressBar::chunk { background: #1890ff; }")
        self.pbar.hide()
        v3.addWidget(self.pbar)

        self.run_btn = QPushButton("开始构建数据库")
        self.run_btn.setStyleSheet(styles.BUTTON_PRIMARY)
        self.run_btn.setFixedHeight(42)
        v3.addWidget(self.run_btn)
        
        self.result_info = QLabel("")
        self.result_info.setStyleSheet("color: #1890ff; font-size: 12px;")
        self.result_info.setWordWrap(True)
        v3.addWidget(self.result_info)
        v3.addStretch()

        layout.addWidget(self.card_run, 2)

        # 绑定逻辑
        self.run_btn.clicked.connect(self._on_start_build)

    def _on_browse_fasta(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择参考序列", "", "FASTA (*.fasta *.fa *.fna)")
        if path: self.file_path_edit.setText(path)

    def _on_start_build(self):
        """参考 DetectionPage 的锁死和异步逻辑"""
        local_fasta = self.file_path_edit.text()
        db_name = self.db_name_input.text().strip()

        if not local_fasta or not db_name:
            self.status_label.setText(" 请先完成步骤 1 和 步骤 2")
            return

        if not self.get_ssh_client():
            self.status_label.setText(" 错误：SSH 未连接")
            return

        # 锁死前两步交互
        self.card_file.setEnabled(False)
        self.card_name.setEnabled(False)
        self.run_btn.setEnabled(False)
        
        self.worker = DbBuilderWorker(self.get_ssh_client, local_fasta, db_name)
        self.worker.progress.connect(self.status_label.setText)
        self.worker.finished.connect(self._on_build_finished)
        
        self.pbar.show()
        self.pbar.setRange(0, 0)
        self.worker.start()

    def _on_build_finished(self, success, msg, db_path):
        # 恢复交互
        self.card_file.setEnabled(True)
        self.card_name.setEnabled(True)
        self.run_btn.setEnabled(True)
        self.pbar.hide()
        
        self.status_label.setText(msg)
        if success:
            self.result_info.setText(f" 远程路径：{db_path}\n您现在可以在‘资源确认’步骤中使用此路径。")
        else:
            self.result_info.setText(f" 详情：{msg}")